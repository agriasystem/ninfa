"""Smart Import: let the hotelier use the file they already have.

    file (CSV / Excel)  ->  NINFA reads the columns  ->  proposes what each one means
        ->  the person confirms or corrects  ->  NINFA checks it  ->  anteprima  ->  import
        ->  the configuration is remembered  ->  the next file of the same layout is recognised

Nothing here is new machinery: the file readers, the per-domain mapping rules, the validation, the
all-or-nothing import and the saved "mapping profile" are the import services' own. This module is
the part between the page and them:

* it READS a file (a few example values per column, how dates and numbers are written) and proposes
  a meaning for each column, deterministically (no AI, no network);
* it CHECKS a decision against the backend's own rules, so the page never decides what is required;
* it TRIES a decision on the whole file - every row validated exactly as the import will - and
  writes nothing;
* it builds the validated mapping an import is run with, and remembers it once the import has
  succeeded.

Everything is scoped by the request's `TenantContext` and property: a saved configuration belongs to
ONE data source of ONE property of ONE workspace and is reachable only through it.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.bookings.errors import BookingImportError
from app.modules.bookings.mapping import FormatOptions, header_index, normalize_header
from app.modules.bookings.normalization import DateOrder
from app.modules.bookings.parsers import SourceTable, detect_file_type, open_table
from app.modules.data_sources.column_profile import (
    ColumnSample,
    DateChoice,
    NumberStyle,
    date_order_of,
    date_pattern,
    looks_like_dates,
    number_style,
    sample_columns,
)
from app.modules.data_sources.domain_adapters import (
    ConfigFormat,
    DryRunData,
    FileDomain,
    StoredProfile,
    domain_adapter,
)
from app.modules.data_sources.errors import UnsupportedDomainError
from app.modules.data_sources.files import ImportProblem, problem_of_code
from app.modules.data_sources.mapping_types import (
    ColumnChoice,
    ColumnInfo,
    DryRun,
    DryRunStatus,
    FileInspection,
    FormatHint,
    InvalidRow,
    MappingCheck,
    MappingInput,
    MappingProblem,
    ProfileInfo,
    ProfileReason,
    ProfileStatus,
    RowProblemCount,
    SavedConfiguration,
    SuggestionLevel,
)
from app.modules.data_sources.source_learning import (
    Confirmation,
    Via,
    header_key,
    parse_learning,
    stored_learning,
    without_current,
)
from app.modules.data_sources.source_learning import remember_in as learn
from app.modules.data_sources.understanding_costs import category_question
from app.modules.data_sources.understanding_labor import label_question
from app.modules.data_sources.understanding_redaction import (
    guard_for_samples,
    personal_columns,
    redact_inspection,
)
from app.modules.data_sources.understanding_types import Question
from app.modules.document_understanding.layout import LayoutSpec
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import ImportJobRepository
from app.modules.ingestion.suggestions import SuggestionConfidence

logger = logging.getLogger(__name__)

# Codes of `MappingProblem`: what is wrong with a decision, in one stable word.
UNKNOWN_FIELD = "UNKNOWN_FIELD"
FIELD_USED_TWICE = "FIELD_USED_TWICE"
COLUMN_AND_VALUE = "COLUMN_AND_VALUE"
CONSTANT_NOT_ALLOWED = "CONSTANT_NOT_ALLOWED"
INVALID_CONSTANT = "INVALID_CONSTANT"
UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
DATES_MIXED = "DATES_MIXED"
NUMBERS_MIXED = "NUMBERS_MIXED"

_SHEET_REASON = "sheet_selection_required"

_LEVEL = {
    SuggestionConfidence.HIGH: SuggestionLevel.RECOGNIZED,
    SuggestionConfidence.MEDIUM: SuggestionLevel.TO_CHECK,
    SuggestionConfidence.LOW: SuggestionLevel.TO_CHECK,
}


def problem_of_error_code(code: object, details: object = None) -> ImportProblem:
    """Why a file cannot be read or imported, from an import service's error code (and details),
    in one stable word the page turns into a sentence."""
    text = str(getattr(code, "value", code) or "")
    suffix = text.partition("_")[2]
    info = details if isinstance(details, dict) else {}
    if suffix == "MAPPING_REQUIRED" and info.get("reason") == _SHEET_REASON:
        return ImportProblem.SHEET_REQUIRED
    if suffix in {"AMBIGUOUS_DATE_FORMAT", "AMBIGUOUS_NUMBER_FORMAT"}:
        return ImportProblem.FORMAT_UNCLEAR
    if suffix == "SOURCE_SCHEMA_CHANGED":
        if info.get("reason") == "mapped_columns_missing":
            return ImportProblem.PROFILE_NOT_USABLE
        return ImportProblem.MAPPING_INCOMPLETE  # the chosen sheet is not in the workbook
    if suffix in {"INVALID_MAPPING", "MAPPING_REQUIRED"}:
        return ImportProblem.MAPPING_INCOMPLETE
    return problem_of_code(code)


def problem_of_error(error: AppError) -> ImportProblem:
    """The same, from the error an import service raised."""
    code = getattr(error, "error_code", None) or error.code
    return problem_of_error_code(code, error.details)


@dataclass(frozen=True, slots=True)
class Formats:
    date_formats: dict[str, str]
    decimal_separator: str | None
    thousands_separator: str | None
    hints: tuple[FormatHint, ...]
    problems: tuple[MappingProblem, ...]
    # Something about how the file writes dates or numbers is neither proven by its values nor
    # chosen by the person: they must be asked.
    unresolved: bool = False


@dataclass(frozen=True, slots=True)
class Resolved:
    """A decision turned into the validated mapping an import (or a dry run) is run with."""

    config: Any | None = None
    documents: dict[str, dict[str, Any]] | None = None
    headers: tuple[str, ...] = ()
    problem: ImportProblem | None = None
    check: MappingCheck | None = None
    format_hints: tuple[FormatHint, ...] = ()
    needs_choice: bool = False


class SmartImportService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._jobs = ImportJobRepository(session, tenant)

    # --- the domain ---------------------------------------------------------------------------

    def domain(self, domain: DataSourceDomain) -> FileDomain:
        adapter = domain_adapter(domain, self._session, self._tenant)
        if adapter is None:
            raise UnsupportedDomainError()
        return adapter

    # --- reading a file -------------------------------------------------------------------------

    @staticmethod
    def read_table(
        content: bytes,
        filename: str,
        sheet_name: str | None = None,
        layout: LayoutSpec | None = None,
    ) -> SourceTable:
        """The file as a table (CSV or Excel). Raises the reader's own `BookingImportError`.

        With a `layout` the document's structure is understood first (title, totals, sections, a
        grid of days): the table is the one the importers will read."""
        detect_file_type(filename, content)
        return open_table(content, filename, FormatOptions(sheet_name=sheet_name, layout=layout))

    # --- the period of THIS file (never saved in a configuration) ---------------------------------

    @staticmethod
    def mapping_with_period(
        mapping: MappingInput | None, period_start: date | None
    ) -> MappingInput | None:
        """The decision, with the first day of the period this file is about (a grid of days)."""
        if mapping is None or mapping.layout is None or period_start is None:
            return mapping
        layout = mapping.layout.model_copy(update={"period_start": period_start})
        return mapping.model_copy(update={"layout": layout})

    @staticmethod
    def config_with_period(adapter: FileDomain, config: Any, period_start: date | None) -> Any:
        """The saved configuration, read for the week THIS file is about."""
        layout = adapter.format_of(config).layout
        if layout is None or period_start is None or layout.grid is None:
            return config
        options = config.format_options.model_copy(
            update={"layout": layout.model_copy(update={"period_start": period_start})}
        )
        return config.model_copy(update={"format_options": options})

    # --- 1. what NINFA finds in the file ----------------------------------------------------------

    def inspect(
        self,
        domain: DataSourceDomain,
        filename: str,
        content: bytes,
        sheet_name: str | None,
        source: DataSource | None,
        already_imported: bool,
    ) -> FileInspection:
        adapter = self.domain(domain)
        try:
            table = self.read_table(content, filename, sheet_name)
        except BookingImportError as error:
            problem = problem_of_error(error)
            if problem == ImportProblem.SHEET_REQUIRED:
                names = (error.details or {}).get("sheet_names", [])
                return FileInspection(
                    domain,
                    file_type="XLSX",
                    problem=problem,
                    requires_sheet_selection=True,
                    sheet_names=tuple(str(name) for name in names),
                    fields=tuple(adapter.fields),
                )
            return FileInspection(domain, problem=problem)

        samples = sample_columns(table)
        headers = list(table.headers)
        proposed = self._proposal(adapter, headers, samples)
        columns = tuple(
            self._column_info(adapter, sample, proposed.get(sample.header)) for sample in samples
        )
        decision = MappingInput(
            sheet_name=table.sheet_name,
            columns=[ColumnChoice(header=c.header, field=c.field) for c in columns],
        )
        complete = self.check(domain, decision).valid
        canonical = complete and all(
            normalize_header(c.header) == normalize_header(c.field)
            for c in columns
            if c.field is not None
        )
        profile = self._profile_info(adapter, source, table)
        # A column of people is never shown as an example, whatever its header says.
        personal = personal_columns(samples)
        columns = tuple(
            replace(column, examples=()) if column.position in personal else column
            for column in columns
        )
        return redact_inspection(
            FileInspection(
                domain,
                file_type="XLSX" if table.file_type == "xlsx" else "CSV",
                sheet_name=table.sheet_name,
                columns=columns,
                fields=tuple(adapter.fields),
                requirement_groups=tuple(adapter.groups),
                suggestion_complete=complete,
                already_canonical=canonical,
                profile=profile,
                already_imported=already_imported,
            ),
            guard_for_samples(samples, personal),
        )

    def _proposal(
        self, adapter: FileDomain, headers: list[str], samples: list[ColumnSample]
    ) -> dict[str, tuple[str, SuggestionLevel]]:
        """header -> (field, how sure). Names NINFA knows first; for the one date field of a
        domain, a column made only of dates is offered as a match to check."""
        proposed: dict[str, tuple[str, SuggestionLevel]] = {}
        for suggestion in adapter.suggest(headers):
            if suggestion.column is None or suggestion.confidence == SuggestionConfidence.NONE:
                continue
            proposed[suggestion.column] = (suggestion.field, _LEVEL[suggestion.confidence])
        if len(adapter.date_fields) == 1:
            (date_field,) = adapter.date_fields
            if all(field != date_field for field, _ in proposed.values()):
                candidates = [
                    sample.header
                    for sample in samples
                    if sample.header not in proposed
                    and adapter.excluded_reason(sample.header) is None
                    and looks_like_dates(sample.values)
                ]
                if len(candidates) == 1:
                    proposed[candidates[0]] = (date_field, SuggestionLevel.TO_CHECK)
        return proposed

    @staticmethod
    def _column_info(
        adapter: FileDomain,
        sample: ColumnSample,
        proposal: tuple[str, SuggestionLevel] | None,
    ) -> ColumnInfo:
        reason = adapter.excluded_reason(sample.header)
        text_values = [value for value in sample.values if isinstance(value, str)]
        order = date_order_of(sample.values) if text_values else None
        style = number_style(sample.values) if text_values else None
        return ColumnInfo(
            position=sample.position,
            header=sample.header,
            examples=sample.examples,
            field=None if reason is not None or proposal is None else proposal[0],
            level=None if reason is not None or proposal is None else proposal[1],
            not_used_reason=reason,
            date_order=order.value if order and order != DateOrder.UNKNOWN else None,
            number_style=style.value if style and style != NumberStyle.UNKNOWN else None,
        )

    # --- 2. checking a decision against the backend's own rules ---------------------------------

    def check(self, domain: DataSourceDomain, mapping: MappingInput) -> MappingCheck:
        """Is this decision enough to import, by the rules of the import service? No file needed."""
        adapter = self.domain(domain)
        problems, provided = self._structural_problems(adapter, mapping)
        missing = tuple(
            group for group in adapter.groups if not any(key in provided for key in group)
        )
        if not missing and not problems:
            documents = self._documents(adapter, mapping, _no_formats(), {})
            try:
                adapter.parse_config(documents)
            except (AppError, ValueError):
                problems.append(MappingProblem(INVALID_CONSTANT, tuple(sorted(mapping.constants))))
        return MappingCheck(
            valid=not missing and not problems, missing=missing, problems=tuple(problems)
        )

    @staticmethod
    def _structural_problems(
        adapter: FileDomain, mapping: MappingInput
    ) -> tuple[list[MappingProblem], set[str]]:
        known = {spec.key: spec for spec in adapter.fields}
        problems: list[MappingProblem] = []
        columns: dict[str, str] = {}
        reported: set[tuple[str, str]] = set()
        for choice in mapping.columns:
            if choice.field is None:
                continue
            if choice.field not in known:
                if (UNKNOWN_FIELD, choice.field) not in reported:
                    reported.add((UNKNOWN_FIELD, choice.field))
                    problems.append(MappingProblem(UNKNOWN_FIELD, (choice.field,)))
            elif choice.field in columns:
                if (FIELD_USED_TWICE, choice.field) not in reported:
                    reported.add((FIELD_USED_TWICE, choice.field))
                    problems.append(MappingProblem(FIELD_USED_TWICE, (choice.field,)))
            else:
                columns[choice.field] = choice.header
        provided = set(columns)
        for key in mapping.constants:
            spec = known.get(key)
            if spec is None or spec.constant is None:
                problems.append(MappingProblem(CONSTANT_NOT_ALLOWED, (key,)))
            elif key in columns:
                problems.append(MappingProblem(COLUMN_AND_VALUE, (key,)))
            else:
                provided.add(key)
        return problems, provided

    # --- 3. a decision becomes the validated mapping -----------------------------------------

    def resolve(
        self,
        adapter: FileDomain,
        mapping: MappingInput,
        table: SourceTable,
        preserved: dict[str, dict[str, Any]] | None = None,
    ) -> Resolved:
        """Turn the person's decision, read against THIS file, into the mapping an import runs
        with. Everything that cannot be decided from the file is reported, never guessed."""
        check = self.check(adapter.domain, mapping)
        if not check.valid:
            return Resolved(problem=ImportProblem.MAPPING_INCOMPLETE, check=check)
        index = header_index(table.headers)
        unknown = tuple(
            choice.header
            for choice in mapping.columns
            if choice.field is not None and normalize_header(choice.header) not in index
        )
        if unknown:
            problem = MappingProblem(UNKNOWN_COLUMN, unknown)
            return Resolved(
                problem=ImportProblem.MAPPING_INCOMPLETE,
                check=MappingCheck(False, problems=(problem,)),
            )
        formats = self._formats(adapter, mapping, sample_columns(table))
        if formats.problems:
            return Resolved(
                problem=ImportProblem.FORMAT_UNCLEAR,
                check=MappingCheck(False, problems=formats.problems),
                format_hints=formats.hints,
            )
        if formats.unresolved:
            return Resolved(format_hints=formats.hints, needs_choice=True)
        documents = self._documents(adapter, mapping, formats, preserved or {})
        try:
            config = adapter.parse_config(documents)
        except (AppError, ValueError):
            return Resolved(problem=ImportProblem.MAPPING_INCOMPLETE, check=check)
        return Resolved(
            config=config,
            documents=self._documents_to_keep(adapter, mapping, formats, preserved or {}),
            headers=tuple(table.headers),
            format_hints=formats.hints,
        )

    def _documents_to_keep(
        self,
        adapter: FileDomain,
        mapping: MappingInput,
        formats: "Formats",
        preserved: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """What a profile remembers of this decision: everything, except the dates of THIS file."""
        kept = mapping.model_copy(
            update={"layout": mapping.layout.for_profile() if mapping.layout else None}
        )
        return adapter.documents_of(
            adapter.parse_config(self._documents(adapter, kept, formats, preserved))
        )

    def _formats(
        self, adapter: FileDomain, mapping: MappingInput, samples: list[ColumnSample]
    ) -> Formats:
        """How the mapped date and amount columns are written: from what the values prove, from
        the person's choice where they do not."""
        by_key = {normalize_header(sample.header): sample for sample in samples}
        mapped: dict[str, ColumnSample] = {}
        for choice in mapping.columns:
            sample = by_key.get(normalize_header(choice.header))
            if choice.field is not None and sample is not None:
                mapped[choice.field] = sample

        position_of = {sample.header: sample.position for sample in samples}
        problems: list[MappingProblem] = []
        hints: list[FormatHint] = []
        date_formats: dict[str, str] = {}

        date_columns: list[str] = []
        proven_orders: set[str] = set()
        for key in sorted(adapter.date_fields):
            sample = mapped.get(key)
            if sample is None:
                continue
            order = date_order_of(sample.values)
            if order == DateOrder.CONFLICT:
                problems.append(MappingProblem(DATES_MIXED, (key,)))
            elif order in {DateOrder.DMY, DateOrder.MDY, DateOrder.AMBIGUOUS}:
                date_columns.append(sample.header)
                if order != DateOrder.AMBIGUOUS:
                    proven_orders.add(order.value)
        if len(proven_orders) > 1:
            problems.append(MappingProblem(DATES_MIXED, tuple(sorted(adapter.date_fields))))
        chosen: DateChoice | None = mapping.date_order
        if chosen is None and len(proven_orders) == 1:
            chosen = "DMY" if "DMY" in proven_orders else "MDY"  # one convention per file
        if date_columns:
            hints.append(
                FormatHint(
                    "DATE_ORDER",
                    proven=next(iter(proven_orders)) if len(proven_orders) == 1 else None,
                    columns=tuple(sorted(date_columns, key=position_of.__getitem__)),
                )
            )
        if chosen is not None:
            for key in sorted(adapter.date_fields):
                sample = mapped.get(key)
                if sample is None or sample.header not in date_columns:
                    continue
                pattern = date_pattern(sample.values, chosen)
                if pattern is None:
                    problems.append(MappingProblem(DATES_MIXED, (key,)))
                else:
                    date_formats[key] = pattern

        decimal: tuple[str, str] | None = None
        number_columns: list[str] = []
        styles: set[NumberStyle] = set()
        for key in sorted(adapter.decimal_fields):
            sample = mapped.get(key)
            if sample is None:
                continue
            style = number_style(sample.values)
            if style == NumberStyle.MIXED:
                problems.append(MappingProblem(NUMBERS_MIXED, (key,)))
            elif style != NumberStyle.UNKNOWN:
                number_columns.append(sample.header)
                styles.add(style)
        proven_style = styles - {NumberStyle.AMBIGUOUS}
        if len(proven_style) > 1:
            problems.append(MappingProblem(NUMBERS_MIXED, tuple(sorted(adapter.decimal_fields))))
        style_choice = mapping.decimal_style
        if style_choice is None and len(proven_style) == 1:
            style_choice = "COMMA" if NumberStyle.COMMA in proven_style else "POINT"
        if number_columns:
            hints.append(
                FormatHint(
                    "DECIMAL_STYLE",
                    proven=(
                        ("COMMA" if NumberStyle.COMMA in proven_style else "POINT")
                        if len(proven_style) == 1
                        else None
                    ),
                    columns=tuple(sorted(number_columns, key=position_of.__getitem__)),
                )
            )
        if style_choice is not None and number_columns:
            decimal = (",", ".") if style_choice == "COMMA" else (".", ",")
        return Formats(
            date_formats,
            decimal[0] if decimal else None,
            decimal[1] if decimal else None,
            tuple(hints),
            tuple(problems),
            unresolved=(bool(date_columns) and chosen is None)
            or (bool(number_columns) and style_choice is None),
        )

    def _documents(
        self,
        adapter: FileDomain,
        mapping: MappingInput,
        formats: "Formats",
        preserved: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        column_mapping: dict[str, Any] = {}
        for choice in mapping.columns:
            if choice.field is not None and choice.field not in column_mapping:
                column_mapping[choice.field] = {"column": choice.header}
        for key, value in mapping.constants.items():
            column_mapping.setdefault(key, {"constant": value})
        options: dict[str, Any] = {"schema_version": adapter.schema_version}
        if mapping.sheet_name:
            options["sheet_name"] = mapping.sheet_name
        if mapping.layout is not None:
            options["layout"] = mapping.layout.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            )
        if formats.date_formats:
            options["date_formats"] = formats.date_formats
        if formats.decimal_separator:
            options["decimal_separator"] = formats.decimal_separator
            options["thousands_separator"] = formats.thousands_separator
        documents: dict[str, dict[str, Any]] = {
            "column_mapping": column_mapping,
            "format_options": options,
        }
        for name in adapter.value_documents:
            # What was taught before stays; what the person says now wins (same word, new meaning).
            documents[name] = {**preserved.get(name, {}), **mapping.labels.get(name, {})}
        return documents

    def formats_of(
        self, adapter: FileDomain, mapping: MappingInput, samples: list[ColumnSample]
    ) -> "Formats":
        """How the mapped date and amount columns are written, and what is still unproven."""
        return self._formats(adapter, mapping, samples)

    # --- 4. trying a decision on the whole file ---------------------------------------------------

    def dry_run(
        self,
        property_id: UUID,
        domain: DataSourceDomain,
        filename: str,
        content: bytes,
        mapping: MappingInput | None,
        source: DataSource | None,
        already_imported: bool,
        period_start: date | None = None,
    ) -> DryRun:
        """Judge every row as the import would, and write nothing. `mapping=None` means the
        configuration saved for this kind of data."""
        adapter = self.domain(domain)
        mapping = self.mapping_with_period(mapping, period_start)
        try:
            config, blocked, hints = self._config_for(
                adapter, mapping, filename, content, source, period_start
            )
        except BookingImportError as error:
            return DryRun(DryRunStatus.BLOCKED, problem=problem_of_error(error))
        if blocked is not None:
            return blocked
        try:
            data = adapter.dry_run(property_id, filename, content, config)
        except AppError as error:
            return DryRun(DryRunStatus.BLOCKED, problem=problem_of_error(error))
        return self._to_dry_run(adapter, data, already_imported, hints)

    def _config_for(
        self,
        adapter: FileDomain,
        mapping: MappingInput | None,
        filename: str,
        content: bytes,
        source: DataSource | None,
        period_start: date | None = None,
    ) -> tuple[Any, DryRun | None, tuple[FormatHint, ...]]:
        if mapping is None:
            config, problem = self.saved_config_for(adapter, source)
            if config is None:
                return None, DryRun(DryRunStatus.BLOCKED, problem=problem), ()
            return self.config_with_period(adapter, config, period_start), None, ()
        table = self.read_table(content, filename, mapping.sheet_name, mapping.layout)
        preserved = self.preserved_documents(adapter, source)
        resolved = self.resolve(adapter, mapping, table, preserved)
        if resolved.needs_choice:
            return (
                None,
                DryRun(DryRunStatus.NEEDS_CHOICE, format_hints=resolved.format_hints),
                resolved.format_hints,
            )
        if resolved.problem is not None or resolved.config is None:
            return (
                None,
                DryRun(
                    DryRunStatus.BLOCKED,
                    problem=resolved.problem or ImportProblem.MAPPING_INCOMPLETE,
                    check=resolved.check,
                    format_hints=resolved.format_hints,
                ),
                resolved.format_hints,
            )
        return resolved.config, None, resolved.format_hints

    def _to_dry_run(
        self,
        adapter: FileDomain,
        data: DryRunData,
        already_imported: bool,
        hints: tuple[FormatHint, ...] = (),
    ) -> DryRun:
        if data.rows_total == 0:
            return DryRun(DryRunStatus.BLOCKED, problem=ImportProblem.NO_ROWS)
        samples = [adapter.sample_row(payload) for payload in data.sample_payloads]
        fields = tuple(
            key
            for key in adapter.sample_fields
            if any(sample.get(key) is not None for sample in samples)
        )
        fields_of_code: dict[str, set[str]] = defaultdict(set)
        invalid: list[InvalidRow] = []
        for number, issues in data.invalid_rows:
            pairs = tuple((issue["field"], _suffix(issue["code"])) for issue in issues)
            invalid.append(InvalidRow(number, pairs))
            for field, code in pairs:
                fields_of_code[code].add(field)
        problems = []
        for full_code, count in sorted(data.error_summary.items()):
            code = _suffix(full_code)
            involved = fields_of_code.get(code, set())
            problems.append(
                RowProblemCount(next(iter(involved)) if len(involved) == 1 else "", code, count)
            )
        return DryRun(
            DryRunStatus.READY,
            format_hints=hints,
            rows_total=data.rows_total,
            rows_valid=data.rows_valid,
            rows_invalid=data.rows_invalid,
            sample_fields=fields,
            sample_rows=tuple(tuple(sample.get(key) for key in fields) for sample in samples),
            row_problems=tuple(problems),
            invalid_rows=tuple(invalid),
            already_imported=already_imported,
            rows_unclassified=data.rows_unclassified,
            summary=data.summary,
            questions=_value_questions_of(data),
        )

    # --- the saved configuration -----------------------------------------------------------------

    def saved_config_for(
        self, adapter: FileDomain, source: DataSource | None
    ) -> tuple[Any | None, ImportProblem | None]:
        """The saved configuration as a validated mapping, or why it cannot be used."""
        profile = adapter.get_profile(source.id) if source is not None else None
        if profile is None:
            return None, ImportProblem.PROFILE_NOT_USABLE
        try:
            config = adapter.parse_config(profile.documents)
        except (AppError, ValueError):
            return None, ImportProblem.PROFILE_NOT_USABLE
        if self._version_of(adapter, config) != adapter.schema_version:
            return None, ImportProblem.PROFILE_NOT_USABLE
        return config, None

    @staticmethod
    def _version_of(adapter: FileDomain, config: Any) -> int:
        # A configuration saved before versions existed is the canonical identity one: version 1.
        return adapter.format_of(config).schema_version or 1

    def preserved_documents(
        self, adapter: FileDomain, source: DataSource | None
    ) -> dict[str, dict[str, Any]]:
        """The value labels (status, channel, role) the person already taught NINFA, kept when
        only the columns are matched again."""
        profile = adapter.get_profile(source.id) if source is not None else None
        if profile is None:
            return {}
        return {name: profile.documents.get(name, {}) for name in adapter.value_documents}

    def profile_info(
        self, adapter: FileDomain, source: DataSource | None, table: SourceTable
    ) -> ProfileInfo:
        """How the saved configuration of this source relates to THIS file."""
        return self._profile_info(adapter, source, table)

    def _profile_info(
        self, adapter: FileDomain, source: DataSource | None, table: SourceTable
    ) -> ProfileInfo:
        profile = adapter.get_profile(source.id) if source is not None else None
        if source is None or profile is None:
            return ProfileInfo(ProfileStatus.NONE)
        last_used = self._last_used(source)
        try:
            config = adapter.parse_config(profile.documents)
        except (AppError, ValueError):
            return ProfileInfo(ProfileStatus.NEEDS_REVIEW, ProfileReason.INVALID, None, last_used)
        decision = self._decision_of(adapter, config, table.headers)
        index = header_index(table.headers)
        missing = tuple(
            column
            for column in adapter.columns_of(config).values()
            if normalize_header(column) not in index
        )
        if self._version_of(adapter, config) != adapter.schema_version:
            return ProfileInfo(
                ProfileStatus.NEEDS_REVIEW,
                ProfileReason.VERSION_CHANGED,
                decision,
                last_used,
                missing,
            )
        if missing:
            return ProfileInfo(
                ProfileStatus.NEEDS_REVIEW,
                ProfileReason.COLUMNS_CHANGED,
                decision,
                last_used,
                missing,
            )
        return ProfileInfo(ProfileStatus.RECOGNIZED, None, decision, last_used)

    def _last_used(self, source: DataSource) -> Any:
        job = self._jobs.latest_succeeded_for_data_source(source.id)
        return None if job is None else job.finished_at

    @staticmethod
    def _decision_of(adapter: FileDomain, config: Any, headers: list[str]) -> MappingInput:
        """A saved configuration written as the person's decision (to start "Controlla colonne"
        from it): each column of THIS file with the meaning the configuration gives it."""
        columns = adapter.columns_of(config)
        field_of = {normalize_header(column): key for key, column in columns.items()}
        fmt: ConfigFormat = adapter.format_of(config)
        date_order: DateChoice | None = None
        for pattern in fmt.date_formats.values():
            if pattern.startswith("%d"):
                date_order = "DMY"
            elif pattern.startswith("%m"):
                date_order = "MDY"
        return MappingInput(
            sheet_name=fmt.sheet_name,
            layout=fmt.layout,
            columns=[
                ColumnChoice(header=header, field=field_of.get(normalize_header(header)))
                for header in headers
            ],
            constants=dict(adapter.constants_of(config)),
            date_order=date_order,
            decimal_style=(
                "COMMA"
                if fmt.decimal_separator == ","
                else "POINT"
                if fmt.decimal_separator == "."
                else None
            ),
        )

    @staticmethod
    def _learning_of(adapter: FileDomain, source: DataSource) -> dict[str, Any] | None:
        """The raw memory in this source's saved profile (None: nothing remembered)."""
        profile = adapter.get_profile(source.id)
        if profile is None:
            return None
        learning = (profile.documents.get("format_options") or {}).get("learning")
        return dict(learning) if isinstance(learning, dict) else None

    def configuration_of(self, source: DataSource) -> SavedConfiguration | None:
        adapter = domain_adapter(source.domain, self._session, self._tenant)
        profile: StoredProfile | None = None if adapter is None else adapter.get_profile(source.id)
        if adapter is None or profile is None:
            return None
        try:
            config = adapter.parse_config(profile.documents)
        except (AppError, ValueError):
            return SavedConfiguration(
                str(source.id), source.domain, (), (), self._last_used(source), False
            )
        return SavedConfiguration(
            data_source_id=str(source.id),
            domain=source.domain,
            columns=tuple(adapter.columns_of(config).items()),
            constants=tuple(
                (key, str(value)) for key, value in adapter.constants_of(config).items()
            ),
            last_used_at=self._last_used(source),
            schema_current=self._version_of(adapter, config) == adapter.schema_version,
        )

    def forget(self, source: DataSource) -> bool:
        """Drop the saved configuration. Imported data is not touched."""
        adapter = self.domain(source.domain)
        return adapter.delete_profile(source.id)

    def remember(
        self,
        source: DataSource,
        adapter: FileDomain,
        resolved: Resolved,
        confirmation: Confirmation | None = None,
    ) -> bool:
        """Save the configuration an import has just succeeded with, and what Source Learning
        keeps of it. A failure to save never undoes the import: it is only reported.

        What is learned depends on HOW the decision was confirmed, never on the client's say-so: a
        person's answers or a matching they built by hand make it TRUSTED (a new revision of the
        family the file is, or a new family when it is a structure of its own - never another
        family's); a file the engine read alone leaves ENGINE evidence and never replaces what a
        person confirmed; a decision that came from the memory confirms nothing new and leaves the
        families as they are."""
        if resolved.documents is None:
            return False
        documents = {name: dict(document) for name, document in resolved.documents.items()}
        existing_raw = self._learning_of(adapter, source)
        origin = Via.ENGINE if confirmation is None else confirmation.origin
        if confirmation is not None and confirmation.shape:
            mapped = {
                field: header_key(str(spec["column"]))
                for field, spec in documents.get("column_mapping", {}).items()
                if isinstance(spec, dict) and spec.get("column")
            }
            person = (
                dict(mapped)
                if origin == Via.MANUAL
                else {f: k for f, k in mapped.items() if k in confirmation.classified}
            )
            families = learn(
                parse_learning(existing_raw),
                family=confirmation.family,
                domain=adapter.domain.value,
                shape=confirmation.shape,
                mapped=mapped,
                person=person,
                answers=confirmation.answers,
                origin=origin,
            )
            if families is None and origin != Via.REUSE:
                # the engine alone never replaces what a person confirmed
                return False
            learning = existing_raw if families is None else stored_learning(families)
        else:
            # The saved matching is rewritten without saying which family it belongs to.
            known = parse_learning(existing_raw)
            learning = existing_raw if known is None else stored_learning(without_current(known))
        if learning is not None:
            documents.setdefault("format_options", {})["learning"] = learning
        try:
            adapter.save_profile(source.id, source.property_id, list(resolved.headers), documents)
        except Exception as error:  # the import is done and committed: only the memory failed
            self._session.rollback()
            logger.warning(
                "import configuration not saved workspace_id=%s property_id=%s "
                "data_source_id=%s error_type=%s",
                self._tenant.workspace_id,
                source.property_id,
                source.id,
                type(error).__name__,
            )
            return False
        return True


# --- helpers --------------------------------------------------------------------------------------


def _value_questions_of(data: DryRunData) -> tuple[Question, ...]:
    """The department / category words the file uses that NINFA does not know (one question,
    never a guess)."""
    if not data.unclassified_labels:
        return ()
    labels = list(data.unclassified_labels)
    if data.labels_document == "category_mapping":
        found = category_question(labels, {})
    else:
        found = label_question(labels, {})
    return () if found is None else (found,)


def _no_formats() -> Formats:
    return Formats({}, None, None, (), ())


def _suffix(code: str) -> str:
    """`BOOKING_INVALID_DATE` -> `INVALID_DATE`: the code without its domain prefix."""
    return code.partition("_")[2] or code


__all__ = [
    "COLUMN_AND_VALUE",
    "CONSTANT_NOT_ALLOWED",
    "DATES_MIXED",
    "FIELD_USED_TWICE",
    "INVALID_CONSTANT",
    "NUMBERS_MIXED",
    "UNKNOWN_COLUMN",
    "UNKNOWN_FIELD",
    "Resolved",
    "SmartImportService",
    "problem_of_error",
    "problem_of_error_code",
]

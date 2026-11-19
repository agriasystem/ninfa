"""InvoiceImportService: the application service behind an invoice file import.

Framework-free (no HTTP, no FastAPI): a future worker or an authenticated API can call it as is. It
is given a Session and a TenantContext and it OWNS the transaction boundaries:

    T1  create ImportJob (PENDING) + ImportFile metadata, mark RUNNING             commit
    T2  detect type -> parse -> normalise -> group -> validate -> stage each line      commit
    T3  (any invalid row) mark the job FAILED                                    commit
    T4  (all valid) lock, resolve suppliers, write invoices and lines, mark rows
        IMPORTED, job SUCCEEDED                                                  commit / rollback

The job outcome and the staged diagnostics are committed independently of the canonical write, so a
rolled-back canonicalisation still leaves a FAILED job and its staging rows. Canonical data
(new suppliers, identifiers, aliases, reviews, invoices, lines) is written in ONE transaction (T4):
all or nothing. Suppliers are resolved by the separate `SupplierResolver`; classification and
the document sign are canonical-model rules, not import-service rules.

Supported sources: FatturaPA XML 1.2.x (FPR12/FPA12), structured CSV and XLSX. NOT supported: PDF,
scanned documents (OCR) and signed .p7m files.

Pass a session with no uncommitted work: the service commits (and may roll back) it.
"""

import hashlib
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import PurePath
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source, lock_supplier_registry
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions
from app.modules.bookings.models import ImportRowStatus
from app.modules.bookings.parsers import open_table
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    FileScope,
    ImportJobStatus,
)
from app.modules.ingestion.repository import (
    DataSourceRepository,
    ImportFileRepository,
    ImportJobRepository,
)
from app.modules.ingestion.schemas import ImportFileCreate, ImportJobCreate
from app.modules.ingestion.scope import NO_SCOPE, ScopePlan
from app.modules.invoices.canonical import (
    CanonicalDocument,
    document_from_payloads,
    header_payload,
    line_payload,
    record_key,
)
from app.modules.invoices.classification import classify_line
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.documents import ParsedDocument
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError, RowIssue
from app.modules.invoices.fatturapa import parse_fatturapa
from app.modules.invoices.mapping import (
    InvoiceMappingConfig,
    check_schema,
    compute_header_signature,
    header_index,
    normalize_header,
)
from app.modules.invoices.models import InvoiceMappingProfile, ResolutionMethod, SourceFormat
from app.modules.invoices.repository import (
    ExistingRecord,
    InvoiceIdentity,
    InvoiceImportRowRepository,
    InvoiceMappingProfileRepository,
    InvoiceRepository,
    StagedRow,
)
from app.modules.invoices.structured import extract, parse_structured, require_explicit_formats
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.suppliers.errors import SupplierError
from app.modules.suppliers.resolution import (
    SupplierEvidence,
    SupplierResolution,
    SupplierResolver,
)

logger = logging.getLogger(__name__)

_MAX_SUMMARY_MESSAGE = 500
SourceKind = Literal["xml", "csv", "xlsx"]

# The Gate 2 readers raise BookingImportError: their codes become the invoice codes.
_READER_CODES = {
    BookingErrorCode.UNSUPPORTED_FILE_TYPE: InvoiceErrorCode.UNSUPPORTED_FILE_TYPE,
    BookingErrorCode.UNREADABLE_FILE: InvoiceErrorCode.UNREADABLE_FILE,
    BookingErrorCode.EMPTY_FILE: InvoiceErrorCode.EMPTY_FILE,
    BookingErrorCode.FILE_LIMIT_EXCEEDED: InvoiceErrorCode.FILE_LIMIT_EXCEEDED,
    BookingErrorCode.DUPLICATE_HEADER: InvoiceErrorCode.DUPLICATE_HEADER,
    BookingErrorCode.MAPPING_REQUIRED: InvoiceErrorCode.MAPPING_REQUIRED,
    BookingErrorCode.SOURCE_SCHEMA_CHANGED: InvoiceErrorCode.SOURCE_SCHEMA_CHANGED,
}


# --- results ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class InvoiceFileDescription:
    """What NINFA finds in a structured file, to help a person write a mapping. Nothing is saved."""

    file_type: str | None
    sheet_name: str | None
    headers: list[str]
    requires_sheet_selection: bool = False
    sheet_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InvoiceImportResult:
    """Outcome of one import. Machine-readable: branch on `error_code`, never on messages.

    `details` and `row_error_summary` hold field names, codes and counts only.
    """

    import_job_id: UUID
    import_file_id: UUID
    status: ImportJobStatus
    error_code: InvoiceErrorCode | str | None
    error_message: str | None
    source_format: SourceFormat | None = None
    documents_total: int = 0
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    invoices_created: int = 0
    invoices_unchanged: int = 0
    invoices_revised: int = 0
    # Operating costs with no document number (ADR 0057): a record that a person's word had taken
    # away and that this file holds again (it counts again, as the next revision), and the records
    # this file took away because a person said it holds everything of its period.
    records_restored: int = 0
    records_removed: int = 0
    lines_created: int = 0
    suppliers_created: int = 0
    suppliers_matched: int = 0
    identifiers_added: int = 0
    aliases_added: int = 0
    reviews_created: int = 0
    row_error_summary: dict[str, int] = field(default_factory=dict)
    warning_summary: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    # Informational: this exact file content was already imported successfully by this data
    # source. The import still runs (idempotently).
    duplicate_of_import_file_id: UUID | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == ImportJobStatus.SUCCEEDED

    @property
    def changed_data(self) -> bool:
        return (
            self.invoices_created
            + self.invoices_revised
            + self.records_restored
            + self.records_removed
            > 0
        )


@dataclass(frozen=True)
class InvoiceDryRun:
    """What importing a structured file WOULD do with a given mapping. Nothing was written."""

    file_type: str
    rows_total: int
    rows_valid: int
    rows_invalid: int
    row_error_summary: dict[str, int]
    sample_payloads: list[dict[str, Any]]
    invalid_rows: list[tuple[int, list[dict[str, str]]]]
    # The category words of the file that mean nothing yet, with how many rows each.
    unknown_categories: list[tuple[str, int]] = field(default_factory=list)
    # What the valid documents add up to (from the validated documents, never raw cells).
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Ids:
    """Plain ids, captured up front: safe to use after a rollback expired the ORM objects."""

    job: UUID
    file: UUID
    data_source: UUID
    property: UUID


@dataclass(frozen=True)
class _Counts:
    documents: int = 0
    rows: int = 0
    valid: int = 0
    invalid: int = 0


# --- service ----------------------------------------------------------------------------------


class InvoiceImportService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._data_sources = DataSourceRepository(session, tenant)
        self._properties = PropertyRepository(session, tenant)
        self._jobs = ImportJobRepository(session, tenant)
        self._files = ImportFileRepository(session, tenant)
        self._profiles = InvoiceMappingProfileRepository(session, tenant)
        self._rows = InvoiceImportRowRepository(session, tenant)
        self._invoices = InvoiceRepository(session, tenant)
        self._resolver = SupplierResolver(session, tenant)

    # --- mapping ------------------------------------------------------------------------------

    def describe_file(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
        property_id: UUID | None = None,
    ) -> InvoiceFileDescription:
        """The headers (and sheets) of a structured file. Read-only: writes nothing."""
        self._load_source(data_source_id, property_id)
        try:
            table = self._open_table(content, filename, FormatOptions(sheet_name=sheet_name))
        except InvoiceImportError as error:
            if error.error_code == InvoiceErrorCode.MAPPING_REQUIRED and error.details:
                return InvoiceFileDescription(
                    file_type="xlsx",
                    sheet_name=None,
                    headers=[],
                    requires_sheet_selection=True,
                    sheet_names=list(error.details.get("sheet_names", [])),
                )
            raise
        return InvoiceFileDescription(table.file_type, table.sheet_name, table.headers)

    def save_mapping(
        self,
        data_source_id: UUID,
        *,
        headers: list[str],
        column_mapping: dict[str, Any],
        category_mapping: dict[str, str] | None = None,
        format_options: dict[str, Any] | None = None,
        property_id: UUID | None = None,
    ) -> InvoiceMappingProfile:
        """Confirm a mapping for the data source (replacing the current one) and remember the
        header signature of the file it was confirmed on."""
        data_source, _ = self._load_source(data_source_id, property_id)
        config = InvoiceMappingConfig.parse(
            {
                "column_mapping": column_mapping,
                "category_mapping": category_mapping or {},
                "format_options": format_options or {},
            }
        )
        known = header_index(headers)
        unknown = [c for c in config.mapped_columns().values() if normalize_header(c) not in known]
        if unknown:
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_MAPPING,
                "The mapping refers to columns that are not in the file",
                details={"unknown_columns": unknown},
            )
        profile = self._profiles.upsert(
            data_source,
            stored=config.to_stored(),
            header_signature=compute_header_signature(headers),
        )
        self._session.commit()
        logger.info(
            "invoice mapping saved workspace_id=%s property_id=%s data_source_id=%s",
            self._tenant.workspace_id,
            data_source.property_id,
            data_source.id,
        )
        return profile

    # --- dry run ------------------------------------------------------------------------------

    def dry_run(
        self,
        property_id: UUID,
        *,
        filename: str,
        content: bytes,
        mapping: InvoiceMappingConfig,
        sample_size: int = 5,
        invalid_sample_size: int = 5,
    ) -> InvoiceDryRun:
        """Read, map, normalise and validate a structured file exactly as the import would, and
        write NOTHING: no job, no staged row, no supplier, no profile. It needs no data source.

        Raises InvoiceImportError for what stops the import before any row is judged (an
        unreadable file, a mapped column that is not there, a date or number format that has to be
        chosen). Every other problem is a row problem and is counted in the result.
        """
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_DATA_SOURCE,
                "The property cannot be used for invoice imports",
                details={"reason": "property_unavailable"},
            )
        options = mapping.format_options
        table = self._open_table(
            content,
            filename,
            FormatOptions(
                sheet_name=options.sheet_name,
                delimiter=options.delimiter,
                encoding=options.encoding,
                layout=options.layout,
            ),
        )
        schema = check_schema(mapping, compute_header_signature(table.headers), table.headers)
        if not schema.compatible:
            raise InvoiceImportError(
                InvoiceErrorCode.SOURCE_SCHEMA_CHANGED,
                "The file does not have the columns the mapping refers to",
                details={
                    "reason": "mapped_columns_missing",
                    "missing_columns": list(schema.missing_columns),
                },
            )
        rows = extract(table, mapping)
        if not rows:
            raise InvoiceImportError(InvoiceErrorCode.EMPTY_FILE, "The file has no invoice rows")
        require_explicit_formats(rows, mapping)
        documents = parse_structured(
            rows,
            mapping,
            property_currency=prop.currency,
            data_source_id=None,
            source_format=SourceFormat.XLSX if table.file_type == "xlsx" else SourceFormat.CSV,
        )
        staged, summary, _warnings = _stage(documents)
        # One entry per staged row, in the same order: the row of the file it was read from.
        file_rows: list[int | None] = []
        for document in documents:
            file_rows.extend(line.file_row for line in document.lines)
            if not document.lines:  # a document with no line still has a row to carry its issues
                file_rows.append(None)
        valid = [row for row in staged if row.validation_status == ImportRowStatus.VALID]
        invalid = [
            (position, row)
            for position, row in enumerate(staged)
            if row.validation_status == ImportRowStatus.INVALID
        ]
        unknown: Counter[str] = Counter(
            str(issue["value"])
            for _position, row in invalid
            for issue in row.validation_errors
            if issue.get("code") == InvoiceErrorCode.UNKNOWN_CATEGORY.value and issue.get("value")
        )
        return InvoiceDryRun(
            file_type=table.file_type,
            rows_total=len(staged),
            rows_valid=len(valid),
            rows_invalid=len(invalid),
            row_error_summary=summary,
            sample_payloads=[dict(row.normalized_payload or {}) for row in valid[:sample_size]],
            invalid_rows=[
                (_file_row(file_rows, position) or row.row_number, list(row.validation_errors))
                for position, row in invalid[:invalid_sample_size]
            ],
            unknown_categories=unknown.most_common(),
            summary=_dry_run_summary(documents),
        )

    def records_a_complete_file_would_remove(
        self,
        data_source_id: UUID,
        property_id: UUID,
        *,
        filename: str,
        content: bytes,
        mapping: InvoiceMappingConfig,
    ) -> int:
        """How many operating costs of this source would stop counting if THIS file holds everything
        of the period it covers (first to last date of its own rows). Read-only: nothing is written
        and no supplier is created.

        0 for a mapping that identifies its records by a document number (a real invoice is never
        taken away by any file), for a file that cannot be read cleanly (what is wrong with it is
        said when it is tried, not here), and when nothing would go."""
        if not mapping.is_synthetic:
            return 0
        prop = self._properties.get(property_id)
        if prop is None:
            return 0
        kind = detect_source(filename, content)
        if kind == "xml":
            return 0
        source_format = SourceFormat.CSV if kind == "csv" else SourceFormat.XLSX
        ids = _Ids(uuid4(), uuid4(), data_source_id, property_id)
        parsed = self._parse_structured(
            ids, filename, content, prop.currency, source_format, mapping
        )
        canonical = [document.canonical for document in parsed if document.valid]
        if not parsed or len(canonical) != len(parsed):
            return 0
        documents = [document for document in canonical if document is not None]
        plan = self._resolver.plan([document.supplier for document in documents])
        placed = self._place_synthetic(
            [(document, plan.resolutions[document.supplier.key]) for document in documents],
            property_id,
            data_source_id,
        )
        return self._invoices.count_synthetic_absent_from(
            data_source_id,
            [placement.identity[1] for placement in placed],
            min(document.invoice_date for document in documents),
            max(document.invoice_date for document in documents),
        )

    def _place_synthetic(
        self,
        resolved: list[tuple[CanonicalDocument, SupplierResolution]],
        property_id: UUID,
        data_source_id: UUID,
    ) -> list["_Placement"]:
        """Where each operating cost with no number goes among the records the source already
        holds (ADR 0057). The same function serves the import and the preview of what a complete
        file would take away, so the figure a person is shown is the one that is applied.

        Rows that are economically identical (same fingerprint) are a MULTISET. The CATEGORY is not
        part of what a cost is: a reclassification is the same cost, and two equal rows may be
        stated with two categories and stay two costs, each with its own. For one fingerprint:

        1. an occurrence keeps the record already holding the same stated category (nothing
           changes);
        2. whatever is left is paired, in a fixed order, with the records left: a different stated
           category is a RECLASSIFICATION of that same cost (the next revision of its key), and a
           file that states no category says nothing and changes nothing;
        3. occurrences beyond the records the source holds are new: a record a person's word took
           away comes back first (the next revision of its key), then new numbers are used.

        The order of the rows in the file is never used: the same rows in another order are the
        same placement."""
        groups: dict[str, list[tuple[CanonicalDocument, SupplierResolution]]] = {}
        for document, resolution in resolved:
            fingerprint = document.record_fingerprint(
                str(resolution.supplier_id), str(data_source_id)
            )
            groups.setdefault(fingerprint, []).append((document, resolution))
        existing = self._invoices.synthetic_records_of(
            property_id,
            data_source_id,
            list(groups),
            [document.invoice_date for document, _ in resolved],
        )
        placed: list[_Placement] = []
        for fingerprint, items in groups.items():
            records = existing.get(fingerprint, [])
            counting = [record for record in records if not record.removed]
            away = [record for record in records if record.removed]
            next_number = max((record.occurrence for record in records), default=0) + 1
            ordered = sorted(items, key=lambda item: _category_order(_stated_category(item[0])))
            leftover: list[tuple[CanonicalDocument, SupplierResolution]] = []
            for document, resolution in ordered:
                stated = _stated_category(document)
                match = next((record for record in counting if record.category == stated), None)
                if match is None:
                    leftover.append((document, resolution))
                    continue
                counting.remove(match)
                placed.append(
                    _placement(
                        document, resolution, fingerprint, match, "UNCHANGED", match.revision
                    )
                )
            fresh: list[tuple[CanonicalDocument, SupplierResolution]] = []
            for document, resolution in leftover:
                if counting:
                    record = counting.pop(0)
                    reclassified = _stated_category(document) is not None
                    placed.append(
                        _placement(
                            document,
                            resolution,
                            fingerprint,
                            record,
                            "RECLASSIFY" if reclassified else "UNCHANGED",
                            record.revision + 1 if reclassified else record.revision,
                        )
                    )
                else:
                    fresh.append((document, resolution))
            for document, resolution in fresh:
                if away:
                    record = away.pop(0)
                    placed.append(
                        _placement(
                            document,
                            resolution,
                            fingerprint,
                            record,
                            "RESTORE",
                            record.revision + 1,
                        )
                    )
                else:
                    placed.append(
                        _placement(
                            document,
                            resolution,
                            fingerprint,
                            None,
                            "NEW",
                            1,
                            record_key(fingerprint, next_number),
                        )
                    )
                    next_number += 1
        return placed

    # --- import -------------------------------------------------------------------------------

    def import_file(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        property_id: UUID | None = None,
        mapping_override: InvoiceMappingConfig | None = None,
        scope: ScopePlan = NO_SCOPE,
    ) -> InvoiceImportResult:
        """Import one invoice file into the canonical model, atomically and idempotently.

        `mapping_override` is a validated mapping used instead of the one saved for the data source
        (Smart Import: the person's own matching, saved only once this import has succeeded).

        `scope` is what the caller knows this file to be. Only `FileScope.FULL`, and only for
        operating costs with no document number, makes the absence of a record mean anything: the
        records of the source the file does not hold, inside the period its own rows cover, stop
        counting. With anything else, or nothing, nothing is ever taken away. A real invoice is
        never taken away by any file.

        Raises InvoiceImportError(INVOICE_INVALID_DATA_SOURCE) when the data source cannot be used
        (nothing is created). Every later problem ends as a FAILED ImportJob and a returned result
        with a stable `error_code`.
        """
        data_source, prop = self._load_source(data_source_id, property_id)
        sha256 = hashlib.sha256(content).hexdigest()
        previous = self._files.find_successful_for_data_source(data_source.id, sha256)

        # T1: the attempt is recorded before anything can go wrong.
        job = self._jobs.add(ImportJobCreate(data_source_id=data_source.id))
        import_file = self._files.add(
            job.id,
            ImportFileCreate(
                original_filename=_safe_filename(filename),
                mime_type=mime_type,
                size_bytes=len(content),
                sha256=sha256,
            ),
        )
        self._jobs.start(job.id)
        ids = _Ids(job.id, import_file.id, data_source.id, data_source.property_id)
        duplicate_of = previous.id if previous is not None else None
        currency = prop.currency
        self._session.commit()
        self._log("invoice import started", ids)

        try:
            result = self._run(
                ids, filename, content, currency, duplicate_of, mapping_override, scope
            )
        except (InvoiceImportError, SupplierError) as error:
            result = self._fail(ids, error.code, error.message, _details(error), duplicate_of)
        except Exception as error:  # a bug or infrastructure problem: never leave the job RUNNING
            logger.error(
                "invoice import crashed workspace_id=%s import_job_id=%s error_type=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
            )
            result = self._fail(
                ids,
                InvoiceErrorCode.INTERNAL_ERROR,
                "The import stopped because of an internal error",
                None,
                duplicate_of,
            )
        self._log(
            f"invoice import finished status={result.status.value} "
            f"error_code={_code(result.error_code)} documents={result.documents_total} "
            f"rows={result.rows_total} invalid={result.rows_invalid} "
            f"invoices_created={result.invoices_created} unchanged={result.invoices_unchanged} "
            f"suppliers_created={result.suppliers_created} reviews={result.reviews_created}",
            ids,
        )
        return result

    # --- pipeline -----------------------------------------------------------------------------

    def _run(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        currency: str,
        duplicate_of: UUID | None,
        mapping_override: InvoiceMappingConfig | None = None,
        scope: ScopePlan = NO_SCOPE,
    ) -> InvoiceImportResult:
        kind = detect_source(filename, content)
        source_format = {
            "xml": SourceFormat.FATTURAPA_XML,
            "csv": SourceFormat.CSV,
            "xlsx": SourceFormat.XLSX,
        }[kind]
        if kind == "xml":
            documents = parse_fatturapa(content, data_source_id=ids.data_source)
        else:
            documents = self._parse_structured(
                ids, filename, content, currency, source_format, mapping_override
            )
        if not documents:
            raise InvoiceImportError(
                InvoiceErrorCode.EMPTY_FILE, "The file has a header but no invoice rows"
            )

        staged, summary, warnings = _stage(documents)
        invalid = sum(1 for row in staged if row.validation_status == ImportRowStatus.INVALID)
        self._rows.add_many(ids.job, ids.file, staged)
        self._session.commit()  # T2: staging and diagnostics are kept whatever happens next

        counts = _Counts(len(documents), len(staged), len(staged) - invalid, invalid)
        if invalid:
            return self._fail(
                ids,
                InvoiceErrorCode.VALIDATION_FAILED,
                f"{invalid} of {len(staged)} rows failed validation: nothing was imported",
                None,
                duplicate_of,
                summary=summary,
                counts=counts,
                warnings=warnings,
                source_format=source_format,
            )
        return self._canonicalize(ids, duplicate_of, counts, warnings, source_format, scope)

    def _parse_structured(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        currency: str,
        source_format: SourceFormat,
        mapping_override: InvoiceMappingConfig | None = None,
    ) -> list[ParsedDocument]:
        profile = (
            None
            if mapping_override is not None
            else self._profiles.get_for_data_source(ids.data_source)
        )
        if profile is None and mapping_override is None:
            raise InvoiceImportError(
                InvoiceErrorCode.MAPPING_REQUIRED,
                "This data source has no confirmed mapping yet: describe the file and confirm one",
                details={"reason": "no_confirmed_mapping"},
            )
        config = mapping_override or InvoiceMappingConfig.parse(
            {
                "column_mapping": profile.column_mapping if profile else {},
                "category_mapping": profile.category_mapping if profile else {},
                "format_options": profile.format_options if profile else {},
            }
        )
        options = config.format_options
        table = self._open_table(
            content,
            filename,
            FormatOptions(
                sheet_name=options.sheet_name,
                delimiter=options.delimiter,
                encoding=options.encoding,
                layout=options.layout,
            ),
        )
        # An override was built from THIS file's headers a moment ago: only a saved one can be
        # stale.
        schema = check_schema(config, profile.header_signature if profile else "", table.headers)
        if not schema.compatible:
            raise InvoiceImportError(
                InvoiceErrorCode.SOURCE_SCHEMA_CHANGED,
                "The file no longer has the columns this data source was mapped on: "
                "review and confirm the mapping again",
                details={
                    "reason": "mapped_columns_missing",
                    "missing_columns": list(schema.missing_columns),
                },
            )
        rows = extract(table, config)
        require_explicit_formats(rows, config)
        return parse_structured(
            rows,
            config,
            property_currency=currency,
            data_source_id=ids.data_source,
            source_format=source_format,
        )

    @staticmethod
    def _open_table(content: bytes, filename: str, options: FormatOptions) -> Any:
        try:
            return open_table(content, filename, options)
        except BookingImportError as error:
            code = _READER_CODES.get(error.error_code, InvoiceErrorCode.UNREADABLE_FILE)
            raise InvoiceImportError(code, error.message, details=error.details) from None

    # --- canonicalisation (T4) ------------------------------------------------------------------

    def _canonicalize(
        self,
        ids: _Ids,
        duplicate_of: UUID | None,
        counts: _Counts,
        warnings: dict[str, int],
        source_format: SourceFormat,
        scope: ScopePlan = NO_SCOPE,
    ) -> InvoiceImportResult:
        """Every valid document becomes a canonical invoice (with its supplier), or none does."""
        removed = 0
        try:
            # One canonicalisation per data source at a time, and one supplier registry writer per
            # workspace at a time, always in this order (no lock cycle is possible).
            lock_data_source(self._session, ids.data_source)
            lock_supplier_registry(self._session, self._tenant.workspace_id)

            documents = self._load_documents(ids)
            plan = self._resolver.plan([document.supplier for document in documents])
            self._resolver.apply(plan)
            # A supplier created by this import tells ONE story to all its documents: a sibling
            # document that merely matched it (say, one without the IBAN) was not resolved
            # "by VAT number" in any sense a person would care about.
            created_by = {r.supplier_id: r for r in plan.resolutions.values() if r.created}

            resolved = [
                (document, plan.resolutions[document.supplier.key]) for document in documents
            ]
            keyed = _identify([(d, r) for d, r in resolved if not d.is_synthetic])
            placed = self._place_synthetic(
                [(d, r) for d, r in resolved if d.is_synthetic], ids.property, ids.data_source
            )
            identities: dict[InvoiceIdentity, CanonicalDocument] = {}
            duplicated: list[int] = []
            for identity, document, _resolution, _fingerprint in keyed:
                if identity in identities:  # the same document twice in one import
                    duplicated.append(document.source_document_index)
                identities[identity] = document
            if duplicated:
                raise InvoiceImportError(
                    InvoiceErrorCode.DOCUMENT_CONFLICT,
                    "The same invoice appears more than once in the import",
                    details={"reason": "duplicate_in_import", "documents": duplicated[:50]},
                )

            existing = self._invoices.find_by_identities(ids.property, list(identities))
            conflicts: list[int] = []
            new_invoices: list[dict[str, Any]] = []
            new_lines: list[dict[str, Any]] = []
            unchanged = revised = restored = 0
            for identity, document, resolution, fingerprint in keyed:
                stored = existing.get(identity)
                revision = 1
                if stored is not None:
                    if stored.source_fingerprint == fingerprint:
                        unchanged += 1
                        continue
                    if SourceFormat.FATTURAPA_XML in (stored.source_format, document.source_format):
                        conflicts.append(document.source_document_index)
                        continue
                    # A row of a spreadsheet corrected: the older version stays, this one counts.
                    revision = stored.revision + 1
                    revised += 1
                invoice_id = uuid4()
                new_invoices.append(
                    self._invoice_row(
                        ids,
                        invoice_id,
                        document,
                        resolution,
                        fingerprint,
                        _resolution_story(resolution, created_by),
                        revision,
                        identity[1],
                    )
                )
                new_lines.extend(self._line_rows(invoice_id, document, resolution))
            for placement in placed:
                if placement.action == "UNCHANGED":
                    unchanged += 1
                    continue
                if placement.action == "RESTORE":
                    restored += 1  # a record a person's word took away comes back: next revision
                elif placement.action == "RECLASSIFY":
                    revised += 1  # the same cost, stated with another category: next revision
                invoice_id = uuid4()
                new_invoices.append(
                    self._invoice_row(
                        ids,
                        invoice_id,
                        placement.document,
                        placement.resolution,
                        placement.fingerprint,
                        _resolution_story(placement.resolution, created_by),
                        placement.revision,
                        placement.identity[1],
                    )
                )
                new_lines.extend(
                    self._line_rows(invoice_id, placement.document, placement.resolution)
                )
            if conflicts:
                raise InvoiceImportError(
                    InvoiceErrorCode.DOCUMENT_CONFLICT,
                    "A fiscal document with this identity already exists with a different "
                    "content: it is never replaced",
                    details={"reason": "different_content", "documents": conflicts[:50]},
                )

            # What a COMPLETE file of operating costs takes away: the records of this source it does
            # not hold, inside the period its own rows cover. Computed here, under the lock: if it
            # is not what the person was shown, nothing is imported. A real invoice is never in it.
            synthetic = [doc for doc in documents if doc.is_synthetic]
            complete = (
                scope.file_scope is FileScope.FULL
                and bool(synthetic)
                and len(synthetic) == len(documents)
            )
            held = [placement.identity[1] for placement in placed]
            first = min((doc.invoice_date for doc in synthetic), default=None)
            last = max((doc.invoice_date for doc in synthetic), default=None)
            if complete and first is not None and last is not None:
                absent = self._invoices.count_synthetic_absent_from(
                    ids.data_source, held, first, last
                )
                if scope.is_stale(absent):
                    raise InvoiceImportError(
                        InvoiceErrorCode.IMPORT_PLAN_CHANGED,
                        "What this file would take away changed after it was read: "
                        "nothing was imported",
                    )

            self._invoices.insert_invoices(new_invoices)
            self._invoices.insert_lines(new_lines)
            if complete and first is not None and last is not None:
                removed = self._invoices.remove_synthetic_absent_from(
                    ids.data_source, ids.job, held, first, last
                )
            self._rows.mark_valid_rows_imported(ids.job)
            self._jobs.succeed(
                ids.job,
                changed_data=bool(new_invoices) or removed > 0,
                file_scope=scope.file_scope,
                remembered_file_scope=scope.remembered_file_scope,
            )
            self._session.commit()
        except (InvoiceImportError, SupplierError):
            raise  # rolled back and recorded as FAILED by import_file
        except Exception as error:
            self._session.rollback()  # nothing of this batch survives
            constraint = _constraint_name(error)
            logger.error(
                "invoice canonicalisation rolled back workspace_id=%s import_job_id=%s "
                "error_type=%s constraint=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
                constraint or "-",
            )
            return self._fail(
                ids,
                InvoiceErrorCode.CANONICALIZATION_FAILED,
                "The database rejected the batch: no invoice was imported",
                {"constraint": constraint} if constraint else None,
                duplicate_of,
                counts=counts,
                warnings=warnings,
                source_format=source_format,
            )
        created_suppliers = list(created_by.values())
        matched_suppliers = {
            r.supplier_id
            for r in plan.resolutions.values()
            if not r.created and r.supplier_id not in created_by
        }
        return InvoiceImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.SUCCEEDED,
            error_code=None,
            error_message=None,
            source_format=source_format,
            documents_total=counts.documents,
            rows_total=counts.rows,
            rows_valid=counts.valid,
            rows_invalid=counts.invalid,
            invoices_created=len(new_invoices) - revised - restored,
            invoices_unchanged=unchanged,
            invoices_revised=revised,
            records_restored=restored,
            records_removed=removed,
            lines_created=len(new_lines),
            suppliers_created=len(created_suppliers),
            suppliers_matched=len(matched_suppliers),
            identifiers_added=len(plan.identifiers) - _identifiers_of_new(plan),
            aliases_added=len(plan.aliases) - len(created_suppliers),
            reviews_created=len(plan.reviews),
            warning_summary=warnings,
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_documents(self, ids: _Ids) -> list[CanonicalDocument]:
        """The canonical documents of the staged VALID rows, in file order."""
        rows = self._rows.list_for_job(ids.job, status=ImportRowStatus.VALID)
        headers: dict[int, dict[str, Any]] = {}
        lines: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            payload = row.normalized_payload or {}
            if "header" in payload:
                headers[row.source_document_index] = payload["header"]
            lines[row.source_document_index].append(payload["line"])
        return [
            document_from_payloads(headers[index], lines[index], ids.data_source)
            for index in sorted(headers)
        ]

    def _invoice_row(
        self,
        ids: _Ids,
        invoice_id: UUID,
        document: CanonicalDocument,
        resolution: SupplierResolution,
        fingerprint: str,
        method: ResolutionMethod,
        revision: int = 1,
        key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": invoice_id,
            "revision": revision,
            "workspace_id": self._tenant.workspace_id,
            "property_id": ids.property,
            "data_source_id": ids.data_source,
            "supplier_id": resolution.supplier_id,
            # the SOURCE's number: None for an operating cost that has none, never an invented one
            "invoice_number": document.invoice_number,
            "normalized_invoice_number": document.normalized_invoice_number,
            "source_record_key": key or document.normalized_invoice_number,
            "identity_origin": document.identity_origin,
            "invoice_date": document.invoice_date,
            "due_date": document.due_date,
            "document_type_code": document.document_type_code,
            "document_kind": document.document_kind,
            "currency": document.currency,
            "net_amount": document.net_amount,
            "tax_amount": document.tax_amount,
            "gross_amount": document.gross_amount,
            "source_format": document.source_format,
            "source_import_job_id": ids.job,
            "source_import_file_id": ids.file,
            "source_fingerprint": fingerprint,
            "supplier_resolution_method": method,
        }

    def _line_rows(
        self, invoice_id: UUID, document: CanonicalDocument, resolution: SupplierResolution
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in document.lines:
            classification = classify_line(
                line.description_normalized,
                explicit=line.explicit_category,
                supplier_default=resolution.default_cost_category,
            )
            rows.append(
                {
                    "workspace_id": self._tenant.workspace_id,
                    "invoice_id": invoice_id,
                    "source_line_number": line.source_line_number,
                    "description_raw": line.description_raw,
                    "description_normalized": line.description_normalized,
                    "quantity": line.quantity,
                    "unit": line.unit,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                    "vat_rate": line.vat_rate,
                    "cost_category": classification.category,
                    "classification_confidence": classification.confidence,
                    "classification_method": classification.method,
                }
            )
        return rows

    # --- helpers ------------------------------------------------------------------------------

    def _fail(
        self,
        ids: _Ids,
        code: InvoiceErrorCode | str,
        message: str,
        details: dict[str, Any] | None,
        duplicate_of: UUID | None,
        *,
        summary: dict[str, int] | None = None,
        counts: _Counts | None = None,
        warnings: dict[str, int] | None = None,
        source_format: SourceFormat | None = None,
    ) -> InvoiceImportResult:
        """Record the failure in its own transaction: it survives any data rollback."""
        self._session.rollback()  # drop anything left over from a failed step
        code_text = code.value if isinstance(code, InvoiceErrorCode) else str(code)
        self._jobs.fail(ids.job, error_code=code_text, error_message=message[:_MAX_SUMMARY_MESSAGE])
        self._session.commit()
        counted = counts or _Counts()
        return InvoiceImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.FAILED,
            error_code=code,
            error_message=message[:_MAX_SUMMARY_MESSAGE],
            source_format=source_format,
            documents_total=counted.documents,
            rows_total=counted.rows,
            rows_valid=counted.valid,
            rows_invalid=counted.invalid,
            row_error_summary=summary or {},
            warning_summary=warnings or {},
            details=details or {},
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_source(
        self, data_source_id: UUID, property_id: UUID | None = None
    ) -> tuple[DataSource, Property]:
        """The data source must be an active COSTS/FILE_UPLOAD source of this workspace.

        Unknown ids and ids of another workspace are indistinguishable (same error).
        """
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.COSTS:
            reason = "wrong_domain"
        elif data_source.source_type != DataSourceType.FILE_UPLOAD:
            reason = "wrong_source_type"
        elif not data_source.is_active:
            reason = "inactive"
        elif property_id is not None and data_source.property_id != property_id:
            reason = "property_mismatch"
        prop = self._properties.get(data_source.property_id) if data_source is not None else None
        if reason is None and (prop is None or prop.archived_at is not None):
            reason = "property_unavailable"
        if reason is not None or data_source is None or prop is None:
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for invoice imports",
                details={"reason": reason or "not_found"},
            )
        return data_source, prop

    def _log(self, message: str, ids: _Ids) -> None:
        logger.info(
            "%s workspace_id=%s property_id=%s data_source_id=%s "
            "import_job_id=%s import_file_id=%s",
            message,
            self._tenant.workspace_id,
            ids.property,
            ids.data_source,
            ids.job,
            ids.file,
        )


# --- module functions ---------------------------------------------------------------------------


def detect_source(filename: str, content: bytes) -> SourceKind:
    """`.xml` (FatturaPA), `.csv` and `.xlsx` only. PDF, scans and signed `.p7m` are refused."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".xml":
        return "xml"
    if suffix in {".csv", ".xlsx"}:
        return "xlsx" if suffix == ".xlsx" else "csv"
    reason = {".p7m": "signed_p7m_not_supported", ".pdf": "pdf_not_supported"}.get(
        suffix, "unsupported_extension"
    )
    raise InvoiceImportError(
        InvoiceErrorCode.UNSUPPORTED_FILE_TYPE,
        f"Unsupported file type '{suffix or 'none'}': only FatturaPA .xml, .csv and .xlsx are "
        "supported (no PDF, no OCR, no signed .p7m)",
        details={"reason": reason, "supported": [".xml", ".csv", ".xlsx"]},
    )


def _stage(
    documents: list[ParsedDocument],
) -> tuple[list[StagedRow], dict[str, int], dict[str, int]]:
    """One staging row per source line (a document header rides on its first line)."""
    rows: list[StagedRow] = []
    summary: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    for document in documents:
        warnings.update(w.code.value for w in document.warnings)
        canonical = document.canonical if document.valid else None
        located = document.located_issues()
        if not document.lines:  # a document with no line still needs a row to carry its issues
            issues = [item.issue for item in located]
            summary.update(issue.code.value for issue in issues)
            rows.append(
                StagedRow(
                    row_number=len(rows) + 1,
                    source_document_index=document.index,
                    source_line_number=None,
                    mapped_payload=dict(document.mapped_header),
                    normalized_payload=None,
                    validation_status=ImportRowStatus.INVALID,
                    validation_errors=[issue.to_json() for issue in issues],
                    validation_warnings=[w.to_json() for w in document.warnings],
                )
            )
            continue
        for position, line in enumerate(document.lines):
            first = position == 0
            issues = [item.issue for item in located if item.line_index == position]
            if first:
                issues = [item.issue for item in located if item.line_index is None] + issues
            summary.update(issue.code.value for issue in issues)
            if not issues and canonical is None:
                issues = [
                    RowIssue(
                        "document",
                        InvoiceErrorCode.VALIDATION_FAILED,
                        "another line or the document header is invalid",
                    )
                ]
            mapped = dict(document.mapped_header) if first else {}
            mapped.update(line.mapped)
            normalized: dict[str, Any] | None = None
            if canonical is not None and not issues:
                normalized = {"line": line_payload(canonical.lines[position])}
                if first:
                    normalized["header"] = header_payload(canonical)
            rows.append(
                StagedRow(
                    row_number=len(rows) + 1,
                    source_document_index=document.index,
                    source_line_number=line.source_line_number,
                    mapped_payload=mapped,
                    normalized_payload=normalized,
                    validation_status=(
                        ImportRowStatus.INVALID if issues else ImportRowStatus.VALID
                    ),
                    validation_errors=[issue.to_json() for issue in issues],
                    validation_warnings=([w.to_json() for w in document.warnings] if first else []),
                )
            )
    return rows, dict(sorted(summary.items())), dict(sorted(warnings.items()))


def _file_row(file_rows: list[int | None], position: int) -> int | None:
    return file_rows[position] if position < len(file_rows) else None


def _identify(
    resolved: list[tuple[CanonicalDocument, SupplierResolution]],
) -> list[tuple[InvoiceIdentity, CanonicalDocument, SupplierResolution, str]]:
    """The identity and the content fingerprint of every REAL document, in file order: its number,
    as it always was. (An operating cost with no number is placed by `_place_synthetic`.)"""
    keyed: list[tuple[InvoiceIdentity, CanonicalDocument, SupplierResolution, str]] = []
    for document, resolution in resolved:
        if document.normalized_invoice_number is None:  # pragma: no cover - checked by the DB
            raise InvoiceImportError(
                InvoiceErrorCode.VALIDATION_FAILED, "a document with no number and no identity"
            )
        identity = (
            resolution.supplier_id,
            document.normalized_invoice_number,
            document.invoice_date,
            document.document_kind,
        )
        fingerprint = document.fingerprint(str(resolution.supplier_id))
        keyed.append((identity, document, resolution, fingerprint))
    return keyed


@dataclass(frozen=True, slots=True)
class _Placement:
    """Where one operating cost with no number goes (`InvoiceImportService._place_synthetic`)."""

    identity: InvoiceIdentity
    document: CanonicalDocument
    resolution: SupplierResolution
    fingerprint: str
    action: Literal["NEW", "UNCHANGED", "RESTORE", "RECLASSIFY"]
    # the revision to WRITE (the stored one for UNCHANGED, where nothing is written)
    revision: int


def _placement(
    document: CanonicalDocument,
    resolution: SupplierResolution,
    fingerprint: str,
    record: ExistingRecord | None,
    action: Literal["NEW", "UNCHANGED", "RESTORE", "RECLASSIFY"],
    revision: int,
    key: str | None = None,
) -> _Placement:
    chosen = key if record is None else record.key
    assert chosen is not None  # a new occurrence is given its key; an existing one has its own
    identity = (resolution.supplier_id, chosen, document.invoice_date, document.document_kind)
    return _Placement(identity, document, resolution, fingerprint, action, revision)


def _stated_category(document: CanonicalDocument) -> CostCategory | None:
    """The category the SOURCE stated for this cost (None: it stated none). An operating cost is one
    line; what NINFA derives when the source says nothing is not a statement of the source."""
    return next((line.explicit_category for line in document.lines), None)


def _category_order(category: CostCategory | None) -> tuple[bool, str]:
    """A fixed order for the categories of identical rows (none last), never the file order."""
    return (category is None, "" if category is None else category.value)


def _dry_run_summary(documents: list[ParsedDocument]) -> dict[str, Any]:
    """The totals of the documents that passed validation (what the import would keep)."""
    valid = [document.canonical for document in documents if document.valid and document.canonical]
    if not valid:
        return {}
    net = sum((line.line_total for doc in valid for line in doc.lines), Decimal(0))
    dates = [doc.invoice_date.isoformat() for doc in valid]
    currencies = {doc.currency for doc in valid}
    return {
        "documents": len(valid),
        "suppliers": len({doc.supplier.normalized_name for doc in valid}),
        "net_total": format(net, "f"),
        "date_from": min(dates),
        "date_to": max(dates),
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
    }


def _resolution_story(
    resolution: SupplierResolution, created_by: dict[UUID, SupplierResolution]
) -> ResolutionMethod:
    """How a document's supplier was resolved: the creation story when this import created it."""
    origin = created_by.get(resolution.supplier_id)
    return origin.method if origin is not None else resolution.method


def _identifiers_of_new(plan: Any) -> int:
    """Identifiers written for suppliers created in this import (not counted as 'added')."""
    created = {item.id for item in plan.suppliers}
    return sum(1 for item in plan.identifiers if item.supplier_id in created)


def _details(error: InvoiceImportError | SupplierError) -> dict[str, Any] | None:
    details = error.details
    return details if isinstance(details, dict) else None


def _code(code: InvoiceErrorCode | str | None) -> str:
    if code is None:
        return "-"
    return code.value if isinstance(code, InvoiceErrorCode) else str(code)


def _safe_filename(filename: str) -> str:
    """Base name only (no client path), bounded, never empty."""
    name = PurePath(filename.replace("\\", "/")).name.strip()
    return (name or "upload")[:255]


def _constraint_name(error: Exception) -> str | None:
    """The violated constraint of a database error: a schema name, never row data."""
    if isinstance(error, DBAPIError):
        diag = getattr(error.orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
        return name if isinstance(name, str) else None
    return None


__all__ = [
    "InvoiceFileDescription",
    "InvoiceImportResult",
    "InvoiceImportService",
    "SupplierEvidence",
    "detect_source",
]

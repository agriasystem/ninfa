"""Smart Import V3: NINFA understands the DOCUMENT, then asks only what is really ambiguous.

    file -> every sheet read -> the table found (title, summary, totals, department lines left out)
         -> what kind of data it is -> where the department of each row comes from
         -> what each column means (by its words, checked against its values) -> a decision
         -> what is STILL unclear, as single questions - or nothing, and the person just imports

This sits next to V2's matching and reuses all of it: the decision it proposes is a V2
`MappingInput` (plus the small `layout` that makes the reading repeatable), checked by the import
service's own rules, tried on the whole file by the same dry run, imported all-or-nothing by the
same import. What is new is only that the decision usually does not have to be built by hand.

Deterministic, no AI, no network: an AI resolver (see `app.modules.import_understanding`) may be
asked about what is left, but it is optional, off by default, and never the only reason for a
certainty.
"""

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from itertools import islice
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.bookings.errors import BookingImportError
from app.modules.bookings.mapping import normalize_header
from app.modules.bookings.normalization import DateOrder
from app.modules.bookings.parsers import Cell, SourceTable
from app.modules.bookings.statuses import BUILTIN_STATUS_KEYS
from app.modules.bookings.text import normalize_key
from app.modules.data_sources.column_profile import (
    ColumnSample,
    NumberStyle,
    date_order_of,
    number_style,
    sample_columns,
)
from app.modules.data_sources.domain_adapters import FileDomain
from app.modules.data_sources.domain_detection import (
    DomainScore,
    DomainVerdict,
    score_domain,
    verdict,
)
from app.modules.data_sources.files import ImportProblem
from app.modules.data_sources.mapping_types import (
    ColumnChoice,
    ColumnInfo,
    FileInspection,
    MappingInput,
    ProfileStatus,
    SmartImportDecision,
    SuggestionLevel,
)
from app.modules.data_sources.proposal import CONTESTED, ColumnProposal, Proposal, propose
from app.modules.data_sources.semantics import DomainSem, Level, NameMatch
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR, hourly_or_known_exclusion
from app.modules.data_sources.smart_import import Formats, SmartImportService, problem_of_error
from app.modules.data_sources.source_learning import (
    Confirmation,
    Drift,
    Learning,
    LearningInfo,
    Memory,
    SourceMatch,
    Via,
    choose_family,
    column_views,
    header_key,
    kept_answers,
    match_source,
    parse_learning,
    reusable,
    shape_of,
)
from app.modules.data_sources.understanding_ai import (
    apply_resolution,
    build_evidence,
    egress_guard,
    fit_function,
    needs_help,
)
from app.modules.data_sources.understanding_bookings import (
    channel_by_taught,
    check_stay,
    identifier_by_context,
    lone_total_is_room_revenue,
)
from app.modules.data_sources.understanding_costs import (
    CostsPlan,
    category_question,
    lexicon_labels,
    plan_costs,
    promote,
)
from app.modules.data_sources.understanding_labor import (
    column_labels,
    known_labels,
    label_question,
    lexicon_roles,
    names_a_department,
    plan_labor,
)
from app.modules.data_sources.understanding_redaction import guard_for, redact_inspection
from app.modules.data_sources.understanding_types import (
    Blocker,
    BlockerCode,
    Choice,
    Detection,
    DocumentSummary,
    DomainScoreInfo,
    LabelCount,
    Origin,
    OriginKind,
    Question,
    QuestionKind,
    Recognized,
    SheetSummary,
    SkippedSummary,
    TableSummary,
    UnderstandingInfo,
    UnderstandingLevel,
)
from app.modules.document_understanding.apply import (
    DEPARTMENT_HEADERS,
    LayoutTable,
    open_layout_table,
)
from app.modules.document_understanding.document import (
    DocumentUnderstanding,
    Selection,
    SheetRole,
    understand,
)
from app.modules.document_understanding.grid import WorkbookScan, scan_workbook
from app.modules.document_understanding.layout import GridLayout, LayoutSpec
from app.modules.document_understanding.lexicon import SUMMARY_SHEET_WORDS
from app.modules.document_understanding.redaction import PersonalDataGuard
from app.modules.document_understanding.structure import RowKind
from app.modules.document_understanding.text import fold, has_word
from app.modules.document_understanding.values import text_of
from app.modules.ingestion.models import DataSource, DataSourceDomain

logger = logging.getLogger(__name__)

_SEMANTICS: dict[DataSourceDomain, DomainSem] = {
    DataSourceDomain.BOOKINGS: BOOKINGS,
    DataSourceDomain.LABOR: LABOR,
    DataSourceDomain.COSTS: COSTS,
}
_LEVEL = {Level.HIGH: SuggestionLevel.RECOGNIZED, Level.MEDIUM: SuggestionLevel.TO_CHECK}
_EXAMPLE_FIELDS_HIDDEN = {"PERSON", "CONTACT", "IDENTITY"}
_MAX_TABLES_OFFERED = 4
# The table the file is read as can leave real data out: another sheet (or block) that holds data,
# has records enough to matter and looks like data of the kind the person chose. The ranking picks
# the BEST table; it cannot prove the others are irrelevant - so the person is asked (a summary, a
# legend, a hidden sheet, an example of two rows or a table of another kind never counts).
_MIN_LEFT_OUT_RECORDS = 4
_LEFT_OUT_SCORE_SHARE = 0.5
# Any Monday: only used to read the NAMES the columns of an unpivoted grid get.
_SIGNATURE_WEEK = date(2001, 1, 1)


class UnderstandAnswers(BaseModel):
    """What the person has already said, so a question is never asked twice. Nothing here is a
    value from the file except the words the person taught."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = Field(default=None, max_length=200)
    table_key: str | None = Field(default=None, max_length=300)
    period_start: date | None = None
    grid_hours: Literal["planned_hours", "actual_hours"] | None = None
    # Costs: is the amount NET (what NINFA works with) or does it include VAT?
    amount_basis: Literal["NET", "GROSS"] | None = None
    # How the file writes dates (03/10/2026) and numbers (1,234) when its values cannot prove it.
    date_order: Literal["DMY", "MDY"] | None = None
    decimal_style: Literal["COMMA", "POINT"] | None = None
    # The department comes from the title (the person confirmed it).
    department_from: Literal["SECTION", "SHEET", "TITLE"] | None = None
    # One department for ALL the rows (a NINFA category code).
    department_value: str | None = Field(default=None, max_length=40)
    # A column the person classified: {"Ore": "planned_hours"}.
    column_fields: dict[str, str] = Field(default_factory=dict, max_length=60)
    # What the person taught: {"role_mapping": {"HK": "HOUSEKEEPING"}}.
    labels: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=4)


@dataclass(slots=True)
class _Candidate:
    selection: Selection
    table: LayoutTable
    samples: list[ColumnSample]
    scores: dict[DataSourceDomain, DomainScore]
    proposals: dict[DataSourceDomain, Proposal]


class UnderstandingService:
    def __init__(
        self,
        session: Session,
        tenant: TenantContext,
        smart: SmartImportService,
        resolver: ImportUnderstandingResolver | None = None,
    ) -> None:
        self._session = session
        self._tenant = tenant
        self._smart = smart
        self._resolver = resolver

    # --- public -----------------------------------------------------------------------------------

    def understand(
        self,
        domain: DataSourceDomain,
        filename: str,
        content: bytes,
        answers: UnderstandAnswers,
        confirmed_domain: bool,
        source: DataSource | None,
        already_imported: bool,
        currency: str | None = None,
    ) -> FileInspection:
        adapter = self._smart.domain(domain)
        sem = _SEMANTICS[domain]
        try:
            scan = scan_workbook(content, filename)
        except BookingImportError as error:
            return FileInspection(domain, problem=problem_of_error(error))

        saved_config, saved_decision_layout = self._saved(adapter, source)
        taught = {
            name: dict(document) for name, document in self._saved_labels(adapter, source).items()
        }
        base = self._base_layout(answers, saved_decision_layout)
        document = understand(scan, base)
        if document.chosen is None:
            return redact_inspection(
                self._without_table(domain, scan, document, already_imported),
                PersonalDataGuard(),
            )

        candidates = self._candidates(content, filename, document, domain)
        detection = self._detect(candidates)
        chosen = self._pick(candidates, domain, answers)
        questions: list[Question] = []
        blockers: list[Blocker] = []
        questions.extend(self._domain_question(detection, domain, confirmed_domain))
        table_question = self._table_question(candidates, chosen, domain, answers, document)
        if table_question is not None:
            questions.append(table_question)

        # --- the layout this kind of document needs, and the table it gives -----------------------
        layout = base.model_copy(
            update={"table_key": answers.table_key} if answers.table_key else {}
        )
        proposal = chosen.proposals[domain]
        # --- Source Learning: what a PERSON confirmed about this source, where the file agrees.
        # A memory is evidence, never authority: each column the person decided is reused only if
        # the current document still proves it (see `source_learning`); the engine's own reading of
        # THIS file, and its values, always win over the memory.
        # A source can remember several recurring structures (the PMS export, an OTA export, an
        # internal report): the file is matched with ALL of them and belongs to one only if that
        # one explains it clearly better than the others; when it cannot be told, nothing is reused.
        store = self._learning(adapter, saved_config)
        views = column_views(sem, proposal)
        choice = choose_family(store, views, match_source)
        memory, match = choice.memory, choice.match
        reuse = memory is not None and match is not None and reusable(memory, match)
        remembered = dict(match.proven) if reuse and match is not None else {}
        # (what the person answers NOW wins over what they answered before)
        asked_fields = {**remembered, **dict(answers.column_fields)}
        effective = self._with_kept_answers(
            answers, domain, memory, match, reuse, _with_answers(proposal, asked_fields)
        )
        taught_roles = known_labels(
            dict(taught.get("role_mapping", {})), answers.labels.get("role_mapping", {})
        )
        if domain == DataSourceDomain.LABOR:
            plan = plan_labor(
                scan=scan,
                document=document,
                selection=chosen.selection,
                base=layout,
                proposal=_with_answers(proposal, asked_fields),
                taught=taught_roles,
                asked_department=effective.department_value,
                asked_department_from=answers.department_from,
                asked_grid_hours=answers.grid_hours,
                asked_period=answers.period_start is not None,
            )
            layout = plan.layout
            questions.extend(plan.questions)
            blockers.extend(plan.blockers)
            origin, origin_level = plan.department_origin, plan.department_level
            department_words = plan.words
        else:
            origin, origin_level = None, None
            department_words = ()

        wanted_layout = layout
        table, built_layout = self._table_for(
            content, filename, document, chosen.selection, layout, chosen.table
        )
        layout = built_layout
        samples = sample_columns(table)
        proposal = propose(sem, samples, excluded_reason=self._excluded(domain))
        if domain == DataSourceDomain.BOOKINGS:
            proposal = identifier_by_context(lone_total_is_room_revenue(proposal))
            proposal = channel_by_taught(proposal, frozenset(taught.get("channel_mapping", {})))
        overrides = dict(asked_fields)
        if layout.department is not None:
            header = _synthetic_header(table, layout.department.kind)
            if header is not None:
                overrides[header] = "role"
        costs_plan: CostsPlan | None = None
        if domain == DataSourceDomain.COSTS:
            costs_plan = plan_costs(
                proposal=_with_answers(proposal, overrides),
                rows=_sample_rows(table),
                asked_basis=effective.amount_basis,
                asked_columns=asked_fields,
            )
            questions.extend(costs_plan.questions)
            blockers.extend(costs_plan.blockers)
            overrides.update(costs_plan.assigned or {})
        proposal = _with_answers(proposal, overrides)
        if costs_plan is not None:
            proposal = promote(proposal, costs_plan.confirmed)
        if domain == DataSourceDomain.BOOKINGS and not {"check_in", "check_out"} & set(
            overrides.values()
        ):
            # a stay does not end before it begins: when it does on every row, look before going on
            proposal, reversed_dates = check_stay(proposal, _sample_rows(table))
            if reversed_dates is not None:
                questions.append(reversed_dates)

        # The optional assistant: asked only when the rules left something open it could help with,
        # and what it says is a SUGGESTION (MEDIUM at most) that the person still confirms.
        ai_headers: frozenset[str] = frozenset()
        # The rules say the document is ANOTHER kind of data than the card the person came from:
        # they ask which it is, and the model is not asked at all - what the document says wins
        # over anything anyone suggests.
        rules_contradict_card = any(
            q.kind == QuestionKind.DOMAIN and q.candidate is not None for q in questions
        )
        if (
            self._resolver is not None
            and self._resolver.enabled
            and not rules_contradict_card
            and needs_help(proposal, adapter.groups, questions)
        ):
            # where the rules saw nothing at all, the model may say it is ANOTHER kind of data (the
            # person is asked only if it does: the card they chose is what NINFA goes by)
            offered = (
                tuple(kind.value for kind in _SEMANTICS)
                if detection.domain is None and not confirmed_domain
                else ()
            )
            evidence = build_evidence(
                expected=domain,
                semantics=_SEMANTICS,
                sheets=[
                    (
                        s.name,
                        s.role.value if isinstance(s.role, SheetRole) else str(s.role),
                        s.last_row,
                    )
                    for s in document.sheets
                ],
                title=chosen.selection.title,
                proposal=proposal,
                questions=[
                    *questions,
                    *(
                        [Question(id="DOMAIN", kind=QuestionKind.DOMAIN, choices=_domain_choices())]
                        if offered
                        else []
                    ),
                ],
            )
            resolution = self._resolver.resolve(
                evidence,
                fit_function(_SEMANTICS, proposal),
                egress_guard(guard_for(samples, proposal), _SEMANTICS),
            )
            proposal, questions, ai_headers = apply_resolution(
                proposal, questions, resolution, domain, offered
            )
            if ai_headers and {"role", "labor_category"} & set(proposal.assigned()):
                # the assistant found the department column: "which department are all the rows?"
                # is no longer a question
                questions = [
                    q
                    for q in questions
                    if q.kind not in (QuestionKind.DEPARTMENT_ROWS, QuestionKind.DEPARTMENT_CONFIRM)
                ]
        constants: dict[str, str | int] = {}
        if (
            domain == DataSourceDomain.LABOR
            and effective.department_value
            and "role" not in proposal.assigned()
            and "labor_category" not in proposal.assigned()
        ):
            constants["labor_category"] = effective.department_value
        if currency and _has_cost_without_currency(domain, proposal):
            # Costs with no currency in the file: the hotel's own currency, said so on screen.
            constants["currency"] = currency

        decision_labels = {name: dict(words) for name, words in answers.labels.items() if words}
        if domain == DataSourceDomain.COSTS and "cost_category" in proposal.assigned():
            known_categories = known_labels(
                dict(taught.get("category_mapping", {})), answers.labels.get("category_mapping", {})
            )
            words = lexicon_labels(
                column_labels(samples[proposal.assigned()["cost_category"].position]),
                known_categories,
            )
            if words:
                decision_labels["category_mapping"] = {
                    **words,
                    **decision_labels.get("category_mapping", {}),
                }

        if domain == DataSourceDomain.LABOR:
            role_column = proposal.assigned().get("role")
            lexicon = lexicon_roles(
                column_labels(samples[role_column.position])
                if role_column is not None
                else department_words,
                taught_roles,
            )
            if lexicon:
                decision_labels["role_mapping"] = {
                    **lexicon,
                    **decision_labels.get("role_mapping", {}),
                }

        decision = MappingInput(
            sheet_name=None,
            layout=layout if _has_layout(layout) else LayoutSpec(),
            columns=[ColumnChoice(header=c.header, field=c.field) for c in proposal.columns],
            constants=constants,
            labels=decision_labels,
            date_order=answers.date_order,
            decimal_style=answers.decimal_style,
            smart_import=SmartImportDecision(
                answers=answers.model_dump(mode="json", exclude_defaults=True),
                confirmed_domain=confirmed_domain,
            ),
        )
        check = self._smart.check(domain, decision)

        # --- what is still missing, as questions or as an honest "this is not in the file" --------
        extra_questions, extra_blockers = self._missing(
            domain, proposal, check.missing, layout, chosen.selection
        )
        questions.extend(extra_questions)
        blockers.extend(extra_blockers)
        # A column that is clearly hours / an amount but not WHICH, or that says the same as
        # another column: a question - or, for money, the matching screen - never a quiet guess.
        ambiguity, hold = _ambiguity_questions(sem, adapter.groups, proposal)
        # (a document that points at no kind of data is never imported without a person, even if
        # its columns happen to fit the card: the card alone is not evidence)
        hold = hold or (detection.domain is None and not confirmed_domain)
        questions.extend(ambiguity)
        value_questions = self._value_questions(domain, proposal, samples, taught, answers)
        questions.extend(value_questions)
        if reuse and match is not None:
            questions.extend(_conflict_questions(match, answers, questions))
        proposal = _with_known_departments(proposal, samples, taught_roles, value_questions)

        # --- the profile, the people, the explanation ---------------------------------------------
        # A grid whose week is not known yet is judged by the columns it WILL have (its names do
        # not depend on the week), so the way it was read last time is still recognised.
        signature = table
        if wanted_layout.grid is not None and layout.grid is None:
            signature = self._signature_table(
                content, filename, document, chosen.selection, wanted_layout, table
            )
        profile = self._smart.profile_info(adapter, source, signature)
        # What a PERSON confirmed about this source, still proven by THIS file, with no column
        # renamed: the file is a source the person has taught (a memory is evidence, not authority:
        # the engine cannot teach itself, and what the person says now is never overridden).
        recognized_by_family = (
            reuse
            and match is not None
            and not match.renamed
            and match.drift in (Drift.NONE, Drift.COSMETIC, Drift.ADDITIVE)
            and not answers.column_fields
        )
        recognized_by_profile = (
            recognized_by_family
            and profile.status == ProfileStatus.RECOGNIZED
            and saved_config is not None
            and profile.mapping is not None
            # ...and only for the family whose import wrote that saved matching: another family's
            # matching is never applied to this file
            and memory is not None
            and store is not None
            and memory.id == store.current
        )
        if recognized_by_profile and profile.mapping is not None:
            # A source whose files have been read before keeps reading them the same way.
            kept = profile.mapping.layout or LayoutSpec()
            decision = profile.mapping.model_copy(
                update={
                    "layout": kept.model_copy(
                        update={
                            "period_start": answers.period_start,
                            "table_key": answers.table_key,
                        }
                    ),
                    "labels": {n: dict(w) for n, w in answers.labels.items() if w},
                    # the decision is still the server's own reading, to be verified like any other
                    "smart_import": SmartImportDecision(
                        answers=answers.model_dump(mode="json", exclude_defaults=True),
                        confirmed_domain=confirmed_domain,
                    ),
                }
            )
            check = self._smart.check(domain, decision)
        if not recognized_by_profile and not blockers:
            decision = self._with_kept_formats(adapter, decision, samples, memory, match, reuse)
            formats = self._smart.formats_of(adapter, decision, samples)
            if formats.problems:
                blockers.append(Blocker(BlockerCode.MIXED_FORMATS))
            else:
                questions.extend(_format_questions(formats, decision))
                # (the labels of a department column are asked about as labels, not twice)
                skip: set[str] = set()
                if any(q.kind == QuestionKind.VALUE_LABELS for q in questions):
                    skip.add("role")
                if any(q.kind == QuestionKind.AMOUNT_BASIS for q in questions):
                    skip.add("line_total")  # the amount is asked about as an amount, not twice
                if any(q.kind == QuestionKind.DATES_REVERSED for q in questions):
                    skip.update({"check_in", "check_out"})  # looked at together, not one by one
                questions.extend(_confirm_questions(adapter.groups, proposal, skip))
        questions = _without_premature(_domain_first(questions), blockers)
        people = self._count_people(table, proposal) if domain == DataSourceDomain.LABOR else None
        recognized = self._recognized(
            proposal,
            decision,
            layout,
            origin,
            origin_level,
            recognized_by_profile,
            answers,
            table,
            ai_headers,
            samples,
            frozenset(remembered),
        )
        level = self._level(
            adapter,
            proposal,
            decision,
            check.valid,
            questions,
            blockers,
            recognized_by_profile,
            origin_level,
            hold and not recognized_by_family,
        )
        columns = tuple(
            self._column_info(sample, cp)
            for sample, cp in zip(samples, proposal.columns, strict=True)
        )
        understanding = UnderstandingInfo(
            level=level,
            detection=_detection_info(detection, domain),
            document=replace(
                self._document_summary(scan, document, chosen.selection, layout),
                amounts=costs_plan.amounts if costs_plan is not None else None,
            ),
            recognized=tuple(recognized),
            people=people,
            questions=tuple(_dedupe(questions)),
            blockers=tuple(blockers),
        )
        complete = check.valid
        canonical = complete and all(
            normalize_header(c.header) == normalize_header(c.field)
            for c in columns
            if c.field is not None
        )
        # The last gate: nothing personal in this file goes out, whatever put it in the answer.
        return redact_inspection(
            FileInspection(
                domain,
                file_type="XLSX" if scan.file_type == "xlsx" else "CSV",
                sheet_name=table.sheet_name,
                columns=columns,
                fields=tuple(adapter.fields),
                requirement_groups=tuple(adapter.groups),
                suggestion_complete=complete,
                already_canonical=canonical,
                profile=profile,
                already_imported=already_imported,
                understanding=understanding,
                proposal=decision,
                learning=LearningInfo(
                    memory=memory,
                    match=match,
                    family=choice.family,
                    known=choice.known,
                    eligible=choice.eligible,
                    ambiguous=choice.ambiguous,
                    reused=tuple(sorted(remembered)),
                    shape=tuple(shape_of(views)),
                    engine=tuple((v.header, v.field, v.level) for v in views),
                ),
            ),
            guard_for(samples, proposal),
        )

    # --- the saved configuration ------------------------------------------------------------------

    def _saved(
        self, adapter: FileDomain, source: DataSource | None
    ) -> tuple[Any | None, LayoutSpec | None]:
        profile = adapter.get_profile(source.id) if source is not None else None
        if profile is None:
            return None, None
        try:
            config = adapter.parse_config(profile.documents)
        except (AppError, ValueError):
            return None, None
        return config, adapter.format_of(config).layout

    @staticmethod
    def _learning(adapter: FileDomain, config: Any | None) -> Learning | None:
        """What Source Learning remembers of this source: its families (None: nothing, or not
        readable). A family that says it belongs to another kind of data is never applied here."""
        if config is None:
            return None
        store = parse_learning(adapter.format_of(config).learning)
        return None if store is None else store.of_domain(adapter.domain.value)

    @staticmethod
    def _with_kept_answers(
        answers: UnderstandAnswers,
        domain: DataSourceDomain,
        memory: Memory | None,
        match: Any,
        reuse: bool,
        proposal: Proposal,
    ) -> UnderstandAnswers:
        """The person's answers, plus what they said before and still holds for this file: the
        department of ALL the rows (only if no column says it) and whether the amounts are net."""
        if memory is None or match is None or not reuse:
            return answers
        kept = kept_answers(memory, match)
        update: dict[str, Any] = {}
        if (
            domain == DataSourceDomain.LABOR
            and answers.department_value is None
            and kept.get("department_value")
            and not {"role", "labor_category"} & set(proposal.assigned())
        ):
            update["department_value"] = kept["department_value"]
        if (
            domain == DataSourceDomain.COSTS
            and answers.amount_basis is None
            and kept.get("amount_basis") in ("NET", "GROSS")
        ):
            update["amount_basis"] = kept["amount_basis"]
        return answers.model_copy(update=update) if update else answers

    def _with_kept_formats(
        self,
        adapter: FileDomain,
        decision: MappingInput,
        samples: list[ColumnSample],
        memory: Memory | None,
        match: Any,
        reuse: bool,
    ) -> MappingInput:
        """How the person said this source writes dates and numbers, when the values themselves
        cannot prove it - and only if the file still reads cleanly that way."""
        if memory is None or match is None or not reuse:
            return decision
        kept = kept_answers(memory, match)
        update: dict[str, Any] = {}
        if decision.date_order is None and kept.get("date_order") in ("DMY", "MDY"):
            update["date_order"] = kept["date_order"]
        if decision.decimal_style is None and kept.get("decimal_style") in ("COMMA", "POINT"):
            update["decimal_style"] = kept["decimal_style"]
        if not update or not self._smart.formats_of(adapter, decision, samples).unresolved:
            return decision
        trial = decision.model_copy(update=update)
        return trial if not self._smart.formats_of(adapter, trial, samples).problems else decision

    def _saved_labels(
        self, adapter: FileDomain, source: DataSource | None
    ) -> dict[str, dict[str, str]]:
        return {
            name: {k: str(v) for k, v in document.items()}
            for name, document in self._smart.preserved_documents(adapter, source).items()
        }

    @staticmethod
    def _base_layout(answers: UnderstandAnswers, saved: LayoutSpec | None) -> LayoutSpec:
        sheets = [answers.sheet_name] if answers.sheet_name else (saved.sheets if saved else [])
        grid = (
            GridLayout(hours_field=answers.grid_hours)
            if answers.grid_hours
            else (saved.grid if saved else None)
        )
        return LayoutSpec(
            sheets=list(sheets),
            table_key=answers.table_key,
            department=saved.department if saved else None,
            grid=grid,
            period_start=answers.period_start,
        )

    # --- candidates and the kind of data ----------------------------------------------------------

    def _candidates(
        self,
        content: bytes,
        filename: str,
        document: DocumentUnderstanding,
        domain: DataSourceDomain,
    ) -> list[_Candidate]:
        found: list[_Candidate] = []
        for selection in document.selections[:_MAX_TABLES_OFFERED]:
            plain = open_layout_table(
                content, filename, LayoutSpec(), document=replace(document, chosen=selection)
            )
            samples = sample_columns(plain)
            context = [*selection.preamble, *(t.sheet for t in selection.tables if t.sheet)]
            scores: dict[DataSourceDomain, DomainScore] = {}
            proposals: dict[DataSourceDomain, Proposal] = {}
            for kind, sem in _SEMANTICS.items():
                adapter = self._smart.domain(kind)
                proposals[kind] = propose(sem, samples, excluded_reason=self._excluded(kind))
                scores[kind] = score_domain(
                    sem, adapter.groups, proposals[kind], context, _supplied(kind, selection)
                )
            found.append(_Candidate(selection, plain, samples, scores, proposals))
        return found

    @staticmethod
    def _excluded(domain: DataSourceDomain) -> Any:
        if domain == DataSourceDomain.LABOR:
            return hourly_or_known_exclusion
        return lambda _header: None

    @staticmethod
    def _detect(candidates: list[_Candidate]) -> DomainVerdict:
        best: dict[DataSourceDomain, DomainScore] = {}
        for candidate in candidates:
            for kind, score in candidate.scores.items():
                if kind not in best or score.score > best[kind].score:
                    best[kind] = score
        return verdict(best)

    @staticmethod
    def _pick(
        candidates: list[_Candidate], domain: DataSourceDomain, answers: UnderstandAnswers
    ) -> _Candidate:
        if answers.table_key:
            keyed = next((c for c in candidates if c.selection.key == answers.table_key), None)
            if keyed is not None:
                return keyed
        return max(candidates, key=lambda c: (c.scores[domain].score, c.selection.value))

    @staticmethod
    def _domain_question(
        detection: DomainVerdict, domain: DataSourceDomain, confirmed: bool
    ) -> list[Question]:
        # The card the person came from is a weak prior: it is argued with only when the document
        # points at ANOTHER kind of data. A document that points nowhere is not asked "what is
        # this?" - the answer would change nothing; it is just not enough to import (see `_level`).
        if confirmed:
            return []
        if (
            detection.domain is not None
            and detection.level in (Level.HIGH, Level.MEDIUM)
            and detection.domain != domain
        ):
            return [
                Question(
                    id="DOMAIN",
                    kind=QuestionKind.DOMAIN,
                    candidate=detection.domain.value,
                    choices=_domain_choices(),
                )
            ]
        return []

    @staticmethod
    def _left_out(
        candidates: list[_Candidate],
        chosen: _Candidate,
        domain: DataSourceDomain,
        document: DocumentUnderstanding,
    ) -> list[_Candidate]:
        """The other tables of the file that are real data of the kind chosen and that the chosen
        table leaves out: every sheet they sit on holds data (not a summary, hidden or empty), they
        have records enough to matter and the kind of data fits at least half as well as the
        chosen table's. A file that leaves such a table out is never read without asking."""
        roles = {sheet.name: sheet.role for sheet in document.sheets}
        found: list[_Candidate] = []
        for candidate in candidates:
            if candidate is chosen:
                continue
            # a sheet that is hidden or empty, or that SAYS it is a summary, is not data left out.
            # (A sheet only called "summary" for being much smaller than the best table is: size
            # alone does not prove it is one.)
            if any(
                roles.get(t.sheet) not in (SheetRole.DATA, SheetRole.SUMMARY)
                or has_word(t.sheet, SUMMARY_SHEET_WORDS)
                for t in candidate.selection.tables
            ):
                continue
            if sum(t.data_rows for t in candidate.selection.tables) < _MIN_LEFT_OUT_RECORDS:
                continue
            if candidate.scores[domain].score < _LEFT_OUT_SCORE_SHARE * chosen.scores[domain].score:
                continue
            found.append(candidate)
        return found

    @staticmethod
    def _table_question(
        candidates: list[_Candidate],
        chosen: _Candidate,
        domain: DataSourceDomain,
        answers: UnderstandAnswers,
        document: DocumentUnderstanding,
    ) -> Question | None:
        if answers.table_key or len(candidates) < 2:
            return None
        ranked = sorted(candidates, key=lambda c: -c.scores[domain].score)
        top, second = ranked[0], ranked[1]
        comparable = (
            document.ambiguous and top.scores[domain].score - second.scores[domain].score < 0.15
        )
        if not comparable and not UnderstandingService._left_out(
            candidates, chosen, domain, document
        ):
            return None
        return Question(
            id="TABLE",
            kind=QuestionKind.TABLE,
            choices=tuple(
                Choice(
                    c.selection.key,
                    count=sum(t.data_rows for t in c.selection.tables),
                    sheets=tuple(t.sheet for t in c.selection.tables if t.sheet),
                    columns=tuple(col.label for col in c.selection.first.columns[:6]),
                    title=_short(
                        c.selection.first.preamble[-1] if c.selection.first.preamble else None
                    ),
                    first_row=c.selection.first.first_row,
                )
                for c in ranked[:_MAX_TABLES_OFFERED]
            ),
        )

    # --- the table, under the layout the document needs -------------------------------------------

    def _table_for(
        self,
        content: bytes,
        filename: str,
        document: DocumentUnderstanding,
        selection: Selection,
        layout: LayoutSpec,
        plain: LayoutTable,
    ) -> tuple[LayoutTable, LayoutSpec]:
        try:
            return (
                open_layout_table(
                    content, filename, layout, document=replace(document, chosen=selection)
                ),
                layout,
            )
        except BookingImportError:
            # A grid whose week is not known yet: the plain table still shows the person the file.
            plain_layout = layout.model_copy(update={"grid": None})
            return plain, plain_layout

    @staticmethod
    def _signature_table(
        content: bytes,
        filename: str,
        document: DocumentUnderstanding,
        selection: Selection,
        layout: LayoutSpec,
        plain: LayoutTable,
    ) -> LayoutTable:
        try:
            return open_layout_table(
                content,
                filename,
                layout.model_copy(update={"period_start": _SIGNATURE_WEEK}),
                document=replace(document, chosen=selection),
            )
        except BookingImportError:
            return plain

    # --- what is missing --------------------------------------------------------------------------

    @staticmethod
    def _missing(
        domain: DataSourceDomain,
        proposal: Proposal,
        missing: tuple[tuple[str, ...], ...],
        layout: LayoutSpec,
        selection: Selection,
    ) -> tuple[list[Question], list[Blocker]]:
        questions: list[Question] = []
        blockers: list[Blocker] = []
        lacking: list[tuple[str, ...]] = []
        for group in missing:
            if set(group) == {"role", "labor_category"}:
                continue  # the department question (or context) already covers it
            if (
                domain == DataSourceDomain.LABOR
                and selection.day_grid is not None
                and (group == ("work_date",) or set(group) == {"planned_hours", "actual_hours"})
            ):
                continue  # the grid (its hours, its week) answers it, once asked
            if any(
                c.ambiguous_group and set(c.ambiguous_fields) & set(group) for c in proposal.columns
            ):
                continue  # a column that may be it: asked about (or matched by hand), not "missing"
            if (
                domain == DataSourceDomain.LABOR
                and group == ("work_date",)
                and layout.grid is None
                and selection.day_grid is None
                and any(
                    c.field in {"planned_hours", "actual_hours"} or c.ambiguous_group == "HOURS"
                    for c in proposal.columns
                )
            ):
                blockers.append(Blocker(BlockerCode.PERIOD_SUMMARY_ONLY))
                continue
            lacking.append(tuple(group))
        if lacking:
            blockers.append(Blocker(BlockerCode.MISSING_REQUIRED, tuple(lacking)))
        return questions, blockers

    def _value_questions(
        self,
        domain: DataSourceDomain,
        proposal: Proposal,
        samples: list[ColumnSample],
        taught: Mapping[str, Mapping[str, str]],
        answers: UnderstandAnswers,
    ) -> list[Question]:
        questions: list[Question] = []
        assigned = proposal.assigned()
        if domain == DataSourceDomain.LABOR and "role" in assigned:
            known = known_labels(
                dict(taught.get("role_mapping", {})), answers.labels.get("role_mapping", {})
            )
            question = label_question(
                column_labels(samples[assigned["role"].position]), known, lexicon=True
            )
            if question is not None:
                questions.append(question)
        if domain == DataSourceDomain.COSTS and "cost_category" in assigned:
            known = known_labels(
                dict(taught.get("category_mapping", {})), answers.labels.get("category_mapping", {})
            )
            question = category_question(
                column_labels(samples[assigned["cost_category"].position]), known
            )
            if question is not None:
                questions.append(question)
        if domain == DataSourceDomain.BOOKINGS and "status" in assigned:
            known = known_labels(
                dict(taught.get("status_mapping", {})), answers.labels.get("status_mapping", {})
            )
            unknown = [
                (label, count)
                for label, count in column_labels(samples[assigned["status"].position])
                if normalize_key(label) not in BUILTIN_STATUS_KEYS
                and normalize_key(label) not in known
            ]
            if unknown:
                questions.append(
                    Question(
                        id="LABELS:status_mapping",
                        kind=QuestionKind.VALUE_LABELS,
                        document="status_mapping",
                        field="status",
                        choices=tuple(
                            Choice(s)
                            for s in (
                                "CONFIRMED",
                                "CANCELLED",
                                "NO_SHOW",
                                "CHECKED_IN",
                                "CHECKED_OUT",
                            )
                        ),
                        labels=tuple(LabelCount(label, count) for label, count in unknown[:12]),
                        total_labels=len(unknown),
                    )
                )
        return questions

    # --- the explanation --------------------------------------------------------------------------

    def _recognized(
        self,
        proposal: Proposal,
        decision: MappingInput,
        layout: LayoutSpec,
        origin: Origin | None,
        origin_level: Level | None,
        by_profile: bool,
        answers: UnderstandAnswers,
        table: LayoutTable,
        ai_headers: frozenset[str] = frozenset(),
        samples: Sequence[ColumnSample] = (),
        remembered: frozenset[str] = frozenset(),
    ) -> list[Recognized]:
        out: list[Recognized] = []
        decided = {c.header: c.field for c in decision.columns if c.field is not None}
        for column in proposal.columns:
            field = decided.get(column.header)
            if field is None:
                continue
            kind = OriginKind.PROFILE if by_profile else OriginKind.COLUMN
            if column.header in answers.column_fields:
                kind = OriginKind.USER
            elif column.header in remembered:
                kind = (
                    OriginKind.PROFILE
                )  # what the person confirmed before, and the file still proves
            elif column.header in ai_headers and not by_profile:
                kind = OriginKind.ASSISTANT
            example = None if column.locked or column.pii else _example(samples, column)
            if layout.department is not None and column.header == _synthetic_header(
                table, layout.department.kind
            ):
                out.append(
                    Recognized(
                        field,
                        origin or Origin(OriginKind.SECTION),
                        (origin_level or Level.HIGH).value,
                        example,
                    )
                )
                continue
            out.append(
                Recognized(
                    field,
                    Origin(kind, column.header),
                    "HIGH"
                    if by_profile or column.header in remembered
                    else (column.level or Level.LOW).value,
                    example,
                )
            )
        for key, value in decision.constants.items():
            if by_profile:
                kind = OriginKind.PROFILE
            else:
                kind = OriginKind.PROPERTY if key == "currency" else OriginKind.USER
            out.append(Recognized(key, Origin(kind), "HIGH", str(value)))
        return out

    @staticmethod
    def _level(
        adapter: FileDomain,
        proposal: Proposal,
        decision: MappingInput,
        valid: bool,
        questions: list[Question],
        blockers: list[Blocker],
        by_profile: bool,
        context_level: Level | None,
        hold: bool = False,
    ) -> UnderstandingLevel:
        hard = {
            BlockerCode.NO_TABLE,
            BlockerCode.PERIOD_SUMMARY_ONLY,
            BlockerCode.GRID_NOT_SUPPORTED,
            BlockerCode.GRID_NOT_HOURS,
            BlockerCode.AMOUNT_NOT_NET,
            BlockerCode.MIXED_FORMATS,
        }
        if any(b.code in hard for b in blockers):
            return UnderstandingLevel.BLOCKED
        if blockers:
            return UnderstandingLevel.MANUAL
        if questions:
            return UnderstandingLevel.ASK
        if not valid or hold:
            return UnderstandingLevel.MANUAL
        if by_profile:
            return UnderstandingLevel.READY
        decided = {c.field: c for c in proposal.columns if c.field is not None}
        for group in adapter.groups:
            fields = [f for f in group if f in decided]
            if fields:
                if not all(decided[f].level == Level.HIGH for f in fields):
                    return UnderstandingLevel.MANUAL
            elif not any(f in decision.constants for f in group) and context_level != Level.HIGH:
                return UnderstandingLevel.MANUAL
        return UnderstandingLevel.READY

    @staticmethod
    def _column_info(sample: ColumnSample, column: ColumnProposal) -> ColumnInfo:
        hidden = column.locked in _EXAMPLE_FIELDS_HIDDEN or column.pii is not None
        text_values = [value for value in sample.values if isinstance(value, str)]
        order = date_order_of(sample.values) if text_values else None
        style = number_style(sample.values) if text_values else None
        return ColumnInfo(
            position=sample.position,
            header=sample.header,
            examples=() if hidden else sample.examples,
            field=column.field,
            level=_LEVEL.get(column.level) if column.level else None,
            not_used_reason=column.locked,
            date_order=order.value if order and order != DateOrder.UNKNOWN else None,
            number_style=style.value if style and style != NumberStyle.UNKNOWN else None,
        )

    @staticmethod
    def _count_people(table: SourceTable, proposal: Proposal) -> int | None:
        """Distinct people in the file. Counted in memory from the name columns that are left out of
        the import, and kept nowhere: only the number leaves this function."""
        positions = [
            c.position for c in proposal.columns if c.pii is not None and c.locked == "PERSON"
        ]
        if not positions:
            return None
        seen: set[tuple[str, ...]] = set()
        for row in table.rows():
            key = tuple(fold(text_of(row.cells[p])) for p in positions if p < len(row.cells))
            if any(key):
                seen.add(key)
        return len(seen) or None

    @staticmethod
    def _document_summary(
        scan: WorkbookScan,
        document: DocumentUnderstanding,
        selection: Selection,
        layout: LayoutSpec,
    ) -> DocumentSummary:
        table = selection.first
        counts = Counter(s.kind for t in selection.tables for s in t.skipped)
        states = [t.state for tab in selection.tables for t in tab.totals]
        totals: str | None = None
        if states:
            totals = (
                "MISMATCH"
                if "MISMATCH" in states
                else (
                    "PARTIAL"
                    if "PARTIAL" in states
                    else ("MATCH" if all(s == "MATCH" for s in states) else "UNVERIFIED")
                )
            )
        period = selection.period
        return DocumentSummary(
            file_type="XLSX" if scan.file_type == "xlsx" else "CSV",
            sheets=tuple(
                SheetSummary(
                    s.name,
                    s.role.value if isinstance(s.role, SheetRole) else str(s.role),
                    s.last_row,
                )
                for s in document.sheets
            ),
            table=TableSummary(
                sheets=tuple(t.sheet for t in selection.tables if t.sheet),
                header_rows=table.header_rows,
                first_row=table.first_row,
                last_row=table.last_row,
                data_rows=sum(t.data_rows for t in selection.tables),
                partition=selection.partition,
                renamed_headers=table.renamed_headers,
            ),
            title=selection.title,
            period_start=period.start.isoformat() if period else None,
            period_end=period.end.isoformat() if period and period.end else None,
            skipped=SkippedSummary(
                totals=counts.get(RowKind.TOTAL, 0),
                # (a header written again on a new page is a line left out, like a note)
                notes=counts.get(RowKind.NOTE, 0) + counts.get(RowKind.HEADER, 0),
                sections=counts.get(RowKind.SECTION, 0),
            ),
            totals=totals,
            day_grid=selection.day_grid is not None or layout.grid is not None,
        )

    def _without_table(
        self,
        domain: DataSourceDomain,
        scan: WorkbookScan,
        document: DocumentUnderstanding,
        already_imported: bool,
    ) -> FileInspection:
        adapter = self._smart.domain(domain)
        info = UnderstandingInfo(
            level=UnderstandingLevel.BLOCKED,
            detection=Detection(None, "LOW", (), domain.value),
            document=DocumentSummary(
                file_type="XLSX" if scan.file_type == "xlsx" else "CSV",
                sheets=tuple(
                    SheetSummary(s.name, s.role.value, s.last_row) for s in document.sheets
                ),
            ),
            blockers=(Blocker(BlockerCode.NO_TABLE),),
        )
        return FileInspection(
            domain,
            file_type="XLSX" if scan.file_type == "xlsx" else "CSV",
            problem=ImportProblem.NO_ROWS,
            fields=tuple(adapter.fields),
            requirement_groups=tuple(adapter.groups),
            already_imported=already_imported,
            understanding=info,
        )


# --- helpers --------------------------------------------------------------------------------------


# A column NINFA is only fairly sure about is confirmed with ONE question - unless there are so many
# that the person is better off with the matching screen in front of them.
_MAX_CONFIRMATIONS = 2
# ...and so is a column that may be one of two things, or one of two look-alikes.
_MAX_AMBIGUITY_QUESTIONS = 3
_AMOUNT_CHECK_ROWS = 400


def _ambiguity_questions(
    sem: DomainSem, groups: Sequence[tuple[str, ...]], proposal: Proposal
) -> tuple[list[Question], bool]:
    """One question per column that may be something the import needs and that NINFA will not
    decide: a column that is "hours" or "an amount" without saying which, or one of several columns
    that say the same thing about one field ("Ore previste" / "Ore previste (rev.)").

    Money is never put as a yes/no: when the columns in competition are amounts the import needs,
    nothing is asked and the second value says so - the person matches the columns by hand,
    seeing all of them. So it is when there would be more questions than a person should be
    asked one by one (the matching screen is better then). What the import does not need (a
    column nobody required) is left out, as before."""
    needed = {field for group in groups for field in group}
    questions: list[Question] = []
    hold = False
    for column in proposal.columns:
        if not column.ambiguous_group:
            continue
        fields = tuple(column.ambiguous_fields)
        if not needed & set(fields):
            continue
        if column.ambiguous_group == CONTESTED and fields[0] in sem.financial:
            hold = True
            continue
        question = Question(
            id=f"MEANING:{column.header}",
            kind=QuestionKind.COLUMN_MEANING,
            column=column.header,
            choices=tuple(Choice(f) for f in fields),
        )
        if len(fields) == 1:  # "Is «Ore prog.» the planned hours?" - yes, or not this
            question = replace(
                question, field=fields[0], candidate=fields[0], origin=OriginKind.COLUMN
            )
        questions.append(question)
    if len(questions) > _MAX_AMBIGUITY_QUESTIONS:
        return [], True
    return questions, hold


def _confirm_questions(
    groups: Sequence[tuple[str, ...]], proposal: Proposal, skip: set[str]
) -> list[Question]:
    """One question per column a required field rests on whose meaning is likely but not proven
    ("Codice" - is it the reservation code?). Answering "yes" is `column_fields[header] = field`."""
    needed = {field for group in groups for field in group}
    unsure = [
        c
        for c in proposal.columns
        if c.field in needed
        and c.level != Level.HIGH
        and not c.ambiguous_group
        and c.field not in skip
    ]
    if not unsure or len(unsure) > _MAX_CONFIRMATIONS:
        return []
    return [
        Question(
            id=f"CONFIRM:{c.header}",
            kind=QuestionKind.COLUMN_MEANING,
            column=c.header,
            field=c.field,
            candidate=c.field,
            origin=OriginKind.COLUMN,
            choices=(Choice(c.field or ""),),
        )
        for c in unsure
    ]


def _with_known_departments(
    proposal: Proposal,
    samples: Sequence[ColumnSample],
    known: Mapping[str, str],
    asked: Sequence[Question],
) -> Proposal:
    """A department column whose NAME is clear is as sure as its values: when NINFA knows every
    label in it (by its own rules or because the person taught them), nothing is left to doubt."""
    column = proposal.assigned().get("role")
    if (
        column is None
        or column.level == Level.HIGH
        or column.name not in (NameMatch.EXACT, NameMatch.TOKEN)
        or any(q.kind == QuestionKind.VALUE_LABELS for q in asked)
        or label_question(column_labels(samples[column.position]), known, lexicon=True) is not None
    ):
        return proposal
    return Proposal(
        tuple(
            replace(c, level=Level.HIGH) if c.header == column.header else c
            for c in proposal.columns
        )
    )


def _format_questions(formats: Formats, decision: MappingInput) -> list[Question]:
    """How the file writes its dates and numbers, when its own values cannot prove it."""
    questions: list[Question] = []
    for hint in formats.hints:
        column = hint.columns[0] if hint.columns else None
        if hint.question == "DATE_ORDER" and hint.proven is None and decision.date_order is None:
            questions.append(
                Question(
                    id="DATE_ORDER",
                    kind=QuestionKind.DATE_ORDER,
                    column=column,
                    choices=(Choice("DMY"), Choice("MDY")),
                )
            )
        if (
            hint.question == "DECIMAL_STYLE"
            and hint.proven is None
            and decision.decimal_style is None
        ):
            questions.append(
                Question(
                    id="DECIMAL_STYLE",
                    kind=QuestionKind.DECIMAL_STYLE,
                    column=column,
                    choices=(Choice("COMMA"), Choice("POINT")),
                )
            )
    return questions


def _sample_rows(table: SourceTable) -> list[list[Cell]]:
    """The first rows of the table as plain cells (enough to check that the amounts add up)."""
    return [list(row.cells) for row in islice(table.rows(), _AMOUNT_CHECK_ROWS)]


def _has_cost_without_currency(domain: DataSourceDomain, proposal: Proposal) -> bool:
    if domain != DataSourceDomain.LABOR:
        return False
    assigned = set(proposal.assigned())
    return bool({"planned_cost", "actual_cost"} & assigned) and "currency" not in assigned


def _supplied(domain: DataSourceDomain, selection: Selection) -> frozenset[str]:
    """Fields a document supplies without a column of their own: a department that is a line, a
    sheet or the title, the dates and hours of a grid of days."""
    if domain != DataSourceDomain.LABOR:
        return frozenset()
    found: set[str] = set()
    names = [t.sheet for t in selection.tables if t.sheet]
    if (
        selection.first.sections
        or selection.partition
        or any(names_a_department(name) for name in names)
    ):
        found.add("role")
    if selection.day_grid is not None:
        found.update({"work_date", "planned_hours"})
    return frozenset(found)


def _has_layout(layout: LayoutSpec) -> bool:
    return bool(
        layout.sheets or layout.department or layout.grid or layout.table_key or layout.period_start
    )


def _domain_choices() -> tuple[Choice, ...]:
    return tuple(Choice(kind.value) for kind in _SEMANTICS)


def _domain_first(questions: list[Question]) -> list[Question]:
    """A file that looks like ANOTHER kind of data is asked about that, and only that: what else it
    would need depends on the answer (a department for the "staff rows" of a bookings file, the
    basis of an amount that is not a cost). Once the person has said, the rest follows."""
    if any(q.kind == QuestionKind.DOMAIN for q in questions):
        return [q for q in questions if q.kind == QuestionKind.DOMAIN]
    return questions


# What a question about the MEANING of columns and words can change - and nothing else.
_ABOUT_MEANING = frozenset(
    {
        QuestionKind.COLUMN_MEANING,
        QuestionKind.VALUE_LABELS,
        QuestionKind.DEPARTMENT_ROWS,
        QuestionKind.DEPARTMENT_CONFIRM,
    }
)


def _without_premature(questions: list[Question], blockers: list[Blocker]) -> list[Question]:
    """While the file lacks something the import cannot do without (or is a kind of document it
    cannot read), asking what its columns and words mean changes nothing: the person matches the
    columns by hand first, and the questions come back as soon as they can change the result.
    The basis of an amount is kept only when the amount is what is missing (its answer settles
    it)."""
    if not blockers:
        return questions
    amount_is_missing = any(
        ("line_total",) in blocker.groups
        for blocker in blockers
        if blocker.code == BlockerCode.MISSING_REQUIRED
    )
    return [
        q
        for q in questions
        if q.kind not in _ABOUT_MEANING
        and not (q.kind == QuestionKind.AMOUNT_BASIS and not amount_is_missing)
    ]


def _dedupe(questions: list[Question]) -> list[Question]:
    seen: set[str] = set()
    out: list[Question] = []
    for question in questions:
        if question.id not in seen:
            seen.add(question.id)
            out.append(question)
    return out


def _synthetic_header(table: SourceTable, kind: str) -> str | None:
    wanted = DEPARTMENT_HEADERS.get(kind)
    if wanted is None:
        return None
    return next((h for h in table.headers if fold(h).startswith(fold(wanted))), None)


def confirmation_from(answers: UnderstandAnswers, learning: LearningInfo | None) -> Confirmation:
    """How a decision the server made was confirmed. Only what the PERSON answered counts: a file
    the engine read alone is ENGINE (it cannot teach itself), and one the memory pre-answered is
    REUSE (it confirms nothing new)."""
    kept = {
        key: str(value)
        for key, value in (
            ("date_order", answers.date_order),
            ("decimal_style", answers.decimal_style),
            ("amount_basis", answers.amount_basis),
            ("department_value", answers.department_value),
        )
        if value
    }
    engine = {} if learning is None else {h: (f, lv) for h, f, lv in learning.engine}
    # (an answer that only repeats what the engine already read clearly decides nothing)
    classified = frozenset(
        header_key(header)
        for header, field in answers.column_fields.items()
        if engine.get(header) != (field, "HIGH")
    )
    decided = bool(
        classified
        or kept
        or answers.grid_hours
        or answers.department_from
        or answers.table_key
        or answers.sheet_name
    )
    if decided:
        origin = Via.ANSWERS
    elif learning is not None and learning.reused:
        origin = Via.REUSE
    else:
        origin = Via.ENGINE
    shape = () if learning is None else learning.shape
    return Confirmation(
        origin, kept, classified, shape, None if learning is None else learning.family
    )


def _conflict_questions(
    match: SourceMatch, answers: UnderstandAnswers, existing: Sequence[Question]
) -> list[Question]:
    """The file contradicts what a person confirmed about a column that is still there: ask what it
    is now. (A column that turned into personal data is simply not used; a duplicated header is the
    engine's own question.)"""
    taken = {q.id for q in existing}
    out: list[Question] = []
    for conflict in match.conflicts:
        question_id = f"CONFIRM:{conflict.header}"
        if (
            conflict.reason in {"PERSONAL_DATA", "DUPLICATE_HEADER"}
            or conflict.header in answers.column_fields
            or question_id in taken
        ):
            continue
        taken.add(question_id)
        out.append(
            Question(
                id=question_id,
                kind=QuestionKind.COLUMN_MEANING,
                column=conflict.header,
                field=conflict.field,
                # "is «Ore A» still the planned hours?" - yes, or the person looks at the columns
                candidate=conflict.field,
                origin=OriginKind.PROFILE,
                choices=(Choice(conflict.field),),
            )
        )
    return out


def _with_answers(proposal: Proposal, overrides: Mapping[str, str]) -> Proposal:
    """The person's own classification of columns wins; a field is used once."""
    if not overrides:
        return proposal
    taken = {field for field in overrides.values()}
    columns: list[ColumnProposal] = []
    for column in proposal.columns:
        if column.header in overrides:
            columns.append(
                replace(
                    column,
                    field=overrides[column.header],
                    level=Level.HIGH,
                    ambiguous_group=None,
                    ambiguous_fields=(),
                )
            )
        elif column.field in taken:
            columns.append(replace(column, field=None, level=None, name=None, fit=None))
        elif column.ambiguous_group and set(column.ambiguous_fields) & taken:
            # some of what this column might have been is settled by the person's answers
            left = tuple(f for f in column.ambiguous_fields if f not in taken)
            columns.append(
                replace(
                    column,
                    ambiguous_group=column.ambiguous_group if left else None,
                    ambiguous_fields=left,
                )
            )
        else:
            columns.append(column)
    return Proposal(tuple(columns))


def _example(samples: Sequence[ColumnSample], column: ColumnProposal) -> str | None:
    """A value seen in the file for this column (never for personal data: the caller checks)."""
    if column.position < len(samples) and samples[column.position].examples:
        return _short(samples[column.position].examples[0])
    return column.stats.texts[0] if column.stats.texts else None


def _short(text: str | None) -> str | None:
    if text is None:
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= 60 else flat[:59].rstrip() + "…"


def _detection_info(verdict_: DomainVerdict, expected: DataSourceDomain) -> Detection:
    return Detection(
        domain=verdict_.domain.value if verdict_.domain else None,
        level=verdict_.level.value,
        scores=tuple(DomainScoreInfo(s.domain.value, s.score) for s in verdict_.scores),
        expected=expected.value,
    )


__all__ = ["UnderstandAnswers", "UnderstandingService"]

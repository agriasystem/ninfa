"""What Smart Import V3 answered, reduced to plain facts.

The system under test is `UnderstandingService.understand` - the call the API's
`/import-understanding` route makes - run in-process with no database, no source saved, no AI
provider (`IMPORT_UNDERSTANDING_PROVIDER` stays `unconfigured`). Its answer is turned into
`Observed`, a record with nothing of the system's types in it, plus the exact JSON the API would
send to the browser (`payload`), which is what the personal-data scan reads.

Nothing here knows what the right answer is.
"""

import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.api.v1.sources.router import _inspection_response
from app.core.tenant import TenantContext
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.data_sources.column_profile import sample_columns
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.ingestion.models import DataSourceDomain

# Which API-level kinds of data each domain card means.
CARD = {
    "labor": DataSourceDomain.LABOR,
    "bookings": DataSourceDomain.BOOKINGS,
    "costs": DataSourceDomain.COSTS,
}


@dataclass(slots=True)
class OColumn:
    position: int
    header: str
    field: str | None
    level: str | None
    not_used_reason: str | None
    examples: tuple[str, ...]


@dataclass(slots=True)
class OClaim:
    """One thing NINFA says it read: a field, and where from."""

    field: str
    kind: str  # COLUMN | SECTION | SHEET | TITLE | GRID | PROFILE | USER | LEARNED | PROPERTY ...
    header: str | None
    level: str


@dataclass(slots=True)
class OQuestion:
    kind: str
    column: str | None
    field: str | None
    document: str | None
    candidate: str | None
    labels: tuple[str, ...]
    choices: tuple[tuple[str, int | None], ...]  # (value, first_row) of the choices


@dataclass(slots=True)
class Observed:
    error: str | None = None
    level: str | None = None
    problem: str | None = None
    detection_domain: str | None = None
    detection_level: str | None = None
    detection_scores: dict[str, float] = field(default_factory=dict)
    sheet_name: str | None = None
    table_sheets: tuple[str, ...] = ()
    header_rows: tuple[int, ...] = ()
    first_row: int | None = None
    last_row: int | None = None
    data_rows: int | None = None
    skipped: dict[str, int] = field(default_factory=dict)
    totals_state: str | None = None
    amounts_state: str | None = None
    period_start: str | None = None
    day_grid: bool = False
    title: str | None = None
    columns: list[OColumn] = field(default_factory=list)
    claims: list[OClaim] = field(default_factory=list)
    constants: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    questions: list[OQuestion] = field(default_factory=list)
    blockers: list[tuple[str, tuple[tuple[str, ...], ...]]] = field(default_factory=list)
    people: int | None = None
    suggestion_complete: bool = False
    elapsed_ms: float = 0.0
    peak_kib: float | None = None
    payload: str = ""
    # the work dates of an unpivoted day grid, as the importers will read them (ISO)
    virtual_dates: tuple[str, ...] = ()
    # how the importers will read text dates (per field) and amounts, as Smart Import resolved it
    date_patterns: dict[str, str] = field(default_factory=dict)
    decimal_mark: str | None = None
    formats_unresolved: bool = False

    @property
    def question_kinds(self) -> list[str]:
        return [q.kind for q in self.questions]

    @property
    def blocker_codes(self) -> list[str]:
        return [code for code, _ in self.blockers]

    @property
    def automatic(self) -> bool:
        """The person would see a summary and one button: nothing asked, nothing refused."""
        return self.level == "READY" and not self.questions and not self.blockers


def make_service() -> UnderstandingService:
    """The real understanding service, with no database and no assistant (resolver None)."""
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    resolver: ImportUnderstandingResolver | None = None
    return UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)


def observe(inspection: FileInspection, *, elapsed_ms: float = 0.0) -> Observed:
    out = Observed(elapsed_ms=elapsed_ms)
    out.problem = inspection.problem.value if inspection.problem else None
    out.sheet_name = inspection.sheet_name
    out.suggestion_complete = inspection.suggestion_complete
    out.columns = [
        OColumn(
            c.position,
            c.header,
            c.field,
            c.level.value if c.level else None,
            c.not_used_reason,
            tuple(c.examples),
        )
        for c in inspection.columns
    ]
    out.payload = _inspection_response(inspection).model_dump_json()
    info = inspection.understanding
    if info is None:
        return out
    out.level = info.level.value
    out.detection_domain = info.detection.domain
    out.detection_level = info.detection.level
    out.detection_scores = {s.domain: round(s.score, 3) for s in info.detection.scores}
    document = info.document
    out.totals_state = document.totals
    out.amounts_state = document.amounts
    out.period_start = document.period_start
    out.day_grid = document.day_grid
    out.title = document.title
    out.skipped = {
        "totals": document.skipped.totals,
        "notes": document.skipped.notes,
        "sections": document.skipped.sections,
    }
    if document.table is not None:
        out.table_sheets = tuple(document.table.sheets)
        out.header_rows = tuple(document.table.header_rows)
        out.first_row = document.table.first_row
        out.last_row = document.table.last_row
        out.data_rows = document.table.data_rows
    out.claims = [
        OClaim(r.field, r.origin.kind.value, r.origin.detail, r.level) for r in info.recognized
    ]
    out.people = info.people
    out.questions = [
        OQuestion(
            q.kind.value,
            q.column,
            q.field,
            q.document,
            q.candidate,
            tuple(item.label for item in q.labels),
            tuple((c.value, c.first_row) for c in q.choices),
        )
        for q in info.questions
    ]
    out.blockers = [(b.code.value, tuple(tuple(g) for g in b.groups)) for b in info.blockers]
    if inspection.proposal is not None:
        out.constants = dict(inspection.proposal.constants)
        out.labels = {name: dict(words) for name, words in inspection.proposal.labels.items()}
    return out


def run(
    service: UnderstandingService,
    domain: str,
    filename: str,
    content: bytes,
    *,
    answers: UnderstandAnswers | None = None,
    confirmed_domain: bool = False,
    memory: bool = False,
) -> Observed:
    """Ask Smart Import to understand one document, as the first upload of a card does."""
    started = time.perf_counter()
    if memory:
        tracemalloc.start()
    try:
        inspection = service.understand(
            CARD[domain],
            filename,
            content,
            answers or UnderstandAnswers(),
            confirmed_domain,
            None,
            False,
            currency="EUR",
        )
        elapsed = (time.perf_counter() - started) * 1000
        peak = tracemalloc.get_traced_memory()[1] / 1024 if memory else None
    except Exception as error:
        if memory:
            tracemalloc.stop()
        failed = Observed(error=f"{type(error).__name__}: {error}"[:300])
        failed.elapsed_ms = (time.perf_counter() - started) * 1000
        return failed
    if memory:
        tracemalloc.stop()
    result = observe(inspection, elapsed_ms=elapsed)
    result.peak_kib = peak
    result.virtual_dates = _grid_dates(inspection, filename, content)
    _read_formats(result, inspection, domain, filename, content)
    return result


def _grid_dates(inspection: FileInspection, filename: str, content: bytes) -> tuple[str, ...]:
    """For a day grid: the dates the importers will find in the unpivoted table. This reads the
    table through the decision's own layout (`SmartImportService.read_table`) - what would be
    imported - and nothing else; it is not timed."""
    decision = inspection.proposal
    if decision is None or decision.layout is None or decision.layout.grid is None:
        return ()
    position = next((c.position for c in inspection.columns if c.field == "work_date"), None)
    if position is None:
        return ()
    try:
        table = SmartImportService.read_table(content, filename, None, decision.layout)
        found: set[str] = set()
        for index, row in enumerate(table.rows()):
            if index > 20000:
                break
            cells = row.cells
            value = cells[position] if position < len(cells) else None
            if isinstance(value, datetime | date):
                found.add(
                    value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
                )
        return tuple(sorted(found))
    except Exception:  # an unreadable grid is reported by the answer itself
        return ()


_NO_SESSION: Any = None
_SMART = SmartImportService(_NO_SESSION, TenantContext(UUID(int=1)))


def _read_formats(
    result: Observed, inspection: FileInspection, domain: str, filename: str, content: bytes
) -> None:
    """How the decision reads the dates and amounts that are written as TEXT. Uses the same pure
    function the import path uses (`formats_of`), after the stopwatch has stopped."""
    decision = inspection.proposal
    if decision is None or inspection.understanding is None:
        return
    try:
        adapter = _SMART.domain(CARD[domain])
        table = SmartImportService.read_table(
            content, filename, decision.sheet_name, decision.layout
        )
        formats = _SMART.formats_of(adapter, decision, sample_columns(table))
    except Exception:  # unreadable here means unreadable there: the answer already says so
        return
    result.date_patterns = dict(formats.date_formats)
    result.decimal_mark = formats.decimal_separator
    result.formats_unresolved = formats.unresolved

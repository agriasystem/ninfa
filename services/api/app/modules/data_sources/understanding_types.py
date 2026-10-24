"""The vocabulary of "NINFA understood your file" (Smart Import V3).

Like the matching vocabulary of V2, everything a page needs to decide is decided by the backend
and sent as a FACT, in stable codes the page turns into Italian sentences: what kind of data this
is, how sure NINFA is, which table it read, what it took out of it (and why), where each value came
from, what it still needs to ask - and nothing else. A question is only ever asked about what is
REALLY ambiguous, and a question never carries a value read from the file other than a department
label.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class QuestionKind(StrEnum):
    # What kind of data is this file? (the choices are the kinds of data)
    DOMAIN = "DOMAIN"
    # Which of two tables on offer? (the choices are the tables)
    TABLE = "TABLE"
    # No column, line, sheet or title says the department: which one are all these rows?
    DEPARTMENT_ROWS = "DEPARTMENT_ROWS"
    # The title says "Housekeeping": is that the department of all the rows?
    DEPARTMENT_CONFIRM = "DEPARTMENT_CONFIRM"
    # Words NINFA does not know ("Turno A", "HK"): which department / status / category?
    VALUE_LABELS = "VALUE_LABELS"
    # One column that is clearly hours / a cost / an amount but not WHICH: pick what it is.
    COLUMN_MEANING = "COLUMN_MEANING"
    # A grid of days holds hours: planned or actual?
    GRID_HOURS = "GRID_HOURS"
    # The days of a grid are Mon, Tue...: which week is this?
    PERIOD = "PERIOD"
    # An amount that does not say whether VAT is in it: net (what NINFA works with) or gross?
    AMOUNT_BASIS = "AMOUNT_BASIS"
    # 03/10/2026 is the 3rd of October or the 10th of March: only the person knows (DMY / MDY).
    DATE_ORDER = "DATE_ORDER"
    # 1,234 is one thousand two hundred or one and a bit: only the person knows (COMMA / POINT).
    DECIMAL_STYLE = "DECIMAL_STYLE"


class UnderstandingLevel(StrEnum):
    # NINFA is sure of everything it needs: a summary and "Importa dati", no matching screen.
    READY = "READY"
    # NINFA understood almost everything: a few single questions remain.
    ASK = "ASK"
    # NINFA could not read it with confidence: the person matches the columns (V2 screen).
    MANUAL = "MANUAL"
    # The file cannot be imported as it is, and says why (`blockers`).
    BLOCKED = "BLOCKED"


class BlockerCode(StrEnum):
    NO_TABLE = "NO_TABLE"
    # A required piece of information is not in the file (`fields` says which ones).
    MISSING_REQUIRED = "MISSING_REQUIRED"
    # Hours per person for the WEEK, with no day: not usable by an analysis that is day by day.
    PERIOD_SUMMARY_ONLY = "PERIOD_SUMMARY_ONLY"
    GRID_NOT_SUPPORTED = "GRID_NOT_SUPPORTED"
    # The cells of a "grid" are not hours (shift codes, time ranges).
    GRID_NOT_HOURS = "GRID_NOT_HOURS"
    # Amounts that are gross (VAT included) with no way to get the net NINFA works with.
    AMOUNT_NOT_NET = "AMOUNT_NOT_NET"
    # One column writes its dates (or numbers) in two different ways: the file has to be fixed.
    MIXED_FORMATS = "MIXED_FORMATS"


class OriginKind(StrEnum):
    COLUMN = "COLUMN"  # a column of the file, by its header
    SECTION = "SECTION"  # a line of its own above the rows ("RECEPTION")
    SHEET = "SHEET"  # the name of the sheet
    TITLE = "TITLE"  # the title of the document
    PROFILE = "PROFILE"  # how this source's files were read the last time
    USER = "USER"  # what the person said
    LEARNED = "LEARNED"  # a word the person taught NINFA before
    PROPERTY = "PROPERTY"  # the hotel's own settings (its currency)
    ASSISTANT = "ASSISTANT"  # suggested by the optional assistant: always to be checked
    GRID = "GRID"  # the days of a grid


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    count: int | None = None
    # A table on offer: where it is and how big (for the TABLE question).
    sheets: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    # The line written just above it ("Turni sera") and the row it starts on, so two tables with the
    # same columns can be told apart.
    title: str | None = None
    first_row: int | None = None


@dataclass(frozen=True, slots=True)
class LabelCount:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    kind: QuestionKind
    column: str | None = None
    field: str | None = None
    # The stored document an answer is kept in ("role_mapping", "status_mapping").
    document: str | None = None
    # A suggested answer and where it comes from (the person confirms it).
    candidate: str | None = None
    origin: OriginKind | None = None
    choices: tuple[Choice, ...] = ()
    labels: tuple[LabelCount, ...] = ()
    # How many labels there were in all (the list shows the most frequent ones).
    total_labels: int = 0


@dataclass(frozen=True, slots=True)
class Blocker:
    code: BlockerCode
    # MISSING_REQUIRED: what the file does not have; each group is "at least one of".
    groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Origin:
    kind: OriginKind
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Recognized:
    """One thing NINFA read from the file: the field, the value it saw, where it comes from."""

    field: str
    origin: Origin
    level: str  # "HIGH" | "MEDIUM" | "LOW"
    example: str | None = None


@dataclass(frozen=True, slots=True)
class DomainScoreInfo:
    domain: str
    score: float


@dataclass(frozen=True, slots=True)
class Detection:
    domain: str | None
    level: str  # "HIGH" | "MEDIUM" | "LOW"
    scores: tuple[DomainScoreInfo, ...] = ()
    # The kind of data the person asked to import (the card they came from).
    expected: str | None = None


@dataclass(frozen=True, slots=True)
class SheetSummary:
    name: str
    role: str  # DATA | SUMMARY | EMPTY | HIDDEN
    rows: int


@dataclass(frozen=True, slots=True)
class TableSummary:
    sheets: tuple[str, ...]
    header_rows: tuple[int, ...]
    first_row: int
    last_row: int
    data_rows: int
    partition: bool
    renamed_headers: int = 0


@dataclass(frozen=True, slots=True)
class SkippedSummary:
    totals: int = 0
    notes: int = 0
    sections: int = 0


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    file_type: str
    sheets: tuple[SheetSummary, ...] = ()
    table: TableSummary | None = None
    title: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    skipped: SkippedSummary = field(default_factory=SkippedSummary)
    # Do the totals of the file add up the rows? MATCH | PARTIAL | MISMATCH | UNVERIFIED | None.
    totals: str | None = None
    day_grid: bool = False
    # Costs: do net + VAT = total on the rows? MATCH | MISMATCH | None (not enough to say).
    amounts: str | None = None


@dataclass(frozen=True, slots=True)
class UnderstandingInfo:
    level: UnderstandingLevel
    detection: Detection
    document: DocumentSummary
    recognized: tuple[Recognized, ...] = ()
    # Distinct people in the file, counted in memory and kept nowhere (staff files only).
    people: int | None = None
    questions: tuple[Question, ...] = ()
    blockers: tuple[Blocker, ...] = ()


__all__ = [
    "Blocker",
    "BlockerCode",
    "Choice",
    "Detection",
    "DomainScoreInfo",
    "DocumentSummary",
    "LabelCount",
    "Origin",
    "OriginKind",
    "Question",
    "QuestionKind",
    "Recognized",
    "SheetSummary",
    "SkippedSummary",
    "TableSummary",
    "UnderstandingInfo",
    "UnderstandingLevel",
]

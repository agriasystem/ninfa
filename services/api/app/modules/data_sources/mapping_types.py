"""The vocabulary of "match the columns of your file" (Smart Import): what is asked of the person,
what NINFA proposes, what a saved configuration is.

Everything a page needs to decide is decided by the backend and sent as a fact: which fields exist,
which of them are required (and which are "at least one of"), which column NINFA recognised, what a
column's values prove about how dates and numbers are written. The page only shows them.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.data_sources.files import ImportProblem
from app.modules.data_sources.understanding_types import Question, UnderstandingInfo
from app.modules.document_understanding.layout import LayoutSpec
from app.modules.ingestion.models import DataSourceDomain

MAX_COLUMNS = 200
MAX_HEADER_LENGTH = 200
MAX_CONSTANTS = 20
MAX_CONSTANT_LENGTH = 200
MAX_LABEL_DOCUMENTS = 4
MAX_LABELS = 200
MAX_LABEL_LENGTH = 120
MAX_DECISION_ANSWERS = 12


# --- what the person decides (the request) --------------------------------------------------------


class ColumnChoice(BaseModel):
    """What ONE column of the file means. `field=None` is "ignore this column"."""

    model_config = ConfigDict(extra="forbid")

    header: str = Field(min_length=1, max_length=MAX_HEADER_LENGTH)
    field: str | None = Field(default=None, max_length=64)


class SmartImportDecision(BaseModel):
    """Where a decision comes from: the understanding the SERVER made of this file, with the answers
    the person had given when it made it.

    A decision that carries this is not taken on trust. Before it is judged or imported the server
    reads the file again (without any model), with these answers, and the decision is accepted only
    if that reading is READY - no question open, nothing refusing - and gives exactly this mapping.
    So it cannot be turned from "asked" into "ready" by posting it again, by copying the suggested
    matching, or by saying it is confirmed: the only way is to answer the questions, which the
    server checks. Nothing here is a claim the client makes about itself; it only says WHICH
    reading to verify. A matching the person builds by hand does not carry it (the manual
    contract)."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any] = Field(default_factory=dict, max_length=MAX_DECISION_ANSWERS)
    confirmed_domain: bool = False


class MappingInput(BaseModel):
    """The whole decision: what each column means, the fixed values for fields the file does not
    have, and how the dates and numbers of the file are written."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = Field(default=None, max_length=MAX_HEADER_LENGTH)
    columns: list[ColumnChoice] = Field(default_factory=list, max_length=MAX_COLUMNS)
    # "The same value on every row" for the few fields where that cannot invent a fact.
    constants: dict[str, str | int] = Field(default_factory=dict, max_length=MAX_CONSTANTS)
    # Only needed when the file writes dates as 12/10/2026 and its values do not say which is the
    # day; absent otherwise (a date written 2026-10-12, or a real Excel date, needs no choice).
    date_order: Literal["DMY", "MDY"] | None = None
    # Only needed when the file writes amounts with a comma or a point as the decimal mark.
    decimal_style: Literal["COMMA", "POINT"] | None = None
    # Smart Import V3: how the STRUCTURE of the document is read (a department that is a line, a
    # sheet or the title; a grid of days) - saved with the configuration, minus this file's dates.
    layout: LayoutSpec | None = None
    # The words the person taught NINFA: {"role_mapping": {"HK": "HOUSEKEEPING"}} (a department
    # label, a status, a cost category). Kept in the configuration of THIS source only.
    labels: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Set by the server on the decisions IT issues (see `SmartImportDecision`); absent on a matching
    # the person builds by hand.
    smart_import: SmartImportDecision | None = None

    @field_validator("labels")
    @classmethod
    def _labels_are_bounded(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        if len(value) > MAX_LABEL_DOCUMENTS:
            raise ValueError("too many documents of labels")
        for document, words in value.items():
            if len(document) > 40 or len(words) > MAX_LABELS:
                raise ValueError("too many labels")
            for label, meaning in words.items():
                if not label.strip() or len(label) > MAX_LABEL_LENGTH or len(meaning) > 40:
                    raise ValueError("a label is empty or too long")
        return value


# --- what the page may ask for --------------------------------------------------------------------


class FieldKind(StrEnum):
    DATE = "DATE"
    DATETIME = "DATETIME"
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    TEXT = "TEXT"
    CHOICE = "CHOICE"
    CURRENCY = "CURRENCY"


class ConstantKind(StrEnum):
    INTEGER = "INTEGER"
    TEXT = "TEXT"
    CHOICE = "CHOICE"
    CURRENCY = "CURRENCY"


@dataclass(frozen=True, slots=True)
class ConstantSpec:
    """A field that may be given ONE value for every row of the file."""

    kind: ConstantKind
    choices: tuple[str, ...] = ()
    default: str | int | None = None


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One thing NINFA can read from a column."""

    key: str
    kind: FieldKind
    constant: ConstantSpec | None = None


class SuggestionLevel(StrEnum):
    RECOGNIZED = "RECOGNIZED"  # the column carries a name NINFA knows for this field
    TO_CHECK = "TO_CHECK"  # a likely match, not a certain one


# --- what NINFA finds in a file -----------------------------------------------------------------


class ProfileStatus(StrEnum):
    NONE = "NONE"  # no saved configuration for this kind of data
    RECOGNIZED = "RECOGNIZED"  # the saved configuration reads this file as it is
    NEEDS_REVIEW = "NEEDS_REVIEW"  # there is one, but it cannot be applied to this file silently


class ProfileReason(StrEnum):
    COLUMNS_CHANGED = "COLUMNS_CHANGED"  # a column the configuration uses is not in this file
    VERSION_CHANGED = "VERSION_CHANGED"  # NINFA's own reading rules changed since it was saved
    INVALID = "INVALID"  # the saved configuration cannot be read any more


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    position: int
    header: str
    examples: tuple[str, ...]
    # The meaning NINFA proposes (None: nothing proposed, the person chooses or ignores it).
    field: str | None = None
    level: SuggestionLevel | None = None
    # Why a column is deliberately not offered as a field (an hourly rate, a person's name).
    not_used_reason: str | None = None
    # What the values prove about how they are written (only for columns that hold such values).
    date_order: str | None = None
    number_style: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileInfo:
    status: ProfileStatus
    reason: ProfileReason | None = None
    # The saved configuration as a decision, so "Controlla colonne" can start from it.
    mapping: MappingInput | None = None
    # The last time a file was imported through this source.
    last_used_at: datetime | None = None
    missing_columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileInspection:
    domain: DataSourceDomain
    # None when the file cannot be read: `problem` says why and nothing else is filled.
    file_type: str | None = None
    problem: ImportProblem | None = None
    sheet_name: str | None = None
    sheet_names: tuple[str, ...] = ()
    requires_sheet_selection: bool = False
    columns: tuple[ColumnInfo, ...] = ()
    fields: tuple[FieldSpec, ...] = ()
    # Each group is "at least one of": a single-field group is a field that is required.
    requirement_groups: tuple[tuple[str, ...], ...] = ()
    # The proposal, as it stands, already meets every requirement.
    suggestion_complete: bool = False
    # The file already is in NINFA's own format (no matching of columns needed).
    already_canonical: bool = False
    profile: ProfileInfo = field(default_factory=lambda: ProfileInfo(ProfileStatus.NONE))
    already_imported: bool = False
    # Smart Import V3: what NINFA understood of the DOCUMENT (None: the plain V2 reading).
    understanding: UnderstandingInfo | None = None
    # ...and the decision it proposes from that (columns, layout, what the person already said).
    proposal: "MappingInput | None" = None


# --- checking and trying a decision ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingProblem:
    code: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MappingCheck:
    valid: bool
    # What is still needed: each entry is a group "at least one of these".
    missing: tuple[tuple[str, ...], ...] = ()
    problems: tuple[MappingProblem, ...] = ()


class DryRunStatus(StrEnum):
    READY = "READY"  # the file was read and every row judged
    NEEDS_CHOICE = "NEEDS_CHOICE"  # the person must say how dates / numbers are written
    BLOCKED = "BLOCKED"  # the file or the matching cannot be used: `problem` / `check` say why


@dataclass(frozen=True, slots=True)
class FormatHint:
    """A question about how the file writes something, with what its values already prove."""

    question: Literal["DATE_ORDER", "DECIMAL_STYLE"]
    # What the values prove ("DMY", "MDY", "COMMA", "POINT"), or None when only the person knows.
    proven: str | None = None
    # The file columns the question is about.
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RowProblemCount:
    field: str
    code: str
    count: int


@dataclass(frozen=True, slots=True)
class InvalidRow:
    row: int
    issues: tuple[tuple[str, str], ...]  # (field, code)


@dataclass(frozen=True, slots=True)
class DryRunSummary:
    """What a whole file adds up to, from the rows that PASSED validation (never from raw cells)."""

    date_from: str | None = None
    date_to: str | None = None
    # Staff
    departments: tuple[str, ...] = ()
    planned_hours: str | None = None
    actual_hours: str | None = None
    planned_cost: str | None = None
    actual_cost: str | None = None
    currency: str | None = None
    # Bookings
    channels: int | None = None
    revenue: str | None = None
    # Costs
    documents: int | None = None
    suppliers: int | None = None
    net_total: str | None = None


@dataclass(frozen=True, slots=True)
class DryRun:
    status: DryRunStatus
    problem: ImportProblem | None = None
    check: MappingCheck | None = None
    format_hints: tuple[FormatHint, ...] = ()
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    # The fields shown, in order, and the first valid rows in NINFA's own form (plain text).
    sample_fields: tuple[str, ...] = ()
    sample_rows: tuple[tuple[str | None, ...], ...] = ()
    row_problems: tuple[RowProblemCount, ...] = ()
    invalid_rows: tuple[InvalidRow, ...] = ()
    already_imported: bool = False
    # Valid rows NINFA could not assign to a department (kept as "Altro", which no staffing decision
    # uses). Staff files only; always 0 elsewhere.
    rows_unclassified: int = 0
    summary: DryRunSummary | None = None
    # What is still unclear about the VALUES of the file (department words NINFA does not know...).
    questions: tuple[Question, ...] = ()

    @property
    def can_import(self) -> bool:
        return self.status == DryRunStatus.READY and self.rows_total > 0 and self.rows_invalid == 0


# --- the saved configuration ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SavedConfiguration:
    """What is remembered about how this source's files are read - for the page's "manage" view."""

    data_source_id: str
    domain: DataSourceDomain
    # (field key, the file's own column name) for the fields read from a column.
    columns: tuple[tuple[str, str], ...]
    # (field key, fixed value) for the fields given one value for every row.
    constants: tuple[tuple[str, str], ...]
    last_used_at: datetime | None
    schema_current: bool


__all__ = [
    "MAX_COLUMNS",
    "MAX_LABELS",
    "DryRunSummary",
    "MAX_CONSTANTS",
    "MAX_CONSTANT_LENGTH",
    "MAX_HEADER_LENGTH",
    "ColumnChoice",
    "ColumnInfo",
    "ConstantKind",
    "ConstantSpec",
    "DryRun",
    "DryRunStatus",
    "FieldKind",
    "FieldSpec",
    "FileInspection",
    "FormatHint",
    "InvalidRow",
    "MappingCheck",
    "MappingInput",
    "MappingProblem",
    "ProfileInfo",
    "ProfileReason",
    "ProfileStatus",
    "RowProblemCount",
    "SavedConfiguration",
    "SuggestionLevel",
]

"""What the VALUES of a column say it can and cannot be - positive proof and negative evidence.

Two questions, asked of a column's profile:

* CAN a column with no helpful name be this field? Only some fields can be PROVEN from their values
  alone, because their values belong to a closed vocabulary or a shape that is not shared with the
  rest of the file: a booking status (confirmed / cancelled / no show), a sales channel
  (Booking.com,
  Expedia, direct), a department, a currency code, a cost category, a VAT number, a booking code
  (different on every row, letters and digits). `proof` says how strongly. A number is never
  proof of
  an amount, a count or an hour: those need a name (or a relation to another column).

* CAN'T it be this field? `veto` is the reason a column is NOT a field whatever its name says: a
  column of channel names is not a status, a column with cents is not a booking code, a column of
  dates is not a room count, a percentage is not a number of rooms. Negative evidence matters as
  much as positive: it stops a confident wrong reading, which costs more than a question.

Everything here reads a `ColumnProfile`; nothing reads or keeps a value. No value is ever turned
into
a business fact: the importers do that, with their own rules.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.modules.data_sources.algorithmic.profile import ColumnProfile, Primitive
from app.modules.ingestion.models import DataSourceDomain

# how much of a column must be words NINFA knows for the values alone to say what it is
PROOF_SHARE = 0.9
# a column "of words": most cells are text and few distinct ones repeat
WORDY = 0.9
MIN_ROWS = 5
MIN_RULED_OUT = 3  # fewer values than this never rule a column out
UNIQUE = 0.98
SLIP = 0.2  # a share of values this small is a slip of the data, not another kind of column
CODE_SHAPE = 0.67  # share of values with one shape (AA999) that makes a column of codes a code


class Sem(StrEnum):
    DATE = "DATE"
    IDENTIFIER = "IDENTIFIER"  # one per row: a booking code
    DOC_NUMBER = "DOC_NUMBER"  # may repeat over the lines of one document
    STATUS = "STATUS"
    CHANNEL = "CHANNEL"
    DEPARTMENT = "DEPARTMENT"
    CURRENCY = "CURRENCY"
    CATEGORY = "CATEGORY"
    MONEY = "MONEY"
    PERCENT = "PERCENT"
    COUNT = "COUNT"
    HOURS = "HOURS"
    NUMBER = "NUMBER"
    VAT_NUMBER = "VAT_NUMBER"
    LABEL = "LABEL"
    TEXT = "TEXT"


B, L, C = DataSourceDomain.BOOKINGS, DataSourceDomain.LABOR, DataSourceDomain.COSTS

# What each field IS, as far as its values go.
FIELD_SEM: dict[tuple[DataSourceDomain, str], Sem] = {
    (B, "source_record_id"): Sem.IDENTIFIER,
    (B, "booked_at"): Sem.DATE,
    (B, "check_in"): Sem.DATE,
    (B, "check_out"): Sem.DATE,
    (B, "status"): Sem.STATUS,
    (B, "rooms"): Sem.COUNT,
    (B, "room_revenue"): Sem.MONEY,
    (B, "channel"): Sem.CHANNEL,
    (B, "guests"): Sem.COUNT,
    (B, "total_revenue"): Sem.MONEY,
    (B, "commission_amount"): Sem.MONEY,
    (B, "commission_rate"): Sem.PERCENT,
    (B, "cancelled_at"): Sem.DATE,
    (B, "room_type"): Sem.LABEL,
    (B, "rate_plan"): Sem.LABEL,
    (L, "work_date"): Sem.DATE,
    (L, "role"): Sem.DEPARTMENT,
    (L, "labor_category"): Sem.DEPARTMENT,
    (L, "planned_hours"): Sem.HOURS,
    (L, "actual_hours"): Sem.HOURS,
    (L, "planned_cost"): Sem.MONEY,
    (L, "actual_cost"): Sem.MONEY,
    (L, "currency"): Sem.CURRENCY,
    (C, "supplier_name"): Sem.TEXT,
    (C, "supplier_vat_number"): Sem.VAT_NUMBER,
    (C, "supplier_tax_code"): Sem.TEXT,
    (C, "invoice_number"): Sem.DOC_NUMBER,
    (C, "invoice_date"): Sem.DATE,
    (C, "due_date"): Sem.DATE,
    (C, "document_type"): Sem.LABEL,
    (C, "currency"): Sem.CURRENCY,
    (C, "invoice_net_amount"): Sem.MONEY,
    (C, "invoice_tax_amount"): Sem.MONEY,
    (C, "invoice_gross_amount"): Sem.MONEY,
    (C, "line_description"): Sem.TEXT,
    (C, "quantity"): Sem.NUMBER,
    (C, "unit_price"): Sem.MONEY,
    (C, "line_total"): Sem.MONEY,
    (C, "vat_rate"): Sem.PERCENT,
    (C, "cost_category"): Sem.CATEGORY,
}

# Fields whose values can name them with NO helpful header (never a number, never a free text).
PROVABLE = frozenset(
    {
        (B, "status"),
        (B, "channel"),
        (B, "source_record_id"),
        (L, "role"),
        (L, "currency"),
        (C, "currency"),
        (C, "cost_category"),
        (C, "supplier_vat_number"),
    }
)


@dataclass(frozen=True, slots=True)
class ValueEvidence:
    # 0..1: how well the values fit the field, None when they say nothing either way
    fit: float | None
    # 0..1: how strongly the values ALONE name the field (0: they cannot)
    proof: float
    # why the column cannot be this field, or None
    veto: str | None
    reasons: tuple[str, ...] = ()


def semantic_of(domain: DataSourceDomain, field: str) -> Sem | None:
    return FIELD_SEM.get((domain, field))


# --- negative evidence ----------------------------------------------------------------------------


def _wordy(profile: ColumnProfile) -> bool:
    return profile.text_share >= WORDY


def _numeric(profile: ColumnProfile) -> bool:
    return profile.numeric_share >= WORDY


def _dated(profile: ColumnProfile) -> bool:
    return profile.date_share >= 0.8


def _repeats(profile: ColumnProfile) -> bool:
    return profile.non_null >= MIN_ROWS and profile.uniqueness <= 0.5


def _different_every_row(profile: ColumnProfile) -> bool:
    return profile.non_null >= MIN_ROWS and profile.uniqueness >= 0.95


def veto(profile: ColumnProfile, sem: Sem) -> str | None:
    """Why a column cannot be a field of this kind - or None. Judged from the values alone."""
    if profile.non_null < MIN_RULED_OUT:
        return None  # one or two values are no evidence against anything
    if sem == Sem.DATE:
        if _wordy(profile) and profile.date_share < 0.2:
            return "words, not dates"
        if _numeric(profile) and profile.primitive != Primitive.DATE:
            return "numbers, not dates"
    elif sem in {Sem.MONEY, Sem.COUNT, Sem.HOURS, Sem.PERCENT, Sem.NUMBER}:
        if _dated(profile):
            return "dates, not numbers"
        if _wordy(profile) and profile.numeric_share < 0.2:
            return "words, not numbers"
        if sem != Sem.PERCENT and profile.percent_like >= 0.5:
            return "written as percentages"
        if sem in {Sem.COUNT, Sem.HOURS} and profile.negative / profile.non_null >= SLIP:
            return "negative values"
        if sem == Sem.COUNT and profile.cents_share >= 0.3:
            return "values with cents"
        if sem == Sem.MONEY and profile.identifier_like >= 0.9 and _different_every_row(profile):
            return "a different long code on every row"
    elif sem == Sem.IDENTIFIER:
        if _dated(profile):
            return "dates, not codes"
        if (
            profile.negative / profile.non_null >= SLIP
            or profile.cents_share >= 0.3
            or profile.percent_like >= 0.5
        ):
            return "amounts, not codes"
        if profile.status_share >= 0.6:
            return "booking statuses, not codes"
        if profile.channel_share >= 0.6:
            return "channel names, not codes"
        if _repeats(profile):
            return "repeats too much to be one per booking"
    elif sem == Sem.DOC_NUMBER:
        if _dated(profile) or profile.negative or profile.cents_share >= 0.3:
            return "dates or amounts, not document numbers"
        if profile.status_share >= 0.6 or profile.channel_share >= 0.6:
            return "words NINFA knows for something else"
    elif sem == Sem.STATUS:
        if _numeric(profile) or _dated(profile):
            return "numbers or dates, not statuses"
        if profile.channel_share >= 0.6 and profile.status_share < 0.3:
            return "channel names, not statuses"
        if profile.department_share >= 0.6 and profile.status_share < 0.3:
            return "departments, not statuses"
        if _different_every_row(profile):
            return "different on every row, a status repeats"
    elif sem == Sem.CHANNEL:
        if _numeric(profile) or _dated(profile):
            return "numbers or dates, not channels"
        if profile.status_share >= 0.6 and profile.channel_share < 0.3:
            return "booking statuses, not channels"
        if profile.department_share >= 0.6 and profile.channel_share < 0.3:
            return "departments, not channels"
        if profile.place_share >= 0.6:
            return "countries, not channels"
        if _different_every_row(profile):
            return "different on every row, a channel repeats"
    elif sem in {Sem.DEPARTMENT, Sem.CATEGORY, Sem.CURRENCY, Sem.LABEL}:
        if _numeric(profile) or _dated(profile):
            return "numbers or dates, not words"
        if sem in {Sem.DEPARTMENT, Sem.CATEGORY}:
            if profile.status_share >= 0.6 or profile.channel_share >= 0.6:
                return "words NINFA knows for something else"
            if _different_every_row(profile):
                return "different on every row"
    elif sem == Sem.VAT_NUMBER:
        if _dated(profile) or profile.cents_share >= 0.3:
            return "dates or amounts, not VAT numbers"
    elif sem == Sem.TEXT and (_dated(profile) or _numeric(profile)):
        return "dates or numbers, not free text"
    return None


# --- positive proof ------------------------------------------------------------------------------


def proof_of(profile: ColumnProfile, sem: Sem, *, vat_fit: float = 0.0) -> float:
    """How strongly the values ALONE name a field of this kind. 0 for anything a number or a bare
    text could be."""
    if profile.non_null < 3 or profile.personal:
        return 0.0
    if sem == Sem.STATUS:
        return (
            profile.status_share if profile.status_share >= PROOF_SHARE and _wordy(profile) else 0.0
        )
    if sem == Sem.CHANNEL:
        return (
            profile.channel_share
            if profile.channel_share >= PROOF_SHARE and _wordy(profile)
            else 0.0
        )
    if sem == Sem.DEPARTMENT:
        return (
            profile.department_share
            if profile.department_share >= PROOF_SHARE and _wordy(profile)
            else 0.0
        )
    if sem == Sem.CATEGORY:
        return (
            profile.category_share
            if profile.category_share >= PROOF_SHARE and _wordy(profile)
            else 0.0
        )
    if sem == Sem.CURRENCY:
        return (
            profile.currency_share
            if profile.currency_share >= 0.95 and profile.unique <= 4
            else 0.0
        )
    if sem == Sem.VAT_NUMBER:
        return vat_fit if vat_fit >= PROOF_SHARE else 0.0
    if sem == Sem.IDENTIFIER:
        if (
            profile.non_null >= MIN_ROWS
            and profile.uniqueness >= UNIQUE
            and profile.identifier_like >= PROOF_SHARE
            and profile.cents_share < 0.3
        ):
            # a code has one shape (BK123456); a long number is whole and long by itself
            shaped = max(profile.shape_consistency, 1.0 if profile.text_share < 0.5 else 0.0)
            return min(1.0, 0.7 + 0.3 * shaped) if shaped >= CODE_SHAPE else 0.0
        return 0.0
    return 0.0


def read_values(
    domain: DataSourceDomain,
    field: str,
    fit: float | None,
    profile: ColumnProfile,
    *,
    vat_fit: float = 0.0,
) -> ValueEvidence:
    """The values of a column against one field: how well they fit, what they prove alone, and the
    reason they rule it out if they do."""
    sem = semantic_of(domain, field)
    if sem is None:
        return ValueEvidence(fit, 0.0, None)
    reason = veto(profile, sem)
    proof = proof_of(profile, sem, vat_fit=vat_fit) if (domain, field) in PROVABLE else 0.0
    notes: list[str] = []
    if reason is not None:
        notes.append(f"ruled out by the values: {reason}")
    elif proof:
        notes.append(f"the values alone name it ({sem.value.lower()}: {proof:.0%})")
    return ValueEvidence(fit, proof, reason, tuple(notes))


__all__ = [
    "FIELD_SEM",
    "PROVABLE",
    "Sem",
    "ValueEvidence",
    "proof_of",
    "read_values",
    "semantic_of",
    "veto",
]

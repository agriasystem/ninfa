"""Columns that CONFIRM each other: what the values of two columns say about one another.

A name alone is a maybe: "CI" is a check-in, or an identity card. A column of dates called "CI"
next to a column of dates called "CO" that is later than it on every row is a check-in and a
check-out - the relation between the two is evidence no header could give. Relations are evidence,
never an assumption: a file that does not hold one (a booking export without a departure) is not
wrong, it just has nothing to confirm, and the name stays what it was.

A relation only ever PROMOTES a reading that already stands on a name and on values that fit
(MEDIUM to HIGH). It never creates one from nothing and it never overrules a name. Deterministic,
bounded by the rows the caller already read, kept nowhere.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.bookings.normalization import DateOrder, detect_date_order
from app.modules.bookings.parsers import Cell
from app.modules.ingestion.value_text import month_name_date, split_weekday

# Enough rows for two columns to agree by chance only rarely.
MIN_PAIRS = 3
# A stay ends after it starts on (nearly) every row: a few stray rows are a data-entry slip, not a
# different kind of column.
HOLDS_AT_LEAST = 0.95
LONGEST_STAY_DAYS = 90

Holds = Callable[[Sequence[Cell], Sequence[Cell]], bool]


@dataclass(frozen=True, slots=True)
class Relation:
    """`first` and `second` are field keys of a kind of data; `holds` receives their columns,
    aligned row by row (an empty cell stays None so the rows keep matching)."""

    first: str
    second: str
    holds: Holds


def _order_of(*columns: Sequence[Cell]) -> DateOrder:
    texts = [
        split_weekday(cell.strip())[0]
        for column in columns
        for cell in column
        if isinstance(cell, str)
    ]
    return detect_date_order(texts) if texts else DateOrder.UNKNOWN


def _as_day(cell: Cell, order: DateOrder) -> date | None:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if not isinstance(cell, str):
        return None
    text = split_weekday(cell.strip())[0]
    named = month_name_date(text)
    if named is not None:
        return named.date()
    head = text[:10]
    for separator in ("-", "/", "."):
        parts = head.split(separator)
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            continue
        a, b, c = (int(part) for part in parts)
        try:
            if len(parts[0]) == 4:
                return date(a, b, c)
            if len(parts[2]) != 4:
                return None
            day, month = (b, a) if order == DateOrder.MDY else (a, b)
            return date(c, month, day)
        except ValueError:
            return None
    return None


def stay_dates(first: Sequence[Cell], second: Sequence[Cell]) -> bool:
    """`second` is later than `first` on (nearly) every row where both are dates, by a stay's
    length: the pair is an arrival and a departure."""
    order = _order_of(first, second)
    gaps: list[int] = []
    for a, b in zip(first, second, strict=False):
        start, end = _as_day(a, order), _as_day(b, order)
        if start is not None and end is not None:
            gaps.append((end - start).days)
    if len(gaps) < MIN_PAIRS:
        return False
    later = sum(1 for gap in gaps if 0 < gap <= LONGEST_STAY_DAYS)
    return later / len(gaps) >= HOLDS_AT_LEAST


__all__ = ["Holds", "Relation", "stay_dates"]

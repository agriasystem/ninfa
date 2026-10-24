"""What the first rows of a file say about each of its columns - read-only, deterministic, bounded.

The person is shown a few example values per column and, where the values prove it, how dates and
numbers are written (day first or month first, comma or point as the decimal mark). That is
EVIDENCE for a proposal: nothing here decides a mapping and nothing here writes anything. Only the
first `SCAN_ROWS` rows are read, so a very large file costs no more than a small one; the import
itself still validates every row.

Cells are shown, never interpreted as anything but text: a value that starts with `=`, `+`, `-` or
`@` is just text here, and NINFA never writes a spreadsheet or a CSV back out.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from itertools import islice
from typing import Literal

from app.modules.bookings.normalization import DateOrder, detect_date_order
from app.modules.bookings.parsers import Cell, SourceTable

SCAN_ROWS = 2000
EXAMPLES_PER_COLUMN = 3
EXAMPLE_MAX_CHARS = 40

DateChoice = Literal["DMY", "MDY"]


# --- looking at the cells -------------------------------------------------------------------------


def display_cell(cell: Cell) -> str:
    """A cell as a short piece of plain text for the page."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        text = cell.date().isoformat() if cell.time() == time(0) else cell.isoformat(" ", "minutes")
    elif isinstance(cell, date | time):
        text = cell.isoformat()
    elif isinstance(cell, bool):
        text = "true" if cell else "false"
    elif isinstance(cell, float):
        text = str(int(cell)) if cell.is_integer() else repr(cell)
    elif isinstance(cell, int | Decimal):
        text = str(cell)
    else:
        text = " ".join(str(cell).split())
    return text if len(text) <= EXAMPLE_MAX_CHARS else text[: EXAMPLE_MAX_CHARS - 1] + "…"


@dataclass(frozen=True)
class ColumnSample:
    position: int
    header: str
    examples: tuple[str, ...]
    # Every non-empty value among the scanned rows (kept for the evidence below).
    values: tuple[Cell, ...]


def sample_columns(table: SourceTable) -> list[ColumnSample]:
    """The first rows, column by column. Stops reading after `SCAN_ROWS` rows."""
    columns: list[list[Cell]] = [[] for _ in table.headers]
    for row in islice(table.rows(), SCAN_ROWS):
        for position, cell in enumerate(row.cells[: len(columns)]):
            if cell is not None:
                columns[position].append(cell)
    return [
        ColumnSample(
            position=position,
            header=header,
            examples=tuple(display_cell(value) for value in values[:EXAMPLES_PER_COLUMN]),
            values=tuple(values),
        )
        for position, (header, values) in enumerate(zip(table.headers, columns, strict=True))
    ]


# --- dates ----------------------------------------------------------------------------------------

_ISO_DATE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
_SLASHED_DATE = re.compile(
    r"^(\d{1,2})([/.\-])(\d{1,2})\2(\d{4})(?:([T ])(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)


def _texts(values: Sequence[Cell]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def looks_like_dates(values: Sequence[Cell]) -> bool:
    """True when there are values and every one of them is a date (a real one, or text written as
    a date) - the only value-based hint NINFA offers, for a column whose name says nothing."""
    if not values:
        return False
    for value in values:
        if isinstance(value, datetime | date):
            continue
        if isinstance(value, str) and (
            _ISO_DATE.match(value.strip()) or _SLASHED_DATE.match(value.strip())
        ):
            continue
        return False
    return True


def date_order_of(values: Sequence[Cell]) -> DateOrder:
    """What the written dates of ONE column prove about their day/month order (evidence only)."""
    return detect_date_order(_texts(values))


def date_pattern(values: Sequence[Cell], order: DateChoice) -> str | None:
    """The pattern that reads every day/month-first date of the column, or None when the column
    has no such date or writes them in more than one way (the import then reports the rows)."""
    shapes: set[tuple[str, str, str]] = set()
    for text in _texts(values):
        match = _SLASHED_DATE.match(text)
        if match is None:
            if _ISO_DATE.match(text):
                return None  # year-first and day/month-first dates in one column: not one way
            continue
        time_shape = "" if match.group(6) is None else ("HMS" if match.group(8) else "HM")
        shapes.add((match.group(2), match.group(5) or "", time_shape))
    if len(shapes) != 1:
        return None
    separator, time_separator, time_shape = next(iter(shapes))
    first, second = ("%d", "%m") if order == "DMY" else ("%m", "%d")
    pattern = f"{first}{separator}{second}{separator}%Y"
    if time_shape:
        pattern += f"{time_separator}%H:%M" + (":%S" if time_shape == "HMS" else "")
    return pattern


# --- numbers --------------------------------------------------------------------------------------


class NumberStyle(StrEnum):
    UNKNOWN = "UNKNOWN"  # no written number that needs a decision
    COMMA = "COMMA"  # 14,50 and 1.234,56
    POINT = "POINT"  # 14.5 and 1,234.56
    AMBIGUOUS = "AMBIGUOUS"  # 1.234 / 1,234: a thousand, or one and a bit - only a person knows
    MIXED = "MIXED"  # both styles in the same column


_COMMA_GROUPED = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$")  # 1.234,56
_POINT_GROUPED = re.compile(r"^-?\d{1,3}(?:,\d{3})+\.\d+$")  # 1,234.56
_THOUSAND_OR_DECIMAL = re.compile(r"^-?\d{1,3}[.,]\d{3}$")  # 1.234 / 1,234: either reading fits
_COMMA_PLAIN = re.compile(r"^-?\d+,\d+$")  # 14,50
_POINT_PLAIN = re.compile(r"^-?\d+\.\d+$")  # 14.5


def number_style(values: Sequence[Cell]) -> NumberStyle:
    """How the written numbers of ONE column use ',' and '.', where the values prove it."""
    comma = point = ambiguous = False
    for text in _texts(values):
        cleaned = text.replace(" ", "").replace(" ", "")
        if _COMMA_GROUPED.match(cleaned):
            comma = True
        elif _POINT_GROUPED.match(cleaned):
            point = True
        elif _THOUSAND_OR_DECIMAL.match(cleaned):
            ambiguous = True
        elif _COMMA_PLAIN.match(cleaned):
            comma = True
        elif _POINT_PLAIN.match(cleaned):
            point = True
    if comma and point:
        return NumberStyle.MIXED
    if comma:
        return NumberStyle.COMMA
    if point:
        return NumberStyle.POINT
    return NumberStyle.AMBIGUOUS if ambiguous else NumberStyle.UNKNOWN


__all__ = [
    "EXAMPLES_PER_COLUMN",
    "EXAMPLE_MAX_CHARS",
    "SCAN_ROWS",
    "ColumnSample",
    "DateChoice",
    "NumberStyle",
    "date_order_of",
    "date_pattern",
    "display_cell",
    "looks_like_dates",
    "number_style",
    "sample_columns",
]

"""What kind of thing ONE cell is: nothing, text, a number, a date, a time.

Structure detection needs only this much (is this row made of labels or of values?). It never parses
a value into a business fact: that is the importers' job, with their explicit rules. A cell that
starts with `=`, `+`, `-` or `@` is just text here.
"""

import re
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from app.modules.bookings.parsers import Cell
from app.modules.ingestion.value_text import split_weekday


class CellKind(StrEnum):
    EMPTY = "EMPTY"
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"
    TIME = "TIME"


_NUMBER_TEXT = re.compile(
    r"^[-+]?\s*(?:€|\$|£|eur\b)?\s*\d[\d.,' ]*\s*(?:€|%|eur\b)?$", re.IGNORECASE
)
_ISO_DATE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$")
_SLASHED_DATE = re.compile(
    r"^\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def kind_of(cell: Cell) -> CellKind:
    if cell is None:
        return CellKind.EMPTY
    if isinstance(cell, bool):
        return CellKind.TEXT
    if isinstance(cell, datetime | date):
        return CellKind.DATE
    if isinstance(cell, time):
        return CellKind.TIME
    if isinstance(cell, int | float | Decimal):
        return CellKind.NUMBER
    text = str(cell).strip()
    if not text:
        return CellKind.EMPTY
    dated = split_weekday(text)[0]  # "gio 29/10/2026" is a date with its weekday in front
    if _ISO_DATE.match(dated) or _SLASHED_DATE.match(dated):
        return CellKind.DATE
    if _TIME.match(text):
        return CellKind.TIME
    if _NUMBER_TEXT.match(text):
        return CellKind.NUMBER
    return CellKind.TEXT


def text_of(cell: Cell) -> str:
    """A cell as plain text (dates as ISO, whole floats without `.0`)."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.date().isoformat() if cell.time() == time(0) else cell.isoformat(" ", "minutes")
    if isinstance(cell, date | time):
        return cell.isoformat()
    if isinstance(cell, bool):
        return "true" if cell else "false"
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else repr(cell)
    return " ".join(str(cell).split())


def is_value(cell: Cell) -> bool:
    """A number, a date or a time: something that is data, not a label."""
    return kind_of(cell) in {CellKind.NUMBER, CellKind.DATE, CellKind.TIME}


__all__ = ["CellKind", "is_value", "kind_of", "text_of"]

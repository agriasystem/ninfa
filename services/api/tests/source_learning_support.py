"""Files for Source Learning tests and its benchmark: a source as a hotel keeps it, in successive
versions (another month, columns moved, a junk column, a renamed header, a new column, a column
gone, a column whose meaning changed).

A file is described by `columns`: header -> KIND of its values. Order is the order of the columns.
Real `.xlsx` bytes with real dates and numbers, so the engine never has to guess a date order.
"""

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from tests.booking_support import xlsx_bytes

DEPARTMENTS = ("Reception", "Cucina", "Sala", "Housekeeping")
PEOPLE = ("Mario Rossi", "Giulia Bianchi", "Luca Verdi", "Anna Neri", "Paolo Gialli")
CHANNELS = ("Booking.com", "Diretto", "Expedia")
SUPPLIERS = ("Alfa Srl", "Beta SpA", "Gamma Snc")
EXPENSES = ("Pulizie", "Energia", "Forniture", "Manutenzione")


def _day(month: int, step: int) -> datetime:
    return datetime(2026, month, 1) + timedelta(days=step)


# One generator per kind of value: (row index, month) -> the cell.
KINDS: dict[str, Callable[[int, int], Any]] = {
    # staff
    "day": lambda i, m: _day(m, i // 4),
    "planned": lambda i, m: (6, 7, 8)[i % 3],
    "actual": lambda i, m: (6, 7.5, 8, 9)[i % 4],
    "dept": lambda i, m: DEPARTMENTS[i % 4],
    "people": lambda i, m: PEOPLE[i % len(PEOPLE)],
    # bookings
    "ref": lambda i, m: f"RES-{m:02d}{i:04d}",
    "booked": lambda i, m: _day(m, 0) - timedelta(days=10 + i % 5),
    "checkin": lambda i, m: _day(m, 2 + i % 20),
    "checkout": lambda i, m: _day(m, 3 + i % 20 + i % 3),
    "status": lambda i, m: ("Confermata", "Cancellata")[i % 7 == 0],
    "rooms": lambda i, m: 1 + i % 2,
    "revenue": lambda i, m: round(90 + (i * 13) % 170 + 0.5, 2),
    "channel": lambda i, m: CHANNELS[i % 3],
    # costs
    "supplier": lambda i, m: SUPPLIERS[i % 3],
    "invno": lambda i, m: f"FT/{m:02d}{i:03d}",
    "invdate": lambda i, m: _day(m, i % 25),
    "desc": lambda i, m: EXPENSES[i % 4],
    "net": lambda i, m: round(40 + (i * 37) % 800 + 0.25, 2),
    # anything
    "junk": lambda i, m: (i * 7) % 19,
    "note": lambda i, m: ("", "ok", "da verificare")[i % 3],
}


def xlsx_of(
    columns: Mapping[str, str], *, rows: int = 12, month: int = 11, sheet: str = "Foglio1"
) -> bytes:
    """A workbook with one sheet: a header row and `rows` data rows."""
    kinds = list(columns.values())
    body = [[KINDS[kind](i, month) for kind in kinds] for i in range(rows)]
    return xlsx_bytes({sheet: [list(columns), *body]})


def same_columns_with(
    columns: Mapping[str, str],
    *,
    move: tuple[str, int] | None = None,
    add: Mapping[str, str] | None = None,
    drop: str | None = None,
    rename: tuple[str, str] | None = None,
    retype: tuple[str, str] | None = None,
) -> dict[str, str]:
    """The columns of a later version of a source: one thing changed at most."""
    out = dict(columns)
    if retype is not None:
        out[retype[0]] = retype[1]
    if rename is not None:
        out = {(rename[1] if h == rename[0] else h): k for h, k in out.items()}
    if drop is not None:
        out.pop(drop)
    if add:
        out.update(add)
    if move is not None:
        header, to = move
        items = [(h, k) for h, k in out.items() if h != header]
        items.insert(to, (header, out[header]))
        out = dict(items)
    return out

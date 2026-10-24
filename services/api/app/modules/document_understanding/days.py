"""A persons x days grid, and the REAL dates of its day columns.

    Persona | Reparto | Lun | Mar | Mer | Gio | Ven | Sab | Dom | Totale
    Mario   | Reception |  8 |  8  |  8  |  8  |  8  |  0  |  0  |   40

becomes one row per person per day - but only when the days can be tied to real dates: the header
cells ARE dates, or the period is stated (in the title, or by the person). Otherwise the period is
asked; a date is never invented, and a weekly total is never spread over the days.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from app.modules.bookings.parsers import Cell
from app.modules.document_understanding.lexicon import MONTHS, WEEKDAYS
from app.modules.document_understanding.structure import Column
from app.modules.document_understanding.text import fold, has_word
from app.modules.document_understanding.values import text_of

MIN_DAY_COLUMNS = 3
_DAY_MONTH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?$")
_WEEKDAY_DAY = re.compile(r"^([a-zì]+)\s+(\d{1,2})(?:\s+([a-z]+))?$")
_ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")

DayKind = Literal["DATE", "WEEKDAY", "WEEKDAY_DAY", "DAY_MONTH"]


@dataclass(frozen=True, slots=True)
class DayColumn:
    index: int
    kind: DayKind
    weekday: int | None = None
    day: int | None = None
    month: int | None = None
    on: date | None = None


@dataclass(frozen=True, slots=True)
class DayGrid:
    columns: tuple[DayColumn, ...]
    # Columns next to the days that are totals of them ("Totale", "Ore settimana"): left out.
    total_columns: tuple[int, ...]
    # The upper header lines over the day columns ("Ore previste"): more than one = several blocks.
    groups: tuple[str, ...]


def _parse_day(column: Column) -> DayColumn | None:
    raw: Cell = column.raw
    if isinstance(raw, datetime):
        return DayColumn(column.index, "DATE", on=raw.date(), weekday=raw.weekday())
    if isinstance(raw, date):
        return DayColumn(column.index, "DATE", on=raw, weekday=raw.weekday())
    sub = column.label.rsplit(" - ", 1)[-1] if column.group else column.label
    text = fold(sub)
    if not text:
        return None
    iso = _ISO_DATE.match(sub.strip())
    if iso:
        parsed = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if parsed:
            return DayColumn(column.index, "DATE", on=parsed, weekday=parsed.weekday())
    match = _DAY_MONTH.match(sub.strip())
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = match.group(3)
        if year:
            parsed = _safe_date(int(year) + (2000 if len(year) == 2 else 0), month, day)
            if parsed:
                return DayColumn(column.index, "DATE", on=parsed, weekday=parsed.weekday())
        elif 1 <= day <= 31 and 1 <= month <= 12:
            return DayColumn(column.index, "DAY_MONTH", day=day, month=month)
        return None
    if text in WEEKDAYS:
        return DayColumn(column.index, "WEEKDAY", weekday=WEEKDAYS[text])
    parts = text.split()
    if (
        len(parts) in (2, 3)
        and parts[0] in WEEKDAYS
        and parts[1].isdigit()
        and 1 <= int(parts[1]) <= 31
    ):
        named_month = MONTHS.get(parts[2]) if len(parts) == 3 else None
        if len(parts) == 3 and named_month is None:
            return None
        return DayColumn(
            column.index,
            "WEEKDAY_DAY",
            weekday=WEEKDAYS[parts[0]],
            day=int(parts[1]),
            month=named_month,
        )
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _is_total_column(column: Column) -> bool:
    return has_word(column.label, ("tot", "totale", "totali", "total", "somma")) or (
        has_word(column.label, ("settimana", "week", "settimanali"))
        and has_word(column.label, ("ore", "hours"))
    )


def detect_day_grid(columns: Sequence[Column]) -> DayGrid | None:
    """The day columns of a table, when it is a grid of days (at least three of them)."""
    days = [parsed for column in columns if (parsed := _parse_day(column)) is not None]
    if len(days) < MIN_DAY_COLUMNS:
        return None
    last_day = days[-1].index
    totals = tuple(c.index for c in columns if c.index > last_day - 1 and _is_total_column(c))
    by_index = {c.index: c for c in columns}
    groups: list[str] = []
    for day in days:
        group = by_index[day.index].group
        if group and group not in groups:
            groups.append(group)
    return DayGrid(tuple(days), totals, tuple(groups))


@dataclass(frozen=True, slots=True)
class ResolvedDays:
    dates: tuple[tuple[int, date], ...]  # (column index, real date)
    anchor_source: Literal["HEADERS", "TITLE", "PERSON"]


def resolve_days(
    grid: DayGrid, *, title_start: date | None, person_start: date | None
) -> ResolvedDays | None:
    """Tie every day column to a real date, or None when that is not certain."""
    if all(day.kind == "DATE" and day.on for day in grid.columns):
        return ResolvedDays(tuple((d.index, d.on) for d in grid.columns if d.on), "HEADERS")
    anchor: date | None = None
    source: Literal["TITLE", "PERSON"] | None = None
    if person_start is not None:
        anchor, source = person_start, "PERSON"
    elif title_start is not None:
        anchor, source = title_start, "TITLE"
    if anchor is None or source is None:
        return None
    if source == "PERSON":
        # The person names ANY day of the week the file is about: the week starts on the weekday of
        # the grid's first column, on or before that day.
        first = next(
            (d.weekday for d in grid.columns if d.kind != "DATE" and d.weekday is not None), None
        )
        if first is not None:
            anchor -= timedelta(days=(anchor.weekday() - first) % 7)
    resolved: list[tuple[int, date]] = []
    cursor = anchor
    for day in grid.columns:
        if day.kind == "DATE" and day.on:
            resolved.append((day.index, day.on))
            cursor = day.on + timedelta(days=1)
            continue
        found: date | None = None
        if day.kind == "DAY_MONTH" and day.day and day.month:
            year = anchor.year
            found = _safe_date(year, day.month, day.day)
            if found is not None and (anchor - found).days > 200:
                found = _safe_date(year + 1, day.month, day.day)
        elif day.weekday is not None:
            probe = cursor
            for _ in range(7):
                if probe.weekday() == day.weekday:
                    found = probe
                    break
                probe += timedelta(days=1)
            if found is not None and day.day is not None and found.day != day.day:
                return None  # "Lun 26" that is not a Monday the 26th: the dates do not fit
        if found is None:
            return None
        resolved.append((day.index, found))
        cursor = found + timedelta(days=1)
    dates = [d for _, d in resolved]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        return None
    return ResolvedDays(tuple(resolved), source)


def hours_basis(grid: DayGrid, *texts: str) -> Literal["planned_hours", "actual_hours"] | None:
    """Planned or actual hours, when the group over the days, the title or the sheet says which."""
    planned = (
        "previste",
        "previsto",
        "pianificate",
        "programmate",
        "planned",
        "scheduled",
        "budget",
    )
    actual = (
        "effettive",
        "effettivo",
        "lavorate",
        "reali",
        "consuntivo",
        "actual",
        "worked",
        "timbrate",
    )
    haystack = [*grid.groups, *texts]
    has_planned = any(has_word(t, planned) for t in haystack)
    has_actual = any(has_word(t, actual) for t in haystack)
    if has_planned and not has_actual:
        return "planned_hours"
    if has_actual and not has_planned:
        return "actual_hours"
    return None


__all__ = [
    "DayColumn",
    "DayGrid",
    "ResolvedDays",
    "detect_day_grid",
    "hours_basis",
    "resolve_days",
    "text_of",
]

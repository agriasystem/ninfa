"""The VIRTUAL table: what a document looks like once its structure is understood.

The importers read a header and rows. A hotel's file is a title, a summary, a header (maybe on two
lines), people grouped under department lines, a total, notes - maybe a grid of days, maybe one
sheet per department. This module turns that into the simple table the importers (and their rules,
unchanged) already know:

    * the header is the one found, two-level headers joined, duplicates made unique;
    * totals, notes and section lines are not rows (they are reported, never imported);
    * a department that is a section line, a sheet name or the title becomes a column of its own;
    * a persons x days grid becomes one row per person per day, with the day as a real date;
    * several sheets that are the same table become one table.

Nothing is invented: a cell is passed on exactly as read (a value that is not a number is passed on
as it is, so the importer rejects it - it is not dropped), and a date that cannot be tied to the
calendar stops the reading with a precise reason instead of guessing.
"""

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.parsers import Cell, SourceRow, SourceTable, limit_rows
from app.modules.document_understanding.days import resolve_days
from app.modules.document_understanding.document import DocumentUnderstanding, Selection, understand
from app.modules.document_understanding.grid import ensure_columns, iter_rows, scan_workbook
from app.modules.document_understanding.layout import LayoutSpec
from app.modules.document_understanding.structure import (
    Column,
    Row,
    RowKind,
    as_decimal,
    classify_row,
    row_features,
)
from app.modules.document_understanding.text import fold
from app.modules.document_understanding.titles import department_words

DEPARTMENT_HEADERS = {
    "SECTION": "Reparto (sezione)",
    "SHEET": "Reparto (foglio)",
    "TITLE": "Reparto (titolo)",
}
DATE_HEADER = "Data"
HOURS_HEADERS = {"planned_hours": "Ore previste", "actual_hours": "Ore effettive"}
_LOOKAHEAD = 5


def needs(reason: str, message: str, **details: object) -> BookingImportError:
    """The file cannot be read as asked yet: something has to be decided first (`reason` says
    what)."""
    return BookingImportError(
        BookingErrorCode.MAPPING_REQUIRED, message, details={"reason": reason, **details}
    )


@dataclass(frozen=True, slots=True)
class TablePlan:
    """How the virtual table is made, decided once from the understanding and the layout."""

    selection: Selection
    headers: tuple[str, ...]
    # For each table of the selection: where, in ITS rows, each source column of the header is.
    sources: tuple[tuple[int | None, ...], ...]
    day_dates: tuple[tuple[int, date], ...] | None
    department_kind: str | None
    title_label: str | None
    renumber: bool

    @property
    def source_width(self) -> int:
        return len(self.sources[0]) if self.sources else 0


@dataclass(frozen=True)
class LayoutTable(SourceTable):
    """A `SourceTable` that remembers how it was made (for explanations and error locations)."""

    plan: TablePlan | None = None


def _unique(name: str, taken: set[str]) -> str:
    candidate, number = name, 1
    while fold(candidate) in taken:
        number += 1
        candidate = f"{name} ({number})"
    taken.add(fold(candidate))
    return candidate


def build_plan(document: DocumentUnderstanding, layout: LayoutSpec | None) -> TablePlan:
    layout = layout or LayoutSpec()
    selection = document.chosen
    if selection is None:
        raise BookingImportError(BookingErrorCode.EMPTY_FILE, "The file contains no table of data")
    first = selection.first
    kept: list[Column] = list(first.columns)
    day_dates: tuple[tuple[int, date], ...] | None = None
    hours_header: str | None = None
    if layout.grid is not None:
        grid = selection.day_grid
        if grid is None:
            raise needs("grid_not_found", "The table is not a grid of days")
        if selection.partition or len(grid.groups) > 1:
            raise needs(
                "grid_not_supported", "A grid over several sheets or blocks is not supported"
            )
        resolved = resolve_days(
            grid,
            title_start=selection.period.start if selection.period else None,
            person_start=layout.period_start,
        )
        if resolved is None:
            raise needs("period_required", "The days of the grid need the period they belong to")
        skipped_columns = {day.index for day in grid.columns} | set(grid.total_columns)
        kept = [column for column in first.columns if column.index not in skipped_columns]
        day_dates = resolved.dates
        hours_header = HOURS_HEADERS[layout.grid.hours_field]

    taken: set[str] = set()
    headers = [_unique(column.label, taken) for column in kept]
    department_kind = layout.department.kind if layout.department else None
    if department_kind:
        headers.append(_unique(DEPARTMENT_HEADERS[department_kind], taken))
    if day_dates is not None and hours_header is not None:
        headers.append(_unique(DATE_HEADER, taken))
        headers.append(_unique(hours_header, taken))

    sources: list[tuple[int | None, ...]] = []
    for table in selection.tables:
        by_label = {fold(column.label): column.index for column in table.columns}
        sources.append(tuple(by_label.get(fold(column.label)) for column in kept))
    words = department_words(selection.preamble) if department_kind == "TITLE" else []
    ensure_columns(len(headers))
    return TablePlan(
        selection=selection,
        headers=tuple(headers),
        sources=tuple(sources),
        day_dates=day_dates,
        department_kind=department_kind,
        title_label=words[0] if len(words) == 1 else None,
        renumber=selection.partition or day_dates is not None,
    )


def _followers(
    rows: Iterator[tuple[int, list[Cell]]], start: int, end: int
) -> Iterator[tuple[Row, list[Row]]]:
    """Each non-blank row of the body with the few non-blank rows that follow it."""
    ahead: deque[Row] = deque()
    exhausted = False

    def refill() -> None:
        nonlocal exhausted
        while not exhausted and len(ahead) <= _LOOKAHEAD:
            try:
                number, cells = next(rows)
            except StopIteration:
                exhausted = True
                return
            if number > end:
                exhausted = True
                return
            if number >= start and any(cell is not None for cell in cells):
                ahead.append(row_features(number, cells))

    refill()
    while ahead:
        current = ahead.popleft()
        refill()
        yield current, list(ahead)[:_LOOKAHEAD]


def generate(
    content: bytes,
    filename: str,
    plan: TablePlan,
    *,
    delimiter: str | None,
    encoding: str | None,
) -> Iterator[tuple[int, list[Cell], str, int]]:
    """The rows of the virtual table: (number, cells, source sheet, source row)."""
    counter = 1
    for table, mapping in zip(plan.selection.tables, plan.sources, strict=True):
        sheet = table.sheet or None
        scan_sections = dict(table.sections)
        width = len(table.columns)
        section: str | None = None
        note_started = False
        stream = iter_rows(content, filename, sheet, delimiter=delimiter, encoding=encoding)
        for row, followers in _followers(stream, table.header_rows[-1] + 1, table.last_row):
            if note_started:
                continue
            kind = (
                RowKind.SECTION
                if row.number in scan_sections
                else classify_row(row, followers, width)
            )
            if kind == RowKind.SECTION:
                section = row.first_text
                continue
            if kind == RowKind.NOTE:
                note_started = True
                continue
            if kind != RowKind.DATA:
                continue
            cells: tuple[Cell, ...] = row.cells
            base: list[Cell] = [
                cells[index] if index is not None and index < len(cells) else None
                for index in mapping
            ]
            label: str | None = None
            if plan.department_kind == "SECTION":
                label = section
            elif plan.department_kind == "SHEET":
                label = table.sheet or None
            elif plan.department_kind == "TITLE":
                label = plan.title_label
            extras: list[Cell] = [label] if plan.department_kind else []
            number: int = row.number
            if plan.day_dates is None:
                counter += 1
                yield (counter if plan.renumber else number), base + extras, table.sheet, number
                continue
            for column, day in plan.day_dates:
                value = cells[column] if column < len(cells) else None
                if value is None:
                    continue
                amount = as_decimal(value)
                if amount is not None and amount == Decimal(0):
                    continue  # a day off is "not scheduled", not "scheduled for zero hours"
                counter += 1
                yield (
                    counter,
                    [*base, *extras, datetime(day.year, day.month, day.day), value],
                    table.sheet,
                    number,
                )


def open_layout_table(
    content: bytes,
    filename: str,
    layout: LayoutSpec,
    *,
    delimiter: str | None = None,
    encoding: str | None = None,
    document: DocumentUnderstanding | None = None,
) -> LayoutTable:
    """The virtual table of a file under a layout (what the import services read)."""
    document = document or understand(
        scan_workbook(content, filename, delimiter=delimiter, encoding=encoding), layout
    )
    plan = build_plan(document, layout)
    file_type: Literal["csv", "xlsx"] = "xlsx" if document.file_type == "xlsx" else "csv"
    sheet_name = None if plan.selection.partition else (plan.selection.first.sheet or None)

    def rows() -> Iterator[SourceRow]:
        for number, cells, _sheet, _row in generate(
            content, filename, plan, delimiter=delimiter, encoding=encoding
        ):
            yield SourceRow(number, cells + [None] * (len(plan.headers) - len(cells)))

    return LayoutTable(
        file_type,
        list(plan.headers),
        sheet_name,
        lambda: limit_rows(rows()),
        plan,
    )


def locate_rows(
    content: bytes,
    filename: str,
    table: LayoutTable,
    numbers: set[int],
    *,
    delimiter: str | None = None,
    encoding: str | None = None,
) -> dict[int, tuple[str, int]]:
    """Where, in the FILE, the rows of the virtual table (by number) come from: (sheet, row)."""
    plan = table.plan
    if plan is None or not numbers:
        return {}
    found: dict[int, tuple[str, int]] = {}
    for number, _cells, sheet, source_row in generate(
        content, filename, plan, delimiter=delimiter, encoding=encoding
    ):
        if number in numbers:
            found[number] = (sheet, source_row)
    return found


__all__ = [
    "DATE_HEADER",
    "DEPARTMENT_HEADERS",
    "HOURS_HEADERS",
    "LayoutTable",
    "TablePlan",
    "build_plan",
    "generate",
    "locate_rows",
    "needs",
    "open_layout_table",
]

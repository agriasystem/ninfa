"""What a whole workbook is: which sheets hold the data, which are summaries, which table to read.

A sheet is DATA (it has a table of records), SUMMARY (a recap, a legend, a chart page), EMPTY or
HIDDEN. Sheets that are the SAME table over and over - one sheet per department, every sheet with
the same columns - are one logical table (a `Selection` with `partition=True`): the name of each
sheet is then information about its rows. Everything the document offers is returned, best first,
and a clear winner is chosen; when two tables are comparable the caller decides (it knows the kind
of data).
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.document_understanding.days import DayGrid, detect_day_grid
from app.modules.document_understanding.grid import SheetScan, WorkbookScan
from app.modules.document_understanding.layout import LayoutSpec
from app.modules.document_understanding.lexicon import SUMMARY_SHEET_WORDS
from app.modules.document_understanding.structure import TableCandidate, analyze_sheet
from app.modules.document_understanding.text import fold, has_word
from app.modules.document_understanding.titles import DateRange, parse_period

# A table this much bigger than the next one is simply "the" table.
CLEAR_WINNER = 1.6
_ALIKE = 0.8


class SheetRole(StrEnum):
    DATA = "DATA"
    SUMMARY = "SUMMARY"
    EMPTY = "EMPTY"
    HIDDEN = "HIDDEN"


@dataclass(slots=True)
class SheetInfo:
    name: str
    role: SheetRole
    last_row: int
    tables: list[TableCandidate] = field(default_factory=list)


@dataclass(slots=True)
class Selection:
    """One thing the person could mean by "the table of this file"."""

    key: str
    tables: tuple[TableCandidate, ...]
    partition: bool
    day_grid: DayGrid | None
    period: DateRange | None
    preamble: tuple[str, ...]

    @property
    def value(self) -> int:
        return sum(t.value for t in self.tables)

    @property
    def title(self) -> str | None:
        return self.preamble[0] if self.preamble else None

    @property
    def first(self) -> TableCandidate:
        return self.tables[0]


@dataclass(slots=True)
class DocumentUnderstanding:
    file_type: str
    delimiter: str | None
    sheets: list[SheetInfo]
    selections: list[Selection]
    chosen: Selection | None
    # Two comparable tables: which one is the right one is a question for the caller to settle.
    ambiguous: bool = False

    @property
    def data_sheets(self) -> list[str]:
        return [s.name for s in self.sheets if s.role == SheetRole.DATA]


def _labels(table: TableCandidate) -> frozenset[str]:
    return frozenset(fold(c.label) for c in table.columns)


def _alike(a: frozenset[str], b: frozenset[str]) -> bool:
    union = a | b
    return bool(union) and len(a & b) / len(union) >= _ALIKE


def _key(tables: tuple[TableCandidate, ...]) -> str:
    return "+".join(t.sheet or "-" for t in tables) + f"#{tables[0].header_rows[-1]}"


def _selection(tables: tuple[TableCandidate, ...], partition: bool) -> Selection:
    first = tables[0]
    sheet_lines = tuple(t.sheet for t in tables[:1] if t.sheet)
    return Selection(
        key=_key(tables),
        tables=tables,
        partition=partition,
        day_grid=detect_day_grid(first.columns),
        period=parse_period([*first.preamble, *sheet_lines]),
        preamble=first.preamble,
    )


def understand(scan: WorkbookScan, layout: LayoutSpec | None = None) -> DocumentUnderstanding:
    """Read the structure of every sheet and the tables the document offers."""
    chosen_sheets = set(layout.sheets) if layout and layout.sheets else None
    infos: list[SheetInfo] = []
    analysed: list[tuple[SheetScan, SheetInfo]] = []
    for sheet in scan.sheets:
        if not sheet.visible:
            infos.append(SheetInfo(sheet.name, SheetRole.HIDDEN, sheet.last_row))
            continue
        tables = analyze_sheet(sheet)
        role = SheetRole.EMPTY if sheet.last_row == 0 else SheetRole.DATA
        info = SheetInfo(sheet.name, role, sheet.last_row, tables)
        infos.append(info)
        if tables and (chosen_sheets is None or sheet.name in chosen_sheets):
            analysed.append((sheet, info))

    named_summary = {
        info.name
        for _, info in analysed
        if has_word(info.name, SUMMARY_SHEET_WORDS) and chosen_sheets is None
    }
    if len(named_summary) < len(analysed):
        analysed = [(s, i) for s, i in analysed if i.name not in named_summary]

    best = [(info.name, info.tables[0]) for _, info in analysed]
    groups: list[list[TableCandidate]] = []
    for _, table in best:
        for group in groups:
            if _alike(_labels(group[0]), _labels(table)):
                group.append(table)
                break
        else:
            groups.append([table])

    in_partition = {id(t) for g in groups if len(g) > 1 for t in g}
    selections: list[Selection] = [_selection(tuple(g), True) for g in groups if len(g) > 1]
    for _, info in analysed:
        selections.extend(_selection((t,), False) for t in info.tables if id(t) not in in_partition)
    selections.sort(key=lambda s: (-s.value, s.first.header_rows[0]))

    used = {t.sheet for s in selections[:1] for t in s.tables}
    top = selections[0].value if selections else 0
    for info in infos:
        if info.role != SheetRole.DATA:
            continue
        in_a_selection = any(t.sheet == info.name for s in selections for t in s.tables)
        if (
            info.name in named_summary
            or not info.tables
            or (info.name not in used and in_a_selection and info.tables[0].value < 0.25 * top)
        ):
            info.role = SheetRole.SUMMARY
        elif not info.tables:
            info.role = SheetRole.EMPTY

    chosen: Selection | None = None
    ambiguous = False
    if layout and layout.table_key:
        chosen = next((s for s in selections if s.key == layout.table_key), None)
    if chosen is None and selections:
        chosen = selections[0]
        if len(selections) > 1 and selections[0].value < CLEAR_WINNER * selections[1].value:
            ambiguous = True
    return DocumentUnderstanding(
        file_type=scan.file_type,
        delimiter=scan.delimiter,
        sheets=infos,
        selections=selections,
        chosen=chosen,
        ambiguous=ambiguous and not (layout and layout.table_key),
    )


__all__ = [
    "CLEAR_WINNER",
    "DocumentUnderstanding",
    "Selection",
    "SheetInfo",
    "SheetRole",
    "understand",
]

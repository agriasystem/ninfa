"""Where the table is, in a sheet that is not just a table.

A hotel's file usually starts with a title, a line about the period, a small summary, and only then
the header row; it ends with a total and a few notes; its department may be a row of its own
("RECEPTION") above the people. This module reads the grid of ONE sheet and answers:

    - which row is the header (one row, or two: a group row over a label row)?
    - which rows are data, and which are totals, section lines or notes (never data)?
    - do the totals add up (evidence that the table's edges are right)?
    - is there more than one table?

Nothing here is a business rule: the vocabulary is generic (`lexicon`), every decision is a plain
look at the cells, and whatever is left out of the table is REPORTED (kind, row, first words), never
dropped silently.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import ceil
from typing import Literal

from app.modules.bookings.parsers import Cell
from app.modules.document_understanding.grid import MergedRange, SheetScan
from app.modules.document_understanding.lexicon import (
    HEADER_STEMS,
    NOTE_PREFIXES,
    SECTION_WORDS,
    TOTAL_WORDS,
)
from app.modules.document_understanding.text import fold, stem, tokens
from app.modules.document_understanding.values import CellKind, kind_of, text_of

HEADER_SEARCH_ROWS = 150
MAX_TABLES_PER_SHEET = 3
_TEXT_PREVIEW = 60
_PREAMBLE_CHARS = 300


class RowKind(StrEnum):
    BLANK = "BLANK"
    DATA = "DATA"
    TOTAL = "TOTAL"
    SECTION = "SECTION"
    NOTE = "NOTE"


@dataclass(frozen=True, slots=True)
class Column:
    """One column of the table as the importers will see it."""

    index: int  # 0-based position in the sheet's rows
    label: str  # what the header says (two-level headers are joined: "Previste - Ore")
    group: str | None = None  # the upper header line, when there is one
    raw: Cell = None  # the header cell itself (a real date stays a date: day grids need it)
    renamed: bool = False  # the label was made unique or filled in (two columns called "Ore")


@dataclass(frozen=True, slots=True)
class SkippedRow:
    number: int
    kind: RowKind
    text: str


@dataclass(frozen=True, slots=True)
class TotalCheck:
    """A total row and whether it adds up the rows it should."""

    row: int
    label: str
    checked: int  # numeric columns compared
    matched: int
    state: Literal["MATCH", "PARTIAL", "MISMATCH", "UNVERIFIED"]


@dataclass(slots=True)
class TableCandidate:
    sheet: str
    header_rows: tuple[int, ...]
    first_row: int
    last_row: int
    columns: tuple[Column, ...]
    data_rows: int
    skipped: tuple[SkippedRow, ...]
    totals: tuple[TotalCheck, ...]
    sections: tuple[tuple[int, str], ...]
    score: float
    lexicon_ratio: float
    # Every row of the table was inside the scan window (so counts and totals are exact).
    complete_scan: bool
    # The non-blank lines above the header, as text: the title first, then what describes the file.
    preamble: tuple[str, ...] = ()
    # The header cells were made unique or filled in (see `Column.renamed`).
    renamed_headers: int = 0

    @property
    def title(self) -> str | None:
        return self.preamble[0] if self.preamble else None

    @property
    def width(self) -> int:
        return len(self.columns)

    @property
    def value(self) -> int:
        """How much table this is (rows x columns): the biggest table is usually the one."""
        return max(self.data_rows, 0) * max(self.width, 1)


# --- looking at one row ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Row:
    number: int
    cells: tuple[Cell, ...]
    positions: tuple[int, ...]
    n: int
    n_text: int
    n_value: int  # numbers and times
    n_date: int
    texts: tuple[str, ...]

    @property
    def first_text(self) -> str:
        return self.texts[0] if self.texts else ""


def _features(number: int, cells: list[Cell]) -> _Row:
    positions: list[int] = []
    n_text = n_value = n_date = 0
    texts: list[str] = []
    for index, cell in enumerate(cells):
        kind = kind_of(cell)
        if kind == CellKind.EMPTY:
            continue
        positions.append(index)
        if kind == CellKind.TEXT:
            n_text += 1
            texts.append(text_of(cell))
        elif kind == CellKind.DATE:
            n_date += 1
        else:
            n_value += 1
    return _Row(
        number,
        tuple(cells),
        tuple(positions),
        len(positions),
        n_text,
        n_value,
        n_date,
        tuple(texts),
    )


def _label_row(row: _Row) -> bool:
    """Made of labels: at least two cells, nearly all text (dates count when they are day
    columns)."""
    if row.n < 2 or row.n_text < 1:
        return False
    labelish = row.n_text + (row.n_date if row.n_date >= 3 else 0)
    return labelish / row.n >= 0.75


def _lexicon_ratio(row: _Row) -> float:
    labels = [
        text_of(row.cells[p]) for p in row.positions if kind_of(row.cells[p]) == CellKind.TEXT
    ]
    if not labels:
        return 0.0
    return sum(1 for label in labels if tokens(label) & HEADER_STEMS) / len(labels)


def _preview(text: str) -> str:
    return text if len(text) <= _TEXT_PREVIEW else text[: _TEXT_PREVIEW - 1] + "…"


# --- what a row is, inside a table ----------------------------------------------------------------


def is_total_label(text: str) -> bool:
    folded = fold(text)
    return any(folded == fold(word) or folded.startswith(fold(word) + " ") for word in TOTAL_WORDS)


def is_note_text(text: str) -> bool:
    folded = fold(text)
    return any(folded == fold(p) or folded.startswith(fold(p) + " ") for p in NOTE_PREFIXES)


_SECTION_FILLER = frozenset({"e", "ed", "di", "del", "della", "dei", "delle", "and", "da", "per"})


def looks_like_section(text: str, *, merged_wide: bool = False) -> bool:
    """A line that names a group of the rows below it ("RECEPTION", "Sala e bar"): short, not a
    note, and shouty or made of department words - never a person's name written in full."""
    if not text or is_note_text(text) or len(text) > 50:
        return False
    if merged_wide:
        return True
    letters = [ch for ch in text if ch.isalpha()]
    if letters and text.upper() == text and len(letters) >= 3:
        return True
    words = [w for w in fold(text).split() if w not in _SECTION_FILLER]
    return bool(words) and all(stem(w) in SECTION_WORDS for w in words)


def _wide(spans: list[tuple[int, int]], width: int) -> bool:
    """A merged block that covers a good part of the table (a line that belongs to all of it)."""
    return any(end - start + 1 >= max(3, ceil(0.5 * width)) for start, end in spans)


def classify_row(
    row: _Row, followers: Sequence[_Row], width: int, *, merged_wide: bool = False
) -> RowKind:
    """What a row of the body is, from the row and the few non-blank rows that follow it.

    The SAME rules are used to scan a sheet and to stream it for the import, so the table NINFA
    describes is exactly the table it reads."""
    if row.n == 0:
        return RowKind.BLANK
    if is_total_label(row.first_text) and (row.n_value or row.n <= 2):
        return RowKind.TOTAL
    if row.n == 1 and kind_of(row.cells[row.positions[0]]) == CellKind.TEXT:
        text = text_of(row.cells[row.positions[0]])
        if is_note_text(text) or len(text) > 80:
            return RowKind.NOTE
        followed = any(f.n >= 2 and (f.n_value or f.n_date) for f in followers)
        if followed and looks_like_section(text, merged_wide=merged_wide):
            return RowKind.SECTION
    return RowKind.DATA


Row = _Row


def row_features(number: int, cells: list[Cell]) -> Row:
    return _features(number, cells)


# --- the header -----------------------------------------------------------------------------------


def _col_letter(index: int) -> str:
    letters = ""
    number = index + 1
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _spans_by_row(merged: tuple[MergedRange, ...]) -> dict[int, list[tuple[int, int]]]:
    spans: dict[int, list[tuple[int, int]]] = {}
    for block in merged:
        if block.max_col <= block.min_col:
            continue
        for number in range(block.min_row, min(block.max_row, block.min_row + 3) + 1):
            spans.setdefault(number, []).append((block.min_col - 1, block.max_col - 1))
    return spans


def _group_labels(
    group: _Row,
    header: _Row,
    spans: dict[int, list[tuple[int, int]]],
) -> list[str] | None:
    """The upper header line spread over the columns it covers, or None when that row is not one.

    A group row sits directly above the label row, is made of text only, has at least two groups
    and is told apart from a title by a merged block over several columns, a group written once per
    column, or labels underneath that repeat ("Ore", "Costo", "Ore", "Costo")."""
    if group.n < 2 or group.n_value or group.n_date:
        return None
    width = (header.positions[-1] + 1) if header.positions else 0
    merged_spans = [span for span in spans.get(group.number, []) if span[1] > span[0]]
    texts = [text_of(group.cells[p]) for p in group.positions]
    repeated = (
        any(a == b for a, b in zip(texts, texts[1:], strict=False)) and group.n >= width * 0.6
    )
    header_labels = [fold(text_of(header.cells[p])) for p in header.positions]
    duplicated = len(set(header_labels)) < len(header_labels)
    if not (merged_spans or repeated or duplicated):
        return None
    labels: list[str] = [""] * width
    if repeated:
        for position in group.positions:
            if position < width:
                labels[position] = text_of(group.cells[position])
        return labels
    ends = {start: end for start, end in merged_spans}
    next_group = list(group.positions[1:]) + [width]
    for position, following in zip(group.positions, next_group, strict=True):
        end = ends.get(position, following - 1)
        for column in range(position, min(max(end, position) + 1, width)):
            labels[column] = text_of(group.cells[position])
    return labels


def _build_columns(
    header: _Row, group_labels: list[str] | None, taken_width: int
) -> tuple[tuple[Column, ...], int]:
    """The columns of the table, with labels that are unique and never empty."""
    width = max(taken_width, (header.positions[-1] + 1) if header.positions else 0)
    columns: list[Column] = []
    seen: dict[str, int] = {}
    renamed_count = 0
    for index in range(width):
        cell = header.cells[index] if index < len(header.cells) else None
        sub = text_of(cell) if kind_of(cell) != CellKind.EMPTY else ""
        group = group_labels[index] if group_labels and index < len(group_labels) else ""
        group_text = group if group and fold(group) != fold(sub) else ""
        label = f"{group_text} - {sub}" if group_text and sub else (sub or group_text)
        renamed = False
        if not label:
            label, renamed = f"Colonna {_col_letter(index)}", True
        key = fold(label)
        if key in seen:
            seen[key] += 1
            label, renamed = f"{label} ({seen[key]})", True
        else:
            seen[key] = 1
        renamed_count += 1 if renamed else 0
        columns.append(Column(index, label, group_text or None, cell, renamed))
    return tuple(columns), renamed_count


# --- the extent of a table ------------------------------------------------------------------------


@dataclass(slots=True)
class _Body:
    data: list[int] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    totals: list[TotalCheck] = field(default_factory=list)
    sections: list[tuple[int, str]] = field(default_factory=list)
    last_row: int = 0
    complete: bool = True


def _is_dense(row: _Row, width: int) -> bool:
    return row.n >= max(2, ceil(0.5 * width))


def _total_check(
    row: _Row,
    rows: dict[int, _Row],
    data_numbers: list[int],
    since: int,
    columns: tuple[Column, ...],
) -> TotalCheck:
    """Does this total row add up the data rows above it (since the last total or section)?"""
    label = _preview(row.first_text or "TOTALE")
    members = [rows[n] for n in data_numbers if since < n < row.number and n in rows]
    if not members:
        return TotalCheck(row.number, label, 0, 0, "UNVERIFIED")
    checked = matched = 0
    for column in columns:
        total_cell = row.cells[column.index] if column.index < len(row.cells) else None
        if kind_of(total_cell) != CellKind.NUMBER:
            continue
        total = _as_decimal(total_cell)
        parts = [
            _as_decimal(m.cells[column.index] if column.index < len(m.cells) else None)
            for m in members
        ]
        numbers = [p for p in parts if p is not None]
        if total is None or not numbers:
            continue
        checked += 1
        if abs(sum(numbers, Decimal(0)) - total) <= Decimal("0.011"):
            matched += 1
    if not checked:
        return TotalCheck(row.number, label, 0, 0, "UNVERIFIED")
    state: Literal["MATCH", "PARTIAL", "MISMATCH"] = (
        "MATCH" if matched == checked else ("PARTIAL" if matched else "MISMATCH")
    )
    return TotalCheck(row.number, label, checked, matched, state)


def _as_decimal(cell: Cell) -> Decimal | None:
    if isinstance(cell, bool) or cell is None:
        return None
    if isinstance(cell, int | float | Decimal):
        try:
            return Decimal(str(cell))
        except InvalidOperation:
            return None
    text = str(cell).strip().replace("€", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _walk_body(
    scan: SheetScan,
    rows: dict[int, _Row],
    first: int,
    columns: tuple[Column, ...],
    spans: dict[int, list[tuple[int, int]]],
    stop_at: int | None,
) -> _Body:
    """Classify every row after the header: data, total, section line or note."""
    width = len(columns)
    body = _Body()
    numbers = sorted(n for n in rows if n >= first and (stop_at is None or n < stop_at))
    body.complete = scan.last_row <= len(scan.head) or not scan.tail
    data_since_total: list[int] = []
    last_total_or_section = first - 1
    last_dense = 0
    note_started = False
    for position, number in enumerate(numbers):
        row = rows[number]
        if row.n == 0:
            continue
        if note_started:
            body.skipped.append(SkippedRow(number, RowKind.NOTE, _preview(row.first_text)))
            continue
        wide = _wide(spans.get(number, []), width)
        followers = [rows[m] for m in numbers[position + 1 : position + 6] if rows[m].n]
        kind = classify_row(row, followers, width, merged_wide=wide)
        first_text = row.first_text
        if kind == RowKind.TOTAL:
            body.totals.append(
                _total_check(row, rows, data_since_total, last_total_or_section, columns)
            )
            body.skipped.append(SkippedRow(number, RowKind.TOTAL, _preview(first_text)))
            last_total_or_section = number
            data_since_total = []
            continue
        if kind == RowKind.NOTE:
            note_started = True
            body.skipped.append(SkippedRow(number, RowKind.NOTE, _preview(first_text)))
            continue
        if kind == RowKind.SECTION:
            body.sections.append((number, first_text))
            body.skipped.append(SkippedRow(number, RowKind.SECTION, _preview(first_text)))
            last_total_or_section = number
            data_since_total = []
            continue
        body.data.append(number)
        data_since_total.append(number)
        if _is_dense(row, width):
            last_dense = number
    # Sparse rows after the last dense one are a footer ("Totale persone: 13", "Generato il ..."),
    # not records: take them out of the data, but report them.
    if last_dense:
        tail = [n for n in body.data if n > last_dense]
        for number in tail:
            body.data.remove(number)
            body.skipped.append(SkippedRow(number, RowKind.NOTE, _preview(rows[number].first_text)))
    body.last_row = max([last_dense, *[t.row for t in body.totals], *[s[0] for s in body.sections]])
    body.skipped.sort(key=lambda item: item.number)
    return body


# --- one sheet ------------------------------------------------------------------------------------


def _row_map(scan: SheetScan) -> dict[int, _Row]:
    rows = {n: _features(n, cells) for n, cells in enumerate(scan.head, start=1) if cells}
    for number, cells in scan.tail:
        rows[number] = _features(number, cells)
    return rows


def analyze_sheet(scan: SheetScan) -> list[TableCandidate]:
    """The tables of one sheet, best first. A sheet with nothing in it has none."""
    if scan.last_row == 0:
        return []
    rows = _row_map(scan)
    spans = _spans_by_row(scan.merged)
    ordered = sorted(rows)
    tables: list[TableCandidate] = []
    claimed: list[tuple[int, int]] = []
    for _ in range(MAX_TABLES_PER_SHEET):
        found = _best_table(scan, rows, ordered, spans, claimed)
        if found is None:
            break
        tables.append(found)
        claimed.append((found.header_rows[0], max(found.last_row, found.header_rows[-1])))
    # The lines above each table, up to the end of the table before it.
    floor = 0
    for table in sorted(tables, key=lambda t: t.header_rows[0]):
        table.preamble = tuple(
            " ".join(rows[n].texts + _value_texts(rows[n]))[:_PREAMBLE_CHARS]
            for n in ordered
            if floor < n < table.header_rows[0] and rows[n].n
        )
        floor = max(table.last_row, table.header_rows[-1])
    tables.sort(key=lambda t: (-t.value, t.header_rows[0]))
    return tables


def _best_table(
    scan: SheetScan,
    rows: dict[int, _Row],
    ordered: list[int],
    spans: dict[int, list[tuple[int, int]]],
    claimed: list[tuple[int, int]],
) -> TableCandidate | None:
    def inside(number: int) -> bool:
        return any(start <= number <= end for start, end in claimed)

    candidates: list[TableCandidate] = []
    search = [n for n in ordered if n <= HEADER_SEARCH_ROWS and not inside(n)]
    max_n = max((rows[n].n for n in search), default=0)
    for number in search:
        row = rows[number]
        if not _label_row(row) or row.n < 2:
            continue
        # The label row of a two-level header is the lower one: it is the one with data under it.
        group = rows.get(number - 1) if not inside(number - 1) else None
        group_labels = _group_labels(group, row, spans) if group is not None else None
        columns, renamed = _build_columns(row, group_labels, row.positions[-1] + 1)
        stop = _next_header(rows, ordered, number, row, spans)
        next_claimed = min((start for start, _ in claimed if start > number), default=None)
        if next_claimed is not None:
            stop = next_claimed if stop is None else min(stop, next_claimed)
        body = _walk_body(scan, rows, number + 1, columns, spans, stop)
        if not body.data:
            continue
        lexicon = _lexicon_ratio(row)
        data_count = len(body.data)
        if not body.complete:
            data_count = max(data_count, scan.last_row - number - len(body.skipped))
        text_ratio = row.n_text / row.n
        score = (
            0.35 * lexicon
            + 0.25 * min(1.0, data_count / 8)
            + 0.15 * (row.n / max_n if max_n else 0)
            + 0.15 * text_ratio
            + 0.10
            * (1.0 if len({fold(text_of(c)) for c in row.cells if c is not None}) >= row.n else 0.5)
        )
        header_rows = (number - 1, number) if group_labels is not None else (number,)
        candidates.append(
            TableCandidate(
                sheet=scan.name,
                header_rows=header_rows,
                first_row=body.data[0],
                last_row=body.last_row,
                columns=columns,
                data_rows=data_count,
                skipped=tuple(body.skipped),
                totals=tuple(body.totals),
                sections=tuple(body.sections),
                score=score,
                lexicon_ratio=lexicon,
                complete_scan=body.complete,
                renamed_headers=renamed,
            )
        )
    if not candidates:
        return None
    biggest = max(c.value for c in candidates) or 1
    return max(
        candidates, key=lambda c: (0.6 * c.score + 0.4 * (c.value / biggest), -c.header_rows[0])
    )


def _value_texts(row: _Row) -> tuple[str, ...]:
    return tuple(
        text_of(row.cells[p]) for p in row.positions if kind_of(row.cells[p]) != CellKind.TEXT
    )


def _next_header(
    rows: dict[int, _Row],
    ordered: list[int],
    number: int,
    header: _Row,
    spans: dict[int, list[tuple[int, int]]],
) -> int | None:
    """The row where ANOTHER table starts below this header (a label row with data under it)."""
    later = [n for n in ordered if n > number]
    for index, candidate in enumerate(later):
        row = rows[candidate]
        if not _label_row(row) or row.n < max(3, ceil(0.5 * header.n)):
            continue
        if _lexicon_ratio(row) < 0.5:
            continue
        under = [rows[m] for m in later[index + 1 : index + 4]]
        if any(r.n >= 2 and (r.n_value or r.n_date) for r in under):
            return (
                candidate - 1
                if rows.get(candidate - 1) and _label_row(rows[candidate - 1])
                else candidate
            )
    return None


__all__ = [
    "Column",
    "Row",
    "RowKind",
    "SkippedRow",
    "TableCandidate",
    "TotalCheck",
    "analyze_sheet",
    "classify_row",
    "is_note_text",
    "is_total_label",
    "looks_like_section",
    "row_features",
]

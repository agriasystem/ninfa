"""CSV reader: UTF-8 (with or without BOM) with Windows-1252 fallback; comma, semicolon or tab."""

import csv
import io
from collections.abc import Iterator

from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions
from app.modules.bookings.parsers import MAX_COLUMNS, Cell, SourceRow, SourceTable, limit_rows

# Preference order when two delimiters give the same number of header fields.
_DELIMITERS = (";", ",", "\t")


def _decode(content: bytes, encoding: str | None) -> str:
    """UTF-8 first (a BOM is dropped), then Windows-1252, unless the profile fixes one."""
    candidates = {"utf-8": ["utf-8-sig"], "cp1252": ["cp1252"], None: ["utf-8-sig", "cp1252"]}
    for name in candidates[encoding]:
        try:
            return content.decode(name)
        except UnicodeDecodeError:
            continue
    raise BookingImportError(
        BookingErrorCode.UNREADABLE_FILE,
        "The file is not valid UTF-8 or Windows-1252 text",
        details={"encoding": encoding or "auto"},
    )


def _detect_delimiter(lines: list[str]) -> str:
    """The delimiter that splits the header line into the most fields (ties: ; , tab)."""
    header = next((line for line in lines if line.strip()), "")
    best, best_fields = ",", 1
    for delimiter in _DELIMITERS:
        try:
            fields = len(next(csv.reader([header], delimiter=delimiter), []))
        except csv.Error:
            continue
        if fields > best_fields:
            best, best_fields = delimiter, fields
    return best


def _clean(cell: str) -> Cell:
    stripped = cell.strip()
    return stripped if stripped else None


def read_csv(content: bytes, options: FormatOptions) -> SourceTable:
    text = _decode(content, options.encoding)
    if "\x00" in text:  # UTF-16/binary decoded as single-byte text: never guess, refuse
        raise BookingImportError(
            BookingErrorCode.UNREADABLE_FILE,
            "The file is not plain UTF-8 or Windows-1252 text (is it UTF-16 or binary?)",
        )
    lines = text.splitlines()

    # Excel's "sep=;" hint line: honour it, and do not treat it as data.
    forced: str | None = None
    if lines and lines[0].lower().startswith("sep=") and len(lines[0]) == 5:
        forced = lines[0][4]
        text = text[text.index(lines[0]) + len(lines[0]) :].lstrip("\r\n")
        lines = lines[1:]
    delimiter = (
        options.delimiter or (forced if forced in _DELIMITERS else None) or _detect_delimiter(lines)
    )

    def records() -> Iterator[tuple[int, list[str]]]:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        try:
            yield from enumerate(reader, start=1)
        except csv.Error as exc:
            raise BookingImportError(
                BookingErrorCode.UNREADABLE_FILE, "The file could not be parsed as CSV"
            ) from exc

    header: list[str] | None = None
    header_number = 0
    for number, record in records():
        if any(cell.strip() for cell in record):
            header, header_number = [cell.strip() for cell in record], number
            break
    if header is None:
        raise BookingImportError(BookingErrorCode.EMPTY_FILE, "The file contains no data")
    while header and not header[-1]:  # trailing delimiter: unnamed trailing columns
        header.pop()
    if len(header) > MAX_COLUMNS:
        # Reported by open_table with a proper code; keep the reader cheap.
        return SourceTable("csv", header, None, lambda: iter(()))
    width = len(header)

    def rows() -> Iterator[SourceRow]:
        for number, record in records():
            if number <= header_number:
                continue
            cells = [_clean(c) for c in record[:width]]
            if not any(cell is not None for cell in cells):
                continue  # blank line (numbering still counts it)
            cells.extend([None] * (width - len(cells)))
            yield SourceRow(number, cells)

    return SourceTable("csv", header, None, lambda: limit_rows(rows()))

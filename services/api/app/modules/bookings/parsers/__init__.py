"""Readers for booking files (.csv and .xlsx). They return raw cell values and nothing else.

A reader knows nothing about bookings: it finds the header row and yields data rows. Picking out
the mapped columns (and dropping every other one) happens in the importer, right after reading,
so unmapped cells are never staged, logged or persisted.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath
from typing import Literal

from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions, find_duplicate_headers

# Defensive limits (a booking export of a single property is far below these).
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 200

Cell = str | int | float | Decimal | bool | date | datetime | time | None
FileType = Literal["csv", "xlsx"]

_UNSUPPORTED_HINT = {
    ".xls": "legacy .xls",
    ".xlsm": "macro-enabled .xlsm",
    ".ods": "OpenDocument .ods",
}


@dataclass(frozen=True)
class SourceRow:
    number: int  # 1-based, as in a spreadsheet: the header row is 1
    cells: list[Cell]  # exactly len(headers) cells (padded/truncated)


@dataclass(frozen=True)
class SourceTable:
    file_type: FileType
    headers: list[str]
    sheet_name: str | None
    rows: Callable[[], Iterator[SourceRow]]


def detect_file_type(filename: str, content: bytes) -> FileType:
    """.csv and .xlsx only. The extension decides, the content must agree."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".xlsx":
        if not content.startswith(b"PK\x03\x04"):
            raise BookingImportError(
                BookingErrorCode.UNREADABLE_FILE, "The file is not a valid .xlsx workbook"
            )
        return "xlsx"
    if suffix == ".csv":
        if content.startswith(b"PK\x03\x04"):
            raise BookingImportError(
                BookingErrorCode.UNSUPPORTED_FILE_TYPE,
                "A workbook was given a .csv extension: export it as CSV or upload the .xlsx",
            )
        return "csv"
    raise BookingImportError(
        BookingErrorCode.UNSUPPORTED_FILE_TYPE,
        f"Unsupported file type '{suffix or 'none'}'"
        f"{' (' + _UNSUPPORTED_HINT[suffix] + ')' if suffix in _UNSUPPORTED_HINT else ''}: "
        "only .csv and .xlsx are supported",
        details={"supported": [".csv", ".xlsx"]},
    )


def open_table(content: bytes, filename: str, options: FormatOptions | None = None) -> SourceTable:
    """Locate the header row and return a table whose data rows can be iterated.

    Raises BookingImportError for unsupported/unreadable files, files over the limits,
    duplicate headers and (xlsx) sheets that need to be chosen.
    """
    from app.modules.bookings.parsers import csv_parser, xlsx_parser

    if len(content) > MAX_FILE_BYTES:
        raise BookingImportError(
            BookingErrorCode.FILE_LIMIT_EXCEEDED,
            "The file is larger than the supported maximum",
            details={"max_bytes": MAX_FILE_BYTES},
        )
    options = options or FormatOptions()
    file_type = detect_file_type(filename, content)
    table = (
        csv_parser.read_csv(content, options)
        if file_type == "csv"
        else xlsx_parser.read_xlsx(content, options)
    )
    if len(table.headers) > MAX_COLUMNS:
        raise BookingImportError(
            BookingErrorCode.FILE_LIMIT_EXCEEDED,
            "The file has more columns than the supported maximum",
            details={"max_columns": MAX_COLUMNS},
        )
    duplicates = find_duplicate_headers(table.headers)
    if duplicates:
        raise BookingImportError(
            BookingErrorCode.DUPLICATE_HEADER,
            "The file has duplicate column headers, so columns cannot be mapped unambiguously",
            details={"duplicate_headers": duplicates},
        )
    return table


def limit_rows(rows: Iterator[SourceRow]) -> Iterator[SourceRow]:
    """Stop the import (not silently truncate) when a file has too many data rows."""
    for count, row in enumerate(rows, start=1):
        if count > MAX_ROWS:
            raise BookingImportError(
                BookingErrorCode.FILE_LIMIT_EXCEEDED,
                "The file has more rows than the supported maximum",
                details={"max_rows": MAX_ROWS},
            )
        yield row

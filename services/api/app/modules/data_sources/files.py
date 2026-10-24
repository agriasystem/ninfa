"""Looking at a file BEFORE it is imported, and naming what went wrong AFTER - read-only,
deterministic.

Nothing here parses a row into the canonical model or decides whether a value is valid: that stays
in the import services (`BookingImportService`, `LaborImportService`, `InvoiceImportService`). A
preview answers only what can be known without importing: is the file readable, which of NINFA's
columns does it carry, how many rows (or invoices) does it hold, was this exact file already
imported. Whether every row is valid is decided when the file is imported - and a file with even one
invalid row imports nothing.
"""

import csv
import io
from dataclasses import dataclass
from enum import StrEnum

from app.modules.bookings.mapping import REQUIRED_FIELDS as BOOKING_REQUIRED_FIELDS
from app.modules.bookings.mapping import CanonicalField, find_duplicate_headers, normalize_header
from app.modules.data_sources.types import SourceMethod
from app.modules.ingestion.canonical_csv import (
    identity_column_mapping,
    read_headers,
    unrecognized_columns,
)
from app.modules.ingestion.models import DataSourceDomain
from app.modules.invoices.errors import InvoiceImportError
from app.modules.invoices.fatturapa import parse_fatturapa
from app.modules.labor.mapping import (
    HOURS_FIELDS,
    ROLE_OR_CATEGORY_FIELDS,
    LaborField,
)

MAX_FILE_BYTES = 10 * 1024 * 1024
SAMPLE_ROWS = 3
SAMPLE_COLUMNS = 6


class ImportProblem(StrEnum):
    """WHY a file cannot be (or was not) imported, in one stable word the page turns into a
    sentence."""

    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    UNREADABLE_FILE = "UNREADABLE_FILE"
    EMPTY_FILE = "EMPTY_FILE"
    NO_ROWS = "NO_ROWS"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    MISSING_COLUMNS = "MISSING_COLUMNS"
    DUPLICATE_COLUMNS = "DUPLICATE_COLUMNS"
    INVALID_ROWS = "INVALID_ROWS"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    SAME_DAY_CONFLICT = "SAME_DAY_CONFLICT"
    # Smart Import: matching the columns of a file the person already has.
    MAPPING_INCOMPLETE = "MAPPING_INCOMPLETE"  # the matching misses something or contradicts itself
    FORMAT_UNCLEAR = "FORMAT_UNCLEAR"  # dates or numbers are written in a way NINFA cannot tell
    PROFILE_NOT_USABLE = "PROFILE_NOT_USABLE"  # the saved configuration cannot read this file
    SHEET_REQUIRED = "SHEET_REQUIRED"  # an Excel file with several sheets: one must be chosen
    GENERIC = "GENERIC"


# The suffix of an import service's own error code (BOOKING_/LABOR_/INVOICE_ prefix removed).
_PROBLEM_BY_CODE: dict[str, ImportProblem] = {
    "UNSUPPORTED_FILE_TYPE": ImportProblem.UNSUPPORTED_FILE,
    "UNREADABLE_FILE": ImportProblem.UNREADABLE_FILE,
    "EMPTY_FILE": ImportProblem.EMPTY_FILE,
    "FILE_LIMIT_EXCEEDED": ImportProblem.FILE_TOO_LARGE,
    "DUPLICATE_HEADER": ImportProblem.DUPLICATE_COLUMNS,
    "MAPPING_REQUIRED": ImportProblem.MISSING_COLUMNS,
    "INVALID_MAPPING": ImportProblem.MISSING_COLUMNS,
    "SOURCE_SCHEMA_CHANGED": ImportProblem.MISSING_COLUMNS,
    "AMBIGUOUS_DATE_FORMAT": ImportProblem.INVALID_ROWS,
    "AMBIGUOUS_NUMBER_FORMAT": ImportProblem.INVALID_ROWS,
    "VALIDATION_FAILED": ImportProblem.INVALID_ROWS,
    "CANONICALIZATION_FAILED": ImportProblem.INVALID_ROWS,
    "DOCUMENT_CONFLICT": ImportProblem.INVALID_ROWS,
    "UNSUPPORTED_FATTURAPA": ImportProblem.UNSUPPORTED_FORMAT,
    "XML_SECURITY_REJECTED": ImportProblem.UNSUPPORTED_FORMAT,
    "SNAPSHOT_CONFLICT": ImportProblem.SAME_DAY_CONFLICT,
}


def problem_of_code(code: object) -> ImportProblem:
    """The user-facing reason of an import service's error code. Unknown or internal codes are
    `GENERIC`: the technical detail stays in the server log, never in the page."""
    text = str(getattr(code, "value", code) or "")
    _, _, suffix = text.partition("_")
    return _PROBLEM_BY_CODE.get(suffix, ImportProblem.GENERIC)


@dataclass(frozen=True, slots=True)
class ImportPreview:
    method: SourceMethod
    # `False` while `problem` is set: the file cannot be imported as it is.
    can_import: bool
    problem: ImportProblem | None
    # Data rows of a CSV, invoices of an XML.
    rows_total: int = 0
    recognized_columns: tuple[str, ...] = ()
    # Each entry is a group of alternatives, one of which the file must carry.
    missing_columns: tuple[tuple[str, ...], ...] = ()
    unrecognized_columns: tuple[str, ...] = ()
    sample_columns: tuple[str, ...] = ()
    sample_rows: tuple[tuple[str, ...], ...] = ()
    # XML only: invoices of the file that NINFA could not read completely.
    documents_with_issues: int = 0
    already_imported: bool = False


def _fields_of(domain: DataSourceDomain) -> type[StrEnum]:
    return CanonicalField if domain == DataSourceDomain.BOOKINGS else LaborField


def missing_columns_of(domain: DataSourceDomain, headers: list[str]) -> tuple[tuple[str, ...], ...]:
    """The columns NINFA requires that the headers do not carry (the import services' own rules)."""
    present = {normalize_header(header) for header in headers}

    def has(field: StrEnum) -> bool:
        return normalize_header(field.value) in present

    if domain == DataSourceDomain.BOOKINGS:
        return tuple(
            (field.value,)
            for field in CanonicalField
            if field in BOOKING_REQUIRED_FIELDS and not has(field)
        )
    missing: list[tuple[str, ...]] = []
    if not has(LaborField.WORK_DATE):
        missing.append((LaborField.WORK_DATE.value,))
    for group in (HOURS_FIELDS, ROLE_OR_CATEGORY_FIELDS):
        if not any(has(field) for field in group):
            missing.append(tuple(sorted(field.value for field in group)))
    return tuple(missing)


def template_csv(domain: DataSourceDomain) -> bytes:
    """A header row with every canonical column, nothing else: an example row would be fictitious
    data one click away from being imported. The formats (dates `YYYY-MM-DD`, decimals with `.`) are
    in
    the page's own words."""
    fields = _fields_of(domain)
    return ("﻿" + ",".join(field.value for field in fields) + "\r\n").encode("utf-8")


def preview_csv(
    domain: DataSourceDomain, content: bytes, *, already_imported: bool
) -> ImportPreview:
    method = SourceMethod.CSV
    if not content.strip():
        return ImportPreview(method, False, ImportProblem.EMPTY_FILE)
    try:
        text = content.decode("utf-8-sig")
        headers = read_headers(content)
        table = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    except (UnicodeDecodeError, csv.Error):
        return ImportPreview(method, False, ImportProblem.UNREADABLE_FILE)
    if not headers or not any(header.strip() for header in headers):
        return ImportPreview(method, False, ImportProblem.EMPTY_FILE)

    fields = _fields_of(domain)
    mapping = identity_column_mapping(headers, fields)
    recognized = tuple(mapping)
    extra = tuple(unrecognized_columns(headers, fields))
    missing = missing_columns_of(domain, headers)
    rows = table[1:]

    sample_columns = recognized[:SAMPLE_COLUMNS]
    index_of = {normalize_header(header): position for position, header in enumerate(headers)}
    positions = [index_of[normalize_header(name)] for name in sample_columns]
    sample_rows = tuple(
        tuple(row[position] if position < len(row) else "" for position in positions)
        for row in rows[:SAMPLE_ROWS]
    )

    problem: ImportProblem | None = None
    if find_duplicate_headers(headers):
        problem = ImportProblem.DUPLICATE_COLUMNS
    elif missing:
        problem = ImportProblem.MISSING_COLUMNS
    elif not rows:
        problem = ImportProblem.NO_ROWS
    return ImportPreview(
        method=method,
        can_import=problem is None,
        problem=problem,
        rows_total=len(rows),
        recognized_columns=recognized,
        missing_columns=missing,
        unrecognized_columns=extra,
        sample_columns=sample_columns,
        sample_rows=sample_rows,
        already_imported=already_imported,
    )


def preview_invoices(content: bytes, *, already_imported: bool) -> ImportPreview:
    method = SourceMethod.XML
    if not content.strip():
        return ImportPreview(method, False, ImportProblem.EMPTY_FILE)
    try:
        documents = parse_fatturapa(content)
    except InvoiceImportError as error:
        return ImportPreview(method, False, problem_of_code(error.error_code))
    # A document NINFA cannot read completely makes the whole file import nothing (all-or-nothing).
    with_issues = sum(1 for document in documents if not document.no_issues())
    return ImportPreview(
        method=method,
        can_import=with_issues == 0,
        problem=ImportProblem.INVALID_ROWS if with_issues else None,
        rows_total=len(documents),
        documents_with_issues=with_issues,
        already_imported=already_imported,
    )


__all__ = [
    "MAX_FILE_BYTES",
    "ImportPreview",
    "ImportProblem",
    "missing_columns_of",
    "preview_csv",
    "preview_invoices",
    "problem_of_code",
    "template_csv",
]

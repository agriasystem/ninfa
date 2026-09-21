"""Parsed documents: what a parser hands to the import pipeline, and the checks they all share.

A parser (FatturaPA XML, structured CSV/XLSX) reads a source into `ParsedDocument`s: for each
document the MAPPED values (text, for staging), the canonical document when everything is valid,
and every issue found, located on a line or on the document. `assemble` applies the rules that do
not depend on the format: at least one line, no duplicate line numbers, an ISO 4217 currency, and
amounts that fit the columns. It is the only place a `CanonicalDocument` is built from parsed
values, so both formats obey the same rules.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.iso4217 import ISO_4217_CODES
from app.modules.invoices.canonical import (
    CanonicalDocument,
    LocatedIssue,
    RawDocument,
    RawLine,
    canonicalize,
)
from app.modules.invoices.errors import InvoiceErrorCode, RowIssue, RowWarning
from app.modules.invoices.models import DocumentKind, SourceFormat
from app.modules.suppliers.resolution import SupplierEvidence

MAX_NUMBER_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 1000
MAX_UNIT_LENGTH = 30
MAX_DOCUMENT_TYPE_LENGTH = 20


@dataclass(slots=True)
class ParsedLine:
    """One source line: its mapped text values, the parsed line and its own issues."""

    mapped: dict[str, Any]
    source_line_number: int | None
    raw: RawLine | None = None
    issues: list[RowIssue] = field(default_factory=list)


@dataclass(slots=True)
class Header:
    """The document-level values a parser managed to read (None where absent or invalid)."""

    supplier: SupplierEvidence | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    document_type_code: str | None = None
    document_kind: DocumentKind | None = None
    currency: str | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    warnings: list[RowWarning] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    index: int
    mapped_header: dict[str, Any]
    lines: list[ParsedLine]
    issues: list[RowIssue]  # document level
    warnings: list[RowWarning]
    canonical: CanonicalDocument | None = None

    def no_issues(self) -> bool:
        return not self.issues and all(not line.issues for line in self.lines)

    @property
    def valid(self) -> bool:
        return self.canonical is not None and self.no_issues()

    def located_issues(self) -> list[LocatedIssue]:
        found = [LocatedIssue(None, issue) for issue in self.issues]
        for position, line in enumerate(self.lines):
            found.extend(LocatedIssue(position, issue) for issue in line.issues)
        return found


def assemble(
    *,
    index: int,
    header: Header,
    mapped_header: dict[str, Any],
    lines: list[ParsedLine],
    header_issues: list[RowIssue],
    source_format: SourceFormat,
) -> ParsedDocument:
    """Apply the format-independent rules; with nothing wrong, build the canonical document."""
    issues = list(header_issues)

    if not lines:
        issues.append(RowIssue("lines", InvoiceErrorCode.NO_LINES))

    seen: dict[int, ParsedLine] = {}
    duplicated: set[int] = set()
    for line in lines:
        number = line.source_line_number
        if number is None:
            continue
        if number in seen:
            duplicated.add(number)
        seen.setdefault(number, line)
    for line in lines:
        if line.source_line_number in duplicated:
            line.issues.append(
                RowIssue("line_number", InvoiceErrorCode.DUPLICATE_LINE, "same line number twice")
            )

    if header.currency is not None and header.currency not in ISO_4217_CODES:
        issues.append(RowIssue("currency", InvoiceErrorCode.INVALID_CURRENCY))
    if header.invoice_number is not None and len(header.invoice_number) > MAX_NUMBER_LENGTH:
        issues.append(RowIssue("invoice_number", InvoiceErrorCode.VALUE_TOO_LONG))
    if (
        header.document_type_code is not None
        and len(header.document_type_code) > MAX_DOCUMENT_TYPE_LENGTH
    ):
        issues.append(RowIssue("document_type", InvoiceErrorCode.VALUE_TOO_LONG))

    parsed = ParsedDocument(
        index=index,
        mapped_header=mapped_header,
        lines=lines,
        issues=issues,
        warnings=list(header.warnings),
    )
    complete = (
        header.supplier is not None
        and header.invoice_number is not None
        and header.invoice_date is not None
        and header.document_kind is not None
        and header.currency is not None
        and all(line.raw is not None for line in lines)
    )
    if not complete or not parsed.no_issues():
        return parsed

    assert header.supplier is not None  # narrowed by `complete`
    assert header.invoice_number is not None and header.invoice_date is not None
    assert header.document_kind is not None and header.currency is not None
    raw = RawDocument(
        source_document_index=index,
        supplier=header.supplier,
        invoice_number=header.invoice_number,
        invoice_date=header.invoice_date,
        document_kind=header.document_kind,
        currency=header.currency,
        lines=tuple(line.raw for line in lines if line.raw is not None),
        source_format=source_format,
        due_date=header.due_date,
        document_type_code=header.document_type_code,
        net_amount=header.net_amount,
        tax_amount=header.tax_amount,
        gross_amount=header.gross_amount,
        warnings=tuple(header.warnings),
    )
    try:
        parsed.canonical = canonicalize(raw)
    except ValueError:
        parsed.issues.append(RowIssue("amount", InvoiceErrorCode.OUT_OF_RANGE))
    return parsed

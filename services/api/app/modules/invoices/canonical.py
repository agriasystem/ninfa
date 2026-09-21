"""The canonical invoice: values, signs, fingerprint and their staged (JSON) form.

Everything here is deterministic and free of I/O and float. Money is `Decimal` from the first
character to the database column: a source may carry up to eight decimals (FatturaPA does), the
canonical amount is quantised ONCE, HALF_UP to two decimals, after the document rules (the sign)
have been applied to the exact values.

Signed monetary semantics: an INVOICE keeps the amounts of the source; a CREDIT_NOTE is stored as a
negative cost, so a plain SUM(line_total) is right everywhere. `document_multiplier` decides, per
document and from its own headline amount, whether the source wrote the credit note with positive
amounts (they are negated) or already with negative ones (they are left alone): no double negation.
"""

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.bookings.text import normalize_key
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.errors import RowIssue, RowWarning, WarningCode
from app.modules.invoices.models import MAX_MONEY, DocumentKind, SourceFormat
from app.modules.suppliers.resolution import SupplierEvidence

_CENT = Decimal("0.01")
_FINGERPRINT_FORMAT = 1
MAX_DECIMALS = 8  # decimals accepted in a source amount, quantity or unit price


# --- values -----------------------------------------------------------------------------------


def normalize_invoice_number(raw: str) -> str:
    """Conservative: Unicode compatibility form, trimmed, whitespace collapsed, upper case.

    Slashes, dashes and letters are part of an accounting identifier and are KEPT: "123/A" is not
    "123A", and "12-3" is not "123".
    """
    return " ".join(unicodedata.normalize("NFKC", raw).split()).upper()


def normalize_description(raw: str) -> str:
    """Deterministic comparison form of a line description (case, accents, punctuation, spacing)."""
    return normalize_key(raw)


def to_money(value: Decimal) -> Decimal:
    """The canonical two-decimal amount (HALF_UP). Raises ValueError beyond the column's range."""
    quantized = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if abs(quantized) > MAX_MONEY:
        raise ValueError("amount out of range")
    return quantized


def plain(value: Decimal | None) -> str | None:
    """Canonical text of a Decimal: equal numbers give equal text (`1.50` and `1.5` alike)."""
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def money_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, ".2f")


def decimals_of(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -int(exponent)) if isinstance(exponent, int) else 0


# --- sign normalisation -------------------------------------------------------------------------


def document_multiplier(
    kind: DocumentKind,
    gross: Decimal | None,
    net: Decimal | None,
    line_totals: Sequence[Decimal],
) -> int:
    """+1 or -1: the factor that turns the source amounts into signed canonical amounts.

    An INVOICE is +1. A CREDIT_NOTE looks at its own headline amount (gross, else net, else the sum
    of its lines): positive means the source wrote it positive (negate everything), negative means
    it is already signed (keep everything). An all-zero document needs no sign.
    """
    if kind == DocumentKind.INVOICE:
        return 1
    for reference in (gross, net, sum(line_totals, Decimal(0))):
        if reference is not None and reference != 0:
            return -1 if reference > 0 else 1
    return 1


# --- raw and canonical documents ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawLine:
    """A line as the source states it (exact values, nothing rounded or signed yet)."""

    source_line_number: int
    description: str
    line_total: Decimal
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    vat_rate: Decimal | None = None
    explicit_category: CostCategory | None = None


@dataclass(frozen=True, slots=True)
class RawDocument:
    source_document_index: int
    supplier: SupplierEvidence
    invoice_number: str
    invoice_date: date
    document_kind: DocumentKind
    currency: str
    lines: tuple[RawLine, ...]
    source_format: SourceFormat
    due_date: date | None = None
    document_type_code: str | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    warnings: tuple[RowWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalLine:
    source_line_number: int
    description_raw: str
    description_normalized: str
    line_total: Decimal  # signed canonical, two decimals
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    vat_rate: Decimal | None = None
    explicit_category: CostCategory | None = None


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Diagnostics only: NINFA does not require the lines to add up to a document total (VAT,
    stamp duty, discounts, withholdings and rounding all legitimately make them differ)."""

    line_net_sum: Decimal
    document_net_amount: Decimal | None
    reconciliation_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    source_document_index: int
    supplier: SupplierEvidence
    invoice_number: str
    normalized_invoice_number: str
    invoice_date: date
    document_kind: DocumentKind
    currency: str
    lines: tuple[CanonicalLine, ...]
    source_format: SourceFormat
    due_date: date | None = None
    document_type_code: str | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    warnings: tuple[RowWarning, ...] = field(default=())

    def reconciliation(self) -> Reconciliation:
        total = sum((line.line_total for line in self.lines), Decimal(0))
        delta = None if self.net_amount is None else self.net_amount - total
        return Reconciliation(total, self.net_amount, delta)

    def fingerprint(self, supplier_id: str) -> str:
        """SHA-256 of the CANONICAL business content, and of nothing technical.

        It covers the resolved supplier, the document identity, the currency, the signed amounts and
        the ordered canonical lines. It excludes the file name, the import job, timestamps, the due
        date, the raw document type code and the cost categories (a category is analysis, not
        accounting: a supplier's default may change without the invoice having changed). Two source
        formats that state the same canonical invoice give the same fingerprint.
        """
        document = {
            "v": _FINGERPRINT_FORMAT,
            "supplier_id": supplier_id,
            "number": self.normalized_invoice_number,
            "date": self.invoice_date.isoformat(),
            "kind": self.document_kind.value,
            "currency": self.currency,
            "net": money_text(self.net_amount),
            "tax": money_text(self.tax_amount),
            "gross": money_text(self.gross_amount),
            "lines": [
                [
                    line.source_line_number,
                    line.description_normalized,
                    plain(line.quantity),
                    None if line.unit is None else line.unit.casefold(),
                    plain(line.unit_price),
                    money_text(line.line_total),
                    plain(line.vat_rate),
                ]
                for line in sorted(self.lines, key=lambda item: item.source_line_number)
            ],
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonicalize(raw: RawDocument) -> CanonicalDocument:
    """Apply the document sign, then quantise every money amount once (HALF_UP, two decimals).

    Raises ValueError when an amount is out of the storable range.
    """
    multiplier = document_multiplier(
        raw.document_kind,
        raw.gross_amount,
        raw.net_amount,
        [line.line_total for line in raw.lines],
    )

    def money(value: Decimal | None) -> Decimal | None:
        return None if value is None else to_money(value * multiplier)

    lines = tuple(
        CanonicalLine(
            source_line_number=line.source_line_number,
            description_raw=line.description,
            description_normalized=normalize_description(line.description),
            line_total=to_money(line.line_total * multiplier),
            quantity=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
            vat_rate=line.vat_rate,
            explicit_category=line.explicit_category,
        )
        for line in raw.lines
    )
    return CanonicalDocument(
        source_document_index=raw.source_document_index,
        supplier=raw.supplier,
        invoice_number=raw.invoice_number,
        normalized_invoice_number=normalize_invoice_number(raw.invoice_number),
        invoice_date=raw.invoice_date,
        document_kind=raw.document_kind,
        currency=raw.currency,
        lines=lines,
        source_format=raw.source_format,
        due_date=raw.due_date,
        document_type_code=raw.document_type_code,
        net_amount=money(raw.net_amount),
        tax_amount=money(raw.tax_amount),
        gross_amount=money(raw.gross_amount),
        warnings=raw.warnings,
    )


# --- the staged (JSON) form ---------------------------------------------------------------------


def supplier_payload(supplier: SupplierEvidence) -> dict[str, Any]:
    return {
        "legal_name": supplier.legal_name,
        "country": supplier.country,
        "vat_number": supplier.vat_number,
        "tax_code": supplier.tax_code,
        "iban_sha256": list(supplier.iban_sha256),
    }


def supplier_from_payload(payload: Mapping[str, Any], data_source_id: Any) -> SupplierEvidence:
    return SupplierEvidence.build(
        legal_name=payload["legal_name"],
        country=payload["country"],
        vat_number=payload["vat_number"],
        tax_code=payload["tax_code"],
        iban_sha256=payload["iban_sha256"],
        data_source_id=data_source_id,
    )


def line_payload(line: CanonicalLine) -> dict[str, Any]:
    return {
        "source_line_number": line.source_line_number,
        "description_raw": line.description_raw,
        "quantity": plain(line.quantity),
        "unit": line.unit,
        "unit_price": plain(line.unit_price),
        "line_total": money_text(line.line_total),
        "vat_rate": plain(line.vat_rate),
        "explicit_category": None
        if line.explicit_category is None
        else line.explicit_category.value,
    }


def line_from_payload(payload: Mapping[str, Any]) -> CanonicalLine:
    def opt(key: str) -> Decimal | None:
        return None if payload[key] is None else Decimal(payload[key])

    category = payload["explicit_category"]
    return CanonicalLine(
        source_line_number=payload["source_line_number"],
        description_raw=payload["description_raw"],
        description_normalized=normalize_description(payload["description_raw"]),
        line_total=Decimal(payload["line_total"]),
        quantity=opt("quantity"),
        unit=payload["unit"],
        unit_price=opt("unit_price"),
        vat_rate=opt("vat_rate"),
        explicit_category=None if category is None else CostCategory(category),
    )


def header_payload(document: CanonicalDocument) -> dict[str, Any]:
    reconciliation = document.reconciliation()
    return {
        "source_document_index": document.source_document_index,
        "supplier": supplier_payload(document.supplier),
        "invoice_number": document.invoice_number,
        "invoice_date": document.invoice_date.isoformat(),
        "due_date": None if document.due_date is None else document.due_date.isoformat(),
        "document_type_code": document.document_type_code,
        "document_kind": document.document_kind.value,
        "currency": document.currency,
        "net_amount": money_text(document.net_amount),
        "tax_amount": money_text(document.tax_amount),
        "gross_amount": money_text(document.gross_amount),
        "source_format": document.source_format.value,
        "warnings": [warning.to_json() for warning in document.warnings],
        # Diagnostics only (no anomaly detection): kept with the staged document.
        "diagnostics": {
            "line_net_sum": money_text(reconciliation.line_net_sum),
            "document_net_amount": money_text(reconciliation.document_net_amount),
            "reconciliation_delta": money_text(reconciliation.reconciliation_delta),
        },
    }


def document_from_payloads(
    header: Mapping[str, Any], lines: Sequence[Mapping[str, Any]], data_source_id: Any
) -> CanonicalDocument:
    def opt_decimal(key: str) -> Decimal | None:
        return None if header[key] is None else Decimal(header[key])

    return CanonicalDocument(
        source_document_index=header["source_document_index"],
        supplier=supplier_from_payload(header["supplier"], data_source_id),
        invoice_number=header["invoice_number"],
        normalized_invoice_number=normalize_invoice_number(header["invoice_number"]),
        invoice_date=date.fromisoformat(header["invoice_date"]),
        document_kind=DocumentKind(header["document_kind"]),
        currency=header["currency"],
        lines=tuple(line_from_payload(line) for line in lines),
        source_format=SourceFormat(header["source_format"]),
        due_date=None if header["due_date"] is None else date.fromisoformat(header["due_date"]),
        document_type_code=header["document_type_code"],
        net_amount=opt_decimal("net_amount"),
        tax_amount=opt_decimal("tax_amount"),
        gross_amount=opt_decimal("gross_amount"),
        warnings=tuple(
            RowWarning(item["field"], WarningCode(item["code"])) for item in header["warnings"]
        ),
    )


# --- issues located in a document ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocatedIssue:
    """A problem at document level (`line_index` is None) or on one line (its index)."""

    line_index: int | None
    issue: RowIssue

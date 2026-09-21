"""FatturaPA XML 1.2.x (FPR12 private, FPA12 public administration): a deterministic reader.

It reads only what NINFA needs and drops everything else at once:

  supplier   CedentePrestatore: name (Denominazione, or Nome + Cognome), IdFiscaleIVA,
             CodiceFiscale, the country, and the payment IBANs (hashed here, never kept)
  document   TipoDocumento, Divisa, Data, Numero, ImportoTotaleDocumento, the VAT summary totals,
             the payment due dates
  lines      NumeroLinea, Descrizione, Quantita, UnitaMisura, PrezzoUnitario, PrezzoTotale,
             AliquotaIVA

NEVER read: the recipient (CessionarioCommittente), addresses, phones, e-mails, PEC, attachments.
Element names are matched by LOCAL name, so any namespace prefix works. One file may hold several
FatturaElettronicaBody: each is a separate document that shares the supplier of the header.

Security: the standard-library parser is used (no custom parser), with a builder that REFUSES any
DOCTYPE. Entities can only be declared inside a DOCTYPE, so no entity, external or internal, is
ever expanded and no external resource is ever fetched. Size and document counts are bounded.
Signed files (.p7m) are not supported: only the plain XML.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.invoices.canonical import MAX_DECIMALS, RawLine, decimals_of
from app.modules.invoices.documents import (
    MAX_DESCRIPTION_LENGTH,
    MAX_UNIT_LENGTH,
    Header,
    ParsedDocument,
    ParsedLine,
    assemble,
)
from app.modules.invoices.errors import (
    InvoiceErrorCode,
    InvoiceImportError,
    RowIssue,
    RowWarning,
    WarningCode,
)
from app.modules.invoices.models import DocumentKind, SourceFormat
from app.modules.suppliers.normalization import (
    display_name,
    hash_iban,
    normalize_country,
    normalize_supplier_name,
    normalize_tax_code,
    normalize_vat_number,
)
from app.modules.suppliers.resolution import SupplierEvidence

MAX_XML_BYTES = 25 * 1024 * 1024
MAX_DOCUMENTS = 5_000
MAX_LINES = 10_000
SUPPORTED_VERSIONS = frozenset({"FPR12", "FPA12"})

# TipoDocumento values NINFA reads as a cost document. TD04 and TD08 (credit notes, ordinary and
# simplified) become CREDIT_NOTE; the debit notes and the ordinary/simplified invoices are INVOICE.
# Reverse-charge / self-invoice types (TD16-TD28) swap the roles of supplier and buyer and are not
# supported in V1.
INVOICE_TYPES = frozenset({"TD01", "TD02", "TD03", "TD05", "TD06", "TD07", "TD09", "TD24", "TD25"})
CREDIT_NOTE_TYPES = frozenset({"TD04", "TD08"})

_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
_INTEGER = re.compile(r"^\d{1,9}$")


class _RefusedError(Exception):
    """Internal: the document declares a DOCTYPE."""


class _SecureBuilder(ET.TreeBuilder):
    def doctype(self, name: str | None, pubid: str | None, system: str | None) -> None:
        raise _RefusedError


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(element: ET.Element, name: str) -> Iterator[ET.Element]:
    return (child for child in element if _local(child.tag) == name)


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next(_children(element, name), None)


def _text(element: ET.Element | None, name: str) -> str | None:
    child = _child(element, name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def read_xml(content: bytes) -> ET.Element:
    """The root element, or a stable error. Never expands an entity, never fetches anything."""
    if len(content) > MAX_XML_BYTES:
        raise InvoiceImportError(
            InvoiceErrorCode.FILE_LIMIT_EXCEEDED,
            "The file is larger than the supported maximum",
            details={"max_bytes": MAX_XML_BYTES},
        )
    parser = ET.XMLParser(target=_SecureBuilder())
    try:
        parser.feed(content)
        root = parser.close()
    except _RefusedError:
        raise InvoiceImportError(
            InvoiceErrorCode.XML_SECURITY_REJECTED,
            "The XML declares a DOCTYPE (entities and external resources are refused)",
        ) from None
    except ET.ParseError:
        raise InvoiceImportError(
            InvoiceErrorCode.UNREADABLE_FILE, "The file is not well-formed XML"
        ) from None
    if not isinstance(root, ET.Element):  # pragma: no cover - an empty document raised above
        raise InvoiceImportError(InvoiceErrorCode.UNREADABLE_FILE, "The file is empty XML")
    return root


def _decimal(text: str | None, field: str, issues: list[RowIssue]) -> Decimal | None:
    if text is None:
        return None
    if not _DECIMAL.match(text):
        issues.append(RowIssue(field, InvoiceErrorCode.INVALID_NUMBER))
        return None
    value = Decimal(text)
    if decimals_of(value) > MAX_DECIMALS:
        issues.append(RowIssue(field, InvoiceErrorCode.AMOUNT_PRECISION))
        return None
    return value


def _date(text: str | None, field: str, issues: list[RowIssue]) -> date | None:
    if text is None:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        issues.append(RowIssue(field, InvoiceErrorCode.INVALID_DATE))
        return None


def parse_fatturapa(content: bytes, *, data_source_id: UUID | None = None) -> list[ParsedDocument]:
    """Every FatturaElettronicaBody of the file as a parsed document (in file order)."""
    root = read_xml(content)
    if _local(root.tag) != "FatturaElettronica":
        raise InvoiceImportError(
            InvoiceErrorCode.UNSUPPORTED_FATTURAPA,
            "The XML is not a FatturaPA document",
            details={"reason": "not_fatturapa"},
        )
    version = root.get("versione")
    if version not in SUPPORTED_VERSIONS:
        raise InvoiceImportError(
            InvoiceErrorCode.UNSUPPORTED_FATTURAPA,
            "Only FatturaPA 1.2.x (FPR12 and FPA12) is supported",
            details={"reason": "unsupported_version", "supported": sorted(SUPPORTED_VERSIONS)},
        )
    header = _child(root, "FatturaElettronicaHeader")
    supplier_element = _child(header, "CedentePrestatore")
    bodies = list(_children(root, "FatturaElettronicaBody"))
    if supplier_element is None or not bodies:
        raise InvoiceImportError(
            InvoiceErrorCode.UNSUPPORTED_FATTURAPA,
            "The FatturaPA has no supplier or no document body",
            details={"reason": "missing_structure"},
        )
    if len(bodies) > MAX_DOCUMENTS:
        raise InvoiceImportError(
            InvoiceErrorCode.FILE_LIMIT_EXCEEDED,
            "The file has more documents than the supported maximum",
            details={"max_documents": MAX_DOCUMENTS},
        )
    supplier = _read_supplier(supplier_element)
    return [
        _read_body(body, index, supplier, data_source_id)
        for index, body in enumerate(bodies, start=1)
    ]


# --- supplier ----------------------------------------------------------------------------------


class _SupplierParts:
    """The supplier as the header states it (identifiers not yet checked)."""

    def __init__(self, element: ET.Element) -> None:
        anagrafica = _child(_child(element, "DatiAnagrafici"), "Anagrafica")
        vat = _child(_child(element, "DatiAnagrafici"), "IdFiscaleIVA")
        person = " ".join(
            part
            for part in (_text(anagrafica, "Nome"), _text(anagrafica, "Cognome"))
            if part is not None
        )
        self.name: str | None = _text(anagrafica, "Denominazione") or person or None
        self.vat_country: str | None = _text(vat, "IdPaese")
        self.vat_code: str | None = _text(vat, "IdCodice")
        self.tax_code: str | None = _text(_child(element, "DatiAnagrafici"), "CodiceFiscale")
        # Only the COUNTRY of the registered office, never its address.
        self.office_country: str | None = _text(_child(element, "Sede"), "Nazione")


def _read_supplier(element: ET.Element) -> _SupplierParts:
    return _SupplierParts(element)


def _evidence(
    parts: _SupplierParts,
    body: ET.Element,
    data_source_id: UUID | None,
    issues: list[RowIssue],
    warnings: list[RowWarning],
) -> SupplierEvidence | None:
    if parts.name is None:
        issues.append(RowIssue("supplier_name", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
        return None
    name = display_name(parts.name)
    normalized = normalize_supplier_name(name)
    if not normalized:
        issues.append(RowIssue("supplier_name", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
        return None

    country = normalize_country(parts.vat_country) or normalize_country(parts.office_country)
    if parts.vat_country is not None and normalize_country(parts.vat_country) is None:
        issues.append(RowIssue("supplier_country", InvoiceErrorCode.INVALID_COUNTRY))
    vat: str | None = None
    if parts.vat_code is not None:
        try:
            vat = normalize_vat_number(f"{parts.vat_country or ''}{parts.vat_code}", country)
        except ValueError:
            issues.append(RowIssue("supplier_vat_number", InvoiceErrorCode.INVALID_VAT_NUMBER))
    tax_code: str | None = None
    if parts.tax_code is not None:
        try:
            tax_code = normalize_tax_code(parts.tax_code)
        except ValueError:
            issues.append(RowIssue("supplier_tax_code", InvoiceErrorCode.INVALID_TAX_CODE))
    hashes = _payment_ibans(body, normalized, warnings)
    return SupplierEvidence(
        legal_name=name,
        normalized_name=normalized,
        country=country,
        vat_number=vat,
        tax_code=tax_code,
        iban_sha256=tuple(sorted(hashes)),
        data_source_id=data_source_id,
    )


def _payment_ibans(body: ET.Element, supplier_name: str, warnings: list[RowWarning]) -> set[str]:
    """SHA-256 of the IBANs of the payment details. An IBAN whose Beneficiario is not the supplier
    is a third party's account (a factor, a group company): it is ignored, not used to identify."""
    hashes: set[str] = set()
    for payment in _children(body, "DatiPagamento"):
        for detail in _children(payment, "DettaglioPagamento"):
            raw = _text(detail, "IBAN")
            if raw is None:
                continue
            beneficiary = _text(detail, "Beneficiario")
            if beneficiary is not None and normalize_supplier_name(beneficiary) != supplier_name:
                warnings.append(RowWarning("supplier_iban", WarningCode.BENEFICIARY_IBAN_IGNORED))
                continue
            digest = hash_iban(raw)
            if digest is None:
                warnings.append(RowWarning("supplier_iban", WarningCode.INVALID_IBAN_IGNORED))
                continue
            hashes.add(digest)
    return hashes


# --- one document ------------------------------------------------------------------------------


def _read_body(
    body: ET.Element, index: int, parts: _SupplierParts, data_source_id: UUID | None
) -> ParsedDocument:
    issues: list[RowIssue] = []
    warnings: list[RowWarning] = []
    general = _child(_child(body, "DatiGenerali"), "DatiGeneraliDocumento")
    goods = _child(body, "DatiBeniServizi")

    header = Header()
    header.supplier = _evidence(parts, body, data_source_id, issues, warnings)
    header.warnings = warnings

    type_code = _text(general, "TipoDocumento")
    header.document_type_code = type_code
    if type_code is None:
        issues.append(RowIssue("document_type", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    elif type_code in CREDIT_NOTE_TYPES:
        header.document_kind = DocumentKind.CREDIT_NOTE
    elif type_code in INVOICE_TYPES:
        header.document_kind = DocumentKind.INVOICE
    else:
        issues.append(RowIssue("document_type", InvoiceErrorCode.UNSUPPORTED_DOCUMENT_TYPE))

    header.currency = _text(general, "Divisa")
    if header.currency is None:
        issues.append(RowIssue("currency", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    header.invoice_number = _text(general, "Numero")
    if header.invoice_number is None:
        issues.append(RowIssue("invoice_number", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    date_text = _text(general, "Data")
    header.invoice_date = _date(date_text, "invoice_date", issues)
    if date_text is None:
        issues.append(RowIssue("invoice_date", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    header.gross_amount = _decimal(
        _text(general, "ImportoTotaleDocumento"), "invoice_gross_amount", issues
    )

    summaries = list(_children(goods, "DatiRiepilogo")) if goods is not None else []
    if summaries:
        nets = [
            _decimal(_text(s, "ImponibileImporto"), "invoice_net_amount", issues) for s in summaries
        ]
        taxes = [_decimal(_text(s, "Imposta"), "invoice_tax_amount", issues) for s in summaries]
        if all(value is not None for value in nets):
            header.net_amount = sum((v for v in nets if v is not None), Decimal(0))
        if all(value is not None for value in taxes):
            header.tax_amount = sum((v for v in taxes if v is not None), Decimal(0))

    due_dates: set[date] = set()
    for payment in _children(body, "DatiPagamento"):
        for detail in _children(payment, "DettaglioPagamento"):
            due = _date(_text(detail, "DataScadenzaPagamento"), "due_date", issues)
            if due is not None:
                due_dates.add(due)
    if len(due_dates) == 1:
        header.due_date = next(iter(due_dates))
    elif len(due_dates) > 1:  # never invent one representative date
        warnings.append(RowWarning("due_date", WarningCode.MULTIPLE_PAYMENT_DUE_DATES))

    detail_lines = list(_children(goods, "DettaglioLinee")) if goods is not None else []
    if len(detail_lines) > MAX_LINES:
        raise InvoiceImportError(
            InvoiceErrorCode.FILE_LIMIT_EXCEEDED,
            "A document has more lines than the supported maximum",
            details={"max_lines": MAX_LINES},
        )
    lines = [_read_line(element) for element in detail_lines]

    mapped_header: dict[str, Any] = {
        "supplier_name": parts.name,
        "supplier_vat_number": None if header.supplier is None else header.supplier.vat_number,
        "supplier_tax_code": None if header.supplier is None else header.supplier.tax_code,
        "supplier_iban_sha256": []
        if header.supplier is None
        else list(header.supplier.iban_sha256),
        "invoice_number": header.invoice_number,
        "invoice_date": date_text,
        "due_date": None if header.due_date is None else header.due_date.isoformat(),
        "document_type": type_code,
        "currency": header.currency,
        "invoice_net_amount": None if header.net_amount is None else format(header.net_amount, "f"),
        "invoice_tax_amount": None if header.tax_amount is None else format(header.tax_amount, "f"),
        "invoice_gross_amount": None
        if header.gross_amount is None
        else format(header.gross_amount, "f"),
    }
    return assemble(
        index=index,
        header=header,
        mapped_header=mapped_header,
        lines=lines,
        header_issues=issues,
        source_format=SourceFormat.FATTURAPA_XML,
    )


def _read_line(element: ET.Element) -> ParsedLine:
    issues: list[RowIssue] = []
    number_text = _text(element, "NumeroLinea")
    number: int | None = None
    if number_text is None:
        issues.append(RowIssue("line_number", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    elif not _INTEGER.match(number_text) or int(number_text) <= 0:
        issues.append(RowIssue("line_number", InvoiceErrorCode.INVALID_NUMBER))
    else:
        number = int(number_text)

    description = _text(element, "Descrizione")
    if description is None:
        issues.append(RowIssue("line_description", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        issues.append(RowIssue("line_description", InvoiceErrorCode.VALUE_TOO_LONG))
        description = None

    total_text = _text(element, "PrezzoTotale")
    line_total = _decimal(total_text, "line_total", issues)
    if total_text is None:
        issues.append(RowIssue("line_total", InvoiceErrorCode.REQUIRED_VALUE_MISSING))

    quantity = _decimal(_text(element, "Quantita"), "quantity", issues)
    unit_price = _decimal(_text(element, "PrezzoUnitario"), "unit_price", issues)
    vat_text = _text(element, "AliquotaIVA")
    vat_rate = _decimal(vat_text, "vat_rate", issues)
    if vat_rate is not None and not Decimal(0) <= vat_rate <= Decimal(100):
        issues.append(RowIssue("vat_rate", InvoiceErrorCode.OUT_OF_RANGE))
        vat_rate = None
    unit = _text(element, "UnitaMisura")
    if unit is not None and len(unit) > MAX_UNIT_LENGTH:
        issues.append(RowIssue("unit", InvoiceErrorCode.VALUE_TOO_LONG))
        unit = None

    mapped = {
        "line_number": number_text,
        "line_description": description,
        "quantity": _text(element, "Quantita"),
        "unit": unit,
        "unit_price": _text(element, "PrezzoUnitario"),
        "line_total": total_text,
        "vat_rate": vat_text,
    }
    raw = None
    if description is not None and line_total is not None and number is not None and not issues:
        raw = RawLine(
            source_line_number=number,
            description=description,
            line_total=line_total,
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            vat_rate=vat_rate,
        )
    return ParsedLine(mapped=mapped, source_line_number=number, raw=raw, issues=issues)

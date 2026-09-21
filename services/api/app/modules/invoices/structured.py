"""Structured CSV/XLSX invoice files: mapped columns -> grouped, validated documents.

Reading the file (encodings, delimiters, sheets, header row, duplicate headers) is the Gate 2
reader, reused as it is. Here the MAPPED columns of every row are read (every other column is
dropped at once), values are normalised by explicit rules (ISO dates or a configured pattern,
configured number separators: never guessed), and rows are grouped into documents:

    key = (supplier identity source, normalised invoice number, invoice date, document kind)

where the supplier identity source is the VAT number, else the tax code, else the normalised name.
Every header field repeated on the lines of one document must agree: two currencies, two totals or
incompatible supplier identifiers make the document INVALID (there is no "last row wins").
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.modules.bookings.parsers import Cell, SourceTable
from app.modules.bookings.text import normalize_key
from app.modules.invoices.canonical import (
    MAX_DECIMALS,
    RawLine,
    decimals_of,
    normalize_invoice_number,
)
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
from app.modules.invoices.mapping import (
    DATE_FIELDS,
    DECIMAL_FIELDS,
    InvoiceField,
    InvoiceMappingConfig,
    header_index,
    is_slashed_date,
    normalize_header,
    resolve_category,
    resolve_document_kind,
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

F = InvoiceField
_ISO_DATE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
_INTEGER = re.compile(r"^\d{1,9}$")
_MAX_TEXT = 300


# --- extraction: the data-minimisation boundary -----------------------------------------------


def extract(
    table: SourceTable, config: InvoiceMappingConfig
) -> list[tuple[int, dict[InvoiceField, Cell]]]:
    """(row number, values of the MAPPED columns) for every row that has at least one. Whatever
    else the row holds is dropped here and never reaches staging, logs or errors."""
    index = header_index(table.headers)
    positions = {
        field: index[normalize_header(column)] for field, column in config.mapped_columns().items()
    }
    constants = config.constants()
    rows: list[tuple[int, dict[InvoiceField, Cell]]] = []
    for row in table.rows():
        values: dict[InvoiceField, Cell] = {f: row.cells[i] for f, i in positions.items()}
        if all(value is None for value in values.values()):
            continue
        values.update(constants)
        rows.append((row.number, values))
    return rows


def require_explicit_formats(
    rows: list[tuple[int, dict[InvoiceField, Cell]]], config: InvoiceMappingConfig
) -> None:
    """Dates such as 01/02/2026 and numbers such as 1,234 mean two things: the profile must say
    which. Detected per column before any row is judged, so the customer is asked once."""
    options = config.format_options
    ambiguous_dates = sorted(
        field.value
        for field in DATE_FIELDS
        if field in config.column_mapping
        and field not in options.date_formats
        and any(
            isinstance(values.get(field), str) and is_slashed_date(str(values[field]))
            for _, values in rows
        )
    )
    if ambiguous_dates:
        raise InvoiceImportError(
            InvoiceErrorCode.AMBIGUOUS_DATE_FORMAT,
            "Some date columns are written day/month/year or month/day/year: set the date format",
            details={"fields": ambiguous_dates},
        )
    if options.decimal_separator is None and options.thousands_separator is None:
        ambiguous_numbers = sorted(
            field.value
            for field in DECIMAL_FIELDS
            if field in config.column_mapping
            and any(
                isinstance(values.get(field), str)
                and ("," in str(values[field]) or str(values[field]).count(".") > 1)
                for _, values in rows
            )
        )
        if ambiguous_numbers:
            raise InvoiceImportError(
                InvoiceErrorCode.AMBIGUOUS_NUMBER_FORMAT,
                "Some amount columns use separators that can mean two things: set them",
                details={"fields": ambiguous_numbers},
            )


# --- one value ----------------------------------------------------------------------------------


class _BadValueError(Exception):
    def __init__(self, code: InvoiceErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _text(cell: Cell) -> str | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER)
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else repr(cell)
    if isinstance(cell, datetime | date):
        return cell.isoformat()
    text = str(cell).strip()
    return text or None


def _date(cell: Cell, field: InvoiceField, config: InvoiceMappingConfig) -> date | None:
    if cell is None:
        return None
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if not isinstance(cell, str):
        raise _BadValueError(InvoiceErrorCode.INVALID_DATE)
    text = cell.strip()
    pattern = config.format_options.date_formats.get(field)
    try:
        if pattern is not None:
            return datetime.strptime(text, pattern).date()
        if _ISO_DATE.match(text):
            return datetime.fromisoformat(text.replace("/", "-", 2)).date()
    except ValueError:
        raise _BadValueError(InvoiceErrorCode.INVALID_DATE) from None
    raise _BadValueError(InvoiceErrorCode.INVALID_DATE)


def _decimal(cell: Cell, config: InvoiceMappingConfig) -> Decimal | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER)
    if isinstance(cell, Decimal):
        value = cell
    elif isinstance(cell, int):
        value = Decimal(cell)
    elif isinstance(cell, float):
        value = Decimal(repr(cell))  # Excel doubles: through the shortest repr, never the binary
    elif isinstance(cell, str):
        value = _parse_decimal_text(cell, config)
    else:
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER)
    if not value.is_finite():
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER)
    if decimals_of(value) > MAX_DECIMALS:
        raise _BadValueError(InvoiceErrorCode.AMOUNT_PRECISION)
    return value


def _parse_decimal_text(text: str, config: InvoiceMappingConfig) -> Decimal:
    """ "1234.56", "1,234.56", "1234,56" or "1.234,56" as configured; never guessed."""
    cleaned = text.replace(" ", " ").strip()
    decimal = config.format_options.decimal_separator or "."
    thousands = config.format_options.thousands_separator
    dec = re.escape(decimal)
    if thousands:
        thou = re.escape(thousands)
        pattern = rf"^-?(?:\d+|\d{{1,3}}(?:{thou}\d{{3}})+)(?:{dec}\d+)?$"
    else:
        pattern = rf"^-?\d+(?:{dec}\d+)?$"
    if not re.match(pattern, cleaned):
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER)
    normalised = cleaned.replace(thousands, "") if thousands else cleaned
    try:
        return Decimal(normalised.replace(decimal, "."))
    except InvalidOperation:
        raise _BadValueError(InvoiceErrorCode.INVALID_NUMBER) from None


# --- one row ---------------------------------------------------------------------------------


class _Row:
    """One source row, parsed field by field, with its issues (a bad field never hides the rest)."""

    def __init__(
        self,
        number: int,
        values: Mapping[InvoiceField, Cell],
        config: InvoiceMappingConfig,
        property_currency: str,
    ) -> None:
        self.number = number
        self.issues: list[RowIssue] = []
        self.warnings: list[RowWarning] = []
        self.mapped: dict[str, Any] = {}
        self._values = values
        self._config = config

        self.supplier_name = self._name()
        self.vat = self._identifier(
            F.SUPPLIER_VAT_NUMBER, normalize_vat_number, InvoiceErrorCode.INVALID_VAT_NUMBER
        )
        self.tax_code = self._identifier(
            F.SUPPLIER_TAX_CODE, normalize_tax_code, InvoiceErrorCode.INVALID_TAX_CODE
        )
        self.iban_hashes = self._iban()
        self.invoice_number = self._required_text(F.INVOICE_NUMBER)
        self.invoice_date = self._required_date(F.INVOICE_DATE)
        self.due_date = self._optional(F.DUE_DATE, self._date_of)
        self.document_type_text = self._safe(F.DOCUMENT_TYPE, _text)
        self.kind = self._kind()
        currency = self._safe(F.CURRENCY, _text)
        self.currency = (currency or property_currency).upper()
        self.net = self._amount(F.INVOICE_NET_AMOUNT)
        self.tax = self._amount(F.INVOICE_TAX_AMOUNT)
        self.gross = self._amount(F.INVOICE_GROSS_AMOUNT)

        self.line_number = self._line_number()
        self.description = self._description()
        self.line_total = self._amount(F.LINE_TOTAL, required=True)
        self.quantity = self._amount(F.QUANTITY)
        self.unit = self._unit()
        self.unit_price = self._amount(F.UNIT_PRICE)
        self.vat_rate = self._rate()
        self.category = self._category()

    # --- helpers ---------------------------------------------------------------------------

    def _add(self, field: InvoiceField, code: InvoiceErrorCode, value: str | None = None) -> None:
        self.issues.append(RowIssue(field.value, code, value=value))

    def _record(self, field: InvoiceField, text: str | None) -> None:
        if text is not None:
            self.mapped[field.value] = text if len(text) <= 500 else text[:500] + "…"

    def _safe(self, field: InvoiceField, reader: Any) -> Any:
        try:
            value = reader(self._values.get(field))
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        return value

    def _optional(self, field: InvoiceField, reader: Any) -> Any:
        try:
            value = reader(self._values.get(field), field)
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        self._record(field, None if value is None else str(value))
        return value

    def _date_of(self, cell: Cell, field: InvoiceField) -> date | None:
        return _date(cell, field, self._config)

    def _name(self) -> str | None:
        raw = self._safe(F.SUPPLIER_NAME, _text)
        if raw is None:
            self._add(F.SUPPLIER_NAME, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
            return None
        name = display_name(raw)
        if len(name) > _MAX_TEXT:
            self._add(F.SUPPLIER_NAME, InvoiceErrorCode.VALUE_TOO_LONG)
            return None
        if not normalize_supplier_name(name):
            self._add(F.SUPPLIER_NAME, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
            return None
        self._record(F.SUPPLIER_NAME, name)
        return name

    def _identifier(
        self, field: InvoiceField, normalizer: Any, code: InvoiceErrorCode
    ) -> str | None:
        raw = self._safe(field, _text)
        if raw is None:
            return None
        try:
            value: str = normalizer(raw)
        except ValueError:
            self._add(field, code)
            return None
        self._record(field, value)
        return value

    def _iban(self) -> tuple[str, ...]:
        """The IBAN is hashed HERE. Neither the raw value nor an error about it is kept."""
        raw = self._safe(F.SUPPLIER_IBAN, _text)
        if raw is None:
            return ()
        digest = hash_iban(raw)
        if digest is None:
            self.warnings.append(RowWarning("supplier_iban", WarningCode.INVALID_IBAN_IGNORED))
            return ()
        self.mapped["supplier_iban_sha256"] = digest
        return (digest,)

    def _required_text(self, field: InvoiceField) -> str | None:
        value: str | None = self._safe(field, _text)
        if value is None:
            self._add(field, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
            return None
        self._record(field, value)
        return value

    def _required_date(self, field: InvoiceField) -> date | None:
        value = self._optional(field, self._date_of)
        if value is None and not any(issue.field == field.value for issue in self.issues):
            self._add(field, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
        return value  # type: ignore[no-any-return]

    def _kind(self) -> DocumentKind | None:
        if F.DOCUMENT_TYPE not in self._config.column_mapping:
            return DocumentKind.INVOICE
        if self.document_type_text is None:
            return DocumentKind.INVOICE  # an empty cell: an ordinary invoice
        self._record(F.DOCUMENT_TYPE, self.document_type_text)
        kind = resolve_document_kind(self.document_type_text)
        if kind is None:
            self._add(F.DOCUMENT_TYPE, InvoiceErrorCode.UNKNOWN_DOCUMENT_TYPE)
        return kind

    def _amount(self, field: InvoiceField, *, required: bool = False) -> Decimal | None:
        try:
            value = _decimal(self._values.get(field), self._config)
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        if value is None:
            if required:
                self._add(field, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
            return None
        self._record(field, format(value, "f"))
        return value

    def _rate(self) -> Decimal | None:
        value = self._amount(F.VAT_RATE)
        if value is not None and not Decimal(0) <= value <= Decimal(100):
            self._add(F.VAT_RATE, InvoiceErrorCode.OUT_OF_RANGE)
            return None
        return value

    def _line_number(self) -> int:
        """The source's own line number when mapped, else the row number (always unique)."""
        cell = self._values.get(F.LINE_NUMBER)
        if F.LINE_NUMBER not in self._config.column_mapping or cell is None:
            return self.number
        text = self._safe(F.LINE_NUMBER, _text)
        if text is None or not _INTEGER.match(text) or int(text) <= 0:
            self._add(F.LINE_NUMBER, InvoiceErrorCode.INVALID_NUMBER)
            return self.number
        self._record(F.LINE_NUMBER, text)
        return int(text)

    def _description(self) -> str | None:
        text: str | None = self._safe(F.LINE_DESCRIPTION, _text)
        if text is None:
            self._add(F.LINE_DESCRIPTION, InvoiceErrorCode.REQUIRED_VALUE_MISSING)
            return None
        if len(text) > MAX_DESCRIPTION_LENGTH:
            self._add(F.LINE_DESCRIPTION, InvoiceErrorCode.VALUE_TOO_LONG)
            return None
        self._record(F.LINE_DESCRIPTION, text)
        return text

    def _unit(self) -> str | None:
        text: str | None = self._safe(F.UNIT, _text)
        if text is None:
            return None
        if len(text) > MAX_UNIT_LENGTH:
            self._add(F.UNIT, InvoiceErrorCode.VALUE_TOO_LONG)
            return None
        self._record(F.UNIT, text)
        return text

    def _category(self) -> Any:
        text = self._safe(F.COST_CATEGORY, _text)
        if text is None:
            return None
        self._record(F.COST_CATEGORY, text)
        category = resolve_category(text, self._config.category_mapping)
        if category is None:
            self._add(F.COST_CATEGORY, InvoiceErrorCode.UNKNOWN_CATEGORY, value=text[:80])
        return category

    # --- grouping key ------------------------------------------------------------------------

    @property
    def group_key(self) -> tuple[Any, ...] | None:
        """None when a component is unusable: the row then stands alone, with its issues."""
        if (
            self.supplier_name is None
            or self.invoice_number is None
            or self.invoice_date is None
            or self.kind is None
        ):
            return None
        source = (
            ("vat", self.vat)
            if self.vat
            else ("tax", self.tax_code)
            if self.tax_code
            else ("name", normalize_supplier_name(self.supplier_name))
        )
        return (source, normalize_invoice_number(self.invoice_number), self.invoice_date, self.kind)


# --- documents -------------------------------------------------------------------------------


def parse_structured(
    rows: Iterable[tuple[int, dict[InvoiceField, Cell]]],
    config: InvoiceMappingConfig,
    *,
    property_currency: str,
    data_source_id: UUID | None,
    source_format: SourceFormat,
) -> list[ParsedDocument]:
    """Group the rows into documents (numbered in order of first appearance) and assemble them."""
    parsed_rows = [_Row(number, values, config, property_currency) for number, values in rows]
    groups: dict[Any, list[_Row]] = defaultdict(list)
    order: list[Any] = []
    for row in parsed_rows:
        key = row.group_key if row.group_key is not None else ("stand-alone", row.number)
        if key not in groups:
            order.append(key)
        groups[key].append(row)
    return [
        _assemble_group(index, groups[key], config, data_source_id, source_format)
        for index, key in enumerate(order, start=1)
    ]


def _distinct(values: Iterable[Any]) -> list[Any]:
    found: list[Any] = []
    for value in values:
        if value is not None and value not in found:
            found.append(value)
    return found


def _assemble_group(
    index: int,
    rows: list[_Row],
    config: InvoiceMappingConfig,
    data_source_id: UUID | None,
    source_format: SourceFormat,
) -> ParsedDocument:
    issues: list[RowIssue] = []

    def consistent(field: str, values: Iterable[Any]) -> Any:
        distinct = _distinct(values)
        if len(distinct) > 1:
            issues.append(RowIssue(field, InvoiceErrorCode.INCONSISTENT_HEADER))
        return distinct[0] if distinct else None

    names = consistent(
        "supplier_name",
        (normalize_supplier_name(r.supplier_name) for r in rows if r.supplier_name),
    )
    first_name = next((r.supplier_name for r in rows if r.supplier_name), None)
    vat = consistent("supplier_vat_number", (r.vat for r in rows))
    tax = consistent("supplier_tax_code", (r.tax_code for r in rows))
    ibans = sorted({h for r in rows for h in r.iban_hashes})
    currency = consistent("currency", (r.currency for r in rows))
    due = consistent("due_date", (r.due_date for r in rows))
    type_text = consistent(
        "document_type", (normalize_key(r.document_type_text) for r in rows if r.document_type_text)
    )
    net = consistent("invoice_net_amount", (r.net for r in rows))
    tax_amount = consistent("invoice_tax_amount", (r.tax for r in rows))
    gross = consistent("invoice_gross_amount", (r.gross for r in rows))
    number = consistent("invoice_number", (r.invoice_number for r in rows))
    invoice_date = consistent("invoice_date", (r.invoice_date for r in rows))

    header = Header()
    if first_name is not None and names is not None:
        try:
            header.supplier = SupplierEvidence(
                legal_name=first_name,
                normalized_name=names,
                country=normalize_country(vat[:2]) if vat else None,
                vat_number=vat,
                tax_code=tax,
                iban_sha256=tuple(ibans),
                data_source_id=data_source_id,
            )
        except ValueError:  # pragma: no cover - the values were normalised row by row
            issues.append(RowIssue("supplier_name", InvoiceErrorCode.REQUIRED_VALUE_MISSING))
    header.invoice_number = number
    header.invoice_date = invoice_date
    header.due_date = due
    header.document_kind = next((r.kind for r in rows if r.kind is not None), None)
    header.document_type_code = (
        next((r.document_type_text for r in rows if r.document_type_text), None)
        if type_text is not None
        else None
    )
    header.currency = currency
    header.net_amount, header.tax_amount, header.gross_amount = net, tax_amount, gross
    header.warnings = _distinct_warnings(rows)

    lines = [
        ParsedLine(
            mapped=r.mapped,
            source_line_number=r.line_number,
            raw=_raw_line(r),
            issues=list(r.issues),
        )
        for r in rows
    ]
    mapped_header = {
        key: value
        for key, value in rows[0].mapped.items()
        if key
        in {
            "supplier_name",
            "supplier_vat_number",
            "supplier_tax_code",
            "supplier_iban_sha256",
            "invoice_number",
            "invoice_date",
            "due_date",
            "document_type",
            "invoice_net_amount",
            "invoice_tax_amount",
            "invoice_gross_amount",
        }
    }
    mapped_header["currency"] = currency
    return assemble(
        index=index,
        header=header,
        mapped_header=mapped_header,
        lines=lines,
        header_issues=issues,
        source_format=source_format,
    )


def _distinct_warnings(rows: list[_Row]) -> list[RowWarning]:
    return _distinct(warning for row in rows for warning in row.warnings)


def _raw_line(row: _Row) -> RawLine | None:
    if row.issues or row.description is None or row.line_total is None:
        return None
    return RawLine(
        source_line_number=row.line_number,
        description=row.description,
        line_total=row.line_total,
        quantity=row.quantity,
        unit=row.unit,
        unit_price=row.unit_price,
        vat_rate=row.vat_rate,
        explicit_category=row.category,
    )

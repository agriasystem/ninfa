"""Invoice column mapping ("mapping memory") for structured CSV/XLSX files.

A confirmed mapping says which source column feeds each canonical field (or gives a constant where
that is safe), how to read the file, and how to read category labels. Only mapped columns are ever
read into NINFA: that is how unneeded personal data is kept out. It is NOT the booking mapping:
the two have different fields and rules, and share only the header helpers.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.core.iso4217 import ISO_4217_CODES
from app.modules.bookings.mapping import (
    FieldSource,
    compute_header_signature,
    header_index,
    normalize_header,
    validate_date_pattern,
)
from app.modules.bookings.text import normalize_key
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError
from app.modules.invoices.models import DocumentKind

__all__ = ["compute_header_signature", "header_index", "normalize_header"]


class InvoiceField(StrEnum):
    SUPPLIER_NAME = "supplier_name"
    SUPPLIER_VAT_NUMBER = "supplier_vat_number"
    SUPPLIER_TAX_CODE = "supplier_tax_code"
    SUPPLIER_IBAN = "supplier_iban"
    INVOICE_NUMBER = "invoice_number"
    INVOICE_DATE = "invoice_date"
    DUE_DATE = "due_date"
    DOCUMENT_TYPE = "document_type"
    CURRENCY = "currency"
    INVOICE_NET_AMOUNT = "invoice_net_amount"
    INVOICE_TAX_AMOUNT = "invoice_tax_amount"
    INVOICE_GROSS_AMOUNT = "invoice_gross_amount"
    LINE_NUMBER = "line_number"
    LINE_DESCRIPTION = "line_description"
    QUANTITY = "quantity"
    UNIT = "unit"
    UNIT_PRICE = "unit_price"
    LINE_TOTAL = "line_total"
    VAT_RATE = "vat_rate"
    COST_CATEGORY = "cost_category"


F = InvoiceField
REQUIRED_FIELDS = frozenset(
    {F.SUPPLIER_NAME, F.INVOICE_NUMBER, F.INVOICE_DATE, F.LINE_DESCRIPTION, F.LINE_TOTAL}
)
# A constant is only safe where it cannot invent facts about one invoice or one line: never the
# invoice number, the dates, the supplier, the description or the amount.
CONSTANT_FIELDS = frozenset({F.DOCUMENT_TYPE, F.CURRENCY, F.COST_CATEGORY})
DATE_FIELDS = frozenset({F.INVOICE_DATE, F.DUE_DATE})
DECIMAL_FIELDS = frozenset(
    {
        F.INVOICE_NET_AMOUNT,
        F.INVOICE_TAX_AMOUNT,
        F.INVOICE_GROSS_AMOUNT,
        F.QUANTITY,
        F.UNIT_PRICE,
        F.LINE_TOTAL,
        F.VAT_RATE,
    }
)

# Labels of the document type column (compared through `normalize_key`).
CREDIT_NOTE_LABELS = frozenset(
    {"td04", "td08", "credit note", "creditnote", "credit", "nota di credito", "nota credito", "nc"}
)
INVOICE_LABELS = frozenset(
    {
        "td01",
        "td02",
        "td03",
        "td05",
        "td06",
        "td07",
        "td09",
        "td24",
        "td25",
        "invoice",
        "fattura",
        "fattura immediata",
        "fattura differita",
        "nota di debito",
        "debit note",
    }
)


def resolve_document_kind(label: str) -> DocumentKind | None:
    key = normalize_key(label)
    if key in CREDIT_NOTE_LABELS:
        return DocumentKind.CREDIT_NOTE
    if key in INVOICE_LABELS:
        return DocumentKind.INVOICE
    return None


class InvoiceFormatOptions(BaseModel):
    """How to read the file. Everything is explicit: nothing is inferred while importing."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    delimiter: Literal[",", ";", "\t"] | None = None
    encoding: Literal["utf-8", "cp1252"] | None = None
    date_formats: dict[InvoiceField, str] = {}
    decimal_separator: Literal[".", ","] | None = None
    thousands_separator: Literal[",", ".", " ", "'"] | None = None

    @field_validator("date_formats")
    @classmethod
    def _date_formats(cls, value: dict[InvoiceField, str]) -> dict[InvoiceField, str]:
        for field, pattern in value.items():
            if field not in DATE_FIELDS:
                raise ValueError(f"{field.value} is not a date field")
            validate_date_pattern(pattern)
        return value

    @model_validator(mode="after")
    def _separators_differ(self) -> "InvoiceFormatOptions":
        if self.decimal_separator and self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal_separator and thousands_separator must differ")
        return self


class InvoiceMappingConfig(BaseModel):
    """A validated mapping. Invalid configurations cannot be constructed."""

    model_config = ConfigDict(extra="forbid")

    column_mapping: dict[InvoiceField, FieldSource]
    category_mapping: dict[str, CostCategory] = {}
    format_options: InvoiceFormatOptions = InvoiceFormatOptions()

    @field_validator("category_mapping")
    @classmethod
    def _normalise_category_keys(cls, value: dict[str, CostCategory]) -> dict[str, CostCategory]:
        normalised: dict[str, CostCategory] = {}
        for raw_key, category in value.items():
            key = normalize_key(raw_key)
            if not key:
                raise ValueError("a category label has no letters or digits")
            if normalised.get(key, category) != category:
                raise ValueError(
                    "two category labels differ only in case/punctuation but map differently"
                )
            normalised[key] = category
        return normalised

    @model_validator(mode="after")
    def _check_fields(self) -> "InvoiceMappingConfig":
        missing = sorted(f.value for f in REQUIRED_FIELDS if f not in self.column_mapping)
        if missing:
            raise ValueError(f"required fields not mapped: {', '.join(missing)}")
        for field, source in self.column_mapping.items():
            if source.constant is not None and field not in CONSTANT_FIELDS:
                allowed = ", ".join(sorted(f.value for f in CONSTANT_FIELDS))
                raise ValueError(f"{field.value} cannot be a constant (allowed: {allowed})")
        self._check_constants()
        return self

    def _check_constants(self) -> None:
        currency = self.column_mapping.get(F.CURRENCY)
        if (
            currency is not None
            and currency.constant is not None
            and str(currency.constant).strip().upper() not in ISO_4217_CODES
        ):
            raise ValueError("the constant for currency is not an ISO 4217 code")
        kind = self.column_mapping.get(F.DOCUMENT_TYPE)
        if (
            kind is not None
            and kind.constant is not None
            and resolve_document_kind(str(kind.constant)) is None
        ):
            raise ValueError("the constant for document_type is not a recognised document type")
        category = self.column_mapping.get(F.COST_CATEGORY)
        if (
            category is not None
            and category.constant is not None
            and resolve_category(str(category.constant), self.category_mapping) is None
        ):
            raise ValueError("the constant for cost_category is not a recognised category")

    # --- conversions ---------------------------------------------------------------------------

    def mapped_columns(self) -> dict[InvoiceField, str]:
        return {f: s.column for f, s in self.column_mapping.items() if s.column is not None}

    def constants(self) -> dict[InvoiceField, str | int]:
        return {f: s.constant for f, s in self.column_mapping.items() if s.constant is not None}

    def to_stored(self) -> dict[str, dict[str, Any]]:
        """The three JSON documents persisted in the mapping profile."""
        return {
            "column_mapping": {
                field.value: source.model_dump(mode="json", exclude_none=True)
                for field, source in self.column_mapping.items()
            },
            "category_mapping": {key: cat.value for key, cat in self.category_mapping.items()},
            "format_options": self.format_options.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            ),
        }

    @classmethod
    def parse(cls, data: Mapping[str, Any]) -> "InvoiceMappingConfig":
        """Build from untrusted/stored data; failures become INVOICE_INVALID_MAPPING."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            problems = [
                {"loc": ".".join(str(part) for part in err["loc"]), "msg": err["msg"]}
                for err in exc.errors()
            ]
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_MAPPING,
                "The invoice mapping is not valid",
                details={"problems": problems},
            ) from exc


def resolve_category(label: str, mapping: Mapping[str, CostCategory]) -> CostCategory | None:
    """A source label as a canonical category: through the confirmed mapping, or when the label IS
    a canonical category name (case, spacing and punctuation aside). Anything else is unknown."""
    key = normalize_key(label)
    if key in mapping:
        return mapping[key]
    for category in CostCategory:
        if normalize_key(category.value) == key:
            return category
    return None


@dataclass(frozen=True)
class SchemaCheck:
    compatible: bool
    signature_matches: bool
    missing_columns: tuple[str, ...]


def check_schema(
    config: InvoiceMappingConfig, stored_signature: str, headers: Sequence[str]
) -> SchemaCheck:
    """Can the confirmed mapping still be applied? Yes when every MAPPED column is still there
    (extra columns are harmless); a renamed or removed mapped column means the schema changed."""
    index = header_index(headers)
    missing = tuple(
        column
        for column in config.mapped_columns().values()
        if normalize_header(column) not in index
    )
    return SchemaCheck(
        compatible=not missing,
        signature_matches=compute_header_signature(headers) == stored_signature,
        missing_columns=missing,
    )


_SLASHED_DATE = re.compile(
    r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$"
)


def is_slashed_date(text: str) -> bool:
    """Day/month or month/day first: cannot be read without a configured pattern."""
    return bool(_SLASHED_DATE.match(text.strip()))

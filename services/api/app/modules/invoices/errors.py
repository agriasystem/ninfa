"""Stable, machine-readable error codes of the invoice import.

Callers (and later the API/UI) branch on the *code*, never on the human message. Job-level codes end
up in `ImportJob.error_code`; row-level codes in a staged row's `validation_errors`. Messages and
details never contain row payloads, unmapped columns, identifiers or an IBAN.
"""

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class InvoiceErrorCode(StrEnum):
    # --- job level: the import cannot proceed ---------------------------------------------------
    INVALID_DATA_SOURCE = "INVOICE_INVALID_DATA_SOURCE"
    UNSUPPORTED_FILE_TYPE = "INVOICE_UNSUPPORTED_FILE_TYPE"
    UNREADABLE_FILE = "INVOICE_UNREADABLE_FILE"
    EMPTY_FILE = "INVOICE_EMPTY_FILE"
    FILE_LIMIT_EXCEEDED = "INVOICE_FILE_LIMIT_EXCEEDED"
    DUPLICATE_HEADER = "INVOICE_DUPLICATE_HEADER"
    MAPPING_REQUIRED = "INVOICE_MAPPING_REQUIRED"
    INVALID_MAPPING = "INVOICE_INVALID_MAPPING"
    SOURCE_SCHEMA_CHANGED = "INVOICE_SOURCE_SCHEMA_CHANGED"
    AMBIGUOUS_DATE_FORMAT = "INVOICE_AMBIGUOUS_DATE_FORMAT"
    AMBIGUOUS_NUMBER_FORMAT = "INVOICE_AMBIGUOUS_NUMBER_FORMAT"
    UNSUPPORTED_FATTURAPA = "INVOICE_UNSUPPORTED_FATTURAPA"
    XML_SECURITY_REJECTED = "INVOICE_XML_SECURITY_REJECTED"
    VALIDATION_FAILED = "INVOICE_VALIDATION_FAILED"
    DOCUMENT_CONFLICT = "INVOICE_DOCUMENT_CONFLICT"
    CANONICALIZATION_FAILED = "INVOICE_CANONICALIZATION_FAILED"
    INTERNAL_ERROR = "INVOICE_INTERNAL_ERROR"
    # --- row / document level (also used as job-level summary keys) ------------------------------
    REQUIRED_VALUE_MISSING = "INVOICE_REQUIRED_VALUE_MISSING"
    INVALID_DATE = "INVOICE_INVALID_DATE"
    INVALID_NUMBER = "INVOICE_INVALID_NUMBER"
    AMOUNT_PRECISION = "INVOICE_AMOUNT_PRECISION"
    OUT_OF_RANGE = "INVOICE_OUT_OF_RANGE"
    VALUE_TOO_LONG = "INVOICE_VALUE_TOO_LONG"
    INVALID_CURRENCY = "INVOICE_INVALID_CURRENCY"
    INVALID_VAT_NUMBER = "INVOICE_INVALID_VAT_NUMBER"
    INVALID_TAX_CODE = "INVOICE_INVALID_TAX_CODE"
    INVALID_COUNTRY = "INVOICE_INVALID_COUNTRY"
    UNKNOWN_DOCUMENT_TYPE = "INVOICE_UNKNOWN_DOCUMENT_TYPE"
    UNSUPPORTED_DOCUMENT_TYPE = "INVOICE_UNSUPPORTED_DOCUMENT_TYPE"
    UNKNOWN_CATEGORY = "INVOICE_UNKNOWN_CATEGORY"
    DUPLICATE_LINE = "INVOICE_DUPLICATE_LINE"
    INCONSISTENT_HEADER = "INVOICE_INCONSISTENT_HEADER"
    NO_LINES = "INVOICE_NO_LINES"


class InvoiceImportError(AppError):
    """An invoice-import failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: InvoiceErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code


@dataclass(frozen=True)
class RowIssue:
    """One problem found in a document or a line. Carries the field and a code, not the value."""

    field: str
    code: InvoiceErrorCode
    detail: str | None = None
    # Only ever set for categorical values needed to fix a mapping (an unknown category label).
    value: str | None = None

    def to_json(self) -> dict[str, str]:
        payload = {"field": self.field, "code": self.code.value}
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.value is not None:
            payload["value"] = self.value
        return payload


class WarningCode(StrEnum):
    """Diagnostics that do not stop an import."""

    MULTIPLE_PAYMENT_DUE_DATES = "MULTIPLE_PAYMENT_DUE_DATES"
    INVALID_IBAN_IGNORED = "INVALID_IBAN_IGNORED"
    BENEFICIARY_IBAN_IGNORED = "BENEFICIARY_IBAN_IGNORED"


@dataclass(frozen=True)
class RowWarning:
    field: str
    code: WarningCode

    def to_json(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code.value}

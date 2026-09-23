"""Stable, machine-readable error codes of the labor import.

Callers (and later the API/UI) branch on the *code*, never on the human message. Job-level codes
end up in `ImportJob.error_code`; row-level codes in a staged row's `validation_errors`. Messages
and details never contain a person's identity: labor V1 does not collect it in the first place.
"""

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class LaborErrorCode(StrEnum):
    # --- job level: the import cannot proceed ---------------------------------------------------
    INVALID_DATA_SOURCE = "LABOR_INVALID_DATA_SOURCE"
    UNSUPPORTED_FILE_TYPE = "LABOR_UNSUPPORTED_FILE_TYPE"
    UNREADABLE_FILE = "LABOR_UNREADABLE_FILE"
    EMPTY_FILE = "LABOR_EMPTY_FILE"
    FILE_LIMIT_EXCEEDED = "LABOR_FILE_LIMIT_EXCEEDED"
    DUPLICATE_HEADER = "LABOR_DUPLICATE_HEADER"
    MAPPING_REQUIRED = "LABOR_MAPPING_REQUIRED"
    INVALID_MAPPING = "LABOR_INVALID_MAPPING"
    SOURCE_SCHEMA_CHANGED = "LABOR_SOURCE_SCHEMA_CHANGED"
    AMBIGUOUS_DATE_FORMAT = "LABOR_AMBIGUOUS_DATE_FORMAT"
    AMBIGUOUS_NUMBER_FORMAT = "LABOR_AMBIGUOUS_NUMBER_FORMAT"
    SNAPSHOT_DATE_REQUIRED = "LABOR_SNAPSHOT_DATE_REQUIRED"
    SNAPSHOT_CONFLICT = "LABOR_SNAPSHOT_CONFLICT"
    VALIDATION_FAILED = "LABOR_VALIDATION_FAILED"
    CANONICALIZATION_FAILED = "LABOR_CANONICALIZATION_FAILED"
    INTERNAL_ERROR = "LABOR_INTERNAL_ERROR"
    # --- row level (also used as job-level summary keys) -----------------------------------------
    REQUIRED_VALUE_MISSING = "LABOR_REQUIRED_VALUE_MISSING"
    INVALID_DATE = "LABOR_INVALID_DATE"
    INVALID_NUMBER = "LABOR_INVALID_NUMBER"
    NEGATIVE_VALUE = "LABOR_NEGATIVE_VALUE"
    FRACTIONAL_MINUTES = "LABOR_FRACTIONAL_MINUTES"
    HOURS_MISSING = "LABOR_HOURS_MISSING"
    CURRENCY_REQUIRED = "LABOR_CURRENCY_REQUIRED"
    INVALID_CURRENCY = "LABOR_INVALID_CURRENCY"
    UNKNOWN_CATEGORY = "LABOR_UNKNOWN_CATEGORY"
    VALUE_TOO_LONG = "LABOR_VALUE_TOO_LONG"


class LaborImportError(AppError):
    """A labor-import failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: LaborErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code


@dataclass(frozen=True)
class RowIssue:
    """One problem found in one staged row. Carries the field and a code, not the row."""

    field: str
    code: LaborErrorCode
    detail: str | None = None
    # Only ever set for a categorical value needed to fix a mapping (an unknown category label).
    value: str | None = None

    def to_json(self) -> dict[str, str]:
        payload = {"field": self.field, "code": self.code.value}
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.value is not None:
            payload["value"] = self.value
        return payload

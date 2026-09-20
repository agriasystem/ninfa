"""Stable, machine-readable error codes of the booking import.

Callers (and later the API/UI) must branch on the *code*, never on the human message.
Job-level codes end up in `ImportJob.error_code`; row-level codes in a staged row's
`validation_errors`. Messages and details never contain row payloads or unmapped columns.
"""

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class BookingErrorCode(StrEnum):
    # --- job level: the import cannot proceed ---------------------------------------------------
    INVALID_DATA_SOURCE = "BOOKING_INVALID_DATA_SOURCE"
    UNSUPPORTED_FILE_TYPE = "BOOKING_UNSUPPORTED_FILE_TYPE"
    UNREADABLE_FILE = "BOOKING_UNREADABLE_FILE"
    EMPTY_FILE = "BOOKING_EMPTY_FILE"
    FILE_LIMIT_EXCEEDED = "BOOKING_FILE_LIMIT_EXCEEDED"
    DUPLICATE_HEADER = "BOOKING_DUPLICATE_HEADER"
    MAPPING_REQUIRED = "BOOKING_MAPPING_REQUIRED"
    INVALID_MAPPING = "BOOKING_INVALID_MAPPING"
    SOURCE_SCHEMA_CHANGED = "BOOKING_SOURCE_SCHEMA_CHANGED"
    AMBIGUOUS_DATE_FORMAT = "BOOKING_AMBIGUOUS_DATE_FORMAT"
    AMBIGUOUS_NUMBER_FORMAT = "BOOKING_AMBIGUOUS_NUMBER_FORMAT"
    VALIDATION_FAILED = "BOOKING_VALIDATION_FAILED"
    CANONICALIZATION_FAILED = "BOOKING_CANONICALIZATION_FAILED"
    INTERNAL_ERROR = "BOOKING_INTERNAL_ERROR"
    # --- row level (also used as job-level summary keys) -----------------------------------------
    DUPLICATE_SOURCE_ID = "BOOKING_DUPLICATE_SOURCE_ID"
    UNKNOWN_STATUS = "BOOKING_UNKNOWN_STATUS"
    REQUIRED_VALUE_MISSING = "BOOKING_REQUIRED_VALUE_MISSING"
    INVALID_DATE = "BOOKING_INVALID_DATE"
    INVALID_DATETIME = "BOOKING_INVALID_DATETIME"
    # A naive local time that maps to no instant / to two instants (daylight-saving change).
    NONEXISTENT_LOCAL_TIME = "BOOKING_NONEXISTENT_LOCAL_TIME"
    AMBIGUOUS_LOCAL_TIME = "BOOKING_AMBIGUOUS_LOCAL_TIME"
    INVALID_NUMBER = "BOOKING_INVALID_NUMBER"
    INVALID_INTEGER = "BOOKING_INVALID_INTEGER"
    AMOUNT_PRECISION = "BOOKING_AMOUNT_PRECISION"
    NEGATIVE_VALUE = "BOOKING_NEGATIVE_VALUE"
    NOT_POSITIVE = "BOOKING_NOT_POSITIVE"
    OUT_OF_RANGE = "BOOKING_OUT_OF_RANGE"
    VALUE_TOO_LONG = "BOOKING_VALUE_TOO_LONG"
    CHECK_OUT_NOT_AFTER_CHECK_IN = "BOOKING_CHECK_OUT_NOT_AFTER_CHECK_IN"
    CANCELLED_AT_WITHOUT_CANCELLED_STATUS = "BOOKING_CANCELLED_AT_WITHOUT_CANCELLED_STATUS"


class BookingImportError(AppError):
    """A booking-import failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: BookingErrorCode,
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
    code: BookingErrorCode
    detail: str | None = None
    # Only ever set for categorical values needed to fix a mapping (an unknown status).
    value: str | None = None

    def to_json(self) -> dict[str, str]:
        payload = {"field": self.field, "code": self.code.value}
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.value is not None:
            payload["value"] = self.value
        return payload

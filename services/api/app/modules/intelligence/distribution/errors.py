"""Stable, machine-readable error codes of REV_OTA_DEPENDENCY Detection.

Callers branch on the *code*, never on the message. A detector that simply cannot decide (an
incomplete window, low coverage, ...) does NOT raise: it returns an evaluation whose status says
so. Errors are for requests that cannot be answered at all (an unusable property, booking source
or target as-of).
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class OtaDependencyErrorCode(StrEnum):
    INVALID_PROPERTY = "OTA_DEPENDENCY_INVALID_PROPERTY"
    BOOKING_DATA_SOURCE_INVALID = "OTA_DEPENDENCY_BOOKING_DATA_SOURCE_INVALID"
    INVALID_AS_OF_DATE = "OTA_DEPENDENCY_INVALID_AS_OF_DATE"


class OtaDependencyError(AppError):
    """A REV_OTA_DEPENDENCY evaluation failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: OtaDependencyErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

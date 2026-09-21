"""Stable, machine-readable error codes of the Expected Engine.

Callers branch on the *code*, never on the message. Messages and details carry ids, dates and
counts only.
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class ExpectedErrorCode(StrEnum):
    # A stored baseline for the same target and calculation_version differs from the new result.
    BASELINE_CONFLICT = "EXPECTED_BASELINE_CONFLICT"
    # Operational targets must be real observations, never reconstructions.
    TARGET_NOT_OBSERVED = "EXPECTED_TARGET_NOT_OBSERVED"
    # Unknown snapshot, or one of another workspace (indistinguishable).
    TARGET_NOT_FOUND = "EXPECTED_TARGET_NOT_FOUND"
    # details.reason: negative_lead_time | data_source_mismatch | property_mismatch
    INVALID_TARGET = "EXPECTED_INVALID_TARGET"
    INVALID_PROPERTY = "EXPECTED_INVALID_PROPERTY"
    INVALID_DATA_SOURCE = "EXPECTED_INVALID_DATA_SOURCE"
    INVALID_RANGE = "EXPECTED_INVALID_RANGE"


class ExpectedError(AppError):
    """An Expected Engine failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: ExpectedErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

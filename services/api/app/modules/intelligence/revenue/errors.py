"""Stable, machine-readable error codes of Revenue Decision Detection.

Callers branch on the *code*, never on the message. Messages and details carry ids, dates and
reasons only. A detector that simply cannot decide (not enough data, a sold-out night, ...) does
NOT raise: it returns an evaluation whose status says so. Errors are for requests that cannot be
answered at all.
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class RevenueErrorCode(StrEnum):
    # Unknown snapshot, or one of another workspace (indistinguishable).
    TARGET_NOT_FOUND = "REVENUE_TARGET_NOT_FOUND"
    # Operational targets must be real observations, never reconstructions.
    TARGET_NOT_OBSERVED = "REVENUE_TARGET_NOT_OBSERVED"
    # details.reason: negative_lead_time | data_source_mismatch | property_mismatch
    INVALID_TARGET = "REVENUE_INVALID_TARGET"
    INVALID_PROPERTY = "REVENUE_INVALID_PROPERTY"
    INVALID_DATA_SOURCE = "REVENUE_INVALID_DATA_SOURCE"
    INVALID_RANGE = "REVENUE_INVALID_RANGE"


class RevenueDecisionError(AppError):
    """A Revenue Decision Detection failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: RevenueErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

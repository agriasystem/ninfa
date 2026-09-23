"""Stable, machine-readable error codes of LABOR_OVERSTAFFING Detection.

Callers branch on the *code*, never on the message. A detector that simply cannot decide (not
enough data, an incomplete plan, ...) does NOT raise: it returns an evaluation whose status says
so. Errors are for requests that cannot be answered at all (an unusable property, booking source,
labor source, target snapshot, or category).
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class LaborDecisionErrorCode(StrEnum):
    INVALID_PROPERTY = "LABOR_DECISION_INVALID_PROPERTY"
    BOOKING_DATA_SOURCE_INVALID = "LABOR_DECISION_BOOKING_DATA_SOURCE_INVALID"
    LABOR_DATA_SOURCE_INVALID = "LABOR_DECISION_LABOR_DATA_SOURCE_INVALID"
    TARGET_NOT_FOUND = "LABOR_DECISION_TARGET_NOT_FOUND"
    TARGET_NOT_OBSERVED = "LABOR_DECISION_TARGET_NOT_OBSERVED"
    INVALID_TARGET = "LABOR_DECISION_INVALID_TARGET"
    INVALID_CATEGORY = "LABOR_DECISION_INVALID_CATEGORY"


class LaborDecisionError(AppError):
    """A LABOR_OVERSTAFFING evaluation failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: LaborDecisionErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

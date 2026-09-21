"""Stable, machine-readable error codes of Cost CPOR Anomaly Detection.

Callers branch on the *code*, never on the message. Messages and details carry ids and reasons
only. A detector that simply cannot decide (not enough data, an incomplete month, ...) does NOT
raise: it returns an evaluation whose status says so. Errors are for requests that cannot be
answered at all (an unusable property or data source, a malformed period, category or currency).
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class CostErrorCode(StrEnum):
    # details.reason: not_found | archived
    INVALID_PROPERTY = "COST_INVALID_PROPERTY"
    # details.reason: not_found | wrong_domain | inactive | property_mismatch
    BOOKING_DATA_SOURCE_INVALID = "COST_BOOKING_DATA_SOURCE_INVALID"
    # details.reason: bad_year | bad_month
    INVALID_PERIOD = "COST_INVALID_PERIOD"
    # a currency is exactly three upper-case letters: there is no conversion and no default
    INVALID_CURRENCY = "COST_INVALID_CURRENCY"
    INVALID_CATEGORY = "COST_INVALID_CATEGORY"


class CostDecisionError(AppError):
    """A Cost Decision Detection failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: CostErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

"""Stable, machine-readable error codes of the booking snapshot services.

Callers branch on the *code*, never on the message. Messages and details carry ids, dates and
constraint-level facts only: never booking content.
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class SnapshotErrorCode(StrEnum):
    # A stored snapshot exists for the same key with different content. It is never updated.
    CONFLICT = "BOOKING_SNAPSHOT_CONFLICT"
    INVALID_PROPERTY = "BOOKING_SNAPSHOT_INVALID_PROPERTY"
    INVALID_DATA_SOURCE = "BOOKING_SNAPSHOT_INVALID_DATA_SOURCE"
    INVALID_RANGE = "BOOKING_SNAPSHOT_INVALID_RANGE"
    # A property-local date that never existed (a calendar day skipped by a time-zone change).
    LOCAL_DATE_DOES_NOT_EXIST = "BOOKING_SNAPSHOT_LOCAL_DATE_DOES_NOT_EXIST"


class SnapshotError(AppError):
    """A booking-snapshot failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: SnapshotErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code

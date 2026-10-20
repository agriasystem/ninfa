"""Stable error codes of the Dati overview API V1.

A well-typed but out-of-contract value is a 400 (like Decision API V1's own semantic rejections);
a structurally malformed one FastAPI cannot coerce (`period=abc`) answers its generic 422. An
unknown, archived or foreign property is the SAME 404 `PROPERTY_NOT_FOUND` every property route
answers (raised by `resolve_property_scope`): distinguishing them would leak which ids exist.
"""

from app.core.exceptions import AppError


class InvalidPeriodError(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_PERIOD", "period must be 7 or 30", status_code=400)


__all__ = ["InvalidPeriodError"]

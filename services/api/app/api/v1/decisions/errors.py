"""Stable, machine-readable error codes of Decision API V1.

Deliberately 400 (not FastAPI/Pydantic's own generic 422 `validation_error`) for every SEMANTIC
query rejection below: a well-typed but out-of-contract value (`limit=0`, `status=BOGUS`, a cursor
that fails to decode). A structurally malformed value FastAPI cannot even coerce (`limit=abc`)
still reaches Pydantic first and answers 422, as it already does everywhere else in this codebase -
see docs/architecture/decision-api-v1.md, "Error contract" for the exact split.
"""

from app.core.exceptions import AppError


class PropertyNotFoundError(AppError):
    """The property does not exist, is archived, or the caller has no membership on its
    workspace - all three are answered identically, on purpose (see ADR 0018)."""

    def __init__(self) -> None:
        super().__init__("PROPERTY_NOT_FOUND", "Property not found", status_code=404)


class DecisionNotFoundError(AppError):
    """The decision does not exist, or belongs to a property/workspace outside the resolved
    tenant scope - answered identically, on purpose (see ADR 0018)."""

    def __init__(self) -> None:
        super().__init__("DECISION_NOT_FOUND", "Decision not found", status_code=404)


class InvalidAsOfDateError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "INVALID_AS_OF_DATE", "as_of must be a valid ISO date (YYYY-MM-DD)", status_code=400
        )


class InvalidDecisionStatusError(AppError):
    def __init__(self, value: str) -> None:
        super().__init__(
            "INVALID_DECISION_STATUS",
            "status must be one of OPEN, RESOLVED",
            status_code=400,
            details={"value": value},
        )


class InvalidDecisionTypeError(AppError):
    def __init__(self, value: str) -> None:
        super().__init__(
            "INVALID_DECISION_TYPE",
            "decision_type is not one of the five MVP decision types",
            status_code=400,
            details={"value": value},
        )


class InvalidCursorError(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_CURSOR", "cursor is malformed or unsupported", status_code=400)


class InvalidLimitError(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_LIMIT", "limit must be between 1 and 100", status_code=400)


__all__ = [
    "DecisionNotFoundError",
    "InvalidAsOfDateError",
    "InvalidCursorError",
    "InvalidDecisionStatusError",
    "InvalidDecisionTypeError",
    "InvalidLimitError",
    "PropertyNotFoundError",
]

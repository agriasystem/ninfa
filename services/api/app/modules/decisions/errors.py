"""Stable, machine-readable error codes of Decision Persistence, Lifecycle and Memory V1.

These are request-level errors (raised as `DecisionError`, never carried by a `Decision` or a
`DecisionObservation`): they mean the SYNC could not be produced at all from its input, exactly
like `PriorityError` means a ranking could not be produced. A non-TRIGGERED evaluation is never an
error: it is read, classified and (if a Decision already exists for its identity) recorded.
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class DecisionErrorCode(StrEnum):
    # Two evaluations mapped to the same identity_key inside one sync but carry different
    # identity_payload bodies: a hash cannot be trusted if it is not collision-free in practice.
    DECISION_IDENTITY_HASH_COLLISION = "DECISION_IDENTITY_HASH_COLLISION"
    # A run tries to move a Decision's lifecycle using an as-of date strictly before its own
    # last_evaluated_local_date: the past is never rewritten (see docs/architecture/decision-
    # layer-v1.md, "Out-of-order history").
    DECISION_OUT_OF_ORDER_RUN = "DECISION_OUT_OF_ORDER_RUN"
    # The PriorityContext/PriorityRankingResult/evaluations passed to DecisionService.sync() are
    # not the coherent output of ONE Priority Engine run: a workspace/property/as-of mismatch, a
    # TRIGGERED evaluation with no matching candidate (or vice versa), or status counts that do
    # not match the logical evaluation set.
    DECISION_PRIORITY_INPUT_MISMATCH = "DECISION_PRIORITY_INPUT_MISMATCH"
    # The same logical decision identity appears twice in one run's source evaluations with two
    # DIFFERENT calculation fingerprints: never resolved arbitrarily (mirrors Gate 10's own
    # PRIORITY_CONFLICTING_SOURCE_EVALUATION, one level up: by Decision identity, not target key).
    DECISION_CONFLICTING_SOURCE_EVALUATION = "DECISION_CONFLICTING_SOURCE_EVALUATION"


class DecisionError(AppError):
    """A Decision Layer sync failure with a stable code and non-sensitive details."""

    def __init__(
        self,
        code: DecisionErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code


__all__ = ["DecisionError", "DecisionErrorCode"]

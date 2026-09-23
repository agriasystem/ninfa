"""Stable error codes for a ranking run that cannot be produced at all.

These are request-level errors (raised as `PriorityError`, never carried by a `PriorityCandidate`
or a `PriorityRankingResult`): they mean the INPUT to the Priority Engine was incoherent, not that
a detector's own evaluation is wrong. A non-TRIGGERED evaluation is never an error — it is simply
excluded and counted (see `service.py`).
"""

from enum import StrEnum


class PriorityErrorCode(StrEnum):
    # A TRIGGERED evaluation whose facts are incoherent with its own status (e.g. REV_PICKUP_LOW
    # TRIGGERED with missing_rooms < 2), a confidence outside 0-100, a confidence below the
    # detector's OWN gate, a malformed/empty fingerprint, an unrecognised evaluation type, or a
    # COST_CPOR_ANOMALY target month that has not yet ended.
    PRIORITY_INVALID_SOURCE_EVALUATION = "PRIORITY_INVALID_SOURCE_EVALUATION"
    # The evaluation's own as-of/snapshot date does not equal PriorityContext.as_of_local_date.
    PRIORITY_AS_OF_MISMATCH = "PRIORITY_AS_OF_MISMATCH"
    # A forward-dated signal (pickup, occupancy, labor) whose target date already lies before the
    # ranking's as-of date (days_to_target < 0).
    PRIORITY_STALE_SOURCE_EVALUATION = "PRIORITY_STALE_SOURCE_EVALUATION"
    # The evaluation's workspace_id differs from PriorityContext.workspace_id.
    PRIORITY_TENANT_MISMATCH = "PRIORITY_TENANT_MISMATCH"
    # The evaluation's property_id differs from PriorityContext.property_id.
    PRIORITY_PROPERTY_MISMATCH = "PRIORITY_PROPERTY_MISMATCH"
    # The same logical source target (decision type + source target key) appears twice in one run
    # with two DIFFERENT calculation fingerprints: never resolved arbitrarily.
    PRIORITY_CONFLICTING_SOURCE_EVALUATION = "PRIORITY_CONFLICTING_SOURCE_EVALUATION"


class PriorityError(Exception):
    """Raised when a ranking run cannot be produced from its input at all."""

    def __init__(self, code: PriorityErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")

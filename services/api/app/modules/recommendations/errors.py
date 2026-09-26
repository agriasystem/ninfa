"""Framework-free exceptions of Recommendation Engine V1.

Distinguish two very different failure shapes on purpose:

* A known decision type with facts that are missing/malformed -> NEVER an exception. The engine
  returns a normal `RecommendationResult` with `status = INSUFFICIENT_CONTEXT`; this is expected,
  recoverable, and still a valid 200 response one layer up (see `docs/architecture/
  recommendation-engine-v1.md`, "Missing or malformed context").
* A `decision_type` the engine has no rule for at all (structurally impossible today - the five
  MVP types are exhaustive - but a genuine integrity violation if it ever happened, e.g. a future
  sixth type added to `PriorityDecisionType` without a matching rule here) -> this exception,
  which the API layer's own generic unhandled-exception handler turns into a fail-closed 500,
  exactly like any other unexpected error in this codebase. The engine itself never decides what
  HTTP status that becomes - it has no HTTP awareness at all.
"""

from app.modules.intelligence.priority.types import PriorityDecisionType


class UnsupportedDecisionTypeError(Exception):
    def __init__(self, decision_type: PriorityDecisionType) -> None:
        super().__init__(f"no recommendation rule exists for decision_type {decision_type!r}")
        self.decision_type = decision_type


__all__ = ["UnsupportedDecisionTypeError"]

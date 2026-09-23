"""Actionability Score V1: how directly a signal can be the object of an operational response.

A FIXED heuristic policy per decision type (`ACTIONABILITY_POLICY_V1`, versioned as
`ACTIONABILITY_POLICY_VERSION`), never a probability and never a formula: V1 has no data yet to
justify computing it from anything. `actionability_score == 90` for `REV_PICKUP_LOW` does not mean
"lower the price" or "run a promotion" - it is a quantitative component only; no action text is
ever generated from it (see the module docstring of `priority/__init__.py`).
"""

from decimal import Decimal

from app.modules.intelligence.priority.types import (
    ACTIONABILITY_POLICY_V1,
    ACTIONABILITY_POLICY_VERSION,
    PriorityDecisionType,
)


def actionability_score(decision_type: PriorityDecisionType) -> Decimal:
    """The fixed V1 policy score (0-100) of one decision type."""
    return ACTIONABILITY_POLICY_V1[decision_type]


def actionability_policy_name() -> str:
    return ACTIONABILITY_POLICY_VERSION

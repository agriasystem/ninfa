"""Priority Score V1: the frozen formula over four already-normalized 0-100 components.

    priority_score = 0.40 * impact + 0.25 * urgency + 0.20 * confidence + 0.15 * actionability

`priority_score_exact` is what the ranking sorts on; `priority_score_display` (HALF_UP, two
decimals) never decides anything, including which of two equal-display candidates ranks first
(see `ranking.py`).
"""

from decimal import Decimal

from app.modules.intelligence.priority.precision import CALCULATION_CONTEXT, for_display
from app.modules.intelligence.priority.types import (
    ACTIONABILITY_WEIGHT,
    CONFIDENCE_WEIGHT,
    IMPACT_WEIGHT,
    URGENCY_WEIGHT,
)


def priority_score_exact(
    *,
    impact_score: Decimal,
    urgency_score: Decimal,
    confidence_score: Decimal,
    actionability_score: Decimal,
) -> Decimal:
    """The full-precision weighted sum, in the dedicated context, never rounded before ranking."""
    weighted_impact = CALCULATION_CONTEXT.multiply(IMPACT_WEIGHT, impact_score)
    weighted_urgency = CALCULATION_CONTEXT.multiply(URGENCY_WEIGHT, urgency_score)
    weighted_confidence = CALCULATION_CONTEXT.multiply(CONFIDENCE_WEIGHT, confidence_score)
    weighted_actionability = CALCULATION_CONTEXT.multiply(ACTIONABILITY_WEIGHT, actionability_score)
    total = CALCULATION_CONTEXT.add(weighted_impact, weighted_urgency)
    total = CALCULATION_CONTEXT.add(total, weighted_confidence)
    return CALCULATION_CONTEXT.add(total, weighted_actionability)


def priority_score_display(exact: Decimal) -> Decimal:
    """The two-decimal, HALF_UP presentation value. Never used to sort or filter."""
    return for_display(exact)

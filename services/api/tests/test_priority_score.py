"""Priority Score V1 at the candidate level: exact formula, exact used for rank (spec part M)."""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import (
    DEFAULT_PROPERTY_ID,
    DEFAULT_WORKSPACE_ID,
    pickup_evaluation,
    pickup_facts,
)

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def test_the_exact_weighted_formula_matches_a_hand_calculation() -> None:
    # impact: abs_delta=40 -> relative 100, missing_rooms=4 -> rooms 100 => impact MIN = 100.
    # urgency: stay_date 7 days out (>=4,<=7) -> 80. confidence: 90. actionability (pickup): 90.
    # priority = 0.40*100 + 0.25*80 + 0.20*90 + 0.15*90 = 40 + 20 + 18 + 13.5 = 91.5
    evaluation = pickup_evaluation(
        snapshot_local_date=_CONTEXT.as_of_local_date,
        stay_date=_CONTEXT.as_of_local_date + timedelta(days=7),
        confidence_score=Decimal(90),
        facts=pickup_facts(missing_rooms=Decimal(4), delta_percent_exact=Decimal("-40.00")),
    )
    result = PriorityService().rank(_CONTEXT, [evaluation])
    candidate = result.ranked_candidates[0].candidate
    assert candidate.impact_score_exact == Decimal(100)
    assert candidate.urgency_score == Decimal(80)
    assert candidate.confidence_score == Decimal(90)
    assert candidate.actionability_score == Decimal(90)
    assert candidate.priority_score_exact == Decimal("91.5")


def test_the_exact_score_never_the_display_score_decides_the_rank() -> None:
    high_exact = pickup_evaluation(
        snapshot_local_date=_CONTEXT.as_of_local_date,
        stay_date=_CONTEXT.as_of_local_date,
        confidence_score=Decimal("80.004"),
        facts=pickup_facts(missing_rooms=Decimal(2), delta_percent_exact=Decimal("-20.00")),
    )
    low_exact = pickup_evaluation(
        snapshot_local_date=_CONTEXT.as_of_local_date,
        stay_date=_CONTEXT.as_of_local_date,
        confidence_score=Decimal("80.000"),
        facts=pickup_facts(missing_rooms=Decimal(2), delta_percent_exact=Decimal("-20.00")),
    )
    result = PriorityService().rank(_CONTEXT, [high_exact, low_exact])
    first, second = (ranked.candidate for ranked in result.ranked_candidates)
    # both display as the same two-decimal figure, yet the higher exact score ranks first.
    assert first.priority_score_display == second.priority_score_display
    assert first.priority_score_exact > second.priority_score_exact

"""Economic proxies travel through as EVIDENCE ONLY, never into the score (spec part S)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.modules.intelligence.priority.ranking import rank_candidates
from app.modules.intelligence.priority.service import PriorityService, SourceEvaluation
from app.modules.intelligence.priority.types import PriorityCandidate, PriorityContext
from tests.priority_support import (
    DEFAULT_PROPERTY_ID,
    DEFAULT_WORKSPACE_ID,
    cost_evaluation,
    labor_evaluation,
    occupancy_evaluation,
    ota_evaluation,
    pickup_evaluation,
)

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def _one_candidate(evaluation: SourceEvaluation) -> PriorityCandidate:
    result = PriorityService().rank(_CONTEXT, [evaluation])
    return result.ranked_candidates[0].candidate


def test_pickup_revenue_gap_proxy_is_propagated_as_evidence() -> None:
    evaluation = pickup_evaluation(revenue_gap_proxy=Decimal("450.00"))
    candidate = _one_candidate(evaluation)
    assert candidate.economic_proxy_exact == Decimal("450.00")
    assert candidate.economic_proxy_label == "REVENUE_GAP_PROXY"


def test_occupancy_revenue_gap_proxy_is_propagated_as_evidence() -> None:
    evaluation = occupancy_evaluation(revenue_gap_proxy=Decimal("600.00"))
    candidate = _one_candidate(evaluation)
    assert candidate.economic_proxy_exact == Decimal("600.00")
    assert candidate.economic_proxy_label == "REVENUE_GAP_PROXY"


def test_cost_gap_proxy_is_propagated_with_its_currency() -> None:
    evaluation = cost_evaluation(cost_gap_proxy_exact=Decimal("1100.00"), currency="EUR")
    candidate = _one_candidate(evaluation)
    assert candidate.economic_proxy_exact == Decimal("1100.00")
    assert candidate.economic_proxy_currency == "EUR"
    assert candidate.economic_proxy_label == "COST_GAP_PROXY"


def test_labor_cost_gap_proxy_is_propagated_with_its_currency() -> None:
    evaluation = labor_evaluation(labor_cost_gap_proxy_exact=Decimal("200.00"), cost_currency="EUR")
    candidate = _one_candidate(evaluation)
    assert candidate.economic_proxy_exact == Decimal("200.00")
    assert candidate.economic_proxy_currency == "EUR"
    assert candidate.economic_proxy_label == "LABOR_COST_GAP_PROXY"


def test_ota_revenue_exposure_is_optional_and_absent_is_fine() -> None:
    proxy = Decimal("1200.00")
    with_exposure = _one_candidate(ota_evaluation(ota_room_revenue_on_books_exact=proxy))
    assert with_exposure.economic_proxy_exact == Decimal("1200.00")
    assert with_exposure.economic_proxy_label == "OTA_ROOM_REVENUE_EXPOSURE"

    without_exposure = _one_candidate(ota_evaluation(ota_room_revenue_on_books_exact=None))
    assert without_exposure.economic_proxy_exact is None
    assert without_exposure.economic_proxy_label is None


def test_the_proxy_never_changes_the_priority_score() -> None:
    cheap = cost_evaluation(cost_gap_proxy_exact=Decimal("100.00"))
    expensive = cost_evaluation(cost_gap_proxy_exact=Decimal("999999.00"))
    cheap_candidate = _one_candidate(cheap)
    expensive_candidate = _one_candidate(expensive)
    assert cheap_candidate.impact_score_exact == expensive_candidate.impact_score_exact
    assert cheap_candidate.priority_score_exact == expensive_candidate.priority_score_exact


def test_revenue_and_ota_evaluations_carry_no_currency_string_never_invented() -> None:
    # Neither Booking nor RevenueDecisionEvaluation/OtaDependencyEvaluation carries a currency
    # column: the priority engine must never invent one, so it leaves it None rather than guess.
    pickup_candidate = _one_candidate(pickup_evaluation())
    ota_candidate = _one_candidate(ota_evaluation())
    assert pickup_candidate.economic_proxy_currency is None
    assert ota_candidate.economic_proxy_currency is None


def test_two_candidates_of_different_currencies_are_never_compared_by_their_proxy() -> None:
    # Same decision type (so the decision-type tie-break cannot interfere) and identical scores
    # on both candidates (so the tie-break chain, never the proxy, decides the order), but one's
    # proxy is EUR-and-tiny and the other's is USD-and-enormous.
    eur_candidate = _one_candidate(
        cost_evaluation(currency="EUR", cost_gap_proxy_exact=Decimal("1.00"))
    )
    usd_candidate = _one_candidate(
        cost_evaluation(currency="USD", cost_gap_proxy_exact=Decimal("999999999.00"))
    )
    tied_score = Decimal(50)
    tied_eur = replace(
        eur_candidate,
        impact_score_exact=tied_score,
        urgency_score=tied_score,
        confidence_score=tied_score,
        actionability_score=tied_score,
        priority_score_exact=tied_score,
        source_target_key="a",
    )
    tied_usd = replace(
        usd_candidate,
        impact_score_exact=tied_score,
        urgency_score=tied_score,
        confidence_score=tied_score,
        actionability_score=tied_score,
        priority_score_exact=tied_score,
        source_target_key="b",
    )
    ranked = rank_candidates([tied_usd, tied_eur])
    # the order is decided by source_target_key ("a" before "b"), NOT by the proxy magnitude.
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]

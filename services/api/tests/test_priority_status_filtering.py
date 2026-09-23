"""Only TRIGGERED becomes a candidate; every other status is excluded and counted, never scored
(spec part N). SUPPRESSED_LOW_CONFIDENCE is never "resuscitated" by the Priority Engine."""

from datetime import date
from decimal import Decimal

from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import (
    CLEAR,
    DEFAULT_PROPERTY_ID,
    DEFAULT_WORKSPACE_ID,
    INSUFFICIENT_DATA,
    NOT_APPLICABLE,
    SUPPRESSED_LOW_CONFIDENCE,
    TRIGGERED,
    pickup_evaluation,
    pickup_facts,
)

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def test_a_triggered_evaluation_becomes_one_candidate() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation(status=TRIGGERED)])
    assert result.candidate_count == 1
    assert len(result.ranked_candidates) == 1


def test_a_clear_evaluation_is_excluded_and_counted() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation(status=CLEAR)])
    assert result.candidate_count == 0
    assert result.excluded_clear_count == 1
    assert result.ranked_candidates == ()


def test_an_insufficient_data_evaluation_is_excluded_and_counted() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation(status=INSUFFICIENT_DATA)])
    assert result.candidate_count == 0
    assert result.excluded_insufficient_count == 1


def test_a_not_applicable_evaluation_is_excluded_and_counted() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation(status=NOT_APPLICABLE)])
    assert result.candidate_count == 0
    assert result.excluded_not_applicable_count == 1


def test_a_suppressed_low_confidence_evaluation_is_excluded_never_resuscitated() -> None:
    # Even one with a huge impact-shaped delta must NOT become a candidate: status alone decides.
    evaluation = pickup_evaluation(
        status=SUPPRESSED_LOW_CONFIDENCE,
        facts=pickup_facts(missing_rooms=Decimal(100), delta_percent_exact=Decimal(-99)),
    )
    result = PriorityService().rank(_CONTEXT, [evaluation])
    assert result.candidate_count == 0
    assert result.excluded_suppressed_count == 1
    assert result.ranked_candidates == ()


def test_all_five_exclusion_counts_are_correct_together() -> None:
    evaluations = [
        pickup_evaluation(status=TRIGGERED),
        pickup_evaluation(status=CLEAR),
        pickup_evaluation(status=CLEAR),
        pickup_evaluation(status=INSUFFICIENT_DATA),
        pickup_evaluation(status=NOT_APPLICABLE),
        pickup_evaluation(status=SUPPRESSED_LOW_CONFIDENCE),
        pickup_evaluation(status=SUPPRESSED_LOW_CONFIDENCE),
        pickup_evaluation(status=SUPPRESSED_LOW_CONFIDENCE),
    ]
    result = PriorityService().rank(_CONTEXT, evaluations)
    assert result.candidate_count == 1
    assert result.excluded_clear_count == 2
    assert result.excluded_insufficient_count == 1
    assert result.excluded_not_applicable_count == 1
    assert result.excluded_suppressed_count == 3


def test_no_triggered_signals_gives_an_empty_ranking_never_a_fabricated_all_clear() -> None:
    result = PriorityService().rank(
        _CONTEXT,
        [pickup_evaluation(status=CLEAR), pickup_evaluation(status=NOT_APPLICABLE)],
    )
    assert result.candidate_count == 0
    assert result.ranked_candidates == ()
    # nothing here generates any text; the result is plain, empty data.
    assert isinstance(result.ranked_candidates, tuple)

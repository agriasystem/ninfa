"""Deterministic SHA-256 fingerprints of a candidate and of a whole ranking result (spec part R)."""

import inspect
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.modules.intelligence.priority.fingerprint import candidate_fingerprint
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from tests.priority_support import DEFAULT_PROPERTY_ID, DEFAULT_WORKSPACE_ID, pickup_evaluation

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def _fingerprint(**overrides: object) -> str:
    base: dict[str, object] = {
        "decision_type": PriorityDecisionType.REV_PICKUP_LOW,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "property_id": DEFAULT_PROPERTY_ID,
        "priority_as_of_date": date(2026, 9, 1),
        "source_evaluation_fingerprint": "source-fp",
        "source_target_key": "target-key",
        "impact_score_exact": Decimal(50),
        "urgency_score": Decimal(50),
        "confidence_score": Decimal(50),
        "actionability_score": Decimal(90),
        "priority_score_exact": Decimal("57.5"),
        "impact_basis": {"delta": Decimal(1)},
        "urgency_basis": {"days": 3},
        "source_reason_codes": ("TRIGGER_PICKUP_SHORTFALL",),
        "priority_version": "priority-engine-v1",
    }
    base.update(overrides)
    return candidate_fingerprint(**base)  # type: ignore[arg-type]


def test_the_same_candidate_gives_the_same_fingerprint() -> None:
    assert _fingerprint() == _fingerprint()


def test_a_changed_exact_score_changes_the_fingerprint() -> None:
    assert _fingerprint() != _fingerprint(priority_score_exact=Decimal("57.51"))


def test_a_changed_as_of_date_changes_the_fingerprint() -> None:
    assert _fingerprint() != _fingerprint(priority_as_of_date=date(2026, 9, 2))


def test_two_exact_scores_with_the_same_two_decimal_display_never_share_a_fingerprint() -> None:
    # 57.504 and 57.500 both display as "57.50", but the fingerprint hashes the EXACT value.
    assert _fingerprint(priority_score_exact=Decimal("57.504")) != _fingerprint(
        priority_score_exact=Decimal("57.500")
    )


def test_the_fingerprint_function_takes_no_clock_or_timestamp_input() -> None:
    parameters = set(inspect.signature(candidate_fingerprint).parameters)
    assert not {"timestamp", "now", "created_at", "as_of_at"} & parameters
    # calling it twice, arbitrarily far apart in real time, gives the identical result.
    assert _fingerprint() == _fingerprint()


def test_the_same_logical_set_of_evaluations_gives_the_same_ranking_fingerprint_in_any_order() -> (
    None
):
    first = pickup_evaluation(target_snapshot_id=uuid4())
    second = pickup_evaluation(target_snapshot_id=uuid4())
    forward = PriorityService().rank(_CONTEXT, [first, second])
    backward = PriorityService().rank(_CONTEXT, [second, first])
    assert forward.calculation_fingerprint == backward.calculation_fingerprint
    assert forward.calculation_fingerprint != ""


def test_a_different_evaluation_changes_the_ranking_fingerprint() -> None:
    evaluation = pickup_evaluation(target_snapshot_id=uuid4())
    other_evaluation = pickup_evaluation(target_snapshot_id=uuid4())
    result_one = PriorityService().rank(_CONTEXT, [evaluation])
    result_two = PriorityService().rank(_CONTEXT, [other_evaluation])
    assert result_one.calculation_fingerprint != result_two.calculation_fingerprint

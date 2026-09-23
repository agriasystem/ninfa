"""Confidence component: EXACTLY the detector's own final confidence, never recomputed, never
averaged (spec part L)."""

from decimal import Decimal

import pytest

from app.modules.intelligence.priority.adapters import (
    adapt_cost,
    adapt_labor,
    adapt_occupancy,
    adapt_ota,
    adapt_pickup,
)
from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import (
    cost_evaluation,
    labor_evaluation,
    occupancy_evaluation,
    ota_evaluation,
    pickup_evaluation,
)


def test_pickup_confidence_is_reused_exactly_not_transformed() -> None:
    evaluation = pickup_evaluation(confidence_score=Decimal("73.42"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    signal = adapt_pickup(context, evaluation)
    assert signal.confidence_score == Decimal("73.42")


def test_occupancy_confidence_is_reused_exactly() -> None:
    evaluation = occupancy_evaluation(confidence_score=Decimal("91.10"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    signal = adapt_occupancy(context, evaluation)
    assert signal.confidence_score == Decimal("91.10")


def test_no_component_of_confidence_is_averaged_with_anything_else() -> None:
    # The adapted signal's confidence_score is bit-for-bit the source evaluation's own value,
    # independent of impact/urgency (which are computed from entirely different facts).
    evaluation = labor_evaluation(confidence_score=Decimal("61.00"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.target_as_of_date
    )
    signal = adapt_labor(context, evaluation)
    assert signal.confidence_score == evaluation.confidence_score == Decimal("61.00")


def test_a_confidence_above_a_hundred_is_rejected() -> None:
    evaluation = pickup_evaluation(confidence_score=Decimal("150"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    with pytest.raises(PriorityError) as excinfo:
        adapt_pickup(context, evaluation)
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_INVALID_SOURCE_EVALUATION


def test_a_negative_confidence_is_rejected() -> None:
    evaluation = pickup_evaluation(confidence_score=Decimal("-1"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    with pytest.raises(PriorityError) as excinfo:
        adapt_pickup(context, evaluation)
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_INVALID_SOURCE_EVALUATION


def test_triggered_below_the_detectors_own_gate_is_rejected() -> None:
    # REV_OCCUPANCY_RISK's own gate is 55: a TRIGGERED evaluation below it is incoherent.
    evaluation = occupancy_evaluation(confidence_score=Decimal("54.99"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    with pytest.raises(PriorityError) as excinfo:
        adapt_occupancy(context, evaluation)
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_INVALID_SOURCE_EVALUATION


def test_triggered_at_exactly_the_detectors_own_gate_is_accepted() -> None:
    evaluation = occupancy_evaluation(confidence_score=Decimal("55.00"))
    context = PriorityContext(
        evaluation.workspace_id, evaluation.property_id, evaluation.snapshot_local_date
    )
    signal = adapt_occupancy(context, evaluation)
    assert signal.confidence_score == Decimal("55.00")


def test_cost_and_ota_and_labor_also_enforce_their_own_gate_of_fifty_five() -> None:
    cost = cost_evaluation(confidence_score=Decimal("54"))
    cost_context = PriorityContext(cost.workspace_id, cost.property_id, cost.target_period_end)
    with pytest.raises(PriorityError):
        adapt_cost(cost_context, cost)

    ota = ota_evaluation(confidence_score=Decimal("54"))
    ota_context = PriorityContext(ota.workspace_id, ota.property_id, ota.as_of_local_date)
    with pytest.raises(PriorityError):
        adapt_ota(ota_context, ota)

    labor = labor_evaluation(confidence_score=Decimal("54"))
    labor_context = PriorityContext(labor.workspace_id, labor.property_id, labor.target_as_of_date)
    with pytest.raises(PriorityError):
        adapt_labor(labor_context, labor)

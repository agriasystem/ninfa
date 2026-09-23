"""Duplicate and conflicting source evaluations within one ranking run (spec part P)."""

from datetime import date
from uuid import uuid4

import pytest

from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import (
    DEFAULT_PROPERTY_ID,
    DEFAULT_WORKSPACE_ID,
    occupancy_evaluation,
    pickup_evaluation,
)

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def test_an_identical_fingerprint_seen_twice_collapses_to_one_candidate() -> None:
    snapshot_id = uuid4()
    evaluation = pickup_evaluation(
        target_snapshot_id=snapshot_id, calculation_fingerprint="same-fingerprint"
    )
    result = PriorityService().rank(_CONTEXT, [evaluation, evaluation])
    assert result.candidate_count == 1


def test_the_duplicate_input_count_increments() -> None:
    snapshot_id = uuid4()
    evaluation = pickup_evaluation(
        target_snapshot_id=snapshot_id, calculation_fingerprint="same-fingerprint"
    )
    result = PriorityService().rank(_CONTEXT, [evaluation, evaluation, evaluation])
    assert result.candidate_count == 1
    assert result.duplicate_input_count == 2


def test_the_same_logical_target_with_a_different_fingerprint_is_a_conflict() -> None:
    snapshot_id = uuid4()
    first = pickup_evaluation(
        target_snapshot_id=snapshot_id, calculation_fingerprint="fingerprint-a"
    )
    second = pickup_evaluation(
        target_snapshot_id=snapshot_id, calculation_fingerprint="fingerprint-b"
    )
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [first, second])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_CONFLICTING_SOURCE_EVALUATION


def test_two_different_decision_types_on_the_same_stay_date_are_never_merged() -> None:
    snapshot_id = uuid4()
    pickup = pickup_evaluation(target_snapshot_id=snapshot_id)
    occupancy = occupancy_evaluation(target_snapshot_id=snapshot_id)
    result = PriorityService().rank(_CONTEXT, [pickup, occupancy])
    assert result.candidate_count == 2
    assert result.duplicate_input_count == 0

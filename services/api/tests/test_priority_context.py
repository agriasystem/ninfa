"""PriorityContext scoping and as-of coherence: one property, one workspace, one explicit date,
never a clock (spec part O)."""

import ast
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

import app.modules.intelligence.priority as priority_package
from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import (
    DEFAULT_PROPERTY_ID,
    DEFAULT_WORKSPACE_ID,
    OTHER_PROPERTY_ID,
    OTHER_WORKSPACE_ID,
    labor_evaluation,
    ota_evaluation,
    pickup_evaluation,
)

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def test_an_evaluation_of_the_same_workspace_and_property_passes() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation()])
    assert result.candidate_count == 1


def test_a_cross_workspace_evaluation_is_rejected() -> None:
    evaluation = pickup_evaluation(workspace_id=OTHER_WORKSPACE_ID)
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [evaluation])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_TENANT_MISMATCH


def test_an_evaluation_of_the_same_property_passes() -> None:
    result = PriorityService().rank(_CONTEXT, [pickup_evaluation(property_id=DEFAULT_PROPERTY_ID)])
    assert result.candidate_count == 1


def test_a_cross_property_evaluation_is_rejected() -> None:
    evaluation = pickup_evaluation(property_id=OTHER_PROPERTY_ID)
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [evaluation])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_PROPERTY_MISMATCH


def test_a_revenue_as_of_mismatch_is_rejected() -> None:
    evaluation = pickup_evaluation(snapshot_local_date=date(2026, 8, 31))  # != context as-of
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [evaluation])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_AS_OF_MISMATCH


def test_a_labor_as_of_mismatch_is_rejected() -> None:
    evaluation = labor_evaluation(target_as_of_date=date(2026, 8, 31))
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [evaluation])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_AS_OF_MISMATCH


def test_an_ota_as_of_mismatch_is_rejected() -> None:
    evaluation = ota_evaluation(as_of_local_date=date(2026, 8, 31))
    with pytest.raises(PriorityError) as excinfo:
        PriorityService().rank(_CONTEXT, [evaluation])
    assert excinfo.value.code == PriorityErrorCode.PRIORITY_AS_OF_MISMATCH


def test_a_historical_replay_works_with_an_explicit_earlier_date() -> None:
    replay_date = date(2025, 1, 15)
    replay_context = PriorityContext(uuid4(), uuid4(), replay_date)
    evaluation = pickup_evaluation(
        workspace_id=replay_context.workspace_id,
        property_id=replay_context.property_id,
        snapshot_local_date=replay_date,
        stay_date=replay_date,
    )
    result = PriorityService().rank(replay_context, [evaluation])
    assert result.as_of_local_date == replay_date
    assert result.candidate_count == 1


def test_the_priority_engine_never_calls_the_clock() -> None:
    # AST-based, not substring-based (this very module's own docstrings mention "date.today()"
    # while explaining it is forbidden, which would false-positive a plain text search).
    package_dir = Path(priority_package.__file__).parent
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        clock_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"today", "now", "utcnow"}
        ]
        assert clock_calls == [], f"clock call found in {source.name}: {clock_calls}"

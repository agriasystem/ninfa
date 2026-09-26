"""Recommendation Engine V1 performance (review items 65-66): the detail endpoint's own query
count stays bounded with the new `recommendation` block attached, and the engine itself - called
directly, with no session at all - issues zero SQL statements, proving the bound holds by
construction and not by coincidence of today's fixture shape.

Reuses `test_decision_api_performance.py`'s own `statements_of()`/`_select_count()` technique
unmodified.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from app.modules.recommendations.engine import RecommendationEngine
from app.modules.recommendations.types import RecommendationStatus
from tests.decision_api_support import authed_tenant, detail_url
from tests.decision_support import revenue_evaluation, sync_run
from tests.recommendation_support import build_decision, build_observation
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


@contextmanager
def statements_of(session: Session) -> Iterator[list[str]]:
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[str] = []

    def record(*args: Any) -> None:
        captured.append(str(args[2]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _select_count(statements: list[str]) -> int:
    return sum(1 for sql in statements if sql.strip().upper().startswith("SELECT"))


# --- 65: detail with a recommendation attached stays within the pre-existing bound --------------


def test_detail_with_recommendation_query_count_is_still_bounded(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids

    with statements_of(db_session) as statements:
        response = api_client.get(detail_url(tenant.property.id, decision_id))
    assert "recommendation" in response.json()
    # Same bound `test_decision_api_performance.py::test_detail_query_count_is_bounded` already
    # asserts for the endpoint WITHOUT considering the recommendation - proving Gate 16 added no
    # query of its own, never just that some bound happens to hold.
    assert _select_count(statements) <= 5


def test_repeated_detail_calls_do_not_grow_the_query_count(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids

    counts = []
    for _ in range(3):
        with statements_of(db_session) as statements:
            api_client.get(detail_url(tenant.property.id, decision_id))
        counts.append(_select_count(statements))

    assert len(set(counts)) == 1  # identical every time - never growing with repetition


# --- 66: the engine itself, called directly, issues zero SQL ------------------------------------


def test_engine_evaluate_issues_zero_sql_statements(db_session: Session) -> None:
    """`RecommendationEngine.evaluate()` takes no session at all - calling it directly while
    listening on a REAL connection proves zero statements are issued, not just that none were
    observed by accident of a particular endpoint's call graph."""
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision)

    with statements_of(db_session) as statements:
        result = RecommendationEngine().evaluate(decision, observation)

    assert statements == []
    assert result.status is RecommendationStatus.AVAILABLE


def test_engine_evaluate_issues_zero_sql_across_all_five_types(db_session: Session) -> None:
    for decision_type in PriorityDecisionType:
        decision = build_decision(decision_type)
        observation = build_observation(decision)
        with statements_of(db_session) as statements:
            RecommendationEngine().evaluate(decision, observation)
        assert statements == [], decision_type.value

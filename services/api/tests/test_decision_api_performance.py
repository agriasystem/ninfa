"""Decision API V1: bounded query counts, no N+1 (Gate 12 review items 110-115)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import authed_tenant, detail_url, feed_url, history_url, list_url
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"
STAY_BASE = date(2026, 9, 1)


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


def _n_open_decisions(db_session: Session, tenant: Tenant, n: int) -> None:
    evaluations = [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY_BASE + timedelta(days=index),
            snapshot_local_date=D1,
        )
        for index in range(n)
    ]
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


# --- 110: feed bounded, 1 vs 50 ----------------------------------------------------------------


def test_feed_query_count_is_bounded_not_linear(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    small = authed_tenant(factory, authenticated_as)
    _n_open_decisions(db_session, small.tenant, 1)
    with statements_of(db_session) as small_statements:
        api_client.get(feed_url(small.tenant.property.id, D1_ISO))
    small_selects = _select_count(small_statements)

    large_tenant = factory.tenant()
    factory.membership(large_tenant.workspace, small.user)
    _n_open_decisions(db_session, large_tenant, 50)
    with statements_of(db_session) as large_statements:
        api_client.get(feed_url(large_tenant.property.id, D1_ISO))
    large_selects = _select_count(large_statements)

    assert large_selects <= small_selects + 1
    assert large_selects <= 6


# --- 111: list bounded, 5 vs 50 -----------------------------------------------------------------


def test_list_query_count_is_bounded_not_linear(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    small = authed_tenant(factory, authenticated_as)
    _n_open_decisions(db_session, small.tenant, 5)
    with statements_of(db_session) as small_statements:
        api_client.get(list_url(small.tenant.property.id, limit="50"))
    small_selects = _select_count(small_statements)

    large_tenant = factory.tenant()
    factory.membership(large_tenant.workspace, small.user)
    _n_open_decisions(db_session, large_tenant, 50)
    with statements_of(db_session) as large_statements:
        api_client.get(list_url(large_tenant.property.id, limit="50"))
    large_selects = _select_count(large_statements)

    assert large_selects <= small_selects + 1  # 114: no SELECT per decision
    assert large_selects <= 6


# --- 112: detail bounded --------------------------------------------------------------------


def test_detail_query_count_is_bounded(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    evaluation = revenue_evaluation(
        workspace_id=at.tenant.workspace.id,
        property_id=at.tenant.property.id,
        data_source_id=at.tenant.data_source.id,
        stay_date=STAY_BASE,
        snapshot_local_date=D1,
    )
    context = PriorityContext(at.tenant.workspace.id, at.tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(at.tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids

    with statements_of(db_session) as statements:
        api_client.get(detail_url(at.tenant.property.id, decision_id))
    assert _select_count(statements) <= 5


# --- 113, 115: history bounded, no SELECT per observation ---------------------------------------


def test_history_query_count_is_bounded_not_linear_in_observation_count(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    decision_id: UUID | None = None
    for offset in range(6):
        as_of = D1 + timedelta(days=7 * offset)
        evaluation = revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY_BASE,
            snapshot_local_date=as_of,
        )
        context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
        outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
        if decision_id is None:
            [decision_id] = outcome.result.touched_decision_ids
    assert decision_id is not None

    with statements_of(db_session) as statements:
        response = api_client.get(history_url(tenant.property.id, decision_id))
    assert len(response.json()["items"]) == 6
    assert _select_count(statements) <= 5  # bounded: authorization + one history query

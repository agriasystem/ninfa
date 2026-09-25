"""Set-based retrieval, no N+1 (tests 134-137)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

STAY_BASE = date(2026, 9, 1)
D1 = date(2026, 8, 1)


@contextmanager
def statements_of(session: Session) -> Iterator[list[tuple[str, Any]]]:
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[tuple[str, Any]] = []

    def record(*args: Any) -> None:
        captured.append((str(args[2]), args[3]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _select_count(statements: list[tuple[str, Any]]) -> int:
    return sum(1 for sql, _ in statements if sql.strip().upper().startswith("SELECT"))


def _n_evaluations(tenant: Tenant, n: int, as_of: date) -> list[RevenueDecisionEvaluation]:
    return [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY_BASE + timedelta(days=index),
            snapshot_local_date=as_of,
        )
        for index in range(n)
    ]


def test_existing_decisions_are_loaded_with_one_set_based_select(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    evaluations = _n_evaluations(tenant, 10, D1)
    sync_run(db_session, tenant_ctx, context, evaluations)  # day 1: opens 10 Decisions

    day2_evaluations = _n_evaluations(tenant, 10, D1 + timedelta(days=7))
    context2 = PriorityContext(tenant.workspace.id, tenant.property.id, D1 + timedelta(days=7))
    with statements_of(db_session) as statements:
        sync_run(db_session, tenant_ctx, context2, day2_evaluations)

    # exactly ONE SELECT reads the existing Decisions of all 10 identities (plus the idempotency
    # check's own SELECT and the final open-count SELECT: a small, N-INDEPENDENT constant, never
    # one SELECT per evaluation).
    assert _select_count(statements) <= 4


def test_no_select_per_evaluation_the_count_is_bounded_not_linear(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)

    small = _n_evaluations(tenant, 5, D1)
    with statements_of(db_session) as small_statements:
        sync_run(
            db_session,
            tenant_ctx,
            PriorityContext(tenant.workspace.id, tenant.property.id, D1),
            small,
        )

    tenant2 = factory.tenant()
    large = _n_evaluations(tenant2, 50, D1)
    with statements_of(db_session) as large_statements:
        sync_run(
            db_session,
            TenantContext(tenant2.workspace.id),
            PriorityContext(tenant2.workspace.id, tenant2.property.id, D1),
            large,
        )

    small_selects = _select_count(small_statements)
    large_selects = _select_count(large_statements)
    # 50 identities is 10x more than 5: a per-evaluation SELECT would show a ~10x jump. The
    # bounded, set-based design shows (at most) the same tiny constant either way.
    assert large_selects <= small_selects + 1
    assert large_selects <= 4


def test_history_read_is_one_query_not_one_per_observation(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    stay = STAY_BASE
    decision_id: UUID | None = None
    for offset in range(6):
        as_of = D1 + timedelta(days=7 * offset)
        evaluation = revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=stay,
            snapshot_local_date=as_of,
        )
        context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
        result = sync_run(db_session, tenant_ctx, context, [evaluation]).result
        if decision_id is None:
            [decision_id] = result.touched_decision_ids
    assert decision_id is not None

    memory = DecisionMemoryService(db_session, tenant_ctx)
    with statements_of(db_session) as statements:
        history = memory.get_history(decision_id)

    assert len(history) == 6
    assert _select_count(statements) == 1

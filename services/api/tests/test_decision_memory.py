"""DecisionMemoryService: chronological history, priority history, and tenant/property
isolation (tests 96-105)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionSyncResult, LifecycleTransition
from app.modules.intelligence.priority.types import (
    PriorityContext,
    PriorityRankingResult,
    RankedPriorityCandidate,
)
from app.modules.intelligence.revenue.types import EvaluationStatus, RevenueDecisionEvaluation
from tests.decision_support import CLEAR, TRIGGERED, candidate_for, fp, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
D2 = date(2026, 8, 2)
D3 = date(2026, 8, 3)
STAY = date(2026, 8, 15)


def _pickup(
    tenant: Tenant,
    as_of: date,
    status: EvaluationStatus | None = None,
    fingerprint: str | None = None,
) -> RevenueDecisionEvaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=as_of,
        status=status or TRIGGERED,
        fingerprint=fingerprint,
    )


def _sync_with_rank(
    db_session: Session,
    tenant: Tenant,
    as_of: date,
    evaluation: RevenueDecisionEvaluation,
    *,
    impact: Decimal,
) -> DecisionSyncResult:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    candidate = candidate_for(evaluation, impact=impact)
    ranking = PriorityRankingResult(
        workspace_id=context.workspace_id,
        property_id=context.property_id,
        as_of_local_date=context.as_of_local_date,
        candidate_count=1,
        excluded_clear_count=0,
        excluded_insufficient_count=0,
        excluded_not_applicable_count=0,
        excluded_suppressed_count=0,
        duplicate_input_count=0,
        ranked_candidates=(RankedPriorityCandidate(1, candidate),),
        calculation_fingerprint=fp(f"rank:{as_of.isoformat()}"),
    )
    return DecisionService(db_session, TenantContext(tenant.workspace.id)).sync(
        context, ranking, [evaluation]
    )


def test_history_returns_observations_in_chronological_order(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    day1 = sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    ).result
    [decision_id] = day1.touched_decision_ids
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2)],
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D3),
        [_pickup(tenant, D3, status=CLEAR)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    history = memory.get_history(decision_id)
    assert [o.as_of_local_date for o in history] == [D1, D2, D3]
    assert [o.lifecycle_transition for o in history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.OBSERVED,
        LifecycleTransition.RESOLVED,
    ]


def test_first_day_facts_are_retained_after_later_updates(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    day1_eval = _pickup(tenant, D1)
    day1 = sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [day1_eval],
    ).result
    [decision_id] = day1.touched_decision_ids
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    history = memory.get_history(decision_id)
    assert history[0].facts_payload["stay_date"] == "2026-08-15"
    assert history[0].source_evaluation_fingerprint == day1_eval.calculation_fingerprint
    assert history[0].as_of_local_date == D1  # untouched by day 2's own observation


def test_previous_priority_rank_is_retained_after_a_rank_change(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    day1_eval = _pickup(tenant, D1)
    day1 = _sync_with_rank(db_session, tenant, D1, day1_eval, impact=Decimal("90.00"))
    [decision_id] = day1.touched_decision_ids

    day2_eval = _pickup(tenant, D2)
    _sync_with_rank(db_session, tenant, D2, day2_eval, impact=Decimal("10.00"))

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    history = memory.get_history(decision_id)
    assert history[0].impact_score == Decimal("90.00")
    assert history[1].impact_score == Decimal("10.00")  # day 1's own value is never overwritten


def test_resolution_observation_is_retained(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    day1 = sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    ).result
    [decision_id] = day1.touched_decision_ids
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2, status=CLEAR)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    history = memory.get_history(decision_id)
    resolved = [o for o in history if o.lifecycle_transition == LifecycleTransition.RESOLVED]
    assert len(resolved) == 1
    assert resolved[0].as_of_local_date == D2


def test_reopen_observation_is_retained(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    day1 = sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    ).result
    [decision_id] = day1.touched_decision_ids
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2, status=CLEAR)],
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D3),
        [_pickup(tenant, D3)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    history = memory.get_history(decision_id)
    assert [o.lifecycle_transition for o in history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.RESOLVED,
        LifecycleTransition.REOPENED,
    ]


def test_list_open_excludes_a_resolved_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2, status=CLEAR)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    assert memory.list_open_decisions(tenant.property.id) == []


def test_list_open_includes_a_reopened_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D2),
        [_pickup(tenant, D2, status=CLEAR)],
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D3),
        [_pickup(tenant, D3)],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    [decision] = memory.list_open_decisions(tenant.property.id)
    assert decision.episode_count == 2


def test_decision_memory_is_isolated_per_tenant(
    db_session: Session, factory: BookingFactory
) -> None:
    a, b = factory.tenant(), factory.tenant()
    sync_run(
        db_session,
        TenantContext(a.workspace.id),
        PriorityContext(a.workspace.id, a.property.id, D1),
        [_pickup(a, D1)],
    )
    sync_run(
        db_session,
        TenantContext(b.workspace.id),
        PriorityContext(b.workspace.id, b.property.id, D1),
        [_pickup(b, D1)],
    )
    memory_a = DecisionMemoryService(db_session, TenantContext(a.workspace.id))
    memory_b = DecisionMemoryService(db_session, TenantContext(b.workspace.id))
    assert len(memory_a.list_open_decisions(a.property.id)) == 1
    assert len(memory_b.list_open_decisions(b.property.id)) == 1
    # a's decision does not exist for b's tenant context (belongs to another workspace)
    [decision_a] = memory_a.list_open_decisions(a.property.id)
    assert memory_b.get_decision(decision_a.id) is None


def test_decision_memory_is_isolated_per_property(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    other_property = factory.property(tenant.workspace)
    other_source = factory.data_source(other_property)
    tenant_ctx = TenantContext(tenant.workspace.id)

    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, tenant.property.id, D1),
        [_pickup(tenant, D1)],
    )
    other_eval = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=other_property.id,
        data_source_id=other_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(tenant.workspace.id, other_property.id, D1),
        [other_eval],
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    assert len(memory.list_open_decisions(tenant.property.id)) == 1
    assert len(memory.list_open_decisions(other_property.id)) == 1


def test_get_decision_of_another_workspace_is_not_found(
    db_session: Session, factory: BookingFactory
) -> None:
    owner, stranger = factory.tenant(), factory.tenant()
    tenant_ctx = TenantContext(owner.workspace.id)
    result = sync_run(
        db_session,
        tenant_ctx,
        PriorityContext(owner.workspace.id, owner.property.id, D1),
        [_pickup(owner, D1)],
    ).result
    [decision_id] = result.touched_decision_ids

    stranger_memory = DecisionMemoryService(db_session, TenantContext(stranger.workspace.id))
    assert stranger_memory.get_decision(decision_id) is None
    assert stranger_memory.get_history(decision_id) == []

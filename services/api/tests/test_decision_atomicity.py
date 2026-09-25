"""Atomicity: a Decision sync is ALL OR NOTHING (tests 124-129)."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.errors import DecisionError
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.service import DecisionService
from app.modules.intelligence.priority.types import (
    PriorityContext,
    PriorityRankingResult,
    RankedPriorityCandidate,
)
from tests.decision_support import (
    candidate_for,
    cost_evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
D2 = date(2026, 8, 2)
STAY = date(2026, 8, 15)


def _row_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (DecisionRun, Decision, DecisionObservation)
    }


def test_one_invalid_evaluation_among_many_rolls_back_the_whole_run(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    good = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    foreign = cost_evaluation(  # belongs to a DIFFERENT workspace: makes the whole batch invalid
        workspace_id=uuid4(),
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    before = _row_counts(db_session)

    with pytest.raises(DecisionError):
        sync_run(db_session, tenant_ctx, context, [good, foreign])

    assert _row_counts(db_session) == before  # nothing at all was written, not even `good`'s row


def test_a_failure_rolls_back_a_would_be_new_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    trigger = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    foreign = cost_evaluation(
        workspace_id=uuid4(),
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)

    with pytest.raises(DecisionError):
        sync_run(db_session, tenant_ctx, context, [trigger, foreign])

    memory = DecisionMemoryService(db_session, tenant_ctx)
    assert memory.list_open_decisions(tenant.property.id) == []  # the new Decision never landed


def test_a_failure_rolls_back_an_existing_decisions_update(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    day1 = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    opened = sync_run(
        db_session, tenant_ctx, PriorityContext(tenant.workspace.id, tenant.property.id, D1), [day1]
    ).result
    [decision_id] = opened.touched_decision_ids
    memory = DecisionMemoryService(db_session, tenant_ctx)
    before = memory.get_decision(decision_id)
    assert before is not None
    before_state = (
        before.status,
        before.last_evaluated_local_date,
        before.triggered_observation_count,
    )

    day2 = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D2,
    )
    foreign = cost_evaluation(
        workspace_id=uuid4(),
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    with pytest.raises(DecisionError):
        sync_run(
            db_session,
            tenant_ctx,
            PriorityContext(tenant.workspace.id, tenant.property.id, D2),
            [day2, foreign],
        )

    after = memory.get_decision(decision_id)
    assert after is not None
    after_state = (after.status, after.last_evaluated_local_date, after.triggered_observation_count)
    assert after_state == before_state  # the OBSERVED update never landed either


def test_a_failure_rolls_back_the_observation_insert(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    trigger = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    foreign = cost_evaluation(
        workspace_id=uuid4(),
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)

    with pytest.raises(DecisionError):
        sync_run(db_session, tenant_ctx, context, [trigger, foreign])

    assert db_session.scalar(select(func.count()).select_from(DecisionObservation)) == 0


def test_conflicting_identity_rolls_back_everything(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    conflicting = replace(evaluation, calculation_fingerprint="9" * 64)
    other = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    before = _row_counts(db_session)

    with pytest.raises(DecisionError):
        sync_run(db_session, tenant_ctx, context, [evaluation, conflicting, other])

    assert _row_counts(db_session) == before  # `other`'s own valid Decision never landed either


def test_priority_mismatch_rolls_back_everything(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_ctx = TenantContext(tenant.workspace.id)
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    candidate = candidate_for(evaluation)
    tampered_ranking = PriorityRankingResult(
        workspace_id=context.workspace_id,
        property_id=context.property_id,
        as_of_local_date=context.as_of_local_date,
        candidate_count=1,
        excluded_clear_count=1,  # a lie: nothing was CLEAR
        excluded_insufficient_count=0,
        excluded_not_applicable_count=0,
        excluded_suppressed_count=0,
        duplicate_input_count=0,
        ranked_candidates=(RankedPriorityCandidate(1, candidate),),
        calculation_fingerprint="e" * 64,
    )
    before = _row_counts(db_session)

    with pytest.raises(DecisionError):
        DecisionService(db_session, tenant_ctx).sync(context, tampered_ranking, [evaluation])

    assert _row_counts(db_session) == before

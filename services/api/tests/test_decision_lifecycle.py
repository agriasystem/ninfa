"""Lifecycle rules of Decision Persistence, Lifecycle and Memory V1 (`decision-lifecycle-v1`).

One shared identity (a REV_PICKUP_LOW target) is walked through many days/runs for most rules;
dedicated identities cover the RESOLVED+non-CLEAR family (Rule 8) and out-of-order rejection.
"""

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.errors import DecisionError, DecisionErrorCode
from app.modules.decisions.models import Decision
from app.modules.decisions.types import DecisionStatus, DecisionSyncResult, LifecycleTransition
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import EvaluationStatus, RevenueDecisionEvaluation
from tests.decision_support import (
    CLEAR,
    INSUFFICIENT,
    NOT_APPLICABLE,
    SUPPRESSED,
    TRIGGERED,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1, D2, D3, D4, D5, D6, D7 = (date(2026, 8, day) for day in range(1, 8))
STAY = date(2026, 8, 15)


def _pickup(
    tenant: Tenant, as_of: date, status: EvaluationStatus = TRIGGERED
) -> RevenueDecisionEvaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=as_of,
        status=status,
    )


def _one(
    db_session: Session, tenant: Tenant, as_of: date, status: EvaluationStatus = TRIGGERED
) -> DecisionSyncResult:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    outcome = sync_run(
        db_session, TenantContext(tenant.workspace.id), context, [_pickup(tenant, as_of, status)]
    )
    return outcome.result


def _fetch(db_session: Session, tenant: Tenant, decision_id: UUID) -> Decision:
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    found = memory.get_decision(decision_id)
    assert found is not None
    return found


# --- REGOLA 1: first trigger creates OPEN (27-32) -----------------------------------------------


def test_first_trigger_opens_a_new_decision(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    result = _one(db_session, tenant, D1)

    assert result.created_decision_count == 1
    [decision_id] = result.touched_decision_ids
    decision = _fetch(db_session, tenant, decision_id)

    assert decision.status == DecisionStatus.OPEN
    assert decision.first_seen_local_date == D1
    assert decision.last_seen_local_date == D1
    assert decision.last_evaluated_local_date == D1
    assert decision.episode_count == 1
    assert decision.triggered_observation_count == 1

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    [observation] = memory.get_history(decision.id)
    assert observation.lifecycle_transition == LifecycleTransition.OPENED


# --- REGOLA 2: OPEN + TRIGGERED -> same id, OBSERVED (33-37) ------------------------------------


def test_second_day_trigger_reuses_the_same_decision_and_observes(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids

    second = _one(db_session, tenant, D2)
    assert second.created_decision_count == 0
    assert second.observed_open_count == 1
    assert second.touched_decision_ids == (decision_id,)  # same Decision id: no duplicate

    decision = _fetch(db_session, tenant, decision_id)
    assert decision.status == DecisionStatus.OPEN
    assert decision.last_seen_local_date == D2
    assert decision.last_evaluated_local_date == D2
    assert decision.triggered_observation_count == 2
    assert decision.episode_count == 1

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    assert len(memory.list_open_decisions(tenant.property.id)) == 1  # never a duplicate Decision
    history = memory.get_history(decision.id)
    assert len(history) == 2
    assert history[1].lifecycle_transition == LifecycleTransition.OBSERVED


# --- REGOLA 3: OPEN + CLEAR -> RESOLVED (38-42) -------------------------------------------------


def test_clear_resolves_an_open_decision(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids

    result = _one(db_session, tenant, D2, status=CLEAR)
    assert result.resolved_count == 1

    decision = _fetch(db_session, tenant, decision_id)
    assert decision.status == DecisionStatus.RESOLVED
    assert decision.resolved_local_date == D2
    assert decision.last_seen_local_date == D1  # unchanged: last TRIGGERED, not last evaluated
    assert decision.last_evaluated_local_date == D2

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    assert memory.list_open_decisions(tenant.property.id) == []
    history = memory.get_history(decision.id)
    assert history[-1].lifecycle_transition == LifecycleTransition.RESOLVED


# --- REGOLA 7: RESOLVED + TRIGGERED -> REOPENED (43-47) -----------------------------------------


def test_trigger_after_resolve_reopens_the_same_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids
    _one(db_session, tenant, D2, status=CLEAR)

    result = _one(db_session, tenant, D3)
    assert result.reopened_count == 1
    assert result.touched_decision_ids == (decision_id,)

    decision = _fetch(db_session, tenant, decision_id)
    assert decision.status == DecisionStatus.OPEN
    assert decision.episode_count == 2
    assert decision.resolved_local_date is None
    assert decision.first_seen_local_date == D1  # never changes
    assert decision.last_seen_local_date == D3
    assert decision.last_evaluated_local_date == D3
    assert decision.triggered_observation_count == 2

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    history = memory.get_history(decision.id)
    assert [o.lifecycle_transition for o in history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.RESOLVED,
        LifecycleTransition.REOPENED,
    ]


# --- REGOLA 4/5/6: OPEN + insufficient/suppressed/N-A never resolve (48-50) ---------------------


@pytest.mark.parametrize("status", [INSUFFICIENT, SUPPRESSED, NOT_APPLICABLE])
def test_open_decision_is_not_resolved_by_a_non_clear_non_trigger_status(
    db_session: Session, factory: BookingFactory, status: EvaluationStatus
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids

    result = _one(db_session, tenant, D2, status=status)
    assert result.no_state_change_count == 1
    assert result.resolved_count == 0

    decision = _fetch(db_session, tenant, decision_id)
    assert decision.status == DecisionStatus.OPEN
    assert decision.last_evaluated_local_date == D2
    assert decision.last_seen_local_date == D1  # only a real TRIGGERED moves last_seen

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    history = memory.get_history(decision.id)
    assert history[-1].lifecycle_transition == LifecycleTransition.NO_STATE_CHANGE
    assert history[-1].source_status.value == status.value


# --- absence is not CLEAR (51) -------------------------------------------------------------------


def test_missing_evaluation_never_resolves_an_open_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids
    before = _fetch(db_session, tenant, decision_id)

    # Day 2's run touches nothing of this identity at all (a totally unrelated context/empty run).
    context2 = PriorityContext(tenant.workspace.id, tenant.property.id, D2)
    result = sync_run(db_session, TenantContext(tenant.workspace.id), context2, []).result
    assert decision_id not in result.touched_decision_ids

    after = _fetch(db_session, tenant, decision_id)
    assert after.status == DecisionStatus.OPEN
    assert after.last_evaluated_local_date == before.last_evaluated_local_date == D1
    assert after.last_seen_local_date == D1

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    history = memory.get_history(decision_id)
    assert len(history) == 1  # no new Observation was appended for the absent day


# --- REGOLA 8: RESOLVED + non-TRIGGERED stays RESOLVED (52-55) ----------------------------------


@pytest.mark.parametrize("status", [CLEAR, INSUFFICIENT, SUPPRESSED, NOT_APPLICABLE])
def test_resolved_decision_stays_resolved_for_any_non_trigger_status(
    db_session: Session, factory: BookingFactory, status: EvaluationStatus
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)
    [decision_id] = first.touched_decision_ids
    _one(db_session, tenant, D2, status=CLEAR)  # resolve it first

    result = _one(db_session, tenant, D3, status=status)
    assert result.resolved_count == 0
    assert result.reopened_count == 0
    assert result.no_state_change_count == 1

    decision = _fetch(db_session, tenant, decision_id)
    assert decision.status == DecisionStatus.RESOLVED
    assert decision.last_evaluated_local_date == D3
    assert decision.resolved_local_date == D2  # unchanged: it was already resolved on day 2

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    history = memory.get_history(decision.id)
    assert history[-1].lifecycle_transition == LifecycleTransition.NO_STATE_CHANGE


# --- non-triggered with no existing Decision creates nothing ------------------------------------


@pytest.mark.parametrize("status", [CLEAR, INSUFFICIENT, SUPPRESSED, NOT_APPLICABLE])
def test_non_triggered_evaluation_with_no_existing_decision_creates_nothing(
    db_session: Session, factory: BookingFactory, status: EvaluationStatus
) -> None:
    tenant = factory.tenant()
    result = _one(db_session, tenant, D1, status=status)

    assert result.created_decision_count == 0
    assert result.observation_count == 0
    assert result.touched_decision_ids == ()
    assert result.open_decision_count_after_sync == 0

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    assert memory.list_open_decisions(tenant.property.id) == []


# --- out-of-order rejection / same-day different run (56-57) ------------------------------------


def test_out_of_order_run_is_rejected_wholesale(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _one(db_session, tenant, D5)  # last_evaluated_local_date is now D5

    with pytest.raises(DecisionError) as info:
        _one(db_session, tenant, D3)  # strictly before D5
    assert info.value.error_code == DecisionErrorCode.DECISION_OUT_OF_ORDER_RUN

    # the rejection rolled back completely: no phantom second Decision, state unchanged
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    [decision] = memory.list_open_decisions(tenant.property.id)
    assert decision.last_evaluated_local_date == D5
    assert len(memory.get_history(decision.id)) == 1


def test_same_as_of_date_with_a_different_input_is_a_new_run(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = _one(db_session, tenant, D1)

    # a second, unrelated TRIGGERED evaluation on the SAME as-of date, different identity: a
    # legitimately different logical input, so a new run (never rejected as out-of-order: the
    # as-of is equal, not before, last_evaluated_local_date).
    other_source = uuid4()
    other = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=other_source,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    second = sync_run(db_session, TenantContext(tenant.workspace.id), context, [other]).result

    assert second.decision_run_id != first.decision_run_id
    assert second.is_idempotent_replay is False
    assert second.created_decision_count == 1

    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    assert len(memory.list_open_decisions(tenant.property.id)) == 2

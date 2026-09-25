"""DecisionRun persistence and idempotency (tests 58-66)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.identity import build_identity
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.service import DecisionService
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_support import CLEAR, cost_evaluation, revenue_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _row_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (DecisionRun, Decision, DecisionObservation)
    }


def test_first_run_persists_a_decision_run_row(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])

    row = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert row is not None
    assert row.as_of_local_date == D1
    assert row.triggered_count == 1
    assert row.evaluation_count == 1


def test_identical_replay_returns_the_same_run_and_writes_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    first = sync_run(db_session, tenant_context, context, [evaluation]).result
    before = _row_counts(db_session)

    replay = sync_run(db_session, tenant_context, context, [evaluation]).result
    after = _row_counts(db_session)

    assert replay.decision_run_id == first.decision_run_id
    assert replay.is_idempotent_replay is True
    assert before == after  # zero new rows in any of the three tables


def test_input_order_does_not_change_the_resulting_run(
    db_session: Session, factory: BookingFactory
) -> None:
    """Order-independence end to end needs the REAL `PriorityService.rank()` (order-independence
    of ITS OWN ranking fingerprint is Gate 10's own tested invariant): the simplified
    `ranking_result_for()` test helper assigns ranks in caller order on purpose (it is not a
    ranking test) and would not exercise this."""
    tenant = factory.tenant()
    pickup = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    forward_ranking = PriorityService().rank(context, [pickup, cost])
    forward = DecisionService(db_session, tenant_context).sync(
        context, forward_ranking, [pickup, cost]
    )

    reordered_ranking = PriorityService().rank(context, [cost, pickup])
    reordered = DecisionService(db_session, tenant_context).sync(
        context, reordered_ranking, [cost, pickup]
    )

    assert reordered.decision_run_id == forward.decision_run_id
    assert reordered.is_idempotent_replay is True


def test_a_literal_duplicate_evaluation_is_deduplicated_like_priority(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(
        db_session, TenantContext(tenant.workspace.id), context, [evaluation, evaluation]
    )

    assert outcome.result.created_decision_count == 1  # one logical Decision, not two
    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.duplicate_input_count == 1
    assert run.evaluation_count == 1


def test_a_changed_source_fingerprint_produces_a_new_run(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    original = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        confidence_score=Decimal("70.00"),
        fingerprint="1" * 64,
    )
    first = sync_run(db_session, tenant_context, context, [original]).result

    changed = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        confidence_score=Decimal("95.00"),
        fingerprint="2" * 64,  # a different calculation, TRIGGERED again
    )
    second = sync_run(db_session, tenant_context, context, [changed]).result

    assert second.decision_run_id != first.decision_run_id
    assert second.is_idempotent_replay is False


def test_same_day_changed_dataset_produces_a_new_run_and_reuses_the_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    pickup = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    first = sync_run(db_session, tenant_context, context, [pickup]).result

    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=uuid4(),
        target_period_start=date(2026, 7, 1),
    )
    second = sync_run(db_session, tenant_context, context, [pickup, cost]).result

    assert second.decision_run_id != first.decision_run_id
    assert second.created_decision_count == 1  # cost's own Decision
    assert second.observed_open_count == 1  # pickup's Decision, TRIGGERED again


def test_a_zero_trigger_run_still_persists_a_run_row(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [clear])

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.triggered_count == 0
    assert run.clear_count == 1


def test_a_zero_trigger_run_creates_no_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [clear])

    assert outcome.result.created_decision_count == 0
    assert outcome.result.observation_count == 0
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    assert memory.list_open_decisions(tenant.property.id) == []


def test_cost_same_target_evaluated_two_real_runs_apart_persists_one_identity(
    db_session: Session, factory: BookingFactory
) -> None:
    """The exact scenario the Gate 11 privacy/identity review asked to see proven at the
    PERSISTENCE level (not just `build_identity()` in isolation, see `test_decision_identity.py`'s
    own `test_cost_identity_includes_the_real_gate_7_target_dimensions`): the SAME workspace,
    property, booking data source (the occupancy denominator's stated provenance - the cost lines
    themselves are read cross-source by Gate 6/7 and carry no ingestion source dimension at all),
    calendar month, category and currency, genuinely re-evaluated in TWO SEPARATE `sync()` calls a
    week apart, must resolve to the SAME `Decision.identity_key` and the SAME Decision row."""
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    booking_source = uuid4()

    day1_evaluation = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=booking_source,
        target_period_start=date(2026, 8, 1),
    )
    day2_evaluation = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=booking_source,
        target_period_start=date(2026, 8, 1),
    )
    # A fresh, independently-built fingerprint each call (no `fingerprint=` override): a genuine
    # re-evaluation, not a byte-identical replay - and still the SAME identity, because identity
    # never depends on `calculation_fingerprint`.
    assert day1_evaluation.calculation_fingerprint != day2_evaluation.calculation_fingerprint
    day1_identity_key = build_identity(day1_evaluation).identity_key
    assert day1_identity_key == build_identity(day2_evaluation).identity_key

    day1 = date(2026, 8, 3)
    day2 = day1 + timedelta(days=7)

    first = sync_run(
        db_session,
        tenant_context,
        PriorityContext(tenant.workspace.id, tenant.property.id, day1),
        [day1_evaluation],
    ).result
    second = sync_run(
        db_session,
        tenant_context,
        PriorityContext(tenant.workspace.id, tenant.property.id, day2),
        [day2_evaluation],
    ).result

    assert first.decision_run_id != second.decision_run_id  # two genuinely separate runs
    assert first.touched_decision_ids == second.touched_decision_ids  # the SAME Decision row
    [decision_id] = first.touched_decision_ids

    memory = DecisionMemoryService(db_session, tenant_context)
    decision = memory.get_decision(decision_id)
    assert decision is not None
    assert decision.identity_key == day1_identity_key
    assert decision.episode_count == 1  # still the same episode: OBSERVED, never REOPENED
    assert decision.triggered_observation_count == 2
    history = memory.get_history(decision_id)
    assert len(history) == 2  # both runs recorded, never overwritten

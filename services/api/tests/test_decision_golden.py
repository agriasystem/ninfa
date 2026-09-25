"""MASSERIA NINFA DEMO — DECISION MEMORY V1: the real pipeline, end to end.

    canonical data -> REAL detector services (Gate 5/7/8/9, unmodified) -> PriorityService.rank()
    -> DecisionService.sync() -> PostgreSQL Decision Memory

`decision_golden_support.py` builds one shared workspace/property and drives the real
`RevenueDecisionService`/`OtaDependencyService`/`CostDecisionService`/`LaborDecisionService` (Gate
10's own already-proven `priority_golden_support.py`, reused UNMODIFIED) to produce the five real
TRIGGERED evaluations, plus a SEPARATE, dedicated `REV_OTA_DEPENDENCY` source built specifically to
walk OPENED -> RESOLVED -> REOPENED across three widely-spaced calendar windows. No
`PriorityCandidate`, `Decision` or `DecisionObservation` is ever built by hand.

GOLDEN INDEPENDENCE: the expected identity payload/hash below is verified without calling
`app.modules.decisions.identity` to compute the EXPECTED side - only stdlib (`hashlib`, `json`) and
literal values, exactly like `test_decision_identity.py`'s own hash test.
"""

import hashlib
import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.identity import SourceEvaluation, build_identity
from app.modules.decisions.models import Decision
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionStatus, LifecycleTransition
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from app.modules.intelligence.revenue.service import RevenueDecisionService
from tests.decision_golden_support import (
    DAY_1,
    DAY_2,
    DAY_3,
    DecisionGoldenWorld,
    build_decision_golden_world,
)
from tests.expected_support import add_snapshots
from tests.revenue_support import snap
from tests.support import BookingFactory

STAY_DATE = date(2026, 8, 15)  # the shared golden world's own revenue target stay date


def test_golden_day_1_five_canonical_and_one_lifecycle_decision_all_open(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build_decision_golden_world(db_session, factory)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)

    pickup, occupancy = world.priority_world.revenue_signals()
    ota_canonical = world.priority_world.ota_structural()
    cost = world.priority_world.cost_anomaly()
    labor = world.priority_world.labor_overstaffing()
    lifecycle_ota_day1 = world.lifecycle_ota.evaluate(DAY_1)

    canonical_evaluations: list[SourceEvaluation] = [pickup, occupancy, ota_canonical, cost, labor]
    for evaluation in [*canonical_evaluations, lifecycle_ota_day1]:
        assert evaluation.status.value == "TRIGGERED", evaluation.decision_type

    # Two SEPARATE runs of the SAME as-of date: Gate 10's own `source_target_key` for
    # REV_OTA_DEPENDENCY is `as-of + window` only (no data source), so the canonical OTA source
    # and the dedicated lifecycle OTA source - both evaluated at the SAME as-of, both with the
    # SAME 30-day window - would collide as a false "conflict" if ranked together. Two data
    # sources evaluated separately, on the same day, is exactly the "MULTIPLE SAME-DAY RUNS"
    # case the spec explicitly allows (same as-of, a different logical input, a new DecisionRun).
    service = DecisionService(db_session, tenant_ctx)

    canonical_ranking = PriorityService().rank(context, canonical_evaluations)
    assert canonical_ranking.candidate_count == 5
    canonical_result = service.sync(context, canonical_ranking, canonical_evaluations)

    lifecycle_ranking = PriorityService().rank(context, [lifecycle_ota_day1])
    assert lifecycle_ranking.candidate_count == 1
    lifecycle_result = service.sync(context, lifecycle_ranking, [lifecycle_ota_day1])

    assert canonical_result.decision_run_id != lifecycle_result.decision_run_id
    assert canonical_result.is_idempotent_replay is False
    assert lifecycle_result.is_idempotent_replay is False
    assert canonical_result.created_decision_count == 5
    assert lifecycle_result.created_decision_count == 1
    assert lifecycle_result.open_decision_count_after_sync == 6

    memory = DecisionMemoryService(db_session, tenant_ctx)
    open_decisions = memory.list_open_decisions(world.tenant.property.id)
    assert len(open_decisions) == 6
    for decision in open_decisions:
        assert decision.status == DecisionStatus.OPEN
        assert decision.episode_count == 1
        assert decision.triggered_observation_count == 1
        assert decision.first_seen_local_date == DAY_1
        assert decision.last_seen_local_date == DAY_1
        assert decision.last_evaluated_local_date == DAY_1
        [observation] = memory.get_history(decision.id)
        assert observation.lifecycle_transition == LifecycleTransition.OPENED
        assert observation.source_status.value == "TRIGGERED"
    assert {d.decision_type for d in open_decisions} == set(PriorityDecisionType)

    # --- EXACT REPLAY: same two runs, zero new rows, zero lifecycle mutations ------------------
    canonical_replay = service.sync(
        context, PriorityService().rank(context, canonical_evaluations), canonical_evaluations
    )
    lifecycle_replay = service.sync(
        context, PriorityService().rank(context, [lifecycle_ota_day1]), [lifecycle_ota_day1]
    )

    assert canonical_replay.is_idempotent_replay is True
    assert canonical_replay.decision_run_id == canonical_result.decision_run_id
    assert canonical_replay.created_decision_count == 0
    assert lifecycle_replay.is_idempotent_replay is True
    assert lifecycle_replay.decision_run_id == lifecycle_result.decision_run_id
    assert lifecycle_replay.created_decision_count == 0
    for decision in memory.list_open_decisions(world.tenant.property.id):
        assert len(memory.get_history(decision.id)) == 1  # the replay appended nothing


def _run_day_1(
    db_session: Session, factory: BookingFactory
) -> tuple[
    DecisionGoldenWorld,
    TenantContext,
    DecisionService,
    DecisionMemoryService,
    dict[PriorityDecisionType, Decision],
]:
    """Builds the world and runs Day 1 (the real pipeline), returning everything Day 2/3 need."""
    world = build_decision_golden_world(db_session, factory)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)

    pickup, occupancy = world.priority_world.revenue_signals()
    ota_canonical = world.priority_world.ota_structural()
    cost = world.priority_world.cost_anomaly()
    labor = world.priority_world.labor_overstaffing()
    lifecycle_ota_day1 = world.lifecycle_ota.evaluate(DAY_1)

    # Two separate same-day runs: see the comment in the Day 1 test above (Gate 10's own
    # `source_target_key` for OTA has no data source, so two OTA sources sharing the same as-of
    # and window would otherwise collide as a false conflict).
    canonical_evaluations: list[SourceEvaluation] = [pickup, occupancy, ota_canonical, cost, labor]
    service = DecisionService(db_session, tenant_ctx)
    service.sync(
        context, PriorityService().rank(context, canonical_evaluations), canonical_evaluations
    )
    service.sync(
        context, PriorityService().rank(context, [lifecycle_ota_day1]), [lifecycle_ota_day1]
    )

    memory = DecisionMemoryService(db_session, tenant_ctx)
    open_decisions = memory.list_open_decisions(world.tenant.property.id)
    # `decision_type` alone is NOT a unique key here: the canonical and the lifecycle OTA
    # Decisions share REV_OTA_DEPENDENCY (two different booking data sources). The four other
    # types are each unique, so a plain dict is safe for them; the lifecycle OTA Decision is
    # looked up separately, by its own identity.
    by_type: dict[PriorityDecisionType, Decision] = {
        decision.decision_type: decision
        for decision in open_decisions
        if decision.decision_type != PriorityDecisionType.REV_OTA_DEPENDENCY
    }
    lifecycle_identity_key = build_identity(lifecycle_ota_day1).identity_key
    [lifecycle_decision] = [
        decision
        for decision in open_decisions
        if decision.decision_type == PriorityDecisionType.REV_OTA_DEPENDENCY
        and decision.identity_key == lifecycle_identity_key
    ]
    by_type[PriorityDecisionType.REV_OTA_DEPENDENCY] = lifecycle_decision
    return world, tenant_ctx, service, memory, by_type


def test_golden_day_2_remains_triggered_absent_insufficient_and_rank_changes(
    db_session: Session, factory: BookingFactory
) -> None:
    """Day 2 (near-term refresh, one week after Day 1): the two revenue Decisions can still be
    re-observed (the stay date is still in the future); labor and the canonical OTA Decision are
    simply not part of this run (ABSENCE, never CLEAR); cost is re-evaluated unchanged."""
    world, tenant_ctx, service, memory, day1_by_type = _run_day_1(db_session, factory)
    day2a = DAY_1 + timedelta(days=7)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, day2a)

    # A NEW observed snapshot for the SAME stay date, one week later, with NO lead-7 historical
    # curves built for it: the real Gate 4 baseline comes back INSUFFICIENT_DATA, and so does
    # REV_PICKUP_LOW/REV_OCCUPANCY_RISK for it - the SAME identity (same stay date), genuinely
    # re-evaluated, genuinely insufficient.
    row = snap(world.tenant, day2a, STAY_DATE, 22, available=40)
    add_snapshots(db_session, world.tenant, [row])
    db_session.commit()

    revenue_service = RevenueDecisionService(db_session, world.tenant.context)
    day2_signals = revenue_service.evaluate_revenue_signals(row["id"])
    pickup_day2 = day2_signals.pickup_low
    occupancy_day2 = day2_signals.occupancy_risk
    assert pickup_day2.status.value == "INSUFFICIENT_DATA"
    assert occupancy_day2.status.value == "INSUFFICIENT_DATA"

    cost_decision_id = day1_by_type[PriorityDecisionType.COST_CPOR_ANOMALY].id
    [cost_day1_observation] = memory.get_history(cost_decision_id)
    cost_day2 = world.priority_world.cost_anomaly()  # identical inputs: the SAME fingerprint
    assert cost_day2.calculation_fingerprint == cost_day1_observation.source_evaluation_fingerprint

    evaluations: list[SourceEvaluation] = [pickup_day2, occupancy_day2, cost_day2]
    ranking = PriorityService().rank(context, evaluations)
    assert ranking.candidate_count == 1  # only COST is TRIGGERED

    result = service.sync(context, ranking, evaluations)

    assert result.created_decision_count == 0
    assert result.observed_open_count == 1  # COST: TRIGGERED again
    assert result.no_state_change_count == 2  # both revenue Decisions: INSUFFICIENT_DATA

    cost_decision_id = day1_by_type[PriorityDecisionType.COST_CPOR_ANOMALY].id
    cost_after = memory.get_decision(cost_decision_id)
    assert cost_after is not None
    assert cost_after.status == DecisionStatus.OPEN
    assert cost_after.triggered_observation_count == 2
    assert cost_after.episode_count == 1
    cost_history = memory.get_history(cost_decision_id)
    assert [o.lifecycle_transition for o in cost_history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.OBSERVED,
    ]
    # E: COST's own rank changed (it was not #1 among Day 1's six candidates; here it is the ONLY
    # TRIGGERED candidate) - the SAME Decision, a DIFFERENT rank, both kept in its own history.
    assert cost_history[0].priority_rank != cost_history[1].priority_rank
    assert cost_history[1].priority_rank == 1

    for decision_type in (
        PriorityDecisionType.REV_PICKUP_LOW,
        PriorityDecisionType.REV_OCCUPANCY_RISK,
    ):
        decision_id = day1_by_type[decision_type].id
        after = memory.get_decision(decision_id)
        assert after is not None
        assert after.status == DecisionStatus.OPEN  # INSUFFICIENT_DATA never resolves
        assert after.last_evaluated_local_date == day2a
        assert after.last_seen_local_date == DAY_1  # last TRIGGERED, unchanged
        assert memory.get_history(decision_id)[-1].lifecycle_transition == (
            LifecycleTransition.NO_STATE_CHANGE
        )

    # D: absence. Labor's Day 1 work date has already passed and is simply never mentioned again;
    # the canonical OTA Decision is likewise not part of this run. Neither is touched.
    for decision_type in (
        PriorityDecisionType.LABOR_OVERSTAFFING,
        PriorityDecisionType.REV_OTA_DEPENDENCY,
    ):
        decision_id = day1_by_type[decision_type].id
        after = memory.get_decision(decision_id)
        assert after is not None
        assert after.status == DecisionStatus.OPEN
        assert after.last_evaluated_local_date == DAY_1  # untouched
        assert len(memory.get_history(decision_id)) == 1  # no new Observation


def test_golden_day_2_ota_cross_day_identity_and_clear_resolves(
    db_session: Session, factory: BookingFactory
) -> None:
    """Day 2 (the lifecycle OTA source's own 30-day-window cadence, 35 days after Day 1): the
    SAME booking data source, a DIFFERENT window - and, per the real detector, a real CLEAR."""
    world, tenant_ctx, service, memory, day1_by_type = _run_day_1(db_session, factory)

    lifecycle_ota_day1 = world.lifecycle_ota.evaluate(DAY_1)
    lifecycle_ota_day2 = world.lifecycle_ota.evaluate(DAY_2)

    assert lifecycle_ota_day1.status.value == "TRIGGERED"
    assert lifecycle_ota_day2.status.value == "CLEAR"
    assert lifecycle_ota_day1.window_start != lifecycle_ota_day2.window_start
    assert lifecycle_ota_day1.window_end != lifecycle_ota_day2.window_end

    # --- GOLDEN OTA CROSS-DAY IDENTITY: independent hash, never calling app.modules.decisions ---
    expected_payload = {
        "identity_version": "decision-identity-v1",
        "decision_type": "REV_OTA_DEPENDENCY",
        "workspace_id": str(lifecycle_ota_day1.workspace_id),
        "property_id": str(lifecycle_ota_day1.property_id),
        "booking_data_source_id": str(lifecycle_ota_day1.booking_data_source_id),
    }
    expected_key = hashlib.sha256(
        json.dumps(
            expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()

    identity_day1 = build_identity(lifecycle_ota_day1)
    identity_day2 = build_identity(lifecycle_ota_day2)
    assert identity_day1.identity_key == identity_day2.identity_key == expected_key

    # --- sync Day 2: the SAME Decision resolves ------------------------------------------------
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    ranking = PriorityService().rank(context, [lifecycle_ota_day2])
    assert ranking.candidate_count == 0  # CLEAR is excluded, never a candidate

    result = service.sync(context, ranking, [lifecycle_ota_day2])
    assert result.resolved_count == 1

    ota_decision_id = day1_by_type[PriorityDecisionType.REV_OTA_DEPENDENCY].id
    decision = memory.get_decision(ota_decision_id)
    assert decision is not None
    assert decision.status == DecisionStatus.RESOLVED
    assert decision.resolved_local_date == DAY_2
    assert decision.last_seen_local_date == DAY_1  # last TRIGGERED
    assert decision.last_evaluated_local_date == DAY_2
    history = memory.get_history(ota_decision_id)
    assert [o.lifecycle_transition for o in history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.RESOLVED,
    ]


def test_golden_day_3_ota_reopens_the_same_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    """Day 3: the SAME lifecycle OTA identity, TRIGGERED again after having resolved - REOPENED,
    same Decision id, first_seen preserved, a second episode."""
    world, tenant_ctx, service, memory, day1_by_type = _run_day_1(db_session, factory)
    ota_decision_id = day1_by_type[PriorityDecisionType.REV_OTA_DEPENDENCY].id

    lifecycle_ota_day2 = world.lifecycle_ota.evaluate(DAY_2)
    context2 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    service.sync(
        context2, PriorityService().rank(context2, [lifecycle_ota_day2]), [lifecycle_ota_day2]
    )

    lifecycle_ota_day3 = world.lifecycle_ota.evaluate(DAY_3)
    assert lifecycle_ota_day3.status.value == "TRIGGERED"
    assert lifecycle_ota_day3.structural_condition is True

    context3 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_3)
    ranking3 = PriorityService().rank(context3, [lifecycle_ota_day3])
    result3 = service.sync(context3, ranking3, [lifecycle_ota_day3])

    assert result3.reopened_count == 1
    assert result3.touched_decision_ids == (ota_decision_id,)

    decision = memory.get_decision(ota_decision_id)
    assert decision is not None
    assert decision.status == DecisionStatus.OPEN
    assert decision.resolved_local_date is None
    assert decision.episode_count == 2
    assert decision.first_seen_local_date == DAY_1  # never changes
    assert decision.last_seen_local_date == DAY_3
    assert decision.last_evaluated_local_date == DAY_3

    history = memory.get_history(ota_decision_id)
    assert [o.lifecycle_transition for o in history] == [
        LifecycleTransition.OPENED,
        LifecycleTransition.RESOLVED,
        LifecycleTransition.REOPENED,
    ]
    assert [o.as_of_local_date for o in history] == [DAY_1, DAY_2, DAY_3]

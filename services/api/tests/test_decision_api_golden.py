"""MASSERIA NINFA DEMO — DECISION API V1: the real pipeline, end to end, through HTTP.

    canonical data -> real detectors -> PriorityService.rank() -> DecisionService.sync()
    -> PostgreSQL Decision Memory -> HTTP GET -> JSON response

Reuses Gate 11's own, already-proven `tests.decision_golden_support` /
`tests.priority_golden_support` UNMODIFIED for the world and the real detector evaluations - this
module drives no detector and no `DecisionService.sync()` differently than Gate 11 already does;
it only adds the HTTP layer on top and asserts on its JSON. `DecisionService.sync()` itself is
still called in-process here (exactly as a real scheduled job would), never through HTTP - Gate 12
is READ-only, by design.

GOLDEN INDEPENDENCE: expected values are the real `PriorityRankingResult`/`DecisionSyncResult`
Gate 10/11 already produced (never the API's own serializer functions) plus stdlib
`canonical_text` - never re-derived from `app.api.v1.decisions.serializers`.
"""

from collections.abc import Callable
from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.identity import SourceEvaluation
from app.modules.decisions.precision import canonical_text
from app.modules.decisions.service import DecisionService
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from app.modules.intelligence.revenue.service import RevenueDecisionService
from tests.decision_api_support import detail_url, feed_url, history_url, list_url
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

STAY_DATE = date(2026, 8, 15)


def _golden_world(
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> DecisionGoldenWorld:
    world = build_decision_golden_world(db_session, factory)
    user = factory.user()
    factory.membership(world.tenant.workspace, user)
    authenticated_as(user.id)
    return world


def test_golden_day_1_feed_is_action_required_with_real_pipeline_data(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    pickup, occupancy = world.priority_world.revenue_signals()
    ota = world.priority_world.ota_structural()
    cost = world.priority_world.cost_anomaly()
    labor = world.priority_world.labor_overstaffing()
    canonical: list[SourceEvaluation] = [pickup, occupancy, ota, cost, labor]

    ranking = PriorityService().rank(context, canonical)  # independent expected ground truth
    DecisionService(db_session, tenant_ctx).sync(context, ranking, canonical)

    response = api_client.get(feed_url(world.tenant.property.id, DAY_1.isoformat()))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feed_state"] == "ACTION_REQUIRED"
    assert body["triggered_count"] == 5
    assert len(body["items"]) == 5

    by_fingerprint = {item["priority"]["candidate_fingerprint"]: item for item in body["items"]}
    assert set(by_fingerprint) == {
        ranked.candidate.calculation_fingerprint for ranked in ranking.ranked_candidates
    }
    for ranked in ranking.ranked_candidates:
        item = by_fingerprint[ranked.candidate.calculation_fingerprint]
        assert item["priority"]["rank"] == ranked.rank
        assert item["priority"]["priority_score"] == canonical_text(
            ranked.candidate.priority_score_exact
        )
        assert item["source_status"] == "TRIGGERED"

    ranks = [item["priority"]["rank"] for item in body["items"]]
    assert ranks == sorted(ranks) == list(range(1, 6))  # priority_rank ASC, exactly 1..5


def _cost_decision_id(memory: DecisionMemoryService, touched: tuple[UUID, ...]) -> UUID:
    for decision_id in touched:
        decision = memory.get_decision(decision_id)
        if decision is None:
            continue
        if decision.decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
            return decision_id
    raise AssertionError("no COST_CPOR_ANOMALY decision among the touched ids")


def test_golden_day_2_latest_run_open_lifecycle_and_resolution_via_http(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Day 2 (real re-evaluation, one week later): the revenue Decisions can still be re-observed
    (insufficient this time - a new snapshot with no lead-7 historical curves), cost is re-
    TRIGGERED unchanged, labor/OTA are simply absent from THIS run. Verifies through HTTP: a
    Decision that stays OPEN but is not part of the selected run's feed, and that
    DATA_QUALITY_LIMITED never gets shown as "nothing to do"."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    memory = DecisionMemoryService(db_session, tenant_ctx)

    day1_context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    pickup, occupancy = world.priority_world.revenue_signals()
    cost = world.priority_world.cost_anomaly()
    day1_evaluations: list[SourceEvaluation] = [pickup, occupancy, cost]
    day1_ranking = PriorityService().rank(day1_context, day1_evaluations)
    day1_result = DecisionService(db_session, tenant_ctx).sync(
        day1_context, day1_ranking, day1_evaluations
    )
    cost_decision_id = _cost_decision_id(memory, day1_result.touched_decision_ids)

    day2 = DAY_1 + timedelta(days=7)
    row = snap(world.tenant, day2, STAY_DATE, 22, available=40)
    add_snapshots(db_session, world.tenant, [row])
    db_session.commit()
    revenue_service = RevenueDecisionService(db_session, world.tenant.context)
    day2_signals = revenue_service.evaluate_revenue_signals(row["id"])
    assert day2_signals.pickup_low.status.value == "INSUFFICIENT_DATA"

    day2_context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, day2)
    cost_day2 = world.priority_world.cost_anomaly()  # identical inputs: re-TRIGGERED, real
    day2_evaluations: list[SourceEvaluation] = [
        day2_signals.pickup_low,
        day2_signals.occupancy_risk,
        cost_day2,
    ]
    day2_ranking = PriorityService().rank(day2_context, day2_evaluations)
    DecisionService(db_session, tenant_ctx).sync(day2_context, day2_ranking, day2_evaluations)

    feed = api_client.get(feed_url(world.tenant.property.id, day2.isoformat())).json()
    assert feed["feed_state"] == "ACTION_REQUIRED"  # cost alone is enough
    assert feed["triggered_count"] == 1
    [item] = feed["items"]
    assert item["decision_type"] == "COST_CPOR_ANOMALY"

    # the revenue Decisions stay OPEN (INSUFFICIENT_DATA never resolves) but are NOT in the feed:
    # OPEN lifecycle is a Decision-list concern, separate from "what needs action today".
    list_body = api_client.get(list_url(world.tenant.property.id, status="OPEN")).json()
    open_types = {entry["decision_type"] for entry in list_body["items"]}
    assert {"REV_PICKUP_LOW", "REV_OCCUPANCY_RISK", "COST_CPOR_ANOMALY"} <= open_types
    for entry in list_body["items"]:
        if entry["decision_type"] in ("REV_PICKUP_LOW", "REV_OCCUPANCY_RISK"):
            assert entry["latest_observation_summary"]["source_status"] == "INSUFFICIENT_DATA"
            assert entry["latest_observation_summary"]["priority_rank"] is None  # never an action

    cost_detail = api_client.get(detail_url(world.tenant.property.id, cost_decision_id)).json()
    assert cost_detail["status"] == "OPEN"
    assert cost_detail["latest_observation"]["priority"] is not None


def test_golden_data_quality_limited_via_real_insufficient_data(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """A REAL DecisionRun, through the real pipeline, with `triggered_count == 0` and
    `insufficient_count > 0`: a new observed snapshot for the golden stay date, one week after
    Day 1, with no lead-7 historical curves built for it - the real `RevenueDecisionService`
    genuinely returns `INSUFFICIENT_DATA` for both detectors on it (the exact mechanism Gate 11's
    own golden Day 2 scenario uses). No cost/labor/OTA evaluation is included in THIS run, so
    `triggered_count` is genuinely 0 - never hand-set."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)

    day2 = DAY_1 + timedelta(days=7)
    row = snap(world.tenant, day2, STAY_DATE, 22, available=40)
    add_snapshots(db_session, world.tenant, [row])
    db_session.commit()
    revenue_service = RevenueDecisionService(db_session, world.tenant.context)
    signals = revenue_service.evaluate_revenue_signals(row["id"])
    assert signals.pickup_low.status.value == "INSUFFICIENT_DATA"
    assert signals.occupancy_risk.status.value == "INSUFFICIENT_DATA"

    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, day2)
    evaluations: list[SourceEvaluation] = [signals.pickup_low, signals.occupancy_risk]
    ranking = PriorityService().rank(context, evaluations)
    assert ranking.candidate_count == 0  # nothing TRIGGERED, by construction of the real data
    result = DecisionService(db_session, tenant_ctx).sync(context, ranking, evaluations)
    assert result.observation_count == 0  # INSUFFICIENT_DATA with no existing Decision: no memory

    body = api_client.get(feed_url(world.tenant.property.id, day2.isoformat())).json()
    assert body["feed_state"] == "DATA_QUALITY_LIMITED"
    assert body["feed_state"] != "NO_ACTION_REQUIRED"
    assert body["decision_run_id"] == str(result.decision_run_id)  # never null: a run DID happen
    assert body["run_sequence"] is not None
    assert body["triggered_count"] == 0
    assert body["insufficient_count"] == 2
    assert body["suppressed_count"] == 0
    assert body["items"] == []


def test_golden_no_action_required_via_real_clear(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """A REAL DecisionRun with `triggered_count == insufficient_count == suppressed_count == 0`:
    the dedicated OTA lifecycle source's real Day-2 evaluation, which the real
    `OtaDependencyService` genuinely returns as `CLEAR` (its 20%/80% OTA/DIRECT low zone - see
    `decision_golden_support.py`). Distinct from `NOT_PROCESSED`: a run genuinely happened."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)

    day2_ota = world.lifecycle_ota.evaluate(DAY_2)
    assert day2_ota.status.value == "CLEAR"

    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    evaluations: list[SourceEvaluation] = [day2_ota]
    ranking = PriorityService().rank(context, evaluations)
    assert ranking.candidate_count == 0
    result = DecisionService(db_session, tenant_ctx).sync(context, ranking, evaluations)

    body = api_client.get(feed_url(world.tenant.property.id, DAY_2.isoformat())).json()
    assert body["feed_state"] == "NO_ACTION_REQUIRED"
    assert body["feed_state"] != "NOT_PROCESSED"
    assert body["decision_run_id"] == str(result.decision_run_id)  # never null: a run DID happen
    assert body["run_sequence"] is not None
    assert body["triggered_count"] == 0
    assert body["insufficient_count"] == 0
    assert body["suppressed_count"] == 0
    assert body["items"] == []


def test_golden_no_run_for_the_date_is_not_processed(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    world = _golden_world(factory, authenticated_as, db_session)
    never_synced = date(2030, 1, 1)
    body = api_client.get(feed_url(world.tenant.property.id, never_synced.isoformat())).json()
    assert body["feed_state"] == "NOT_PROCESSED"
    assert body["decision_run_id"] is None  # never a run id: none ever happened for this date
    assert body["run_sequence"] is None
    for field in (
        "triggered_count",
        "clear_count",
        "insufficient_count",
        "not_applicable_count",
        "suppressed_count",
    ):
        assert body[field] is None, field
    assert body["items"] == []


def test_golden_ota_lifecycle_history_newest_first_via_http(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """The dedicated OTA lifecycle source: OPENED (Day1) -> RESOLVED (Day2) -> REOPENED (Day3),
    read back through `/history`, newest-first."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    service = DecisionService(db_session, tenant_ctx)

    day1_ota = world.lifecycle_ota.evaluate(DAY_1)
    ctx1 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    result1 = service.sync(ctx1, PriorityService().rank(ctx1, [day1_ota]), [day1_ota])
    [decision_id] = result1.touched_decision_ids

    day2_ota = world.lifecycle_ota.evaluate(DAY_2)
    ctx2 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    service.sync(ctx2, PriorityService().rank(ctx2, [day2_ota]), [day2_ota])

    day3_ota = world.lifecycle_ota.evaluate(DAY_3)
    ctx3 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_3)
    service.sync(ctx3, PriorityService().rank(ctx3, [day3_ota]), [day3_ota])

    history = api_client.get(history_url(world.tenant.property.id, decision_id)).json()
    transitions = [item["lifecycle_transition"] for item in history["items"]]
    assert transitions == ["REOPENED", "RESOLVED", "OPENED"]  # newest-first

    detail = api_client.get(detail_url(world.tenant.property.id, decision_id)).json()
    assert detail["status"] == "OPEN"
    assert detail["episode_count"] == 2
    assert detail["resolved_local_date"] is None

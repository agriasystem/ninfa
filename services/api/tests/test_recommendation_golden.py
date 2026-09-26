"""MASSERIA NINFA DEMO — RECOMMENDATION ENGINE V1: the real pipeline, end to end, through HTTP.

    canonical data -> real detectors -> PriorityService.rank() -> DecisionService.sync()
    -> PostgreSQL Decision Memory -> RecommendationEngine.evaluate() -> HTTP GET -> JSON

Reuses `tests.decision_golden_support`/`tests.priority_golden_support` UNMODIFIED, exactly like
`test_decision_api_golden.py` - this module drives no detector and no `DecisionService.sync()`
differently than Gate 11/12 already do; it only reads the `recommendation` block their own real
runs now additionally produce.

GOLDEN INDEPENDENCE: expected values are read straight off the real, persisted `Decision`/
`DecisionObservation` rows (via `DecisionMemoryService`, never the API's own serializer) plus
stdlib `canonical_text`/`json.dumps`/`hashlib.sha256` - never re-derived from
`app.modules.recommendations` itself.

Scope, deliberately: SUPPRESSED_LOW_CONFIDENCE and NOT_APPLICABLE are covered exhaustively at the
pure-engine level only (`test_recommendation_engine.py`) - no golden fixture in this codebase
drives a real decision into either status on demand, and building one purely to re-prove a branch
already proven pure-unit would not add independent evidence.
"""

import hashlib
import json
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
from tests.decision_api_support import detail_url
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

_EXPECTED_PRIMARY_ACTION_CODE = {
    PriorityDecisionType.REV_PICKUP_LOW: "REVIEW_PRICING_AND_AVAILABILITY",
    PriorityDecisionType.REV_OCCUPANCY_RISK: "REVIEW_DEMAND_POSITIONING",
    PriorityDecisionType.REV_OTA_DEPENDENCY: "REVIEW_DISTRIBUTION_MIX",
    PriorityDecisionType.COST_CPOR_ANOMALY: "REVIEW_COST_DRIVERS",
    PriorityDecisionType.LABOR_OVERSTAFFING: "REVIEW_STAFFING_PLAN",
}


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


# --- 5 types AVAILABLE, via the real Day 1 pipeline ----------------------------------------------


def test_golden_all_five_types_are_available_via_real_day1_pipeline(
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

    ranking = PriorityService().rank(context, canonical)
    result = DecisionService(db_session, tenant_ctx).sync(context, ranking, canonical)
    assert len(result.touched_decision_ids) == 5

    memory = DecisionMemoryService(db_session, tenant_ctx)
    seen_types: set[PriorityDecisionType] = set()
    for decision_id in result.touched_decision_ids:
        decision = memory.get_decision(decision_id)
        observation = memory.get_latest_observation(decision_id)
        assert decision is not None and observation is not None
        seen_types.add(decision.decision_type)

        body = api_client.get(detail_url(world.tenant.property.id, decision_id)).json()
        recommendation = body["recommendation"]
        assert recommendation["status"] == "AVAILABLE", decision.decision_type
        assert recommendation["primary_action"] is not None
        assert (
            recommendation["primary_action"]["action_code"]
            == _EXPECTED_PRIMARY_ACTION_CODE[decision.decision_type]
        )
        assert recommendation["requires_human_review"] is True
        # golden independence: confidence copied verbatim from the ground-truth DB row, never
        # recomputed by the engine or the test.
        assert recommendation["confidence"] == canonical_text(observation.confidence_score)

    assert seen_types == set(PriorityDecisionType)


# --- NOT_AVAILABLE, via a real CLEAR re-evaluation ------------------------------------------------


def test_golden_not_available_via_real_clear_ota_reevaluation(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """The dedicated OTA lifecycle source's real Day-2 evaluation, which the real
    `OtaDependencyService` genuinely returns as CLEAR (see `test_decision_api_golden.py`'s own
    identical premise) - after a real Day-1 TRIGGERED open, the SAME decision's recommendation
    must flip to NOT_AVAILABLE once its latest observation is CLEAR."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    service = DecisionService(db_session, tenant_ctx)

    day1_ota = world.lifecycle_ota.evaluate(DAY_1)
    ctx1 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    result1 = service.sync(ctx1, PriorityService().rank(ctx1, [day1_ota]), [day1_ota])
    [decision_id] = result1.touched_decision_ids

    day2_ota = world.lifecycle_ota.evaluate(DAY_2)
    assert day2_ota.status.value == "CLEAR"
    ctx2 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    service.sync(ctx2, PriorityService().rank(ctx2, [day2_ota]), [day2_ota])

    body = api_client.get(detail_url(world.tenant.property.id, decision_id)).json()
    assert body["status"] == "RESOLVED"
    recommendation = body["recommendation"]
    assert recommendation["status"] == "NOT_AVAILABLE"
    assert recommendation["primary_action"] is None
    assert recommendation["confidence"] is None


# --- NOT_AVAILABLE, via a real INSUFFICIENT_DATA re-evaluation -----------------------------------


def test_golden_not_available_via_real_insufficient_data_reevaluation(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Real Day-1 TRIGGERED pickup, then a real Day-2 re-observation with no lead-7 historical
    curves (the exact mechanism `test_decision_api_golden.py`'s own Day-2 scenario uses) - the
    real `RevenueDecisionService` genuinely returns INSUFFICIENT_DATA; the Decision stays OPEN
    (INSUFFICIENT_DATA never resolves) but its recommendation must still be NOT_AVAILABLE."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)

    day1_context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    pickup, occupancy = world.priority_world.revenue_signals()
    day1_evaluations: list[SourceEvaluation] = [pickup, occupancy]
    day1_ranking = PriorityService().rank(day1_context, day1_evaluations)
    day1_result = DecisionService(db_session, tenant_ctx).sync(
        day1_context, day1_ranking, day1_evaluations
    )
    memory = DecisionMemoryService(db_session, tenant_ctx)
    pickup_decision_id = next(
        did
        for did in day1_result.touched_decision_ids
        if memory.get_decision(did).decision_type is PriorityDecisionType.REV_PICKUP_LOW  # type: ignore[union-attr]
    )

    day2 = DAY_1 + timedelta(days=7)
    row = snap(world.tenant, day2, STAY_DATE, 22, available=40)
    add_snapshots(db_session, world.tenant, [row])
    db_session.commit()
    revenue_service = RevenueDecisionService(db_session, world.tenant.context)
    day2_signals = revenue_service.evaluate_revenue_signals(row["id"])
    assert day2_signals.pickup_low.status.value == "INSUFFICIENT_DATA"

    day2_context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, day2)
    day2_evaluations: list[SourceEvaluation] = [
        day2_signals.pickup_low,
        day2_signals.occupancy_risk,
    ]
    day2_ranking = PriorityService().rank(day2_context, day2_evaluations)
    DecisionService(db_session, tenant_ctx).sync(day2_context, day2_ranking, day2_evaluations)

    body = api_client.get(detail_url(world.tenant.property.id, pickup_decision_id)).json()
    assert body["status"] == "OPEN"  # INSUFFICIENT_DATA never resolves an OPEN decision
    recommendation = body["recommendation"]
    assert recommendation["status"] == "NOT_AVAILABLE"
    assert recommendation["primary_action"] is None


# --- REOPENED: the recommendation reflects ONLY the latest observation ---------------------------


def test_golden_reopened_recommendation_reflects_latest_observation_only(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """OPENED (Day1, 90% OTA) -> RESOLVED (Day2, 20% OTA, CLEAR) -> REOPENED (Day3, 90% OTA
    again) - the real `LifecycleOtaWorld`'s own three calendar zones. The recommendation after
    Day3 must be AVAILABLE again, built from Day3's OWN real facts - never Day1's stale ones,
    even though both days are structurally TRIGGERED with the same 90/10 split."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    service = DecisionService(db_session, tenant_ctx)
    memory = DecisionMemoryService(db_session, tenant_ctx)

    day1_ota = world.lifecycle_ota.evaluate(DAY_1)
    ctx1 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    result1 = service.sync(ctx1, PriorityService().rank(ctx1, [day1_ota]), [day1_ota])
    [decision_id] = result1.touched_decision_ids

    day2_ota = world.lifecycle_ota.evaluate(DAY_2)
    ctx2 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_2)
    service.sync(ctx2, PriorityService().rank(ctx2, [day2_ota]), [day2_ota])

    day3_ota = world.lifecycle_ota.evaluate(DAY_3)
    assert day3_ota.status.value == "TRIGGERED"
    ctx3 = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_3)
    service.sync(ctx3, PriorityService().rank(ctx3, [day3_ota]), [day3_ota])

    day3_observation = memory.get_latest_observation(decision_id)
    assert day3_observation is not None
    expected_ota_share = canonical_text(day3_ota.ota_share_exact)

    body = api_client.get(detail_url(world.tenant.property.id, decision_id)).json()
    assert body["status"] == "OPEN"
    assert body["latest_observation"]["lifecycle_transition"] == "REOPENED"
    recommendation = body["recommendation"]
    assert recommendation["status"] == "AVAILABLE"
    primary = recommendation["primary_action"]
    assert primary is not None
    assert primary["supporting_facts"]["ota_share_exact"] == expected_ota_share
    # Day1 and Day3 share the same 90/10 split, so this is NOT a value-difference proof by
    # itself - the identical-value case is exactly why `test_golden_ota_lifecycle_history_...`
    # already proves (in `test_decision_api_golden.py`) that Day3 is a genuinely NEW, REOPENED
    # observation and not a reuse of Day1's row; this test only adds that the recommendation is
    # read off THAT (latest) row, never Day1's.
    assert day3_observation.facts_payload["ota_share_exact"] == expected_ota_share


# --- golden independence: the fingerprint, recomputed from the ground-truth DB row ---------------


def test_golden_fingerprint_matches_independently_recomputed_value(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Recomputes the expected SHA-256 by hand, from the real persisted `Decision`/
    `DecisionObservation` row - stdlib `json.dumps`/`hashlib.sha256` only, never calling
    `app.modules.recommendations.fingerprint.recommendation_fingerprint()` itself."""
    world = _golden_world(factory, authenticated_as, db_session)
    tenant_ctx = TenantContext(world.tenant.workspace.id)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    cost = world.priority_world.cost_anomaly()
    ranking = PriorityService().rank(context, [cost])
    result = DecisionService(db_session, tenant_ctx).sync(context, ranking, [cost])
    [decision_id] = result.touched_decision_ids

    memory = DecisionMemoryService(db_session, tenant_ctx)
    decision = memory.get_decision(decision_id)
    observation = memory.get_latest_observation(decision_id)
    assert decision is not None and observation is not None
    facts = observation.facts_payload

    primary_action_payload = {
        "action_code": "REVIEW_COST_DRIVERS",
        "category": "REVIEW_COST_DRIVERS",
        "scope": "COST_PERIOD",
        "supporting_facts": {
            "actual_cpor_exact": facts["actual_cpor_exact"],
            "expected_cpor_exact": facts["expected_cpor_exact"],
        },
        "risk_notes": [],
    }
    supporting_checks_payload = [
        {
            "action_code": "CHECK_RECENT_COST_ENTRIES",
            "category": "VERIFY_DATA",
            "scope": "COST_PERIOD",
            "supporting_facts": {"delta_cpor_exact": facts["delta_cpor_exact"]},
            "risk_notes": [],
        },
        {
            "action_code": "CHECK_VOLUME_VS_COST",
            "category": "VERIFY_DATA",
            "scope": "COST_PERIOD",
            "supporting_facts": {"delta_percent_exact": facts["delta_percent_exact"]},
            "risk_notes": [],
        },
    ]
    expected_payload = {
        "recommendation_version": "recommendation-engine-v1",
        "decision_type": "COST_CPOR_ANOMALY",
        "identity_version": decision.identity_version,
        "identity_key": decision.identity_key,
        "source_evaluation_fingerprint": observation.source_evaluation_fingerprint,
        "status": "AVAILABLE",
        "primary_action": primary_action_payload,
        "supporting_checks": supporting_checks_payload,
        "confidence": canonical_text(observation.confidence_score),
    }
    encoded = json.dumps(expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected_fingerprint = hashlib.sha256(encoded.encode("ascii")).hexdigest()

    body = api_client.get(detail_url(world.tenant.property.id, decision_id)).json()
    assert body["recommendation"]["fingerprint"] == expected_fingerprint

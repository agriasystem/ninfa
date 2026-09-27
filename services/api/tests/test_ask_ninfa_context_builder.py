"""Gate 18 review items 1-14: `AskDecisionContextBuilder`, pure and direct (no HTTP), against real
persisted `Decision`/`DecisionObservation` rows built via `tests.decision_support.sync_run` - the
same pattern `test_recommendation_engine.py` uses for its own pure-engine tests.
"""

from dataclasses import fields
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.context_builder import AskDecisionContextBuilder
from app.modules.ai.ask_ninfa.types import AskDecisionContext, AskObservationContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import RevenueDecisionType
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.recommendations.engine import RecommendationEngine
from tests.decision_support import (
    Evaluation,
    cost_evaluation,
    labor_evaluation,
    ota_evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _context_for(db_session: Session, tenant: Tenant, decision_id: UUID) -> AskDecisionContext:
    tenant_ctx = TenantContext(tenant.workspace.id)
    memory = DecisionMemoryService(db_session, tenant_ctx)
    decision = memory.get_decision(decision_id)
    latest = memory.get_latest_observation(decision_id)
    assert decision is not None and latest is not None
    recommendation = RecommendationEngine().evaluate(decision, latest)
    history_page = memory.get_history_page_desc(decision_id, limit=10, after=None)
    history = [row.observation for row in history_page.items]
    return AskDecisionContextBuilder().build(decision, latest, recommendation, history)


def _open_decision(
    db_session: Session, tenant: Tenant, evaluation: Evaluation, as_of: date
) -> UUID:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    return decision_id


# --- 1-5: one context per real decision type ------------------------------------------------------


def test_1_pickup_context(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_type == "REV_PICKUP_LOW"
    assert context.target == {"stay_date": STAY.isoformat()}
    assert "missing_rooms" in context.latest.facts


def test_2_occupancy_context(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_type == "REV_OCCUPANCY_RISK"
    assert "occupancy_gap_pp_exact" in context.latest.facts


def test_3_ota_context(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = ota_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_type == "REV_OTA_DEPENDENCY"
    # No human-relevant target field exists for OTA beyond the (excluded) data source id.
    assert context.target == {}
    assert "ota_share_exact" in context.latest.facts


def test_4_cost_context(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=D1,
        cost_category=CostCategory.LAUNDRY,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_type == "COST_CPOR_ANOMALY"
    assert context.target == {
        "period_start": D1.isoformat(),
        "cost_category": "LAUNDRY",
        "currency": "EUR",
    }
    assert "actual_cpor_exact" in context.latest.facts


def test_5_labor_context(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    labor_data_source_id = factory.data_source(tenant.property).id
    evaluation = labor_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        labor_data_source_id=labor_data_source_id,
        target_work_date=D1,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_type == "LABOR_OVERSTAFFING"
    assert context.target == {"work_date": D1.isoformat(), "labor_category": "HOUSEKEEPING"}
    assert "scheduled_hours_exact" in context.latest.facts


# --- 6-9: decision status, latest facts, evidence, recommendation ---------------------------------


def test_6_decision_status(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.decision_status == "OPEN"
    assert context.first_seen_local_date == D1.isoformat()
    assert context.episode_count == 1
    assert context.resolved_local_date is None


def test_7_latest_facts_whitelisted(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert context.latest.facts["stay_date"] == STAY.isoformat()
    assert context.latest.source_status == "TRIGGERED"
    assert context.latest.lifecycle_transition == "OPENED"


def test_8_evidence_whitelisted(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    assert "confidence_score" in context.latest.evidence
    assert "revenue_gap_proxy" in context.latest.evidence


def test_9_recommendation_context_matches_real_engine(
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
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    # This minimal fixture never sets actual_pickup/expected_pickup (see Gate 16's own docs),
    # so the real engine genuinely reaches INSUFFICIENT_CONTEXT here - exactly what proves the
    # context builder copies the engine's REAL status, never a hardcoded AVAILABLE.
    assert context.recommendation.status == "INSUFFICIENT_CONTEXT"
    assert context.recommendation.primary_action is None
    assert context.recommendation.requires_human_review is True


# --- 10-11: bounded, chronological history --------------------------------------------------------


def test_10_11_history_bounded_and_chronological(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    decision_id: UUID | None = None
    for offset in range(12):
        evaluation = revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY,
            snapshot_local_date=date(2026, 8, 1 + offset),
            confidence_score=Decimal(f"{50 + offset}.00"),
        )
        decision_id = _open_decision(db_session, tenant, evaluation, date(2026, 8, 1 + offset))
    assert decision_id is not None

    context = _context_for(db_session, tenant, decision_id)

    assert len(context.history) == 10  # MAX_HISTORY_OBSERVATIONS, never all 12
    dates = [observation.as_of_local_date for observation in context.history]
    assert dates == sorted(dates)  # chronological, oldest -> newest
    # The 10 most RECENT observations are kept (offsets 2..11), never the oldest 10.
    assert dates[0] == date(2026, 8, 3).isoformat()
    assert dates[-1] == date(2026, 8, 12).isoformat()
    # The latest observation is also the final entry of history - the same current row, twice,
    # intentionally (see `AskDecisionContext`'s own docstring).
    assert context.history[-1].confidence == context.latest.confidence


# --- 12-13: exact Decimal preserved -------------------------------------------------------------


def test_12_13_exact_decimal_confidence_preserved(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        confidence_score=Decimal("81.23"),
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    context = _context_for(db_session, tenant, decision_id)

    # "81.23" remains "81.23" - never divided/multiplied by 100 (see the confidence-scale
    # convention this same value must respect everywhere it is read - `[[ninfa-confidence-scale]]`
    # in spirit, here as a real regression test).
    assert context.latest.confidence == "81.23"


# --- 14: no raw ORM serialization -----------------------------------------------------------------


def test_14_no_raw_orm_field_names_leak_into_the_context_shape(
    db_session: Session, factory: BookingFactory
) -> None:
    """Structural: `AskDecisionContext`/`AskObservationContext` never carry a `decision_id`,
    `observation_id`, `workspace_id`, `property_id`, or any `*fingerprint*`/`*_data_source_id`
    field name - these dataclasses were hand-written, not derived via `dataclasses.asdict()` of an
    ORM row, and this test pins that shape directly."""
    context_field_names = {f.name for f in fields(AskDecisionContext)}
    observation_field_names = {f.name for f in fields(AskObservationContext)}
    forbidden = {
        "decision_id",
        "observation_id",
        "workspace_id",
        "property_id",
        "id",
        "source_evaluation_fingerprint",
        "source_target_key",
        "memory_version",
        "priority_candidate_fingerprint",
        "identity_key",
        "identity_version",
        "identity_payload",
    }
    assert context_field_names.isdisjoint(forbidden)
    assert observation_field_names.isdisjoint(forbidden)

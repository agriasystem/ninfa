"""Gate 19.1 (ADR 0026): the exact live case that exposed the original technical leak -

    20 booked / 40 available, forecast 28, expected 34, shortfall 6, occupancy gap 15pp,
    revenue proxy 600, confidence 100, recommendation REVIEW_DEMAND_POSITIONING

reconstructed deterministically through the real pipeline (a real `RevenueDecisionEvaluation` ->
`DecisionService.sync()` -> the real `RecommendationEngine` -> `AskDecisionContextBuilder`), never
hand-typed as a fixture the context builder itself produced - the whole point is proving the REAL
engine's own output, once run through Gate 19.1's semantic context, carries no raw engine
identifier at all.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.context_builder import AskDecisionContextBuilder
from app.modules.ai.ask_ninfa.serialization import serialize_context
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import (
    RULES_VERSION,
    EvaluationStatus,
    OccupancyFacts,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)
from app.modules.recommendations.engine import RecommendationEngine
from tests.decision_support import fp, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)

_FORBIDDEN_RAW_STRINGS = (
    "forecast_rooms",
    "occupancy_gap_pp_exact",
    "reason_codes",
    "TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL",
    "REVIEW_DEMAND_POSITIONING",
    "REVIEW_AVAILABILITY",
)


def _occupancy_golden_evaluation(tenant: Tenant) -> RevenueDecisionEvaluation:
    target_snapshot_id = uuid4()
    facts = OccupancyFacts(
        current_rooms_on_books=20,
        rooms_available=40,
        forecast_rooms=Decimal(28),
        expected_final_rooms=Decimal(34),
        room_shortfall=Decimal(6),
        occupancy_gap_pp_exact=Decimal("15.00"),
        gap_condition=True,
        shortfall_condition=True,
    )
    return RevenueDecisionEvaluation(
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
        status=EvaluationStatus.TRIGGERED,
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        target_snapshot_id=target_snapshot_id,
        target_baseline_id=uuid4(),
        snapshot_local_date=D1,
        stay_date=STAY,
        lead_time_days=(STAY - D1).days,
        confidence_score=Decimal("100.00"),
        rules_version=RULES_VERSION,
        calculation_fingerprint=fp("occupancy-golden"),
        reason_codes=(),
        facts=facts,
        evidence_snapshot_ids=(target_snapshot_id,),
        revenue_gap_proxy=Decimal("600.00"),
        reference_adr=Decimal("100.00"),
        reference_adr_source=ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
    )


def _open_decision(db_session: Session, tenant: Tenant) -> UUID:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    evaluation = _occupancy_golden_evaluation(tenant)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    return decision_id


def test_occupancy_golden_case_reaches_the_real_engine_as_expected(
    db_session: Session, factory: BookingFactory
) -> None:
    """Sanity check on the fixture itself, BEFORE checking Ask NINFA's own context: the real
    Recommendation Engine really does select REVIEW_DEMAND_POSITIONING for this exact case - never
    assumed, always derived from the real engine call."""
    tenant = factory.tenant()
    decision_id = _open_decision(db_session, tenant)
    tenant_ctx = TenantContext(tenant.workspace.id)
    memory = DecisionMemoryService(db_session, tenant_ctx)
    decision = memory.get_decision(decision_id)
    latest = memory.get_latest_observation(decision_id)
    assert decision is not None and latest is not None

    recommendation = RecommendationEngine().evaluate(decision, latest)

    assert recommendation.primary_action is not None
    assert recommendation.primary_action.action_code.value == "REVIEW_DEMAND_POSITIONING"


def test_occupancy_golden_case_serialized_context_carries_no_raw_engine_string(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    decision_id = _open_decision(db_session, tenant)
    tenant_ctx = TenantContext(tenant.workspace.id)
    memory = DecisionMemoryService(db_session, tenant_ctx)
    decision = memory.get_decision(decision_id)
    latest = memory.get_latest_observation(decision_id)
    assert decision is not None and latest is not None
    recommendation = RecommendationEngine().evaluate(decision, latest)
    history_page = memory.get_history_page_desc(decision_id, limit=10, after=None)
    history = [row.observation for row in history_page.items]

    context = AskDecisionContextBuilder().build(decision, latest, recommendation, history)
    serialized = serialize_context(context)

    for forbidden in _FORBIDDEN_RAW_STRINGS:
        assert forbidden not in serialized

    # The MEANING of the data is still there, just relabeled - never silently dropped.
    assert context.decision_label == "Rischio occupazione"
    fact_by_label = {point.label: point for point in context.latest.facts}
    assert fact_by_label["Previsione camere"].value == "28"
    assert fact_by_label["Atteso a fine finestra"].value == "34"
    assert fact_by_label["Scarto camere"].value == "6"
    assert fact_by_label["Scarto occupazione"].value == "15"
    assert context.latest.confidence == "100"
    assert context.recommendation.primary_action is not None
    assert context.recommendation.primary_action.title == "Rivedi il posizionamento della data"
    evidence_by_label = {point.label: point for point in context.latest.evidence}
    proxy_label = next(label for label in evidence_by_label if "Impatto sui ricavi" in label)
    assert evidence_by_label[proxy_label].value == "600"

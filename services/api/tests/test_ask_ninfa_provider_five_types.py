"""Gate 19 review items 71-75: all five real decision types, through the real
`AnthropicLanguageModelProvider` (fake transport only) - the provider receives ONLY Gate 18's own
minimized `AskDecisionContext`, serialized, never anything more.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.context_builder import AskDecisionContextBuilder
from app.modules.ai.ask_ninfa.serialization import serialize_context
from app.modules.ai.gateway.protocol import LanguageModelRequest
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.recommendations.engine import RecommendationEngine
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    answered_message,
    provider_with_fake_transport,
)
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


def _open_decision(
    db_session: Session, tenant: Tenant, evaluation: Evaluation, as_of: date
) -> UUID:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    return decision_id


def _serialized_context_sent_to_provider(
    db_session: Session, tenant: Tenant, decision_id: UUID
) -> str:
    tenant_ctx = TenantContext(tenant.workspace.id)
    memory = DecisionMemoryService(db_session, tenant_ctx)
    decision = memory.get_decision(decision_id)
    latest = memory.get_latest_observation(decision_id)
    assert decision is not None and latest is not None
    recommendation = RecommendationEngine().evaluate(decision, latest)
    history_page = memory.get_history_page_desc(decision_id, limit=10, after=None)
    history = [row.observation for row in history_page.items]
    ask_context = AskDecisionContextBuilder().build(decision, latest, recommendation, history)

    transport = FakeMessagesTransport(response=answered_message())
    provider = provider_with_fake_transport(transport)
    request = LanguageModelRequest(
        system_instructions="ISTRUZIONI",
        context=serialize_context(ask_context),
        question="Perché me lo stai mostrando?",
        max_answer_chars=1200,
    )
    provider.generate(request)

    [message] = transport.last_call["messages"]
    blocks_text = "\n".join(block["text"] for block in message["content"])
    return blocks_text


_FORBIDDEN_MARKERS = (
    "decision_id",
    "workspace_id",
    "property_id",
    "booking_data_source_id",
    "labor_data_source_id",
    "source_evaluation_fingerprint",
    "observation_id",
    "identity_key",
    "identity_version",
)


def test_71_pickup_context_reaches_the_provider_minimized(
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
    blocks_text = _serialized_context_sent_to_provider(db_session, tenant, decision_id)

    assert '"decision_type": "REV_PICKUP_LOW"' in blocks_text
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blocks_text


def test_72_occupancy_context_reaches_the_provider_minimized(
    db_session: Session, factory: BookingFactory
) -> None:
    from app.modules.intelligence.revenue.types import RevenueDecisionType

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
    blocks_text = _serialized_context_sent_to_provider(db_session, tenant, decision_id)

    assert '"decision_type": "REV_OCCUPANCY_RISK"' in blocks_text
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blocks_text


def test_73_ota_context_reaches_the_provider_minimized(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = ota_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    blocks_text = _serialized_context_sent_to_provider(db_session, tenant, decision_id)

    assert '"decision_type": "REV_OTA_DEPENDENCY"' in blocks_text
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blocks_text


def test_74_cost_context_reaches_the_provider_minimized(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    blocks_text = _serialized_context_sent_to_provider(db_session, tenant, decision_id)

    assert '"decision_type": "COST_CPOR_ANOMALY"' in blocks_text
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blocks_text


def test_75_labor_context_reaches_the_provider_minimized(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    labor_data_source_id = factory.data_source(tenant.property).id
    evaluation = labor_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        labor_data_source_id=labor_data_source_id,
        target_work_date=D1,
    )
    decision_id = _open_decision(db_session, tenant, evaluation, D1)
    blocks_text = _serialized_context_sent_to_provider(db_session, tenant, decision_id)

    assert '"decision_type": "LABOR_OVERSTAFFING"' in blocks_text
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blocks_text

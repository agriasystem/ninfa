"""Gate 19 review items 76-82: the same PII/fingerprint scan Gate 18 already proved for the
context builder itself, now proved for what actually reaches the (fake) Anthropic transport - the
full path a real request would take.
"""

from collections.abc import Iterator
from dataclasses import replace
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
from tests.decision_support import cost_evaluation, labor_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)

_OPEN_FIELD_PROBE = "OPEN_STRING_FIELD_PROBE_NOT_PII"

_FORBIDDEN_SENTINELS = (
    "PII_GUEST_NAME_SENTINEL",  # 76
    "PII_EMAIL_SENTINEL@example.com",  # 76
    "PII_PHONE_SENTINEL",  # 76
    "PII_EMPLOYEE_SENTINEL",  # 77
    "PII_SUPPLIER_NAME_SENTINEL",  # 78
    "PII_RAW_INVOICE_SENTINEL",  # 79
    "SESSION_TOKEN_SENTINEL",  # 80
    "AUTH_COOKIE_SENTINEL",  # 80
)

_FORBIDDEN_TECHNICAL_MARKERS = (  # 81
    "source_evaluation_fingerprint",
    "source_target_key",
    "memory_version",
    "identity_key",
    "identity_version",
    "candidate_fingerprint",
)

_FORBIDDEN_ORM_MARKERS = (  # 82: no raw ORM serialization
    "_sa_instance_state",
    "<Decision",
    "<DecisionObservation",
)


def _flatten_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten_strings(item)


def test_privacy_scan_of_what_actually_reaches_the_provider(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    labor_source: UUID = factory.data_source(tenant.property).id

    cost = replace(
        cost_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            target_period_start=D1,
            currency=_OPEN_FIELD_PROBE,
        ),
        rules_version=_OPEN_FIELD_PROBE,
    )
    labor = replace(
        labor_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            labor_data_source_id=labor_source,
            target_work_date=D1,
        ),
        cost_currency=_OPEN_FIELD_PROBE,
        rules_version=_OPEN_FIELD_PROBE,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_ctx = TenantContext(tenant.workspace.id)
    outcome = sync_run(db_session, tenant_ctx, context, [cost, labor])

    memory = DecisionMemoryService(db_session, tenant_ctx)
    all_strings: list[str] = []
    for decision_id in outcome.result.touched_decision_ids:
        decision = memory.get_decision(decision_id)
        latest = memory.get_latest_observation(decision_id)
        assert decision is not None and latest is not None
        recommendation = RecommendationEngine().evaluate(decision, latest)
        ask_context = AskDecisionContextBuilder().build(decision, latest, recommendation, [latest])
        serialized = serialize_context(ask_context)

        transport = FakeMessagesTransport(response=answered_message())
        provider = provider_with_fake_transport(transport)
        provider.generate(
            LanguageModelRequest(
                system_instructions="ISTRUZIONI",
                context=serialized,
                question="Perché me lo stai mostrando?",
                max_answer_chars=1200,
            )
        )
        [message] = transport.last_call["messages"]
        for block in message["content"]:
            all_strings.append(block["text"])
        all_strings.extend(_flatten_strings({"blob": serialized}))

    # Sanity (mirrors Gate 18's own privacy test): the probe IS present, proving the scan reaches
    # real, whitelisted content.
    assert any(_OPEN_FIELD_PROBE in value for value in all_strings)

    for sentinel in _FORBIDDEN_SENTINELS:
        assert not [v for v in all_strings if sentinel in v], sentinel
    for marker in _FORBIDDEN_TECHNICAL_MARKERS:
        assert not [v for v in all_strings if marker in v], marker
    for marker in _FORBIDDEN_ORM_MARKERS:
        assert not [v for v in all_strings if marker in v], marker

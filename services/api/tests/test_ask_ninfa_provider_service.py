"""Gate 19 review items 50-56: `AskNinfaService` (Gate 18, unmodified) wired to a REAL
`AnthropicLanguageModelProvider` (fake transport only) - end to end, still vendor-agnostic.
"""

import inspect

from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import (
    AskActionContext,
    AskDecisionContext,
    AskObservationContext,
    AskRecommendationContext,
    AskStatus,
)
from app.modules.ai.gateway.anthropic_provider import AnthropicLanguageModelProvider
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelProvider
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    make_message,
    provider_with_fake_transport,
)

_CONTEXT = AskDecisionContext(
    decision_type="REV_PICKUP_LOW",
    decision_status="OPEN",
    first_seen_local_date="2026-08-01",
    last_seen_local_date="2026-08-01",
    last_evaluated_local_date="2026-08-01",
    resolved_local_date=None,
    episode_count=1,
    target={"stay_date": "2026-08-15"},
    latest=AskObservationContext(
        as_of_local_date="2026-08-01",
        source_status="TRIGGERED",
        lifecycle_transition="OPENED",
        reason_codes=("TRIGGER_PICKUP_SHORTFALL",),
        confidence="81.23",
        priority_rank=1,
        facts={"actual_pickup": 3, "expected_pickup": "7.50"},
        evidence={"confidence_score": "81.23"},
    ),
    recommendation=AskRecommendationContext(
        status="AVAILABLE",
        primary_action=AskActionContext(
            action_code="REVIEW_PRICING_AND_AVAILABILITY",
            category="REVIEW_PRICING",
            risk_notes=("PRICING_CHANGE_MAY_AFFECT_REVENUE",),
        ),
        supporting_checks=(),
        requires_human_review=True,
    ),
    history=(),
)


# --- 50: the real adapter structurally satisfies the Protocol ------------------------------------


def test_50_anthropic_provider_satisfies_the_protocol() -> None:
    payload = {"status": "ANSWERED", "answer": "x", "grounding_refs": [], "limitations": []}
    provider: LanguageModelProvider = provider_with_fake_transport(
        FakeMessagesTransport(response=make_message(payload))
    )
    assert isinstance(provider, AnthropicLanguageModelProvider)
    assert hasattr(provider, "generate")
    assert callable(provider.generate)


# --- 51: AskNinfaService itself is untouched by this gate -----------------------------------------


def test_51_ask_ninfa_service_constructor_is_still_typed_against_the_protocol_only() -> None:
    # `LanguageModelProvider` and `AnthropicLanguageModelProvider` are distinct classes, so this
    # single identity check already proves the constructor was never narrowed to the concrete
    # adapter type.
    signature = inspect.signature(AskNinfaService.__init__)
    annotation = signature.parameters["provider"].annotation
    assert annotation is LanguageModelProvider


# --- 52-53: real roundtrips through the full service ----------------------------------------------


def test_52_answered_roundtrip_through_the_real_adapter() -> None:
    transport = FakeMessagesTransport(
        response=make_message(
            {
                "status": "ANSWERED",
                "answer": "Il pickup è sotto le attese.",
                "grounding_refs": ["LATEST_FACTS"],
                "limitations": [],
            }
        )
    )
    provider = provider_with_fake_transport(transport)
    service = AskNinfaService(provider)

    result = service.ask(_CONTEXT, "Perché me lo stai mostrando?")

    assert result.status is AskStatus.ANSWERED
    assert result.answer == "Il pickup è sotto le attese."


def test_53_insufficient_context_roundtrip_through_the_real_adapter() -> None:
    transport = FakeMessagesTransport(
        response=make_message(
            {
                "status": "INSUFFICIENT_CONTEXT",
                "answer": "Non posso stabilire un valore esatto con i dati disponibili.",
                "grounding_refs": [],
                "limitations": [],
            }
        )
    )
    provider = provider_with_fake_transport(transport)
    service = AskNinfaService(provider)

    result = service.ask(_CONTEXT, "Di quanto dovrei abbassare il prezzo?")

    assert result.status is AskStatus.INSUFFICIENT_CONTEXT


# --- 54: a provider failure fails closed through the full service ---------------------------------


def test_54_provider_failure_fails_closed_through_the_real_adapter() -> None:
    transport = FakeMessagesTransport(error=LanguageModelUnavailableError("simulated failure"))
    provider = provider_with_fake_transport(transport)
    service = AskNinfaService(provider)

    result = service.ask(_CONTEXT, "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None


# --- 55-56: no mutation, no conversation persistence anywhere in this path ------------------------


def test_55_56_service_and_adapter_expose_no_write_or_persistence_capability() -> None:
    """Structural: neither `AskNinfaService` nor `AnthropicLanguageModelProvider` import a
    database session type, a repository, or anything named like a conversation/message model -
    there is nothing in this call path that COULD write anything."""
    import app.modules.ai.ask_ninfa.service as service_module
    import app.modules.ai.gateway.anthropic_provider as provider_module

    forbidden_tokens = (
        "Session",
        "session.add",
        "session.commit",
        "Conversation",
        "Message(",
        "sqlalchemy",
    )
    for module in (service_module, provider_module):
        source = inspect.getsource(module)
        for forbidden in forbidden_tokens:
            assert forbidden not in source, (module.__name__, forbidden)

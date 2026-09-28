"""Gate 19 review items 50-56: `AskNinfaService` (Gate 18, unmodified) wired to a REAL
`AnthropicLanguageModelProvider` (fake transport only) - end to end, still vendor-agnostic.
"""

import inspect

from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.anthropic_provider import AnthropicLanguageModelProvider
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelProvider
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    make_message,
    provider_with_fake_transport,
)
from tests.ask_ninfa_support import sample_ask_context

_CONTEXT = sample_ask_context()


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

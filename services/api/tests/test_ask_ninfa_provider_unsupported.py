"""Gate 19 review items 83-85: an exact price/staffing question, through the REAL adapter, can
resolve to `INSUFFICIENT_CONTEXT` - and neither the adapter nor the service ever adds a number of
their own to whatever the (fake, here) model actually said.
"""

from app.modules.ai.ask_ninfa.guardrails import classify_refusal
from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import AskStatus
from tests.anthropic_provider_support import (
    FakeMessagesTransport,
    make_message,
    provider_with_fake_transport,
)
from tests.ask_ninfa_support import sample_ask_context

_CONTEXT = sample_ask_context()


# --- 83: exact price decrease can return INSUFFICIENT_CONTEXT ------------------------------------


def test_83_price_decrease_question_reaches_the_model_and_can_be_insufficient() -> None:
    question = "Di quanto dovrei abbassare il prezzo per questa data?"
    # Never REFUSED - domain-relevant, not an execution command.
    assert classify_refusal(question) is None

    canned_answer = "Non posso stabilire un valore esatto con i dati disponibili."
    transport = FakeMessagesTransport(
        response=make_message(
            {
                "status": "INSUFFICIENT_CONTEXT",
                "answer": canned_answer,
                "grounding_refs": [],
                "limitations": ["NINFA non include un motore di ottimizzazione del prezzo."],
            }
        )
    )
    service = AskNinfaService(provider_with_fake_transport(transport))

    result = service.ask(_CONTEXT, question)

    assert result.status is AskStatus.INSUFFICIENT_CONTEXT
    assert result.answer == canned_answer  # passed through verbatim, never rewritten


# --- 84: exact staffing cut can return INSUFFICIENT_CONTEXT ---------------------------------------


def test_84_exact_staffing_cut_question_reaches_the_model_and_can_be_insufficient_context() -> None:
    question = "Quante ore dovrei tagliare da questo turno?"
    assert classify_refusal(question) is None

    canned_answer = "Non posso stabilire un numero esatto di ore da ridurre con i dati disponibili."
    transport = FakeMessagesTransport(
        response=make_message(
            {
                "status": "INSUFFICIENT_CONTEXT",
                "answer": canned_answer,
                "grounding_refs": [],
                "limitations": [],
            }
        )
    )
    service = AskNinfaService(provider_with_fake_transport(transport))

    result = service.ask(_CONTEXT, question)

    assert result.status is AskStatus.INSUFFICIENT_CONTEXT
    assert result.answer == canned_answer


# --- 85: no fabricated number is added by the adapter or the service -----------------------------


def test_85_adapter_and_service_never_add_a_number_to_the_models_own_answer() -> None:
    """The adapter/service pipeline is a pure pass-through of the model's own `answer` string
    (truncation aside) - it never appends, computes, or interpolates a figure of its own into it,
    for ANY status."""
    canned_answer = "Ecco la spiegazione richiesta, senza cifre aggiuntive."
    transport = FakeMessagesTransport(
        response=make_message(
            {
                "status": "ANSWERED",
                "answer": canned_answer,
                "grounding_refs": ["LATEST_FACTS"],
                "limitations": [],
            }
        )
    )
    service = AskNinfaService(provider_with_fake_transport(transport))

    result = service.ask(_CONTEXT, "Perché me lo stai mostrando?")

    assert result.answer == canned_answer

"""Gate 19 review items 83-85: an exact price/staffing question, through the REAL adapter, can
resolve to `INSUFFICIENT_CONTEXT` - and neither the adapter nor the service ever adds a number of
their own to whatever the (fake, here) model actually said.
"""

from app.modules.ai.ask_ninfa.guardrails import classify_refusal
from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import (
    AskActionContext,
    AskDecisionContext,
    AskObservationContext,
    AskRecommendationContext,
    AskStatus,
)
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
        evidence={},
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

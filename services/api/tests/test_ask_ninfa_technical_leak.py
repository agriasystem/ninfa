"""Gate 19.1 (ADR 0026): the output safety validator (`app.modules.ai.ask_ninfa.technical_leak`)
and its wiring into `answer_validation.validate_model_answer` - fail closed to `AskStatus.
UNAVAILABLE`, never a post-hoc rewrite, never a second provider call.
"""

import dataclasses

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer
from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.technical_leak import contains_technical_leak
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider, sample_ask_context

_NATURAL_ANSWER = (
    "NINFA ti sta mostrando questa decisione perché, per la data indicata, le camere prenotate "
    "risultano sotto le attese rispetto allo storico. Può essere utile rivedere prezzi e "
    "disponibilità per questa data. La decisione finale resta a te."
)


def _answer(text: str) -> LanguageModelAnswer:
    return LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED,
        answer=text,
        grounding_refs=("LATEST_FACTS",),
        limitations=(),
    )


# --- contains_technical_leak: closed identifiers -------------------------------------------------


def test_forecast_rooms_is_rejected() -> None:
    assert contains_technical_leak("Il valore di forecast_rooms è alto.") is True


def test_occupancy_gap_pp_exact_is_rejected() -> None:
    assert contains_technical_leak("Lo scarto è occupancy_gap_pp_exact.") is True


def test_rev_occupancy_risk_decision_type_is_rejected() -> None:
    assert contains_technical_leak("Questa è una REV_OCCUPANCY_RISK.") is True


def test_trigger_prefixed_reason_code_is_rejected() -> None:
    assert contains_technical_leak("Il motivo è TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL.") is True


def test_review_demand_positioning_action_code_is_rejected() -> None:
    assert contains_technical_leak("Ti consiglio REVIEW_DEMAND_POSITIONING.") is True


def test_a_normal_italian_answer_is_accepted() -> None:
    assert contains_technical_leak(_NATURAL_ANSWER) is False


# --- underscore-shaped tokens: narrow, never a generic word blocklist -----------------------------


def test_any_snake_case_shaped_token_is_rejected_even_if_not_in_the_closed_list() -> None:
    """Defense in depth for an identifier this module's closed list was not updated for (e.g. a
    future sixth decision type) - Italian prose never naturally joins words with an underscore."""
    assert contains_technical_leak("Il valore di un_campo_futuro è alto.") is True


def test_a_long_answer_with_no_underscore_or_known_code_is_never_flagged() -> None:
    long_answer = _NATURAL_ANSWER * 3
    assert contains_technical_leak(long_answer) is False


def test_ordinary_capitalized_italian_words_are_never_flagged() -> None:
    """Whole-word, case-sensitive matching against the closed identifier set - an ordinary
    capitalized Italian sentence start is never mistaken for a technical enum value."""
    assert contains_technical_leak("Aperta da tre giorni, la situazione è stabile.") is False


# --- wired into validate_model_answer: fails the WHOLE answer closed ------------------------------


def test_leak_in_the_answer_fails_the_whole_response_closed() -> None:
    raw = _answer("Il pickup dipende da forecast_rooms e dal relativo scostamento.")
    assert validate_model_answer(raw) is None


def test_leak_in_a_limitation_also_fails_closed() -> None:
    raw = LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED,
        answer=_NATURAL_ANSWER,
        grounding_refs=("LATEST_FACTS",),
        limitations=("Non è disponibile un valore per REV_OTA_DEPENDENCY.",),
    )
    assert validate_model_answer(raw) is None


def test_a_clean_natural_answer_still_validates_normally() -> None:
    validated = validate_model_answer(_answer(_NATURAL_ANSWER))
    assert validated is not None
    assert validated.status is AskStatus.ANSWERED
    assert validated.answer == _NATURAL_ANSWER


# --- end to end through AskNinfaService: UNAVAILABLE, never a rewrite or a second call -----------


def test_service_fails_closed_to_unavailable_on_a_leaking_provider_answer() -> None:
    leaking = dataclasses.replace(
        _answer(_NATURAL_ANSWER), answer="Il valore di occupancy_gap_pp_exact è 15."
    )
    provider = DeterministicFakeLanguageModelProvider(answer=leaking)
    service = AskNinfaService(provider)

    result = service.ask(sample_ask_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None
    # Exactly one provider call - no retry, no second call to "fix" the leaking answer.
    assert len(provider.requests) == 1

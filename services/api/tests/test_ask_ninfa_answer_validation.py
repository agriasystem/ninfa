"""Gate 18 review items 31-37: `AskNinfaService.ask()` against a
`DeterministicFakeLanguageModelProvider` - no HTTP, no database, exactly like
`test_recommendation_engine.py`'s own pure-engine posture.
"""

import dataclasses

from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import MAX_ANSWER_CHARS, AskStatus
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider, sample_ask_context

_context = sample_ask_context


def _answer(**overrides: object) -> LanguageModelAnswer:
    base = LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED,
        answer="Il pickup è sotto le attese: sono entrate 3 camere contro le 7.50 previste.",
        grounding_refs=("LATEST_FACTS",),
        limitations=(),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


# --- 31-33: a real, grounded answer is accepted with refs and limitations ------------------------


def test_31_32_33_grounded_answer_with_refs_and_limitations_is_answered() -> None:
    provider = DeterministicFakeLanguageModelProvider(
        answer=_answer(
            grounding_refs=("LATEST_FACTS", "RECOMMENDATION"), limitations=("Stima indicativa.",)
        )
    )
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.ANSWERED
    assert result.answer is not None and len(result.answer) > 0
    assert set(ref.value for ref in result.grounding_refs) == {"LATEST_FACTS", "RECOMMENDATION"}
    assert result.limitations == ("Stima indicativa.",)


def test_32_unrecognised_grounding_ref_is_dropped_not_crashed_on() -> None:
    provider = DeterministicFakeLanguageModelProvider(
        answer=_answer(grounding_refs=("LATEST_FACTS", "SOME_FUTURE_REF"))
    )
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.ANSWERED
    assert [ref.value for ref in result.grounding_refs] == ["LATEST_FACTS"]


def test_33_insufficient_context_status_from_the_model_is_preserved() -> None:
    provider = DeterministicFakeLanguageModelProvider(
        answer=_answer(
            status=ModelAnswerStatus.INSUFFICIENT_CONTEXT,
            answer="Non posso stabilire di quanto ridurre il prezzo con i dati disponibili.",
        )
    )
    result = AskNinfaService(provider).ask(_context(), "Di quanto devo abbassare il prezzo?")

    assert result.status is AskStatus.INSUFFICIENT_CONTEXT
    assert result.answer is not None


# --- 34: overlong answer fails closed, never silently truncated -----------------------------------


def test_34_overlong_answer_fails_closed_never_silently_truncated() -> None:
    """Gate 19.1b (ADR 0026's own update): reverses the original "truncate, never reject" policy -
    a real live answer was once cut mid-number by character-count slicing. An answer over
    `MAX_ANSWER_CHARS` now fails the WHOLE response closed, exactly like a malformed one."""
    long_answer = "a" * (MAX_ANSWER_CHARS + 1)
    provider = DeterministicFakeLanguageModelProvider(answer=_answer(answer=long_answer))
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None


def test_34b_an_answer_at_exactly_the_bound_is_still_accepted() -> None:
    exact_answer = "a" * MAX_ANSWER_CHARS
    provider = DeterministicFakeLanguageModelProvider(answer=_answer(answer=exact_answer))
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.ANSWERED
    assert result.answer == exact_answer


# --- 35: malformed provider output fails closed ---------------------------------------------------


def test_35_empty_answer_is_malformed_and_fails_closed_to_unavailable() -> None:
    provider = DeterministicFakeLanguageModelProvider(answer=_answer(answer="   "))
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None
    assert result.grounding_refs == ()


# --- 36-37: provider timeout/exception fail closed to UNAVAILABLE, never leaked -------------------


def test_36_provider_timeout_becomes_unavailable() -> None:
    provider = DeterministicFakeLanguageModelProvider(
        error=LanguageModelUnavailableError("simulated timeout")
    )
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None
    assert result.limitations == ()


def test_37_unexpected_provider_exception_also_becomes_unavailable_never_leaked() -> None:
    provider = DeterministicFakeLanguageModelProvider(error=RuntimeError("boom: secret detail"))
    result = AskNinfaService(provider).ask(_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None

"""Gate 19.1b (ADR 0026's own update): golden, product-quality example answers - proving the
PREFERRED vocabulary and question-sensitive selective style validates cleanly end to end, never a
runtime intent classifier (there is none - these are static examples, one per question type).
"""

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer
from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider, sample_ask_context

# The six/eight terms Gate 19.1b's own live finding traced back to instructions.py using the
# English/technical word itself, or a clunky label a user should never need to read.
_FORBIDDEN_TERMS = (
    "confidence",
    "pattern storico",
    "atteso a fine finestra",
    "on the books",
    "shortfall",
    "forecast",
    "reason code",
    "rank",
)

# Matches the live occupancy case's own real numbers (20/40/28/34/6/15pp) - never hardcoded as
# THE production answer (instructions.py contains no fixed answer text), only as a test fixture
# proving the target style is achievable and accepted end to end.
_GENERIC_WHY_ANSWER = (
    "NINFA ti sta mostrando questa decisione perché, per il 15 agosto, risultano 20 camere "
    "prenotate su 40 disponibili e l'occupazione prevista è sotto il livello atteso sulla base "
    "dello storico.\n\nLo scostamento è di circa 6 camere, pari a 15 punti percentuali di "
    "occupazione. Per questo può essere utile rivedere il posizionamento della data, verificando "
    "prezzi, disponibilità e restrizioni. La decisione finale resta a te."
)

_RELIABILITY_ANSWER = (
    "L'affidabilità di questa rilevazione è del 100%, basata su 12 confronti con l'andamento "
    "storico della stessa data. È quindi un dato su cui puoi fare affidamento."
)

_ECONOMIC_IMPACT_ANSWER = (
    "Sulla base dello scostamento rilevato, l'impatto stimato sui ricavi è di circa 600 euro: è "
    "una stima indicativa, non un valore certo, utile solo per farsi un'idea di massima."
)

_WHAT_TO_CHECK_ANSWER = (
    "Può essere utile rivedere il posizionamento della data, verificando in particolare prezzi e "
    "disponibilità/restrizioni per il periodo. La decisione finale resta a te."
)


def _answer(text: str) -> LanguageModelAnswer:
    return LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED,
        answer=text,
        grounding_refs=("LATEST_FACTS", "RECOMMENDATION"),
        limitations=(),
    )


def _assert_no_forbidden_terms(text: str) -> None:
    lowered = text.lower()
    for forbidden in _FORBIDDEN_TERMS:
        assert forbidden not in lowered, (forbidden, text)


# --- TEST - LIVE OCCUPANCY STYLE ------------------------------------------------------------------


def test_occupancy_style_answer_contains_no_forbidden_term() -> None:
    _assert_no_forbidden_terms(_GENERIC_WHY_ANSWER)


def test_occupancy_style_answer_contains_the_critical_facts_and_recommendation_meaning() -> None:
    assert "20" in _GENERIC_WHY_ANSWER
    assert "40" in _GENERIC_WHY_ANSWER
    assert "6 camere" in _GENERIC_WHY_ANSWER
    assert "15 punti percentuali" in _GENERIC_WHY_ANSWER
    assert "posizionamento della data" in _GENERIC_WHY_ANSWER


def test_occupancy_style_answer_is_near_the_300_500_char_style_target() -> None:
    assert 300 <= len(_GENERIC_WHY_ANSWER) <= 550


def test_occupancy_style_answer_validates_end_to_end_through_the_service() -> None:
    provider = DeterministicFakeLanguageModelProvider(answer=_answer(_GENERIC_WHY_ANSWER))
    result = AskNinfaService(provider).ask(sample_ask_context(), "Perché me lo stai mostrando?")

    assert result.status is AskStatus.ANSWERED
    assert result.answer == _GENERIC_WHY_ANSWER


# --- TEST - QUESTION SENSITIVITY: each question type's own natural answer style validates too -----


def test_reliability_question_answer_may_use_affidabilita_and_comparable_count() -> None:
    """ "Quanto è affidabile?" - confidence/comparable count ARE relevant here, unlike the generic
    "perché" case above; this is never structurally forbidden, only de-prioritised by instruction
    for a generic question (rule 22) - no runtime intent classifier decides this either way."""
    validated = validate_model_answer(_answer(_RELIABILITY_ANSWER))
    assert validated is not None
    assert "affidabilità" in _RELIABILITY_ANSWER.lower()
    assert "confidence" not in _RELIABILITY_ANSWER.lower()


def test_economic_impact_question_answer_may_use_the_proxy_with_its_caveat() -> None:
    """ "Qual è l'impatto economico?" - the proxy figure is allowed here, always with its caveat."""
    validated = validate_model_answer(_answer(_ECONOMIC_IMPACT_ANSWER))
    assert validated is not None
    assert "stima indicativa" in _ECONOMIC_IMPACT_ANSWER.lower()
    assert "valore certo" in _ECONOMIC_IMPACT_ANSWER.lower()


def test_what_to_check_question_answer_focuses_on_recommendation_as_one_sentence() -> None:
    """ "Cosa posso verificare?" - one natural recommendation sentence, human review implied, no
    category/scope/flag described as separate data."""
    validated = validate_model_answer(_answer(_WHAT_TO_CHECK_ANSWER))
    assert validated is not None
    assert "la decisione finale resta a te" in _WHAT_TO_CHECK_ANSWER.lower()


def test_none_of_the_four_question_type_answers_contain_a_forbidden_term() -> None:
    for answer in (
        _GENERIC_WHY_ANSWER,
        _RELIABILITY_ANSWER,
        _ECONOMIC_IMPACT_ANSWER,
        _WHAT_TO_CHECK_ANSWER,
    ):
        _assert_no_forbidden_terms(answer)

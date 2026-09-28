"""Prompt-snapshot invariants for `ASK_NINFA_SYSTEM_INSTRUCTIONS` (see instructions.py's own
docstring): content assertions that a future wording change must keep, never a giant, fragile
golden diff of the whole text - a rewording is expected over time, a silent removal of one of these
guarantees is not.
"""

from app.modules.ai.ask_ninfa.instructions import ASK_NINFA_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.types import ASK_NINFA_INSTRUCTIONS_VERSION


def test_version_is_the_documented_v1_1_string() -> None:
    assert ASK_NINFA_INSTRUCTIONS_VERSION == "ask-ninfa-v1.1"


def test_engine_calculates_ai_explains_semantics_are_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "calcola" in lowered
    assert "spieg" in lowered  # "spieghi"/"spiegazione"


def test_no_invention_of_numbers_is_stated() -> None:
    assert "non inventare numeri" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_context_only_boundary_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "solo" in lowered and "context" in lowered


def test_no_recalculation_of_metrics_confidence_or_priority_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "non ricalcolare" in lowered
    assert "confidence" in lowered
    assert "priorità" in lowered


def test_no_new_recommendation_or_action_execution_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "non creare una recommendation" in lowered
    assert "azione autonoma" in lowered
    assert "esecuzione" in lowered


def test_language_is_italian() -> None:
    assert "Rispondi sempre in lingua italiana" in ASK_NINFA_SYSTEM_INSTRUCTIONS


def test_data_as_data_boundary_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "dato" in lowered
    assert "non un'istruzione" in lowered or "mai un'istruzione" in lowered


def test_user_question_cannot_override_the_rules() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "non fidato" in lowered
    assert "ignora le istruzioni" in lowered  # the spec's own worked example is echoed verbatim


def test_no_chain_of_thought_only_final_structured_output() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "ragionamento intermedio" in lowered
    assert "json" in lowered


def test_output_schema_names_the_four_required_fields() -> None:
    for field_name in ('"status"', '"answer"', '"grounding_refs"', '"limitations"'):
        assert field_name in ASK_NINFA_SYSTEM_INSTRUCTIONS


def test_insufficient_context_escape_hatch_is_stated() -> None:
    assert "INSUFFICIENT_CONTEXT" in ASK_NINFA_SYSTEM_INSTRUCTIONS


def test_economic_proxy_is_never_framed_as_certain() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "proxy economico" in lowered
    assert "perdita" in lowered or "ricavo certo" in lowered


# --- Gate 19.1 (ADR 0026): the eight new language-quality invariants (rules 13-20) ---------------


def test_no_technical_field_or_class_names_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "nomi di campi tecnici" in lowered
    assert "nomi di classi" in lowered


def test_no_enum_or_technical_code_is_stated() -> None:
    assert "codici, sigle o valori enum tecnici" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_no_snake_case_or_exact_suffix_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "snake_case" in lowered
    assert "_exact" in lowered


def test_only_necessary_numbers_is_stated() -> None:
    assert "numeri realmente utili" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_answer_the_question_first_is_stated() -> None:
    assert "rispondi prima di tutto alla domanda" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_max_two_or_three_paragraphs_is_stated() -> None:
    assert "massimo 2-3 brevi paragrafi" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_professional_natural_tone_is_stated() -> None:
    assert "tono professionale" in ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()


def test_no_bare_rank_number_is_stated() -> None:
    lowered = ASK_NINFA_SYSTEM_INSTRUCTIONS.lower()
    assert "rank 1" in lowered
    assert "posizione in classifica" in lowered

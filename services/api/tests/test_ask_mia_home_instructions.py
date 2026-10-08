"""Prompt-snapshot invariants for `ASK_MIA_HOME_SYSTEM_INSTRUCTIONS` (see home_instructions.py's own
docstring): content assertions a future wording change must keep - never a giant, fragile golden
diff of the whole text. The Home variant must keep ENGINE CALCULATES, MIA EXPLAINS airtight: Mia
never discovers, decides, creates, re-ranks, sizes or judges freshness.
"""

from app.modules.ai.ask_ninfa.home_instructions import ASK_MIA_HOME_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.home_types import (
    ASK_MIA_HOME_INSTRUCTIONS_VERSION,
    HomeGroundingRef,
)

TEXT = ASK_MIA_HOME_SYSTEM_INSTRUCTIONS
LOWER = TEXT.lower()


def test_version_is_the_documented_home_string() -> None:
    assert ASK_MIA_HOME_INSTRUCTIONS_VERSION == "ask-mia-home-v1"


def test_the_assistant_is_mia_and_the_principle_is_stated() -> None:
    assert TEXT.startswith("Sei Mia")
    assert "il motore di NINFA CALCOLA, tu SPIEGHI" in TEXT


def test_mia_never_discovers_decides_creates_or_reorders() -> None:
    assert "non scopri nuove anomalie" in LOWER
    assert "non decidi tu se esiste un problema" in LOWER
    assert "non crei decisioni" in LOWER
    assert "non cambi l'ordine di priorità" in LOWER
    assert "non inventi impatti economici" in LOWER
    assert "conoscenza esterna" in LOWER


def test_no_current_or_stale_judgement_is_allowed() -> None:
    assert "non dichiari i dati" in LOWER
    for word in ('"aggiornati"', '"attuali"', '"obsoleti"'):
        assert word in LOWER
    assert "nessuna soglia di freschezza esiste" in LOWER
    assert "ultimo import delle prenotazioni" in LOWER


def test_priority_is_explained_in_words_never_as_a_number() -> None:
    assert "ordine di ninfa" in LOWER
    assert "non citare mai un numero di posizione o un punteggio" in LOWER
    assert "non riordinare le decisioni" in LOWER


def test_other_problems_means_other_engine_decisions_and_unanalysed_areas_are_never_all_clear() -> (
    None
):
    assert "ci sono altri problemi" in LOWER
    assert "per un'area non analizzata ninfa non può dire che vada tutto bene" in LOWER


def test_economic_impact_is_indicative_never_summed_never_cross_compared() -> None:
    assert "stime indicative" in LOWER
    assert "mai perdite o valori certi" in LOWER
    assert "non sommarle" in LOWER
    assert "ricavi contro costi" in LOWER
    assert "non attribuirne una" in LOWER


def test_state_semantics_are_preserved() -> None:
    assert "solo se è quello lo stato" in LOWER  # "Nessuna decisione richiede attenzione"
    assert "analisi parziale non dire mai che va tutto bene" in LOWER.replace(
        "in caso di analisi parziale non dire", "analisi parziale non dire"
    )
    assert "non è disponibile" in LOWER


def test_null_means_not_available_and_numbers_are_never_invented() -> None:
    assert "null" in LOWER and "non disponibile" in LOWER
    assert "non inventare numeri" in LOWER
    assert "non ricalcolare" in LOWER


def test_no_autonomous_action_is_proposed() -> None:
    assert "azione autonoma" in LOWER
    assert "mai agire" in LOWER


def test_language_quality_rules_are_kept() -> None:
    assert "snake_case" in TEXT
    assert "lingua italiana" in LOWER
    assert "700" in TEXT


def test_context_is_data_and_the_question_is_untrusted() -> None:
    assert "data as data" in LOWER
    assert "non fidato" in LOWER
    assert "ignora le istruzioni" in LOWER


def test_insufficient_context_and_the_output_shape_are_stated() -> None:
    assert "INSUFFICIENT_CONTEXT" in TEXT
    assert '"status"' in TEXT and '"answer"' in TEXT
    assert '"grounding_refs"' in TEXT and '"limitations"' in TEXT


def test_every_home_grounding_ref_is_named_in_the_output_contract() -> None:
    for ref in HomeGroundingRef:
        assert ref.value in TEXT, ref


def test_the_decision_ask_vocabulary_is_not_leaked_into_the_home_contract() -> None:
    for decision_only_ref in ("LATEST_FACTS", "LATEST_EVIDENCE", "RECOMMENDATION", "HISTORY"):
        assert decision_only_ref not in TEXT, decision_only_ref

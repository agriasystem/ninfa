"""The reasoning policy: LOW for a pointer or a definition, MEDIUM by default, HIGH only for a
question that joins several areas or asks for an analysis - never "high for every message".

The table below is the product's own examples (the questions people are expected to ask Mia), so a
change of the heuristic has to be a change of this table on purpose."""

import pytest

from app.modules.ai.mia import policy

LOW = [
    "Dove trovo le decisioni?",
    "Cos'è il pickup?",
    "Come cambio il numero di camere?",
    "Che differenza c'è tra FULL, PARTIAL e DELTA?",
    "Cosa può fare NINFA?",
    "Cosa significa dato ricostruito?",
    "Come funziona Smart Import?",
    "Dove devo andare per configurare questa cosa?",
    "Che file posso importare?",
    "A cosa serve la sezione Struttura?",
]
MEDIUM = [
    "Perché oggi non ho Decision?",
    "Perché l'occupazione è sopra il 100%?",
    "Quanto sto dipendendo da Booking.com?",
    "Perché il costo per camera non è disponibile?",
    "Quali giorni della prossima settimana meritano attenzione?",
    "Da dove arrivano questi dati?",
    "Perché vedo Analisi parziale?",
    "Come viene calcolato il pickup?",
    "Spiegamelo più semplicemente.",
    "Che cosa sai di questa struttura?",
    "E sabato?",
    "Perché venerdì è debole?",
    "Come funziona il mio import di oggi?",
]
HIGH = [
    "Fammi un riepilogo della situazione dell'hotel.",
    "Qual è il problema più importante adesso?",
    "Confrontami ricavi, distribuzione e personale.",
    "Sto vendendo bene ma sto guadagnando?",
    "Analizza perché dicembre sta andando male",
    "Come sta andando l'hotel?",
    "Dove devo concentrarmi questa settimana?",
]


@pytest.mark.parametrize("question", LOW)
def test_a_pointer_or_a_definition_is_low(question: str) -> None:
    assert policy.initial(question) == "low"


@pytest.mark.parametrize("question", MEDIUM)
def test_an_ordinary_question_about_the_property_is_medium(question: str) -> None:
    assert policy.initial(question) == "medium"


@pytest.mark.parametrize("question", HIGH)
def test_an_analysis_or_a_multi_area_question_is_high(question: str) -> None:
    assert policy.initial(question) == "high"


def test_high_is_the_exception_not_the_rule() -> None:
    levels = [policy.initial(q) for q in LOW + MEDIUM]

    assert "high" not in levels


def test_a_very_long_question_is_high_but_a_long_definition_request_is_not_low() -> None:
    assert policy.initial("Ho bisogno di capire " + "molto bene " * 40) == "high"
    # a support-looking question about THIS property is a data question, not a pointer
    assert policy.initial("Come funziona il mio import di oggi?") == "medium"


def test_the_wording_is_read_without_accents_or_case() -> None:
    assert policy.initial("COS'E' IL PICKUP?") == policy.initial("cos'è il pickup?") == "low"


def test_areas_are_counted_by_the_words_people_use() -> None:
    assert policy.areas_mentioned("ricavi e costi") == {"ricavi", "costi"}
    assert policy.areas_mentioned("quanto pesa Booking sul personale") == {
        "distribuzione",
        "personale",
    }
    assert policy.areas_mentioned("ciao") == frozenset()


def test_after_tools_a_low_question_that_needed_numbers_is_at_least_medium() -> None:
    assert policy.after_tools("low", data_domains=1, used_data_tool=True) == "medium"
    assert policy.after_tools("low", data_domains=0, used_data_tool=False) == "low"


def test_a_turn_that_consulted_three_areas_is_high_whatever_the_wording() -> None:
    assert policy.after_tools("medium", data_domains=3, used_data_tool=True) == "high"
    assert policy.after_tools("low", data_domains=4, used_data_tool=True) == "high"
    assert policy.after_tools("medium", data_domains=2, used_data_tool=True) == "medium"


def test_the_effort_never_goes_down_after_tools() -> None:
    assert policy.after_tools("high", data_domains=1, used_data_tool=True) == "high"

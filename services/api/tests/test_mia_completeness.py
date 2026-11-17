"""`looks_truncated`: an answer that stops mid-sentence is never shown (it is rewritten once)."""

import pytest

from app.modules.ai.mia.completeness import looks_truncated


@pytest.mark.parametrize(
    "answer",
    [
        "Domani sei al 77,50%.",
        "Vuoi che controlli domani?",
        "Attenzione!",
        "Il canale (Booking.com).",
        "Ha detto: «ok»",
        "Ecco l'elenco:",
        "Frase finita…",
        "Prima riga.\n\n- voce senza punto\n- altra voce senza punto",
        'Titolo "citato"',
        "  Risposta con spazio finale.  \n",
    ],
)
def test_an_answer_that_closes_its_last_sentence_is_complete(answer: str) -> None:
    assert looks_truncated(answer) is False


@pytest.mark.parametrize(
    "answer",
    [
        "Non posso farlo. Mia lavora su un'unica struttura, Hotel Aurora, e non esistono ",
        "Domani sei al",
        "Prima frase. Seconda frase che si interrompe",
        "Elenco:\n- voce\nChiusura senza punto",
    ],
)
def test_an_answer_that_stops_mid_sentence_is_truncated(answer: str) -> None:
    assert looks_truncated(answer) is True


def test_emptiness_is_not_truncation() -> None:
    assert looks_truncated("") is False and looks_truncated("   \n") is False

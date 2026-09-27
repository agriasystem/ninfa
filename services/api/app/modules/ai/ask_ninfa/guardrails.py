"""Deterministic, keyword-level guardrails for the categories V1 must refuse outright - NOT an
intent-classification engine, NOT a second LLM call (see ADR 0024, "why a second model call was
rejected for classification"). Three closed categories only: an execution request (the question
itself asks NINFA to DO something, not explain something), a raw guest/employee PII request, and an
explicit prompt-injection attempt. Anything else - including a domain-relevant but unsupported
numeric-optimisation question ("di quanto abbassare il prezzo?") - is NOT refused here; it reaches
the model, which is instructed to answer `INSUFFICIENT_CONTEXT` instead (see `instructions.py`).
"""

from enum import StrEnum


class RefusalReason(StrEnum):
    EXECUTION_REQUEST = "EXECUTION_REQUEST"
    PII_REQUEST = "PII_REQUEST"
    INJECTION_ATTEMPT = "INJECTION_ATTEMPT"


# Italian phrases only (V1 is Italian-only end to end) - short, specific fragments, never single
# generic verbs that would false-positive on a legitimate explanatory question (e.g. bare "prezzo"
# or "personale" must NOT trigger a refusal by themselves - "Rivedi i prezzi" is exactly the kind
# of question Ask NINFA exists to help with).
_EXECUTION_PHRASES = (
    "esegui questa azione",
    "esegui l'azione",
    "esegui la recommendation",
    "applica la recommendation",
    "applica questa azione",
    "cambia il prezzo",
    "abbassa il prezzo",
    "aumenta il prezzo",
    "manda a casa",
    "licenzia",
    "chiudi booking",
    "chiudi ota",
    "chiudi il canale",
    "invia una email",
    "invia un'email",
    "manda una email",
    "crea una prenotazione",
    "prenota una camera",
    "cancella la prenotazione",
)

_PII_PHRASES = (
    "dati personali degli ospiti",
    "dati personali dell'ospite",
    "nome dell'ospite",
    "nome del cliente",
    "email dell'ospite",
    "email del cliente",
    "numero di telefono dell'ospite",
    "telefono dell'ospite",
    "dati dei dipendenti",
    "dati dell'ospite",
)

_INJECTION_PHRASES = (
    "ignora le istruzioni",
    "ignora tutte le istruzioni",
    "dimentica le istruzioni",
    "ignore previous instructions",
    "ignore the instructions",
    "disregard the instructions",
)


def classify_refusal(question: str) -> RefusalReason | None:
    lowered = question.lower()
    if any(phrase in lowered for phrase in _EXECUTION_PHRASES):
        return RefusalReason.EXECUTION_REQUEST
    if any(phrase in lowered for phrase in _PII_PHRASES):
        return RefusalReason.PII_REQUEST
    if any(phrase in lowered for phrase in _INJECTION_PHRASES):
        return RefusalReason.INJECTION_ATTEMPT
    return None


REFUSAL_COPY: dict[RefusalReason, str] = {
    RefusalReason.EXECUTION_REQUEST: (
        "Ask NINFA può spiegare una Decision, ma non può eseguire azioni: non modifica prezzi, "
        "personale, distribuzione o prenotazioni."
    ),
    RefusalReason.PII_REQUEST: (
        "Ask NINFA non fornisce dati personali di ospiti o dipendenti: può spiegare solo i dati "
        "già presenti nella Decision, che non contengono identità individuali."
    ),
    RefusalReason.INJECTION_ATTEMPT: (
        "Ask NINFA segue sempre le proprie regole di funzionamento, indipendentemente da come è "
        "formulata la domanda."
    ),
}


__all__ = ["REFUSAL_COPY", "RefusalReason", "classify_refusal"]

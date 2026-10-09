"""A deterministic stand-in for "a model that answers well" - used ONLY to prove that the Mia Home
context carries everything a rich, grounded answer needs.

THIS IS NOT A LANGUAGE MODEL AND IT PROVES NOTHING ABOUT ONE. `ContextReadingProvider` composes an
answer by reading nothing but the JSON context it is handed (the exact string a real provider would
receive): if the context lacks a field the answer needs - an area, a target, an estimate, its kind,
the coverage, the import fact - composing the answer raises, and the test fails. That is the whole
claim: "the information a good answer needs is in the context, in a form that can be used". Whether
the real model then FOLLOWS `home_instructions.py` is checked by prompt-content tests (the rules are
present) and, for actual behaviour, only by the real Anthropic smoke test.

Free functions + one tiny provider class, like the other `*_support.py` modules.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.gateway.protocol import (
    LanguageModelAnswer,
    LanguageModelRequest,
    ModelAnswerStatus,
)

_MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

Context = dict[str, Any]


def italian_date(value: str) -> str:
    """ "2026-08-15" -> "15 agosto"; anything else is returned unchanged."""
    match = _ISO.match(value)
    if match is None:
        return value
    return f"{int(match.group(3))} {_MONTHS[int(match.group(2)) - 1]}"


def _target_of(decision: Context) -> str:
    return ", ".join(f"{key} {italian_date(value)}" for key, value in decision["riguarda"].items())


def _impact_of(decision: Context) -> str | None:
    points = decision["impatto economico"]
    if not points:
        return None
    point = points[0]
    unit = f" {point['unità']}" if point["unità"] else ""
    return f"{point['etichetta']}: {point['valore']}{unit}"


def _decision_line(decision: Context) -> str:
    parts = [f"{decision['decisione']} ({decision['area']})"]
    target = _target_of(decision)
    if target:
        parts.append(target)
    impact = _impact_of(decision)
    if impact:
        parts.append(impact)
    return "- " + ", ".join(parts)


def _unanalysed_areas(context: Context) -> list[str]:
    coverage = context["copertura dell'analisi"]
    if coverage is None:
        return []
    return [item["area"] for item in coverage["aree"] if item["stato"] == "non analizzata"]


def _answered(text: str, *refs: str) -> LanguageModelAnswer:
    return LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED, answer=text, grounding_refs=refs, limitations=()
    )


def _insufficient(text: str, *refs: str) -> LanguageModelAnswer:
    return LanguageModelAnswer(
        status=ModelAnswerStatus.INSUFFICIENT_CONTEXT,
        answer=text,
        grounding_refs=refs,
        limitations=(),
    )


def _no_decisions_answer(context: Context) -> LanguageModelAnswer:
    """What each feed state with no decision to talk about must say - taken from the context's own
    state sentence and its coverage / last-analysis fields."""
    state = context["stato dell'analisi"]
    last = context["data dell'ultima analisi completata"]
    if context["copertura dell'analisi"] is None:  # NOT_PROCESSED
        text = state + "."
        if last is not None:
            text += f" L'ultima analisi completata è del {italian_date(last)}."
        return _insufficient(text, "ANALYSIS_STATE", "LAST_ANALYSIS")
    skipped = _unanalysed_areas(context)
    insufficient = context["controlli con dati insufficienti"]
    if state.startswith("Analisi parziale"):
        text = f"L'analisi di oggi è parziale: {insufficient} controlli senza dati sufficienti."
        if skipped:
            text += f" Non sono state analizzate le aree: {', '.join(skipped)}."
        return _answered(text, "ANALYSIS_STATE", "COVERAGE")
    text = "Oggi nessuna decisione richiede attenzione."
    if skipped:
        text += f" Non sono state analizzate le aree: {', '.join(skipped)}."
    else:
        text += " Tutte le aree sono state analizzate."
    return _answered(text, "ANALYSIS_STATE", "COVERAGE")


def other_problems(context: Context) -> LanguageModelAnswer:
    decisions = context["decisioni in ordine di priorità"]
    if not decisions:
        return _no_decisions_answer(context)
    skipped = _unanalysed_areas(context)
    if len(decisions) == 1:
        text = "No: oggi NINFA non ha rilevato altre decisioni che richiedono attenzione."
    else:
        lines = "\n".join(_decision_line(item) for item in decisions[1:])
        text = f"Sì, oltre alla prima NINFA ha rilevato anche:\n{lines}"
    if context["decisioni non mostrate"] > 0:
        text += "\n\nCe ne sono altre che qui non elenco."
    if skipped:
        text += f"\n\nNon sono state analizzate le aree: {', '.join(skipped)}."
    return _answered(text, "DECISIONS", "ECONOMIC_IMPACT", "COVERAGE")


def priority(context: Context) -> LanguageModelAnswer:
    decisions = context["decisioni in ordine di priorità"]
    if not decisions:
        return _no_decisions_answer(context)
    first = decisions[0]
    facts = "\n".join(
        f"- {point['etichetta']}: {point['valore']}"
        + (f" {point['unità']}" if point["unità"] else "")
        for point in first["dati"][:4]
    )
    text = (
        f"La più prioritaria per NINFA è «{first['decisione']}» ({first['area']}). "
        f"{first['descrizione']}\n\n{facts}\n\n"
        f"Affidabilità: {first['affidabilità']} su 100."
    )
    impact = _impact_of(first)
    if impact:
        text += f" {impact}."
    return _answered(text, "DECISIONS", "ECONOMIC_IMPACT")


def highest_impact(context: Context) -> LanguageModelAnswer:
    decisions = context["decisioni in ordine di priorità"]
    with_impact = [item for item in decisions if item["impatto economico"]]
    if not with_impact:
        if not decisions:
            return _no_decisions_answer(context)
        return _insufficient(
            "Per le decisioni di oggi il motore non ha registrato stime d'impatto economico.",
            "ECONOMIC_IMPACT",
        )
    by_kind: dict[str, list[Context]] = {}
    for item in with_impact:
        by_kind.setdefault(item["tipo di impatto economico"], []).append(item)
    best_of = {
        kind: max(items, key=lambda item: float(item["impatto economico"][0]["valore"]))
        for kind, items in by_kind.items()
    }
    if len(best_of) == 1:
        [(kind, best)] = best_of.items()
        text = (
            f"La stima indicativa più alta è quella di «{best['decisione']}» "
            f"({best['area']}): {_impact_of(best)}. Sono stime di {kind}, non perdite certe."
        )
    else:
        lines = "\n".join(
            f"- {kind}: «{best['decisione']}», {_impact_of(best)}" for kind, best in best_of.items()
        )
        text = (
            "Le stime di oggi sono di tipo diverso e non sono direttamente confrontabili. "
            f"Per ogni tipo la più alta è:\n{lines}\n\nSono stime indicative, non perdite certe."
        )
    return _answered(text, "DECISIONS", "ECONOMIC_IMPACT")


def data_used(context: Context) -> LanguageModelAnswer:
    coverage = context["copertura dell'analisi"]
    if coverage is None:
        return _no_decisions_answer(context)
    analysed = [item["area"] for item in coverage["aree"] if item["stato"] == "analizzata"]
    skipped = _unanalysed_areas(context)
    text = f"NINFA ha analizzato: {', '.join(analysed)}."
    if skipped:
        text += f" Non sono state analizzate: {', '.join(skipped)}."
    imported = context["dati usati dall'analisi"]["ultimo import prenotazioni"]
    if isinstance(imported, dict):
        day = imported["giorno rispetto alla data di riferimento"] or italian_date(imported["data"])
        text += (
            f"\n\nL'ultimo import delle prenotazioni è di {day}, "
            f"alle {imported['ora locale della struttura']}."
        )
    else:
        text += "\n\nL'ora dell'ultimo import delle prenotazioni non è disponibile."
    insufficient = context["controlli con dati insufficienti"]
    if insufficient:
        text += f" {insufficient} controlli non avevano dati sufficienti."
    return _answered(text, "COVERAGE", "FRESHNESS")


def area_question(context: Context, area: str) -> LanguageModelAnswer:
    """Free text about one area: its decisions if any; "no decision here" ONLY if the area was
    analysed; otherwise the honest "cannot say"."""
    matching = [item for item in context["decisioni in ordine di priorità"] if item["area"] == area]
    if matching:
        lines = "\n".join(_decision_line(item) for item in matching)
        return _answered(f"Per {area} NINFA ha rilevato:\n{lines}", "DECISIONS")
    if area in _unanalysed_areas(context):
        return _insufficient(
            f"L'area {area} oggi non è stata analizzata: non posso dirlo.", "COVERAGE"
        )
    return _answered(f"Per {area} oggi NINFA non ha rilevato nessuna decisione.", "COVERAGE")


def vague_question() -> LanguageModelAnswer:
    return _insufficient(
        "Non ho memoria delle domande precedenti: puoi riformularla indicando di quale decisione "
        "parli? Posso spiegarti la priorità di oggi, le altre decisioni o i dati usati."
    )


def answer_from_context(question: str, context: Context) -> LanguageModelAnswer:
    lowered = question.lower()
    if "altri problemi" in lowered:
        return other_problems(context)
    if "priorità" in lowered:
        return priority(context)
    if "impatto economico" in lowered:
        return highest_impact(context)
    if "dati ha usato" in lowered:
        return data_used(context)
    if "costi" in lowered:
        return area_question(context, "Costi")
    if "ricavi" in lowered:
        return area_question(context, "Ricavi")
    if "distribuzione" in lowered:
        return area_question(context, "Distribuzione")
    return vague_question()


@dataclass
class ContextReadingProvider:
    """`LanguageModelProvider` that answers from `request.context` alone (see the module docstring:
    a context-sufficiency probe, never evidence about a real model)."""

    requests: list[LanguageModelRequest] = field(default_factory=list)

    def generate(self, request: LanguageModelRequest) -> LanguageModelAnswer:
        self.requests.append(request)
        return answer_from_context(request.question, json.loads(request.context))

    @property
    def last_request(self) -> LanguageModelRequest:
        return self.requests[-1]


# The reliability scale is stated by the instructions themselves ("78 su 100"), not by the context.
_SCALE_FIGURES = frozenset({"100"})


def ungrounded_numbers(answer: str, serialized_context: str) -> list[str]:
    """Every number in `answer` (decimal comma read as a point) that does NOT literally occur in
    the context text it was supposed to come from, apart from the 0-100 reliability scale. Empty
    list == every figure is grounded."""
    normalised = re.sub(r"(?<=\d),(?=\d)", ".", answer)
    return [
        number
        for number in _NUMBER.findall(normalised)
        if number not in serialized_context and number not in _SCALE_FIGURES
    ]


__all__ = [
    "ContextReadingProvider",
    "answer_from_context",
    "italian_date",
    "ungrounded_numbers",
]

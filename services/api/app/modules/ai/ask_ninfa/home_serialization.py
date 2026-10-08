"""`AskHomeContext` -> canonical JSON: DATA handed to a provider, never pseudo-instructions.

Every field is written out by hand (never `dataclasses.asdict()`), exactly like the Decision Ask's
own `serialization.py`. The JSON KEYS are plain Italian phrases (with spaces), never snake_case
identifiers: a model that echoes a key verbatim then produces natural Italian instead of a
technical token, and the technical-leak check (`technical_leak.py`, which fails closed on any
snake_case-shaped word) never has a context-derived reason to fire - the same lesson Gate 19.1b
already applied to the single key `"affidabilita"` (see `serialization.py`).

`null` always means "not available": the context builder only ever emits it where the underlying
run/analysis does not exist, and the instructions say so explicitly.
"""

import json

from app.modules.ai.ask_ninfa.home_facts import OperationalContext, OperationalSection
from app.modules.ai.ask_ninfa.home_types import (
    AskHomeContext,
    AskHomeCoverageContext,
    AskHomeDecisionContext,
    AskHomeFreshnessContext,
)
from app.modules.ai.ask_ninfa.types import AskDataPoint


def _data_point_dict(point: AskDataPoint) -> dict[str, object]:
    return {"etichetta": point.label, "valore": point.value, "unità": point.unit}


def _decision_dict(decision: AskHomeDecisionContext) -> dict[str, object]:
    return {
        "posizione nell'ordine di NINFA": decision.position,
        "decisione": decision.decision_label,
        "descrizione": decision.description,
        "area": decision.area,
        "stato": decision.status_label,
        "riguarda": dict(decision.target),
        "affidabilità": decision.confidence,
        "rilevata per la prima volta il": decision.first_seen_local_date,
        "episodi": decision.episode_count,
        "dati": [_data_point_dict(point) for point in decision.facts],
        "tipo di impatto economico": decision.impact_kind,
        "impatto economico": [_data_point_dict(point) for point in decision.economic_impact],
        "riferimento": decision.ref,
    }


def _coverage_dict(coverage: AskHomeCoverageContext) -> dict[str, object]:
    return {
        "sintesi": coverage.summary_label,
        "aree": [
            {"area": item.area, "stato": item.status_label, "riferimento": item.ref}
            for item in coverage.areas
        ],
    }


def _freshness_dict(freshness: AskHomeFreshnessContext) -> dict[str, object]:
    if not freshness.known:
        return {"ultimo import prenotazioni": "non disponibile per questa analisi"}
    return {
        "ultimo import prenotazioni": {
            "data": freshness.local_date,
            "ora locale della struttura": freshness.local_time,
            "giorno rispetto alla data di riferimento": freshness.relative_day,
        },
        "riferimento": freshness.ref,
    }


def _section_dict(section: OperationalSection) -> dict[str, object]:
    return {
        "riferimento": section.ref,
        "titolo": section.title,
        "periodo": section.period,
        "dati": [_data_point_dict(point) for point in section.data],
        "righe": [dict(row) for row in section.rows],
        "nota": section.note,
    }


def _operational_dict(operational: OperationalContext) -> dict[str, object]:
    payload: dict[str, object] = {
        "argomenti riconosciuti nella domanda": list(operational.topics),
        "argomento ripreso dalla domanda precedente": operational.from_previous_question,
        "sezioni": [_section_dict(section) for section in operational.sections],
        "cosa NINFA non può determinare": list(operational.not_available),
    }
    if operational.supported_topics:
        payload["cosa NINFA sa spiegare"] = list(operational.supported_topics)
    return payload


def home_context_to_dict(context: AskHomeContext) -> dict[str, object]:
    """The explicit, hand-built dict `serialize_home_context` encodes - exposed separately so a
    test can assert on structure without re-parsing JSON."""
    return {
        "data di riferimento": context.business_date,
        "stato dell'analisi": context.analysis_state,
        "numero di decisioni che richiedono attenzione": context.decisions_total,
        "decisioni in ordine di priorità": [_decision_dict(item) for item in context.decisions],
        "decisioni non mostrate": context.decisions_omitted,
        "controlli con dati insufficienti": context.insufficient_checks,
        "controlli con affidabilità troppo bassa": context.low_confidence_checks,
        "copertura dell'analisi": (
            None if context.coverage is None else _coverage_dict(context.coverage)
        ),
        "dati usati dall'analisi": (
            None if context.freshness is None else _freshness_dict(context.freshness)
        ),
        "data dell'ultima analisi completata": context.last_successful_analysis_date,
        "dati operativi richiesti": (
            None if context.operational is None else _operational_dict(context.operational)
        ),
    }


def serialize_home_context(context: AskHomeContext) -> str:
    return json.dumps(home_context_to_dict(context), sort_keys=True, ensure_ascii=False)


__all__ = ["home_context_to_dict", "serialize_home_context"]

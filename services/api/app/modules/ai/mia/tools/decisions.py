"""Mia tools: the decisions NINFA's engine produced, and why.

    get_today_summary   the state of today's analysis, area by area, and why no decision
    list_decisions      the engine's decisions of a day (engine order) or the memory of them
    explain_decision    one decision: what NINFA checked, expected / actual / delta, how reliable

Mia never creates, changes or re-ranks a decision: every one of these comes from the Decision
Engine, exactly as the Oggi and Decisioni screens show it. What a tool says about "no decision"
is a FACT about the run (how many checks could not conclude, which areas were not analysed),
never an invented cause: NINFA does not record why a check left no conclusion, so no tool
guesses one.

Two conventions that protect the numeric grounding guard and the person:

* A decision's id travels to the model as a letters-only TOKEN (`ref_token`), not as a UUID: the
  digit runs of a UUID would otherwise land in the set of "figures" the answer's numbers are
  checked against, and a small invented number could be grounded by chance.
  `explain_decision` accepts the token and, for the id the page itself carries, the canonical
  UUID.
* Every key of an observation is plain Italian with spaces (never snake_case), so a model that
  echoes a key does not trip the technical-leak check.
"""

import contextlib
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.ask_ninfa import semantic_labels
from app.modules.ai.ask_ninfa.context_builder import AskDecisionContextBuilder
from app.modules.ai.ask_ninfa.home_context_builder import DOMAIN_OF_DECISION_TYPE
from app.modules.ai.ask_ninfa.types import AskDataPoint, AskDecisionContext
from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.labels import area_label
from app.modules.ai.mia.tools.base import ToolDefinition, ToolRuntime
from app.modules.ai.mia.tools.format import day, iso
from app.modules.ai.mia.types import Observation
from app.modules.decision_memory.types import FeedItem, FeedResult, FeedState
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    CoverageSummary,
    DomainCoverageStatus,
)
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.types import DecisionStatus
from app.modules.decisions.whitelist import evidence_of, facts_of
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.recommendations.engine import RecommendationEngine

# The longest history Mia reads of one decision (the Ask reads up to ten): enough to see the trend,
# small enough for an observation.
HISTORY_LIMIT = 6
MAX_LIST_ROWS = 10
MAX_LIST_FACTS = 5
# The lifecycle listing is filtered by area here, so it reads a wider page than it shows.
_MEMORY_PAGE = 50

_NOT_FOUND = (
    "La decisione indicata non esiste oppure non è accessibile per questo utente: non posso "
    "dire altro su di essa."
)

# --- opaque ids
# hex digit -> letter, so a decision id carries no digit at all (see the module docstring)
_TO_TOKEN = str.maketrans("0123456789", "ghijklmnop")
_FROM_TOKEN = str.maketrans("ghijklmnop", "0123456789")


def ref_token(decision_id: UUID) -> str:
    """The letters-only reference of a decision, as Mia's tools hand it to the model."""
    return decision_id.hex.translate(_TO_TOKEN)


def parse_ref(value: str) -> UUID | None:
    """A decision reference as the model (or the page) names it: the token above or a UUID."""
    text = value.strip()
    try:
        return UUID(text)
    except ValueError:
        pass
    if len(text) == 32:
        try:
            return UUID(hex=text.lower().translate(_FROM_TOKEN))
        except ValueError:
            return None
    return None


# --- areas and what the person may see

AreaArg = Literal["ricavi", "distribuzione", "costi", "personale"]
_AREA_OF_ARG: dict[str, AnalysisDomain] = {
    "ricavi": AnalysisDomain.REVENUE,
    "distribuzione": AnalysisDomain.DISTRIBUTION,
    "costi": AnalysisDomain.COSTS,
    "personale": AnalysisDomain.LABOR,
}


def access_domain_of(domain: AnalysisDomain) -> AccessDomain:
    return AccessDomain(domain.value)


def visible_areas(runtime: ToolRuntime) -> frozenset[AnalysisDomain]:
    """The analysis areas the asking user may reach: the ones everything below is counted over."""
    return frozenset(d for d in AnalysisDomain if runtime.allows(access_domain_of(d)))


def coverage_of(feed: FeedResult) -> AnalysisCoverage | None:
    run = feed.run
    if run is None or run.analysis_coverage is None:
        return None
    try:
        return AnalysisCoverage.from_json(run.analysis_coverage)
    except (KeyError, ValueError, TypeError):
        return None


def coverage_status_of(
    coverage: AnalysisCoverage | None, domain: AnalysisDomain
) -> DomainCoverageStatus | None:
    if coverage is None:
        return None
    return next((i.status for i in coverage.domains if i.domain is domain), None)


# --- the state of today's analysis, in plain Italian


def _decisions_in(feed: FeedResult, areas: frozenset[AnalysisDomain]) -> list[FeedItem]:
    return [
        item for item in feed.items if DOMAIN_OF_DECISION_TYPE[item.decision.decision_type] in areas
    ]


def feed_state_text(feed: FeedResult, areas: frozenset[AnalysisDomain]) -> str:
    """What the feed's state means, never "all fine" for a run that could not conclude. When some
    areas are hidden the state is read from the visible decisions only (the engine's state is
    domain-blind: it may be driven by an area the user cannot see)."""
    hidden = len(areas) < len(AnalysisDomain)
    visible = _decisions_in(feed, areas)
    if feed.state is FeedState.NOT_PROCESSED:
        last = feed.last_successful_analysis
        if last is not None:
            return (
                "L'analisi di questo giorno non è ancora disponibile; l'ultima analisi completata "
                f"risale al {last.as_of_local_date.isoformat()}."
            )
        return "NINFA non ha ancora completato una prima analisi per questa struttura."
    if hidden:
        if visible:
            return "Ci sono decisioni che richiedono attenzione nelle aree che puoi vedere."
        return "Nessuna decisione che richieda attenzione nelle aree che puoi vedere."
    if feed.state is FeedState.ACTION_REQUIRED:
        return "Ci sono decisioni che richiedono attenzione."
    if feed.state is FeedState.DATA_QUALITY_LIMITED:
        return (
            "Nessuna decisione affidabile oggi: alcuni controlli non hanno potuto "
            "concludere perché "
            "i dati non bastavano o non erano abbastanza affidabili. Non vuol dire che vada tutto "
            "bene."
        )
    return (
        "Nessuna decisione richiede attenzione: per quanto analizzato oggi, tutti i controlli "
        "dell'analisi hanno concluso."
    )


def coverage_text(coverage: AnalysisCoverage | None, run_exists: bool) -> str:
    if not run_exists:
        return "nessuna analisi disponibile"
    if coverage is None:
        return "non registrata per questa analisi"
    return "completa" if coverage.summary is CoverageSummary.FULL else "parziale"


def area_outcome(
    domain: AnalysisDomain, feed: FeedResult, coverage: AnalysisCoverage | None
) -> tuple[str, int, str]:
    """(analysis status, decisions in this area, plain-Italian outcome) of one area."""
    count = sum(
        1 for item in feed.items if DOMAIN_OF_DECISION_TYPE[item.decision.decision_type] is domain
    )
    run = feed.run
    if run is None:
        return (
            "non disponibile",
            0,
            "l'analisi di oggi non è ancora disponibile: NINFA non può valutare quest'area",
        )
    status = coverage_status_of(coverage, domain)
    if status is None:
        return (
            "non disponibile",
            count,
            "la copertura dell'analisi non è registrata per questa analisi: NINFA non può dire se "
            "quest'area sia stata analizzata",
        )
    if status is DomainCoverageStatus.SKIPPED:
        return (
            "non analizzata",
            count,
            "quest'area non è stata analizzata: NINFA non può dire che vada tutto bene",
        )
    if count > 0:
        return ("analizzata", count, "NINFA ha prodotto almeno una decisione in quest'area")
    if feed.state is FeedState.DATA_QUALITY_LIMITED:
        return (
            "analisi parziale",
            0,
            "nessuna decisione in quest'area; alcuni controlli dell'analisi (non "
            "attribuibili a una "
            "singola area) non hanno potuto concludere, quindi non si può escludere un problema "
            "non rilevato",
        )
    return (
        "analizzata",
        0,
        "per quanto analizzato oggi, NINFA non ha prodotto decisioni in quest'area",
    )


# --- decision rows


def _points(points: tuple[AskDataPoint, ...]) -> list[dict[str, str]]:
    rows = []
    for point in points:
        row = {"etichetta": point.label, "valore": point.value}
        if point.unit:
            row["unità"] = point.unit
        rows.append(row)
    return rows


def _target_of(decision: Decision) -> dict[str, str]:
    """When or what the decision is about, in plain Italian (never a data source id)."""
    payload = decision.identity_payload

    def text(key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None

    decision_type = decision.decision_type
    target: dict[str, str] = {}
    if decision_type in (
        PriorityDecisionType.REV_PICKUP_LOW,
        PriorityDecisionType.REV_OCCUPANCY_RISK,
    ):
        if (stay := text("stay_date")) is not None:
            target["notte di soggiorno"] = stay
    elif decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
        if (start := text("target_period_start")) is not None:
            target["mese che inizia il"] = start
        if (category := text("cost_category")) is not None:
            with contextlib.suppress(ValueError):  # a category this version does not know: dropped
                target["categoria di costo"] = semantic_labels.cost_category_label_of(
                    CostCategory(category)
                )
    elif decision_type is PriorityDecisionType.LABOR_OVERSTAFFING:
        if (work := text("work_date")) is not None:
            target["giorno di lavoro"] = work
        if (category := text("labor_category")) is not None:
            with contextlib.suppress(ValueError):
                target["reparto"] = semantic_labels.labor_category_label_of(LaborCategory(category))
    return target


def _decision_row(
    runtime: ToolRuntime,
    decision: Decision,
    observation: DecisionObservation,
    *,
    position: int | None,
) -> dict[str, Any]:
    decision_type = decision.decision_type
    facts = semantic_labels.data_points_of(
        semantic_labels.FACT_LABELS[decision_type],
        facts_of(decision_type, observation.facts_payload),
    )
    evidence = semantic_labels.data_points_of(
        semantic_labels.EVIDENCE_LABELS[decision_type],
        evidence_of(decision_type, observation.evidence_payload),
    )
    impact = [point for point in evidence if "stima indicativa" in point.label]
    row: dict[str, Any] = {
        "riferimento": ref_token(decision.id),
        "titolo": semantic_labels.decision_label_of(decision_type),
        "area": area_label(DOMAIN_OF_DECISION_TYPE[decision_type]),
        "riguarda": _target_of(decision),
        "stato": semantic_labels.decision_status_label_of(decision.status),
        "vista la prima volta": iso(decision.first_seen_local_date),
        "ultima valutazione": iso(decision.last_evaluated_local_date),
        "dati principali": _points(facts[:MAX_LIST_FACTS]),
    }
    if position is not None:
        row["posizione nell'ordine di NINFA"] = position
    if impact:
        row["impatto stimato"] = _points(tuple(impact))
    return row


# --- tool 1: get_today_summary


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _today_summary(runtime: ToolRuntime, _: _NoArgs) -> Observation:
    feed = runtime.feed()
    run = feed.run
    coverage = coverage_of(feed)
    areas = visible_areas(runtime)
    hidden = len(areas) < len(AnalysisDomain)
    visible_items = _decisions_in(feed, areas)

    rows: list[dict[str, Any]] = []
    not_analysed: list[str] = []
    analysed: list[str] = []
    for domain in AnalysisDomain:
        if domain not in areas:
            continue
        status, count, outcome = area_outcome(domain, feed, coverage)
        rows.append(
            {
                "area": area_label(domain),
                "stato dell'analisi": status,
                "decisioni": count,
                "esito": outcome,
            }
        )
        if coverage_status_of(coverage, domain) is DomainCoverageStatus.SKIPPED:
            not_analysed.append(area_label(domain))
        elif coverage_status_of(coverage, domain) is DomainCoverageStatus.EVALUATED:
            analysed.append(area_label(domain))

    data: dict[str, Any] = {
        "giorno": day(runtime.as_of),
        "stato dell'analisi": feed_state_text(feed, areas),
        "decisioni che richiedono attenzione": len(visible_items),
        "aree": rows,
    }
    if visible_items:
        first = visible_items[0].decision
        data["prima decisione nell'ordine di NINFA"] = {
            "riferimento": ref_token(first.id),
            "titolo": semantic_labels.decision_label_of(first.decision_type),
            "area": area_label(DOMAIN_OF_DECISION_TYPE[first.decision_type]),
        }
    not_available: list[str] = []
    if run is not None and not hidden:
        # The two counts are domain-blind by construction: withheld whenever an area is hidden.
        data["controlli rimasti senza conclusione per dati insufficienti"] = run.insufficient_count
        data["controlli non mostrati perché poco affidabili"] = run.suppressed_count
    if run is None:
        not_available.append("l'analisi del giorno richiesto non è disponibile")

    last = feed.last_successful_analysis
    freshness: dict[str, Any] = {
        "analisi del giorno presente": run is not None,
        "giorno dell'ultima analisi completata": (
            iso(last.as_of_local_date)
            if last is not None
            else (iso(run.as_of_local_date) if run is not None else None)
        ),
    }
    coverage_data: dict[str, Any] = {
        "copertura dell'analisi": coverage_text(coverage, run is not None),
        "aree analizzate": analysed,
        "aree non analizzate": not_analysed,
    }
    notes = [
        "Le decisioni sono prodotte dal motore di NINFA: Mia le spiega, non le crea "
        "né le modifica.",
        "NINFA non registra il motivo per cui un controllo non ha concluso: non ipotizzarne uno "
        "(storico ancora corto, nessuna nuova prenotazione, poca affidabilità...).",
        "L'ordine delle decisioni è quello di NINFA: riportalo, non spiegare "
        "perché una viene prima.",
    ]
    if hidden:
        notes.append("Alcune aree non sono consentite a questo utente e non sono incluse.")
    return Observation(
        tool="get_today_summary",
        refs=("decisioni:oggi",),
        data=data,
        coverage=coverage_data,
        freshness=freshness,
        not_available=tuple(not_available),
        notes=tuple(notes),
        resolved={},
    )


# --- tool 2: list_decisions


class ListDecisionsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date | None = Field(
        default=None,
        description=(
            "Il giorno di analisi (AAAA-MM-GG). Se assente: oggi (la data di riferimento). Usalo "
            "solo con `status` assente: elenca le decisioni di quel giorno nell'ordine di NINFA."
        ),
    )
    area: AreaArg | None = Field(
        default=None, description="Limita a un'area: ricavi, distribuzione, costi, personale."
    )
    status: Literal["open", "all"] | None = Field(
        default=None,
        description=(
            "Se assente: le decisioni del giorno, nell'ordine di priorità di NINFA (quello che "
            "mostra la schermata Decisioni). 'open': le decisioni oggi ancora aperte; "
            "'all': tutte, "
            "anche risolte. Con 'open' o 'all' l'ordine è per ultima valutazione, NON di priorità."
        ),
    )
    limit: int = Field(default=5, ge=1, le=MAX_LIST_ROWS)


def _list_decisions(runtime: ToolRuntime, args: ListDecisionsArgs) -> Observation:
    areas = visible_areas(runtime)
    hidden = len(areas) < len(AnalysisDomain)
    wanted = None if args.area is None else _AREA_OF_ARG[args.area]
    if wanted is not None and wanted not in areas:
        return Observation(
            tool="list_decisions",
            refs=("decisioni:elenco",),
            data={"decisioni": []},
            not_available=("quest'area non è consentita a questo utente",),
            resolved={"area": args.area},
        )

    rows: list[dict[str, Any]] = []
    not_available: list[str] = []
    if args.status is None:
        feed_day = args.day or runtime.as_of
        feed = runtime.feed(feed_day)
        items = [
            item
            for item in _decisions_in(feed, areas)
            if wanted is None or DOMAIN_OF_DECISION_TYPE[item.decision.decision_type] is wanted
        ]
        for position, item in enumerate(items[: args.limit], start=1):
            rows.append(_decision_row(runtime, item.decision, item.observation, position=position))
        origin = "decisioni del giorno, nell'ordine di priorità di NINFA"
        if not items:
            not_available.append(
                "nessuna decisione per questo giorno"
                + (" in quest'area" if wanted is not None else "")
                + ": "
                + feed_state_text(feed, areas)
            )
        refs = ["decisioni:elenco"]
        resolved: dict[str, Any] = {
            "giorno": feed_day.isoformat(),
            "area": args.area,
            "limite": args.limit,
        }
        shown_day: str | None = day(feed_day)
    else:
        page = runtime.memory().list_decisions_page(
            runtime.property_id,
            status=DecisionStatus.OPEN if args.status == "open" else None,
            decision_type=None,
            limit=_MEMORY_PAGE,
            after=None,
        )
        kept = [
            decision
            for decision in page.decisions
            if DOMAIN_OF_DECISION_TYPE[decision.decision_type] in areas
            and (wanted is None or DOMAIN_OF_DECISION_TYPE[decision.decision_type] is wanted)
        ]
        for decision in kept[: args.limit]:
            rows.append(
                _decision_row(
                    runtime, decision, page.latest_observations[decision.id], position=None
                )
            )
        origin = (
            "memoria delle decisioni, per ultima valutazione: non è l'ordine di priorità di NINFA"
        )
        if not kept:
            not_available.append("nessuna decisione corrisponde ai filtri richiesti")
        refs = ["decisioni:elenco"]
        resolved = {"stato": args.status, "area": args.area, "limite": args.limit}
        shown_day = None
    refs.extend(f"decisione:{row['riferimento']}" for row in rows)
    notes = [
        "Le decisioni sono prodotte dal motore di NINFA: Mia le spiega, non le crea "
        "né le modifica.",
        "Gli impatti sono stime indicative, mai valori certi.",
        "Per spiegare una decisione serve il suo riferimento: passalo allo strumento "
        "che le spiega.",
    ]
    if hidden:
        notes.append("Alcune aree non sono consentite a questo utente e non sono incluse.")
    data: dict[str, Any] = {
        "origine dell'elenco": origin,
        "decisioni": rows,
        "valuta": runtime.currency,
    }
    if shown_day is not None:
        data["giorno"] = shown_day
    return Observation(
        tool="list_decisions",
        refs=tuple(refs),
        data=data,
        not_available=tuple(not_available),
        notes=tuple(notes),
        resolved=resolved,
    )


# --- tool 3: explain_decision

_RELIABILITY_PREFIX = "Affidabilità"
_OBSERVED_LABELS = ("Giorni con dati osservati", "Periodi con dati osservati")
_RECONSTRUCTED_LABELS = ("Giorni con dati ricostruiti",)


class ExplainDecisionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(
        min_length=8,
        max_length=64,
        description=(
            "Il riferimento della decisione, preso da list_decisions / get_today_summary oppure "
            "dal contesto della pagina ('decisione selezionata'). Mai inventato."
        ),
    )


def _not_found(token: str) -> Observation:
    return Observation(
        tool="explain_decision",
        refs=(),
        data={"decisione trovata": False},
        not_available=(_NOT_FOUND,),
        resolved={"riferimento": token[:64]},
    )


def _split_evidence(
    points: tuple[AskDataPoint, ...],
) -> tuple[list[AskDataPoint], list[AskDataPoint], list[AskDataPoint], dict[str, str]]:
    """(impact, reliability, other data used, observed / reconstructed counts)."""
    impact, reliability, used = [], [], []
    provenance: dict[str, str] = {}
    for point in points:
        if "stima indicativa" in point.label:
            impact.append(point)
        elif point.label.startswith(_RELIABILITY_PREFIX):
            reliability.append(point)
        elif point.label in _OBSERVED_LABELS:
            provenance["dati osservati"] = point.value
            used.append(point)
        elif point.label in _RECONSTRUCTED_LABELS:
            provenance["dati ricostruiti"] = point.value
            used.append(point)
        else:
            used.append(point)
    return impact, reliability, used, provenance


def _explain(runtime: ToolRuntime, args: ExplainDecisionArgs) -> Observation:
    decision_id = parse_ref(args.decision_id)
    if decision_id is None:
        return _not_found(args.decision_id)
    memory = runtime.memory()
    decision = memory.get_decision(decision_id)
    # a missing id, another workspace's, another property's and an area the user may not reach are
    # the same answer: nothing is said about which one it was
    if decision is None or decision.property_id != runtime.property_id:
        return _not_found(args.decision_id)
    domain = DOMAIN_OF_DECISION_TYPE[decision.decision_type]
    if not runtime.allows(access_domain_of(domain)):
        return _not_found(args.decision_id)
    latest = memory.get_latest_observation(decision_id)
    if latest is None:  # a decision always has an observation: defensive
        return _not_found(args.decision_id)

    history_page = memory.get_history_page_desc(decision_id, limit=HISTORY_LIMIT, after=None)
    history = [row.observation for row in history_page.items]
    recommendation = RecommendationEngine().evaluate(decision, latest)
    context: AskDecisionContext = AskDecisionContextBuilder().build(
        decision, latest, recommendation, history
    )

    impact, reliability, used, provenance = _split_evidence(context.latest.evidence)
    feed = runtime.feed()
    areas = visible_areas(runtime)
    visible_feed = _decisions_in(feed, areas)
    position = next(
        (i for i, item in enumerate(visible_feed, start=1) if item.decision.id == decision.id),
        None,
    )
    detail: dict[str, Any] = {
        "decisione trovata": True,
        "riferimento": ref_token(decision.id),
        "titolo": context.decision_label,
        "area": area_label(domain),
        "cosa ha controllato NINFA": semantic_labels.decision_description_of(
            decision.decision_type
        ),
        "riguarda": _target_of(decision),
        "stato": context.decision_status,
        "esito dell'ultima valutazione": context.latest.status_label,
        "tra le decisioni di oggi": position is not None,
        "valori rilevati": _points(context.latest.facts),
        "affidabilità (su cento)": context.latest.confidence,
        "valuta": runtime.currency,
    }
    if position is not None:
        detail["posizione nell'ordine di NINFA"] = position
    if reliability:
        detail["affidabilità delle basi usate"] = _points(tuple(reliability))
    if impact:
        detail["impatto stimato"] = _points(tuple(impact))
    primary = context.recommendation.primary_action
    missing: list[str] = []
    if primary is not None:
        detail["cosa suggerisce NINFA di verificare"] = {
            "azione": primary.title,
            "descrizione": primary.description,
            "avvertenze": list(primary.risk_notes),
            "controlli di supporto": [c.title for c in context.recommendation.supporting_checks],
        }
    else:
        detail["cosa suggerisce NINFA di verificare"] = None
        missing.append(
            "NINFA non ha un'azione da suggerire per questa decisione con i dati disponibili"
        )
    detail["andamento nelle ultime valutazioni"] = [
        {
            "giorno": entry.as_of_local_date,
            "esito": entry.status_label,
            "affidabilità (su cento)": entry.confidence,
            "dati principali": _points(entry.facts[:MAX_LIST_FACTS]),
        }
        for entry in context.history
    ]
    if not context.latest.facts:
        missing.append("i valori rilevati di questa decisione non sono disponibili")
    coverage_data = {
        "dati e storico usati": _points(tuple(used)),
    }
    freshness = {
        "vista la prima volta": context.first_seen_local_date,
        "ultima volta in cui era presente": context.last_seen_local_date,
        "ultima valutazione": context.last_evaluated_local_date,
        "risolta il": context.resolved_local_date,
        "episodi": context.episode_count,
        **provenance,
    }
    return Observation(
        tool="explain_decision",
        refs=(f"decisione:{ref_token(decision.id)}",),
        data=detail,
        coverage=coverage_data,
        freshness=freshness,
        not_available=tuple(missing),
        notes=(
            "Spiega con parole semplici cosa ha controllato NINFA e cosa ha trovato; non citare "
            "codici o nomi tecnici.",
            "Gli impatti sono stime indicative, mai valori certi. L'affidabilità è su una scala "
            "da zero a cento e non va trasformata in altro.",
            "La decisione è prodotta dal motore di NINFA: Mia la spiega, non la crea né la cambia.",
            "L'ordine di priorità si riporta, non si spiega.",
        ),
        resolved={"riferimento": ref_token(decision.id)},
    )


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="get_today_summary",
        description=(
            "Riepilogo dell'analisi di oggi: quante decisioni richiedono attenzione, lo stato di "
            "ogni area (ricavi, distribuzione, costi, personale), e il motivo per cui può non "
            "esserci nessuna decisione (analisi non ancora fatta, controlli senza dati "
            "sufficienti, "
            "aree non analizzate). Usalo per 'perché oggi non ho decisioni?', 'come sta andando "
            "oggi?', 'qual è la decisione più importante?'. Nessun argomento."
        ),
        domain=None,
        args_model=_NoArgs,
        handler=_today_summary,
    ),
    ToolDefinition(
        name="list_decisions",
        description=(
            "Elenco delle decisioni del motore di NINFA: quelle di un giorno nell'ordine di "
            "priorità (default: oggi), oppure la memoria delle decisioni aperte o di tutte. Ogni "
            "decisione ha un riferimento da passare a explain_decision. Mia non crea né modifica "
            "decisioni."
        ),
        domain=None,
        args_model=ListDecisionsArgs,
        handler=_list_decisions,
    ),
    ToolDefinition(
        name="explain_decision",
        description=(
            "Spiega UNA decisione: cosa ha controllato NINFA, valore rilevato e atteso, "
            "scostamento, impatto stimato, affidabilità, dati usati, andamento nelle ultime "
            "valutazioni, cosa suggerisce di verificare. Usalo per 'perché me lo stai dicendo?'. "
            "Serve il riferimento della decisione (da list_decisions, da get_today_summary o dal "
            "contesto della pagina)."
        ),
        domain=None,
        args_model=ExplainDecisionArgs,
        handler=_explain,
    ),
)

__all__ = [
    "TOOLS",
    "area_outcome",
    "coverage_of",
    "coverage_status_of",
    "coverage_text",
    "feed_state_text",
    "parse_ref",
    "ref_token",
    "visible_areas",
]

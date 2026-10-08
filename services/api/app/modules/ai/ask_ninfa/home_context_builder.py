"""AskHomeContextBuilder: pure, framework-free, testable.

    AskHomeContextBuilder().build(feed, timezone) -> AskHomeContext

The ONLY input is a `FeedResult` - exactly what `DecisionMemoryService.get_feed()` already returned
for the Decision Feed endpoint (Gate 12) - plus the property's own timezone (to express an import
instant in property-local time, never the server's). No database session, no query of its own: Mia
Home can therefore never see anything the Decision Feed itself would not, and can never "find" a
problem a detector did not already trigger (ENGINE CALCULATES, MIA EXPLAINS - see ADR 0028).

Explicit whitelisting only, exactly like `AskDecisionContextBuilder`: no `dataclasses.asdict()`, no
`__dict__`. Facts go through the SAME shared whitelist (`app.modules.decisions.whitelist`) and the
SAME semantic labels (`semantic_labels.py`) the Decision Ask already uses - one whitelist, one
vocabulary, never a second one that could drift. Every `*_data_source_id` is stripped a second
time, exactly as the Decision Ask does (ADR 0025).
"""

from datetime import date
from zoneinfo import ZoneInfo

from app.modules.ai.ask_ninfa import semantic_labels
from app.modules.ai.ask_ninfa.context_builder import (
    _target_context_of,
    _without_data_source_ids,
)
from app.modules.ai.ask_ninfa.home_types import (
    MAX_HOME_DECISIONS,
    AskHomeAreaCoverage,
    AskHomeContext,
    AskHomeCoverageContext,
    AskHomeDecisionContext,
    AskHomeFreshnessContext,
)
from app.modules.ai.ask_ninfa.home_vocabulary import normalize_text
from app.modules.ai.ask_ninfa.types import AskDataPoint
from app.modules.decision_memory.types import FeedItem, FeedResult, FeedState
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    CoverageSummary,
    DomainCoverageStatus,
)
from app.modules.decisions.models import Decision, DecisionRun
from app.modules.decisions.precision import canonical_text
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.decisions.whitelist import evidence_of, facts_of
from app.modules.intelligence.priority.types import PriorityDecisionType

# --- feed state -> Italian ------------------------------------------------------------------
# The SAME meaning the product UI ships for each state (`apps/web/lib/copy.ts`, `copy.today`):
# "nessuna decisione richiede attenzione" is NEVER used for any other state than the one that
# really means it.
_ANALYSIS_STATE_LABELS: dict[FeedState, str] = {
    FeedState.ACTION_REQUIRED: "Ci sono decisioni che richiedono attenzione",
    FeedState.NO_ACTION_REQUIRED: "Nessuna decisione richiede attenzione in questo momento",
    FeedState.DATA_QUALITY_LIMITED: (
        "Analisi parziale: alcuni controlli non dispongono ancora di dati sufficienti"
    ),
    FeedState.NOT_PROCESSED: "L'analisi di oggi non è ancora disponibile",
}

# --- analysis domain -> Italian ----------------------------------------------------------------
# The SAME four user-facing names the Home's domain summary ships (`apps/web/lib/copy.ts`,
# `analysisDomainLabels`).
_DOMAIN_LABELS: dict[AnalysisDomain, str] = {
    AnalysisDomain.REVENUE: "Ricavi",
    AnalysisDomain.DISTRIBUTION: "Distribuzione",
    AnalysisDomain.COSTS: "Costi",
    AnalysisDomain.LABOR: "Personale",
}

# decision_type -> analysis domain: the grouping `decisions/coverage.py` documents, written out
# explicitly (and tested exhaustive over `PriorityDecisionType`) so a sixth decision type cannot
# silently fall outside every area.
DOMAIN_OF_DECISION_TYPE: dict[PriorityDecisionType, AnalysisDomain] = {
    PriorityDecisionType.REV_PICKUP_LOW: AnalysisDomain.REVENUE,
    PriorityDecisionType.REV_OCCUPANCY_RISK: AnalysisDomain.REVENUE,
    PriorityDecisionType.REV_OTA_DEPENDENCY: AnalysisDomain.DISTRIBUTION,
    PriorityDecisionType.COST_CPOR_ANOMALY: AnalysisDomain.COSTS,
    PriorityDecisionType.LABOR_OVERSTAFFING: AnalysisDomain.LABOR,
}

_COVERAGE_SUMMARY_LABELS: dict[CoverageSummary, str] = {
    CoverageSummary.FULL: "tutte le aree sono state analizzate",
    CoverageSummary.PARTIAL: "alcune aree non sono state analizzate",
    CoverageSummary.UNKNOWN: "copertura dell'analisi non disponibile per questa analisi",
}

_DOMAIN_STATUS_LABELS: dict[DomainCoverageStatus, str] = {
    DomainCoverageStatus.EVALUATED: "analizzata",
    DomainCoverageStatus.SKIPPED: "non analizzata",
}

_ORDINALS = (
    "prima",
    "seconda",
    "terza",
    "quarta",
    "quinta",
    "sesta",
    "settima",
    "ottava",
    "nona",
    "decima",
)

# Economic proxies the Engine ALREADY recorded, one per decision type: (payload, key, currency
# key, label). Mirrors the keys `app.api.v1.decisions.serializers.economic_proxy_of` and the
# Decision Ask's own `EVIDENCE_LABELS` already read - never a recomputation. Revenue and OTA proxies
# carry no currency anywhere in the engine's own types, so none is ever invented for them.
_INDICATIVE = "stima indicativa, non un valore certo"
_IMPACT_SPECS: dict[PriorityDecisionType, tuple[str, str, str | None, str]] = {
    PriorityDecisionType.REV_PICKUP_LOW: (
        "evidence",
        "revenue_gap_proxy",
        None,
        f"Impatto sui ricavi ({_INDICATIVE})",
    ),
    PriorityDecisionType.REV_OCCUPANCY_RISK: (
        "evidence",
        "revenue_gap_proxy",
        None,
        f"Impatto sui ricavi ({_INDICATIVE})",
    ),
    PriorityDecisionType.REV_OTA_DEPENDENCY: (
        "evidence",
        "ota_room_revenue_exposure",
        None,
        f"Ricavo esposto su OTA ({_INDICATIVE})",
    ),
    PriorityDecisionType.COST_CPOR_ANOMALY: (
        "facts",
        "cost_gap_proxy_exact",
        "currency",
        f"Scarto di costo ({_INDICATIVE})",
    ),
    PriorityDecisionType.LABOR_OVERSTAFFING: (
        "evidence",
        "labor_cost_gap_proxy_exact",
        "cost_currency",
        f"Impatto sui costi del personale ({_INDICATIVE})",
    ),
}

# WHAT KIND of estimate each proxy is. Two estimates are only comparable when their kind matches: a
# revenue gap, the revenue exposed on OTAs and a cost excess are three different things (and the
# first two carry no currency in the engine at all), so Mia is told the kind next to every estimate
# instead of being left to guess whether "540.00" and "482.30" can be set side by side.
_IMPACT_KIND_REVENUE = "ricavi"
_IMPACT_KIND_OTA_EXPOSURE = "ricavo esposto su OTA"
_IMPACT_KIND_COSTS = "costi"
_IMPACT_KINDS: dict[PriorityDecisionType, str] = {
    PriorityDecisionType.REV_PICKUP_LOW: _IMPACT_KIND_REVENUE,
    PriorityDecisionType.REV_OCCUPANCY_RISK: _IMPACT_KIND_REVENUE,
    PriorityDecisionType.REV_OTA_DEPENDENCY: _IMPACT_KIND_OTA_EXPOSURE,
    PriorityDecisionType.COST_CPOR_ANOMALY: _IMPACT_KIND_COSTS,
    PriorityDecisionType.LABOR_OVERSTAFFING: _IMPACT_KIND_COSTS,
}

_CURRENCY_WORDS = {"EUR": "euro"}

# The keys `_target_context_of` (shared with the Decision Ask) returns are snake_case identifiers; a
# model that echoed one would trip the technical-leak check (and read badly), so the Home context
# renames each to a plain Italian phrase. A key with NO entry here - including `currency`, which the
# economic-impact `unità` already carries - is DROPPED, never passed through raw (the same fail-safe
# default `semantic_labels.data_points_of` applies).
_TARGET_KEY_LABELS: dict[str, str] = {
    "stay_date": "data del soggiorno",
    "period_start": "inizio del periodo",
    "work_date": "giorno di lavoro",
    "cost_category": "categoria di costo",
    "labor_category": "reparto",
}


# The semantic slug each decision type carries in its grounding ref ("decision:pickup:2026-10-05"):
# hyphenated on purpose - an underscore would make a ref echoed by a model look like a technical
# identifier to the leak check.
_DECISION_REF_SLUGS: dict[PriorityDecisionType, str] = {
    PriorityDecisionType.REV_PICKUP_LOW: "pickup",
    PriorityDecisionType.REV_OCCUPANCY_RISK: "occupancy-risk",
    PriorityDecisionType.REV_OTA_DEPENDENCY: "ota-dependency",
    PriorityDecisionType.COST_CPOR_ANOMALY: "cost-per-room",
    PriorityDecisionType.LABOR_OVERSTAFFING: "labor-hours",
}
_REF_TARGET_KEYS = ("stay_date", "period_start", "work_date", "cost_category", "labor_category")

# "coverage:<area>": the ref naming an analysed (or skipped) area in structured response metadata.
COVERAGE_REF_OF_DOMAIN: dict[AnalysisDomain, str] = {
    AnalysisDomain.REVENUE: "coverage:revenue",
    AnalysisDomain.DISTRIBUTION: "coverage:distribution",
    AnalysisDomain.COSTS: "coverage:costs",
    AnalysisDomain.LABOR: "coverage:labor",
}


def _decision_ref(decision: Decision) -> str:
    raw = _target_context_of(decision)
    parts = [_DECISION_REF_SLUGS[decision.decision_type]]
    parts.extend(
        "-".join(normalize_text(raw[key]).split()) for key in _REF_TARGET_KEYS if key in raw
    )
    return "decision:" + ":".join(parts)


def _target_of(decision: Decision) -> dict[str, str]:
    return {
        _TARGET_KEY_LABELS[key]: value
        for key, value in _target_context_of(decision).items()
        if key in _TARGET_KEY_LABELS
    }


def _economic_impact_of(
    decision_type: PriorityDecisionType,
    facts: dict[str, object],
    evidence: dict[str, object],
) -> tuple[AskDataPoint, ...]:
    source, key, currency_key, label = _IMPACT_SPECS[decision_type]
    payload = facts if source == "facts" else evidence
    value = payload.get(key)
    if value is None:
        return ()
    unit: str | None = None
    if currency_key is not None:
        currency = payload.get(currency_key)
        if not isinstance(currency, str):
            return ()  # a proxy with a currency dimension but no currency is never guessed at
        unit = _CURRENCY_WORDS.get(currency, currency)
    return (AskDataPoint(label=label, value=str(value), unit=unit),)


def _decision_context_of(index: int, item: FeedItem) -> AskHomeDecisionContext:
    decision, observation = item.decision, item.observation
    decision_type = decision.decision_type
    all_facts = facts_of(decision_type, observation.facts_payload)
    all_evidence = evidence_of(decision_type, observation.evidence_payload)
    # `data_points_of` stringifies whatever it is given: a recorded-but-null fact would otherwise
    # surface as the literal word "None", so nulls are dropped BEFORE labelling.
    semantic_facts = semantic_labels.data_points_of(
        semantic_labels.FACT_LABELS[decision_type],
        _without_data_source_ids(
            {key: value for key, value in all_facts.items() if value is not None}
        ),
    )
    confidence = canonical_text(observation.confidence_score)
    assert confidence is not None  # NOT NULL on DecisionObservation, see context_builder.py
    economic_impact = _economic_impact_of(decision_type, all_facts, all_evidence)
    return AskHomeDecisionContext(
        position=_ORDINALS[index],
        decision_label=semantic_labels.decision_label_of(decision_type),
        description=semantic_labels.decision_description_of(decision_type),
        area=_DOMAIN_LABELS[DOMAIN_OF_DECISION_TYPE[decision_type]],
        status_label=semantic_labels.observation_status_label_of(
            observation.lifecycle_transition, observation.source_status
        ),
        target=_target_of(decision),
        confidence=confidence,
        first_seen_local_date=decision.first_seen_local_date.isoformat(),
        episode_count=decision.episode_count,
        facts=semantic_facts,
        # No estimate recorded -> no kind either: an empty list never claims to be "of" anything.
        impact_kind=_IMPACT_KINDS[decision_type] if economic_impact else None,
        economic_impact=economic_impact,
        ref=_decision_ref(decision),
    )


def _coverage_context_of(run: DecisionRun) -> AskHomeCoverageContext:
    raw = run.analysis_coverage
    if raw is None:
        # A run persisted before Gate 22: UNKNOWN, never inferred as FULL or PARTIAL.
        return AskHomeCoverageContext(
            summary_label=_COVERAGE_SUMMARY_LABELS[CoverageSummary.UNKNOWN], areas=()
        )
    coverage = AnalysisCoverage.from_json(raw)
    return AskHomeCoverageContext(
        summary_label=_COVERAGE_SUMMARY_LABELS[coverage.summary],
        areas=tuple(
            AskHomeAreaCoverage(
                area=_DOMAIN_LABELS[item.domain],
                status_label=_DOMAIN_STATUS_LABELS[item.status],
                ref=COVERAGE_REF_OF_DOMAIN[item.domain],
            )
            for item in coverage.domains
        ),
    )


def _freshness_context_of(
    run: DecisionRun, business_date: date, timezone: ZoneInfo
) -> AskHomeFreshnessContext:
    unknown = AskHomeFreshnessContext(
        known=False, local_date=None, local_time=None, relative_day=None
    )
    raw = run.input_provenance
    if raw is None:
        return unknown
    finished_at = RunInputProvenance.from_json(raw).bookings.last_successful_import_finished_at
    if finished_at is None:
        return unknown
    local = finished_at.astimezone(timezone)
    relative: str | None = None
    delta_days = (business_date - local.date()).days
    if delta_days == 0:
        relative = "oggi"
    elif delta_days == 1:
        relative = "ieri"
    return AskHomeFreshnessContext(
        known=True,
        local_date=local.date().isoformat(),
        local_time=local.strftime("%H:%M"),
        relative_day=relative,
    )


class AskHomeContextBuilder:
    def build(self, feed: FeedResult, timezone: ZoneInfo) -> AskHomeContext:
        run = feed.run
        visible = feed.items[:MAX_HOME_DECISIONS]
        decisions = tuple(_decision_context_of(index, item) for index, item in enumerate(visible))
        return AskHomeContext(
            business_date=feed.as_of_local_date.isoformat(),
            analysis_state=_ANALYSIS_STATE_LABELS[feed.state],
            decisions_total=len(feed.items),
            decisions=decisions,
            decisions_omitted=len(feed.items) - len(visible),
            insufficient_checks=None if run is None else run.insufficient_count,
            low_confidence_checks=None if run is None else run.suppressed_count,
            coverage=None if run is None else _coverage_context_of(run),
            freshness=(
                None if run is None else _freshness_context_of(run, feed.as_of_local_date, timezone)
            ),
            last_successful_analysis_date=(
                None
                if feed.last_successful_analysis is None
                else feed.last_successful_analysis.as_of_local_date.isoformat()
            ),
        )


__all__ = ["COVERAGE_REF_OF_DOMAIN", "DOMAIN_OF_DECISION_TYPE", "AskHomeContextBuilder"]

"""The vocabulary of Mia Home (property-level Ask): a grounded, single-turn explanation of what
NINFA ALREADY decided today for one property - never a second detector, never a raw-data analyst.

ENGINE CALCULATES, MIA EXPLAINS: every field of `AskHomeContext` was already decided by the Decision
Engine, the Priority Engine, the Decision Layer, the analysis-coverage rules (Gate 22) or the
booking-input provenance (Gate 23B) - this module only assembles what `DecisionMemoryService
.get_feed()` already returned into a closed, whitelisted, model-facing shape. Same posture as the
Decision Ask's own `AskDecisionContext` (`types.py`), at feed scope instead of one Decision's scope.
Nothing here is persisted: no conversation, no message (see ADR 0028).
"""

from dataclasses import dataclass
from enum import StrEnum

from app.modules.ai.ask_ninfa.types import AskDataPoint

# A feed can carry more triggered candidates than a short, operative answer can usefully compare;
# the context names exactly how many exist (`decisions_total`) and how many were left out
# (`decisions_omitted`) so the model can say so instead of implying completeness.
MAX_HOME_DECISIONS = 10

ASK_MIA_HOME_INSTRUCTIONS_VERSION = "ask-mia-home-v1"


class HomeGroundingRef(StrEnum):
    """A closed, semantic vocabulary of WHICH part of `AskHomeContext` an answer drew on - never a
    database id or a row number. Deliberately separate from the Decision Ask's own `GroundingRef`
    (a Decision's facts/evidence/recommendation/history are not what the Home context contains)."""

    ANALYSIS_STATE = "ANALYSIS_STATE"
    DECISIONS = "DECISIONS"
    ECONOMIC_IMPACT = "ECONOMIC_IMPACT"
    COVERAGE = "COVERAGE"
    FRESHNESS = "FRESHNESS"
    LAST_ANALYSIS = "LAST_ANALYSIS"


@dataclass(frozen=True, slots=True)
class AskHomeDecisionContext:
    """One triggered Decision of today's feed, exactly as the Engine ranked it. `position` is an
    Italian ordinal word ("prima", "seconda", ...) - never a bare rank number, never a score: the
    list ORDER is NINFA's own priority order and `position` only names it in words (see ADR 0026,
    "why priority is not verbalised", kept for the Home on purpose). `area` is the user-facing
    analysis domain ("Ricavi", "Distribuzione", "Costi", "Personale"). `economic_impact` carries
    only proxies the Engine already recorded, each labelled as an indicative estimate."""

    position: str
    decision_label: str
    area: str
    status_label: str
    target: dict[str, str]
    confidence: str
    first_seen_local_date: str
    episode_count: int
    facts: tuple[AskDataPoint, ...]
    economic_impact: tuple[AskDataPoint, ...]


@dataclass(frozen=True, slots=True)
class AskHomeAreaCoverage:
    area: str
    status_label: str


@dataclass(frozen=True, slots=True)
class AskHomeCoverageContext:
    summary_label: str
    areas: tuple[AskHomeAreaCoverage, ...]


@dataclass(frozen=True, slots=True)
class AskHomeFreshnessContext:
    """A plain FACT about the last SUCCEEDED booking import known at analysis time - never a
    CURRENT/STALE judgement (Gate 23B). `known` False means "no factual timestamp exists": the
    other fields are then `None`, never a guessed one. `local_date`/`local_time` are in the
    PROPERTY's own timezone; `relative_day` is "oggi"/"ieri" relative to the business date of the
    analysis, or `None` for an older import."""

    known: bool
    local_date: str | None
    local_time: str | None
    relative_day: str | None


@dataclass(frozen=True, slots=True)
class AskHomeContext:
    """The ENTIRE grounding boundary of Mia Home: this, and nothing else, is what a language model
    provider ever sees about the property. No property name, no workspace/property/decision id, no
    data-source id, no raw booking/invoice/labor row, no detector threshold, no session/auth data.

    `coverage`/`freshness` are `None` exactly when the run they would describe does not exist
    (`NOT_PROCESSED`): never a fabricated "all areas analysed" and never a guessed import time.
    `insufficient_checks`/`low_confidence_checks` are the run's own counts (`None` without a run)
    and are only ever presented as counts of checks, never attributed to an area (the run's counts
    are domain-blind - Gate 22A)."""

    business_date: str
    analysis_state: str
    decisions_total: int
    decisions: tuple[AskHomeDecisionContext, ...]
    decisions_omitted: int
    insufficient_checks: int | None
    low_confidence_checks: int | None
    coverage: AskHomeCoverageContext | None
    freshness: AskHomeFreshnessContext | None
    last_successful_analysis_date: str | None


__all__ = [
    "ASK_MIA_HOME_INSTRUCTIONS_VERSION",
    "MAX_HOME_DECISIONS",
    "AskHomeAreaCoverage",
    "AskHomeContext",
    "AskHomeCoverageContext",
    "AskHomeDecisionContext",
    "AskHomeFreshnessContext",
    "HomeGroundingRef",
]

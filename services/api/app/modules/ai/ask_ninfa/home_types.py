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

from app.modules.ai.ask_ninfa.home_facts import OperationalContext
from app.modules.ai.ask_ninfa.types import AskDataPoint

# A feed can carry more triggered candidates than a short, operative answer can usefully compare;
# the context names exactly how many exist (`decisions_total`) and how many were left out
# (`decisions_omitted`) so the model can say so instead of implying completeness.
MAX_HOME_DECISIONS = 10

# The Home's own answer ceiling. The Decision Ask's `MAX_ANSWER_CHARS` (700) fits ONE Decision; a
# useful Home answer ("ci sono altri problemi?", "quale ha l'impatto più alto?") names several
# decisions with their area, target and impact, ~60-160 words by default and up to ~220 when it
# compares them. 1800 characters is that upper bound plus headroom for Italian's longer words and a
# few line breaks - a HARD fail-closed ceiling exactly like the Decision Ask's (an overlong answer
# is UNAVAILABLE, never truncated), never a style target: the length the model aims for lives in
# `home_instructions.py`.
MAX_HOME_ANSWER_CHARS = 1800

ASK_MIA_HOME_INSTRUCTIONS_VERSION = "ask-mia-home-v3"


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
    analysis domain ("Ricavi", "Distribuzione", "Costi", "Personale"). `description` is one fixed
    plain-Italian sentence per decision TYPE saying what NINFA checked (the same wording the Home's
    hero already ships - no number, no judgement, nothing the Engine did not decide).
    `economic_impact` carries only proxies the Engine already recorded, each labelled as an
    indicative estimate; `impact_kind` names WHAT KIND of estimate that is ("ricavi", "ricavo
    esposto su OTA", "costi") so Mia can compare two estimates only when they are of the same kind
    - `None` exactly when `economic_impact` is empty."""

    position: str
    decision_label: str
    description: str
    area: str
    status_label: str
    target: dict[str, str]
    confidence: str
    first_seen_local_date: str
    episode_count: int
    facts: tuple[AskDataPoint, ...]
    impact_kind: str | None
    economic_impact: tuple[AskDataPoint, ...]
    # The grounding ref naming this decision in structured response metadata ("decision:..."),
    # never shown to the end user. Empty only for a hand-built test context.
    ref: str = ""


@dataclass(frozen=True, slots=True)
class AskHomeAreaCoverage:
    area: str
    status_label: str
    ref: str = ""  # "coverage:<area>", e.g. "coverage:distribution"


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
    ref: str = "freshness:bookings"


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
    # Deterministic facts fetched for THIS question on top of the feed (occupancy, OTA share, ...);
    # `None` for a question that needs nothing beyond the feed.
    operational: OperationalContext | None = None


def grounding_vocabulary(context: AskHomeContext) -> tuple[str, ...]:
    """The closed set of `grounding_refs` a model may name for THIS request: the fixed base refs
    plus exactly the refs present in `context` (its decisions, covered areas, freshness and any
    operational section). A ref the model invents is outside this set and is dropped by validation
    - it can never smuggle a made-up source into the response metadata."""
    refs: dict[str, None] = dict.fromkeys(ref.value for ref in HomeGroundingRef)
    for decision in context.decisions:
        if decision.ref:
            refs.setdefault(decision.ref, None)
    if context.coverage is not None:
        for area in context.coverage.areas:
            if area.ref:
                refs.setdefault(area.ref, None)
    if context.freshness is not None and context.freshness.ref:
        refs.setdefault(context.freshness.ref, None)
    if context.operational is not None:
        for ref in context.operational.refs:
            refs.setdefault(ref, None)
    return tuple(refs)


__all__ = [
    "ASK_MIA_HOME_INSTRUCTIONS_VERSION",
    "MAX_HOME_ANSWER_CHARS",
    "MAX_HOME_DECISIONS",
    "AskHomeAreaCoverage",
    "AskHomeContext",
    "AskHomeCoverageContext",
    "AskHomeDecisionContext",
    "AskHomeFreshnessContext",
    "HomeGroundingRef",
    "grounding_vocabulary",
]

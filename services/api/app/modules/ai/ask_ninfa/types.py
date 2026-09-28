"""The vocabulary of Ask NINFA Core V1: a grounded, single-turn, decision-scoped explanation layer.

ENGINE CALCULATES, AI EXPLAINS: every number in `AskDecisionContext` was already decided by a real
detector, the Priority Engine, the Decision Layer or the Recommendation Engine (Gates 4-16) - this
module never recomputes a delta, a confidence, a rank or a recommendation, it only assembles what
those layers already decided into a closed, whitelisted, model-facing shape. Nothing here is
persisted: no Conversation table, no Message table (see ADR 0024, "why no conversation
persistence") - V1 is one question, one answer.
"""

from dataclasses import dataclass
from enum import StrEnum

MIN_QUESTION_LENGTH = 1
MAX_QUESTION_LENGTH = 1000

# Gate 16's own `MAX_SUPPORTING_CHECKS` bound-style constant, reused here for the SAME reason: a
# predictable, small, deterministic context shape - never "all history there ever was".
MAX_HISTORY_OBSERVATIONS = 10

# "Massimo ragionevole V1" per the spec: a short, operative answer, never an essay. Overlong
# provider output is TRUNCATED to this bound (never rejected outright - a real, grounded answer
# that ran a little long is still more useful than discarding it), documented policy (ADR 0024,
# "why truncation, not rejection"). Lowered from 1200 to 700 in Gate 19.1 (ADR 0026, "why answers
# are shorter") after the first live answer ran to 472 OUTPUT TOKENS of technical, over-long prose -
# 700 characters is roughly 2-3 short Italian paragraphs, matched to the strengthened system
# instructions' own brevity rules, never a token estimator added to this business-layer constant.
MAX_ANSWER_CHARS = 700

ASK_NINFA_INSTRUCTIONS_VERSION = "ask-ninfa-v1.1"


class AskStatus(StrEnum):
    """The SERVICE's own final result status - distinct from the model's own
    `ModelAnswerStatus` (`app.modules.ai.gateway.protocol`), which only ever contributes
    `ANSWERED`/`INSUFFICIENT_CONTEXT`.

    `ANSWERED`: a grounded answer exists. `INSUFFICIENT_CONTEXT`: the model itself determined the
    question needs data/computation NINFA's context does not provide (e.g. an exact price change) -
    domain-relevant, but not fabricable. `UNAVAILABLE`: the provider is not configured, timed out,
    errored, or returned output that failed validation - always fails closed, never a guess.
    `REFUSED`: the question itself is out of Ask NINFA's bounds (an execution request, a raw PII
    request, a clear prompt-injection attempt) - decided BEFORE any provider call, by a
    deterministic guardrail, never a second LLM call.
    """

    ANSWERED = "ANSWERED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    UNAVAILABLE = "UNAVAILABLE"
    REFUSED = "REFUSED"


class GroundingRef(StrEnum):
    """A closed, semantic vocabulary of WHICH part of `AskDecisionContext` an answer drew on -
    never a database id, a row number or a citation index. An answer can name several."""

    DECISION_STATUS = "DECISION_STATUS"
    LATEST_FACTS = "LATEST_FACTS"
    LATEST_EVIDENCE = "LATEST_EVIDENCE"
    RECOMMENDATION = "RECOMMENDATION"
    HISTORY = "HISTORY"


ContextValue = str | int | bool


@dataclass(frozen=True, slots=True)
class AskDataPoint:
    """One semantically-labeled, model-facing number or short fact - NEVER a raw internal
    `facts_payload`/`evidence_payload` key (see Gate 19.1, ADR 0026, "why model context is
    semantic"). `label` is a hand-picked Italian phrase
    (`app.modules.ai.ask_ninfa.semantic_labels`), reusing the SAME wording the real product UI
    already ships (Gate 15's `decision-card.tsx`)
    wherever one already exists, so a user reads the same term in the UI and in an Ask NINFA
    answer. `value` preserves the EXACT underlying string/Decimal-text/int/boolean-word verbatim -
    only ever RELABELED, never reformatted, rounded, or recomputed. `unit` is a short, optional
    Italian unit word (`"camere"`, `"ore"`, `"%"`, ...), never a raw column/currency-code suffix
    glued onto the number."""

    label: str
    value: str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class AskObservationContext:
    """One Observation's model-facing shape - deliberately narrower than the public
    `ObservationDetail` API DTO (Gate 12): no `observation_id`, no
    `source_evaluation_fingerprint`/`source_target_key` (audit-only technical identifiers a model
    has no semantic use for), no raw `priority_score`/`impact_score`/`urgency_score`/
    `actionability_score` (Gate 10's own internal scoring components stay internal).

    Gate 19.1 additionally removed `reason_codes` (machine-level detector vocabulary - the facts
    below already represent the phenomenon a reason code would otherwise name, see ADR 0026, "why
    raw reason codes are omitted") and `priority_rank` (V1 preference: never verbalise a bare rank
    number - see ADR 0026, "why priority is not verbalised"). `status_label` replaces the raw
    `source_status`/`lifecycle_transition` StrEnum pair with ONE already-Italian phrase (the SAME
    vocabulary the Decision Detail UI's own `lifecycleEventCopy` already ships)."""

    as_of_local_date: str
    status_label: str
    # `confidence_score` is NOT NULL on `DecisionObservation` (unlike the Recommendation's own
    # defensively-Optional `confidence`, kept elsewhere) - always a real, exact 0-100 string,
    # never divided/multiplied (see the `fix/frontend-confidence-display` scale convention, which
    # applies identically to any consumer of this same value).
    confidence: str
    facts: tuple[AskDataPoint, ...]
    evidence: tuple[AskDataPoint, ...]


@dataclass(frozen=True, slots=True)
class AskActionContext:
    """One Recommendation action's model-facing shape. Gate 19.1: `action_code`/`category` (raw
    `ActionCode`/`ActionCategory` StrEnum values) are replaced by `title`/`description` - the SAME
    Italian copy the Recommendation UI already ships (`apps/web/lib/recommendations/copy.ts`,
    mirrored in Python by `semantic_labels.py` so the two never drift), never a code a model could
    quote verbatim. `description` is `None` for a supporting check - Gate 17's own copy gives those
    only a single short label, never a separate description, so this mirrors that shape exactly
    rather than inventing a second sentence the real UI does not have either. `risk_notes` are
    already-mapped Italian sentences, never raw `RiskNote` codes."""

    title: str
    description: str | None
    risk_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AskRecommendationContext:
    """Gate 19.1 dropped `status` (the raw `AVAILABLE`/`NOT_AVAILABLE`/`INSUFFICIENT_CONTEXT`
    `RecommendationStatus` enum) and `requires_human_review` (always `True` by construction - an
    invariant the system instructions already state, never a boolean a model could parrot back).
    Whether anything is available to evaluate is already fully conveyed by `primary_action` being
    `None` or not."""

    primary_action: AskActionContext | None
    supporting_checks: tuple[AskActionContext, ...]


@dataclass(frozen=True, slots=True)
class AskDecisionContext:
    """The ENTIRE grounding boundary: this, and nothing else, is what a language model provider
    ever sees about a Decision. No `decision_id` (never semantically necessary in the prompt - see
    ADR 0024, "why context is explicitly whitelisted"), no workspace/property id, no internal
    `*_data_source_id` UUID, no fingerprint, no session/auth data.

    Gate 19.1: `decision_label` replaces the raw `decision_type` `PriorityDecisionType` value with
    an already-Italian title (the SAME wording `apps/web/lib/copy.ts`'s `decisionTypeTitles`
    already ships); `decision_status` is now the already-Italian "Aperta"/"Risolta" phrase, not the
    raw `OPEN`/`RESOLVED` enum. See `semantic_labels.py` for every mapping and ADR 0026 for the
    "why" behind removing raw engine vocabulary from this boundary entirely, structurally, rather
    than relying on the system prompt alone to avoid repeating it.

    `history` is chronological (oldest -> newest, at most `MAX_HISTORY_OBSERVATIONS`) and includes
    the latest observation as its own final entry, intentionally - the same current observation is
    also given standalone as `latest`, so the model can focus on "what is happening now" without
    losing the ability to compare it against earlier entries in one place.
    """

    decision_label: str
    decision_status: str
    first_seen_local_date: str
    last_seen_local_date: str
    last_evaluated_local_date: str
    resolved_local_date: str | None
    episode_count: int
    target: dict[str, str]
    latest: AskObservationContext
    recommendation: AskRecommendationContext
    history: tuple[AskObservationContext, ...]


@dataclass(frozen=True, slots=True)
class AskResult:
    """`AskNinfaService`'s one typed output - the API route maps this, field for field, onto the
    public `AskResponse`. `answer`/`limitations` are `None`/`()` whenever `status` is not
    `ANSWERED`/`INSUFFICIENT_CONTEXT` with a real model response (`UNAVAILABLE`/`REFUSED` carry no
    model output at all - nothing was ever generated to report)."""

    status: AskStatus
    answer: str | None
    grounding_refs: tuple[GroundingRef, ...]
    limitations: tuple[str, ...]


__all__ = [
    "ASK_NINFA_INSTRUCTIONS_VERSION",
    "MAX_ANSWER_CHARS",
    "MAX_HISTORY_OBSERVATIONS",
    "MAX_QUESTION_LENGTH",
    "MIN_QUESTION_LENGTH",
    "AskActionContext",
    "AskDataPoint",
    "AskDecisionContext",
    "AskObservationContext",
    "AskRecommendationContext",
    "AskResult",
    "AskStatus",
    "ContextValue",
    "GroundingRef",
]

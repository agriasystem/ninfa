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
# "why truncation, not rejection").
MAX_ANSWER_CHARS = 1200

ASK_NINFA_INSTRUCTIONS_VERSION = "ask-ninfa-v1"


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
class AskObservationContext:
    """One Observation's model-facing shape - deliberately narrower than the public
    `ObservationDetail` API DTO (Gate 12): no `observation_id`, no
    `source_evaluation_fingerprint`/`source_target_key` (audit-only technical identifiers a model
    has no semantic use for), no raw `priority_score`/`impact_score`/`urgency_score`/
    `actionability_score` (Gate 10's own internal scoring components stay internal - only the
    RANK, when one exists, is a fact worth explaining)."""

    as_of_local_date: str
    source_status: str
    lifecycle_transition: str
    reason_codes: tuple[str, ...]
    # `confidence_score` is NOT NULL on `DecisionObservation` (unlike the Recommendation's own
    # defensively-Optional `confidence`, kept elsewhere) - always a real, exact 0-100 string,
    # never divided/multiplied (see the `fix/frontend-confidence-display` scale convention, which
    # applies identically to any consumer of this same value).
    confidence: str
    priority_rank: int | None
    facts: dict[str, ContextValue]
    evidence: dict[str, ContextValue]


@dataclass(frozen=True, slots=True)
class AskActionContext:
    """One Recommendation action's model-facing shape - `action_code`/`category` only (never
    `title_key`/`description_key`/`scope`, which a model does not need to explain WHY a check
    matters) plus its own risk notes."""

    action_code: str
    category: str
    risk_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AskRecommendationContext:
    status: str
    primary_action: AskActionContext | None
    supporting_checks: tuple[AskActionContext, ...]
    requires_human_review: bool


@dataclass(frozen=True, slots=True)
class AskDecisionContext:
    """The ENTIRE grounding boundary: this, and nothing else, is what a language model provider
    ever sees about a Decision. No `decision_id` (never semantically necessary in the prompt - see
    ADR 0024, "why context is explicitly whitelisted"), no workspace/property id, no internal
    `*_data_source_id` UUID, no fingerprint, no session/auth data.

    `history` is chronological (oldest -> newest, at most `MAX_HISTORY_OBSERVATIONS`) and includes
    the latest observation as its own final entry, intentionally - the same current observation is
    also given standalone as `latest`, so the model can focus on "what is happening now" without
    losing the ability to compare it against earlier entries in one place.
    """

    decision_type: str
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
    "AskDecisionContext",
    "AskObservationContext",
    "AskRecommendationContext",
    "AskResult",
    "AskStatus",
    "ContextValue",
    "GroundingRef",
]

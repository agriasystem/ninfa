"""Decision API V1 response DTOs.

Every Decimal that decided something (a score, a proxy amount) is a canonical STRING, never a
float: JavaScript's `Number` cannot carry arbitrary Decimal precision, and Gate 11's own priority
scores can legitimately run to many significant digits (see
`app/modules/intelligence/priority/precision.py`'s 50-digit context). `identity_payload` is never
returned raw: `target` is one of four explicit, decision_type-discriminated DTOs built by
`serializers.py`, never a passthrough of the stored JSON.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.decision_memory.types import DECISION_API_VERSION

# --- shared value objects -------------------------------------------------------------------


class PrioritySnapshot(BaseModel):
    """The ONE PriorityCandidate Gate 10 produced for this Observation, copied - never
    recomputed. Present only when the Observation's own `source_status` was TRIGGERED."""

    rank: int
    impact_score: str
    urgency_score: str
    confidence_score: str
    actionability_score: str
    priority_score: str
    candidate_fingerprint: str


class EconomicProxy(BaseModel):
    """A gross, non-comparable economic proxy in its OWN currency - never converted, never
    compared across currencies. Omitted entirely (not zeroed) when the detector recorded no
    currency for its proxy (Revenue/OTA: see docs/architecture/decision-api-v1.md, "Economic
    proxy")."""

    label: str
    amount: str
    currency: str


# --- target DTOs, discriminated by decision_type ------------------------------------------


class RevenueDecisionTarget(BaseModel):
    type: Literal["REV_PICKUP_LOW", "REV_OCCUPANCY_RISK"]
    booking_data_source_id: UUID
    stay_date: date


class OtaDecisionTarget(BaseModel):
    type: Literal["REV_OTA_DEPENDENCY"] = "REV_OTA_DEPENDENCY"
    booking_data_source_id: UUID


class CostDecisionTarget(BaseModel):
    type: Literal["COST_CPOR_ANOMALY"] = "COST_CPOR_ANOMALY"
    booking_data_source_id: UUID
    target_period_start: date
    cost_category: str
    currency: str


class LaborDecisionTarget(BaseModel):
    type: Literal["LABOR_OVERSTAFFING"] = "LABOR_OVERSTAFFING"
    booking_data_source_id: UUID
    labor_data_source_id: UUID
    work_date: date
    labor_category: str


DecisionTarget = Annotated[
    RevenueDecisionTarget | OtaDecisionTarget | CostDecisionTarget | LaborDecisionTarget,
    Field(discriminator="type"),
]

# --- observation-shaped payloads (feed item, detail's latest observation, history item) -----


class ObservationDetail(BaseModel):
    """The full audit shape of one Observation: shared verbatim by Decision Detail's own
    `latest_observation` and by every Decision History item - the two never diverge, on purpose
    (see ADR 0018, "why one observation DTO")."""

    observation_id: UUID
    as_of_local_date: date
    source_status: str
    lifecycle_transition: str
    source_evaluation_fingerprint: str
    source_target_key: str
    reason_codes: list[str]
    confidence_score: str
    priority: PrioritySnapshot | None
    facts: dict[str, Any]
    evidence: dict[str, Any]
    economic_proxy: EconomicProxy | None
    memory_version: str


# --- endpoint 1: decision feed ---------------------------------------------------------------


class DomainCoverageResponse(BaseModel):
    """One of the four user-facing analysis domains (Gate 22) and whether THIS run attempted it -
    never what it found: a domain is EVALUATED whichever status its detectors returned, CLEAR
    through TRIGGERED. `reason` is populated only for `status = "SKIPPED"`."""

    domain: Literal["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"]
    status: Literal["EVALUATED", "SKIPPED"]
    reason: Literal["NOT_REQUESTED"] | None = None


class AnalysisCoverageResponse(BaseModel):
    """`summary` is ALWAYS present and never crashes a client: `"UNKNOWN"` with an empty
    `domains` list means this run predates Gate 22 (`DecisionRun.analysis_coverage IS NULL`) or
    no run exists yet - never inferred as `"FULL"` or `"PARTIAL"`, on purpose (see
    `app.modules.decisions.coverage`'s own module docstring)."""

    summary: Literal["FULL", "PARTIAL", "UNKNOWN"]
    domains: list[DomainCoverageResponse]


class BookingFreshnessResponse(BaseModel):
    """Gate 23B: a FACT, never a judgement - `status = "KNOWN"` only states that a SUCCEEDED
    booking import was known at analysis time, and WHEN it finished; it never claims that import
    was "the" source of this run's numbers (canonical booking state is cumulative/upserted - see
    `app.modules.decisions.provenance`'s own module docstring) and never implies CURRENT/STALE
    (no freshness threshold exists in V1). Deliberately omits the internal `ImportJob`/
    `DataSource` UUIDs - no frontend need for them exists yet."""

    status: Literal["KNOWN", "UNKNOWN"]
    last_successful_import_finished_at: datetime | None = None


class InputFreshnessResponse(BaseModel):
    """`bookings` is the only key in V1 (Gate 23B's own P0 scope) - no cost/labor freshness
    exists yet. Always present and never null, exactly like `AnalysisCoverageResponse` above:
    `UNKNOWN` covers both "no run yet" and a run that predates this gate."""

    bookings: BookingFreshnessResponse


class LastSuccessfulAnalysisResponse(BaseModel):
    """Gate 24B: populated ONLY when `feed_state == "NOT_PROCESSED"` and a prior run exists for
    this property on some OTHER as-of date - `null` for every processed feed state and `null`
    when the property has never been analysed at all (never inferred, never fabricated).
    `as_of_local_date` is the BUSINESS date that run represents; `completed_at` is when NINFA
    actually finished/persisted it (`DecisionRun.created_at`) - two distinct facts, kept
    separate on purpose (see `app.modules.decision_memory.types.LastSuccessfulAnalysis`'s own
    docstring). Deliberately omits the run's id and `run_sequence` - no frontend need for them
    exists, exactly like `AnalysisCoverageResponse`/`InputFreshnessResponse` above."""

    as_of_local_date: date
    completed_at: datetime


class FeedItemResponse(BaseModel):
    decision_id: UUID
    decision_type: str
    lifecycle_status: str
    transition: str
    priority: PrioritySnapshot
    first_seen_local_date: date
    last_seen_local_date: date
    episode_count: int
    target: DecisionTarget
    reason_codes: list[str]
    facts: dict[str, Any]
    evidence: dict[str, Any]
    economic_proxy: EconomicProxy | None
    source_status: str


class DecisionFeedResponse(BaseModel):
    property_id: UUID
    as_of_local_date: date
    feed_state: str
    decision_run_id: UUID | None
    run_sequence: int | None
    triggered_count: int | None
    clear_count: int | None
    insufficient_count: int | None
    not_applicable_count: int | None
    suppressed_count: int | None
    analysis_coverage: AnalysisCoverageResponse
    input_freshness: InputFreshnessResponse
    last_successful_analysis: LastSuccessfulAnalysisResponse | None
    items: list[FeedItemResponse]


# --- endpoint 2: decision list -----------------------------------------------------------------


class LatestObservationSummary(BaseModel):
    as_of_local_date: date
    source_status: str
    transition: str
    confidence_score: str
    priority_rank: int | None
    priority_score: str | None
    reason_codes: list[str]


class DecisionListItem(BaseModel):
    decision_id: UUID
    decision_type: str
    status: str
    first_seen_local_date: date
    last_seen_local_date: date
    last_evaluated_local_date: date
    resolved_local_date: date | None
    episode_count: int
    triggered_observation_count: int
    target: DecisionTarget
    latest_observation_summary: LatestObservationSummary


class DecisionListResponse(BaseModel):
    items: list[DecisionListItem]
    next_cursor: str | None


# --- endpoint 3: decision detail ---------------------------------------------------------------


class RecommendedActionResponse(BaseModel):
    """One structured action (Gate 16) - `title_key`/`description_key` are deterministic template
    keys, never generated prose; a future copy/UI layer maps them to human language. See
    docs/architecture/recommendation-engine-v1.md, "Action model"."""

    action_code: str
    title_key: str
    description_key: str
    category: str
    scope: str
    supporting_facts: dict[str, str]
    risk_notes: list[str]
    requires_human_review: bool


class RecommendationResponse(BaseModel):
    """Gate 16, additive to Decision Detail: NEVER null (the engine always returns a typed
    result) - `status` itself is what tells a client whether a real recommendation exists right
    now. Deliberately omits `generated_from_observation_id`/`generated_from_evaluation_fingerprint`/
    `reason_codes` (internal engine bookkeeping, not part of the public contract - see "No detail
    data leak")."""

    status: str
    version: str
    fingerprint: str
    primary_action: RecommendedActionResponse | None
    supporting_checks: list[RecommendedActionResponse]
    confidence: str | None
    requires_human_review: bool = True


class DecisionDetailResponse(BaseModel):
    decision_id: UUID
    decision_type: str
    status: str
    first_seen_local_date: date
    last_seen_local_date: date
    last_evaluated_local_date: date
    resolved_local_date: date | None
    episode_count: int
    triggered_observation_count: int
    target: DecisionTarget
    latest_observation: ObservationDetail
    recommendation: RecommendationResponse
    decision_api_version: str = DECISION_API_VERSION


# --- endpoint 4: decision history --------------------------------------------------------------


class DecisionHistoryResponse(BaseModel):
    items: list[ObservationDetail]
    next_cursor: str | None


# --- endpoint 5: ask NINFA (Gate 18) ------------------------------------------------------------


class AskRequest(BaseModel):
    """`question` is validated again by `app.modules.ai.ask_ninfa.question.validate_question`
    (length/whitespace) - this `str` type annotation alone does not enforce the `[1, 1000]` bound,
    that check happens explicitly in the route, never assumed from Pydantic's own defaults."""

    question: str


class AskHomeRequest(BaseModel):
    """Mia Home (property-level Ask): the question AND the explicit business date of the feed it is
    about - the SAME property-local `YYYY-MM-DD` the Decision Feed endpoint requires, never a server
    clock. Both are validated explicitly in the route (`question` length, `as_of_local_date` ISO
    parse), never assumed from the type annotation alone."""

    question: str
    as_of_local_date: str


class AskResponse(BaseModel):
    """`status` is one of `AskStatus`'s four values (Gate 18). No chat id, no thread id, no
    conversation id anywhere - V1 is one question, one answer, nothing persisted. `answer`/
    `limitations` carry real content only for `ANSWERED`/`INSUFFICIENT_CONTEXT`; `UNAVAILABLE`/
    `REFUSED` carry `answer: null` (a `REFUSED`'s explanation, if any, lives in `limitations`)."""

    status: str
    answer: str | None
    grounding_refs: list[str]
    limitations: list[str]


__all__ = [
    "AnalysisCoverageResponse",
    "AskHomeRequest",
    "AskRequest",
    "AskResponse",
    "BookingFreshnessResponse",
    "CostDecisionTarget",
    "DecisionDetailResponse",
    "DecisionFeedResponse",
    "DecisionHistoryResponse",
    "DecisionListItem",
    "DecisionListResponse",
    "DecisionTarget",
    "DomainCoverageResponse",
    "EconomicProxy",
    "FeedItemResponse",
    "InputFreshnessResponse",
    "LaborDecisionTarget",
    "LastSuccessfulAnalysisResponse",
    "LatestObservationSummary",
    "ObservationDetail",
    "OtaDecisionTarget",
    "PrioritySnapshot",
    "RecommendationResponse",
    "RecommendedActionResponse",
    "RevenueDecisionTarget",
]

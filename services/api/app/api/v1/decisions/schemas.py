"""Decision API V1 response DTOs.

Every Decimal that decided something (a score, a proxy amount) is a canonical STRING, never a
float: JavaScript's `Number` cannot carry arbitrary Decimal precision, and Gate 11's own priority
scores can legitimately run to many significant digits (see
`app/modules/intelligence/priority/precision.py`'s 50-digit context). `identity_payload` is never
returned raw: `target` is one of four explicit, decision_type-discriminated DTOs built by
`serializers.py`, never a passthrough of the stored JSON.
"""

from datetime import date
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
    decision_api_version: str = DECISION_API_VERSION


# --- endpoint 4: decision history --------------------------------------------------------------


class DecisionHistoryResponse(BaseModel):
    items: list[ObservationDetail]
    next_cursor: str | None


__all__ = [
    "CostDecisionTarget",
    "DecisionDetailResponse",
    "DecisionFeedResponse",
    "DecisionHistoryResponse",
    "DecisionListItem",
    "DecisionListResponse",
    "DecisionTarget",
    "EconomicProxy",
    "FeedItemResponse",
    "LaborDecisionTarget",
    "LatestObservationSummary",
    "ObservationDetail",
    "OtaDecisionTarget",
    "PrioritySnapshot",
    "RevenueDecisionTarget",
]

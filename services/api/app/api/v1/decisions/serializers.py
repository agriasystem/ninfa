"""Decision API V1 serializers: ORM rows -> response DTOs.

`facts_of`/`evidence_of` are the WHITELIST this gate's contract requires: Gate 11's own
`facts_payload`/`evidence_payload` are already minimized, but this module never trusts that as its
OWN boundary - only the keys explicitly listed below (audited against the real
`app/modules/decisions/serialization.py`, one whitelist per `decision_type`) ever leave this API.
`observation.facts_payload`/`.evidence_payload` are NEVER returned as-is.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from app.api.v1.decisions.schemas import (
    CostDecisionTarget,
    DecisionDetailResponse,
    DecisionListItem,
    DecisionTarget,
    EconomicProxy,
    FeedItemResponse,
    LaborDecisionTarget,
    LatestObservationSummary,
    ObservationDetail,
    OtaDecisionTarget,
    PrioritySnapshot,
    RevenueDecisionTarget,
)
from app.modules.decision_memory.types import FeedItem
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.precision import canonical_text
from app.modules.intelligence.priority.types import PriorityDecisionType

# Audited, by hand, against `app/modules/decisions/serialization.py`'s own `serialize_*`
# functions: exactly the keys each one writes into `facts_payload`, never more.
_FACTS_WHITELIST: dict[PriorityDecisionType, frozenset[str]] = {
    PriorityDecisionType.REV_PICKUP_LOW: frozenset(
        {
            "stay_date",
            "lead_time_days",
            "current_rooms_on_books",
            "rooms_available",
            "kind",
            "window_days",
            "prior_rooms_on_books",
            "actual_pickup",
            "expected_pickup",
            "delta_rooms",
            "missing_rooms",
            "delta_percent_exact",
            "percent_condition",
            "rooms_condition",
        }
    ),
    PriorityDecisionType.REV_OCCUPANCY_RISK: frozenset(
        {
            "stay_date",
            "lead_time_days",
            "current_rooms_on_books",
            "rooms_available",
            "kind",
            "forecast_rooms",
            "expected_final_rooms",
            "occupancy_gap_pp_exact",
            "room_shortfall",
            "gap_condition",
            "shortfall_condition",
        }
    ),
    PriorityDecisionType.REV_OTA_DEPENDENCY: frozenset(
        {
            "window_start",
            "window_end",
            "window_days",
            "ota_room_nights",
            "direct_room_nights",
            "ota_share_exact",
            "expected_ota_share_exact",
            "delta_pp_exact",
            "upper_fence_exact",
            "structural_condition",
            "rising_condition",
        }
    ),
    PriorityDecisionType.COST_CPOR_ANOMALY: frozenset(
        {
            "target_period_start",
            "target_period_end",
            "cost_category",
            "currency",
            "actual_cpor_exact",
            "expected_cpor_exact",
            "delta_cpor_exact",
            "delta_percent_exact",
            "upper_fence_exact",
            "cost_gap_proxy_exact",
        }
    ),
    PriorityDecisionType.LABOR_OVERSTAFFING: frozenset(
        {
            "work_date",
            "labor_category",
            "forecast_rooms_exact",
            "scheduled_hours_exact",
            "expected_labor_hours_exact",
            "excess_hours_exact",
            "delta_percent_exact",
            "upper_fence_hours_exact",
        }
    ),
}

_REVENUE_EVIDENCE = frozenset(
    {
        "booking_data_source_id",
        "baseline_confidence",
        "pattern_confidence",
        "pattern_pair_count",
        "confidence_score",
        "revenue_gap_proxy",
        "reference_adr",
        "reference_adr_source",
        "rules_version",
    }
)

_EVIDENCE_WHITELIST: dict[PriorityDecisionType, frozenset[str]] = {
    PriorityDecisionType.REV_PICKUP_LOW: _REVENUE_EVIDENCE,
    PriorityDecisionType.REV_OCCUPANCY_RISK: _REVENUE_EVIDENCE,
    PriorityDecisionType.REV_OTA_DEPENDENCY: frozenset(
        {
            "booking_data_source_id",
            "classification_coverage_pct_exact",
            "observed_day_count",
            "reconstructed_day_count",
            "sample_count",
            "baseline_confidence",
            "confidence_score",
            "ota_room_revenue_exposure",
            "rules_version",
        }
    ),
    PriorityDecisionType.COST_CPOR_ANOMALY: frozenset(
        {
            "booking_data_source_id",
            "classification_coverage_pct_exact",
            "occupancy_provenance_score_exact",
            "sample_count",
            "observed_period_count",
            "baseline_confidence",
            "confidence_score",
            "rules_version",
        }
    ),
    PriorityDecisionType.LABOR_OVERSTAFFING: frozenset(
        {
            "booking_data_source_id",
            "labor_data_source_id",
            "classification_coverage_pct_exact",
            "demand_confidence",
            "target_plan_quality",
            "sample_count",
            "fully_observed_count",
            "confidence_score",
            "labor_cost_gap_proxy_exact",
            "cost_currency",
            "rules_version",
        }
    ),
}


def _optional_text(value: Decimal | None) -> str | None:
    return None if value is None else canonical_text(value)


def facts_of(decision_type: PriorityDecisionType, facts_payload: dict[str, Any]) -> dict[str, Any]:
    allowed = _FACTS_WHITELIST[decision_type]
    return {key: value for key, value in facts_payload.items() if key in allowed}


def evidence_of(
    decision_type: PriorityDecisionType, evidence_payload: dict[str, Any]
) -> dict[str, Any]:
    allowed = _EVIDENCE_WHITELIST[decision_type]
    return {key: value for key, value in evidence_payload.items() if key in allowed}


def _str(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    assert isinstance(value, str)
    return value


def target_of(decision: Decision) -> DecisionTarget:
    """Explicit fields read out of the real, audited `identity_payload` keys (see
    `test_decision_identity.py`'s own per-detector tests in Gate 11) - never the raw JSON."""
    payload = decision.identity_payload
    decision_type = decision.decision_type
    if decision_type is PriorityDecisionType.REV_PICKUP_LOW:
        return RevenueDecisionTarget(
            type="REV_PICKUP_LOW",
            booking_data_source_id=UUID(_str(payload, "booking_data_source_id")),
            stay_date=_str(payload, "stay_date"),
        )
    if decision_type is PriorityDecisionType.REV_OCCUPANCY_RISK:
        return RevenueDecisionTarget(
            type="REV_OCCUPANCY_RISK",
            booking_data_source_id=UUID(_str(payload, "booking_data_source_id")),
            stay_date=_str(payload, "stay_date"),
        )
    if decision_type is PriorityDecisionType.REV_OTA_DEPENDENCY:
        return OtaDecisionTarget(
            booking_data_source_id=UUID(_str(payload, "booking_data_source_id"))
        )
    if decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
        return CostDecisionTarget(
            booking_data_source_id=UUID(_str(payload, "booking_data_source_id")),
            target_period_start=_str(payload, "target_period_start"),
            cost_category=_str(payload, "cost_category"),
            currency=_str(payload, "currency"),
        )
    if decision_type is PriorityDecisionType.LABOR_OVERSTAFFING:
        return LaborDecisionTarget(
            booking_data_source_id=UUID(_str(payload, "booking_data_source_id")),
            labor_data_source_id=UUID(_str(payload, "labor_data_source_id")),
            work_date=_str(payload, "work_date"),
            labor_category=_str(payload, "labor_category"),
        )
    raise ValueError(f"unrecognised decision_type {decision_type!r}")  # pragma: no cover


def priority_snapshot_of(observation: DecisionObservation) -> PrioritySnapshot | None:
    """`None` for every non-TRIGGERED Observation (the DB `CHECK` on `decision_observations`
    guarantees the five priority fields are ALL null together in that case)."""
    if observation.priority_rank is None:
        return None
    assert observation.priority_candidate_fingerprint is not None
    assert observation.impact_score is not None
    assert observation.urgency_score is not None
    assert observation.actionability_score is not None
    assert observation.priority_score is not None
    return PrioritySnapshot(
        rank=observation.priority_rank,
        impact_score=canonical_text(observation.impact_score),
        urgency_score=canonical_text(observation.urgency_score),
        confidence_score=canonical_text(observation.confidence_score),
        actionability_score=canonical_text(observation.actionability_score),
        priority_score=canonical_text(observation.priority_score),
        candidate_fingerprint=observation.priority_candidate_fingerprint,
    )


def economic_proxy_of(
    decision_type: PriorityDecisionType, facts: dict[str, Any], evidence: dict[str, Any]
) -> EconomicProxy | None:
    """Only where a detector recorded a REAL currency alongside its own proxy figure (Cost,
    Labor): Revenue's `revenue_gap_proxy` and OTA's exposure figure carry no currency dimension
    anywhere in Gate 5/9's own evaluation types, so this never invents one for them (see
    `test_decision_memory_privacy.py`'s Gate 11 reflection test for why none exists to invent)."""
    if decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
        amount, currency = facts.get("cost_gap_proxy_exact"), facts.get("currency")
        if amount is None or currency is None:
            return None
        return EconomicProxy(label="cost_gap_proxy", amount=amount, currency=currency)
    if decision_type is PriorityDecisionType.LABOR_OVERSTAFFING:
        amount, currency = evidence.get("labor_cost_gap_proxy_exact"), evidence.get("cost_currency")
        if amount is None or currency is None:
            return None
        return EconomicProxy(label="labor_cost_gap_proxy", amount=amount, currency=currency)
    return None


def observation_detail_of(
    decision_type: PriorityDecisionType, observation: DecisionObservation
) -> ObservationDetail:
    facts = facts_of(decision_type, observation.facts_payload)
    evidence = evidence_of(decision_type, observation.evidence_payload)
    return ObservationDetail(
        observation_id=observation.id,
        as_of_local_date=observation.as_of_local_date,
        source_status=observation.source_status.value,
        lifecycle_transition=observation.lifecycle_transition.value,
        source_evaluation_fingerprint=observation.source_evaluation_fingerprint,
        source_target_key=observation.source_target_key,
        reason_codes=list(observation.source_reason_codes),
        confidence_score=canonical_text(observation.confidence_score),
        priority=priority_snapshot_of(observation),
        facts=facts,
        evidence=evidence,
        economic_proxy=economic_proxy_of(decision_type, facts, evidence),
        memory_version=observation.memory_version,
    )


def feed_item_of(item: FeedItem) -> FeedItemResponse:
    decision, observation = item.decision, item.observation
    facts = facts_of(decision.decision_type, observation.facts_payload)
    evidence = evidence_of(decision.decision_type, observation.evidence_payload)
    priority = priority_snapshot_of(observation)
    assert priority is not None  # `feed_rows()` only ever selects TRIGGERED observations
    return FeedItemResponse(
        decision_id=decision.id,
        decision_type=decision.decision_type.value,
        lifecycle_status=decision.status.value,
        transition=observation.lifecycle_transition.value,
        priority=priority,
        first_seen_local_date=decision.first_seen_local_date,
        last_seen_local_date=decision.last_seen_local_date,
        episode_count=decision.episode_count,
        target=target_of(decision),
        reason_codes=list(observation.source_reason_codes),
        facts=facts,
        evidence=evidence,
        economic_proxy=economic_proxy_of(decision.decision_type, facts, evidence),
        source_status=observation.source_status.value,
    )


def latest_observation_summary_of(observation: DecisionObservation) -> LatestObservationSummary:
    return LatestObservationSummary(
        as_of_local_date=observation.as_of_local_date,
        source_status=observation.source_status.value,
        transition=observation.lifecycle_transition.value,
        confidence_score=canonical_text(observation.confidence_score),
        priority_rank=observation.priority_rank,
        priority_score=_optional_text(observation.priority_score),
        reason_codes=list(observation.source_reason_codes),
    )


def decision_list_item_of(
    decision: Decision, latest_observation: DecisionObservation
) -> DecisionListItem:
    return DecisionListItem(
        decision_id=decision.id,
        decision_type=decision.decision_type.value,
        status=decision.status.value,
        first_seen_local_date=decision.first_seen_local_date,
        last_seen_local_date=decision.last_seen_local_date,
        last_evaluated_local_date=decision.last_evaluated_local_date,
        resolved_local_date=decision.resolved_local_date,
        episode_count=decision.episode_count,
        triggered_observation_count=decision.triggered_observation_count,
        target=target_of(decision),
        latest_observation_summary=latest_observation_summary_of(latest_observation),
    )


def decision_detail_of(
    decision: Decision, latest_observation: DecisionObservation
) -> DecisionDetailResponse:
    return DecisionDetailResponse(
        decision_id=decision.id,
        decision_type=decision.decision_type.value,
        status=decision.status.value,
        first_seen_local_date=decision.first_seen_local_date,
        last_seen_local_date=decision.last_seen_local_date,
        last_evaluated_local_date=decision.last_evaluated_local_date,
        resolved_local_date=decision.resolved_local_date,
        episode_count=decision.episode_count,
        triggered_observation_count=decision.triggered_observation_count,
        target=target_of(decision),
        latest_observation=observation_detail_of(decision.decision_type, latest_observation),
    )


__all__ = [
    "decision_detail_of",
    "decision_list_item_of",
    "economic_proxy_of",
    "evidence_of",
    "facts_of",
    "feed_item_of",
    "latest_observation_summary_of",
    "observation_detail_of",
    "priority_snapshot_of",
    "target_of",
]

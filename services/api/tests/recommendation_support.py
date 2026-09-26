"""Shared helpers for the Gate 16 (Recommendation Engine V1) tests.

PURE builders of minimal-but-valid `Decision`/`DecisionObservation` ORM instances - plain Python
objects, never added to a session, never persisted. `RecommendationEngine.evaluate()` takes
exactly these two objects and reads only their column attributes, so building them by hand (never
through `DecisionService.sync()`) is enough to exercise every branch of the engine without a
database at all.

The GOLDEN scenario (`test_recommendation_golden.py`) is entirely separate and never uses these
builders: it drives the real pipeline (detectors -> `PriorityService` -> `DecisionService.sync()`)
end to end, exactly like every other gate's own golden suite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.types import DecisionStatus, LifecycleTransition, SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

DEFAULT_AS_OF = date(2026, 9, 26)

# Real, audited-whitelist facts payloads (one per decision_type) that satisfy every rule's own
# minimal fact requirement - see `app/modules/recommendations/rules.py`. A test that wants
# INSUFFICIENT_CONTEXT starts from one of these and deletes/corrupts a key, never invents a new
# shape of its own.
VALID_FACTS: dict[PriorityDecisionType, dict[str, Any]] = {
    PriorityDecisionType.REV_PICKUP_LOW: {
        "stay_date": "2026-10-01",
        "lead_time_days": 9,
        "current_rooms_on_books": 12,
        "rooms_available": 40,
        "kind": "PICKUP",
        "window_days": 7,
        "prior_rooms_on_books": 9,
        "actual_pickup": 3,
        "expected_pickup": "7.50",
        "delta_rooms": "-4.50",
        "missing_rooms": "4.50",
        "delta_percent_exact": "-60.00",
        "percent_condition": True,
        "rooms_condition": True,
    },
    PriorityDecisionType.REV_OCCUPANCY_RISK: {
        "stay_date": "2026-10-12",
        "lead_time_days": 16,
        "current_rooms_on_books": 18,
        "rooms_available": 40,
        "kind": "OCCUPANCY",
        "forecast_rooms": "22.00",
        "expected_final_rooms": "34.00",
        "occupancy_gap_pp_exact": "30.00",
        "room_shortfall": "12.00",
        "gap_condition": True,
        "shortfall_condition": True,
    },
    PriorityDecisionType.REV_OTA_DEPENDENCY: {
        "window_start": "2026-08-01",
        "window_end": "2026-09-25",
        "window_days": 56,
        "ota_room_nights": 140,
        "direct_room_nights": 84,
        "ota_share_exact": "62.50",
        "expected_ota_share_exact": "45.00",
        "delta_pp_exact": "17.50",
        "upper_fence_exact": "58.00",
        "structural_condition": True,
        "rising_condition": False,
    },
    PriorityDecisionType.COST_CPOR_ANOMALY: {
        "target_period_start": "2026-09-01",
        "target_period_end": "2026-09-30",
        "cost_category": "FOOD_AND_BEVERAGE",
        "currency": "EUR",
        "actual_cpor_exact": "12.40",
        "expected_cpor_exact": "9.00",
        "delta_cpor_exact": "3.40",
        "delta_percent_exact": "37.78",
        "upper_fence_exact": "11.00",
        "cost_gap_proxy_exact": "482.30",
    },
    PriorityDecisionType.LABOR_OVERSTAFFING: {
        "work_date": "2026-09-25",
        "labor_category": "HOUSEKEEPING",
        "forecast_rooms_exact": "24.00",
        "scheduled_hours_exact": "40.00",
        "expected_labor_hours_exact": "28.00",
        "excess_hours_exact": "12.00",
        "delta_percent_exact": "42.86",
        "upper_fence_hours_exact": "32.00",
    },
}

_REASON_CODE_BY_TYPE: dict[PriorityDecisionType, str] = {
    PriorityDecisionType.REV_PICKUP_LOW: "TRIGGER_PICKUP_SHORTFALL",
    PriorityDecisionType.REV_OCCUPANCY_RISK: "TRIGGER_OCCUPANCY_GAP",
    PriorityDecisionType.REV_OTA_DEPENDENCY: "TRIGGER_STRUCTURAL_OTA_DEPENDENCY",
    PriorityDecisionType.COST_CPOR_ANOMALY: "TRIGGER_COST_ANOMALY",
    PriorityDecisionType.LABOR_OVERSTAFFING: "TRIGGER_OVERSTAFFING",
}


def build_decision(
    decision_type: PriorityDecisionType,
    *,
    status: DecisionStatus = DecisionStatus.OPEN,
    episode_count: int = 1,
    identity_key: str | None = None,
    decision_id: UUID | None = None,
) -> Decision:
    """A minimal, valid `Decision` row - never persisted."""
    return Decision(
        id=decision_id or uuid4(),
        workspace_id=uuid4(),
        property_id=uuid4(),
        decision_type=decision_type,
        identity_version="decision-identity-v1",
        identity_key=identity_key or ("a" * 64),
        identity_payload={},
        status=status,
        first_seen_local_date=DEFAULT_AS_OF,
        last_seen_local_date=DEFAULT_AS_OF,
        last_evaluated_local_date=DEFAULT_AS_OF,
        resolved_local_date=None if status is DecisionStatus.OPEN else DEFAULT_AS_OF,
        episode_count=episode_count,
        triggered_observation_count=1,
    )


def build_observation(
    decision: Decision,
    *,
    source_status: SourceStatus = SourceStatus.TRIGGERED,
    lifecycle_transition: LifecycleTransition = LifecycleTransition.OPENED,
    facts_payload: dict[str, Any] | None = None,
    evidence_payload: dict[str, Any] | None = None,
    confidence_score: Decimal | None = Decimal("81.23"),
    priority_rank: int | None = 1,
    source_evaluation_fingerprint: str | None = None,
    reason_codes: list[str] | None = None,
) -> DecisionObservation:
    """A minimal, valid `DecisionObservation` of `decision` - never persisted. Defaults to a real
    TRIGGERED observation whose facts satisfy that decision_type's own rule (see `VALID_FACTS`);
    override `facts_payload={}` (or a corrupted dict) to exercise INSUFFICIENT_CONTEXT."""
    is_triggered = source_status is SourceStatus.TRIGGERED
    facts = VALID_FACTS[decision.decision_type] if facts_payload is None else facts_payload
    default_reason = _REASON_CODE_BY_TYPE[decision.decision_type]
    reasons = reason_codes if reason_codes is not None else [default_reason]
    return DecisionObservation(
        id=uuid4(),
        decision_id=decision.id,
        decision_run_id=uuid4(),
        workspace_id=decision.workspace_id,
        property_id=decision.property_id,
        as_of_local_date=DEFAULT_AS_OF,
        source_status=source_status,
        lifecycle_transition=lifecycle_transition,
        source_evaluation_fingerprint=source_evaluation_fingerprint or ("b" * 64),
        source_target_key="target-key",
        priority_candidate_fingerprint=("c" * 64) if is_triggered else None,
        priority_rank=priority_rank if is_triggered else None,
        impact_score=Decimal("10") if is_triggered else None,
        urgency_score=Decimal("10") if is_triggered else None,
        # The model's own type hint is non-Optional (the DB column is NOT NULL), but a test that
        # wants to prove the engine's OWN defensive handling of a missing confidence must still
        # be able to build a row with `confidence_score=None` - the ORM does not enforce
        # nullability at the Python level, only PostgreSQL's NOT NULL does, and this row is
        # never persisted. Passed through exactly as given, never silently substituted.
        confidence_score=confidence_score,
        actionability_score=Decimal("10") if is_triggered else None,
        priority_score=Decimal("10") if is_triggered else None,
        source_reason_codes=reasons,
        facts_payload=facts,
        evidence_payload=evidence_payload if evidence_payload is not None else {},
        memory_version="decision-memory-v1",
        observation_fingerprint="d" * 64,
    )


__all__ = [
    "DEFAULT_AS_OF",
    "VALID_FACTS",
    "build_decision",
    "build_observation",
]

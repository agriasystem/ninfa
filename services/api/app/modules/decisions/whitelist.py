"""The canonical whitelist of which `facts_payload`/`evidence_payload` keys are safe to expose
OUTSIDE the Decision Layer's own persistence, per `decision_type`.

Gate 11's own `facts_payload`/`evidence_payload` (`app/modules/decisions/serialization.py`) is
already minimized at WRITE time, but nothing that reads it back should trust that as its OWN
boundary. This module is the one, hand-audited whitelist every READER of a persisted Observation's
JSON columns goes through - the Decision API's own serializers
(`app/api/v1/decisions/serializers.py`, Gate 12) and Ask NINFA's context builder
(`app/modules/ai/ask_ninfa/context_builder.py`, Gate 18) both import `facts_of`/`evidence_of` from
here, so there is exactly one whitelist to keep in sync with a detector's own fact shape, never two
that could silently drift apart.
"""

from typing import Any

from app.modules.intelligence.priority.types import PriorityDecisionType

# Audited, by hand, against `app/modules/decisions/serialization.py`'s own `serialize_*`
# functions: exactly the keys each one writes into `facts_payload`, never more.
FACTS_WHITELIST: dict[PriorityDecisionType, frozenset[str]] = {
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

EVIDENCE_WHITELIST: dict[PriorityDecisionType, frozenset[str]] = {
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


def facts_of(decision_type: PriorityDecisionType, facts_payload: dict[str, Any]) -> dict[str, Any]:
    allowed = FACTS_WHITELIST[decision_type]
    return {key: value for key, value in facts_payload.items() if key in allowed}


def evidence_of(
    decision_type: PriorityDecisionType, evidence_payload: dict[str, Any]
) -> dict[str, Any]:
    allowed = EVIDENCE_WHITELIST[decision_type]
    return {key: value for key, value in evidence_payload.items() if key in allowed}


__all__ = ["EVIDENCE_WHITELIST", "FACTS_WHITELIST", "evidence_of", "facts_of"]

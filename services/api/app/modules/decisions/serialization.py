"""Decision Memory serialization (`decision-memory-v1`): EXPLICIT, PER-DETECTOR serializers.

The whole point of this module is what it does NOT do: no `asdict()`, no `dataclasses.asdict`, no
`__dict__`, no blind reuse of a detector's own `payload()`/`canonical_payload()` (those describe
the WHOLE evaluation, evolve with the detector, and were never audited for what a persistent
memory should keep forever). Every field below is named by hand, for one reason: data
minimisation, schema stability independent of a detector's own evolution, and an explicit,
auditable boundary against future PII (guest names/emails/phones, employee identity, tax codes,
addresses, IBANs, medical notes, free-text supplier names never appear here, by construction - see
`test_decision_serialization.py`).

Each serializer returns `(facts_payload, evidence_payload)`:

* `facts_payload` - WHAT the problem is: the target and the numbers the rule compared.
* `evidence_payload` - WHY NINFA trusts it: provenance, sample size, confidence components, the
  optional economic proxy.

Reason codes are not duplicated here: `DecisionObservation.source_reason_codes` is its own column,
read directly off `evaluation.reason_codes` by the caller.
"""

from typing import Any

from app.modules.decisions.precision import canonical_text
from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.revenue.types import (
    OccupancyFacts,
    PickupFacts,
    RevenueDecisionEvaluation,
)

SourceEvaluation = (
    RevenueDecisionEvaluation
    | OtaDependencyEvaluation
    | CostDecisionEvaluation
    | LaborDecisionEvaluation
)

Payload = dict[str, Any]


def _text(value: Any) -> str | None:
    return None if value is None else canonical_text(value)


def reason_codes_of(evaluation: SourceEvaluation) -> tuple[str, ...]:
    """The detector's own stable reason codes, read as they are - never reinterpreted."""
    return tuple(code.value for code in evaluation.reason_codes)


# --- REVENUE (REV_PICKUP_LOW / REV_OCCUPANCY_RISK) -----------------------------------------------


def serialize_revenue(evaluation: RevenueDecisionEvaluation) -> tuple[Payload, Payload]:
    facts_obj = evaluation.facts
    facts: Payload = {
        "stay_date": evaluation.stay_date.isoformat(),
        "lead_time_days": evaluation.lead_time_days,
        "current_rooms_on_books": facts_obj.current_rooms_on_books,
        "rooms_available": facts_obj.rooms_available,
    }
    if isinstance(facts_obj, PickupFacts):
        facts |= {
            "kind": "PICKUP",
            "window_days": facts_obj.window_days,
            "prior_rooms_on_books": facts_obj.prior_rooms_on_books,
            "actual_pickup": facts_obj.actual_pickup,
            "expected_pickup": _text(facts_obj.expected_pickup),
            "delta_rooms": _text(facts_obj.delta_rooms),
            "missing_rooms": _text(facts_obj.missing_rooms),
            "delta_percent_exact": _text(facts_obj.delta_percent_exact),
            "percent_condition": facts_obj.percent_condition,
            "rooms_condition": facts_obj.rooms_condition,
        }
    elif isinstance(facts_obj, OccupancyFacts):
        facts |= {
            "kind": "OCCUPANCY",
            "forecast_rooms": _text(facts_obj.forecast_rooms),
            "expected_final_rooms": _text(facts_obj.expected_final_rooms),
            "occupancy_gap_pp_exact": _text(facts_obj.occupancy_gap_pp_exact),
            "room_shortfall": _text(facts_obj.room_shortfall),
            "gap_condition": facts_obj.gap_condition,
            "shortfall_condition": facts_obj.shortfall_condition,
        }
    else:  # pragma: no cover - PickupFacts | OccupancyFacts is the whole union
        raise TypeError(f"unrecognised revenue facts type {type(facts_obj)!r}")

    pattern = facts_obj.pattern
    evidence: Payload = {
        "booking_data_source_id": str(evaluation.data_source_id),
        "baseline_confidence": _text(facts_obj.baseline_confidence),
        "pattern_confidence": None if pattern is None else _text(pattern.pattern_confidence),
        "pattern_pair_count": None if pattern is None else pattern.pair_count,
        "confidence_score": _text(evaluation.confidence_score),
        "revenue_gap_proxy": _text(evaluation.revenue_gap_proxy),
        "reference_adr": _text(evaluation.reference_adr),
        "reference_adr_source": evaluation.reference_adr_source.value,
        "rules_version": evaluation.rules_version,
    }
    return facts, evidence


# --- REV_OTA_DEPENDENCY ---------------------------------------------------------------------------


def serialize_ota(evaluation: OtaDependencyEvaluation) -> tuple[Payload, Payload]:
    facts: Payload = {
        "window_start": evaluation.window_start.isoformat(),
        "window_end": evaluation.window_end.isoformat(),
        "window_days": evaluation.window_days,
        "ota_room_nights": evaluation.ota_room_nights,
        "direct_room_nights": evaluation.direct_room_nights,
        "ota_share_exact": _text(evaluation.ota_share_exact),
        "expected_ota_share_exact": _text(evaluation.expected_ota_share_exact),
        "delta_pp_exact": _text(evaluation.delta_pp_exact),
        "upper_fence_exact": _text(evaluation.upper_fence_exact),
        "structural_condition": evaluation.structural_condition,
        "rising_condition": evaluation.rising_condition,
    }
    evidence: Payload = {
        "booking_data_source_id": str(evaluation.booking_data_source_id),
        "classification_coverage_pct_exact": _text(evaluation.classification_coverage_pct_exact),
        "observed_day_count": evaluation.observed_day_count,
        "reconstructed_day_count": evaluation.reconstructed_day_count,
        "sample_count": evaluation.sample_count,
        "baseline_confidence": _text(evaluation.baseline_confidence),
        "confidence_score": _text(evaluation.confidence_score),
        "ota_room_revenue_exposure": _text(evaluation.ota_room_revenue_on_books_exact),
        "rules_version": evaluation.rules_version,
    }
    return facts, evidence


# --- COST_CPOR_ANOMALY ----------------------------------------------------------------------------


def serialize_cost(evaluation: CostDecisionEvaluation) -> tuple[Payload, Payload]:
    metric = evaluation.target_metric
    facts: Payload = {
        "target_period_start": evaluation.target_period_start.isoformat(),
        "target_period_end": evaluation.target_period_end.isoformat(),
        "cost_category": evaluation.cost_category.value,
        "currency": evaluation.currency,
        "actual_cpor_exact": _text(metric.cpor_exact),
        "expected_cpor_exact": _text(evaluation.expected_cpor_exact),
        "delta_cpor_exact": _text(evaluation.delta_cpor_exact),
        "delta_percent_exact": _text(evaluation.delta_percent_exact),
        "upper_fence_exact": _text(evaluation.upper_fence_exact),
        "cost_gap_proxy_exact": _text(evaluation.cost_gap_proxy_exact),
    }
    evidence: Payload = {
        "booking_data_source_id": str(evaluation.booking_data_source_id),
        "classification_coverage_pct_exact": _text(metric.classification_coverage_pct_exact),
        "occupancy_provenance_score_exact": _text(metric.occupancy_provenance_score_exact),
        "sample_count": evaluation.sample_count,
        "observed_period_count": evaluation.observed_period_count,
        "baseline_confidence": _text(evaluation.baseline_confidence),
        "confidence_score": _text(evaluation.confidence_score),
        "rules_version": evaluation.rules_version,
    }
    return facts, evidence


# --- LABOR_OVERSTAFFING ---------------------------------------------------------------------------


def serialize_labor(evaluation: LaborDecisionEvaluation) -> tuple[Payload, Payload]:
    facts: Payload = {
        "work_date": evaluation.target_work_date.isoformat(),
        "labor_category": evaluation.labor_category.value,
        "forecast_rooms_exact": _text(evaluation.forecast_rooms_exact),
        "scheduled_hours_exact": _text(evaluation.scheduled_hours_exact),
        "expected_labor_hours_exact": _text(evaluation.expected_labor_hours_exact),
        "excess_hours_exact": _text(evaluation.excess_hours_exact),
        "delta_percent_exact": _text(evaluation.delta_percent_exact),
        "upper_fence_hours_exact": _text(evaluation.upper_fence_hours_exact),
    }
    evidence: Payload = {
        "booking_data_source_id": str(evaluation.booking_data_source_id),
        "labor_data_source_id": str(evaluation.labor_data_source_id),
        "classification_coverage_pct_exact": _text(evaluation.classification_coverage_pct_exact),
        "demand_confidence": _text(evaluation.demand_confidence),
        "target_plan_quality": _text(evaluation.target_plan_quality),
        "sample_count": evaluation.sample_count,
        "fully_observed_count": evaluation.fully_observed_count,
        "confidence_score": _text(evaluation.confidence_score),
        "labor_cost_gap_proxy_exact": _text(evaluation.labor_cost_gap_proxy_exact),
        "cost_currency": evaluation.cost_currency,
        "rules_version": evaluation.rules_version,
    }
    return facts, evidence


def serialize_facts(evaluation: SourceEvaluation) -> tuple[Payload, Payload]:
    """Dispatch one evaluation of a known type to its own explicit serializer."""
    if isinstance(evaluation, RevenueDecisionEvaluation):
        return serialize_revenue(evaluation)
    if isinstance(evaluation, OtaDependencyEvaluation):
        return serialize_ota(evaluation)
    if isinstance(evaluation, CostDecisionEvaluation):
        return serialize_cost(evaluation)
    if isinstance(evaluation, LaborDecisionEvaluation):
        return serialize_labor(evaluation)
    raise TypeError(f"unrecognised source evaluation type {type(evaluation)!r}")


__all__ = [
    "Payload",
    "SourceEvaluation",
    "reason_codes_of",
    "serialize_cost",
    "serialize_facts",
    "serialize_labor",
    "serialize_ota",
    "serialize_revenue",
]

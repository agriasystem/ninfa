"""Five explicit adapters: one TRIGGERED evaluation of a known type -> one `AdaptedSignal`.

An adapter never re-decides whether a detector is right (its own boolean condition fields -
`percent_condition`, `gap_condition`, `structural_condition`, the four cost/labor conditions - are
read, never recomputed) and never calls a repository, a detector or the database: it is a pure
function of one already-computed, immutable evaluation plus the `PriorityContext` it is being
ranked against. Economic proxies (`revenue_gap_proxy`, `cost_gap_proxy_exact`, ...) are carried
through as EVIDENCE ONLY, in their own currency where the source has one; they never feed a score
and are never compared across detectors or currencies (see `priority/impact.py`).

`PRIORITY_INVALID_SOURCE_EVALUATION` is raised whenever a TRIGGERED evaluation's own facts are not
internally coherent with its own status - never a silent correction.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.intelligence.distribution.types import OtaDecisionType, OtaDependencyEvaluation
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.priority.actionability import actionability_policy_name
from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.impact import (
    cost_impact,
    labor_impact,
    occupancy_impact,
    ota_impact,
    pickup_impact,
)
from app.modules.intelligence.priority.types import (
    DETECTOR_CONFIDENCE_GATE,
    PriorityContext,
    PriorityDecisionType,
)
from app.modules.intelligence.priority.urgency import cost_urgency, forward_urgency, ota_urgency
from app.modules.intelligence.revenue.types import (
    OccupancyFacts,
    PickupFacts,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)

_INVALID = PriorityErrorCode.PRIORITY_INVALID_SOURCE_EVALUATION
_AS_OF_MISMATCH = PriorityErrorCode.PRIORITY_AS_OF_MISMATCH
_STALE = PriorityErrorCode.PRIORITY_STALE_SOURCE_EVALUATION
_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class AdaptedSignal:
    """The common, detector-agnostic shape every adapter reduces one evaluation to."""

    decision_type: PriorityDecisionType
    workspace_id: UUID
    property_id: UUID
    source_evaluation_fingerprint: str
    source_target_key: str
    confidence_score: Decimal
    impact_score_exact: Decimal
    impact_basis: dict[str, Any]
    urgency_score: Decimal
    urgency_basis: dict[str, Any]
    economic_proxy_exact: Decimal | None
    economic_proxy_currency: str | None
    economic_proxy_label: str | None
    source_reason_codes: tuple[str, ...]


def _require_fingerprint(fingerprint: str) -> None:
    if not fingerprint:
        raise PriorityError(_INVALID, "a TRIGGERED evaluation must carry a non-empty fingerprint")


def _require_confidence_in_range(confidence_score: Decimal) -> None:
    if confidence_score < 0 or confidence_score > 100:
        raise PriorityError(_INVALID, f"confidence_score {confidence_score} is outside 0-100")


def _require_confidence_meets_gate(
    decision_type: PriorityDecisionType, confidence_score: Decimal
) -> None:
    gate = DETECTOR_CONFIDENCE_GATE[decision_type]
    if confidence_score < gate:
        raise PriorityError(
            _INVALID,
            f"{decision_type.value} TRIGGERED with confidence {confidence_score} "
            f"below its own detector gate {gate}",
        )


def _require_as_of_match(*, evaluation_date: date, context_date: date, label: str) -> None:
    if evaluation_date != context_date:
        raise PriorityError(
            _AS_OF_MISMATCH,
            f"{label} {evaluation_date} != PriorityContext.as_of_local_date {context_date}",
        )


def _forward_days_or_stale(target_date: date, as_of_local_date: date, *, label: str) -> int:
    days_to_target = (target_date - as_of_local_date).days
    if days_to_target < 0:
        raise PriorityError(_STALE, f"{label} {target_date} is before as-of {as_of_local_date}")
    return days_to_target


def _reason_codes(evaluation: Any) -> tuple[str, ...]:
    return tuple(code.value for code in evaluation.reason_codes)


# --- REV_PICKUP_LOW --------------------------------------------------------------------------


def adapt_pickup(context: PriorityContext, evaluation: RevenueDecisionEvaluation) -> AdaptedSignal:
    decision_type = PriorityDecisionType.REV_PICKUP_LOW
    _require_fingerprint(evaluation.calculation_fingerprint)
    _require_confidence_in_range(evaluation.confidence_score)
    _require_confidence_meets_gate(decision_type, evaluation.confidence_score)

    facts = evaluation.facts
    if not isinstance(facts, PickupFacts):
        raise PriorityError(_INVALID, "REV_PICKUP_LOW evaluation must carry PickupFacts")
    if facts.percent_condition is not True or facts.rooms_condition is not True:
        raise PriorityError(
            _INVALID,
            "REV_PICKUP_LOW TRIGGERED but percent_condition/rooms_condition are not both true",
        )
    delta_percent_exact = facts.delta_percent_exact
    missing_rooms = facts.missing_rooms
    if delta_percent_exact is None or missing_rooms is None:
        raise PriorityError(
            _INVALID, "REV_PICKUP_LOW TRIGGERED without delta_percent_exact/missing_rooms"
        )

    abs_negative_delta_percent = abs(min(delta_percent_exact, _ZERO))
    try:
        impact = pickup_impact(abs_negative_delta_percent, missing_rooms)
    except ValueError as error:
        raise PriorityError(_INVALID, str(error)) from error

    _require_as_of_match(
        evaluation_date=evaluation.snapshot_local_date,
        context_date=context.as_of_local_date,
        label="REV_PICKUP_LOW snapshot_local_date",
    )
    days_to_target = _forward_days_or_stale(
        evaluation.stay_date, context.as_of_local_date, label="REV_PICKUP_LOW stay_date"
    )
    urgency = forward_urgency(days_to_target)

    economic_proxy_exact = evaluation.revenue_gap_proxy
    return AdaptedSignal(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=(
            f"stay:{evaluation.stay_date.isoformat()}|snapshot:{evaluation.target_snapshot_id}"
        ),
        confidence_score=evaluation.confidence_score,
        impact_score_exact=impact,
        impact_basis={
            "delta_percent_exact": delta_percent_exact,
            "missing_rooms": missing_rooms,
            "abs_negative_delta_percent": abs_negative_delta_percent,
            "policy": "pickup-impact-v1",
        },
        urgency_score=urgency,
        urgency_basis={
            "target_date": evaluation.stay_date,
            "as_of_local_date": context.as_of_local_date,
            "days_to_target": days_to_target,
            "policy": "forward-urgency-v1",
        },
        economic_proxy_exact=economic_proxy_exact,
        economic_proxy_currency=None,
        economic_proxy_label=None if economic_proxy_exact is None else "REVENUE_GAP_PROXY",
        source_reason_codes=_reason_codes(evaluation),
    )


# --- REV_OCCUPANCY_RISK ----------------------------------------------------------------------


def adapt_occupancy(
    context: PriorityContext, evaluation: RevenueDecisionEvaluation
) -> AdaptedSignal:
    decision_type = PriorityDecisionType.REV_OCCUPANCY_RISK
    _require_fingerprint(evaluation.calculation_fingerprint)
    _require_confidence_in_range(evaluation.confidence_score)
    _require_confidence_meets_gate(decision_type, evaluation.confidence_score)

    facts = evaluation.facts
    if not isinstance(facts, OccupancyFacts):
        raise PriorityError(_INVALID, "REV_OCCUPANCY_RISK evaluation must carry OccupancyFacts")
    if facts.gap_condition is not True and facts.shortfall_condition is not True:
        raise PriorityError(
            _INVALID,
            "REV_OCCUPANCY_RISK TRIGGERED but neither gap_condition nor shortfall_condition holds",
        )
    occupancy_gap_pp = facts.occupancy_gap_pp_exact
    room_shortfall = facts.room_shortfall
    if occupancy_gap_pp is None or room_shortfall is None:
        raise PriorityError(
            _INVALID, "REV_OCCUPANCY_RISK TRIGGERED without occupancy_gap_pp_exact/room_shortfall"
        )

    impact = occupancy_impact(occupancy_gap_pp, room_shortfall)

    _require_as_of_match(
        evaluation_date=evaluation.snapshot_local_date,
        context_date=context.as_of_local_date,
        label="REV_OCCUPANCY_RISK snapshot_local_date",
    )
    days_to_target = _forward_days_or_stale(
        evaluation.stay_date, context.as_of_local_date, label="REV_OCCUPANCY_RISK stay_date"
    )
    urgency = forward_urgency(days_to_target)

    economic_proxy_exact = evaluation.revenue_gap_proxy
    return AdaptedSignal(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=(
            f"stay:{evaluation.stay_date.isoformat()}|snapshot:{evaluation.target_snapshot_id}"
        ),
        confidence_score=evaluation.confidence_score,
        impact_score_exact=impact,
        impact_basis={
            "occupancy_gap_pp_exact": occupancy_gap_pp,
            "room_shortfall": room_shortfall,
            "policy": "occupancy-impact-v1",
        },
        urgency_score=urgency,
        urgency_basis={
            "target_date": evaluation.stay_date,
            "as_of_local_date": context.as_of_local_date,
            "days_to_target": days_to_target,
            "policy": "forward-urgency-v1",
        },
        economic_proxy_exact=economic_proxy_exact,
        economic_proxy_currency=None,
        economic_proxy_label=None if economic_proxy_exact is None else "REVENUE_GAP_PROXY",
        source_reason_codes=_reason_codes(evaluation),
    )


# --- REV_OTA_DEPENDENCY ----------------------------------------------------------------------


def adapt_ota(context: PriorityContext, evaluation: OtaDependencyEvaluation) -> AdaptedSignal:
    decision_type = PriorityDecisionType.REV_OTA_DEPENDENCY
    if evaluation.decision_type != OtaDecisionType.REV_OTA_DEPENDENCY:
        raise PriorityError(_INVALID, f"unexpected OTA decision_type {evaluation.decision_type!r}")
    _require_fingerprint(evaluation.calculation_fingerprint)
    _require_confidence_in_range(evaluation.confidence_score)
    _require_confidence_meets_gate(decision_type, evaluation.confidence_score)

    structural_condition = evaluation.structural_condition
    rising_condition = evaluation.rising_condition
    if structural_condition is None or rising_condition is None:
        raise PriorityError(
            _INVALID, "REV_OTA_DEPENDENCY TRIGGERED without structural_condition/rising_condition"
        )
    if not structural_condition and not rising_condition:
        raise PriorityError(
            _INVALID, "REV_OTA_DEPENDENCY TRIGGERED but neither structural nor rising holds"
        )
    ota_share_exact = evaluation.ota_share_exact
    delta_pp_exact = evaluation.delta_pp_exact
    if ota_share_exact is None or delta_pp_exact is None:
        raise PriorityError(
            _INVALID, "REV_OTA_DEPENDENCY TRIGGERED without ota_share_exact/delta_pp_exact"
        )

    try:
        impact = ota_impact(
            ota_share_exact,
            delta_pp_exact,
            structural_condition=structural_condition,
            rising_condition=rising_condition,
        )
    except ValueError as error:
        raise PriorityError(_INVALID, str(error)) from error

    _require_as_of_match(
        evaluation_date=evaluation.as_of_local_date,
        context_date=context.as_of_local_date,
        label="REV_OTA_DEPENDENCY as_of_local_date",
    )
    try:
        urgency = ota_urgency(
            structural_condition=structural_condition, rising_condition=rising_condition
        )
    except ValueError as error:
        raise PriorityError(_INVALID, str(error)) from error

    economic_proxy_exact = evaluation.ota_room_revenue_on_books_exact
    return AdaptedSignal(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=(
            f"asof:{evaluation.as_of_local_date.isoformat()}"
            f"|window:{evaluation.window_start.isoformat()}..{evaluation.window_end.isoformat()}"
        ),
        confidence_score=evaluation.confidence_score,
        impact_score_exact=impact,
        impact_basis={
            "ota_share_exact": ota_share_exact,
            "delta_pp_exact": delta_pp_exact,
            "structural_condition": structural_condition,
            "rising_condition": rising_condition,
            "policy": "ota-impact-v1",
        },
        urgency_score=urgency,
        urgency_basis={
            "structural_condition": structural_condition,
            "rising_condition": rising_condition,
            "policy": "ota-urgency-v1",
        },
        economic_proxy_exact=economic_proxy_exact,
        # OtaDependencyEvaluation carries no currency string of its own (Booking has none either:
        # only Property does, and this pure engine never queries a repository to fetch it) - never
        # invented, so the exposure is surfaced without a currency label rather than guessing one.
        economic_proxy_currency=None,
        economic_proxy_label=None if economic_proxy_exact is None else "OTA_ROOM_REVENUE_EXPOSURE",
        source_reason_codes=_reason_codes(evaluation),
    )


# --- COST_CPOR_ANOMALY -----------------------------------------------------------------------


def adapt_cost(context: PriorityContext, evaluation: CostDecisionEvaluation) -> AdaptedSignal:
    decision_type = PriorityDecisionType.COST_CPOR_ANOMALY
    _require_fingerprint(evaluation.calculation_fingerprint)
    _require_confidence_in_range(evaluation.confidence_score)
    _require_confidence_meets_gate(decision_type, evaluation.confidence_score)

    conditions = (
        evaluation.above_expected_condition,
        evaluation.relative_condition,
        evaluation.upper_fence_condition,
        evaluation.gap_condition,
    )
    if any(condition is not True for condition in conditions):
        raise PriorityError(
            _INVALID, "COST_CPOR_ANOMALY TRIGGERED but not all four numeric conditions hold"
        )

    actual_cpor = evaluation.target_metric.cpor_exact
    upper_fence = evaluation.upper_fence_exact
    delta_percent = evaluation.delta_percent_exact
    if actual_cpor is None or upper_fence is None or delta_percent is None:
        raise PriorityError(
            _INVALID, "COST_CPOR_ANOMALY TRIGGERED without cpor/upper_fence/delta_percent"
        )
    try:
        impact = cost_impact(delta_percent, actual_cpor, upper_fence)
    except ValueError as error:
        raise PriorityError(_INVALID, str(error)) from error

    days_since_period_end = (context.as_of_local_date - evaluation.target_period_end).days
    try:
        urgency = cost_urgency(days_since_period_end)
    except ValueError as error:
        raise PriorityError(_INVALID, str(error)) from error

    economic_proxy_exact = evaluation.cost_gap_proxy_exact
    return AdaptedSignal(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=(
            f"month:{evaluation.target_period_start.isoformat()}"
            f"|category:{evaluation.cost_category.value}|currency:{evaluation.currency}"
        ),
        confidence_score=evaluation.confidence_score,
        impact_score_exact=impact,
        impact_basis={
            "delta_percent_exact": delta_percent,
            "actual_cpor_exact": actual_cpor,
            "upper_fence_exact": upper_fence,
            "policy": "cost-impact-v1",
        },
        urgency_score=urgency,
        urgency_basis={
            "target_period_end": evaluation.target_period_end,
            "as_of_local_date": context.as_of_local_date,
            "days_since_period_end": days_since_period_end,
            "policy": "cost-urgency-v1",
        },
        economic_proxy_exact=economic_proxy_exact,
        economic_proxy_currency=evaluation.currency,
        economic_proxy_label=None if economic_proxy_exact is None else "COST_GAP_PROXY",
        source_reason_codes=_reason_codes(evaluation),
    )


# --- LABOR_OVERSTAFFING -----------------------------------------------------------------------


def adapt_labor(context: PriorityContext, evaluation: LaborDecisionEvaluation) -> AdaptedSignal:
    decision_type = PriorityDecisionType.LABOR_OVERSTAFFING
    _require_fingerprint(evaluation.calculation_fingerprint)
    _require_confidence_in_range(evaluation.confidence_score)
    _require_confidence_meets_gate(decision_type, evaluation.confidence_score)

    conditions = (
        evaluation.above_expected_condition,
        evaluation.relative_condition,
        evaluation.excess_hours_condition,
        evaluation.upper_fence_condition,
    )
    if any(condition is not True for condition in conditions):
        raise PriorityError(
            _INVALID, "LABOR_OVERSTAFFING TRIGGERED but not all four numeric conditions hold"
        )

    delta_percent = evaluation.delta_percent_exact
    excess_hours = evaluation.excess_hours_exact
    if delta_percent is None or excess_hours is None:
        raise PriorityError(
            _INVALID, "LABOR_OVERSTAFFING TRIGGERED without delta_percent_exact/excess_hours_exact"
        )
    impact = labor_impact(delta_percent, excess_hours)

    _require_as_of_match(
        evaluation_date=evaluation.target_as_of_date,
        context_date=context.as_of_local_date,
        label="LABOR_OVERSTAFFING target_as_of_date",
    )
    days_to_target = _forward_days_or_stale(
        evaluation.target_work_date,
        context.as_of_local_date,
        label="LABOR_OVERSTAFFING target_work_date",
    )
    urgency = forward_urgency(days_to_target)

    if evaluation.target_labor_snapshot_id is None:
        raise PriorityError(
            _INVALID, "LABOR_OVERSTAFFING TRIGGERED without a target_labor_snapshot_id"
        )

    economic_proxy_exact = evaluation.labor_cost_gap_proxy_exact
    return AdaptedSignal(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=(
            f"workdate:{evaluation.target_work_date.isoformat()}"
            f"|category:{evaluation.labor_category.value}"
            f"|laborsnapshot:{evaluation.target_labor_snapshot_id}"
        ),
        confidence_score=evaluation.confidence_score,
        impact_score_exact=impact,
        impact_basis={
            "delta_percent_exact": delta_percent,
            "excess_hours_exact": excess_hours,
            "policy": "labor-impact-v1",
        },
        urgency_score=urgency,
        urgency_basis={
            "target_date": evaluation.target_work_date,
            "as_of_local_date": context.as_of_local_date,
            "days_to_target": days_to_target,
            "policy": "forward-urgency-v1",
        },
        economic_proxy_exact=economic_proxy_exact,
        economic_proxy_currency=evaluation.cost_currency,
        economic_proxy_label=None if economic_proxy_exact is None else "LABOR_COST_GAP_PROXY",
        source_reason_codes=_reason_codes(evaluation),
    )


def adapt_evaluation(context: PriorityContext, evaluation: Any) -> AdaptedSignal:
    """Dispatch one TRIGGERED evaluation of a known type to its own explicit adapter."""
    if isinstance(evaluation, RevenueDecisionEvaluation):
        if evaluation.decision_type == RevenueDecisionType.REV_PICKUP_LOW:
            return adapt_pickup(context, evaluation)
        if evaluation.decision_type == RevenueDecisionType.REV_OCCUPANCY_RISK:
            return adapt_occupancy(context, evaluation)
        raise PriorityError(_INVALID, f"unknown RevenueDecisionType {evaluation.decision_type!r}")
    if isinstance(evaluation, OtaDependencyEvaluation):
        return adapt_ota(context, evaluation)
    if isinstance(evaluation, CostDecisionEvaluation):
        return adapt_cost(context, evaluation)
    if isinstance(evaluation, LaborDecisionEvaluation):
        return adapt_labor(context, evaluation)
    raise PriorityError(_INVALID, f"unrecognised source evaluation type {type(evaluation)!r}")


__all__ = ["AdaptedSignal", "actionability_policy_name", "adapt_evaluation"]

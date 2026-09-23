"""LABOR_OVERSTAFFING V1: are the scheduled hours of a category materially above what comparable
demand days historically needed?

A pure function of the target's demand forecast, its own labor plan and its historical
comparables: no database, no clock, no persistence. The answer is one of the five statuses of the
revenue/cost detectors, with the facts.

Order of the checks (the first that applies decides; each has ONE stable reason):

    1. the category is OTHER                        NOT_APPLICABLE     ..._OTHER_NOT_ACTIONABLE
    2. the demand forecast is insufficient            INSUFFICIENT_DATA  ..._FORECAST_INSUFFICIENT
    3. no labor plan covers the target day            INSUFFICIENT_DATA  LABOR_PLAN_MISSING
    4. the category has no entry that day             NOT_APPLICABLE     ..._NOT_SCHEDULED
    5. the category's planned minutes are partial     INSUFFICIENT_DATA  LABOR_PLAN_INCOMPLETE
    6. the day's classification coverage is < 70%     INSUFFICIENT_DATA  ..._COVERAGE_LOW
    7. fewer than 5 comparable days                   INSUFFICIENT_DATA  ..._SAMPLE_INSUFFICIENT
    8. the expected hours are not positive             NOT_APPLICABLE     ..._NON_POSITIVE
    9. the numeric rule, then the confidence gate      TRIGGERED / SUPPRESSED_LOW_CONFIDENCE / CLEAR

The numeric rule needs ALL FOUR conditions (AND, never OR): scheduled hours above the expected
ones, at least 20% above them, at least 4 hours above them, and at or above the robust upper fence
(P75 + 1.5 * IQR). Every comparison is on the FULL-PRECISION values; the two-decimal display
values never decide. The optional cost proxy is computed whenever a rate is resolvable, whatever
the status, and never enters the trigger.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.intelligence.demand.service import DemandForecast, DemandForecastStatus
from app.modules.intelligence.labor.aggregation import TargetPlan
from app.modules.intelligence.labor.confidence import baseline_confidence, final_confidence
from app.modules.intelligence.labor.cost_proxy import (
    TargetCategoryCost,
    labor_cost_gap_proxy,
    reference_hourly_cost,
)
from app.modules.intelligence.labor.fingerprint import seal
from app.modules.intelligence.labor.precision import percent_of
from app.modules.intelligence.labor.selection import ComparableSelection
from app.modules.intelligence.labor.statistics import summarize
from app.modules.intelligence.labor.types import (
    LABOR_THRESHOLDS,
    EvaluationStatus,
    LaborDecisionEvaluation,
    LaborDecisionType,
    LaborThresholds,
    ReasonCode,
)
from app.modules.labor.roles import LaborCategory

_ZERO = Decimal(0)

_DEFAULTS: dict[str, Any] = {
    "forecast_rooms_exact": None,
    "demand_confidence": None,
    "scheduled_hours_exact": None,
    "classification_coverage_pct_exact": None,
    "target_category_classification_confidence_exact": None,
    "target_plan_quality": None,
    "expected_labor_hours_exact": None,
    "p25_exact": None,
    "p75_exact": None,
    "iqr_exact": None,
    "upper_fence_hours_exact": None,
    "excess_hours_exact": None,
    "delta_percent_exact": None,
    "above_expected_condition": None,
    "relative_condition": None,
    "excess_hours_condition": None,
    "upper_fence_condition": None,
    "sample_count": 0,
    "fully_observed_count": 0,
    "approximate_count": 0,
    "candidate_day_count": 0,
    "rejected_occupancy_incomplete_count": 0,
    "rejected_demand_mismatch_count": 0,
    "rejected_labor_missing_count": 0,
    "rejected_labor_incomplete_count": 0,
    "rejected_low_classification_count": 0,
    "baseline_confidence": None,
    "sample_score_exact": None,
    "provenance_score_exact": None,
    "classification_score_exact": None,
    "stability_score_exact": None,
    "confidence_cap": None,
    "confidence_score": Decimal("0.00"),
    "reference_hourly_cost_exact": None,
    "reference_hourly_cost_source": None,
    "cost_currency": None,
    "labor_cost_gap_proxy_exact": None,
    "comparable_days": (),
}


def evaluate_labor_overstaffing(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    labor_data_source_id: UUID,
    target_booking_snapshot_id: UUID,
    target_as_of_date: date,
    target_work_date: date,
    labor_category: LaborCategory,
    demand: DemandForecast,
    target_labor_snapshot_id: UUID | None,
    target_plan: TargetPlan | None,
    target_cost: TargetCategoryCost,
    select: Callable[[Decimal], ComparableSelection],
    thresholds: LaborThresholds = LABOR_THRESHOLDS,
) -> LaborDecisionEvaluation:
    """`select` builds the historical comparables; it is called only when the target itself is
    fit to be judged, so an unusable target never pays for (or leaks facts about) a baseline."""

    def finish(
        status: EvaluationStatus, reasons: tuple[ReasonCode, ...], **facts: Any
    ) -> LaborDecisionEvaluation:
        values = dict(_DEFAULTS)
        values.update(facts)
        return seal(
            LaborDecisionEvaluation(
                decision_type=LaborDecisionType.LABOR_OVERSTAFFING,
                status=status,
                workspace_id=workspace_id,
                property_id=property_id,
                booking_data_source_id=booking_data_source_id,
                labor_data_source_id=labor_data_source_id,
                target_booking_snapshot_id=target_booking_snapshot_id,
                target_labor_snapshot_id=target_labor_snapshot_id,
                target_as_of_date=target_as_of_date,
                target_work_date=target_work_date,
                labor_category=labor_category,
                thresholds=thresholds,
                reason_codes=reasons,
                **values,
            )
        )

    # 1. the requested category itself needs no data to answer
    if labor_category == LaborCategory.OTHER:
        return finish(
            EvaluationStatus.NOT_APPLICABLE, (ReasonCode.LABOR_CATEGORY_OTHER_NOT_ACTIONABLE,)
        )

    # 2. the demand forecast
    if demand.status == DemandForecastStatus.INSUFFICIENT_DATA:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.LABOR_DEMAND_FORECAST_INSUFFICIENT,)
        )
    assert demand.forecast_rooms_exact is not None and demand.demand_confidence is not None
    demand_facts = {
        "forecast_rooms_exact": demand.forecast_rooms_exact,
        "demand_confidence": demand.demand_confidence,
    }

    # 3. no labor snapshot covers the target day at all
    if target_plan is None and target_labor_snapshot_id is None:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.LABOR_PLAN_MISSING,), **demand_facts
        )

    # 4. the category has no entry that day
    if target_plan is None:
        return finish(
            EvaluationStatus.NOT_APPLICABLE,
            (ReasonCode.LABOR_CATEGORY_NOT_SCHEDULED,),
            **demand_facts,
        )

    # 5. the category's planned minutes are partial
    if not target_plan.complete:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.LABOR_PLAN_INCOMPLETE,), **demand_facts
        )

    scheduled_hours = target_plan.scheduled_hours_exact
    coverage = target_plan.quality.coverage_pct_exact

    # 6. the day's classification coverage (every category, not just this one)
    if coverage is None or coverage < thresholds.min_classification_coverage:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.LABOR_CLASSIFICATION_COVERAGE_LOW,),
            **demand_facts,
            scheduled_hours_exact=scheduled_hours,
            classification_coverage_pct_exact=coverage,
        )

    weighted_confidence = target_plan.quality.weighted_confidence_exact
    target_plan_quality = target_plan.target_plan_quality
    assert weighted_confidence is not None and target_plan_quality is not None
    plan_facts = {
        **demand_facts,
        "scheduled_hours_exact": scheduled_hours,
        "classification_coverage_pct_exact": coverage,
        "target_category_classification_confidence_exact": weighted_confidence,
        "target_plan_quality": target_plan_quality,
    }

    # 7. the historical side: at least 5 comparable days
    selection = select(demand.forecast_rooms_exact)
    selection_facts = {
        "sample_count": selection.sample_count,
        "fully_observed_count": selection.fully_observed_count,
        "approximate_count": selection.approximate_count,
        "candidate_day_count": selection.candidate_day_count,
        "rejected_occupancy_incomplete_count": selection.rejected_occupancy_incomplete_count,
        "rejected_demand_mismatch_count": selection.rejected_demand_mismatch_count,
        "rejected_labor_missing_count": selection.rejected_labor_missing_count,
        "rejected_labor_incomplete_count": selection.rejected_labor_incomplete_count,
        "rejected_low_classification_count": selection.rejected_low_classification_count,
        "comparable_days": selection.days,
    }
    if selection.sample_count < thresholds.min_comparables:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.LABOR_COMPARABLE_SAMPLE_INSUFFICIENT,),
            **plan_facts,
            **selection_facts,
        )

    # 8. the statistics, and the expected hours must be positive
    stats = summarize(
        [day.historical_hours_exact for day in selection.days],
        iqr_multiplier=thresholds.iqr_multiplier,
    )
    stats_facts = {
        "expected_labor_hours_exact": stats.median,
        "p25_exact": stats.p25,
        "p75_exact": stats.p75,
        "iqr_exact": stats.iqr,
        "upper_fence_hours_exact": stats.upper_fence,
    }
    if stats.median <= _ZERO:
        return finish(
            EvaluationStatus.NOT_APPLICABLE,
            (ReasonCode.EXPECTED_LABOR_HOURS_NON_POSITIVE,),
            **plan_facts,
            **selection_facts,
            **stats_facts,
        )

    # 9. the thresholds, on the full-precision values; the display values are derived AFTER
    excess_hours = max(_ZERO, scheduled_hours - stats.median)
    delta_percent = percent_of(scheduled_hours - stats.median, stats.median)
    above = scheduled_hours > stats.median
    relative = delta_percent >= thresholds.relative_percent
    excess_ok = excess_hours >= thresholds.excess_hours_threshold
    fence = scheduled_hours >= stats.upper_fence
    numeric_candidate = above and relative and excess_ok and fence  # AND, never OR

    baseline = baseline_confidence(selection.days, iqr=stats.iqr, expected_hours=stats.median)
    confidence = final_confidence(baseline.score, demand.demand_confidence, target_plan_quality)

    if numeric_candidate and confidence >= thresholds.min_confidence:
        status, reasons = EvaluationStatus.TRIGGERED, (ReasonCode.TRIGGER_LABOR_OVERSTAFFING,)
    elif numeric_candidate:
        status, reasons = EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE, (ReasonCode.LOW_CONFIDENCE,)
    else:
        status, reasons = EvaluationStatus.CLEAR, (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)

    rate = reference_hourly_cost(target_cost, scheduled_hours, selection.days)
    proxy = None if rate is None else labor_cost_gap_proxy(excess_hours, rate.value)

    return finish(
        status,
        reasons,
        **plan_facts,
        **selection_facts,
        **stats_facts,
        excess_hours_exact=excess_hours,
        delta_percent_exact=delta_percent,
        above_expected_condition=above,
        relative_condition=relative,
        excess_hours_condition=excess_ok,
        upper_fence_condition=fence,
        baseline_confidence=baseline.score,
        sample_score_exact=baseline.sample_score,
        provenance_score_exact=baseline.provenance_score,
        classification_score_exact=baseline.classification_score,
        stability_score_exact=baseline.stability_score,
        confidence_cap=baseline.cap,
        confidence_score=confidence,
        reference_hourly_cost_exact=None if rate is None else rate.value,
        reference_hourly_cost_source=None if rate is None else rate.source,
        cost_currency=None if rate is None else rate.currency,
        labor_cost_gap_proxy_exact=proxy,
    )

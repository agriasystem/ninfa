"""COST_CPOR_ANOMALY V1: is the cost per occupied room of a category materially above history?

A pure function of a period metric and its historical comparables: no database, no clock, no
persistence. The answer is one of the five statuses of the revenue detectors, with the facts.

Order of the checks (the first that fails decides; each has ONE stable reason):

    1. the category is OTHER                       NOT_APPLICABLE    ..._OTHER_NOT_ACTIONABLE
    2. no cost line of the currency / category     NOT_APPLICABLE    COST_..._NOT_PRESENT
    3. the occupancy of the month is incomplete    INSUFFICIENT_DATA OCCUPANCY_PERIOD_INCOMPLETE
    4. the month has no occupied room night        NOT_APPLICABLE    ZERO_OCCUPIED_ROOM_NIGHTS
    5. too much of the month's cost is OTHER       INSUFFICIENT_DATA COST_CLASSIFICATION_COVERAGE_*
    6. fewer than 5 comparable months              INSUFFICIENT_DATA COMPARABLE_SAMPLE_INSUFFICIENT
    7. the expected CPOR is not positive           NOT_APPLICABLE    EXPECTED_CPOR_NON_POSITIVE
    8. the numeric rule, then the confidence gate  TRIGGERED / SUPPRESSED_LOW_CONFIDENCE / CLEAR

The numeric rule needs ALL FOUR conditions (AND, never OR): the CPOR is above the expected one, at
least 20 % above it, at or above the robust upper fence (P75 + 1.5 * IQR), and the gross cost gap
at the target's own volume is at least 100 currency units: relative materiality AND a real
departure from the historical distribution AND absolute materiality. Every comparison is on the
FULL-PRECISION values; the two-decimal display values never decide.

A target whose net cost is zero or negative (credit notes) is not a high-cost anomaly: it is CLEAR.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.modules.intelligence.costs.confidence import (
    baseline_confidence,
    final_confidence,
    target_quality,
)
from app.modules.intelligence.costs.fingerprint import seal
from app.modules.intelligence.costs.precision import CALCULATION_CONTEXT, percent_of
from app.modules.intelligence.costs.selection import ComparableSelection
from app.modules.intelligence.costs.statistics import summarize
from app.modules.intelligence.costs.types import (
    COST_THRESHOLDS,
    ComparablePeriodFact,
    CostDecisionEvaluation,
    CostDecisionType,
    CostPeriodMetric,
    CostThresholds,
    EvaluationStatus,
    MetricStatus,
    ReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory

_ZERO = Decimal(0)


def _evaluation(
    target: CostPeriodMetric,
    status: EvaluationStatus,
    reasons: tuple[ReasonCode, ...],
    thresholds: CostThresholds,
    selection: ComparableSelection | None = None,
    **facts: Any,
) -> CostDecisionEvaluation:
    """Build and seal an evaluation; every fact not given is `None` / zero (nothing invented)."""
    values: dict[str, Any] = {
        "expected_cpor_exact": None,
        "p25_exact": None,
        "p75_exact": None,
        "iqr_exact": None,
        "upper_fence_exact": None,
        "delta_cpor_exact": None,
        "delta_percent_exact": None,
        "expected_cost_for_target_volume_exact": None,
        "cost_gap_proxy_exact": None,
        "above_expected_condition": None,
        "relative_condition": None,
        "upper_fence_condition": None,
        "gap_condition": None,
        "baseline_confidence": None,
        "sample_score_exact": None,
        "provenance_score_exact": None,
        "classification_score_exact": None,
        "stability_score_exact": None,
        "confidence_cap": None,
        "target_quality": None,
        "confidence_score": _ZERO,
        "comparable_periods": (),
    }
    values.update(facts)
    return seal(
        CostDecisionEvaluation(
            decision_type=CostDecisionType.COST_CPOR_ANOMALY,
            status=status,
            workspace_id=target.workspace_id,
            property_id=target.property_id,
            booking_data_source_id=target.booking_data_source_id,
            target_period_start=target.period_start,
            target_period_end=target.period_end,
            cost_category=target.cost_category,
            currency=target.currency,
            target_metric=target,
            sample_count=0 if selection is None else selection.sample_count,
            observed_period_count=0 if selection is None else selection.observed_period_count,
            approximate_period_count=(
                0 if selection is None else selection.approximate_period_count
            ),
            candidate_month_count=0 if selection is None else selection.candidate_month_count,
            rejected_no_cost_data_count=(
                0 if selection is None else selection.rejected_no_cost_data_count
            ),
            rejected_low_classification_count=(
                0 if selection is None else selection.rejected_low_classification_count
            ),
            rejected_incomplete_occupancy_count=(
                0 if selection is None else selection.rejected_incomplete_occupancy_count
            ),
            rejected_zero_occupancy_count=(
                0 if selection is None else selection.rejected_zero_occupancy_count
            ),
            thresholds=thresholds,
            reason_codes=reasons,
            **values,
        )
    )


# How a metric that is not READY is answered (its reason codes become the evaluation's).
_NOT_READY: dict[MetricStatus, EvaluationStatus] = {
    MetricStatus.NO_COST_DATA: EvaluationStatus.NOT_APPLICABLE,
    MetricStatus.INCOMPLETE: EvaluationStatus.INSUFFICIENT_DATA,
    MetricStatus.ZERO_OCCUPANCY: EvaluationStatus.NOT_APPLICABLE,
    MetricStatus.LOW_CLASSIFICATION_COVERAGE: EvaluationStatus.INSUFFICIENT_DATA,
}


def evaluate_cpor_anomaly(
    target: CostPeriodMetric,
    select: Callable[[], ComparableSelection],
    thresholds: CostThresholds = COST_THRESHOLDS,
) -> CostDecisionEvaluation:
    """Evaluate COST_CPOR_ANOMALY for one target metric.

    `select` builds the historical comparables; it is called only when the target itself is fit
    to be judged, so an unusable target never pays for (or leaks facts about) a baseline.
    """
    if target.cost_category == CostCategory.OTHER:
        return _evaluation(
            target,
            EvaluationStatus.NOT_APPLICABLE,
            (ReasonCode.COST_CATEGORY_OTHER_NOT_ACTIONABLE,),
            thresholds,
        )
    if target.status != MetricStatus.READY:
        return _evaluation(target, _NOT_READY[target.status], target.reason_codes, thresholds)

    assert target.cpor_exact is not None and target.net_cost is not None
    assert target.occupied_room_nights is not None

    selection = select()
    if selection.sample_count < thresholds.min_comparables:
        return _evaluation(
            target,
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.COMPARABLE_SAMPLE_INSUFFICIENT,),
            thresholds,
            selection,
        )

    periods = tuple(ComparablePeriodFact.of(metric) for metric in selection.periods)
    stats = summarize([p.cpor_exact for p in periods], iqr_multiplier=thresholds.iqr_multiplier)
    if stats.median <= _ZERO:
        return _evaluation(
            target,
            EvaluationStatus.NOT_APPLICABLE,
            (ReasonCode.EXPECTED_CPOR_NON_POSITIVE,),
            thresholds,
            selection,
            expected_cpor_exact=stats.median,
            p25_exact=stats.p25,
            p75_exact=stats.p75,
            iqr_exact=stats.iqr,
            upper_fence_exact=stats.upper_fence,
            comparable_periods=periods,
        )

    actual = target.cpor_exact
    delta = CALCULATION_CONTEXT.subtract(actual, stats.median)
    delta_percent = percent_of(delta, stats.median)
    expected_cost = CALCULATION_CONTEXT.multiply(stats.median, Decimal(target.occupied_room_nights))
    gap = max(_ZERO, CALCULATION_CONTEXT.subtract(target.net_cost, expected_cost))

    above = actual > stats.median
    relative = delta_percent >= thresholds.relative_percent
    fence = actual >= stats.upper_fence
    materiality = gap >= thresholds.absolute_gap
    numeric_candidate = above and relative and fence and materiality  # AND, never OR

    baseline = baseline_confidence(periods, stats)
    quality = target_quality(target)
    confidence = final_confidence(baseline.score, quality)

    if numeric_candidate and confidence >= thresholds.min_confidence:
        status, reasons = EvaluationStatus.TRIGGERED, (ReasonCode.TRIGGER_CPOR_ANOMALY,)
    elif numeric_candidate:
        status, reasons = EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE, (ReasonCode.LOW_CONFIDENCE,)
    else:
        status = EvaluationStatus.CLEAR
        reasons = (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)

    return _evaluation(
        target,
        status,
        reasons,
        thresholds,
        selection,
        expected_cpor_exact=stats.median,
        p25_exact=stats.p25,
        p75_exact=stats.p75,
        iqr_exact=stats.iqr,
        upper_fence_exact=stats.upper_fence,
        delta_cpor_exact=delta,
        delta_percent_exact=delta_percent,
        expected_cost_for_target_volume_exact=expected_cost,
        cost_gap_proxy_exact=gap,
        above_expected_condition=above,
        relative_condition=relative,
        upper_fence_condition=fence,
        gap_condition=materiality,
        baseline_confidence=baseline.score,
        sample_score_exact=baseline.sample_score,
        provenance_score_exact=baseline.provenance_score,
        classification_score_exact=baseline.classification_score,
        stability_score_exact=baseline.stability_score,
        confidence_cap=baseline.cap,
        target_quality=quality,
        confidence_score=confidence,
        comparable_periods=periods,
    )

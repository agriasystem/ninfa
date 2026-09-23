"""REV_OTA_DEPENDENCY V1: is the property's next 30 days of room-night business concentrated on
OTA channels, either STRUCTURALLY (already high, regardless of history) or by RISING sharply
above comparable history?

A pure function of the target's own 30-day channel mix and its historical comparables: no
database, no clock, no persistence. The answer is one of the five statuses of the revenue/cost/
labor detectors, with the facts. It measures CONCENTRATION of the distribution mix, never
channel PERFORMANCE.

Order of the checks (the first that applies decides; each has ONE stable reason):

    1. the target's 30-snapshot window is incomplete   INSUFFICIENT_DATA  ..._WINDOW_INCOMPLETE
    2. any target snapshot is uncertain                 INSUFFICIENT_DATA  ..._WINDOW_UNCERTAIN
    3. the reconstructed channel mix does not reconcile INSUFFICIENT_DATA  ..._RECONCILIATION_FAILED
    4. zero certain room nights on the books             NOT_APPLICABLE     ..._NO_ON_BOOKS_DEMAND
    5. classification coverage under 80%                INSUFFICIENT_DATA  ..._COVERAGE_LOW
    6. fewer than 20 classified room nights              INSUFFICIENT_DATA  ..._VOLUME_LOW
    7. fewer than 5 comparable periods                   INSUFFICIENT_DATA  ..._SAMPLE_INSUFFICIENT
    8. the numeric rule, then the confidence gate        TRIGGERED / SUPPRESSED / CLEAR

The numeric rule is STRUCTURAL (actual share >= 70%) OR RISING (actual >= 55% AND at least 15
percentage points above the historical median AND at or above the robust upper fence P75 + 1.5 *
IQR) - never AND between the two paths, and structural dependency never requires the share to
have risen. Every comparison is on the FULL-PRECISION values; the two-decimal display values
never decide. The optional revenue exposure is computed whenever both room revenues resolve,
whatever the status, and never enters the trigger.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.intelligence.distribution.confidence import baseline_confidence, final_confidence
from app.modules.intelligence.distribution.confidence import target_quality as target_quality_of
from app.modules.intelligence.distribution.fingerprint import seal
from app.modules.intelligence.distribution.metrics import TargetFacts
from app.modules.intelligence.distribution.precision import CALCULATION_CONTEXT, percent_of
from app.modules.intelligence.distribution.selection import ComparableSelection
from app.modules.intelligence.distribution.statistics import summarize
from app.modules.intelligence.distribution.types import (
    OTA_THRESHOLDS,
    EvaluationStatus,
    OtaDecisionType,
    OtaDependencyEvaluation,
    OtaThresholds,
    ReasonCode,
)

_ZERO = Decimal(0)

_DEFAULTS: dict[str, Any] = {
    "ota_room_nights": None,
    "direct_room_nights": None,
    "other_room_nights": None,
    "unknown_room_nights": None,
    "classified_room_nights": None,
    "certain_room_nights": None,
    "observed_day_count": 0,
    "reconstructed_day_count": 0,
    "classification_coverage_pct_exact": None,
    "snapshot_provenance_score_exact": None,
    "ota_share_exact": None,
    "direct_share_exact": None,
    "expected_ota_share_exact": None,
    "p25_exact": None,
    "p75_exact": None,
    "iqr_exact": None,
    "upper_fence_exact": None,
    "delta_pp_exact": None,
    "structural_condition": None,
    "rising_condition": None,
    "sample_count": 0,
    "fully_observed_count": 0,
    "approximate_count": 0,
    "candidate_period_count": 0,
    "rejected_snapshot_incomplete_count": 0,
    "rejected_snapshot_uncertain_count": 0,
    "rejected_reconciliation_count": 0,
    "rejected_low_classification_count": 0,
    "rejected_low_volume_count": 0,
    "baseline_confidence": None,
    "sample_score_exact": None,
    "provenance_score_exact": None,
    "classification_score_exact": None,
    "stability_score_exact": None,
    "confidence_cap": None,
    "target_quality": None,
    "confidence_score": Decimal("0.00"),
    "ota_room_revenue_on_books_exact": None,
    "direct_room_revenue_on_books_exact": None,
    "ota_revenue_share_exact": None,
    "comparable_periods": (),
}


def _revenue_share(ota_revenue: Decimal | None, direct_revenue: Decimal | None) -> Decimal | None:
    if ota_revenue is None or direct_revenue is None:
        return None
    total = CALCULATION_CONTEXT.add(ota_revenue, direct_revenue)
    if total <= 0:
        return None
    return percent_of(ota_revenue, total)


def evaluate_ota_dependency(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    as_of_local_date: date,
    window_start: date,
    window_end: date,
    target_window_complete: bool,
    target_any_uncertain: bool,
    target_facts: TargetFacts | None,
    select: Callable[[], ComparableSelection],
    thresholds: OtaThresholds = OTA_THRESHOLDS,
) -> OtaDependencyEvaluation:
    """`select` builds the historical comparables; it is called only when the target itself is
    fit to be judged, so an unusable target never pays for (or leaks facts about) a baseline."""

    def finish(
        status: EvaluationStatus, reasons: tuple[ReasonCode, ...], **facts: Any
    ) -> OtaDependencyEvaluation:
        values = dict(_DEFAULTS)
        values.update(facts)
        return seal(
            OtaDependencyEvaluation(
                decision_type=OtaDecisionType.REV_OTA_DEPENDENCY,
                status=status,
                workspace_id=workspace_id,
                property_id=property_id,
                booking_data_source_id=booking_data_source_id,
                as_of_local_date=as_of_local_date,
                window_start=window_start,
                window_end=window_end,
                window_days=thresholds.forward_window_days,
                thresholds=thresholds,
                reason_codes=reasons,
                **values,
            )
        )

    # 1. the target's own 30-snapshot window must exist in full
    if not target_window_complete:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.OTA_SNAPSHOT_WINDOW_INCOMPLETE,)
        )

    # 2. none of the 30 may be uncertain
    if target_any_uncertain:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.OTA_SNAPSHOT_WINDOW_UNCERTAIN,)
        )

    assert target_facts is not None
    provenance_facts = {
        "observed_day_count": target_facts.observed_day_count,
        "reconstructed_day_count": target_facts.reconstructed_day_count,
        "snapshot_provenance_score_exact": target_facts.snapshot_provenance_score_exact,
    }

    # 3. the independently reconstructed channel mix must reconcile with the stored snapshots
    if not target_facts.reconciled:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.OTA_CHANNEL_MIX_RECONCILIATION_FAILED,),
            **provenance_facts,
        )

    mix_facts = {
        **provenance_facts,
        "ota_room_nights": target_facts.ota_room_nights,
        "direct_room_nights": target_facts.direct_room_nights,
        "other_room_nights": target_facts.other_room_nights,
        "unknown_room_nights": target_facts.unknown_room_nights,
        "classified_room_nights": target_facts.classified_room_nights,
        "certain_room_nights": target_facts.certain_room_nights,
    }

    # 4. no on-books demand at all: never divide by zero
    if target_facts.certain_room_nights == 0:
        return finish(
            EvaluationStatus.NOT_APPLICABLE, (ReasonCode.OTA_NO_ON_BOOKS_DEMAND,), **mix_facts
        )

    coverage = percent_of(
        Decimal(target_facts.classified_room_nights), Decimal(target_facts.certain_room_nights)
    )
    coverage_facts = {**mix_facts, "classification_coverage_pct_exact": coverage}

    # 5. classification coverage of the target's own window
    if coverage < thresholds.min_classification_coverage:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW,),
            **coverage_facts,
        )

    # 6. low volume: too little to trust a share computed on it
    if target_facts.classified_room_nights < thresholds.min_classified_room_nights:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.OTA_BOOKING_VOLUME_LOW,),
            **coverage_facts,
        )

    ota_share = percent_of(
        Decimal(target_facts.ota_room_nights), Decimal(target_facts.classified_room_nights)
    )
    direct_share = percent_of(
        Decimal(target_facts.direct_room_nights), Decimal(target_facts.classified_room_nights)
    )
    share_facts = {
        **coverage_facts,
        "ota_share_exact": ota_share,
        "direct_share_exact": direct_share,
    }

    # 7. the historical side: at least 5 comparable periods
    selection = select()
    selection_facts = {
        "sample_count": selection.sample_count,
        "fully_observed_count": selection.fully_observed_count,
        "approximate_count": selection.approximate_count,
        "candidate_period_count": selection.candidate_period_count,
        "rejected_snapshot_incomplete_count": selection.rejected_snapshot_incomplete_count,
        "rejected_snapshot_uncertain_count": selection.rejected_snapshot_uncertain_count,
        "rejected_reconciliation_count": selection.rejected_reconciliation_count,
        "rejected_low_classification_count": selection.rejected_low_classification_count,
        "rejected_low_volume_count": selection.rejected_low_volume_count,
        "comparable_periods": selection.periods,
    }
    if selection.sample_count < thresholds.min_comparables:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.OTA_COMPARABLE_SAMPLE_INSUFFICIENT,),
            **share_facts,
            **selection_facts,
        )

    # 8. the statistics, on the FULL-PRECISION values; the display values are derived AFTER
    stats = summarize(
        [period.ota_share_exact for period in selection.periods],
        iqr_multiplier=thresholds.iqr_multiplier,
    )
    stats_facts = {
        "expected_ota_share_exact": stats.median,
        "p25_exact": stats.p25,
        "p75_exact": stats.p75,
        "iqr_exact": stats.iqr,
        "upper_fence_exact": stats.upper_fence,
    }
    delta_pp = CALCULATION_CONTEXT.subtract(ota_share, stats.median)

    structural = ota_share >= thresholds.structural_share_threshold
    rising = (
        ota_share >= thresholds.rising_min_share
        and delta_pp >= thresholds.rising_gap_pp
        and ota_share >= stats.upper_fence
    )
    numerical_trigger = structural or rising  # OR, never AND

    baseline = baseline_confidence(
        selection.periods, iqr=stats.iqr, expected_ota_share=stats.median
    )
    quality = target_quality_of(target_facts.snapshot_provenance_score_exact, coverage)
    confidence = final_confidence(baseline.score, quality)

    if numerical_trigger and confidence >= thresholds.min_confidence:
        if structural and rising:
            status = EvaluationStatus.TRIGGERED
            reasons = (ReasonCode.TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY,)
        elif structural:
            status = EvaluationStatus.TRIGGERED
            reasons = (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)
        else:
            status = EvaluationStatus.TRIGGERED
            reasons = (ReasonCode.TRIGGER_RISING_OTA_DEPENDENCY,)
    elif numerical_trigger:
        status, reasons = EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE, (ReasonCode.LOW_CONFIDENCE,)
    else:
        status, reasons = EvaluationStatus.CLEAR, (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)

    revenue_share = _revenue_share(
        target_facts.ota_room_revenue_exact, target_facts.direct_room_revenue_exact
    )

    return finish(
        status,
        reasons,
        **share_facts,
        **selection_facts,
        **stats_facts,
        delta_pp_exact=delta_pp,
        structural_condition=structural,
        rising_condition=rising,
        baseline_confidence=baseline.score,
        sample_score_exact=baseline.sample_score,
        provenance_score_exact=baseline.provenance_score,
        classification_score_exact=baseline.classification_score,
        stability_score_exact=baseline.stability_score,
        confidence_cap=baseline.cap,
        target_quality=quality,
        confidence_score=confidence,
        ota_room_revenue_on_books_exact=target_facts.ota_room_revenue_exact,
        direct_room_revenue_on_books_exact=target_facts.direct_room_revenue_exact,
        ota_revenue_share_exact=revenue_share,
    )

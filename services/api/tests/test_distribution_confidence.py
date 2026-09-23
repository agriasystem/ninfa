"""Part Q: confidence (sample/provenance/classification/stability, caps, target quality, MIN)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.intelligence.distribution.confidence import (
    baseline_confidence,
    classification_score,
    final_confidence,
    provenance_score,
    sample_score,
    stability_score,
    target_quality,
)
from app.modules.intelligence.distribution.detector import evaluate_ota_dependency
from app.modules.intelligence.distribution.metrics import TargetFacts
from app.modules.intelligence.distribution.selection import ComparableSelection
from app.modules.intelligence.distribution.types import (
    ComparablePeriodFact,
    EvaluationStatus,
    OtaDependencyEvaluation,
    ReasonCode,
)

TARGET = date(2026, 9, 5)
WINDOW_END = TARGET + timedelta(days=29)


def _period(
    i: int,
    *,
    provenance: Decimal = Decimal(100),
    coverage: Decimal = Decimal(100),
    fully_observed: bool = True,
) -> ComparablePeriodFact:
    as_of = TARGET - timedelta(weeks=i + 1)
    return ComparablePeriodFact(
        as_of_local_date=as_of,
        window_start=as_of,
        window_end=as_of + timedelta(days=29),
        observed_day_count=30 if fully_observed else 0,
        reconstructed_day_count=0 if fully_observed else 30,
        snapshot_provenance_score_exact=provenance,
        ota_room_nights=50,
        direct_room_nights=50,
        other_room_nights=0,
        unknown_room_nights=0,
        classification_coverage_pct_exact=coverage,
        ota_share_exact=Decimal(50),
    )


def test_sample_score_saturates_at_12() -> None:
    assert sample_score(12) == 100
    assert sample_score(24) == 100
    assert sample_score(6) == 50


def test_provenance_score_is_the_mean_of_the_periods_scores() -> None:
    periods = [_period(0, provenance=Decimal(100)), _period(1, provenance=Decimal(60))]
    assert provenance_score(periods) == 80


def test_classification_score_is_the_mean_of_coverage() -> None:
    periods = [_period(0, coverage=Decimal(100)), _period(1, coverage=Decimal(80))]
    assert classification_score(periods) == 90


def test_stability_score_is_100_when_iqr_is_zero() -> None:
    assert stability_score(Decimal(0), Decimal(50)) == 100


def test_stability_score_decreases_with_a_wider_iqr() -> None:
    narrow = stability_score(Decimal(5), Decimal(50))
    wide = stability_score(Decimal(20), Decimal(50))
    assert wide < narrow


def test_baseline_confidence_formula_and_no_cap_when_all_fully_observed() -> None:
    periods = [_period(i) for i in range(6)]  # 6 fully-observed, provenance=100, coverage=100
    baseline = baseline_confidence(periods, iqr=Decimal(0), expected_ota_share=Decimal(50))
    # sample=50, provenance=100, classification=100, stability=100
    # 0.35*50 + 0.25*100 + 0.20*100 + 0.20*100 = 17.5+25+20+20 = 82.5
    assert baseline.score == Decimal("82.50")
    assert baseline.cap is None


def test_baseline_confidence_caps_at_85_with_one_approximate_period() -> None:
    periods = [_period(i) for i in range(5)] + [_period(5, fully_observed=False)]
    baseline = baseline_confidence(periods, iqr=Decimal(0), expected_ota_share=Decimal(50))
    assert baseline.cap == 85
    assert baseline.score <= 85


def test_baseline_confidence_caps_at_65_with_no_fully_observed_period() -> None:
    periods = [_period(i, fully_observed=False) for i in range(6)]
    baseline = baseline_confidence(periods, iqr=Decimal(0), expected_ota_share=Decimal(50))
    assert baseline.cap == 65
    assert baseline.score <= 65


def test_target_quality_formula() -> None:
    # 0.50*90 + 0.50*70 = 45+35 = 80
    assert target_quality(Decimal(90), Decimal(70)) == Decimal("80.00")


def test_final_confidence_is_the_minimum_never_the_average() -> None:
    assert final_confidence(Decimal(90), Decimal(40)) == 40
    assert final_confidence(Decimal(40), Decimal(90)) == 40
    average_would_be = (Decimal(90) + Decimal(40)) / 2
    assert final_confidence(Decimal(90), Decimal(40)) != average_would_be


# --- the confidence GATE, through the full detector ----------------------------------------------
#
# 6 identical, flat, fully-observed historical periods (IQR=0 -> stability=100; sample=50 for
# n=6) with a chosen provenance/coverage give baseline = 37.5 + 0.25*provenance + 0.20*coverage
# exactly: provenance=69.96, coverage=0 lands it on 54.99; provenance=70, coverage=0 on 55.00.
# The target's own quality is fixed at 100 so it never binds: baseline alone decides the gate.


def _baseline_periods(provenance: Decimal, coverage: Decimal) -> tuple[ComparablePeriodFact, ...]:
    return tuple(
        ComparablePeriodFact(
            as_of_local_date=TARGET - timedelta(weeks=i + 1),
            window_start=TARGET - timedelta(weeks=i + 1),
            window_end=TARGET - timedelta(weeks=i + 1) + timedelta(days=29),
            observed_day_count=30,
            reconstructed_day_count=0,
            snapshot_provenance_score_exact=provenance,
            ota_room_nights=50,
            direct_room_nights=50,
            other_room_nights=0,
            unknown_room_nights=0,
            classification_coverage_pct_exact=coverage,
            ota_share_exact=Decimal(50),
        )
        for i in range(6)
    )


def _evaluate_with_confidence(provenance: Decimal, coverage: Decimal) -> OtaDependencyEvaluation:
    periods = _baseline_periods(provenance, coverage)
    selection = ComparableSelection(
        periods=periods,
        fully_observed_count=6,
        approximate_count=0,
        candidate_period_count=6,
        rejected_snapshot_incomplete_count=0,
        rejected_snapshot_uncertain_count=0,
        rejected_reconciliation_count=0,
        rejected_low_classification_count=0,
        rejected_low_volume_count=0,
    )
    target_facts = TargetFacts(
        reconciled=True,
        observed_day_count=30,
        reconstructed_day_count=0,
        snapshot_provenance_score_exact=Decimal(100),
        ota_room_nights=80,
        direct_room_nights=20,
        other_room_nights=0,
        unknown_room_nights=0,
        ota_room_revenue_exact=Decimal(0),
        direct_room_revenue_exact=Decimal(0),
    )
    return evaluate_ota_dependency(
        workspace_id=uuid4(),
        property_id=uuid4(),
        booking_data_source_id=uuid4(),
        as_of_local_date=TARGET,
        window_start=TARGET,
        window_end=WINDOW_END,
        target_window_complete=True,
        target_any_uncertain=False,
        target_facts=target_facts,
        select=lambda: selection,
    )


def test_confidence_54_99_with_a_numeric_anomaly_is_suppressed() -> None:
    evaluation = _evaluate_with_confidence(Decimal("69.96"), Decimal(0))
    assert evaluation.confidence_score == Decimal("54.99")
    assert evaluation.structural_condition is True  # 80% >= 70%: a real numeric candidate
    assert evaluation.status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.reason_codes == (ReasonCode.LOW_CONFIDENCE,)


def test_confidence_55_00_with_a_numeric_anomaly_triggers() -> None:
    evaluation = _evaluate_with_confidence(Decimal(70), Decimal(0))
    assert evaluation.confidence_score == Decimal("55.00")
    assert evaluation.status == EvaluationStatus.TRIGGERED


def test_low_confidence_with_no_numeric_anomaly_is_clear_not_suppressed() -> None:
    """A low confidence never manufactures a trigger, and a CLEAR outcome is never
    "suppressed" - suppression only applies to a REAL numeric candidate."""
    periods = _baseline_periods(Decimal(0), Decimal(0))  # confidence bottoms out low
    selection = ComparableSelection(
        periods=periods,
        fully_observed_count=6,
        approximate_count=0,
        candidate_period_count=6,
        rejected_snapshot_incomplete_count=0,
        rejected_snapshot_uncertain_count=0,
        rejected_reconciliation_count=0,
        rejected_low_classification_count=0,
        rejected_low_volume_count=0,
    )
    target_facts = TargetFacts(
        reconciled=True,
        observed_day_count=30,
        reconstructed_day_count=0,
        snapshot_provenance_score_exact=Decimal(100),
        ota_room_nights=50,  # 50%: neither structural nor rising vs a median of 50
        direct_room_nights=50,
        other_room_nights=0,
        unknown_room_nights=0,
        ota_room_revenue_exact=Decimal(0),
        direct_room_revenue_exact=Decimal(0),
    )
    evaluation = evaluate_ota_dependency(
        workspace_id=uuid4(),
        property_id=uuid4(),
        booking_data_source_id=uuid4(),
        as_of_local_date=TARGET,
        window_start=TARGET,
        window_end=WINDOW_END,
        target_window_complete=True,
        target_any_uncertain=False,
        target_facts=target_facts,
        select=lambda: selection,
    )
    assert evaluation.confidence_score < 55
    assert evaluation.structural_condition is False
    assert evaluation.rising_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)

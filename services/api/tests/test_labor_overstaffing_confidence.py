"""Pure unit tests of LABOR_OVERSTAFFING's statistics, confidence and cost proxy (no database).

These exercise the exact-Decimal math directly, which is far more precise for boundary testing
than reverse-engineering a database scenario that happens to hit a given score.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.intelligence.labor.confidence import (
    baseline_confidence,
    classification_score,
    final_confidence,
    provenance_score,
    sample_score,
    stability_score,
)
from app.modules.intelligence.labor.cost_proxy import (
    TargetCategoryCost,
    labor_cost_gap_proxy,
    reference_hourly_cost,
)
from app.modules.intelligence.labor.statistics import median, percentile, summarize
from app.modules.intelligence.labor.types import (
    ComparableDayFact,
    LaborBasis,
    ReferenceHourlyCostSource,
)
from app.modules.snapshots.models import SnapshotOrigin


def _day(
    hours: str,
    *,
    basis: LaborBasis = LaborBasis.ACTUAL,
    origin: SnapshotOrigin = SnapshotOrigin.OBSERVED,
    confidence: str | None = "80.00",
    cost: str | None = None,
    currency: str | None = None,
) -> ComparableDayFact:
    return ComparableDayFact(
        work_date=date(2026, 1, 1),
        historical_occupied_rooms=30,
        occupancy_origin=origin,
        booking_snapshot_id=uuid4(),
        labor_basis=basis,
        labor_snapshot_id=uuid4(),
        historical_hours_exact=Decimal(hours),
        classification_coverage_pct_exact=Decimal(100),
        weighted_category_confidence_exact=None if confidence is None else Decimal(confidence),
        category_cost_exact=None if cost is None else Decimal(cost),
        cost_currency=currency,
    )


# --- statistics -----------------------------------------------------------------------------


def test_median_of_odd_sample() -> None:
    assert median([Decimal(10), Decimal(30), Decimal(20)]) == Decimal(20)


def test_median_of_even_sample_is_the_mean_of_the_middle_two() -> None:
    assert median([Decimal(10), Decimal(20), Decimal(30), Decimal(40)]) == Decimal("25")


def test_percentile_25_and_75_by_linear_interpolation() -> None:
    values = [Decimal(v) for v in (18, 20, 22, 26, 28, 30)]
    assert percentile(values, Decimal("0.25")) == Decimal("20.5")
    assert percentile(values, Decimal("0.75")) == Decimal("27.5")


def test_no_outlier_is_ever_removed() -> None:
    values = [Decimal(v) for v in (10, 10, 10, 1000)]
    stats = summarize(values)
    assert stats.median == Decimal("10.0")  # the middle two are both 10: unaffected
    assert stats.p75 > Decimal(10)  # the outlier still pulls the upper quartile (never dropped)


def test_upper_fence_is_p75_plus_1_5_times_iqr() -> None:
    values = [Decimal(v) for v in (18, 20, 22, 26, 28, 30)]
    stats = summarize(values)
    assert stats.iqr == Decimal(7)
    assert stats.upper_fence == Decimal("38.0")


# --- confidence components -------------------------------------------------------------------


def test_sample_score_saturates_at_12_comparables() -> None:
    assert sample_score(12) == Decimal(100)
    assert sample_score(6) == Decimal(50)
    with pytest.raises(ValueError):
        sample_score(0)


def test_provenance_score_is_the_mean_of_pair_quality() -> None:
    days = [_day("8", basis=LaborBasis.ACTUAL, origin=SnapshotOrigin.OBSERVED)] * 3 + [
        _day(
            "8", basis=LaborBasis.PLANNED_FALLBACK, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
        )
    ]
    # 3 * 100 + 1 * 60 = 360 / 4 = 90
    assert provenance_score(days) == Decimal(90)


def test_provenance_score_fully_observed_is_100() -> None:
    days = [_day("8")] * 5
    assert provenance_score(days) == Decimal(100)


def test_classification_score_treats_unknown_confidence_as_zero() -> None:
    days = [_day("8", confidence="80.00"), _day("8", confidence=None)]
    assert classification_score(days) == Decimal(40)


def test_stability_score_is_100_when_iqr_is_zero() -> None:
    assert stability_score(Decimal(0), Decimal(24)) == Decimal(100)


def test_stability_score_decreases_with_a_wider_iqr() -> None:
    tight = stability_score(Decimal(2), Decimal(24))
    wide = stability_score(Decimal(20), Decimal(24))
    assert tight > wide


def test_baseline_confidence_formula_and_no_cap_when_fully_observed() -> None:
    days = [_day("24", confidence="80.00")] * 6  # ACTUAL + OBSERVED, iqr = 0
    result = baseline_confidence(days, iqr=Decimal(0), expected_hours=Decimal(24))
    # sample=6/12*100=50, provenance=100, classification=80, stability=100
    # 0.35*50 + 0.25*100 + 0.15*80 + 0.25*100 = 17.5+25+12+25 = 79.50
    assert result.score == Decimal("79.50")
    assert result.cap is None


def test_baseline_confidence_caps_at_85_with_one_approximate_day() -> None:
    days = [_day("24")] * 5 + [
        _day(
            "24", basis=LaborBasis.PLANNED_FALLBACK, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
        )
    ]
    result = baseline_confidence(days, iqr=Decimal(0), expected_hours=Decimal(24))
    assert result.cap == Decimal(85)
    assert result.score <= Decimal(85)


def test_baseline_confidence_caps_at_65_with_no_fully_observed_day() -> None:
    days = [
        _day(
            "24", basis=LaborBasis.PLANNED_FALLBACK, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
        )
    ] * 6
    result = baseline_confidence(days, iqr=Decimal(0), expected_hours=Decimal(24))
    assert result.cap == Decimal(65)
    assert result.score <= Decimal(65)


def test_final_confidence_is_the_minimum_of_the_three_never_the_average() -> None:
    assert final_confidence(Decimal(90), Decimal(100), Decimal(60)) == Decimal(60)
    assert final_confidence(Decimal(100), Decimal(100), Decimal(100)) == Decimal(100)


# --- cost proxy ------------------------------------------------------------------------------


def test_target_planned_rate_is_preferred_over_historical() -> None:
    target = TargetCategoryCost(total_planned_cost=Decimal("240.00"), currency="EUR")
    used_days = [_day("24", cost="200.00", currency="EUR")]
    rate = reference_hourly_cost(target, Decimal(24), used_days)
    assert rate is not None
    assert rate.source == ReferenceHourlyCostSource.TARGET_PLANNED_COST_RATE
    assert rate.value == Decimal(10)  # 240 / 24


def test_historical_actual_median_rate_is_the_fallback() -> None:
    target = TargetCategoryCost(total_planned_cost=None, currency=None)
    used_days = [
        _day("20", cost="200.00", currency="EUR"),  # 10/h
        _day("20", cost="300.00", currency="EUR"),  # 15/h
        _day("20", cost="400.00", currency="EUR"),  # 20/h
    ]
    rate = reference_hourly_cost(target, Decimal(24), used_days)
    assert rate is not None
    assert rate.source == ReferenceHourlyCostSource.HISTORICAL_ACTUAL_MEDIAN_RATE
    assert rate.value == Decimal(15)


def test_inconsistent_currency_makes_the_proxy_null() -> None:
    target = TargetCategoryCost(total_planned_cost=None, currency=None)
    used_days = [
        _day("20", cost="200.00", currency="EUR"),
        _day("20", cost="300.00", currency="USD"),
    ]
    assert reference_hourly_cost(target, Decimal(24), used_days) is None


def test_missing_cost_data_makes_the_proxy_null_but_detector_still_works() -> None:
    target = TargetCategoryCost(total_planned_cost=None, currency=None)
    assert reference_hourly_cost(target, Decimal(24), [_day("20")]) is None


def test_planned_basis_days_never_feed_the_historical_actual_rate() -> None:
    target = TargetCategoryCost(total_planned_cost=None, currency=None)
    used_days = [_day("20", basis=LaborBasis.PLANNED_FALLBACK, cost="200.00", currency="EUR")]
    assert reference_hourly_cost(target, Decimal(24), used_days) is None


def test_labor_cost_gap_proxy_is_excess_times_rate_half_up() -> None:
    assert labor_cost_gap_proxy(Decimal(8), Decimal("12.345")) == Decimal("98.76")

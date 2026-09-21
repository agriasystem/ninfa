"""Calendar months, precision, statistics and confidence of Cost CPOR V1 (Gate 7, pure).

Groups F (month distance), H (statistics), L (confidence components) and the parts of E and Q that
do not need a database. No clock, no float, no database.
"""

from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from app.modules.intelligence.costs.confidence import (
    CAP_WITH_APPROXIMATE_PERIOD,
    CAP_WITHOUT_OBSERVED_PERIOD,
    baseline_confidence,
    classification_score,
    final_confidence,
    provenance_score,
    sample_score,
    stability_score,
    target_quality,
)
from app.modules.intelligence.costs.periods import CalendarMonth, circular_month_distance
from app.modules.intelligence.costs.precision import (
    canonical_text,
    display_text,
    exact_sum,
    for_display,
    percent_of,
)
from app.modules.intelligence.costs.statistics import median, percentile, summarize
from app.modules.intelligence.costs.types import ComparablePeriodFact
from tests.cost_support import (
    COMPARABLE_MONTHS,
    Ledger,
    cpor_history,
    month,
)

D = Decimal


# --- the calendar month ---------------------------------------------------------------------------


def test_a_month_knows_its_first_and_last_day_and_its_length() -> None:
    assert (month(2026, 8).start, month(2026, 8).end, month(2026, 8).days) == (
        date(2026, 8, 1),
        date(2026, 8, 31),
        31,
    )
    assert month(2026, 4).end == date(2026, 4, 30)
    assert month(2024, 2).days == 29 and month(2026, 2).days == 28  # leap year


def test_month_arithmetic_crosses_years_in_both_directions() -> None:
    assert month(2026, 1).shifted(-1) == month(2025, 12)
    assert month(2026, 12).shifted(1) == month(2027, 1)
    assert month(2026, 8).shifted(-36) == month(2023, 8)
    assert month(2026, 8).months_before(month(2026, 10)) == 2
    assert month(2026, 8).months_before(month(2026, 6)) == -2
    assert CalendarMonth.of(date(2026, 3, 17)) == month(2026, 3)


@pytest.mark.parametrize("year, number", [(2026, 0), (2026, 13), (0, 5), (10000, 1)])
def test_an_impossible_month_is_refused(year: int, number: int) -> None:
    with pytest.raises(ValueError):
        CalendarMonth(year, number)


def test_a_month_is_not_built_from_booleans_or_floats() -> None:
    with pytest.raises(ValueError):
        CalendarMonth(True, 5)
    with pytest.raises(ValueError):
        CalendarMonth(2026, 5.0)  # type: ignore[arg-type]


def test_the_days_of_a_month_are_all_of_them_in_order() -> None:
    days = month(2026, 2).day_list()
    assert len(days) == 28 and days[0] == date(2026, 2, 1) and days[-1] == date(2026, 2, 28)
    assert days == sorted(days)


@pytest.mark.parametrize(
    ("first", "second", "distance"),
    [(7, 7, 0), (7, 8, 1), (7, 5, 2), (7, 4, 3), (7, 10, 3), (12, 1, 1), (1, 12, 1), (1, 3, 2)]
    + [(12, 2, 2), (1, 4, 3), (2, 12, 2), (6, 12, 6)],
)
def test_the_seasonal_distance_is_circular(first: int, second: int, distance: int) -> None:
    assert (
        circular_month_distance(first, second) == distance == circular_month_distance(second, first)
    )


# --- precision ------------------------------------------------------------------------------------


def test_quotients_are_full_precision_and_display_is_two_decimals_half_up() -> None:
    third = D(10) / D(3)
    assert for_display(third) == D("3.33") and display_text(third) == "3.33"
    assert for_display(D("2.675")) == D("2.68") and for_display(D("-2.675")) == D("-2.68")
    assert for_display(D("2.674999")) == D("2.67")
    assert percent_of(D(1), D(3)) == D("33.333333333333333333333333333333333333333333333333")


def test_a_process_wide_decimal_context_cannot_change_a_result() -> None:
    values = [D("1.1"), D("2.3"), D("3.7"), D("4.9"), D("5.13")]
    reference = (
        summarize(values),
        percent_of(D(1), D(3)),
        for_display(D("2.675")),
        exact_sum(values),
        canonical_text(D("10.00")),
    )
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        assert (
            summarize(values),
            percent_of(D(1), D(3)),
            for_display(D("2.675")),
            exact_sum(values),
            canonical_text(D("10.00")),
        ) == reference


def test_canonical_text_is_non_lossy_and_normalised() -> None:
    assert (
        canonical_text(D("10.00")) == canonical_text(D("10")) == canonical_text(D("1E+1")) == "10"
    )
    assert canonical_text(D("-0.00")) == "0" and canonical_text(None) is None
    assert canonical_text(D("19.99999999999999999")) != canonical_text(D("20"))  # no digit dropped


def test_the_display_of_a_value_is_not_a_decision_value() -> None:
    almost = D("19.999999")
    assert for_display(almost) == D("20.00") and almost < D(20)  # displays 20, is not 20


# --- H. statistics --------------------------------------------------------------------------------


def test_the_median_of_an_odd_sample_is_the_middle_value() -> None:
    assert median([D(5), D(1), D(3)]) == D(3)
    assert median([D(7)]) == D(7)


def test_the_median_of_an_even_sample_is_the_mean_of_the_two_middle_values() -> None:
    assert median([D(1), D(2), D(3), D(4)]) == D("2.5")
    assert median([D("1.10"), D("2.30")]) == D("1.70")


def test_p25_and_p75_interpolate_at_n_minus_one_times_p() -> None:
    values = [D(v) for v in (10, 20, 30, 40, 50)]  # n = 5: positions 1 and 3
    assert percentile(values, D("0.25")) == D(20) and percentile(values, D("0.75")) == D(40)
    even = [D(v) for v in (10, 20, 30, 40)]  # n = 4: positions 0.75 and 2.25
    assert percentile(even, D("0.25")) == D("17.5") and percentile(even, D("0.75")) == D("32.5")


def test_the_iqr_and_the_upper_fence_follow_from_the_quartiles() -> None:
    stats = summarize([D(v) for v in (8, 9, 10, 11, 12)])
    assert (stats.median, stats.p25, stats.p75, stats.iqr) == (D(10), D(9), D(11), D(2))
    assert stats.upper_fence == D(14)  # 11 + 1.5 * 2


def test_statistics_are_full_precision_never_rounded_to_two_decimals() -> None:
    stats = summarize([D("0.001"), D("0.002"), D("0.003"), D("0.004"), D("0.0051")])
    assert stats.median == D("0.003") and stats.p75 == D("0.004")
    assert stats.upper_fence == D("0.004") + D("1.5") * (D("0.004") - D("0.002"))
    thirds = [D(1) / D(3), D(2) / D(3), D(1), D(4) / D(3), D(5) / D(3)]
    assert summarize(thirds).median == D(1)
    assert summarize(thirds).p25 == D(2) / D(3)  # not 0.67


def test_no_outlier_is_removed() -> None:
    with_outlier = summarize([D(v) for v in (1, 1, 1, 1, 1000)])
    assert with_outlier.p75 == D(1) and with_outlier.median == D(1)
    assert percentile([D(1), D(1), D(1), D(1), D(1000)], D(1)) == D(1000)  # still in the sample


def test_negative_and_zero_values_are_ordinary_values() -> None:
    stats = summarize([D(-4), D(-2), D(0), D(2), D(4)])
    assert (stats.median, stats.p25, stats.p75, stats.iqr, stats.upper_fence) == (
        D(0),
        D(-2),
        D(2),
        D(4),
        D(8),
    )
    assert summarize([D(0)] * 5).upper_fence == D(0)


def test_an_empty_sample_and_a_bad_percentile_are_refused() -> None:
    with pytest.raises(ValueError):
        median([])
    with pytest.raises(ValueError):
        percentile([], D("0.5"))
    with pytest.raises(ValueError):
        percentile([D(1)], D("1.5"))


def test_the_statistics_do_not_depend_on_the_order_of_the_sample() -> None:
    values = [D(v) for v in (5, 1, 9, 3, 7, 2)]
    assert summarize(values) == summarize(sorted(values)) == summarize(list(reversed(values)))


# --- L. confidence components ---------------------------------------------------------------------


def facts_for(
    values: list[str],
    *,
    reconstructed_days: int = 0,
    confidence: str = "80",
) -> tuple[list[ComparablePeriodFact], Ledger]:
    months = COMPARABLE_MONTHS[: len(values)]
    ledger = cpor_history(
        dict(zip(months, values, strict=True)),
        reconstructed_days=reconstructed_days,
        confidence=confidence,
    )
    return [ComparablePeriodFact.of(ledger.metric(m)) for m in months], ledger


def test_the_sample_score_saturates_at_eight_months() -> None:
    assert sample_score(5) == D("62.5") and sample_score(8) == D(100) and sample_score(12) == D(100)
    assert sample_score(1) == D("12.5")
    with pytest.raises(ValueError):
        sample_score(0)


def test_the_provenance_score_is_the_mean_of_the_months() -> None:
    facts, _ = facts_for(["1", "1", "1", "1"])
    assert provenance_score(facts) == D(100)
    half, _ = facts_for(["1", "1"], reconstructed_days=31)
    assert provenance_score(half) == D(60)
    mixed = [*facts[:2], *half]
    assert provenance_score(mixed) == D(80)  # (100 + 100 + 60 + 60) / 4


def test_the_classification_score_is_weighted_by_absolute_category_cost() -> None:
    facts, _ = facts_for(["1", "1"])
    heavy = [
        replace(
            facts[0],
            weighted_classification_confidence_exact=D(100),
            absolute_category_cost=D(900),
        ),
        replace(
            facts[1],
            weighted_classification_confidence_exact=D(50),
            absolute_category_cost=D(100),
        ),
    ]
    assert classification_score(heavy) == D(95)  # (100*900 + 50*100) / 1000, not the mean 75


def test_a_zero_total_weight_falls_back_to_the_plain_mean() -> None:
    facts, _ = facts_for(["1", "1"])
    zero = [
        replace(f, weighted_classification_confidence_exact=D(c), absolute_category_cost=D(0))
        for f, c in zip(facts, (100, 50), strict=True)
    ]
    assert classification_score(zero) == D(75)


def test_the_stability_score_penalises_dispersion_and_never_goes_below_zero() -> None:
    assert stability_score(D(0), D(10)) == D(100)
    assert stability_score(D(2), D(10)) == D(90)  # 100 - 50 * 0.2
    assert stability_score(D(20), D(10)) == D(0)  # 100 - 50 * 2 -> floored at 0
    assert stability_score(D(100), D(10)) == D(0)


def test_the_stability_denominator_is_floored_and_uses_the_absolute_expected() -> None:
    assert stability_score(D("0.005"), D(0)) == D(75)  # 100 - 50 * (0.005 / 0.01)
    assert stability_score(D(2), D(-10)) == D(90)  # |expected|


def test_baseline_confidence_follows_the_versioned_formula() -> None:
    facts, _ = facts_for(["10"] * 8)  # observed, classified at 80, IQR 0
    stats = summarize([f.cpor_exact for f in facts])

    result = baseline_confidence(facts, stats)

    # 0.35 * 100 + 0.25 * 100 + 0.20 * 80 + 0.20 * 100 = 96
    assert result.score == D("96.00") and result.cap is None
    assert (result.sample_score, result.provenance_score) == (D(100), D(100))
    assert (result.classification_score, result.stability_score) == (D(80), D(100))


def test_a_reconstructed_month_caps_the_baseline_at_85() -> None:
    observed, _ = facts_for(["10"] * 4)
    approximate, _ = facts_for(["10"] * 4, reconstructed_days=5)
    facts = [*observed, *approximate]

    result = baseline_confidence(facts, summarize([f.cpor_exact for f in facts]))

    assert result.cap == CAP_WITH_APPROXIMATE_PERIOD == D(85)
    assert result.score == D("85.00")  # the formula alone gives more


def test_no_fully_observed_month_caps_the_baseline_at_65() -> None:
    facts, _ = facts_for(["10"] * 8, reconstructed_days=31)

    result = baseline_confidence(facts, summarize([f.cpor_exact for f in facts]))

    assert result.cap == CAP_WITHOUT_OBSERVED_PERIOD == D(65)
    assert result.score == D("65.00")  # the formula alone gives 86.00


def test_the_baseline_confidence_is_rounded_half_up_to_two_decimals() -> None:
    facts, _ = facts_for(["10", "10", "10", "10", "10"], confidence="33.33")
    result = baseline_confidence(facts, summarize([f.cpor_exact for f in facts]))
    # 0.35 * 62.5 + 25 + 0.20 * 33.33 + 20 = 21.875 + 25 + 6.666 + 20 = 73.541
    assert result.score == D("73.54")


def test_the_target_quality_is_half_provenance_and_half_classification() -> None:
    ledger = cpor_history({month(2026, 8): "10"})
    assert target_quality(ledger.metric(month(2026, 8))) == D("90.00")  # 0.5 * 100 + 0.5 * 80

    reconstructed = cpor_history({month(2026, 8): "10"}, reconstructed_days=31)
    assert target_quality(reconstructed.metric(month(2026, 8))) == D("70.00")  # 0.5 * 60 + 0.5 * 80


def test_the_target_quality_rounds_half_up() -> None:
    ledger = cpor_history({month(2026, 8): "10"}, confidence="9.99")
    assert target_quality(ledger.metric(month(2026, 8))) == D("55.00")  # 54.995, half up


def test_the_final_confidence_is_the_minimum_never_the_average() -> None:
    assert final_confidence(D("96.00"), D("54.99")) == D("54.99")
    assert final_confidence(D("60.00"), D("90.00")) == D("60.00")
    assert final_confidence(D("70.00"), D("70.00")) == D("70.00")

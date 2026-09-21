"""Curve-pattern statistics and confidence (Gate 5, groups C and D). Pure, no database."""

import random
from decimal import Decimal

import pytest

from app.modules.intelligence.expected.statistics import Statistics
from app.modules.intelligence.expected.statistics import summarize as expected_summarize
from app.modules.intelligence.revenue.confidence import (
    CAP_WITH_APPROXIMATE_PAIR,
    CAP_WITHOUT_OBSERVED_PAIR,
    final_confidence,
    pattern_confidence,
    provenance_score,
    sample_score,
    stability_score,
)
from app.modules.intelligence.revenue.statistics import delta_statistics, other_rooms_median
from app.modules.intelligence.revenue.types import PATTERN_VERSION, RULES_VERSION
from tests.revenue_support import pickup_selection, remaining_selection

D = Decimal


def _stats(*deltas: int) -> Statistics:
    return delta_statistics(pickup_selection(list(deltas)).pairs)


# --- C: statistics ---------------------------------------------------------------------------


def test_median_of_an_odd_and_an_even_sample() -> None:
    assert _stats(3, 1, 2).expected == D("2.00")
    assert _stats(1, 2, 3, 4).expected == D("2.50")


def test_percentiles_use_linear_interpolation_at_n_minus_one_times_p() -> None:
    stats = _stats(2, 4, 6, 8, 10, 12)
    assert stats.expected == D("7.00")
    assert stats.lower == D("4.50")  # position 1.25 -> 4 + 0.25 * 2
    assert stats.upper == D("9.50")  # position 3.75 -> 8 + 0.75 * 2
    assert stats.iqr == D("5.00")


def test_iqr_is_p75_minus_p25() -> None:
    stats = _stats(1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert stats.iqr == stats.upper - stats.lower == D("4.00")


def test_the_algorithms_are_those_of_the_expected_engine() -> None:
    values = [5, -3, 0, 12, 7, 7, 1, 9]
    assert delta_statistics(pickup_selection(values).pairs) == expected_summarize(values)


def test_negative_and_zero_deltas_are_handled() -> None:
    assert _stats(-4, -2, 0, 2, 4).expected == D("0.00")
    negative = _stats(-6, -5, -4, -3, -2)
    assert negative.expected == D("-4.00")
    assert negative.lower == D("-5.00")
    assert negative.upper == D("-3.00")
    assert _stats(0, 0, 0, 0, 0).iqr == D("0.00")


def test_no_outlier_is_removed() -> None:
    stats = _stats(2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 500)
    assert stats.expected == D("2.00")  # robust because of the median, not because of trimming
    assert stats.upper == D("2.00")
    # ... yet the outlier is still part of the sample and of its interpolation
    assert _stats(2, 2, 2, 2, 500).upper == D("2.00")
    assert _stats(2, 2, 2, 500, 500).upper == D("500.00")


def test_statistics_do_not_depend_on_the_input_order() -> None:
    values = [3, 9, -1, 4, 4, 8, 0, 2, 6, 5, 7, 1]
    expected = _stats(*values)
    for seed in range(6):
        shuffled = values[:]
        random.Random(seed).shuffle(shuffled)
        assert _stats(*shuffled) == expected


def test_statistics_are_exact_decimals_never_floats() -> None:
    stats = _stats(1, 2, 4, 8, 16)
    for value in (stats.expected, stats.lower, stats.upper, stats.iqr):
        assert isinstance(value, Decimal)
        assert value == value.quantize(D("0.01"))


def test_the_median_of_the_final_rooms_uses_the_same_pairs() -> None:
    selection = remaining_selection([2, 4, 6], [10, 20, 30])
    assert other_rooms_median(selection.pairs) == D("20.00")
    assert delta_statistics(selection.pairs).expected == D("4.00")


# --- D: pattern confidence -------------------------------------------------------------------


def test_sample_score_saturates_at_twelve_pairs() -> None:
    assert sample_score(12) == D(100)
    assert sample_score(24) == D(100)
    assert sample_score(6) == D(50)
    assert sample_score(5).quantize(D("0.01")) == D("41.67")
    with pytest.raises(ValueError):
        sample_score(0)


def test_provenance_score_weights_observed_100_and_approximate_60() -> None:
    assert provenance_score(5, 0) == D(100)
    assert provenance_score(0, 5) == D(60)
    assert provenance_score(3, 2) == D(84)
    with pytest.raises(ValueError):
        provenance_score(0, 0)


def test_stability_score_is_100_for_a_zero_iqr_and_falls_with_the_relative_iqr() -> None:
    assert stability_score(D("0.00"), D("10.00")) == D(100)
    assert stability_score(D("5.00"), D("10.00")) == D(75)  # relative IQR 0.5
    assert stability_score(D("20.00"), D("10.00")) == D(0)  # relative IQR 2, floored at 0
    assert stability_score(D("40.00"), D("10.00")) == D(0)


def test_stability_uses_the_absolute_value_of_a_negative_median() -> None:
    assert stability_score(D("2.00"), D("-4.00")) == stability_score(D("2.00"), D("4.00")) == D(75)
    # a naive max(median, 1) would divide by 1 here and floor the stability at 0
    assert stability_score(D("2.00"), D("-4.00")) > 0


def test_stability_of_a_zero_median_divides_by_one_not_by_zero() -> None:
    assert stability_score(D("0.50"), D("0.00")) == D(75)
    assert stability_score(D("0.00"), D("0.00")) == D(100)


def test_pattern_confidence_combines_sample_provenance_and_stability() -> None:
    perfect = pattern_confidence(12, 0, D("0.00"), D("10.00"))
    assert perfect.score == D("100.00")
    assert (perfect.sample_score, perfect.provenance_score, perfect.stability_score) == (
        D(100),
        D(100),
        D(100),
    )
    # 5 observed pairs, zero IQR: 0.40 * 41.667 + 0.35 * 100 + 0.25 * 100 = 76.67
    assert pattern_confidence(5, 0, D("0.00"), D("10.00")).score == D("76.67")
    # 8 observed, IQR 2 over a median of 8: 0.4*66.667 + 0.35*100 + 0.25*87.5 = 83.54
    assert pattern_confidence(8, 0, D("2.00"), D("8.00")).score == D("83.54")


def test_the_score_is_rounded_half_up_once_at_the_end() -> None:
    # the raw score is exactly 99.985: HALF_UP gives 99.99 (banker's rounding would give 99.98)
    assert pattern_confidence(12, 0, D("0.75"), D("625")).score == D("99.99")


def test_an_approximate_pair_caps_the_confidence_at_85() -> None:
    # 11 observed + 1 approximate would score 98.83 without the cap
    capped = pattern_confidence(11, 1, D("0.00"), D("10.00"))
    assert capped.score == CAP_WITH_APPROXIMATE_PAIR == D(85)


def test_no_observed_pair_caps_the_confidence_at_65() -> None:
    # 12 approximate pairs would score 86.00 (capped to 85, then to 65)
    capped = pattern_confidence(0, 12, D("0.00"), D("10.00"))
    assert capped.score == CAP_WITHOUT_OBSERVED_PAIR == D(65)


def test_a_low_score_is_not_raised_by_a_cap() -> None:
    low = pattern_confidence(0, 5, D("30.00"), D("10.00"))
    assert low.score < CAP_WITHOUT_OBSERVED_PAIR
    assert low.score >= 0


def test_the_confidence_stays_between_0_and_100() -> None:
    for observed in (0, 3, 12, 24):
        for approximate in (0, 4, 30):
            if observed + approximate == 0:
                continue
            for iqr in (D(0), D("3.00"), D("900.00")):
                score = pattern_confidence(observed, approximate, iqr, D("2.00")).score
                assert D(0) <= score <= D(100)


def test_the_final_confidence_is_the_minimum_never_the_average() -> None:
    assert final_confidence(D("80.00"), D("60.00")) == D("60.00")
    assert final_confidence(D("60.00"), D("80.00")) == D("60.00")
    assert final_confidence(D("70.00"), D("70.00")) == D("70.00")
    assert final_confidence(D("100.00"), D("0.01")) == D("0.01")


def test_the_rules_and_pattern_are_versioned_independently_of_the_application() -> None:
    assert RULES_VERSION == "revenue-decisions-v1"
    assert PATTERN_VERSION == "revenue-curve-pattern-v1"

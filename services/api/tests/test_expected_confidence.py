"""Baseline confidence V1: sample, provenance, stability, caps and bands (pure `Decimal`).

The formula is a versioned heuristic (see ADR 0010), so the numbers here are pinned exactly.
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.modules.intelligence.expected.confidence import (
    ConfidenceBand,
    band_for,
    confidence,
    provenance_score,
    sample_score,
    stability_score,
)

TWO = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


# --- H. sample score --------------------------------------------------------------------------


def test_the_sample_score_of_5_comparables() -> None:
    assert cents(sample_score(5)) == Decimal("41.67")


@pytest.mark.parametrize(
    ("n", "expected"), [(6, "50.00"), (9, "75.00"), (12, "100.00"), (1, "8.33")]
)
def test_the_sample_score_is_linear_up_to_12(n: int, expected: str) -> None:
    assert cents(sample_score(n)) == Decimal(expected)


def test_the_sample_score_of_12_or_more_is_capped_at_100() -> None:
    assert sample_score(12) == Decimal(100)
    assert sample_score(13) == sample_score(24) == sample_score(500) == Decimal(100)


def test_the_sample_score_needs_a_sample() -> None:
    with pytest.raises(ValueError):
        sample_score(0)


# --- H. provenance score ----------------------------------------------------------------------


def test_an_observed_only_baseline_has_provenance_100() -> None:
    assert provenance_score(7, 0) == Decimal(100)


def test_a_reconstructed_only_baseline_has_provenance_60() -> None:
    assert provenance_score(0, 6) == Decimal(60)


def test_a_mixed_baseline_weighs_each_origin() -> None:
    assert provenance_score(3, 2) == Decimal(84)  # (300 + 120) / 5
    assert provenance_score(4, 1) == Decimal(92)  # (400 + 60) / 5
    assert provenance_score(1, 1) == Decimal(80)


# --- H. stability score -----------------------------------------------------------------------


def test_no_dispersion_is_a_perfect_stability() -> None:
    assert stability_score(Decimal("0.00"), Decimal("12.00")) == Decimal(100)


def test_an_iqr_equal_to_the_expected_scores_50() -> None:
    assert stability_score(Decimal("10.00"), Decimal("10.00")) == Decimal(50)


def test_an_iqr_twice_the_expected_scores_0() -> None:
    assert stability_score(Decimal("20.00"), Decimal("10.00")) == Decimal(0)


def test_stability_never_goes_below_0_nor_above_100() -> None:
    assert stability_score(Decimal("300.00"), Decimal("10.00")) == Decimal(0)
    assert stability_score(Decimal("0.00"), Decimal("0.00")) == Decimal(100)
    assert Decimal(0) <= stability_score(Decimal("7.25"), Decimal("3.00")) <= Decimal(100)


def test_an_expected_below_one_is_treated_as_one_in_the_relative_iqr() -> None:
    """max(expected, 1): an expected of 0.50 does not inflate the relative dispersion."""
    assert stability_score(Decimal("1.00"), Decimal("0.50")) == Decimal(50)  # IQR / 1
    assert stability_score(Decimal("1.00"), Decimal("0.00")) == Decimal(50)


# --- H. the weighted formula, rounding, caps --------------------------------------------------


def test_the_final_score_is_the_weighted_sum_of_the_three_components() -> None:
    # 5 observed, IQR 0: 0.40 * 41.666.. + 0.35 * 100 + 0.25 * 100 = 76.666..
    result = confidence(5, 0, Decimal("0.00"), Decimal("12.00"))

    assert result.score == Decimal("76.67")
    assert cents(result.sample_score) == Decimal("41.67")
    assert (result.provenance_score, result.stability_score) == (Decimal(100), Decimal(100))


def test_a_full_observed_stable_baseline_scores_100() -> None:
    assert confidence(12, 0, Decimal("0.00"), Decimal("20.00")).score == Decimal("100.00")


def test_the_final_score_is_rounded_half_up_to_two_decimals() -> None:
    """raw = 79.945 exactly: HALF_UP gives 79.95 (banker's rounding would give 79.94)."""
    # 6 observed: 0.40*50 + 0.35*100 + 0.25*(100 - 50*0.0044) = 20 + 35 + 24.945
    result = confidence(6, 0, Decimal("0.044"), Decimal("10"))

    assert result.score == Decimal("79.95")
    assert result.score.as_tuple().exponent == -2


def test_a_reconstructed_comparable_caps_the_score_at_85() -> None:
    # 6 observed + 6 reconstructed, IQR 0: 40 + 0.35 * 80 + 25 = 93 -> capped
    result = confidence(6, 6, Decimal("0.00"), Decimal("10.00"))

    assert result.score == Decimal("85.00")
    assert result.band == ConfidenceBand.HIGH


def test_a_baseline_without_any_observed_comparable_is_capped_at_65() -> None:
    # 12 reconstructed, IQR 0: 40 + 0.35 * 60 + 25 = 86 -> capped by 85 and then by 65
    result = confidence(0, 12, Decimal("0.00"), Decimal("10.00"))

    assert result.score == Decimal("65.00")
    assert result.band == ConfidenceBand.MEDIUM


def test_the_caps_do_not_touch_a_score_that_is_already_lower() -> None:
    # 2 observed + 3 reconstructed, IQR 0: 16.67 + 0.35 * 76 + 25 = 68.27, below both caps
    assert confidence(2, 3, Decimal("0.00"), Decimal("10.00")).score == Decimal("68.27")
    # 5 reconstructed only: 16.67 + 21 + 25 = 62.67, below 65
    assert confidence(0, 5, Decimal("0.00"), Decimal("10.00")).score == Decimal("62.67")


def test_observed_only_baselines_are_not_capped() -> None:
    assert confidence(24, 0, Decimal("0.00"), Decimal("30.00")).score == Decimal("100.00")


# --- H. bands ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "band"),
    [
        ("100.00", ConfidenceBand.HIGH),
        ("80.00", ConfidenceBand.HIGH),
        ("79.99", ConfidenceBand.MEDIUM),
        ("60.00", ConfidenceBand.MEDIUM),
        ("59.99", ConfidenceBand.LOW),
        ("0.00", ConfidenceBand.LOW),
    ],
)
def test_the_band_thresholds(score: str, band: ConfidenceBand) -> None:
    assert band_for(Decimal(score)) == band


def test_a_ready_baseline_can_be_low_confidence() -> None:
    # 5 observed, IQR twice the expected: 16.67 + 35 + 0 = 51.67
    result = confidence(5, 0, Decimal("20.00"), Decimal("10.00"))

    assert result.score == Decimal("51.67")
    assert result.band == ConfidenceBand.LOW


def test_every_confidence_value_is_a_decimal() -> None:
    result = confidence(7, 2, Decimal("3.25"), Decimal("11.50"))

    for value in (
        result.score,
        result.sample_score,
        result.provenance_score,
        result.stability_score,
    ):
        assert isinstance(value, Decimal)

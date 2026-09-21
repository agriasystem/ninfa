"""Median, P25/P75 (linear interpolation) and IQR of a comparable sample: exact `Decimal`.

Pure functions, no database, no float anywhere.
"""

import ast
from decimal import Decimal
from pathlib import Path

import pytest

import app.modules.intelligence.expected as expected_package
from app.modules.intelligence.expected.statistics import (
    P25,
    P75,
    Statistics,
    median,
    percentile,
    summarize,
)

# --- F. median --------------------------------------------------------------------------------


def test_the_median_of_an_odd_sample_is_the_middle_value() -> None:
    assert median([3, 1, 2]) == Decimal("2.00")
    assert median([9, 1, 7, 3, 5]) == Decimal("5.00")


def test_the_median_of_an_even_sample_is_the_decimal_mean_of_the_two_middle_values() -> None:
    assert median([10, 12, 14, 16]) == Decimal("13.00")
    assert median([16, 10, 14, 12]) == Decimal("13.00")  # order of the input does not matter


def test_the_median_can_be_fractional_and_is_never_rounded_to_an_integer() -> None:
    assert median([10, 11]) == Decimal("10.50")
    assert str(median([10, 11])) == "10.50"
    assert median([0, 1]) == Decimal("0.50")


def test_a_single_value_is_its_own_median() -> None:
    assert median([7]) == Decimal("7.00")


# --- F. percentiles at n = 5, 6, 7, 8 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "p25", "p75", "iqr"),
    [
        (5, "2.00", "4.00", "2.00"),  # positions 1.00 and 3.00
        (6, "2.25", "4.75", "2.50"),  # positions 1.25 and 3.75
        (7, "2.50", "5.50", "3.00"),  # positions 1.50 and 4.50
        (8, "2.75", "6.25", "3.50"),  # positions 1.75 and 5.25
    ],
)
def test_linear_interpolation_percentiles_of_1_to_n(n: int, p25: str, p75: str, iqr: str) -> None:
    values = list(range(1, n + 1))

    stats = summarize(values)

    assert percentile(values, P25) == Decimal(p25)
    assert percentile(values, P75) == Decimal(p75)
    assert (stats.lower, stats.upper, stats.iqr) == (Decimal(p25), Decimal(p75), Decimal(iqr))


def test_percentiles_do_not_depend_on_the_order_of_the_input() -> None:
    assert summarize([8, 2, 6, 4, 1, 7, 3, 5]) == summarize([1, 2, 3, 4, 5, 6, 7, 8])


def test_a_percentile_interpolates_between_uneven_neighbours() -> None:
    # n=6: position 1.25 between 2 and 10 -> 2 + 0.25 * 8 = 4 ; position 3.75 between 12 and 20
    values = [0, 2, 10, 12, 20, 30]

    assert percentile(values, P25) == Decimal("4.00")
    assert percentile(values, P75) == Decimal("18.00")


# --- F. duplicates, zeros ---------------------------------------------------------------------


def test_a_sample_with_duplicates_keeps_every_copy() -> None:
    stats = summarize([1, 1, 1, 9, 9, 9])

    assert stats == Statistics(
        expected=Decimal("5.00"), lower=Decimal("1.00"), upper=Decimal("9.00"), iqr=Decimal("8.00")
    )


def test_a_constant_sample_has_zero_dispersion() -> None:
    stats = summarize([12, 12, 12, 12, 12])

    assert (stats.expected, stats.lower, stats.upper, stats.iqr) == (
        Decimal("12.00"),
        Decimal("12.00"),
        Decimal("12.00"),
        Decimal("0.00"),
    )


def test_zero_rooms_are_real_values_of_the_sample() -> None:
    stats = summarize([0, 0, 1, 2, 3])

    assert stats.expected == Decimal("1.00")
    assert (stats.lower, stats.upper, stats.iqr) == (
        Decimal("0.00"),
        Decimal("2.00"),
        Decimal("2.00"),
    )
    assert summarize([0, 0, 0, 0, 0]).expected == Decimal("0.00")


def test_the_iqr_is_the_upper_quartile_minus_the_lower_one() -> None:
    for values in ([3, 5, 8, 13, 21], [2, 4, 4, 6, 9, 15], [1, 3, 3, 3, 40, 41, 50]):
        stats = summarize(values)
        assert stats.iqr == stats.upper - stats.lower


def test_the_range_brackets_the_median() -> None:
    for values in ([3, 5, 8, 13, 21], [0, 0, 0, 0, 30], [1, 2, 2, 2, 2, 50], list(range(24))):
        stats = summarize(values)
        assert stats.lower <= stats.expected <= stats.upper


def test_an_outlier_moves_neither_the_median_nor_the_quartiles_much() -> None:
    """The robustness is the statistic itself: no outlier is removed."""
    normal = summarize([10, 11, 12, 13, 14])
    with_group = summarize([10, 11, 12, 13, 400])  # one huge group booking

    assert normal.expected == with_group.expected == Decimal("12.00")
    assert with_group.lower == normal.lower and with_group.upper == Decimal("13.00")


def test_empty_samples_and_bad_percentiles_are_refused() -> None:
    with pytest.raises(ValueError):
        median([])
    with pytest.raises(ValueError):
        percentile([], P25)
    with pytest.raises(ValueError):
        percentile([1, 2, 3], Decimal("1.5"))


# --- F. no float ------------------------------------------------------------------------------


def test_every_statistic_is_a_decimal_with_two_places() -> None:
    stats = summarize([1, 2, 4, 8, 16, 32])

    for value in (stats.expected, stats.lower, stats.upper, stats.iqr):
        assert isinstance(value, Decimal)
        assert value.as_tuple().exponent == -2


def test_no_float_is_used_anywhere_in_the_expected_engine() -> None:
    package_dir = Path(expected_package.__file__).parent
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        floats = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "float"]
        literals = [
            n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)
        ]
        assert floats == [] and literals == [], source.name

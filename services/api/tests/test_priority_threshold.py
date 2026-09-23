"""`threshold_progress`: the shared 0->50->100 shape behind every Impact Score V1 (spec part B)."""

from decimal import Decimal

import pytest

from app.modules.intelligence.priority.impact import threshold_progress


def test_value_at_or_below_zero_is_zero() -> None:
    assert threshold_progress(Decimal(0), Decimal(20), Decimal(40)) == Decimal(0)


def test_value_at_threshold_is_fifty() -> None:
    assert threshold_progress(Decimal(20), Decimal(20), Decimal(40)) == Decimal(50)


def test_value_at_saturation_is_a_hundred() -> None:
    assert threshold_progress(Decimal(40), Decimal(20), Decimal(40)) == Decimal(100)


def test_value_above_saturation_is_still_a_hundred() -> None:
    assert threshold_progress(Decimal(1000), Decimal(20), Decimal(40)) == Decimal(100)


def test_midpoint_of_the_lower_segment_is_twenty_five() -> None:
    assert threshold_progress(Decimal(10), Decimal(20), Decimal(40)) == Decimal(25)


def test_midpoint_of_the_upper_segment_is_seventy_five() -> None:
    assert threshold_progress(Decimal(30), Decimal(20), Decimal(40)) == Decimal(75)


def test_a_negative_value_is_zero() -> None:
    assert threshold_progress(Decimal(-5), Decimal(20), Decimal(40)) == Decimal(0)


def test_a_non_positive_threshold_is_rejected() -> None:
    with pytest.raises(ValueError):
        threshold_progress(Decimal(10), Decimal(0), Decimal(40))
    with pytest.raises(ValueError):
        threshold_progress(Decimal(10), Decimal(-5), Decimal(40))


def test_a_saturation_not_above_the_threshold_is_rejected() -> None:
    with pytest.raises(ValueError):
        threshold_progress(Decimal(10), Decimal(20), Decimal(20))
    with pytest.raises(ValueError):
        threshold_progress(Decimal(10), Decimal(20), Decimal(10))


def test_the_result_is_always_exact_decimal() -> None:
    result = threshold_progress(Decimal(15), Decimal(20), Decimal(40))
    assert isinstance(result, Decimal)
    assert result == Decimal("37.5")

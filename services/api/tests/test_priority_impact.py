"""Impact Score V1 per detector: MIN for AND-detectors, MAX for OR-detectors (spec parts C-G)."""

import inspect
from decimal import Decimal

import pytest

from app.modules.intelligence.priority.impact import (
    cost_impact,
    labor_impact,
    occupancy_impact,
    ota_impact,
    pickup_impact,
    threshold_progress,
)

# --- C. REV_PICKUP_LOW (AND -> MIN) -----------------------------------------------------------


def test_pickup_exactly_at_both_thresholds_is_fifty() -> None:
    assert pickup_impact(Decimal(20), Decimal(2)) == Decimal(50)


def test_pickup_doubled_pair_is_a_hundred() -> None:
    assert pickup_impact(Decimal(40), Decimal(4)) == Decimal(100)


def test_pickup_one_huge_one_at_threshold_is_fifty_via_min() -> None:
    assert pickup_impact(Decimal(1000), Decimal(2)) == Decimal(50)
    assert pickup_impact(Decimal(20), Decimal(1000)) == Decimal(50)


def test_pickup_impact_is_exact_decimal() -> None:
    result = pickup_impact(Decimal(10), Decimal(1))
    assert isinstance(result, Decimal)
    # min(threshold_progress(10,20,40)=25, threshold_progress(1,2,4)=25)
    assert result == Decimal(25)


# --- D. REV_OCCUPANCY_RISK (OR -> MAX) --------------------------------------------------------


def test_occupancy_gap_threshold_alone_is_fifty() -> None:
    assert occupancy_impact(Decimal(10), Decimal(0)) == Decimal(50)


def test_occupancy_rooms_threshold_alone_is_fifty() -> None:
    assert occupancy_impact(Decimal(0), Decimal(3)) == Decimal(50)


def test_occupancy_the_larger_path_wins_via_max() -> None:
    assert occupancy_impact(Decimal(20), Decimal(3)) == Decimal(100)
    assert occupancy_impact(Decimal(10), Decimal(6)) == Decimal(100)


def test_occupancy_both_doubled_is_a_hundred() -> None:
    assert occupancy_impact(Decimal(20), Decimal(6)) == Decimal(100)


# --- E. REV_OTA_DEPENDENCY (independent paths) -------------------------------------------------


def test_ota_structural_at_seventy_is_fifty() -> None:
    impact = ota_impact(Decimal(70), Decimal(0), structural_condition=True, rising_condition=False)
    assert impact == Decimal(50)


def test_ota_structural_at_a_hundred_is_a_hundred() -> None:
    impact = ota_impact(Decimal(100), Decimal(0), structural_condition=True, rising_condition=False)
    assert impact == Decimal(100)


def test_ota_rising_at_fifty_five_share_and_fifteen_pp_is_fifty() -> None:
    impact = ota_impact(Decimal(55), Decimal(15), structural_condition=False, rising_condition=True)
    assert impact == Decimal(50)


def test_ota_a_stronger_rising_signal_grows_past_the_threshold_value() -> None:
    baseline = ota_impact(
        Decimal(55), Decimal(15), structural_condition=False, rising_condition=True
    )
    stronger = ota_impact(
        Decimal(80), Decimal(25), structural_condition=False, rising_condition=True
    )
    assert stronger > baseline


def test_ota_structural_only_ignores_a_high_rising_looking_share() -> None:
    # structural_condition True, rising False: the result is the structural component alone,
    # whatever delta_pp says (it must never leak in as if rising also held).
    with_low_delta = ota_impact(
        Decimal(80), Decimal(0), structural_condition=True, rising_condition=False
    )
    with_high_delta = ota_impact(
        Decimal(80), Decimal(50), structural_condition=True, rising_condition=False
    )
    assert with_low_delta == with_high_delta


def test_ota_rising_only_ignores_the_structural_threshold() -> None:
    # rising_condition True, structural False: even a share of 90 (which would saturate the
    # structural component at 100) must be scored ONLY through the rising path.
    rising_only = ota_impact(
        Decimal(90), Decimal(20), structural_condition=False, rising_condition=True
    )
    expected_rising_impact = min(
        threshold_progress(Decimal(90), Decimal(55), Decimal(100)),
        threshold_progress(Decimal(20), Decimal(15), Decimal(30)),
    )
    structural_component_of_the_same_share = threshold_progress(
        Decimal(90), Decimal(70), Decimal(100)
    )
    assert rising_only == expected_rising_impact
    assert rising_only != structural_component_of_the_same_share


def test_ota_both_conditions_choose_the_max_of_the_two_paths() -> None:
    structural_component_only = ota_impact(
        Decimal(90), Decimal(0), structural_condition=True, rising_condition=False
    )
    rising_component_only = ota_impact(
        Decimal(90), Decimal(0), structural_condition=False, rising_condition=True
    )
    both = ota_impact(Decimal(90), Decimal(0), structural_condition=True, rising_condition=True)
    assert both == max(structural_component_only, rising_component_only)


def test_ota_neither_condition_is_rejected() -> None:
    with pytest.raises(ValueError):
        ota_impact(Decimal(90), Decimal(20), structural_condition=False, rising_condition=False)


# --- F. COST_CPOR_ANOMALY (AND -> MIN) ----------------------------------------------------------


def test_cost_delta_twenty_and_fence_ratio_one_is_fifty() -> None:
    # actual_cpor == upper_fence -> ratio 1 (the robust fence threshold)
    assert cost_impact(Decimal(20), Decimal(4), Decimal(4)) == Decimal(50)


def test_cost_delta_forty_and_fence_ratio_one_point_five_is_a_hundred() -> None:
    assert cost_impact(Decimal(40), Decimal(6), Decimal(4)) == Decimal(100)


def test_cost_min_semantics() -> None:
    # relative saturated (100) but robust ratio only at its own threshold (50) -> MIN = 50.
    assert cost_impact(Decimal(1000), Decimal(4), Decimal(4)) == Decimal(50)


def test_cost_impact_has_no_monetary_parameter() -> None:
    # The gross cost_gap_proxy never enters Impact V1: the function itself has no such parameter.
    parameters = set(inspect.signature(cost_impact).parameters)
    assert parameters == {"delta_percent", "actual_cpor", "upper_fence"}


def test_cost_an_invalid_upper_fence_is_rejected() -> None:
    with pytest.raises(ValueError):
        cost_impact(Decimal(20), Decimal(4), Decimal(0))
    with pytest.raises(ValueError):
        cost_impact(Decimal(20), Decimal(4), Decimal(-1))


# --- G. LABOR_OVERSTAFFING (AND -> MIN) --------------------------------------------------------


def test_labor_twenty_percent_and_four_hours_is_fifty() -> None:
    assert labor_impact(Decimal(20), Decimal(4)) == Decimal(50)


def test_labor_forty_percent_and_eight_hours_is_a_hundred() -> None:
    assert labor_impact(Decimal(40), Decimal(8)) == Decimal(100)


def test_labor_min_semantics() -> None:
    assert labor_impact(Decimal(1000), Decimal(4)) == Decimal(50)


def test_labor_impact_has_no_monetary_parameter() -> None:
    # The optional labor_cost_gap_proxy never enters Impact V1.
    parameters = set(inspect.signature(labor_impact).parameters)
    assert parameters == {"delta_percent", "excess_hours"}

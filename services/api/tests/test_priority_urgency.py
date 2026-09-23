"""Urgency Score V1: forward-dated bands, the OTA fixed policy, the cost retrospective bands
(spec parts H, I, J)."""

from decimal import Decimal

import pytest

from app.modules.intelligence.priority.urgency import cost_urgency, forward_urgency, ota_urgency

# --- H. FORWARD-DATED (REV_PICKUP_LOW / REV_OCCUPANCY_RISK / LABOR_OVERSTAFFING) ---------------


@pytest.mark.parametrize(
    ("days_to_target", "expected"),
    [
        (0, 100),
        (1, 100),
        (2, 90),
        (3, 90),
        (4, 80),
        (7, 80),
        (8, 65),
        (14, 65),
        (15, 50),
        (30, 50),
        (31, 35),
        (60, 35),
        (61, 20),
    ],
)
def test_forward_urgency_bands(days_to_target: int, expected: int) -> None:
    assert forward_urgency(days_to_target) == Decimal(expected)


def test_forward_urgency_rejects_a_stale_negative_date() -> None:
    with pytest.raises(ValueError):
        forward_urgency(-1)


# --- I. REV_OTA_DEPENDENCY -----------------------------------------------------------------------


def test_ota_urgency_structural_only_is_forty() -> None:
    assert ota_urgency(structural_condition=True, rising_condition=False) == Decimal(40)


def test_ota_urgency_rising_only_is_sixty() -> None:
    assert ota_urgency(structural_condition=False, rising_condition=True) == Decimal(60)


def test_ota_urgency_both_is_sixty() -> None:
    assert ota_urgency(structural_condition=True, rising_condition=True) == Decimal(60)


def test_ota_urgency_neither_condition_is_rejected() -> None:
    with pytest.raises(ValueError):
        ota_urgency(structural_condition=False, rising_condition=False)


# --- J. COST_CPOR_ANOMALY (retrospective) -------------------------------------------------------


@pytest.mark.parametrize(
    ("days_since_period_end", "expected"),
    [
        (1, 70),
        (7, 70),
        (8, 55),
        (30, 55),
        (31, 40),
        (60, 40),
        (61, 25),
        (90, 25),
        (91, 10),
    ],
)
def test_cost_urgency_bands(days_since_period_end: int, expected: int) -> None:
    assert cost_urgency(days_since_period_end) == Decimal(expected)


def test_cost_urgency_rejects_a_month_that_has_not_yet_concluded() -> None:
    with pytest.raises(ValueError):
        cost_urgency(0)
    with pytest.raises(ValueError):
        cost_urgency(-5)

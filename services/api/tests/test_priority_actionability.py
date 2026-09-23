"""Actionability Score V1: the fixed policy per decision type (spec part K)."""

from decimal import Decimal

from app.modules.intelligence.priority.actionability import actionability_score
from app.modules.intelligence.priority.types import ACTIONABILITY_POLICY_V1, PriorityDecisionType


def test_pickup_actionability_is_ninety() -> None:
    assert actionability_score(PriorityDecisionType.REV_PICKUP_LOW) == Decimal(90)


def test_occupancy_actionability_is_eighty_five() -> None:
    assert actionability_score(PriorityDecisionType.REV_OCCUPANCY_RISK) == Decimal(85)


def test_ota_actionability_is_sixty() -> None:
    assert actionability_score(PriorityDecisionType.REV_OTA_DEPENDENCY) == Decimal(60)


def test_cost_actionability_is_seventy() -> None:
    assert actionability_score(PriorityDecisionType.COST_CPOR_ANOMALY) == Decimal(70)


def test_labor_actionability_is_ninety() -> None:
    assert actionability_score(PriorityDecisionType.LABOR_OVERSTAFFING) == Decimal(90)


def test_every_policy_value_is_bounded_zero_to_a_hundred() -> None:
    for decision_type in PriorityDecisionType:
        value = ACTIONABILITY_POLICY_V1[decision_type]
        assert Decimal(0) <= value <= Decimal(100)

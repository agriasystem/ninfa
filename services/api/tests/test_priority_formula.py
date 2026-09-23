"""Priority Score V1 formula: frozen weights, exact Decimal, HALF_UP display (spec part A)."""

import ast
from decimal import Decimal
from pathlib import Path

import app.modules.intelligence.priority as priority_package
from app.modules.intelligence.priority.scoring import priority_score_display, priority_score_exact
from app.modules.intelligence.priority.types import (
    ACTIONABILITY_WEIGHT,
    CONFIDENCE_WEIGHT,
    IMPACT_WEIGHT,
    URGENCY_WEIGHT,
)


def test_the_four_weights_are_exactly_040_025_020_015() -> None:
    assert Decimal("0.40") == IMPACT_WEIGHT
    assert Decimal("0.25") == URGENCY_WEIGHT
    assert Decimal("0.20") == CONFIDENCE_WEIGHT
    assert Decimal("0.15") == ACTIONABILITY_WEIGHT


def test_the_weights_sum_to_exactly_100() -> None:
    assert (
        Decimal("1.00") == IMPACT_WEIGHT + URGENCY_WEIGHT + CONFIDENCE_WEIGHT + ACTIONABILITY_WEIGHT
    )


def test_all_components_zero_gives_zero() -> None:
    score = priority_score_exact(
        impact_score=Decimal(0),
        urgency_score=Decimal(0),
        confidence_score=Decimal(0),
        actionability_score=Decimal(0),
    )
    assert score == Decimal(0)


def test_all_components_a_hundred_gives_a_hundred() -> None:
    score = priority_score_exact(
        impact_score=Decimal(100),
        urgency_score=Decimal(100),
        confidence_score=Decimal(100),
        actionability_score=Decimal(100),
    )
    assert score == Decimal(100)


def test_a_hand_calculated_example() -> None:
    # 0.40*80 + 0.25*60 + 0.20*90 + 0.15*70 = 32 + 15 + 18 + 10.5 = 75.5
    score = priority_score_exact(
        impact_score=Decimal(80),
        urgency_score=Decimal(60),
        confidence_score=Decimal(90),
        actionability_score=Decimal(70),
    )
    assert score == Decimal("75.5")


def test_equal_components_reduce_to_the_component_itself() -> None:
    # weights sum to exactly 1, so x,x,x,x -> x for any x: a second hand-calculated check.
    for value in (Decimal(0), Decimal("33.33"), Decimal(50), Decimal(100)):
        score = priority_score_exact(
            impact_score=value,
            urgency_score=value,
            confidence_score=value,
            actionability_score=value,
        )
        assert score == value


def test_the_priority_module_uses_decimal_only_no_float() -> None:
    package_dir = Path(priority_package.__file__).parent
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        floats = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "float"]
        literals = [
            n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)
        ]
        assert floats == [] and literals == [], source.name


def test_display_is_half_up_two_decimals() -> None:
    assert priority_score_display(Decimal("75.505")) == Decimal("75.51")
    assert priority_score_display(Decimal("75.504")) == Decimal("75.50")
    assert priority_score_display(Decimal(100)) == Decimal("100.00")


def test_display_rounding_never_decides_which_of_two_scores_is_higher() -> None:
    # Two exact scores 0.004 apart both display as 75.50, but the ranking (tested in
    # test_priority_sorting.py) sorts on priority_score_exact, never on the display value.
    higher = Decimal("75.504")
    lower = Decimal("75.500")
    assert priority_score_display(higher) == priority_score_display(lower) == Decimal("75.50")
    assert higher > lower

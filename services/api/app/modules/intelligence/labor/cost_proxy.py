"""The optional labor cost gap proxy (pure): a GROSS exposure figure, never a saving or a loss.

The detector works fully without any cost data (the trigger is on hours alone). When cost data is
available, `reference_hourly_cost` is resolved by trying, in order:

  1. the target category's own PLANNED cost of the target day, if its total is positive, the
     scheduled hours are positive and every contributing entry shares ONE currency:
     rate = total planned cost / scheduled hours              TARGET_PLANNED_COST_RATE

  2. else, the comparables actually used whose labor basis is ACTUAL and that carry a category
     cost in ONE consistent currency: rate = MEDIAN of (day cost / day hours), at full precision
                                                             HISTORICAL_ACTUAL_MEDIAN_RATE

  3. else: None. NINFA never invents a cost, and a currency mismatch is treated exactly like a
     missing cost (no FX, ever).

`labor_cost_gap_proxy = excess_hours * reference_hourly_cost`, HALF_UP two decimals. It never
enters the numeric trigger.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.intelligence.labor.precision import CALCULATION_CONTEXT, for_display
from app.modules.intelligence.labor.statistics import median
from app.modules.intelligence.labor.types import (
    ComparableDayFact,
    LaborBasis,
    ReferenceHourlyCostSource,
)

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class TargetCategoryCost:
    """The target day's own cost inputs for the requested category (may be all-None)."""

    total_planned_cost: Decimal | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class ReferenceRate:
    value: Decimal
    source: ReferenceHourlyCostSource
    currency: str


def reference_hourly_cost(
    target: TargetCategoryCost,
    scheduled_hours_exact: Decimal,
    used_days: Sequence[ComparableDayFact],
) -> ReferenceRate | None:
    if (
        target.total_planned_cost is not None
        and target.total_planned_cost > 0
        and scheduled_hours_exact > 0
        and target.currency is not None
    ):
        rate = CALCULATION_CONTEXT.divide(target.total_planned_cost, scheduled_hours_exact)
        return ReferenceRate(
            rate, ReferenceHourlyCostSource.TARGET_PLANNED_COST_RATE, target.currency
        )

    candidates = [
        day
        for day in used_days
        if day.labor_basis is LaborBasis.ACTUAL
        and day.category_cost_exact is not None
        and day.category_cost_exact > 0
        and day.cost_currency is not None
        and day.historical_hours_exact > 0
    ]
    if not candidates:
        return None
    currencies: set[str] = {
        day.cost_currency for day in candidates if day.cost_currency is not None
    }
    if len(currencies) != 1:
        return None  # inconsistent currency: never converted, never guessed
    rates = [
        CALCULATION_CONTEXT.divide(day.category_cost_exact, day.historical_hours_exact)
        for day in candidates
        if day.category_cost_exact is not None
    ]
    return ReferenceRate(
        median(rates),
        ReferenceHourlyCostSource.HISTORICAL_ACTUAL_MEDIAN_RATE,
        next(iter(currencies)),
    )


def labor_cost_gap_proxy(excess_hours: Decimal, rate: Decimal) -> Decimal:
    """`excess_hours * rate`, HALF_UP two decimals: a GROSS proxy, never a guaranteed saving."""
    return for_display(CALCULATION_CONTEXT.multiply(excess_hours, rate))

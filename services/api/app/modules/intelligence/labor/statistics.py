"""Robust statistics of the historical labor hours (pure functions, `Decimal` only, no float).

The algorithm is EXACTLY the one of the Expected Engine and of the revenue/cost detectors (median,
and P25/P75 by linear interpolation at index `(n - 1) * p`; IQR = P75 - P25), but an hours figure is
not an integer number of rooms, so the values are kept at FULL PRECISION (the dedicated 50-digit
context) and are never rounded before a threshold is compared:

    position   = (n - 1) * p            lo = floor(position)     hi = min(lo + 1, n - 1)
    percentile = x[lo] + (position - lo) * (x[hi] - x[lo])

    upper fence = P75 + 1.5 * IQR

There is NO outlier removal: the median and the quartiles are the robustness.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from app.modules.intelligence.labor.precision import CALCULATION_CONTEXT
from app.modules.intelligence.labor.types import LABOR_IQR_MULTIPLIER

P25 = Decimal("0.25")
P75 = Decimal("0.75")
_HALF = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class LaborStatistics:
    median: Decimal
    p25: Decimal
    p75: Decimal
    iqr: Decimal
    upper_fence: Decimal


def percentile(values: Sequence[Decimal], p: Decimal) -> Decimal:
    """Linear-interpolation percentile of a non-empty sample, at full precision."""
    if not values:
        raise ValueError("a percentile needs at least one value")
    if not Decimal(0) <= p <= Decimal(1):
        raise ValueError("p must be between 0 and 1")
    ordered = sorted(values)
    position = CALCULATION_CONTEXT.multiply(Decimal(len(ordered) - 1), p)
    low = int(position.to_integral_value(rounding=ROUND_FLOOR))
    high = min(low + 1, len(ordered) - 1)
    fraction = CALCULATION_CONTEXT.subtract(position, Decimal(low))
    step = CALCULATION_CONTEXT.subtract(ordered[high], ordered[low])
    return CALCULATION_CONTEXT.add(ordered[low], CALCULATION_CONTEXT.multiply(fraction, step))


def median(values: Sequence[Decimal]) -> Decimal:
    """Middle value; for an even count the mean of the two middle values."""
    if not values:
        raise ValueError("a median needs at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return CALCULATION_CONTEXT.multiply(
        CALCULATION_CONTEXT.add(ordered[middle - 1], ordered[middle]), _HALF
    )


def summarize(
    values: Sequence[Decimal], *, iqr_multiplier: Decimal = LABOR_IQR_MULTIPLIER
) -> LaborStatistics:
    p25, p75 = percentile(values, P25), percentile(values, P75)
    iqr = CALCULATION_CONTEXT.subtract(p75, p25)
    fence = CALCULATION_CONTEXT.add(p75, CALCULATION_CONTEXT.multiply(iqr_multiplier, iqr))
    return LaborStatistics(median=median(values), p25=p25, p75=p75, iqr=iqr, upper_fence=fence)

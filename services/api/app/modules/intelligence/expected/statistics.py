"""Robust statistics of a comparable sample (pure functions, `Decimal` only, no float).

* EXPECTED = the median.
* Range = the historical P25 and P75 (a "central historical range", NOT a confidence or
  prediction interval).
* IQR = P75 - P25.

Percentiles use linear interpolation over the sorted sample, at index `(n - 1) * p`:

    position = (n - 1) * p            lo = floor(position)     hi = min(lo + 1, n - 1)
    percentile = x[lo] + (position - lo) * (x[hi] - x[lo])

With integer rooms and p in {0.25, 0.75} every result is a multiple of 0.25, so two decimals
always represent it exactly. There is no outlier removal: the median and the quartiles are the
robustness.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")
_HALF = Decimal("0.5")
P25 = Decimal("0.25")
P75 = Decimal("0.75")


@dataclass(frozen=True, slots=True)
class Statistics:
    expected: Decimal  # the median
    lower: Decimal  # historical P25
    upper: Decimal  # historical P75
    iqr: Decimal  # P75 - P25


def percentile(values: Sequence[int], p: Decimal) -> Decimal:
    """Linear-interpolation percentile of a non-empty sample, two decimals."""
    if not values:
        raise ValueError("a percentile needs at least one value")
    if not Decimal(0) <= p <= Decimal(1):
        raise ValueError("p must be between 0 and 1")
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * p
    low = int(position.to_integral_value(rounding=ROUND_FLOOR))
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    value = Decimal(ordered[low]) + fraction * Decimal(ordered[high] - ordered[low])
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def median(values: Sequence[int]) -> Decimal:
    """Middle value; for an even count the Decimal mean of the two middle values."""
    if not values:
        raise ValueError("a median needs at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return Decimal(ordered[middle]).quantize(_TWO_PLACES)
    return ((Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) * _HALF).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )


def summarize(values: Sequence[int]) -> Statistics:
    lower, upper = percentile(values, P25), percentile(values, P75)
    return Statistics(expected=median(values), lower=lower, upper=upper, iqr=upper - lower)

"""Statistics of a curve pattern (pure functions, `Decimal` only, no float).

The algorithms are EXACTLY those of the Expected Engine (`expected.statistics`): median, and P25 /
P75 by linear interpolation at index `(n - 1) * p`; IQR = P75 - P25. They are reused, not copied,
so the two engines cannot drift apart. There is no outlier removal: the median and the quartiles
are the robustness. The deltas are integer rooms and may be negative or zero.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.modules.intelligence.expected.statistics import Statistics, summarize
from app.modules.intelligence.revenue.types import HistoricalPair


def delta_statistics(pairs: Sequence[HistoricalPair]) -> Statistics:
    """Median / P25 / P75 / IQR of the historical pair deltas (pickup or remaining net pickup)."""
    return summarize([pair.delta for pair in pairs])


def other_rooms_median(pairs: Sequence[HistoricalPair]) -> Decimal:
    """Median rooms of the OTHER endpoint of the same pairs (for a remaining pair: the final)."""
    return summarize([pair.other.rooms_on_books for pair in pairs]).expected

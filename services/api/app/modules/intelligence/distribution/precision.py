"""Decision values versus displayed values: the Gate 5 rules, re-exported (not copied).

The OTA dependency detector follows exactly the path of the revenue, cost and labor detectors:

    CALCULATION VALUE  ->  THRESHOLD COMPARISON  ->  STATUS  ->  DISPLAY QUANTIZATION

Shares (percentages) and revenue are computed in the DEDICATED 50-digit context of
`revenue.precision`, independent of the process-wide `decimal` context, and are never rounded
before they are compared. The helpers are RE-EXPORTED, not copied, so the four detectors cannot
drift apart.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.modules.intelligence.revenue.precision import (
    CALCULATION_CONTEXT,
    DISPLAY_PLACES,
    canonical_text,
    percent_of,
)


def for_display(value: Decimal) -> Decimal:
    """Two decimals, HALF_UP (away from zero), in the dedicated context. Never decides anything."""
    return value.quantize(DISPLAY_PLACES, rounding=ROUND_HALF_UP, context=CALCULATION_CONTEXT)


def display_text(value: Decimal | None) -> str | None:
    """Two-decimal text of a value (the presentation of a figure)."""
    return None if value is None else format(for_display(value), "f")


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    """A sum in the dedicated context: no process-wide `decimal` setting can change it."""
    total = Decimal(0)
    for value in values:
        total = CALCULATION_CONTEXT.add(total, value)
    return total


__all__ = [
    "CALCULATION_CONTEXT",
    "DISPLAY_PLACES",
    "canonical_text",
    "display_text",
    "exact_sum",
    "for_display",
    "percent_of",
]

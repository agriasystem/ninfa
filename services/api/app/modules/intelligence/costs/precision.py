"""Decision values versus displayed values: the Gate 5 rules, one implementation.

The cost detector follows exactly the path of the revenue detectors:

    CALCULATION VALUE  ->  THRESHOLD COMPARISON  ->  STATUS  ->  DISPLAY QUANTIZATION

Quotients (a CPOR, a percentage, a coverage) are computed in the DEDICATED 50-digit context of
`revenue.precision`, independent of the process-wide `decimal` context, and are never rounded
before they are compared. Displayed values are the same numbers quantized to two decimals, HALF_UP,
and decide nothing. The helpers are RE-EXPORTED, not copied, so the two detectors cannot drift.
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
    """Two decimals, HALF_UP (away from zero), in the dedicated context.

    The same rounding as the Gate 5 helper, with the context named explicitly so that no
    process-wide `decimal` setting can make it raise or round differently. For presentation and
    contracts only: it never decides anything and never enters a fingerprint.
    """
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

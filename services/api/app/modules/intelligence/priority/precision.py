"""Decision values versus displayed values: the Gate 5 rules, re-exported (not copied).

The Priority Engine follows exactly the path every detector already follows:

    CALCULATION VALUE  ->  THRESHOLD COMPARISON  ->  SCORE  ->  DISPLAY QUANTIZATION

Every component score and the priority score itself are computed in the DEDICATED 50-digit
context of `revenue.precision`, independent of the process-wide `decimal` context, and are never
rounded before they decide anything (a ranking sorts on `*_exact`, never on `*_display`). The
helpers are RE-EXPORTED, not copied, so this gate cannot drift from the detectors whose output it
reads.
"""

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


__all__ = [
    "CALCULATION_CONTEXT",
    "DISPLAY_PLACES",
    "canonical_text",
    "display_text",
    "for_display",
    "percent_of",
]

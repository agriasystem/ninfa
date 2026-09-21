"""Decision values versus displayed values (pure, `Decimal` only, no float).

Every figure a detector compares with a threshold follows ONE path:

    CALCULATION VALUE  ->  THRESHOLD COMPARISON  ->  STATUS  ->  DISPLAY QUANTIZATION

The value that DECIDES is the full-precision `Decimal` the calculation produced; it is never
rounded first. The value that is SHOWN is that same number quantized to two decimals (HALF_UP,
away from zero) and is never used to decide anything. A pickup of -19.995 % is displayed as
-20.00 but does not reach a -20 % threshold; a gap of 9.995 points is displayed as 10.00 but does
not reach 10 points.

Only three kinds of figure are already exact at two decimals BY DEFINITION and need no separate
decision value: rooms (integers, or the median of integers, at most one decimal), the historical
statistics (defined at two decimals by the Gate 4 algorithms) and the confidence scores (the
authoritative two-decimal score of the confidence calculators is the value the gates compare).

Quotients are the only figures that are not terminating. They are computed in a DEDICATED context
of 50 significant digits (independent of the process-wide `decimal` context, so nothing else in
the process can change a result) and are never rounded before they are compared.

The fingerprint serialises Decimals with `canonical_text`: normalised, non-lossy, deterministic.
"""

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal

CALCULATION_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
DISPLAY_PLACES = Decimal("0.01")
_HUNDRED = Decimal(100)


def percent_of(part: Decimal, whole: Decimal) -> Decimal:
    """`part / whole * 100` at full calculation precision (`whole` must not be zero)."""
    return CALCULATION_CONTEXT.divide(CALCULATION_CONTEXT.multiply(part, _HUNDRED), whole)


def for_display(value: Decimal) -> Decimal:
    """The value quantized to two decimals, HALF_UP: for display and contracts, never to decide."""
    return value.quantize(DISPLAY_PLACES, rounding=ROUND_HALF_UP)


def display_text(value: Decimal | None) -> str | None:
    """Two-decimal text of a value (the presentation of a figure)."""
    return None if value is None else format(for_display(value), "f")


def canonical_text(value: Decimal | None) -> str | None:
    """Non-lossy, deterministic text of a Decimal: `10.00` and `10` and `1E+1` are all "10".

    No digit of the value is dropped (so two values on opposite sides of a threshold never share a
    text), the same number always gives the same text, and negative zero is "0".
    """
    if value is None:
        return None
    normalized = value.normalize(CALCULATION_CONTEXT)
    if normalized == 0:
        return "0"
    return format(normalized, "f")

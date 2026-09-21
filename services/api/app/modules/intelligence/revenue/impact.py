"""Reference ADR and the revenue gap PROXY (pure functions, `Decimal` only, no float).

    revenue_gap_proxy = rooms_at_risk x reference_adr        (HALF_UP, 2 dp)

It is a GROSS EXPOSURE proxy: how many rooms are missing versus history, priced at a reference
rate. It is NOT lost revenue and NOT a prediction: it says nothing about how many of those rooms
will really be missed, about cancellations, about a price that is or is not right, or about
margin. There is no loss probability anywhere, and the name never says "loss".

The reference ADR is chosen in this order and never invented:

1. `CURRENT_ON_BOOKS_ADR`            the target's own ADR on books, when it is > 0;
2. `HISTORICAL_COMPARABLE_MEDIAN_ADR` the median of the > 0 ADRs of the baseline's comparable
                                      snapshots (their real observed/reconstructed ADR);
3. `UNAVAILABLE`                     nothing usable: no ADR and therefore no proxy.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.intelligence.revenue.types import ReferenceAdrSource

_TWO_PLACES = Decimal("0.01")
_HALF = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class ReferenceAdr:
    value: Decimal | None
    source: ReferenceAdrSource


def median_decimal(values: Sequence[Decimal]) -> Decimal:
    """Middle value of a non-empty sample; for an even count the mean of the two middle values."""
    if not values:
        raise ValueError("a median needs at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle].quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return ((ordered[middle - 1] + ordered[middle]) * _HALF).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )


def reference_adr(
    target_adr: Decimal | None, comparable_adrs: Sequence[Decimal | None]
) -> ReferenceAdr:
    """The ADR used to price a room gap (see the module docstring for the order)."""
    if target_adr is not None and target_adr > 0:
        return ReferenceAdr(
            target_adr.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
        )
    usable = [adr for adr in comparable_adrs if adr is not None and adr > 0]
    if usable:
        return ReferenceAdr(
            median_decimal(usable), ReferenceAdrSource.HISTORICAL_COMPARABLE_MEDIAN_ADR
        )
    return ReferenceAdr(None, ReferenceAdrSource.UNAVAILABLE)


def revenue_gap_proxy(rooms_at_risk: Decimal, adr: Decimal | None) -> Decimal | None:
    """`rooms_at_risk x adr`, or None when there is no ADR (never a made-up price)."""
    if adr is None:
        return None
    return (rooms_at_risk * adr).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

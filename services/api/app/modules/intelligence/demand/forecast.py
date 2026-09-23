"""The minimal net-pickup rooms forecast (pure): the ONE primitive shared by REV_OCCUPANCY_RISK
(Gate 5) and LABOR_OVERSTAFFING (Gate 8).

    raw_forecast_rooms = rooms_on_books + expected_remaining_net_pickup
    forecast_rooms     = max(0, raw_forecast_rooms)        (the only floor; NO upper cap)

Extracted verbatim from `intelligence.revenue.occupancy` (the two lines are unchanged, only their
home moved): REV_OCCUPANCY_RISK now calls this function instead of repeating the arithmetic, so
its own behaviour is EXACTLY what it was before this extraction. Gate 8 imports it rather than
writing a second implementation of the same formula.
"""

from decimal import Decimal

_ZERO = Decimal(0)


def forecast_rooms_from_pickup(
    rooms_on_books: int, expected_remaining_net_pickup: Decimal
) -> Decimal:
    """`rooms_on_books + expected_remaining_net_pickup`, floored at 0, never clamped above."""
    raw_forecast = Decimal(rooms_on_books) + expected_remaining_net_pickup
    return max(_ZERO, raw_forecast)

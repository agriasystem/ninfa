"""The occupied-room-night denominator of Cost CPOR V1 (pure).

    occupied_room_nights(month) = SUM over every day D of the month of
                                  rooms_on_books of the snapshot (snapshot day D, stay date D)

That is the LEAD-TIME-0 snapshot of each stay night: what the bookings said at the end of the very
day of the stay. It is an OPERATING PROXY. NINFA has no consolidated PMS "actual occupied rooms"
(a Gate 3 snapshot is an observation of the booking table, or a reconstruction from it), so it is
never called certified, accounting or final occupancy.

Rules, all of them conservative:

* EVERY day of the month must have a snapshot. A missing snapshot is NOT zero rooms: it is an
  unknown, and the month is INCOMPLETE. A snapshot with zero rooms is a real, valid zero.
* A snapshot with `uncertain_rooms > 0` cannot enter the sum (its rooms are not known): the month
  is INCOMPLETE too. Uncertain rooms are never subtracted and never estimated.
* OBSERVED and RECONSTRUCTED_APPROXIMATE (with no uncertainty) are both admitted, and the mix is
  measured: provenance = (observed_days * 100 + reconstructed_days * 60) / days.

Nothing here reads a clock or the database.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.precision import CALCULATION_CONTEXT
from app.modules.intelligence.costs.types import OccupancyDenominator
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import SnapshotHistoryRow

OBSERVED_DAY_QUALITY = Decimal(100)
RECONSTRUCTED_DAY_QUALITY = Decimal(60)


def lead_zero_keys(month: CalendarMonth) -> list[tuple[date, date]]:
    """The (snapshot day, stay date) keys of the lead-time-0 snapshots of a month."""
    return [(day, day) for day in month.day_list()]


def index_lead_zero(rows: list[SnapshotHistoryRow]) -> dict[date, SnapshotHistoryRow]:
    """Lead-time-0 rows by stay date. Anything that is not lead time 0 is ignored, never used."""
    return {row.stay_date: row for row in rows if row.snapshot_local_date == row.stay_date}


def build_denominator(
    month: CalendarMonth, lead_zero: Mapping[date, SnapshotHistoryRow]
) -> OccupancyDenominator:
    observed = reconstructed = missing = uncertain = rooms = 0
    for day in month.day_list():
        row = lead_zero.get(day)
        if row is None:
            missing += 1  # never a zero
        elif row.uncertain_rooms > 0:
            uncertain += 1  # its rooms are unknown: it cannot be summed
        else:
            rooms += row.rooms_on_books
            if row.origin == SnapshotOrigin.OBSERVED:
                observed += 1
            else:
                reconstructed += 1
    complete = missing == 0 and uncertain == 0
    provenance: Decimal | None = None
    if complete:
        weighted = (
            Decimal(observed) * OBSERVED_DAY_QUALITY
            + Decimal(reconstructed) * RECONSTRUCTED_DAY_QUALITY
        )
        provenance = CALCULATION_CONTEXT.divide(weighted, Decimal(month.days))
    return OccupancyDenominator(
        total_days=month.days,
        observed_day_count=observed,
        reconstructed_day_count=reconstructed,
        missing_day_count=missing,
        uncertain_day_count=uncertain,
        occupied_room_nights=rooms if complete else None,
        occupancy_provenance_score_exact=provenance,
    )

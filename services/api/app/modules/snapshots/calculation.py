"""The arithmetic of a snapshot (pure functions, no database, no clock, no floats).

Money is handled as integer cents and percentages as integer hundredths of a percent, so every
allocation and rounding is exact and reproducible. Rounding is ROUND_HALF_UP, applied exactly
once, to a derived value (ADR, occupancy); allocation never rounds, it distributes.

Stay-night semantics: a booking occupies the nights `check_in <= D < check_out`. The check-out
date is NOT a stay night.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal
from uuid import UUID

from app.modules.bookings.models import BookingStatus
from app.modules.snapshots.models import SnapshotOrigin

# Identifies the *rules* below (status policy, allocation, rounding, uncertainty), not the
# application release: it changes only when a rule changes, and it is part of the fingerprint.
CALCULATION_VERSION = "booking-snapshot-v1"

# The observed status policy. Explicit and closed: every other status is excluded, none is
# reinterpreted (a CANCELLED booking is not "maybe still on the books", a NO_SHOW is not a stay).
OBSERVED_STATUSES: frozenset[BookingStatus] = frozenset(
    {BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.CHECKED_OUT}
)

_CENTS = Decimal(100)
# A dedicated context for the one multiplication/rescale below: money amounts need at most a
# couple of dozen significant digits, but `Decimal.__mul__`/`.scaleb()` still consult *some*
# context for their own result, so the AMBIENT, process-wide one (which nothing here controls)
# must never be it - exactly the reasoning of `intelligence.revenue.precision.CALCULATION_
# CONTEXT`, kept local here since this module sits below every intelligence module that reuses it.
_MONEY_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def to_cents(amount: Decimal) -> int:
    """Whole cents of a money amount; refuses sub-cent precision instead of rounding it."""
    cents = _MONEY_CONTEXT.multiply(amount, _CENTS)
    if cents != cents.to_integral_value():
        raise ValueError("amount has sub-cent precision")
    return int(cents)


def from_cents(cents: int) -> Decimal:
    """Money value (two decimals) of whole cents."""
    return Decimal(cents).scaleb(-2, context=_MONEY_CONTEXT)


def stay_nights(check_in: date, check_out: date) -> int:
    """Number of stay nights; the check-out date is not one of them."""
    nights = (check_out - check_in).days
    if nights <= 0:
        raise ValueError("check_out must be after check_in")
    return nights


def night_revenue_cents(total_cents: int, nights: int, night_index: int) -> int:
    """Cents of the whole-stay revenue allocated to one night (0-based `night_index`).

    The stay's revenue is spread uniformly; the indivisible remainder is handed out one cent at
    a time to the EARLIEST nights, so the allocations always sum to exactly `total_cents`:
    100.00 over 3 nights -> 33.34, 33.33, 33.33. This is a deterministic allocation, NOT the
    nightly rate the property really charged (the canonical booking only knows the stay total).
    """
    base, remainder = divmod(total_cents, nights)
    return base + 1 if night_index < remainder else base


def adr(revenue_cents: int, rooms_on_books: int) -> Decimal | None:
    """Average daily rate of the rooms on the books; None (never 0) when there are none."""
    if rooms_on_books <= 0:
        return None
    return from_cents((2 * revenue_cents + rooms_on_books) // (2 * rooms_on_books))


def occupancy(rooms_on_books: int, rooms_available: int | None) -> Decimal | None:
    """Rooms on the books over rooms available, in percent, two decimals, NOT clamped.

    112.50 stays 112.50: more rooms on the books than capacity is information (overbooking, a
    wrong inventory), not something to hide. None when the capacity is unknown or zero: there is
    no division by zero and no invented 0 or 100.
    """
    if rooms_available is None or rooms_available <= 0:
        return None
    hundredths = (2 * rooms_on_books * 10_000 + rooms_available) // (2 * rooms_available)
    return Decimal(hundredths).scaleb(-2)


@dataclass(frozen=True, slots=True)
class StayRecord:
    """The part of a canonical booking a snapshot needs (a read-only projection)."""

    status: BookingStatus
    booked_at: datetime
    cancelled_at: datetime | None
    check_in: date
    check_out: date
    rooms: int
    room_revenue: Decimal


@dataclass(slots=True)
class DayTotals:
    """Running totals of one stay night while bookings are accumulated (integers only)."""

    booking_count: int = 0
    rooms: int = 0
    revenue_cents: int = 0
    uncertain_booking_count: int = 0
    uncertain_rooms: int = 0


@dataclass(frozen=True, slots=True)
class SnapshotContent:
    """Everything that defines a snapshot's *content* (and nothing about how it was made).

    `as_of_at`, ids of the row and timestamps are runtime metadata: two runs that calculate the
    same content have the same fingerprint even though they ran at different instants.
    """

    origin: SnapshotOrigin
    snapshot_local_date: date
    stay_date: date
    data_source_id: UUID
    booking_count_on_books: int
    rooms_on_books: int
    allocated_room_revenue_on_books: Decimal
    rooms_available: int | None
    occupancy_on_books: Decimal | None
    adr_on_books: Decimal | None
    uncertain_booking_count: int
    uncertain_rooms: int
    calculation_version: str = CALCULATION_VERSION

    def fingerprint(self) -> str:
        """SHA-256 of the canonical JSON of the content (sorted keys, fixed decimal format)."""
        payload = {
            "calculation_version": self.calculation_version,
            "origin": self.origin.value,
            "snapshot_local_date": self.snapshot_local_date.isoformat(),
            "stay_date": self.stay_date.isoformat(),
            "data_source_id": str(self.data_source_id),
            "booking_count_on_books": self.booking_count_on_books,
            "rooms_on_books": self.rooms_on_books,
            "allocated_room_revenue_on_books": _decimal(self.allocated_room_revenue_on_books),
            "rooms_available": self.rooms_available,
            "occupancy_on_books": _decimal(self.occupancy_on_books),
            "adr_on_books": _decimal(self.adr_on_books),
            "uncertain_booking_count": self.uncertain_booking_count,
            "uncertain_rooms": self.uncertain_rooms,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def build_content(
    *,
    origin: SnapshotOrigin,
    snapshot_local_date: date,
    stay_date: date,
    data_source_id: UUID,
    totals: DayTotals,
    rooms_available: int | None,
) -> SnapshotContent:
    """Turn one night's totals + the inventory copied *now* into the snapshot content."""
    return SnapshotContent(
        origin=origin,
        snapshot_local_date=snapshot_local_date,
        stay_date=stay_date,
        data_source_id=data_source_id,
        booking_count_on_books=totals.booking_count,
        rooms_on_books=totals.rooms,
        allocated_room_revenue_on_books=from_cents(totals.revenue_cents),
        rooms_available=rooms_available,
        occupancy_on_books=occupancy(totals.rooms, rooms_available),
        adr_on_books=adr(totals.revenue_cents, totals.rooms),
        uncertain_booking_count=totals.uncertain_booking_count,
        uncertain_rooms=totals.uncertain_rooms,
    )


def date_range(start: date, end: date) -> list[date]:
    """Every date from `start` to `end`, both included."""
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _decimal(value: Decimal | None) -> str | None:
    """Fixed two-decimal text: 50 and 50.00 are the same content."""
    return None if value is None else format(value.quantize(Decimal("0.01")), "f")

"""Shared helpers for the Gate 9 (REV_OTA_DEPENDENCY) tests.

The Gate 9 tests use the SAME shared `factory: BookingFactory` fixture every other gate's tests
do (no per-module fixture override): `DistributionWorld` is a free-function-style helper over it,
exactly like `LaborWorld` in `labor_support.py` or `RevenueWorld` in `revenue_support.py`.
`factory.channel(...)` and `factory.booking(...)` (Gate 2's own factory methods) are reused
directly rather than duplicated, and `snapshot_row`/`add_snapshots` (Gate 4/5's own helpers) build
the `booking_snapshots` rows.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking, BookingChannel, BookingStatus, ChannelType
from app.modules.snapshots.models import SnapshotOrigin
from tests.expected_support import add_snapshots, snapshot_row
from tests.support import BookingFactory, Tenant

DistributionFactory = BookingFactory

OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
CONFIRMED = BookingStatus.CONFIRMED
CANCELLED = BookingStatus.CANCELLED
NO_SHOW = BookingStatus.NO_SHOW

# Comfortably before every scenario's own dates, so "booked well in advance" needs no thought.
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _per_day(value: Mapping[date, int] | int, day: date) -> int:
    return value[day] if isinstance(value, Mapping) else value


@dataclass
class DistributionWorld:
    """One tenant, its channels, its bookings and a controllable snapshot history."""

    session: Session
    tenant: Tenant
    factory: DistributionFactory
    _booking_counter: int = field(default=0)

    def channel(self, name: str = "Booking.com", **columns: Any) -> BookingChannel:
        return self.factory.channel(self.tenant.property, name, **columns)

    def booking(
        self,
        channel: BookingChannel,
        check_in: date,
        check_out: date,
        *,
        rooms: int = 1,
        status: BookingStatus = CONFIRMED,
        booked_at: datetime = LONG_AGO,
        cancelled_at: datetime | None = None,
        room_revenue: Decimal | None = None,
    ) -> Booking:
        self._booking_counter += 1
        nights = (check_out - check_in).days
        revenue = (
            room_revenue
            if room_revenue is not None
            else Decimal(rooms) * Decimal(nights) * Decimal("100.00")
        )
        return self.factory.booking(
            self.tenant.data_source,
            channel,
            self.tenant.import_job,
            source_record_id=f"BK-{self._booking_counter}",
            check_in=check_in,
            check_out=check_out,
            rooms=rooms,
            status=status,
            booked_at=booked_at,
            cancelled_at=cancelled_at,
            room_revenue=revenue,
        )

    def snapshot_window(
        self,
        as_of: date,
        window_start: date,
        window_end: date,
        rooms: Mapping[date, int] | int,
        *,
        origin: SnapshotOrigin = OBSERVED,
        uncertain_rooms: Mapping[date, int] | int = 0,
        data_source_id: UUID | None = None,
    ) -> None:
        """One `BookingSnapshot` row per night of `[window_start, window_end]`, all with
        `snapshot_local_date = as_of`. `rooms`/`uncertain_rooms` may be one value for every
        night or a `{night: value}` mapping."""
        rows = [
            snapshot_row(
                self.tenant,
                as_of,
                day,
                rooms=_per_day(rooms, day),
                origin=origin,
                uncertain_rooms=_per_day(uncertain_rooms, day),
                data_source_id=data_source_id,
            )
            for day in date_range(window_start, window_end)
        ]
        add_snapshots(self.session, self.tenant, rows)

    def uniform_bookings(
        self, first_night: date, last_night: date, bookings: list[tuple[BookingChannel, int]]
    ) -> None:
        """Each `(channel, rooms)` pair becomes ONE booking spanning
        `[first_night, last_night]`, certainly on the books at every as-of this range is ever
        evaluated at (CONFIRMED, booked long ago, never cancelled). Call this ONCE for a whole
        scenario's combined date range: several 30-day windows of different as-of dates overlap
        by design (a weekly step, a 30-night window), so creating a SEPARATE spanning booking
        per as-of would double-count the overlap."""
        for channel, rooms in bookings:
            self.booking(channel, first_night, last_night + timedelta(days=1), rooms=rooms)

    def clean_period(
        self,
        as_of: date,
        window_start: date,
        window_end: date,
        bookings: list[tuple[BookingChannel, int]],
        *,
        origin: SnapshotOrigin = OBSERVED,
    ) -> None:
        """A self-contained reconciling period for ONE as-of whose window never overlaps any
        other period this scenario also builds: creates the spanning bookings AND the matching
        snapshot. Do not use this when several as-of windows of the same scenario overlap in
        calendar time (use `uniform_bookings` once, then `snapshot_window` per as-of, instead)."""
        self.uniform_bookings(window_start, window_end, bookings)
        total = sum(rooms for _, rooms in bookings)
        self.snapshot_window(as_of, window_start, window_end, total, origin=origin)


@contextmanager
def statements_of(session: Session) -> Iterator[list[tuple[str, Any]]]:
    """Every SQL statement (text, parameters) the session's connection executes meanwhile."""
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[tuple[str, Any]] = []

    def record(*args: Any) -> None:
        captured.append((str(args[2]), args[3]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


__all__ = [
    "CANCELLED",
    "CONFIRMED",
    "LONG_AGO",
    "NO_SHOW",
    "OBSERVED",
    "RECONSTRUCTED",
    "ChannelType",
    "DistributionFactory",
    "DistributionWorld",
    "Tenant",
    "date_range",
    "statements_of",
]

"""Tenant-scoped, READ-ONLY access to the canonical bookings, channels and snapshots that
REV_OTA_DEPENDENCY needs (Part "PERFORMANCE"): ONE statement for the channels of a property, ONE
statement for every booking overlapping the union of every window a run needs (the target's and
every historical candidate's), and Gate 3's own `BookingSnapshotRepository.list_by_keys` for a
batched read of every (as-of, stay date) key a run needs - never a query per stay date, per
booking or per comparable.

Reads `bookings`, `booking_channels` and `booking_snapshots` only: never writes any of them.
"""

from collections.abc import Collection
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking
from app.modules.bookings.repository import BookingChannelRepository
from app.modules.intelligence.distribution.channels import ChannelRow
from app.modules.intelligence.distribution.temporal import StayRecord
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotHistoryRow


class DistributionRepository:
    """Read-only projections of ONE workspace's bookings/channels/snapshots for Gate 9."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._channels = BookingChannelRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)

    def list_channels(self, property_id: UUID) -> list[ChannelRow]:
        """Every channel of the property, in ONE statement (a small set: never paged)."""
        return [
            ChannelRow(
                channel_id=channel.id,
                normalized_name=channel.normalized_name,
                channel_type=channel.channel_type,
                is_verified=channel.is_verified,
            )
            for channel in self._channels.list_for_property(property_id)
        ]

    def list_stays_with_channel(
        self, property_id: UUID, data_source_id: UUID, first_night: date, last_night: date
    ) -> list[tuple[StayRecord, UUID]]:
        """Bookings with at least one stay night in `first_night..last_night`, in ONE query.

        The same overlap rule as `BookingStayRepository.list_stays` (Gate 3): a booking overlaps
        when `check_in <= last_night AND check_out > first_night`. Adds only `channel_id`.
        """
        query = select(
            Booking.status,
            Booking.booked_at,
            Booking.cancelled_at,
            Booking.check_in,
            Booking.check_out,
            Booking.rooms,
            Booking.room_revenue,
            Booking.channel_id,
        ).where(
            Booking.workspace_id == self._tenant.workspace_id,
            Booking.property_id == property_id,
            Booking.data_source_id == data_source_id,
            Booking.check_in <= last_night,
            Booking.check_out > first_night,
        )
        return [(StayRecord(*row[:7]), row[7]) for row in self._session.execute(query)]

    def snapshot_rows_by_as_of(
        self, data_source_id: UUID, as_of_dates: Collection[date], window_days: int
    ) -> dict[date, list[SnapshotHistoryRow]]:
        """Every snapshot row `(as_of, D)` for `D` in each as-of's own `window_days`-day window,
        for every `as_of` in `as_of_dates`, in ONE statement (Gate 3's own batched
        `list_by_keys`, a VALUES-list join): the way a run fetches a few hundred exact snapshots
        instead of one query per as-of or per stay date."""
        keys = {
            (as_of, as_of + timedelta(days=offset))
            for as_of in as_of_dates
            for offset in range(window_days)
        }
        rows = self._snapshots.list_by_keys(data_source_id, keys)
        by_as_of: dict[date, list[SnapshotHistoryRow]] = {as_of: [] for as_of in as_of_dates}
        for row in rows:
            if row.snapshot_local_date in by_as_of:
                by_as_of[row.snapshot_local_date].append(row)
        return by_as_of

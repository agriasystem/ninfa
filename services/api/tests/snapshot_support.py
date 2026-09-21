"""Helpers shared by the Gate 3 (snapshot) tests. Synthetic data only."""

import itertools
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingChannel, BookingStatus
from app.modules.snapshots.common import SnapshotRunResult
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import BookingSnapshotRepository, RoomInventoryRepository
from tests.support import BookingFactory, Tenant, insert_core

FINGERPRINT = "c" * 64
DEFAULT_BOOKED_AT = datetime(2026, 1, 10, 9, 30, tzinfo=UTC)


class FixedClock:
    """A controllable "now": the only source of time the snapshot services accept."""

    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, **delta: float) -> None:
        self.instant += timedelta(**delta)


def snapshot_values(tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    """Column values of a valid, internally consistent booking snapshot."""
    values: dict[str, Any] = {
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "data_source_id": tenant.data_source.id,
        "snapshot_local_date": date(2026, 3, 15),
        "as_of_at": datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
        "stay_date": date(2026, 4, 1),
        "origin": SnapshotOrigin.OBSERVED,
        "booking_count_on_books": 2,
        "rooms_on_books": 3,
        "allocated_room_revenue_on_books": Decimal("300.00"),
        "rooms_available": 10,
        "occupancy_on_books": Decimal("30.00"),
        "adr_on_books": Decimal("100.00"),
        "uncertain_booking_count": 0,
        "uncertain_rooms": 0,
        "calculation_version": "booking-snapshot-v1",
        "content_fingerprint": FINGERPRINT,
    }
    values.update(overrides)
    return values


def inventory_values(tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "stay_date": date(2026, 4, 1),
        "rooms_available": 20,
        "rooms_out_of_order": 0,
    }
    values.update(overrides)
    return values


def insert_snapshot(session: Session, tenant: Tenant, **overrides: Any) -> None:
    insert_core(session, BookingSnapshot, **snapshot_values(tenant, **overrides))


def insert_inventory(session: Session, tenant: Tenant, **overrides: Any) -> None:
    insert_core(session, RoomInventoryDaily, **inventory_values(tenant, **overrides))


@dataclass
class World:
    """One tenant with a booking channel, plus shortcuts to fill it and run the services."""

    session: Session
    factory: BookingFactory
    tenant: Tenant
    channel: BookingChannel
    clock: FixedClock
    _ids: "itertools.count[int]" = field(default_factory=lambda: itertools.count(1))

    @classmethod
    def create(cls, session: Session, factory: BookingFactory, now: datetime) -> "World":
        tenant = factory.tenant()
        channel = factory.channel(tenant.property)
        return cls(session, factory, tenant, channel, FixedClock(now))

    @property
    def context(self) -> TenantContext:
        return self.tenant.context

    def book(
        self,
        check_in: date,
        check_out: date,
        *,
        rooms: int = 1,
        revenue: str = "300.00",
        status: BookingStatus = BookingStatus.CONFIRMED,
        booked_at: datetime = DEFAULT_BOOKED_AT,
        cancelled_at: datetime | None = None,
    ) -> Booking:
        source = self.tenant.data_source
        return self.factory.booking(
            source,
            self.channel,
            self.tenant.import_job,
            source_record_id=f"T-{next(self._ids):05d}",
            check_in=check_in,
            check_out=check_out,
            rooms=rooms,
            room_revenue=Decimal(revenue),
            status=status,
            booked_at=booked_at,
            cancelled_at=cancelled_at,
        )

    def book_in(self, data_source: Any, check_in: date, check_out: date, **kwargs: Any) -> Booking:
        """A booking in ANOTHER data source of the same property."""
        job = self.factory.import_job(data_source)
        return self.factory.booking(
            data_source,
            self.channel,
            job,
            source_record_id=f"T-{next(self._ids):05d}",
            check_in=check_in,
            check_out=check_out,
            **kwargs,
        )

    def set_inventory(self, first: date, last: date, available: int, out_of_order: int = 0) -> None:
        repository = RoomInventoryRepository(self.session, self.context)
        day = first
        while day <= last:
            repository.set_for_date(
                self.tenant.property.id,
                day,
                rooms_available=available,
                rooms_out_of_order=out_of_order,
            )
            day += timedelta(days=1)

    def commit(self) -> None:
        """The services want a session with no uncommitted work (they commit / roll back)."""
        self.session.commit()

    # --- services -----------------------------------------------------------------------------

    def observe(self, first: date, last: date, *, data_source_id: Any = None) -> SnapshotRunResult:
        self.commit()
        return ObservedSnapshotService(self.session, self.context, clock=self.clock).take_snapshot(
            property_id=self.tenant.property.id,
            data_source_id=data_source_id or self.tenant.data_source.id,
            stay_date_start=first,
            stay_date_end=last,
        )

    def reconstruct(
        self,
        snapshot_first: date,
        snapshot_last: date,
        stay_first: date,
        stay_last: date,
        *,
        data_source_id: Any = None,
    ) -> SnapshotRunResult:
        self.commit()
        service = BookingSnapshotReconstructionService(self.session, self.context, clock=self.clock)
        return service.reconstruct(
            property_id=self.tenant.property.id,
            data_source_id=data_source_id or self.tenant.data_source.id,
            snapshot_date_start=snapshot_first,
            snapshot_date_end=snapshot_last,
            stay_date_start=stay_first,
            stay_date_end=stay_last,
        )

    def stored(self, snapshot_date: date, stay_date: date) -> BookingSnapshot | None:
        return BookingSnapshotRepository(self.session, self.context).get_for_stay_date(
            self.tenant.data_source.id, snapshot_date, stay_date
        )

"""Tenant-scoped data access for room inventory, booking snapshots and the bookings they read.

Every query carries the workspace_id of the TenantContext. Repositories flush but never commit:
the service owns the transaction. No pickup, velocity, trend, expected value or forecast is
computed here: the curve access returns stored facts, in order, and nothing else.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import Date, Table, and_, column, func, select, values
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.calculation import SnapshotContent, StayRecord
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin

SNAPSHOT_KEY_CONSTRAINT = "uq_booking_snapshots_data_source_snapshot_date_stay_date"
_INSERT_BLOCK = 2000  # rows per executemany call

# (snapshot_local_date, stay_date): the logical key of a snapshot inside one data source.
SnapshotKey = tuple[date, date]
_KEYS_PER_QUERY = 5000  # (date, date) pairs per VALUES join: 10 000 bind parameters


@dataclass(frozen=True, slots=True)
class SnapshotHistoryRow:
    """The stored facts of a snapshot that a historical comparison needs (nothing else)."""

    snapshot_id: UUID
    snapshot_local_date: date
    stay_date: date
    origin: SnapshotOrigin
    rooms_on_books: int
    uncertain_rooms: int
    adr_on_books: Decimal | None


class RoomInventoryRepository:
    """Room capacity of the properties of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_for_date(self, property_id: UUID, stay_date: date) -> RoomInventoryDaily | None:
        return self._session.scalar(
            select(RoomInventoryDaily).where(
                RoomInventoryDaily.workspace_id == self._tenant.workspace_id,
                RoomInventoryDaily.property_id == property_id,
                RoomInventoryDaily.stay_date == stay_date,
            )
        )

    def list_for_range(
        self, property_id: UUID, first: date, last: date
    ) -> Sequence[RoomInventoryDaily]:
        """Inventory rows of the nights `first..last` (both included), oldest first.

        Nights without a row are simply absent: "capacity unknown" is never turned into 0.
        """
        return self._session.scalars(
            select(RoomInventoryDaily)
            .where(
                RoomInventoryDaily.workspace_id == self._tenant.workspace_id,
                RoomInventoryDaily.property_id == property_id,
                RoomInventoryDaily.stay_date >= first,
                RoomInventoryDaily.stay_date <= last,
            )
            .order_by(RoomInventoryDaily.stay_date)
        ).all()

    def set_for_date(
        self,
        property_id: UUID,
        stay_date: date,
        *,
        rooms_available: int,
        rooms_out_of_order: int = 0,
    ) -> RoomInventoryDaily:
        """Create or replace the capacity of one night. 0 is a real value: a closed night."""
        if rooms_available < 0 or rooms_out_of_order < 0:
            raise ValueError("room counts cannot be negative")
        if PropertyRepository(self._session, self._tenant).get(property_id) is None:
            raise NotFoundError("Property")
        values = {
            "workspace_id": self._tenant.workspace_id,
            "property_id": property_id,
            "stay_date": stay_date,
            "rooms_available": rooms_available,
            "rooms_out_of_order": rooms_out_of_order,
        }
        statement = (
            pg_insert(RoomInventoryDaily)
            .values(values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "property_id", "stay_date"],
                set_={
                    "rooms_available": rooms_available,
                    "rooms_out_of_order": rooms_out_of_order,
                    "updated_at": func.now(),
                },
            )
            .returning(RoomInventoryDaily)
        )
        row = self._session.scalars(statement, execution_options={"populate_existing": True}).one()
        self._session.flush()
        return row


@dataclass(frozen=True, slots=True)
class NewSnapshot:
    """A calculated snapshot ready to be stored: its content, when it was made, its fingerprint."""

    content: SnapshotContent
    as_of_at: datetime
    content_fingerprint: str

    @classmethod
    def of(cls, content: SnapshotContent, as_of_at: datetime) -> "NewSnapshot":
        return cls(content, as_of_at, content.fingerprint())

    @property
    def key(self) -> SnapshotKey:
        return (self.content.snapshot_local_date, self.content.stay_date)


@dataclass(frozen=True, slots=True)
class StoredSnapshotRef:
    """What is needed to compare a stored snapshot with a freshly calculated one."""

    origin: SnapshotOrigin
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class BookingCurvePoint:
    """One point of the booking curve of a stay night: what was on the books on a snapshot day.

    Stored facts only. `origin` tells an observation from a reconstruction; a consumer must keep
    them apart. There is deliberately no pickup, velocity, trend or expected value here.
    """

    snapshot_local_date: date
    as_of_at: datetime
    rooms_on_books: int
    allocated_room_revenue_on_books: Decimal
    rooms_available: int | None
    occupancy_on_books: Decimal | None
    origin: SnapshotOrigin
    uncertain_rooms: int


class BookingSnapshotRepository:
    """Booking snapshots of ONE workspace. A data source is always named: sources never mix."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_for_stay_date(
        self, data_source_id: UUID, snapshot_local_date: date, stay_date: date
    ) -> BookingSnapshot | None:
        return self._session.scalar(
            select(BookingSnapshot).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.snapshot_local_date == snapshot_local_date,
                BookingSnapshot.stay_date == stay_date,
            )
        )

    def get_by_id(self, snapshot_id: UUID) -> BookingSnapshot | None:
        return self._session.scalar(
            select(BookingSnapshot).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.id == snapshot_id,
            )
        )

    def list_by_keys(
        self, data_source_id: UUID, keys: Collection[SnapshotKey]
    ) -> list[SnapshotHistoryRow]:
        """The snapshots of ONE data source at exactly these (snapshot day, stay date) keys.

        One statement per block of keys (a join with a VALUES list, served by the unique key's
        index): the way a historical comparison fetches a few dozen exact snapshots instead of
        scanning the history or asking once per date.
        """
        ordered = sorted(keys)
        found: list[SnapshotHistoryRow] = []
        for start in range(0, len(ordered), _KEYS_PER_QUERY):
            wanted = values(
                column("snapshot_local_date", Date), column("stay_date", Date), name="wanted"
            ).data(ordered[start : start + _KEYS_PER_QUERY])
            rows = self._session.execute(
                select(
                    BookingSnapshot.id,
                    BookingSnapshot.snapshot_local_date,
                    BookingSnapshot.stay_date,
                    BookingSnapshot.origin,
                    BookingSnapshot.rooms_on_books,
                    BookingSnapshot.uncertain_rooms,
                    BookingSnapshot.adr_on_books,
                )
                .join(
                    wanted,
                    and_(
                        BookingSnapshot.snapshot_local_date == wanted.c.snapshot_local_date,
                        BookingSnapshot.stay_date == wanted.c.stay_date,
                    ),
                )
                .where(
                    BookingSnapshot.workspace_id == self._tenant.workspace_id,
                    BookingSnapshot.data_source_id == data_source_id,
                )
            )
            found.extend(SnapshotHistoryRow(*row) for row in rows)
        return found

    def list_by_ids(
        self, data_source_id: UUID, snapshot_ids: Collection[UUID]
    ) -> list[SnapshotHistoryRow]:
        """The snapshots of ONE data source with these ids (one statement)."""
        if not snapshot_ids:
            return []
        rows = self._session.execute(
            select(
                BookingSnapshot.id,
                BookingSnapshot.snapshot_local_date,
                BookingSnapshot.stay_date,
                BookingSnapshot.origin,
                BookingSnapshot.rooms_on_books,
                BookingSnapshot.uncertain_rooms,
                BookingSnapshot.adr_on_books,
            ).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.id.in_(list(snapshot_ids)),
            )
        )
        return [SnapshotHistoryRow(*row) for row in rows]

    def list_for_snapshot_date(
        self,
        data_source_id: UUID,
        snapshot_local_date: date,
        *,
        stay_date_from: date | None = None,
        stay_date_to: date | None = None,
        origin: SnapshotOrigin | None = None,
    ) -> Sequence[BookingSnapshot]:
        """All the stay nights of one snapshot day, oldest stay night first."""
        query = select(BookingSnapshot).where(
            BookingSnapshot.workspace_id == self._tenant.workspace_id,
            BookingSnapshot.data_source_id == data_source_id,
            BookingSnapshot.snapshot_local_date == snapshot_local_date,
        )
        if origin is not None:
            query = query.where(BookingSnapshot.origin == origin)
        if stay_date_from is not None:
            query = query.where(BookingSnapshot.stay_date >= stay_date_from)
        if stay_date_to is not None:
            query = query.where(BookingSnapshot.stay_date <= stay_date_to)
        return self._session.scalars(query.order_by(BookingSnapshot.stay_date)).all()

    def list_curve_for_stay_date(
        self,
        data_source_id: UUID,
        stay_date: date,
        *,
        snapshot_date_from: date | None = None,
        snapshot_date_to: date | None = None,
    ) -> list[BookingCurvePoint]:
        """The booking curve of one stay night in ONE data source, oldest snapshot day first."""
        query = select(
            BookingSnapshot.snapshot_local_date,
            BookingSnapshot.as_of_at,
            BookingSnapshot.rooms_on_books,
            BookingSnapshot.allocated_room_revenue_on_books,
            BookingSnapshot.rooms_available,
            BookingSnapshot.occupancy_on_books,
            BookingSnapshot.origin,
            BookingSnapshot.uncertain_rooms,
        ).where(
            BookingSnapshot.workspace_id == self._tenant.workspace_id,
            BookingSnapshot.data_source_id == data_source_id,
            BookingSnapshot.stay_date == stay_date,
        )
        if snapshot_date_from is not None:
            query = query.where(BookingSnapshot.snapshot_local_date >= snapshot_date_from)
        if snapshot_date_to is not None:
            query = query.where(BookingSnapshot.snapshot_local_date <= snapshot_date_to)
        rows = self._session.execute(query.order_by(BookingSnapshot.snapshot_local_date)).all()
        return [BookingCurvePoint(*row) for row in rows]

    def existing_in_range(
        self,
        data_source_id: UUID,
        snapshot_date_from: date,
        snapshot_date_to: date,
        stay_date_from: date,
        stay_date_to: date,
    ) -> dict[SnapshotKey, StoredSnapshotRef]:
        """What is already stored inside a snapshot-day x stay-night rectangle (one query)."""
        rows = self._session.execute(
            select(
                BookingSnapshot.snapshot_local_date,
                BookingSnapshot.stay_date,
                BookingSnapshot.origin,
                BookingSnapshot.content_fingerprint,
            ).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.snapshot_local_date >= snapshot_date_from,
                BookingSnapshot.snapshot_local_date <= snapshot_date_to,
                BookingSnapshot.stay_date >= stay_date_from,
                BookingSnapshot.stay_date <= stay_date_to,
            )
        ).all()
        return {
            (row.snapshot_local_date, row.stay_date): StoredSnapshotRef(
                row.origin, row.content_fingerprint
            )
            for row in rows
        }

    def insert_if_absent(
        self, property_id: UUID, snapshots: Sequence[NewSnapshot]
    ) -> set[SnapshotKey]:
        """Store the snapshots whose key is free; never touch a stored one. Returns the new keys.

        `ON CONFLICT DO NOTHING` is the last line of defence: the services already compare with
        what exists (and hold a per-data-source lock), so a key skipped here means somebody else
        wrote it in between and the caller must treat that as a conflict.
        """
        if not snapshots:
            return set()
        # One compiled statement executed for a block of rows at a time: compiling a huge
        # multi-VALUES statement per chunk would dominate the cost of a large run, and building
        # every row dict up front would hold them all in memory. Core (table) insert: the ORM bulk
        # path would convert every row through the unit of work.
        table = cast(Table, BookingSnapshot.__table__)
        statement = (
            pg_insert(table)
            .on_conflict_do_nothing(constraint=SNAPSHOT_KEY_CONSTRAINT)
            .returning(table.c.snapshot_local_date, table.c.stay_date)
        )
        inserted: set[SnapshotKey] = set()
        for start in range(0, len(snapshots), _INSERT_BLOCK):
            rows = [
                self._row(property_id, snapshot)
                for snapshot in snapshots[start : start + _INSERT_BLOCK]
            ]
            inserted.update((row[0], row[1]) for row in self._session.execute(statement, rows))
        return inserted

    def _row(self, property_id: UUID, snapshot: NewSnapshot) -> dict[str, object]:
        content = snapshot.content
        return {
            "workspace_id": self._tenant.workspace_id,
            "property_id": property_id,
            "data_source_id": content.data_source_id,
            "snapshot_local_date": content.snapshot_local_date,
            "as_of_at": snapshot.as_of_at,
            "stay_date": content.stay_date,
            "origin": content.origin.value,
            "booking_count_on_books": content.booking_count_on_books,
            "rooms_on_books": content.rooms_on_books,
            "allocated_room_revenue_on_books": content.allocated_room_revenue_on_books,
            "rooms_available": content.rooms_available,
            "occupancy_on_books": content.occupancy_on_books,
            "adr_on_books": content.adr_on_books,
            "uncertain_booking_count": content.uncertain_booking_count,
            "uncertain_rooms": content.uncertain_rooms,
            "calculation_version": content.calculation_version,
            "content_fingerprint": snapshot.content_fingerprint,
        }


class BookingStayRepository:
    """Read-only projection of the canonical bookings of ONE data source, for the calculation."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def list_stays(
        self,
        property_id: UUID,
        data_source_id: UUID,
        first_night: date,
        last_night: date,
        *,
        statuses: frozenset[BookingStatus] | None = None,
    ) -> list[StayRecord]:
        """Bookings with at least one stay night in `first_night..last_night`, in ONE query.

        A booking occupies `check_in <= D < check_out`, so it overlaps the range when
        `check_in <= last_night AND check_out > first_night`. Only the columns the calculation
        needs are read (no ORM entities).
        """
        query = select(
            Booking.status,
            Booking.booked_at,
            Booking.cancelled_at,
            Booking.check_in,
            Booking.check_out,
            Booking.rooms,
            Booking.room_revenue,
        ).where(
            Booking.workspace_id == self._tenant.workspace_id,
            Booking.property_id == property_id,
            Booking.data_source_id == data_source_id,
            Booking.check_in <= last_night,
            Booking.check_out > first_night,
        )
        if statuses is not None:
            query = query.where(Booking.status.in_(sorted(statuses)))
        return [StayRecord(*row) for row in self._session.execute(query)]

"""Tenant-scoped data access for room inventory, booking snapshots and the bookings they read.

Every query carries the workspace_id of the TenantContext. Repositories flush but never commit:
the service owns the transaction. No pickup, velocity, trend, expected value or forecast is
computed here: the curve access returns stored facts, in order, and nothing else.

A day may hold several observations (`BookingSnapshot.revision`). Every read by day or by key gives
ONE row per (snapshot day, stay night), the newest: that is what a new analysis looks at, and what
represents that day in the history of any later day, so a day seen three times is still one sample.
Only `get_by_id` and `list_by_ids` reach an older revision, because a run or a baseline names it.

A comparison with the past says which observations count (`ObservationHistory`): the rule is told
to this module, which knows nothing of who made them.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    Table,
    and_,
    column,
    func,
    or_,
    select,
    text,
    values,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingStatus, is_current_booking
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.calculation import SnapshotContent, StayRecord
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin

SNAPSHOT_KEY_CONSTRAINT = "uq_booking_snapshots_source_snapshot_stay_revision"
_INSERT_BLOCK = 2000  # rows per executemany call

# (snapshot_local_date, stay_date): the logical key of a snapshot inside one data source.
SnapshotKey = tuple[date, date]
_KEYS_PER_QUERY = 5000  # (date, date, revision) per VALUES join: 15 000 bind parameters
_EVERY_REVISION = 2_147_483_647


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
    revision: int = 1


@dataclass(frozen=True, slots=True)
class ObservationHistory:
    """Which snapshots a comparison with the past may take as a SAMPLE of history.

    Readable is not eligible. A reconstruction is inferred TODAY about an earlier day: it can be
    read wherever a final figure is wanted (the rooms a month ended with, the cost per occupied
    room, the distribution), but it is not what NINFA knew on that day, and a comparison whose
    meaning is "what was known then" (the Expected value, the pickup, the curves) must not be built
    on it. So this admits an OBSERVATION and nothing else. A read that names no history
    (`list_by_keys` with `history=None`) is the readable one: it hands out what is stored,
    whatever its origin.

    `newest_revision` names, for each earlier day that counts, the newest of its revisions that does
    (a night reads as its newest row up to it). A day not named has no observation that counts, and
    a row above its revision is not read: it never existed for history, whatever the current
    screens show of it.

    `reading_day` and the days after it are not history, so nothing is said of them.
    """

    reading_day: date
    newest_revision: Mapping[date, int]

    def newest_readable(self, snapshot_local_date: date) -> int:
        if snapshot_local_date >= self.reading_day:
            return _EVERY_REVISION
        return self.newest_revision.get(snapshot_local_date, 0)

    def admits(self, row: SnapshotHistoryRow) -> bool:
        return row.origin == SnapshotOrigin.OBSERVED and row.revision <= self.newest_readable(
            row.snapshot_local_date
        )


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

    def set_for_range(
        self, property_id: UUID, first: date, last: date, *, rooms_available: int
    ) -> int:
        """Create or replace the capacity of every night `first..last` (both included), in one
        statement. A night that already has this number is not touched, and `rooms_out_of_order` of
        an existing night stays. Returns how many nights really changed."""
        if rooms_available < 0:
            raise ValueError("room counts cannot be negative")
        if PropertyRepository(self._session, self._tenant).get(property_id) is None:
            raise NotFoundError("Property")
        result = self._session.execute(
            text(
                """
                INSERT INTO room_inventory_daily
                    (workspace_id, property_id, stay_date, rooms_available)
                SELECT :workspace_id, :property_id, night::date, :rooms
                  FROM generate_series(CAST(:first AS date), CAST(:last AS date), '1 day') AS night
                ON CONFLICT (workspace_id, property_id, stay_date) DO UPDATE
                   SET rooms_available = EXCLUDED.rooms_available, updated_at = now()
                 WHERE room_inventory_daily.rooms_available <> EXCLUDED.rooms_available
                """
            ),
            {
                "workspace_id": self._tenant.workspace_id,
                "property_id": property_id,
                "rooms": rooms_available,
                "first": first,
                "last": last,
            },
        )
        self._session.flush()
        self._session.expire_all()
        return int(result.rowcount)  # type: ignore[attr-defined]


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
            select(BookingSnapshot)
            .where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.snapshot_local_date == snapshot_local_date,
                BookingSnapshot.stay_date == stay_date,
            )
            .order_by(BookingSnapshot.revision.desc())
            .limit(1)
        )

    def get_by_id(self, snapshot_id: UUID) -> BookingSnapshot | None:
        return self._session.scalar(
            select(BookingSnapshot).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.id == snapshot_id,
            )
        )

    def list_by_keys(
        self,
        data_source_id: UUID,
        keys: Collection[SnapshotKey],
        *,
        history: ObservationHistory | None = None,
    ) -> list[SnapshotHistoryRow]:
        """The snapshots of ONE data source at exactly these (snapshot day, stay date) keys.

        One statement per block of keys (a join with a VALUES list, served by the unique key's
        index): the way a historical comparison fetches a few dozen exact snapshots instead of
        scanning the history or asking once per date. `history`: only what counts as a sample of
        history (an observation a finished analysis read, never a reconstruction); with none, what
        is stored is read, whatever its origin.
        """

        def newest(day: date) -> int:
            return _EVERY_REVISION if history is None else history.newest_readable(day)

        def readable(wanted: Any) -> ColumnElement[bool]:
            # The same rule as `ObservationHistory.admits`, in the statement: with a history only an
            # observation is a sample; with none, everything stored is read.
            within = BookingSnapshot.revision <= wanted.c.newest_revision
            if history is None:
                return or_(BookingSnapshot.origin != SnapshotOrigin.OBSERVED, within)
            return and_(BookingSnapshot.origin == SnapshotOrigin.OBSERVED, within)

        ordered = sorted(keys)
        found: list[SnapshotHistoryRow] = []
        for start in range(0, len(ordered), _KEYS_PER_QUERY):
            wanted = values(
                column("snapshot_local_date", Date),
                column("stay_date", Date),
                column("newest_revision", Integer),
                name="wanted",
            ).data(
                [(day, stay, newest(day)) for day, stay in ordered[start : start + _KEYS_PER_QUERY]]
            )
            rows = self._session.execute(
                select(
                    BookingSnapshot.id,
                    BookingSnapshot.snapshot_local_date,
                    BookingSnapshot.stay_date,
                    BookingSnapshot.origin,
                    BookingSnapshot.rooms_on_books,
                    BookingSnapshot.uncertain_rooms,
                    BookingSnapshot.adr_on_books,
                    BookingSnapshot.revision,
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
                    readable(wanted),
                )
                .distinct(BookingSnapshot.snapshot_local_date, BookingSnapshot.stay_date)
                .order_by(
                    BookingSnapshot.snapshot_local_date,
                    BookingSnapshot.stay_date,
                    BookingSnapshot.revision.desc(),
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
                BookingSnapshot.revision,
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
        as_of_revision: int | None = None,
    ) -> Sequence[BookingSnapshot]:
        """All the stay nights of one snapshot day, oldest stay night first: the newest revision of
        each, or the state as of `as_of_revision` (what a run that read that revision saw)."""
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
        if as_of_revision is not None:
            query = query.where(BookingSnapshot.revision <= as_of_revision)
        return self._session.scalars(
            query.distinct(BookingSnapshot.stay_date).order_by(
                BookingSnapshot.stay_date, BookingSnapshot.revision.desc()
            )
        ).all()

    def latest_revision(self, data_source_id: UUID, snapshot_local_date: date) -> int:
        """How many observations this day has had so far: 0 when it has had none."""
        latest = self._session.scalar(
            select(func.max(BookingSnapshot.revision)).where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.snapshot_local_date == snapshot_local_date,
            )
        )
        return latest or 0

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
        rows = self._session.execute(
            query.distinct(BookingSnapshot.snapshot_local_date).order_by(
                BookingSnapshot.snapshot_local_date, BookingSnapshot.revision.desc()
            )
        ).all()
        return [BookingCurvePoint(*row) for row in rows]

    def existing_in_range(
        self,
        data_source_id: UUID,
        snapshot_date_from: date,
        snapshot_date_to: date,
        stay_date_from: date,
        stay_date_to: date,
    ) -> dict[SnapshotKey, StoredSnapshotRef]:
        """What is stored now inside a snapshot-day x stay-night rectangle (one query)."""
        rows = self._session.execute(
            select(
                BookingSnapshot.snapshot_local_date,
                BookingSnapshot.stay_date,
                BookingSnapshot.origin,
                BookingSnapshot.content_fingerprint,
            )
            .where(
                BookingSnapshot.workspace_id == self._tenant.workspace_id,
                BookingSnapshot.data_source_id == data_source_id,
                BookingSnapshot.snapshot_local_date >= snapshot_date_from,
                BookingSnapshot.snapshot_local_date <= snapshot_date_to,
                BookingSnapshot.stay_date >= stay_date_from,
                BookingSnapshot.stay_date <= stay_date_to,
            )
            .distinct(BookingSnapshot.snapshot_local_date, BookingSnapshot.stay_date)
            .order_by(
                BookingSnapshot.snapshot_local_date,
                BookingSnapshot.stay_date,
                BookingSnapshot.revision.desc(),
            )
        ).all()
        return {
            (row.snapshot_local_date, row.stay_date): StoredSnapshotRef(
                row.origin, row.content_fingerprint
            )
            for row in rows
        }

    def insert_if_absent(
        self, property_id: UUID, snapshots: Sequence[NewSnapshot], *, revision: int = 1
    ) -> set[SnapshotKey]:
        """Store the snapshots whose key is free at this revision; never touch a stored one.
        Returns the new keys.

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
                self._row(property_id, snapshot, revision)
                for snapshot in snapshots[start : start + _INSERT_BLOCK]
            ]
            inserted.update((row[0], row[1]) for row in self._session.execute(statement, rows))
        return inserted

    def _row(self, property_id: UUID, snapshot: NewSnapshot, revision: int) -> dict[str, object]:
        content = snapshot.content
        return {
            "workspace_id": self._tenant.workspace_id,
            "property_id": property_id,
            "data_source_id": content.data_source_id,
            "snapshot_local_date": content.snapshot_local_date,
            "revision": revision,
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
            is_current_booking(),
        )
        if statuses is not None:
            query = query.where(Booking.status.in_(sorted(statuses)))
        return [StayRecord(*row) for row in self._session.execute(query)]

    def stay_span(self, property_id: UUID, data_source_id: UUID) -> tuple[date, date] | None:
        """The first and the last NIGHT any current booking of this source covers (every status:
        a cancelled booking still says the file spoke about those dates), or `None` with none.

        What lies outside it is not "zero rooms", it is a period the file says nothing about."""
        first, last_check_out = self._session.execute(
            select(func.min(Booking.check_in), func.max(Booking.check_out)).where(
                Booking.workspace_id == self._tenant.workspace_id,
                Booking.property_id == property_id,
                Booking.data_source_id == data_source_id,
                is_current_booking(),
            )
        ).one()
        if first is None or last_check_out is None or last_check_out <= first:
            return None
        return first, last_check_out - timedelta(days=1)

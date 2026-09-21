import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.bookings.models import MONEY_SCALE

# Sums of many bookings can exceed a single booking's NUMERIC(12, 2): four more integer digits.
SNAPSHOT_MONEY_PRECISION = 16
# Occupancy is a percentage stored with two decimals and deliberately NOT clamped to 100.
OCCUPANCY_PRECISION, OCCUPANCY_SCALE = 14, 2


class SnapshotOrigin(StrEnum):
    """Where a snapshot's content comes from. The two values are never interchangeable.

    OBSERVED                   computed from the canonical bookings at `as_of_at`, the moment
                               NINFA actually looked. Evidence: immutable, never replaced.
    RECONSTRUCTED_APPROXIMATE  inferred *afterwards* for an earlier day from a booking table that
                               only keeps the CURRENT state of each booking. Always approximate,
                               never promoted to OBSERVED, never presented as historical truth.
    """

    OBSERVED = "OBSERVED"
    RECONSTRUCTED_APPROXIMATE = "RECONSTRUCTED_APPROXIMATE"


class RoomInventoryDaily(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How many rooms a property could sell on one stay night (the denominator of occupancy).

    A missing row means "capacity unknown", NOT zero: 0 means the property was closed / had no
    sellable room that night. `rooms_out_of_order` is informational; it is not subtracted from
    `rooms_available` (which is used as declared).
    """

    __tablename__ = "room_inventory_daily"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    rooms_available: Mapped[int] = mapped_column(Integer, nullable=False)
    rooms_out_of_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_room_inventory_daily_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        # One capacity per property and night (also serves range reads by property).
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "stay_date",
            name="uq_room_inventory_daily_workspace_id_property_id_stay_date",
        ),
        CheckConstraint("rooms_available >= 0", name="rooms_available_non_negative"),
        CheckConstraint("rooms_out_of_order >= 0", name="rooms_out_of_order_non_negative"),
    )


class BookingSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """The daily "on the books" state of ONE data source for ONE stay night.

    Row = (data source, snapshot_local_date, stay_date): "as of the end of that property-local
    day, this many rooms were on the books for that night". One row per stay night even when
    nothing is booked (the absence of bookings is data). Immutable (a trigger refuses UPDATE):
    a correction is a new calculation, never an edit.

    The unique key deliberately does NOT contain `origin`: an existing observation and a later
    reconstruction of the same day compete for the same key and the observation wins.

    Metrics are copied at calculation time (in particular `rooms_available`): later changes to
    the inventory or to the bookings never alter a stored snapshot.
    """

    __tablename__ = "booking_snapshots"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    snapshot_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    origin: Mapped[SnapshotOrigin] = mapped_column(enum_column(SnapshotOrigin, 32), nullable=False)

    booking_count_on_books: Mapped[int] = mapped_column(Integer, nullable=False)
    rooms_on_books: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_room_revenue_on_books: Mapped[Decimal] = mapped_column(
        Numeric(SNAPSHOT_MONEY_PRECISION, MONEY_SCALE), nullable=False
    )
    rooms_available: Mapped[int | None] = mapped_column(Integer)
    occupancy_on_books: Mapped[Decimal | None] = mapped_column(
        Numeric(OCCUPANCY_PRECISION, OCCUPANCY_SCALE)
    )
    adr_on_books: Mapped[Decimal | None] = mapped_column(
        Numeric(SNAPSHOT_MONEY_PRECISION, MONEY_SCALE)
    )
    uncertain_booking_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    uncertain_rooms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_booking_snapshots_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        # The data source must belong to the snapshot's own property (and workspace).
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_booking_snapshots_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        # The logical key. No `origin` in it. Its column order also serves "all rows of one
        # snapshot day of a source", so no separate index is needed for that access path.
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "snapshot_local_date",
            "stay_date",
            name="uq_booking_snapshots_data_source_snapshot_date_stay_date",
        ),
        # The booking curve of one stay night: its snapshots ordered by snapshot day.
        Index(
            "ix_booking_snapshots_booking_curve",
            "workspace_id",
            "data_source_id",
            "stay_date",
            "snapshot_local_date",
        ),
        CheckConstraint(values_check("origin", SnapshotOrigin), name="origin_valid"),
        CheckConstraint("booking_count_on_books >= 0", name="booking_count_non_negative"),
        CheckConstraint("rooms_on_books >= 0", name="rooms_on_books_non_negative"),
        CheckConstraint(
            "allocated_room_revenue_on_books >= 0", name="allocated_revenue_non_negative"
        ),
        CheckConstraint(
            "rooms_available IS NULL OR rooms_available >= 0", name="rooms_available_non_negative"
        ),
        CheckConstraint(
            "occupancy_on_books IS NULL OR occupancy_on_books >= 0",
            name="occupancy_non_negative",
        ),
        CheckConstraint("adr_on_books IS NULL OR adr_on_books >= 0", name="adr_non_negative"),
        CheckConstraint("uncertain_booking_count >= 0", name="uncertain_count_non_negative"),
        CheckConstraint("uncertain_rooms >= 0", name="uncertain_rooms_non_negative"),
        # A booking has at least one room, and no booking means no room.
        CheckConstraint(
            "rooms_on_books >= booking_count_on_books"
            " AND (booking_count_on_books > 0 OR rooms_on_books = 0)",
            name="rooms_cover_bookings",
        ),
        CheckConstraint(
            "uncertain_rooms >= uncertain_booking_count"
            " AND (uncertain_booking_count > 0 OR uncertain_rooms = 0)",
            name="uncertain_rooms_cover_bookings",
        ),
        # ADR exists exactly when there is something to divide by (never 0 as a stand-in).
        CheckConstraint(
            "(rooms_on_books > 0) = (adr_on_books IS NOT NULL)", name="adr_defined_with_rooms"
        ),
        # Occupancy exists exactly when the capacity is known and positive.
        CheckConstraint(
            "(rooms_available IS NOT NULL AND rooms_available > 0)"
            " = (occupancy_on_books IS NOT NULL)",
            name="occupancy_defined_with_capacity",
        ),
        # An observation looks at current statuses only: it has nothing "uncertain" in it.
        CheckConstraint(
            "origin <> 'OBSERVED' OR (uncertain_booking_count = 0 AND uncertain_rooms = 0)",
            name="observed_has_no_uncertainty",
        ),
        CheckConstraint("btrim(calculation_version) <> ''", name="calculation_version_not_blank"),
        CheckConstraint(
            "content_fingerprint ~ '^[0-9a-f]{64}$'", name="content_fingerprint_format"
        ),
    )

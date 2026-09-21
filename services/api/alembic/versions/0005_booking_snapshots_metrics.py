"""Gate 3: room inventory and daily booking snapshots.

Adds two tables:

    room_inventory_daily  (workspace_id, property_id, stay_date)   rooms a property could sell
    booking_snapshots     one row per (data source, snapshot day, stay night)

Tenant integrity (see ADR 0006), composite foreign keys carrying workspace_id:

    room_inventory_daily (workspace_id, property_id)                       -> properties
    booking_snapshots    (workspace_id, property_id)                       -> properties
    booking_snapshots    (workspace_id, property_id, data_source_id)       -> data_sources

booking_snapshots is immutable evidence: a trigger refuses every UPDATE (a correction is a new
calculation, never an edit). DELETE is not blocked here: the foreign keys are RESTRICT and
retention belongs to a later gate. Every foreign key is RESTRICT.

The unique key (workspace_id, data_source_id, snapshot_local_date, stay_date) has no `origin`
column on purpose: an observation and a reconstruction of the same day compete for one slot.

Written by hand; tests keep the ORM metadata in sync with it. Gate 0/1/2 objects are untouched.

Revision ID: 0005_booking_snapshots_metrics
Revises: 0004_booking_ingestion
Create Date: 2026-09-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005_booking_snapshots_metrics"
down_revision: str | None = "0004_booking_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


_IMMUTABLE_FUNCTION = """
CREATE FUNCTION booking_snapshots_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'booking_snapshots: a snapshot is immutable evidence and cannot be updated'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # --- room_inventory_daily ------------------------------------------------------------------
    op.create_table(
        "room_inventory_daily",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("stay_date", sa.Date(), nullable=False),
        sa.Column("rooms_available", sa.Integer(), nullable=False),
        sa.Column("rooms_out_of_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_room_inventory_daily")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_room_inventory_daily_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "stay_date",
            name=op.f("uq_room_inventory_daily_workspace_id_property_id_stay_date"),
        ),
        sa.CheckConstraint(
            "rooms_available >= 0",
            name=op.f("ck_room_inventory_daily_rooms_available_non_negative"),
        ),
        sa.CheckConstraint(
            "rooms_out_of_order >= 0",
            name=op.f("ck_room_inventory_daily_rooms_out_of_order_non_negative"),
        ),
    )

    # --- booking_snapshots ---------------------------------------------------------------------
    op.create_table(
        "booking_snapshots",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_local_date", sa.Date(), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stay_date", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("booking_count_on_books", sa.Integer(), nullable=False),
        sa.Column("rooms_on_books", sa.Integer(), nullable=False),
        sa.Column("allocated_room_revenue_on_books", sa.Numeric(16, 2), nullable=False),
        sa.Column("rooms_available", sa.Integer(), nullable=True),
        sa.Column("occupancy_on_books", sa.Numeric(14, 2), nullable=True),
        sa.Column("adr_on_books", sa.Numeric(16, 2), nullable=True),
        sa.Column(
            "uncertain_booking_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("uncertain_rooms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_snapshots")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_booking_snapshots_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_booking_snapshots_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "snapshot_local_date",
            "stay_date",
            name=op.f("uq_booking_snapshots_data_source_snapshot_date_stay_date"),
        ),
        sa.CheckConstraint(
            "origin IN ('OBSERVED', 'RECONSTRUCTED_APPROXIMATE')",
            name=op.f("ck_booking_snapshots_origin_valid"),
        ),
        sa.CheckConstraint(
            "booking_count_on_books >= 0",
            name=op.f("ck_booking_snapshots_booking_count_non_negative"),
        ),
        sa.CheckConstraint(
            "rooms_on_books >= 0", name=op.f("ck_booking_snapshots_rooms_on_books_non_negative")
        ),
        sa.CheckConstraint(
            "allocated_room_revenue_on_books >= 0",
            name=op.f("ck_booking_snapshots_allocated_revenue_non_negative"),
        ),
        sa.CheckConstraint(
            "rooms_available IS NULL OR rooms_available >= 0",
            name=op.f("ck_booking_snapshots_rooms_available_non_negative"),
        ),
        sa.CheckConstraint(
            "occupancy_on_books IS NULL OR occupancy_on_books >= 0",
            name=op.f("ck_booking_snapshots_occupancy_non_negative"),
        ),
        sa.CheckConstraint(
            "adr_on_books IS NULL OR adr_on_books >= 0",
            name=op.f("ck_booking_snapshots_adr_non_negative"),
        ),
        sa.CheckConstraint(
            "uncertain_booking_count >= 0",
            name=op.f("ck_booking_snapshots_uncertain_count_non_negative"),
        ),
        sa.CheckConstraint(
            "uncertain_rooms >= 0", name=op.f("ck_booking_snapshots_uncertain_rooms_non_negative")
        ),
        sa.CheckConstraint(
            "rooms_on_books >= booking_count_on_books"
            " AND (booking_count_on_books > 0 OR rooms_on_books = 0)",
            name=op.f("ck_booking_snapshots_rooms_cover_bookings"),
        ),
        sa.CheckConstraint(
            "uncertain_rooms >= uncertain_booking_count"
            " AND (uncertain_booking_count > 0 OR uncertain_rooms = 0)",
            name=op.f("ck_booking_snapshots_uncertain_rooms_cover_bookings"),
        ),
        sa.CheckConstraint(
            "(rooms_on_books > 0) = (adr_on_books IS NOT NULL)",
            name=op.f("ck_booking_snapshots_adr_defined_with_rooms"),
        ),
        sa.CheckConstraint(
            "(rooms_available IS NOT NULL AND rooms_available > 0)"
            " = (occupancy_on_books IS NOT NULL)",
            name=op.f("ck_booking_snapshots_occupancy_defined_with_capacity"),
        ),
        sa.CheckConstraint(
            "origin <> 'OBSERVED' OR (uncertain_booking_count = 0 AND uncertain_rooms = 0)",
            name=op.f("ck_booking_snapshots_observed_has_no_uncertainty"),
        ),
        sa.CheckConstraint(
            "btrim(calculation_version) <> ''",
            name=op.f("ck_booking_snapshots_calculation_version_not_blank"),
        ),
        sa.CheckConstraint(
            "content_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_booking_snapshots_content_fingerprint_format"),
        ),
    )
    op.create_index(
        op.f("ix_booking_snapshots_booking_curve"),
        "booking_snapshots",
        ["workspace_id", "data_source_id", "stay_date", "snapshot_local_date"],
    )
    op.execute(sa.text(_IMMUTABLE_FUNCTION))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_booking_snapshots_immutable BEFORE UPDATE ON booking_snapshots"
            " FOR EACH ROW EXECUTE FUNCTION booking_snapshots_forbid_update()"
        )
    )


def downgrade() -> None:
    op.drop_table("booking_snapshots")  # drops its trigger with it
    op.execute(sa.text("DROP FUNCTION booking_snapshots_forbid_update()"))
    op.drop_table("room_inventory_daily")

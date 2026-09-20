"""Gate 2: canonical bookings, booking channels, mapping memory and import staging.

Adds booking_channels, booking_mapping_profiles, bookings and booking_import_rows, plus two
unique constraints on Gate 1 tables that exist only to be foreign-key targets:

    import_jobs  (workspace_id, property_id, data_source_id, id)   jobs referenced by bookings
    import_files (workspace_id, import_job_id, id)                 files referenced by staging rows

Tenant integrity (see ADR 0006), all composite foreign keys carrying workspace_id:

    bookings (workspace_id, property_id, data_source_id)      -> data_sources
    bookings (workspace_id, property_id, channel_id)          -> booking_channels
    bookings (workspace_id, property_id, data_source_id, first_import_job_id / last_import_job_id)
                                                              -> import_jobs
    booking_channels (workspace_id, property_id)              -> properties
    booking_mapping_profiles (workspace_id, property_id, data_source_id) -> data_sources
    booking_import_rows (workspace_id, import_job_id, import_file_id)    -> import_files

A booking's identity columns are immutable (trigger), in particular first_import_job_id.
Every foreign key is RESTRICT. Written by hand; tests keep the ORM metadata in sync with it.

Revision ID: 0004_booking_ingestion
Revises: 0003_canonical_data_model
Create Date: 2026-09-21
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_booking_ingestion"
down_revision: str | None = "0003_canonical_data_model"
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


def _jsonb(name: str, *, default: str | None) -> sa.Column[Any]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text(default) if default else None,
    )


_IDENTITY_TRIGGER_FUNCTION = """
CREATE FUNCTION bookings_forbid_identity_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.property_id IS DISTINCT FROM OLD.property_id
       OR NEW.data_source_id IS DISTINCT FROM OLD.data_source_id
       OR NEW.source_record_id IS DISTINCT FROM OLD.source_record_id
       OR NEW.first_import_job_id IS DISTINCT FROM OLD.first_import_job_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'bookings: identity columns are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # --- FK targets on Gate 1 tables -----------------------------------------------------------
    op.create_unique_constraint(
        op.f("uq_import_jobs_workspace_id_property_id_data_source_id_id"),
        "import_jobs",
        ["workspace_id", "property_id", "data_source_id", "id"],
    )
    op.create_unique_constraint(
        op.f("uq_import_files_workspace_id_import_job_id_id"),
        "import_files",
        ["workspace_id", "import_job_id", "id"],
    )

    # --- booking_channels ----------------------------------------------------------------------
    op.create_table(
        "booking_channels",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("channel_type", sa.String(16), nullable=False, server_default=sa.text("'OTHER'")),
        sa.Column("default_commission_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_channels")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_booking_channels_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "normalized_name",
            name=op.f("uq_booking_channels_workspace_id_property_id_normalized_name"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "id",
            name=op.f("uq_booking_channels_workspace_id_property_id_id"),
        ),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_booking_channels_name_not_blank")),
        sa.CheckConstraint(
            "btrim(normalized_name) <> ''",
            name=op.f("ck_booking_channels_normalized_name_not_blank"),
        ),
        sa.CheckConstraint(
            "channel_type IN ('DIRECT', 'OTA', 'TOUR_OPERATOR', 'AGENCY', 'CORPORATE', 'OTHER')",
            name=op.f("ck_booking_channels_channel_type_valid"),
        ),
        sa.CheckConstraint(
            "default_commission_rate IS NULL OR default_commission_rate BETWEEN 0 AND 100",
            name=op.f("ck_booking_channels_default_commission_rate_range"),
        ),
    )

    # --- booking_mapping_profiles --------------------------------------------------------------
    op.create_table(
        "booking_mapping_profiles",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        _jsonb("column_mapping", default=None),
        _jsonb("status_mapping", default="'{}'::jsonb"),
        _jsonb("channel_mapping", default="'{}'::jsonb"),
        _jsonb("format_options", default="'{}'::jsonb"),
        sa.Column("header_signature", sa.String(64), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_mapping_profiles")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_booking_mapping_profiles_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name=op.f("uq_booking_mapping_profiles_workspace_id_data_source_id"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(status_mapping) = 'object'"
            " AND jsonb_typeof(channel_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name=op.f("ck_booking_mapping_profiles_json_shapes"),
        ),
        sa.CheckConstraint(
            "header_signature ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_booking_mapping_profiles_header_signature_format"),
        ),
    )

    # --- bookings ------------------------------------------------------------------------------
    op.create_table(
        "bookings",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rooms", sa.Integer(), nullable=False),
        sa.Column("guests", sa.Integer(), nullable=True),
        sa.Column("room_revenue", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_revenue", sa.Numeric(12, 2), nullable=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("room_type", sa.String(200), nullable=True),
        sa.Column("rate_plan", sa.String(200), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("first_import_job_id", sa.Uuid(), nullable=False),
        sa.Column("last_import_job_id", sa.Uuid(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_bookings_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "channel_id"],
            [
                "booking_channels.workspace_id",
                "booking_channels.property_id",
                "booking_channels.id",
            ],
            name=op.f("fk_bookings_workspace_id_booking_channels"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "first_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name=op.f("fk_bookings_first_import_job"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "last_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name=op.f("fk_bookings_last_import_job"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "source_record_id",
            name=op.f("uq_bookings_workspace_id_data_source_id_source_record_id"),
        ),
        sa.CheckConstraint(
            "btrim(source_record_id) <> ''", name=op.f("ck_bookings_source_record_id_not_blank")
        ),
        sa.CheckConstraint(
            "status IN ('CONFIRMED', 'CANCELLED', 'NO_SHOW', 'CHECKED_IN', 'CHECKED_OUT')",
            name=op.f("ck_bookings_status_valid"),
        ),
        sa.CheckConstraint(
            "check_out > check_in", name=op.f("ck_bookings_check_out_after_check_in")
        ),
        sa.CheckConstraint("rooms > 0", name=op.f("ck_bookings_rooms_positive")),
        sa.CheckConstraint(
            "guests IS NULL OR guests > 0", name=op.f("ck_bookings_guests_positive")
        ),
        sa.CheckConstraint("room_revenue >= 0", name=op.f("ck_bookings_room_revenue_non_negative")),
        sa.CheckConstraint(
            "total_revenue IS NULL OR total_revenue >= 0",
            name=op.f("ck_bookings_total_revenue_non_negative"),
        ),
        sa.CheckConstraint(
            "commission_amount IS NULL OR commission_amount >= 0",
            name=op.f("ck_bookings_commission_amount_non_negative"),
        ),
        sa.CheckConstraint(
            "commission_rate IS NULL OR commission_rate BETWEEN 0 AND 100",
            name=op.f("ck_bookings_commission_rate_range"),
        ),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR status = 'CANCELLED'",
            name=op.f("ck_bookings_cancelled_at_requires_cancelled"),
        ),
        sa.CheckConstraint(
            "room_type IS NULL OR btrim(room_type) <> ''",
            name=op.f("ck_bookings_room_type_not_blank"),
        ),
        sa.CheckConstraint(
            "rate_plan IS NULL OR btrim(rate_plan) <> ''",
            name=op.f("ck_bookings_rate_plan_not_blank"),
        ),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_bookings_source_fingerprint_format"),
        ),
    )
    op.create_index(
        op.f("ix_bookings_workspace_id_property_id_check_in"),
        "bookings",
        ["workspace_id", "property_id", "check_in"],
    )
    op.create_index(
        op.f("ix_bookings_workspace_id_property_id_status"),
        "bookings",
        ["workspace_id", "property_id", "status"],
    )
    op.execute(sa.text(_IDENTITY_TRIGGER_FUNCTION))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_bookings_identity_immutable BEFORE UPDATE ON bookings"
            " FOR EACH ROW EXECUTE FUNCTION bookings_forbid_identity_change()"
        )
    )

    # --- booking_import_rows (staging) ---------------------------------------------------------
    op.create_table(
        "booking_import_rows",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("import_file_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        _jsonb("mapped_payload", default=None),
        sa.Column("normalized_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_status", sa.String(16), nullable=False),
        _jsonb("validation_errors", default="'[]'::jsonb"),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_import_rows")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name=op.f("fk_booking_import_rows_workspace_id_import_files"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "row_number",
            name=op.f("uq_booking_import_rows_workspace_id_import_file_id_row_number"),
        ),
        sa.CheckConstraint(
            "row_number > 0", name=op.f("ck_booking_import_rows_row_number_positive")
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'IMPORTED')",
            name=op.f("ck_booking_import_rows_status_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name=op.f("ck_booking_import_rows_payload_shapes"),
        ),
        sa.CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name=op.f("ck_booking_import_rows_status_consistent"),
        ),
    )
    op.create_index(
        op.f("ix_booking_import_rows_workspace_id_import_job_id"),
        "booking_import_rows",
        ["workspace_id", "import_job_id"],
    )


def downgrade() -> None:
    # Children first; Gate 0/1 objects are untouched apart from the two extra unique keys.
    op.drop_table("booking_import_rows")
    op.drop_table("bookings")
    op.execute(sa.text("DROP FUNCTION bookings_forbid_identity_change()"))
    op.drop_table("booking_mapping_profiles")
    op.drop_table("booking_channels")
    op.drop_constraint(
        op.f("uq_import_files_workspace_id_import_job_id_id"), "import_files", type_="unique"
    )
    op.drop_constraint(
        op.f("uq_import_jobs_workspace_id_property_id_data_source_id_id"),
        "import_jobs",
        type_="unique",
    )

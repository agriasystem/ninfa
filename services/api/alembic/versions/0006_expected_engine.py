"""Gate 4: Expected Engine baselines and their comparables.

Adds two tables:

    booking_expected_baselines    what was normally on the books, for ONE observed target snapshot
    booking_expected_comparables  the historical snapshots a baseline actually used

and, on the Gate 3 table `booking_snapshots`, one unique constraint that exists only to be a
foreign-key target (an addition; no existing object is altered):

    booking_snapshots (workspace_id, property_id, data_source_id, id, origin)

Tenant integrity (see ADR 0006), composite foreign keys carrying workspace_id, all RESTRICT:

    baselines   (workspace, property)                                  -> properties
    baselines   (workspace, property, data_source)                     -> data_sources
    baselines   (workspace, property, data_source, target_snapshot, target_origin)
                                                                       -> booking_snapshots
    comparables (workspace, property, data_source, baseline)           -> baselines
    comparables (workspace, property, data_source, snapshot, origin)   -> booking_snapshots

`target_origin` is CHECKed to 'OBSERVED', so the database itself refuses a baseline whose target
is a reconstruction; a comparable's `origin` must equal its snapshot's. Both new tables are
immutable evidence: a trigger refuses every UPDATE (a change of algorithm is a new
calculation_version, never an edit). DELETE is not blocked: the foreign keys are RESTRICT and
retention belongs to a later gate.

Written by hand; tests keep the ORM metadata in sync with it. Migrations 0001-0005 are untouched.

Revision ID: 0006_expected_engine
Revises: 0005_booking_snapshots_metrics
Create Date: 2026-09-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006_expected_engine"
down_revision: str | None = "0005_booking_snapshots_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


_IMMUTABLE_FUNCTION = """
CREATE FUNCTION booking_expected_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'expected engine: a baseline and its comparables are immutable evidence'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # --- foreign-key target on the Gate 3 table -------------------------------------------------
    op.create_unique_constraint(
        op.f("uq_booking_snapshots_source_id_origin"),
        "booking_snapshots",
        ["workspace_id", "property_id", "data_source_id", "id", "origin"],
    )

    # --- booking_expected_baselines -------------------------------------------------------------
    op.create_table(
        "booking_expected_baselines",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("target_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("target_origin", sa.String(32), nullable=False),
        sa.Column("target_snapshot_local_date", sa.Date(), nullable=False),
        sa.Column("target_stay_date", sa.Date(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expected_rooms_on_books", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_lower", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_upper", sa.Numeric(12, 2), nullable=True),
        sa.Column("iqr", sa.Numeric(12, 2), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("observed_sample_size", sa.Integer(), nullable=False),
        sa.Column("reconstructed_sample_size", sa.Integer(), nullable=False),
        sa.Column("rejected_uncertain_count", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("confidence_band", sa.String(8), nullable=True),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("comparable_fingerprint", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_expected_baselines")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_booking_expected_baselines_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_booking_expected_baselines_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "property_id",
                "data_source_id",
                "target_snapshot_id",
                "target_origin",
            ],
            [
                "booking_snapshots.workspace_id",
                "booking_snapshots.property_id",
                "booking_snapshots.data_source_id",
                "booking_snapshots.id",
                "booking_snapshots.origin",
            ],
            name=op.f("fk_booking_expected_baselines_target_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "target_snapshot_id",
            "calculation_version",
            name=op.f("uq_booking_expected_baselines_target_version"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "data_source_id",
            "id",
            name=op.f("uq_booking_expected_baselines_ws_prop_src_id"),
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'INSUFFICIENT_DATA')",
            name=op.f("ck_booking_expected_baselines_status_valid"),
        ),
        sa.CheckConstraint(
            "confidence_band IS NULL OR confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name=op.f("ck_booking_expected_baselines_confidence_band_valid"),
        ),
        sa.CheckConstraint(
            "target_origin = 'OBSERVED'",
            name=op.f("ck_booking_expected_baselines_target_is_observed"),
        ),
        sa.CheckConstraint(
            "lead_time_days >= 0", name=op.f("ck_booking_expected_baselines_lead_time_non_negative")
        ),
        sa.CheckConstraint(
            "lead_time_days = target_stay_date - target_snapshot_local_date",
            name=op.f("ck_booking_expected_baselines_lead_time_matches_dates"),
        ),
        sa.CheckConstraint(
            "sample_size >= 0 AND observed_sample_size >= 0 AND reconstructed_sample_size >= 0"
            " AND rejected_uncertain_count >= 0",
            name=op.f("ck_booking_expected_baselines_sample_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "sample_size = observed_sample_size + reconstructed_sample_size",
            name=op.f("ck_booking_expected_baselines_sample_size_is_sum"),
        ),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name=op.f("ck_booking_expected_baselines_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "(expected_rooms_on_books IS NULL OR expected_rooms_on_books >= 0)"
            " AND (expected_lower IS NULL OR expected_lower >= 0)"
            " AND (expected_upper IS NULL OR expected_upper >= 0)"
            " AND (iqr IS NULL OR iqr >= 0)",
            name=op.f("ck_booking_expected_baselines_statistics_non_negative"),
        ),
        sa.CheckConstraint(
            "expected_lower IS NULL OR (expected_lower <= expected_rooms_on_books"
            " AND expected_rooms_on_books <= expected_upper)",
            name=op.f("ck_booking_expected_baselines_range_ordered"),
        ),
        sa.CheckConstraint(
            "iqr IS NULL OR iqr = expected_upper - expected_lower",
            name=op.f("ck_booking_expected_baselines_iqr_is_range_width"),
        ),
        sa.CheckConstraint(
            "status <> 'READY' OR (expected_rooms_on_books IS NOT NULL"
            " AND expected_lower IS NOT NULL AND expected_upper IS NOT NULL AND iqr IS NOT NULL"
            " AND confidence_band IS NOT NULL AND sample_size >= 5)",
            name=op.f("ck_booking_expected_baselines_ready_has_statistics"),
        ),
        sa.CheckConstraint(
            "status <> 'INSUFFICIENT_DATA' OR (expected_rooms_on_books IS NULL"
            " AND expected_lower IS NULL AND expected_upper IS NULL AND iqr IS NULL"
            " AND confidence_score = 0 AND confidence_band IS NULL AND sample_size < 5)",
            name=op.f("ck_booking_expected_baselines_insufficient_has_no_statistics"),
        ),
        sa.CheckConstraint(
            "btrim(method) <> ''", name=op.f("ck_booking_expected_baselines_method_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(calculation_version) <> ''",
            name=op.f("ck_booking_expected_baselines_calculation_version_not_blank"),
        ),
        sa.CheckConstraint(
            "comparable_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_booking_expected_baselines_comparable_fingerprint_format"),
        ),
    )
    op.create_index(
        op.f("ix_booking_expected_baselines_snapshot_date"),
        "booking_expected_baselines",
        ["workspace_id", "data_source_id", "target_snapshot_local_date"],
    )
    op.create_index(
        op.f("ix_booking_expected_baselines_stay_date"),
        "booking_expected_baselines",
        ["workspace_id", "data_source_id", "target_stay_date"],
    )

    # --- booking_expected_comparables -----------------------------------------------------------
    op.create_table(
        "booking_expected_comparables",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("rooms_on_books", sa.Integer(), nullable=False),
        sa.Column("recency_rank", sa.Integer(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_expected_comparables")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "baseline_id"],
            [
                "booking_expected_baselines.workspace_id",
                "booking_expected_baselines.property_id",
                "booking_expected_baselines.data_source_id",
                "booking_expected_baselines.id",
            ],
            name=op.f("fk_booking_expected_comparables_baseline"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "snapshot_id", "origin"],
            [
                "booking_snapshots.workspace_id",
                "booking_snapshots.property_id",
                "booking_snapshots.data_source_id",
                "booking_snapshots.id",
                "booking_snapshots.origin",
            ],
            name=op.f("fk_booking_expected_comparables_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "baseline_id",
            "snapshot_id",
            name=op.f("uq_booking_expected_comparables_baseline_snapshot"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "baseline_id",
            "recency_rank",
            name=op.f("uq_booking_expected_comparables_baseline_rank"),
        ),
        sa.CheckConstraint(
            "origin IN ('OBSERVED', 'RECONSTRUCTED_APPROXIMATE')",
            name=op.f("ck_booking_expected_comparables_origin_valid"),
        ),
        sa.CheckConstraint(
            "rooms_on_books >= 0",
            name=op.f("ck_booking_expected_comparables_rooms_on_books_non_negative"),
        ),
        sa.CheckConstraint(
            "recency_rank >= 1", name=op.f("ck_booking_expected_comparables_recency_rank_positive")
        ),
    )

    # --- immutability ---------------------------------------------------------------------------
    op.execute(sa.text(_IMMUTABLE_FUNCTION))
    for table in ("booking_expected_baselines", "booking_expected_comparables"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table}"
                " FOR EACH ROW EXECUTE FUNCTION booking_expected_forbid_update()"
            )
        )


def downgrade() -> None:
    # Children first; the triggers go with their tables. Gate 0-3 objects are untouched apart
    # from the extra unique key added to booking_snapshots.
    op.drop_table("booking_expected_comparables")
    op.drop_table("booking_expected_baselines")
    op.execute(sa.text("DROP FUNCTION booking_expected_forbid_update()"))
    op.drop_constraint(
        op.f("uq_booking_snapshots_source_id_origin"), "booking_snapshots", type_="unique"
    )

"""Gate 8: labor ingestion (canonical snapshots/entries, mapping profile, staging).

Adds four tables:

    labor_snapshots          what NINFA knew of a data source's staffing plan/actuals on ONE
                              local date (immutable evidence)
    labor_entries            canonical rows of a snapshot: work date, category, minutes, cost
                              (immutable; NO employee identity)
    labor_mapping_profiles   the confirmed reading of a LABOR data source's CSV/XLSX files
    labor_import_rows        data-minimised staging of a labor import

Tenant integrity (see ADR 0006), composite foreign keys carrying workspace_id, all RESTRICT:

    labor_snapshots     (workspace, property)                                  -> properties
    labor_snapshots     (workspace, property, data_source)                     -> data_sources
    labor_snapshots     (workspace, property, data_source, import_job)         -> import_jobs
    labor_snapshots     (workspace, import_job, import_file)                   -> import_files
    labor_entries       (workspace, labor_snapshot)                            -> labor_snapshots
    labor_mapping_profiles (workspace, property, data_source)                  -> data_sources
    labor_import_rows   (workspace, import_job, import_file)                   -> import_files

Labor snapshots and their entries are immutable evidence: a trigger refuses every UPDATE.
Mapping profiles are not (configuration evolves). DELETE is not blocked: the foreign keys are
RESTRICT and retention belongs to a later gate.

Written by hand; tests keep the ORM metadata in sync with it. Migrations 0001-0007 are untouched.

Revision ID: 0008_labor_ingestion
Revises: 0007_invoice_supplier_ingestion
Create Date: 2026-09-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_labor_ingestion"
down_revision: str | None = "0007_invoice_supplier_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABOR_CATEGORIES = (
    "'HOUSEKEEPING', 'FRONT_OFFICE', 'FOOD_BEVERAGE', 'KITCHEN', 'MAINTENANCE', 'MANAGEMENT',"
    " 'SPA_WELLNESS', 'OTHER'"
)
LABOR_CLASSIFICATION_METHODS = (
    "'EXPLICIT_SOURCE', 'ROLE_MAPPING', 'DETERMINISTIC_RULE', 'UNCLASSIFIED'"
)
IMPORT_ROW_STATUSES = "'VALID', 'INVALID', 'IMPORTED'"


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
CREATE FUNCTION labor_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'labor: a canonical labor snapshot and its entries are immutable evidence'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # --- labor_snapshots --------------------------------------------------------------------
    op.create_table(
        "labor_snapshots",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_local_date", sa.Date(), nullable=False),
        sa.Column("source_import_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_import_file_id", sa.Uuid(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labor_snapshots")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_labor_snapshots_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_labor_snapshots_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "source_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name=op.f("fk_labor_snapshots_source_import_job"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_import_job_id", "source_import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name=op.f("fk_labor_snapshots_source_import_file"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "snapshot_local_date",
            name=op.f("uq_labor_snapshots_data_source_id_snapshot_local_date"),
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_labor_snapshots_workspace_id_id")),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_labor_snapshots_source_fingerprint_format"),
        ),
    )
    op.create_index(
        op.f("ix_labor_snapshots_property_source_date"),
        "labor_snapshots",
        ["workspace_id", "property_id", "data_source_id", "snapshot_local_date"],
    )

    # --- labor_entries -----------------------------------------------------------------------
    op.create_table(
        "labor_entries",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("labor_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("role_raw", sa.String(200), nullable=True),
        sa.Column("role_normalized", sa.String(200), nullable=True),
        sa.Column("labor_category", sa.String(20), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("planned_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("actual_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("classification_method", sa.String(20), nullable=False),
        sa.Column("classification_confidence", sa.Numeric(5, 2), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labor_entries")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "labor_snapshot_id"],
            ["labor_snapshots.workspace_id", "labor_snapshots.id"],
            name=op.f("fk_labor_entries_workspace_id_labor_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "labor_snapshot_id",
            "source_row_number",
            name=op.f("uq_labor_entries_workspace_id_snapshot_id_row_number"),
        ),
        sa.CheckConstraint(
            "source_row_number > 0", name=op.f("ck_labor_entries_source_row_number_positive")
        ),
        sa.CheckConstraint(
            "planned_minutes IS NULL OR planned_minutes >= 0",
            name=op.f("ck_labor_entries_planned_minutes_non_negative"),
        ),
        sa.CheckConstraint(
            "actual_minutes IS NULL OR actual_minutes >= 0",
            name=op.f("ck_labor_entries_actual_minutes_non_negative"),
        ),
        sa.CheckConstraint(
            "planned_minutes IS NOT NULL OR actual_minutes IS NOT NULL",
            name=op.f("ck_labor_entries_planned_or_actual_minutes_present"),
        ),
        sa.CheckConstraint(
            "planned_cost IS NULL OR planned_cost >= 0",
            name=op.f("ck_labor_entries_planned_cost_non_negative"),
        ),
        sa.CheckConstraint(
            "actual_cost IS NULL OR actual_cost >= 0",
            name=op.f("ck_labor_entries_actual_cost_non_negative"),
        ),
        sa.CheckConstraint(
            "(planned_cost IS NULL AND actual_cost IS NULL) OR currency IS NOT NULL",
            name=op.f("ck_labor_entries_cost_requires_currency"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_labor_entries_currency_format"),
        ),
        sa.CheckConstraint(
            "role_raw IS NULL OR btrim(role_raw) <> ''",
            name=op.f("ck_labor_entries_role_raw_not_blank"),
        ),
        sa.CheckConstraint(
            f"labor_category IN ({LABOR_CATEGORIES})",
            name=op.f("ck_labor_entries_labor_category_valid"),
        ),
        sa.CheckConstraint(
            f"classification_method IN ({LABOR_CLASSIFICATION_METHODS})",
            name=op.f("ck_labor_entries_classification_method_valid"),
        ),
        sa.CheckConstraint(
            "classification_confidence BETWEEN 0 AND 100",
            name=op.f("ck_labor_entries_classification_confidence_range"),
        ),
        sa.CheckConstraint(
            "(classification_method = 'UNCLASSIFIED') = (classification_confidence = 0)"
            " AND (classification_method <> 'UNCLASSIFIED' OR labor_category = 'OTHER')",
            name=op.f("ck_labor_entries_classification_consistent"),
        ),
    )
    op.create_index(
        op.f("ix_labor_entries_workspace_id_snapshot_id"),
        "labor_entries",
        ["workspace_id", "labor_snapshot_id"],
    )
    op.create_index(
        op.f("ix_labor_entries_workspace_id_work_date_category"),
        "labor_entries",
        ["workspace_id", "work_date", "labor_category"],
    )
    op.create_index(
        op.f("ix_labor_entries_snapshot_work_date_category"),
        "labor_entries",
        ["workspace_id", "labor_snapshot_id", "work_date", "labor_category"],
    )

    # --- labor_mapping_profiles ----------------------------------------------------------------
    op.create_table(
        "labor_mapping_profiles",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=False),
        sa.Column(
            "role_mapping",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "format_options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("header_signature", sa.String(64), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labor_mapping_profiles")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_labor_mapping_profiles_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name=op.f("uq_labor_mapping_profiles_workspace_id_data_source_id"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(role_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name=op.f("ck_labor_mapping_profiles_json_shapes"),
        ),
        sa.CheckConstraint(
            "header_signature ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_labor_mapping_profiles_header_signature_format"),
        ),
    )

    # --- labor_import_rows -----------------------------------------------------------------------
    op.create_table(
        "labor_import_rows",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("import_file_id", sa.Uuid(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("mapped_payload", postgresql.JSONB(none_as_null=False), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "validation_warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labor_import_rows")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name=op.f("fk_labor_import_rows_workspace_id_import_files"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "source_row_number",
            name=op.f("uq_labor_import_rows_workspace_id_import_file_id_row_number"),
        ),
        sa.CheckConstraint(
            "source_row_number > 0", name=op.f("ck_labor_import_rows_source_row_number_positive")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND jsonb_typeof(validation_warnings) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name=op.f("ck_labor_import_rows_payload_shapes"),
        ),
        sa.CheckConstraint(
            f"validation_status IN ({IMPORT_ROW_STATUSES})",
            name=op.f("ck_labor_import_rows_status_valid"),
        ),
        sa.CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name=op.f("ck_labor_import_rows_status_consistent"),
        ),
    )
    op.create_index(
        op.f("ix_labor_import_rows_workspace_id_import_job_id"),
        "labor_import_rows",
        ["workspace_id", "import_job_id"],
    )

    # --- immutability of the canonical labor evidence -------------------------------------------
    op.execute(sa.text(_IMMUTABLE_FUNCTION))
    for table in ("labor_snapshots", "labor_entries"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table}"
                " FOR EACH ROW EXECUTE FUNCTION labor_forbid_update()"
            )
        )


def downgrade() -> None:
    # Children first; the triggers go with their tables. Gate 0-7 objects are untouched.
    op.drop_table("labor_import_rows")
    op.drop_table("labor_mapping_profiles")
    op.drop_table("labor_entries")
    op.drop_table("labor_snapshots")
    op.execute(sa.text("DROP FUNCTION labor_forbid_update()"))

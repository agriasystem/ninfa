"""The canonical labor entities and their import bookkeeping (Gate 8, Part A).

A LaborSnapshot is what NINFA knew of the staffing plan/actuals of ONE data source on ONE local
date: immutable evidence (a trigger refuses every UPDATE), identified by
(workspace, data_source, snapshot_local_date). A LaborEntry is one canonical row of that snapshot:
a work date, a category and its planned/actual minutes and optional cost. NEITHER carries an
employee identity: V1 reasons about aggregate scheduled/worked minutes, never about a person.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.bookings.models import ImportRowStatus
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod

# Cost: NUMERIC(14, 2), the same scale as the Gate 6 invoice amounts. No FX in V1: `currency` is
# carried alongside every amount and is required whenever a cost is present.
COST_PRECISION, COST_SCALE = 14, 2


class LaborSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """What NINFA knew of the staffing plan/actuals of ONE data source, on ONE local date.

    Immutable (a trigger refuses UPDATE): a revision of the plan arrives as a NEW snapshot date,
    never an edit. `snapshot_local_date` is always given explicitly by the caller (never
    `date.today()` or a file's mtime): determinism, replay and backtesting all depend on it.
    """

    __tablename__ = "labor_snapshots"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    snapshot_local_date: Mapped[date] = mapped_column(Date, nullable=False)

    source_import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_import_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_labor_snapshots_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_labor_snapshots_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "source_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name="fk_labor_snapshots_source_import_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_import_job_id", "source_import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name="fk_labor_snapshots_source_import_file",
            ondelete="RESTRICT",
        ),
        # The snapshot identity (V1: one snapshot per data source and local date).
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "snapshot_local_date",
            name="uq_labor_snapshots_data_source_id_snapshot_local_date",
        ),
        # Foreign-key target of LaborEntry.
        UniqueConstraint("workspace_id", "id", name="uq_labor_snapshots_workspace_id_id"),
        # "The snapshot of this property/source as of this date" lookup.
        Index(
            "ix_labor_snapshots_property_source_date",
            "workspace_id",
            "property_id",
            "data_source_id",
            "snapshot_local_date",
        ),
        CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="source_fingerprint_format"),
    )


class LaborEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One canonical row of a labor export: a work date, a category, its minutes and cost.

    Immutable (a trigger refuses UPDATE). No employee identity: `role_raw` is a free-text shift
    label from the source (never a person's name), and V1 does not even require it when
    `labor_category` was explicit in the source. `planned_minutes`/`actual_minutes` are kept
    strictly apart (never substituted for one another); at least one must be present.
    """

    __tablename__ = "labor_entries"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    labor_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    work_date: Mapped[date] = mapped_column(Date, nullable=False)

    role_raw: Mapped[str | None] = mapped_column(String(200))
    role_normalized: Mapped[str | None] = mapped_column(String(200))
    labor_category: Mapped[LaborCategory] = mapped_column(
        enum_column(LaborCategory, 20), nullable=False
    )

    planned_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)

    planned_cost: Mapped[Decimal | None] = mapped_column(Numeric(COST_PRECISION, COST_SCALE))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(COST_PRECISION, COST_SCALE))
    currency: Mapped[str | None] = mapped_column(String(3))

    classification_method: Mapped[LaborClassificationMethod] = mapped_column(
        enum_column(LaborClassificationMethod, 20), nullable=False
    )
    classification_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "labor_snapshot_id"],
            ["labor_snapshots.workspace_id", "labor_snapshots.id"],
            name="fk_labor_entries_workspace_id_labor_snapshots",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "labor_snapshot_id",
            "source_row_number",
            name="uq_labor_entries_workspace_id_snapshot_id_row_number",
        ),
        Index("ix_labor_entries_workspace_id_snapshot_id", "workspace_id", "labor_snapshot_id"),
        Index(
            "ix_labor_entries_workspace_id_work_date_category",
            "workspace_id",
            "work_date",
            "labor_category",
        ),
        Index(
            "ix_labor_entries_snapshot_work_date_category",
            "workspace_id",
            "labor_snapshot_id",
            "work_date",
            "labor_category",
        ),
        CheckConstraint("source_row_number > 0", name="source_row_number_positive"),
        CheckConstraint(
            "planned_minutes IS NULL OR planned_minutes >= 0", name="planned_minutes_non_negative"
        ),
        CheckConstraint(
            "actual_minutes IS NULL OR actual_minutes >= 0", name="actual_minutes_non_negative"
        ),
        CheckConstraint(
            "planned_minutes IS NOT NULL OR actual_minutes IS NOT NULL",
            name="planned_or_actual_minutes_present",
        ),
        CheckConstraint(
            "planned_cost IS NULL OR planned_cost >= 0", name="planned_cost_non_negative"
        ),
        CheckConstraint("actual_cost IS NULL OR actual_cost >= 0", name="actual_cost_non_negative"),
        CheckConstraint(
            "(planned_cost IS NULL AND actual_cost IS NULL) OR currency IS NOT NULL",
            name="cost_requires_currency",
        ),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("role_raw IS NULL OR btrim(role_raw) <> ''", name="role_raw_not_blank"),
        CheckConstraint(values_check("labor_category", LaborCategory), name="labor_category_valid"),
        CheckConstraint(
            values_check("classification_method", LaborClassificationMethod),
            name="classification_method_valid",
        ),
        CheckConstraint(
            "classification_confidence BETWEEN 0 AND 100", name="classification_confidence_range"
        ),
        # UNCLASSIFIED <=> confidence 0 (and then the category is OTHER).
        CheckConstraint(
            "(classification_method = 'UNCLASSIFIED') = (classification_confidence = 0)"
            " AND (classification_method <> 'UNCLASSIFIED' OR labor_category = 'OTHER')",
            name="classification_consistent",
        ),
    )


class LaborMappingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The confirmed way to read one LABOR data source's structured files. Configuration only."""

    __tablename__ = "labor_mapping_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    role_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    format_options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    header_signature: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_labor_mapping_profiles_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name="uq_labor_mapping_profiles_workspace_id_data_source_id",
        ),
        CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(role_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name="json_shapes",
        ),
        CheckConstraint("header_signature ~ '^[0-9a-f]{64}$'", name="header_signature_format"),
    )


class LaborImportRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Staging of one source row of a labor import.

    Data minimisation: `mapped_payload` holds ONLY the values of columns explicitly mapped to
    canonical fields. An employee name, e-mail, phone, tax code, address or medical note that a
    source file carries but that was not mapped never reaches this table (or anywhere else).
    """

    __tablename__ = "labor_import_rows"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mapped_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    validation_status: Mapped[ImportRowStatus] = mapped_column(
        enum_column(ImportRowStatus, 16), nullable=False
    )
    validation_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_warnings: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name="fk_labor_import_rows_workspace_id_import_files",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "source_row_number",
            name="uq_labor_import_rows_workspace_id_import_file_id_row_number",
        ),
        Index("ix_labor_import_rows_workspace_id_import_job_id", "workspace_id", "import_job_id"),
        CheckConstraint("source_row_number > 0", name="source_row_number_positive"),
        CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND jsonb_typeof(validation_warnings) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name="payload_shapes",
        ),
        CheckConstraint(values_check("validation_status", ImportRowStatus), name="status_valid"),
        CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name="status_consistent",
        ),
    )

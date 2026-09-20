import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check

if TYPE_CHECKING:
    from app.modules.properties.models import Property


class DataSourceDomain(StrEnum):
    BOOKINGS = "BOOKINGS"
    COSTS = "COSTS"
    LABOR = "LABOR"


class DataSourceType(StrEnum):
    FILE_UPLOAD = "FILE_UPLOAD"


class ImportJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DataSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A logical source of data for one property. No real connection exists in Gate 1.

    Tenant integrity: `workspace_id` is explicit and the composite foreign key
    (workspace_id, property_id) -> properties(workspace_id, id) makes it impossible for a
    source of workspace A to point at a property of workspace B.
    """

    __tablename__ = "data_sources"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[DataSourceDomain] = mapped_column(
        enum_column(DataSourceDomain, 16), nullable=False
    )
    source_type: Mapped[DataSourceType] = mapped_column(
        enum_column(DataSourceType, 32), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )

    property: Mapped["Property"] = relationship("Property", viewonly=True)
    import_jobs: Mapped[list["ImportJob"]] = relationship("ImportJob", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_data_sources_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        # Target of import_jobs' composite FK; also serves "sources of a property in a workspace".
        UniqueConstraint(
            "workspace_id", "property_id", "id", name="uq_data_sources_workspace_id_property_id_id"
        ),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint(values_check("domain", DataSourceDomain), name="domain_valid"),
        CheckConstraint(values_check("source_type", DataSourceType), name="source_type_valid"),
    )


class ImportJob(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Metadata/lifecycle of a future import. No parsing or execution exists in Gate 1.

    Tenant integrity: (workspace_id, property_id, data_source_id) is one composite foreign key
    to data_sources(workspace_id, property_id, id). A single constraint therefore guarantees
    that the data source is in the job's workspace *and* that the job's property is the data
    source's own property.
    """

    __tablename__ = "import_jobs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[ImportJobStatus] = mapped_column(
        enum_column(ImportJobStatus, 16),
        nullable=False,
        default=ImportJobStatus.PENDING,
        server_default=ImportJobStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)

    data_source: Mapped["DataSource"] = relationship("DataSource", viewonly=True)
    files: Mapped[list["ImportFile"]] = relationship("ImportFile", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_import_jobs_workspace_id_data_sources",
            ondelete="RESTRICT",  # operational records are preserved
        ),
        # Target of import_files' composite FK.
        UniqueConstraint("workspace_id", "id", name="uq_import_jobs_workspace_id_id"),
        # Gate 2: target of the composite FKs that tie a booking to the jobs that created/updated
        # it, so a job can only be referenced by rows of its own data source and property.
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "data_source_id",
            "id",
            name="uq_import_jobs_workspace_id_property_id_data_source_id_id",
        ),
        CheckConstraint(values_check("status", ImportJobStatus), name="status_valid"),
        CheckConstraint(
            "(status = 'PENDING' AND started_at IS NULL AND finished_at IS NULL)"
            " OR (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL)"
            " OR (status IN ('SUCCEEDED', 'FAILED') AND finished_at IS NOT NULL)",
            name="lifecycle_consistent",
        ),
        CheckConstraint(
            "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            "(error_code IS NULL AND error_message IS NULL) OR status = 'FAILED'",
            name="error_only_when_failed",
        ),
        # Listing/claiming jobs by state inside a workspace.
        Index("ix_import_jobs_workspace_id_status", "workspace_id", "status"),
    )


class ImportFile(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Metadata of a file attached to an import job. Nothing is stored anywhere yet:
    `storage_key` is a placeholder for the future object storage.
    """

    __tablename__ = "import_files"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(1024))

    import_job: Mapped["ImportJob"] = relationship("ImportJob", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "import_job_id"],
            ["import_jobs.workspace_id", "import_jobs.id"],
            name="fk_import_files_workspace_id_import_jobs",
            ondelete="RESTRICT",
        ),
        # Gate 2: target of the staging rows' composite FK, which pins a staged row's file to
        # the staged row's job and workspace with a single key.
        UniqueConstraint(
            "workspace_id",
            "import_job_id",
            "id",
            name="uq_import_files_workspace_id_import_job_id_id",
        ),
        CheckConstraint("btrim(original_filename) <> ''", name="original_filename_not_blank"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        # Files of a job (also serves the FK's RESTRICT check on import_jobs).
        Index("ix_import_files_workspace_id_import_job_id", "workspace_id", "import_job_id"),
        # Future duplicate detection: "was this exact file already imported in this workspace?".
        # Scoped by workspace on purpose and NOT unique: the same file may be imported twice
        # (re-run, different property) and hashes must never be compared across tenants.
        Index(
            "ix_import_files_workspace_id_sha256",
            "workspace_id",
            "sha256",
            postgresql_where=text("sha256 IS NOT NULL"),
        ),
    )

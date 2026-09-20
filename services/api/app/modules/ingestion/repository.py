from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSource, ImportFile, ImportJob, ImportJobStatus
from app.modules.ingestion.schemas import DataSourceCreate, ImportFileCreate, ImportJobCreate
from app.modules.properties.models import Property

# Parents are looked up with the tenant scope before a child is created, so wrong-tenant input
# is reported as NotFoundError. The composite foreign keys remain the backstop: they reject an
# inconsistent row even if a caller bypasses these repositories (see the DB-level tests).


class DataSourceRepository:
    """Data sources of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add(self, data: DataSourceCreate) -> DataSource:
        prop = self._session.scalar(
            select(Property).where(
                Property.workspace_id == self._tenant.workspace_id,
                Property.id == data.property_id,
            )
        )
        if prop is None:
            raise NotFoundError("Property")
        data_source = DataSource(
            workspace_id=self._tenant.workspace_id,
            property_id=prop.id,
            name=data.name,
            domain=data.domain,
            source_type=data.source_type,
        )
        self._session.add(data_source)
        self._session.flush()
        return data_source

    def get(self, data_source_id: UUID) -> DataSource | None:
        return self._session.scalar(
            select(DataSource).where(
                DataSource.workspace_id == self._tenant.workspace_id,
                DataSource.id == data_source_id,
            )
        )

    def list_all(
        self, *, property_id: UUID | None = None, include_inactive: bool = False
    ) -> Sequence[DataSource]:
        query = select(DataSource).where(DataSource.workspace_id == self._tenant.workspace_id)
        if property_id is not None:
            query = query.where(DataSource.property_id == property_id)
        if not include_inactive:
            query = query.where(DataSource.is_active.is_(True))
        return self._session.scalars(query.order_by(DataSource.name)).all()

    def deactivate(self, data_source_id: UUID) -> DataSource:
        """Data sources are switched off, never deleted."""
        data_source = self.get(data_source_id)
        if data_source is None:
            raise NotFoundError("Data source")
        data_source.is_active = False
        self._session.flush()
        return data_source


class ImportJobRepository:
    """Import jobs of ONE workspace (metadata/lifecycle only)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add(self, data: ImportJobCreate) -> ImportJob:
        data_source = self._session.scalar(
            select(DataSource).where(
                DataSource.workspace_id == self._tenant.workspace_id,
                DataSource.id == data.data_source_id,
            )
        )
        if data_source is None:
            raise NotFoundError("Data source")
        job = ImportJob(
            workspace_id=self._tenant.workspace_id,
            property_id=data_source.property_id,
            data_source_id=data_source.id,
            status=ImportJobStatus.PENDING,
        )
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, import_job_id: UUID) -> ImportJob | None:
        return self._session.scalar(
            select(ImportJob).where(
                ImportJob.workspace_id == self._tenant.workspace_id,
                ImportJob.id == import_job_id,
            )
        )

    def list_all(self, *, status: ImportJobStatus | None = None) -> Sequence[ImportJob]:
        query = select(ImportJob).where(ImportJob.workspace_id == self._tenant.workspace_id)
        if status is not None:
            query = query.where(ImportJob.status == status)
        return self._session.scalars(query.order_by(ImportJob.created_at)).all()


class ImportFileRepository:
    """Import-file metadata of ONE workspace. Nothing is uploaded or stored."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add(self, import_job_id: UUID, data: ImportFileCreate) -> ImportFile:
        job = self._session.scalar(
            select(ImportJob).where(
                ImportJob.workspace_id == self._tenant.workspace_id,
                ImportJob.id == import_job_id,
            )
        )
        if job is None:
            raise NotFoundError("Import job")
        import_file = ImportFile(
            workspace_id=self._tenant.workspace_id,
            import_job_id=job.id,
            original_filename=data.original_filename,
            mime_type=data.mime_type,
            size_bytes=data.size_bytes,
            sha256=data.sha256,
            storage_key=data.storage_key,
        )
        self._session.add(import_file)
        self._session.flush()
        return import_file

    def list_for_job(self, import_job_id: UUID) -> Sequence[ImportFile]:
        return self._session.scalars(
            select(ImportFile)
            .where(
                ImportFile.workspace_id == self._tenant.workspace_id,
                ImportFile.import_job_id == import_job_id,
            )
            .order_by(ImportFile.created_at)
        ).all()

    def find_by_sha256(self, sha256: str) -> Sequence[ImportFile]:
        """Files of THIS workspace with the same content hash (future duplicate detection)."""
        return self._session.scalars(
            select(ImportFile).where(
                ImportFile.workspace_id == self._tenant.workspace_id, ImportFile.sha256 == sha256
            )
        ).all()

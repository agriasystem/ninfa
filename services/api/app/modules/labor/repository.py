"""Tenant-scoped repositories of the labor module (ingestion side).

Every class takes a TenantContext and puts its workspace_id in every query. Repositories `flush()`
but never `commit()`: transaction boundaries belong to LaborImportService. Writes are bulk (one
statement per kind of row) so an import does not grow with its number of entries.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSource
from app.modules.labor.models import (
    LaborEntry,
    LaborImportRow,
    LaborMappingProfile,
    LaborSnapshot,
)

_CHUNK = 1000


@dataclass(frozen=True, slots=True)
class StagedRow:
    source_row_number: int
    mapped_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    validation_status: ImportRowStatus
    validation_errors: list[dict[str, str]]
    validation_warnings: list[dict[str, str]]


class LaborSnapshotRepository:
    """Labor snapshots of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_by_identity(
        self, data_source_id: UUID, snapshot_local_date: date
    ) -> LaborSnapshot | None:
        return self._session.scalar(
            select(LaborSnapshot).where(
                LaborSnapshot.workspace_id == self._tenant.workspace_id,
                LaborSnapshot.data_source_id == data_source_id,
                LaborSnapshot.snapshot_local_date == snapshot_local_date,
            )
        )

    def get_by_id(self, snapshot_id: UUID) -> LaborSnapshot | None:
        return self._session.scalar(
            select(LaborSnapshot).where(
                LaborSnapshot.workspace_id == self._tenant.workspace_id,
                LaborSnapshot.id == snapshot_id,
            )
        )

    def insert(self, row: dict[str, Any]) -> LaborSnapshot:
        snapshot = LaborSnapshot(**row)
        self._session.add(snapshot)
        self._session.flush()
        return snapshot


class LaborEntryRepository:
    """Labor entries of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def insert_many(self, rows: Sequence[dict[str, Any]]) -> None:
        for start in range(0, len(rows), _CHUNK):
            self._session.execute(insert(LaborEntry), list(rows[start : start + _CHUNK]))

    def list_for_snapshot(self, snapshot_id: UUID) -> Sequence[LaborEntry]:
        return self._session.scalars(
            select(LaborEntry)
            .where(
                LaborEntry.workspace_id == self._tenant.workspace_id,
                LaborEntry.labor_snapshot_id == snapshot_id,
            )
            .order_by(LaborEntry.source_row_number)
        ).all()


class LaborMappingProfileRepository:
    """The confirmed mapping of each LABOR data source of ONE workspace (at most one each)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_for_data_source(self, data_source_id: UUID) -> LaborMappingProfile | None:
        return self._session.scalar(
            select(LaborMappingProfile).where(
                LaborMappingProfile.workspace_id == self._tenant.workspace_id,
                LaborMappingProfile.data_source_id == data_source_id,
            )
        )

    def upsert(
        self, data_source: DataSource, *, stored: dict[str, dict[str, Any]], header_signature: str
    ) -> LaborMappingProfile:
        """Replace the current profile of the data source (no history in V1)."""
        statement = (
            pg_insert(LaborMappingProfile)
            .values(
                workspace_id=self._tenant.workspace_id,
                property_id=data_source.property_id,
                data_source_id=data_source.id,
                column_mapping=stored["column_mapping"],
                role_mapping=stored["role_mapping"],
                format_options=stored["format_options"],
                header_signature=header_signature,
            )
            .on_conflict_do_update(
                constraint="uq_labor_mapping_profiles_workspace_id_data_source_id",
                set_={
                    "column_mapping": stored["column_mapping"],
                    "role_mapping": stored["role_mapping"],
                    "format_options": stored["format_options"],
                    "header_signature": header_signature,
                    "updated_at": func.now(),
                },
            )
            .returning(LaborMappingProfile)
        )
        profile = self._session.scalars(
            statement, execution_options={"populate_existing": True}
        ).one()
        self._session.flush()
        return profile


class LaborImportRowRepository:
    """Staging rows of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add_many(
        self, import_job_id: UUID, import_file_id: UUID, rows: Sequence[StagedRow]
    ) -> None:
        payload = [
            {
                "workspace_id": self._tenant.workspace_id,
                "import_job_id": import_job_id,
                "import_file_id": import_file_id,
                "source_row_number": row.source_row_number,
                "mapped_payload": row.mapped_payload,
                "normalized_payload": row.normalized_payload,
                "validation_status": row.validation_status,
                "validation_errors": row.validation_errors,
                "validation_warnings": row.validation_warnings,
            }
            for row in rows
        ]
        for start in range(0, len(payload), _CHUNK):
            self._session.execute(insert(LaborImportRow), payload[start : start + _CHUNK])

    def list_for_job(
        self, import_job_id: UUID, *, status: ImportRowStatus | None = None
    ) -> Sequence[LaborImportRow]:
        query = select(LaborImportRow).where(
            LaborImportRow.workspace_id == self._tenant.workspace_id,
            LaborImportRow.import_job_id == import_job_id,
        )
        if status is not None:
            query = query.where(LaborImportRow.validation_status == status)
        return self._session.scalars(query.order_by(LaborImportRow.source_row_number)).all()

    def mark_valid_rows_imported(self, import_job_id: UUID) -> int:
        result = self._session.execute(
            update(LaborImportRow)
            .where(
                LaborImportRow.workspace_id == self._tenant.workspace_id,
                LaborImportRow.import_job_id == import_job_id,
                LaborImportRow.validation_status == ImportRowStatus.VALID,
            )
            .values(validation_status=ImportRowStatus.IMPORTED)
        )
        return int(getattr(result, "rowcount", 0) or 0)

"""The import with REAL commits and rollbacks, across separate sessions.

Every other database test runs inside one outer transaction (savepoints emulate commit/rollback).
This module proves the service also behaves with plain sessions: real commits, real rollbacks, a
fresh session per step (as after a process restart) and the default `expire_on_commit=True`.
The rows it creates are deleted afterwards.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.errors import BookingErrorCode
from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    ImportRowStatus,
)
from app.modules.bookings.repository import BookingRepository
from app.modules.bookings.service import BookingImportService
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.properties.models import Property
from app.modules.tenancy.models import Workspace
from tests.booking_support import FIXTURES, STANDARD_COLUMNS, STANDARD_HEADERS


@dataclass
class Committed:
    engine: Engine
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID

    def session(self) -> Session:
        # Deliberately the defaults: a new session per use, expire_on_commit=True.
        return Session(self.engine)

    def service(self, session: Session) -> BookingImportService:
        return BookingImportService(session, TenantContext(self.workspace_id))

    def count(self, model: type[Any]) -> int:
        with self.session() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.workspace_id == self.workspace_id)
                )
                or 0
            )


def purge(engine: Engine, workspace_id: UUID) -> None:
    """Delete everything of one workspace, children first (all foreign keys are RESTRICT)."""
    with Session(engine) as session:
        for model in (
            Booking,
            BookingImportRow,
            BookingMappingProfile,
            BookingChannel,
            ImportFile,
            ImportJob,
            DataSource,
            Property,
        ):
            session.execute(delete(model).where(model.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


@pytest.fixture
def committed(db_engine: Engine) -> Iterator[Committed]:
    with Session(db_engine) as session:
        workspace = Workspace(name="Real Commits", slug=f"real-commits-{uuid4().hex[:10]}")
        session.add(workspace)
        session.flush()
        prop = Property(workspace_id=workspace.id, name="Hotel", slug="hotel")
        session.add(prop)
        session.flush()
        source = DataSource(
            workspace_id=workspace.id,
            property_id=prop.id,
            name="Bookings file",
            domain=DataSourceDomain.BOOKINGS,
            source_type=DataSourceType.FILE_UPLOAD,
        )
        session.add(source)
        session.flush()
        ids = Committed(db_engine, workspace.id, prop.id, source.id)
        session.commit()
    try:
        with ids.session() as session:
            ids.service(session).save_mapping(
                ids.data_source_id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS
            )
        yield ids
    finally:
        purge(db_engine, ids.workspace_id)


def run(ids: Committed, fixture: str) -> Any:
    content = (FIXTURES / fixture).read_bytes()
    with ids.session() as session:  # a fresh session each time
        return ids.service(session).import_file(
            ids.data_source_id, filename=fixture, content=content
        )


def test_a_successful_import_is_visible_to_other_sessions_and_releases_its_lock(
    committed: Committed, db_engine: Engine
) -> None:
    result = run(committed, "en_comma.csv")

    assert result.succeeded and result.bookings_created == 3
    with committed.session() as other:
        job = other.get(ImportJob, result.import_job_id)
        assert job is not None and job.status == ImportJobStatus.SUCCEEDED
        stored = BookingRepository(other, TenantContext(committed.workspace_id)).list_for_property(
            committed.property_id
        )
        assert sorted(b.source_record_id for b in stored) == ["EN-1", "EN-2", "EN-3"]
    with db_engine.connect() as connection:  # the advisory lock died with the transaction
        free = connection.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:k AS text), 0))"),
            {"k": str(committed.data_source_id)},
        ).scalar_one()
    assert free is True


def test_a_failed_validation_leaves_a_committed_failed_job_and_no_bookings(
    committed: Committed,
) -> None:
    result = run(committed, "invalid_row.csv")

    assert (result.status, result.error_code) == (
        ImportJobStatus.FAILED,
        BookingErrorCode.VALIDATION_FAILED,
    )
    assert committed.count(Booking) == 0 and committed.count(BookingChannel) == 0
    with committed.session() as other:
        job = other.get(ImportJob, result.import_job_id)
        assert job is not None
        assert (job.status, job.error_code) == (ImportJobStatus.FAILED, "BOOKING_VALIDATION_FAILED")
        statuses = other.scalars(
            select(BookingImportRow.validation_status).where(
                BookingImportRow.import_job_id == job.id
            )
        ).all()
        assert sorted(statuses) == [
            ImportRowStatus.INVALID,
            ImportRowStatus.VALID,
            ImportRowStatus.VALID,
        ]


def test_a_real_rollback_of_the_batch_keeps_the_failed_job(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = BookingRepository.upsert_from_import

    def write_then_crash(self: BookingRepository, **kwargs: Any) -> Any:
        original(self, **kwargs)
        raise RuntimeError("crash after writing")

    monkeypatch.setattr(BookingRepository, "upsert_from_import", write_then_crash)

    result = run(committed, "en_comma.csv")

    assert result.error_code == BookingErrorCode.CANONICALIZATION_FAILED
    assert committed.count(Booking) == 0 and committed.count(BookingChannel) == 0  # rolled back
    with committed.session() as other:
        job = other.get(ImportJob, result.import_job_id)
        assert job is not None and job.status == ImportJobStatus.FAILED  # committed regardless
        assert job.finished_at is not None


def test_a_second_process_reimporting_the_same_file_changes_nothing(committed: Committed) -> None:
    first = run(committed, "en_comma.csv")
    with committed.session() as session:
        before = {
            b.source_record_id: (b.id, b.updated_at, b.last_import_job_id)
            for b in BookingRepository(
                session, TenantContext(committed.workspace_id)
            ).list_for_property(committed.property_id)
        }

    second = run(committed, "en_comma.csv")

    assert (second.bookings_created, second.bookings_updated, second.bookings_unchanged) == (
        0,
        0,
        3,
    )
    assert second.duplicate_of_import_file_id == first.import_file_id
    with committed.session() as session:
        after = {
            b.source_record_id: (b.id, b.updated_at, b.last_import_job_id)
            for b in BookingRepository(
                session, TenantContext(committed.workspace_id)
            ).list_for_property(committed.property_id)
        }
    assert after == before  # with real commits, updated_at would have moved had a row been written
    assert committed.count(Booking) == 3 and committed.count(ImportJob) == 2


def test_the_mapping_saved_in_one_session_is_used_by_the_next(committed: Committed) -> None:
    with committed.session() as session:
        profile = BookingImportService(
            session, TenantContext(committed.workspace_id)
        )._profiles.get_for_data_source(committed.data_source_id)
        assert profile is not None and len(profile.header_signature) == 64
    assert run(committed, "en_comma.csv").succeeded

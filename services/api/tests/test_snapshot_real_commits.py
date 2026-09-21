"""Snapshot runs with REAL commits, separate sessions and concurrent transactions.

Every other database test runs inside one outer transaction. This module proves that the
per-data-source advisory lock really serialises snapshot runs with each other and with the
canonical write of the same source, that a committed observation is visible to other sessions,
and that a conflict rolls back for real. The rows it creates are deleted afterwards.
"""

import inspect
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg.errors as pg
import pytest
from sqlalchemy import Engine, delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source
from app.modules.bookings import service as booking_service
from app.modules.bookings.models import Booking, BookingChannel
from app.modules.ingestion.models import DataSource, DataSourceDomain, DataSourceType, ImportJob
from app.modules.properties.models import Property
from app.modules.snapshots.common import SnapshotRunResult
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.tenancy.models import Workspace
from tests.snapshot_support import FixedClock
from tests.support import booking_values

NOW = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
FIRST = date(2026, 3, 20)
LAST = date(2026, 3, 24)  # five nights


@dataclass
class Committed:
    engine: Engine
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    channel_id: UUID
    job_id: UUID

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(self.workspace_id)

    def session(self) -> Session:
        # Deliberately the defaults: a new session per use, expire_on_commit=True.
        return Session(self.engine)

    def observe(self, clock: FixedClock | None = None) -> SnapshotRunResult:
        with self.session() as session:
            return ObservedSnapshotService(
                session, self.tenant, clock=clock or FixedClock(NOW)
            ).take_snapshot(
                property_id=self.property_id,
                data_source_id=self.data_source_id,
                stay_date_start=FIRST,
                stay_date_end=LAST,
            )

    def add_booking(self, session: Session, record_id: str, **overrides: Any) -> None:
        values = booking_values(
            _Ref(self.workspace_id, self.property_id, self.data_source_id),  # type: ignore[arg-type]
            _Ref(self.workspace_id, self.property_id, self.channel_id),  # type: ignore[arg-type]
            _Ref(self.workspace_id, self.property_id, self.job_id),  # type: ignore[arg-type]
            source_record_id=record_id,
            check_in=FIRST,
            check_out=FIRST + timedelta(days=2),
            **overrides,
        )
        session.execute(insert(Booking), values)

    def snapshot_rows(self) -> list[tuple[date, date, str, int]]:
        with self.session() as session:
            rows = session.execute(
                select(
                    BookingSnapshot.snapshot_local_date,
                    BookingSnapshot.stay_date,
                    BookingSnapshot.content_fingerprint,
                    BookingSnapshot.rooms_on_books,
                )
                .where(BookingSnapshot.workspace_id == self.workspace_id)
                .order_by(BookingSnapshot.snapshot_local_date, BookingSnapshot.stay_date)
            ).all()
            return [(r[0], r[1], r[2], r[3]) for r in rows]


@dataclass
class _Ref:
    """Just enough of an ORM row for `booking_values` (it only reads these attributes)."""

    workspace_id: UUID
    property_id: UUID
    id: UUID


def purge(engine: Engine, workspace_id: UUID) -> None:
    """Delete everything of one workspace, children first (all foreign keys are RESTRICT)."""
    with Session(engine) as session:
        for model in (
            BookingSnapshot,
            RoomInventoryDaily,
            Booking,
            BookingChannel,
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
        workspace = Workspace(name="Real Snapshots", slug=f"real-snapshots-{uuid4().hex[:10]}")
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
        job = ImportJob(workspace_id=workspace.id, property_id=prop.id, data_source_id=source.id)
        channel = BookingChannel(
            workspace_id=workspace.id, property_id=prop.id, name="Direct", normalized_name="direct"
        )
        session.add_all([job, channel])
        session.flush()
        ids = Committed(db_engine, workspace.id, prop.id, source.id, channel.id, job.id)
        session.commit()
    try:
        yield ids
    finally:
        purge(db_engine, ids.workspace_id)


def advisory_lock_is_free(engine: Engine, data_source_id: UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:k AS text), 0))"),
                {"k": str(data_source_id)},
            ).scalar_one()
        )


def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def a_session_is_waiting_for_an_advisory_lock(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
            ).scalar_one()
        )


# --- commits ------------------------------------------------------------------------------------


def test_a_committed_observation_is_visible_to_other_sessions_and_releases_its_lock(
    committed: Committed,
) -> None:
    result = committed.observe()

    assert (result.created, result.unchanged) == (5, 0)
    rows = committed.snapshot_rows()
    assert [(r[0], r[1]) for r in rows] == [
        (date(2026, 3, 15), FIRST + timedelta(days=i)) for i in range(5)
    ]
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)  # died with the txn


def test_repeating_the_run_from_a_fresh_session_is_a_no_op(committed: Committed) -> None:
    committed.observe()
    before = committed.snapshot_rows()

    later = committed.observe(FixedClock(NOW + timedelta(hours=2)))

    assert (later.created, later.unchanged) == (0, 5)
    assert committed.snapshot_rows() == before


def test_a_conflict_rolls_back_for_real_and_leaves_the_stored_rows_alone(
    committed: Committed,
) -> None:
    committed.observe()
    before = committed.snapshot_rows()
    with committed.session() as session:  # the bookings change after the observation
        committed.add_booking(session, "LATE-1", room_revenue=Decimal("100.00"))
        session.commit()

    with pytest.raises(SnapshotError) as info:
        committed.observe(FixedClock(NOW + timedelta(hours=1)))

    assert info.value.error_code == SnapshotErrorCode.CONFLICT
    assert committed.snapshot_rows() == before
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)


def test_the_database_refuses_to_update_a_committed_snapshot(committed: Committed) -> None:
    committed.observe()

    with committed.session() as session, pytest.raises(IntegrityError) as info:
        session.execute(update(BookingSnapshot).values(rooms_on_books=99))
        session.commit()

    assert isinstance(info.value.orig, pg.IntegrityConstraintViolation)
    assert all(row[3] == 0 for row in committed.snapshot_rows())


def test_a_reconstruction_commits_and_an_observation_of_that_day_still_wins(
    committed: Committed,
) -> None:
    with committed.session() as session:
        committed.add_booking(session, "OLD-1", booked_at=datetime(2026, 1, 5, tzinfo=UTC))
        session.commit()
    committed.observe(FixedClock(datetime(2026, 3, 10, 10, 0, tzinfo=UTC)))

    with committed.session() as session:
        result = BookingSnapshotReconstructionService(
            session, committed.tenant, clock=FixedClock(NOW)
        ).reconstruct(
            property_id=committed.property_id,
            data_source_id=committed.data_source_id,
            snapshot_date_start=date(2026, 3, 9),
            snapshot_date_end=date(2026, 3, 11),
            stay_date_start=FIRST,
            stay_date_end=LAST,
        )

    assert (result.created, result.skipped_observed) == (10, 5)
    with committed.session() as session:
        origins = {
            row[0]: row[1]
            for row in session.execute(
                select(BookingSnapshot.snapshot_local_date, BookingSnapshot.origin)
                .where(BookingSnapshot.stay_date == FIRST)
                .order_by(BookingSnapshot.snapshot_local_date)
            )
        }
    assert origins == {
        date(2026, 3, 9): SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        date(2026, 3, 10): SnapshotOrigin.OBSERVED,
        date(2026, 3, 11): SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
    }


# --- concurrency --------------------------------------------------------------------------------


def test_two_concurrent_runs_of_the_same_source_end_as_one_creation_and_one_no_op(
    committed: Committed,
) -> None:
    barrier = threading.Barrier(2)

    def worker() -> SnapshotRunResult:
        barrier.wait(timeout=10)
        return committed.observe()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker), pool.submit(worker)]
        results = [f.result(timeout=30) for f in futures]

    assert sorted((r.created, r.unchanged) for r in results) == [(0, 5), (5, 0)]
    assert len(committed.snapshot_rows()) == 5
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)


def test_a_snapshot_run_waits_for_the_lock_and_sees_the_bookings_committed_before_it(
    committed: Committed,
) -> None:
    """The lock is what makes the read set coherent with an import (the writer holds it too)."""
    writer = committed.session()
    lock_data_source(writer, committed.data_source_id)  # what the import's canonical write does
    committed.add_booking(writer, "IMPORTING-1", rooms=2, room_revenue=Decimal("300.00"))
    # ... not committed yet: an import in the middle of its canonical write

    with ThreadPoolExecutor(max_workers=1) as pool:
        future: Future[SnapshotRunResult] = pool.submit(committed.observe)
        try:
            assert wait_until(lambda: a_session_is_waiting_for_an_advisory_lock(committed.engine))
            assert not future.done()  # blocked on the lock, not reading half an import
            writer.commit()  # the import finishes: bookings are visible, lock released
            result = future.result(timeout=30)
        finally:
            writer.close()

    assert result.created == 5
    rows = committed.snapshot_rows()
    assert [r[3] for r in rows] == [2, 2, 0, 0, 0]  # the whole import, never a part of it


def test_a_snapshot_run_that_finds_the_lock_taken_by_a_rolled_back_import_sees_nothing_of_it(
    committed: Committed,
) -> None:
    writer = committed.session()
    lock_data_source(writer, committed.data_source_id)
    committed.add_booking(writer, "ROLLED-BACK-1", rooms=3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future: Future[SnapshotRunResult] = pool.submit(committed.observe)
        try:
            assert wait_until(lambda: a_session_is_waiting_for_an_advisory_lock(committed.engine))
            writer.rollback()
            result = future.result(timeout=30)
        finally:
            writer.close()

    assert result.created == 5
    assert all(r[3] == 0 for r in committed.snapshot_rows())


def test_the_import_and_the_snapshot_services_take_the_same_lock() -> None:
    """One definition of the lock: a change of key in one place cannot desynchronise them."""
    assert "lock_data_source(" in inspect.getsource(booking_service.BookingImportService)
    from app.modules.snapshots import common

    assert "lock_data_source(" in inspect.getsource(common.SnapshotServiceBase)
    assert vars(booking_service)["lock_data_source"] is lock_data_source
    assert vars(common)["lock_data_source"] is lock_data_source


def test_the_count_of_snapshots_matches_what_was_reported(committed: Committed) -> None:
    result = committed.observe()

    with committed.session() as session:
        stored = session.scalar(
            select(func.count())
            .select_from(BookingSnapshot)
            .where(BookingSnapshot.workspace_id == committed.workspace_id)
        )
    assert stored == result.total == 5

"""Expected runs with REAL commits and concurrent transactions.

Every other database test runs inside one outer transaction. This module proves that the
per-data-source advisory lock serialises two concurrent runs (one creates, the other is a no-op),
that a conflict rolls back for real, and that a committed baseline is visible to another session.
The rows it creates are deleted afterwards.
"""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import Engine, delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source
from app.modules.ingestion.models import DataSource, DataSourceDomain, DataSourceType
from app.modules.intelligence.expected.errors import ExpectedError, ExpectedErrorCode
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.service import BookingExpectedService, ExpectedRunResult
from app.modules.properties.models import Property
from app.modules.snapshots.models import BookingSnapshot
from app.modules.tenancy.models import Workspace
from tests.expected_support import (
    ELIGIBLE,
    LEAD,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    snapshot_row,
)


@dataclass
class Committed:
    engine: Engine
    workspace_id: uuid.UUID
    property_id: uuid.UUID
    data_source_id: uuid.UUID
    target_id: uuid.UUID

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(self.workspace_id)

    def session(self) -> Session:
        # Deliberately the defaults: a new session per use, expire_on_commit=True.
        return Session(self.engine)

    def calculate(self) -> ExpectedRunResult:
        with self.session() as session:
            return BookingExpectedService(session, self.tenant).calculate_for_target(
                property_id=self.property_id,
                data_source_id=self.data_source_id,
                target_snapshot_id=self.target_id,
            )

    def add_history(self, stays: list[Any], rooms: int = 10) -> None:
        rows = [self.row(stay - timedelta(days=LEAD), stay, rooms) for stay in stays]
        with self.session() as session:
            session.execute(insert(BookingSnapshot), rows)
            session.commit()

    def row(self, snapshot_day: Any, stay: Any, rooms: int) -> dict[str, Any]:
        row = snapshot_row(_Tenant(self), snapshot_day, stay, rooms=rooms)  # type: ignore[arg-type]
        row["as_of_at"] = datetime.combine(snapshot_day, datetime.min.time(), tzinfo=UTC)
        return row

    def baselines(self) -> list[tuple[Any, ...]]:
        with self.session() as session:
            return [
                tuple(r)
                for r in session.execute(
                    select(
                        BookingExpectedBaseline.id,
                        BookingExpectedBaseline.status,
                        BookingExpectedBaseline.comparable_fingerprint,
                    ).where(BookingExpectedBaseline.workspace_id == self.workspace_id)
                )
            ]

    def comparable_count(self) -> int:
        with self.session() as session:
            return len(
                session.scalars(
                    select(BookingExpectedComparable.id).where(
                        BookingExpectedComparable.workspace_id == self.workspace_id
                    )
                ).all()
            )


@dataclass
class _Ref:
    id: uuid.UUID


class _Tenant:
    """Just enough of a `Tenant` for `snapshot_row` (workspace, property, data source ids)."""

    def __init__(self, ids: Committed) -> None:
        self.workspace = _Ref(ids.workspace_id)
        self.property = _Ref(ids.property_id)
        self.data_source = _Ref(ids.data_source_id)


def purge(engine: Engine, workspace_id: uuid.UUID) -> None:
    """Delete everything of one workspace, children first (all foreign keys are RESTRICT)."""
    with Session(engine) as session:
        for model in (
            BookingExpectedComparable,
            BookingExpectedBaseline,
            BookingSnapshot,
            DataSource,
            Property,
        ):
            session.execute(delete(model).where(model.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


@pytest.fixture
def committed(db_engine: Engine) -> Iterator[Committed]:
    with Session(db_engine) as session:
        workspace = Workspace(name="Real Expected", slug=f"real-expected-{uuid.uuid4().hex[:10]}")
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
        ids = Committed(db_engine, workspace.id, prop.id, source.id, uuid.uuid4())
        target = snapshot_row(_Tenant(ids), TARGET_SNAPSHOT_DAY, TARGET_STAY, rooms=12)  # type: ignore[arg-type]
        target["id"] = ids.target_id
        target["as_of_at"] = datetime.combine(TARGET_SNAPSHOT_DAY, datetime.min.time(), tzinfo=UTC)
        session.execute(insert(BookingSnapshot), target)
        session.commit()
    ids.add_history(ELIGIBLE[:6], rooms=10)
    try:
        yield ids
    finally:
        purge(db_engine, ids.workspace_id)


def advisory_lock_is_free(engine: Engine, data_source_id: uuid.UUID) -> bool:
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


# --- commits ----------------------------------------------------------------------------------


def test_a_committed_baseline_is_visible_to_other_sessions_and_releases_its_lock(
    committed: Committed,
) -> None:
    result = committed.calculate()

    assert (result.created, result.ready) == (1, 1)
    baselines = committed.baselines()
    assert len(baselines) == 1 and committed.comparable_count() == 6
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)  # died with the txn


def test_repeating_the_run_from_a_fresh_session_is_a_no_op(committed: Committed) -> None:
    committed.calculate()
    before = committed.baselines()

    again = committed.calculate()

    assert (again.created, again.unchanged) == (0, 1)
    assert committed.baselines() == before and committed.comparable_count() == 6


def test_a_conflict_rolls_back_for_real_and_leaves_the_stored_baseline_alone(
    committed: Committed,
) -> None:
    committed.calculate()
    before = committed.baselines()
    committed.add_history(ELIGIBLE[6:8], rooms=40)  # history that arrives after the baseline

    with pytest.raises(ExpectedError) as info:
        committed.calculate()

    assert info.value.error_code == ExpectedErrorCode.BASELINE_CONFLICT
    assert committed.baselines() == before and committed.comparable_count() == 6
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)


def test_the_database_refuses_to_update_a_committed_baseline_or_comparable(
    committed: Committed,
) -> None:
    committed.calculate()

    for statement in (
        update(BookingExpectedBaseline).values(expected_rooms_on_books=Decimal("99.00")),
        update(BookingExpectedComparable).values(rooms_on_books=99),
    ):
        with committed.session() as session, pytest.raises(IntegrityError) as info:
            session.execute(statement)
            session.commit()
        assert isinstance(info.value.orig, pg.IntegrityConstraintViolation)


# --- concurrency ------------------------------------------------------------------------------


def test_two_concurrent_runs_of_the_same_target_end_as_one_creation_and_one_no_op(
    committed: Committed,
) -> None:
    barrier = threading.Barrier(2)

    def worker() -> ExpectedRunResult:
        barrier.wait(timeout=10)
        return committed.calculate()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(worker), pool.submit(worker)]]

    assert sorted((r.created, r.unchanged) for r in results) == [(0, 1), (1, 0)]
    assert len(committed.baselines()) == 1 and committed.comparable_count() == 6
    assert advisory_lock_is_free(committed.engine, committed.data_source_id)


def test_a_run_waits_for_a_snapshot_writer_holding_the_data_source_lock(
    committed: Committed,
) -> None:
    """A snapshot run (or an import) in progress finishes first; the Expected run then sees the
    snapshots it committed, never half of them."""
    writer = committed.session()
    lock_data_source(writer, committed.data_source_id)
    late = [committed.row(stay - timedelta(days=LEAD), stay, 30) for stay in ELIGIBLE[6:9]]
    writer.execute(insert(BookingSnapshot), late)  # not committed yet

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(committed.calculate)
        try:
            assert wait_until(lambda: a_session_is_waiting_for_an_advisory_lock(committed.engine))
            assert not future.done()  # blocked on the lock, not reading half a snapshot run
            writer.commit()
            result = future.result(timeout=30)
        finally:
            writer.close()

    assert result.created == 1
    assert committed.comparable_count() == 9  # the 6 it had + the 3 committed while it waited

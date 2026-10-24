"""The first import into a data source, with REAL commits and concurrent transactions.

Every other data-source test runs inside one outer transaction. The race this module covers needs
separate connections: two first imports of the same kind of data, for the same property, arriving
together. Without serialisation both would find "no source yet" and both would create one, and the
property would answer 409 SEVERAL_SOURCES from then on. The rows it creates are deleted afterwards,
the same pattern as `test_booking_import_real_commits.py`.

The race is provoked on purpose, not hoped for: a hook parks each import right after it has READ the
existing sources and before it writes anything, so both are inside the check-then-act window at the
same time. The control test shows that without the lock the very same setup does create two sources.
"""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.modules.data_sources.service as service_module
from app.core.tenant import TenantContext
from app.db.locks import source_import_lock_key
from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
)
from app.modules.data_sources.errors import ImportInProgressError
from app.modules.data_sources.mapping_types import MappingInput
from app.modules.data_sources.service import DataSourcesService, ImportOutcome, MappedImport
from app.modules.data_sources.types import SourceState
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.labor.models import (
    LaborEntry,
    LaborImportRow,
    LaborMappingProfile,
    LaborSnapshot,
)
from app.modules.properties.models import Property
from app.modules.tenancy.models import Workspace
from tests.data_sources_support import (
    BOOKING_HEADER,
    LABOR_DAY,
    labor_bytes,
    malformed_booking_bytes,
)

LABOR_SNAPSHOT_DAY = date.fromisoformat(LABOR_DAY)
WAIT = 30  # seconds: an upper bound for "this must finish", never a pause the test relies on


def bookings_file(prefix: str, *, channel: str = "Direct") -> bytes:
    """A valid bookings CSV whose records are named by `prefix`, so two files never overlap."""
    rows = [
        f"{prefix}-{n},2026-09-01,2026-11-0{n},2026-11-0{n + 1},confirmed,1,150.00,{channel}"
        for n in (1, 2)
    ]
    return ("\n".join([BOOKING_HEADER, *rows]) + "\n").encode("utf-8")


@dataclass
class Committed:
    engine: Engine
    workspace_id: UUID
    property_id: UUID
    other_property_id: UUID

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(self.workspace_id)

    def import_file(
        self,
        content: bytes,
        *,
        property_id: UUID | None = None,
        domain: DataSourceDomain = DataSourceDomain.BOOKINGS,
        snapshot: date | None = None,
        mapped: MappedImport | None = None,
    ) -> ImportOutcome:
        """One import, the way a request makes it: its own session (like the app's), already used
        for a read before the import starts (authentication does that), a fresh connection."""
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with factory() as session:
            session.scalar(select(func.count()).select_from(Property))
            return DataSourcesService(session, self.tenant).import_file(
                property_id or self.property_id,
                domain,
                filename="file.csv",
                content=content,
                snapshot_local_date=snapshot,
                mapped=mapped,
            )

    def sources(
        self, *, property_id: UUID | None = None, domain: DataSourceDomain | None = None
    ) -> list[DataSource]:
        with Session(self.engine) as session:
            query = select(DataSource).where(DataSource.workspace_id == self.workspace_id)
            if property_id is not None:
                query = query.where(DataSource.property_id == property_id)
            if domain is not None:
                query = query.where(DataSource.domain == domain)
            return list(session.scalars(query))

    def jobs(self) -> list[ImportJob]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(ImportJob)
                    .where(ImportJob.workspace_id == self.workspace_id)
                    .order_by(ImportJob.created_at)
                )
            )

    def count(self, model: type[Any]) -> int:
        with Session(self.engine) as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.workspace_id == self.workspace_id)
                )
                or 0
            )

    def overview_state(self, card: str = "PMS") -> tuple[SourceState, bool]:
        """(state, several_sources) of one card, read the way the page reads it."""
        with Session(self.engine) as session:
            overview = DataSourcesService(session, self.tenant).overview(self.property_id)
        found = next(item for item in overview.cards if item.card.value == card)
        return found.state, found.several_sources

    def lock_key(self, domain: DataSourceDomain, property_id: UUID | None = None) -> str:
        return source_import_lock_key(
            self.workspace_id, property_id or self.property_id, domain.value
        )


def purge(engine: Engine, workspace_id: UUID) -> None:
    """Delete everything of one workspace, children first (all foreign keys are RESTRICT)."""
    with Session(engine) as session:
        for model in (
            Booking,
            BookingImportRow,
            BookingMappingProfile,
            BookingChannel,
            LaborEntry,
            LaborImportRow,
            LaborSnapshot,
            LaborMappingProfile,
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
    """A workspace with two properties and NO data source at all."""
    with Session(db_engine) as session:
        workspace = Workspace(name="Real Sources", slug=f"real-sources-{uuid4().hex[:10]}")
        session.add(workspace)
        session.flush()
        first = Property(workspace_id=workspace.id, name="Hotel Uno", slug="uno")
        second = Property(workspace_id=workspace.id, name="Hotel Due", slug="due")
        session.add_all([first, second])
        session.flush()
        ids = Committed(db_engine, workspace.id, first.id, second.id)
        session.commit()
    try:
        yield ids
    finally:
        purge(db_engine, ids.workspace_id)


def lock_is_free(engine: Engine, key: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:k AS text), 0))"),
                {"k": key},
            ).scalar_one()
        )


def someone_waits_for(engine: Engine, key: str) -> bool:
    """True while a session is queued for exactly this lock (not for any other advisory lock)."""
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                    "AND ((classid::bigint << 32) | objid::bigint) = "
                    "hashtextextended(CAST(:k AS text), 0)"
                ),
                {"k": key},
            ).scalar_one()
        )


def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class BothInsideTheWindow:
    """Parks every import right after it has READ the existing sources, until both have.

    The window is the check-then-act gap: "is there a source?" has been answered, "then create one"
    has not been done yet. Under the lock the second import can never get here while the first is
    inside, so the barrier gives up after `grace` seconds and lets the first one go on.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, grace: float = 2.0) -> None:
        self.barrier = threading.Barrier(2)
        self.grace = grace
        original = DataSourcesService._sources_of
        gate = self

        def sources_of_then_wait(self_: DataSourcesService, *args: Any, **kwargs: Any) -> Any:
            found = original(self_, *args, **kwargs)
            # if the other import is held back by the lock the barrier breaks: carry on alone
            with suppress(threading.BrokenBarrierError):
                gate.barrier.wait(timeout=gate.grace)
            return found

        monkeypatch.setattr(DataSourcesService, "_sources_of", sources_of_then_wait)


class HoldInsideTheImport:
    """Parks the import of one property / kind of data inside `_run_import`, until released."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, property_id: UUID) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        original = DataSourcesService._run_import
        gate = self

        def run_import(self_: DataSourcesService, source: DataSource, *args: Any) -> Any:
            if source.property_id == property_id and not gate.inside.is_set():
                gate.inside.set()
                assert gate.release.wait(timeout=WAIT), "the held import was never released"
            return original(self_, source, *args)

        monkeypatch.setattr(DataSourcesService, "_run_import", run_import)


# --- the race ---------------------------------------------------------------------------------


def test_two_first_imports_arriving_together_create_exactly_one_source(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    BothInsideTheWindow(monkeypatch)
    files = [bookings_file("AAA", channel="Direct"), bookings_file("BBB", channel="Airbnb")]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(committed.import_file, content) for content in files]
        outcomes = [future.result(timeout=WAIT) for future in futures]

    assert [o.succeeded for o in outcomes] == [True, True]
    sources = committed.sources(property_id=committed.property_id)
    assert len(sources) == 1 and sources[0].is_active  # one source, switched on
    jobs = committed.jobs()
    assert len(jobs) == 2  # one job per import, none lost, none duplicated
    assert {job.data_source_id for job in jobs} == {sources[0].id}  # both fed the SAME source
    assert {job.status for job in jobs} == {ImportJobStatus.SUCCEEDED}
    assert committed.count(Booking) == 4  # both files arrived whole
    assert committed.overview_state() == (SourceState.CONFIGURED_FILE, False)  # no SEVERAL_SOURCES
    assert lock_is_free(committed.engine, committed.lock_key(DataSourceDomain.BOOKINGS))


def test_without_the_lock_the_same_setup_does_create_two_sources(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: it proves the hook above really provokes the race, so that the test before is
    not passing by luck."""
    BothInsideTheWindow(monkeypatch)
    monkeypatch.setattr(service_module, "hold_source_import_lock", lambda *a, **k: nullcontext())
    files = [bookings_file("AAA"), bookings_file("BBB")]

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(committed.import_file, c) for c in files]:
            future.result(timeout=WAIT)

    assert len(committed.sources(property_id=committed.property_id)) == 2  # the duplication
    assert committed.overview_state() == (SourceState.CONFIGURED_FILE, True)  # SEVERAL_SOURCES


@pytest.mark.parametrize("failing_goes_first", [True, False], ids=["bad-first", "good-first"])
def test_a_failing_and_a_succeeding_first_import_together_leave_one_configured_source(
    committed: Committed, monkeypatch: pytest.MonkeyPatch, failing_goes_first: bool
) -> None:
    """Either order. The first import fails or succeeds COMPLETELY before the second one starts,
    so the failure of one can never switch off a source the other is filling."""
    gate = HoldInsideTheImport(monkeypatch, property_id=committed.property_id)
    first_file, second_file = (
        (malformed_booking_bytes(), bookings_file("OK"))
        if failing_goes_first
        else (bookings_file("OK"), malformed_booking_bytes())
    )
    key = committed.lock_key(DataSourceDomain.BOOKINGS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(committed.import_file, first_file)
        assert gate.inside.wait(timeout=WAIT)  # the first import is in the middle of its work
        second = pool.submit(committed.import_file, second_file)
        assert wait_until(lambda: someone_waits_for(committed.engine, key))  # queued, not running
        assert not second.done()
        gate.release.set()
        outcomes = [first.result(timeout=WAIT), second.result(timeout=WAIT)]

    assert sorted(o.succeeded for o in outcomes) == [False, True]
    sources = committed.sources(property_id=committed.property_id)
    assert len(sources) == 1 and sources[0].is_active  # the good file configured it, once
    jobs = committed.jobs()
    assert sorted(job.status for job in jobs) == [
        ImportJobStatus.FAILED,
        ImportJobStatus.SUCCEEDED,
    ]
    # both jobs belong to the one source: a source switched off after a failure is reactivated
    assert {job.data_source_id for job in jobs} == {sources[0].id}
    assert committed.overview_state() == (SourceState.CONFIGURED_FILE, False)
    assert lock_is_free(committed.engine, key)


def test_an_import_after_the_concurrent_ones_keeps_working_on_the_same_source(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    BothInsideTheWindow(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [
            pool.submit(committed.import_file, bookings_file(name)) for name in ("AAA", "BBB")
        ]:
            future.result(timeout=WAIT)
    (source,) = committed.sources(property_id=committed.property_id)

    later = committed.import_file(bookings_file("CCC"))  # no 409, no new source

    assert later.succeeded
    assert [s.id for s in committed.sources(property_id=committed.property_id)] == [source.id]
    assert len(committed.jobs()) == 3
    assert committed.count(Booking) == 6
    assert committed.overview_state() == (SourceState.CONFIGURED_FILE, False)


# --- what must NOT wait ---------------------------------------------------------------------


def test_imports_for_different_properties_do_not_wait_for_each_other(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = HoldInsideTheImport(monkeypatch, property_id=committed.property_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(committed.import_file, bookings_file("ONE"))
        assert gate.inside.wait(timeout=WAIT)  # property one is in the middle of its import...
        other = pool.submit(
            committed.import_file, bookings_file("TWO"), property_id=committed.other_property_id
        )
        outcome = other.result(timeout=WAIT)  # ...and property two goes through, not queued
        assert not held.done()  # property one is still held: two really overlapped
        gate.release.set()
        held.result(timeout=WAIT)

    assert outcome.succeeded
    first = committed.sources(property_id=committed.property_id)
    second = committed.sources(property_id=committed.other_property_id)
    assert len(first) == 1 and len(second) == 1 and first[0].id != second[0].id  # never shared
    assert first[0].is_active and second[0].is_active
    assert {job.property_id for job in committed.jobs()} == {
        committed.property_id,
        committed.other_property_id,
    }
    assert lock_is_free(committed.engine, committed.lock_key(DataSourceDomain.BOOKINGS))
    assert lock_is_free(
        committed.engine,
        committed.lock_key(DataSourceDomain.BOOKINGS, committed.other_property_id),
    )


def test_imports_of_different_kinds_of_data_on_one_property_do_not_wait_for_each_other(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = HoldInsideTheImport(monkeypatch, property_id=committed.property_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(committed.import_file, bookings_file("ONE"))
        assert gate.inside.wait(timeout=WAIT)
        staff = pool.submit(
            committed.import_file,
            labor_bytes(),
            domain=DataSourceDomain.LABOR,
            snapshot=LABOR_SNAPSHOT_DAY,
        )
        outcome = staff.result(timeout=WAIT)  # the staff file is not queued behind the bookings
        assert not held.done()
        gate.release.set()
        held.result(timeout=WAIT)

    assert outcome.succeeded
    assert len(committed.sources(property_id=committed.property_id)) == 2  # one source per kind


# --- the lock never outlives the import --------------------------------------------------------


def test_the_lock_is_released_after_a_success_a_refused_file_and_an_unexpected_crash(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = committed.lock_key(DataSourceDomain.BOOKINGS)

    assert committed.import_file(bookings_file("OK")).succeeded
    assert lock_is_free(committed.engine, key)

    assert not committed.import_file(malformed_booking_bytes()).succeeded
    assert lock_is_free(committed.engine, key)

    original = DataSourcesService._run_import

    def crash(self_: DataSourcesService, *args: Any) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(DataSourcesService, "_run_import", crash)
    with pytest.raises(RuntimeError):
        committed.import_file(bookings_file("CRASH"))
    assert lock_is_free(committed.engine, key)  # a crash did not leave the queue blocked

    monkeypatch.setattr(DataSourcesService, "_run_import", original)
    assert committed.import_file(bookings_file("AFTER")).succeeded  # and the next import runs


def test_an_import_that_waits_longer_than_allowed_is_told_so_and_changes_nothing(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "IMPORT_LOCK_WAIT_MS", 300)
    gate = HoldInsideTheImport(monkeypatch, property_id=committed.property_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(committed.import_file, bookings_file("ONE"))
        assert gate.inside.wait(timeout=WAIT)
        waited = pool.submit(committed.import_file, bookings_file("TWO"))
        with pytest.raises(ImportInProgressError):
            waited.result(timeout=WAIT)  # gave up after ~300 ms, did not hang
        assert not held.done()
        gate.release.set()
        assert held.result(timeout=WAIT).succeeded

    assert len(committed.sources(property_id=committed.property_id)) == 1
    assert len(committed.jobs()) == 1  # the import that gave up left no trace at all
    assert committed.count(Booking) == 2
    assert committed.import_file(bookings_file("THREE")).succeeded  # and a retry goes through


# --- Smart Import: the same lock holds for a file read through the person's own matching ---------


def test_two_matched_first_imports_arriving_together_leave_one_source_and_one_configuration(
    committed: Committed, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.smart_import_support import LABOR_IT_DECISION, labor_it_file

    BothInsideTheWindow(monkeypatch)
    mapped = MappedImport(MappingInput.model_validate(LABOR_IT_DECISION), save_configuration=True)
    files = [
        (labor_it_file(days=("26/10/2026", "27/10/2026")), date(2026, 10, 23)),
        (labor_it_file(days=("28/10/2026", "29/10/2026")), date(2026, 10, 24)),
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                committed.import_file,
                content,
                domain=DataSourceDomain.LABOR,
                snapshot=snapshot,
                mapped=mapped,
            )
            for content, snapshot in files
        ]
        outcomes = [future.result(timeout=WAIT) for future in futures]

    assert [o.succeeded for o in outcomes] == [True, True]
    sources = committed.sources(property_id=committed.property_id, domain=DataSourceDomain.LABOR)
    assert len(sources) == 1 and sources[0].is_active
    assert committed.count(LaborMappingProfile) == 1  # one source, one configuration, not two
    assert committed.count(LaborEntry) == 4
    assert {job.data_source_id for job in committed.jobs()} == {sources[0].id}
    assert committed.overview_state("STAFF") == (SourceState.CONFIGURED_FILE, False)

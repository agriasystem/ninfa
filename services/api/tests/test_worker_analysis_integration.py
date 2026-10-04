"""Gate 25B: enqueue -> worker execution -> shared orchestration -> persisted DecisionRun -> the
Decision Memory feed Oggi reads, against the REAL test database with REAL commits.

The queue is Procrastinate's in-memory connector (the Procrastinate Postgres schema is not what is
under test); everything the task does is production code: its own Session from
`get_sessionmaker()`, `run_property_analysis` and the real services. The bootstrap goes through the
real pilot CLI functions, and no detector pipeline is reproduced here.

Every test uses its own workspace and removes everything it committed afterwards.
"""

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest
from procrastinate import testing
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.cli.imports import run_import_bookings
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.analysis import AnalysisRunRequest
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.models import Workspace
from app.modules.tenancy.repository import WorkspaceRepository
from tests.pilot_support import booking_csv
from worker import runtime
from worker.app import DEFAULT_QUEUE, app
from worker.enqueue import enqueue_analysis


@dataclass
class Pilot:
    engine: Engine
    tenant: TenantContext
    property_id: uuid.UUID
    data_source_id: uuid.UUID
    stay_dates: list[date]

    def request(self) -> AnalysisRunRequest:
        return AnalysisRunRequest(
            workspace_id=self.tenant.workspace_id,
            property_id=self.property_id,
            booking_data_source_id=self.data_source_id,
            stay_date_start=min(self.stay_dates),
            stay_date_end=max(self.stay_dates),
        )

    def runs(self) -> list[DecisionRun]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(DecisionRun).where(DecisionRun.workspace_id == self.tenant.workspace_id)
                ).all()
            )

    def feed_run_id(self) -> uuid.UUID | None:
        with Session(self.engine) as session:
            feed = DecisionMemoryService(session, self.tenant).get_feed(
                self.property_id, date.today()
            )
            return feed.run.id if feed.run is not None else None

    def feed_state(self) -> FeedState:
        with Session(self.engine) as session:
            return (
                DecisionMemoryService(session, self.tenant)
                .get_feed(self.property_id, date.today())
                .state
            )


def _purge(engine: Engine, workspace_id: uuid.UUID) -> None:
    """Delete everything a workspace owns, children before parents (FK dependency order)."""
    with Session(engine) as session:
        for table in reversed(Base.metadata.sorted_tables):
            if "workspace_id" in table.c and table.name not in {"properties", "workspaces"}:
                session.execute(delete(table).where(table.c.workspace_id == workspace_id))
        session.execute(delete(Property).where(Property.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


@pytest.fixture
def pilot(db_engine: Engine, tmp_path: Path) -> Iterator[Pilot]:
    slug = f"w25b-{uuid.uuid4().hex[:10]}"
    stay_dates = [date.today() + timedelta(days=14), date.today() + timedelta(days=15)]
    with Session(db_engine) as session:
        run_create_workspace(session, name="Hotel Worker", slug=slug)
        run_create_property(
            session,
            workspace_slug=slug,
            name="Hotel Worker",
            slug=slug,
            timezone="Europe/Rome",
            currency="EUR",
        )
        workspace = WorkspaceRepository(session).get_by_slug(slug)
        assert workspace is not None
        tenant = TenantContext(workspace_id=workspace.id)
        prop = PropertyRepository(session, tenant).get_by_slug(slug)
        assert prop is not None
        run_create_data_source(
            session,
            workspace_slug=slug,
            property_slug=slug,
            domain=DataSourceDomain.BOOKINGS,
            name="Bookings",
        )
        source = DataSourceRepository(session, tenant).list_all(property_id=prop.id)[0]
        file = booking_csv(tmp_path, stay_dates=stay_dates)
        assert (
            run_import_bookings(
                session,
                workspace_slug=slug,
                property_slug=slug,
                data_source_id=source.id,
                file=file,
            )
            == 0
        )
        committed = Pilot(db_engine, tenant, prop.id, source.id, stay_dates)
    try:
        yield committed
    finally:
        _purge(db_engine, committed.tenant.workspace_id)


def _enqueue_and_run_worker(request: AnalysisRunRequest) -> list[str]:
    """One explicit enqueue, then the worker drains the queue; returns the job statuses."""
    connector = testing.InMemoryConnector()

    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            assert await enqueue_analysis(request) == 0
            async with test_app.open_async():
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())
    return [str(job["status"]) for job in connector.jobs.values()]


def test_01_enqueued_job_runs_the_shared_analysis_and_persists_a_readable_decision_run(
    pilot: Pilot,
) -> None:
    assert pilot.feed_state() == FeedState.NOT_PROCESSED

    assert _enqueue_and_run_worker(pilot.request()) == ["succeeded"]

    runs = pilot.runs()
    assert len(runs) == 1
    assert pilot.feed_run_id() == runs[0].id  # the SAME run Oggi reads
    assert pilot.feed_state() == FeedState.DATA_QUALITY_LIMITED  # cold start, honest
    assert runs[0].analysis_coverage is not None
    assert runs[0].input_provenance is not None
    assert pilot.runs()[0].as_of_local_date is not None


def test_02_a_duplicate_identical_execution_the_same_day_is_a_safe_replay(
    pilot: Pilot, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="worker.tasks"):
        statuses = _enqueue_and_run_worker(pilot.request())
        statuses += _enqueue_and_run_worker(pilot.request())

    assert statuses == ["succeeded", "succeeded"]
    assert len(pilot.runs()) == 1  # no second DecisionRun
    completed = [m for m in caplog.messages if "Analysis job completed" in m]
    assert "is_idempotent_replay=False" in completed[0]
    assert "is_idempotent_replay=True" in completed[1]


def test_03_changed_bookings_then_a_same_day_second_analysis_surfaces_the_snapshot_conflict(
    pilot: Pilot, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert _enqueue_and_run_worker(pilot.request()) == ["succeeded"]
    first_run = pilot.runs()[0]

    # A NEW booking lands on an already observed stay night: the same-day observation changed.
    changed = tmp_path / "changed.csv"
    changed.write_text(
        "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel\n"
        f"PILOT-9999,{date.today().isoformat()},{pilot.stay_dates[0].isoformat()},"
        f"{(pilot.stay_dates[0] + timedelta(days=1)).isoformat()},confirmed,1,150.00,Direct\n",
        encoding="utf-8",
    )
    with Session(pilot.engine) as session:
        workspace = session.get(Workspace, pilot.tenant.workspace_id)
        prop = session.get(Property, pilot.property_id)
        assert workspace is not None and prop is not None
        assert (
            run_import_bookings(
                session,
                workspace_slug=workspace.slug,
                property_slug=prop.slug,
                data_source_id=pilot.data_source_id,
                file=changed,
            )
            == 0
        )

    with caplog.at_level(logging.ERROR, logger="worker.tasks"):
        statuses = _enqueue_and_run_worker(pilot.request())

    assert statuses == ["failed"]  # no workaround: the existing immutability rule is visible
    assert any("status=failed error_type=SnapshotError" in m for m in caplog.messages)
    runs = pilot.runs()
    assert [run.id for run in runs] == [first_run.id]  # nothing faked, nothing replaced


def test_04_an_unknown_property_fails_the_job_and_persists_nothing(pilot: Pilot) -> None:
    request = AnalysisRunRequest(
        workspace_id=pilot.tenant.workspace_id,
        property_id=uuid.uuid4(),
        booking_data_source_id=pilot.data_source_id,
        stay_date_start=min(pilot.stay_dates),
        stay_date_end=max(pilot.stay_dates),
    )

    assert _enqueue_and_run_worker(request) == ["failed"]
    assert pilot.runs() == []

"""Gate 26B: the automatic-analysis acceptance scenario on the REAL test database with REAL commits:

    policy disabled -> dispatcher enqueues nothing
    enabled, no import today -> SKIPPED NO_TODAY_BOOKING_IMPORT (no snapshot, no run)
    valid import today -> dispatcher enqueues exactly ONE `analysis.run_policy` job
    worker -> shared orchestration -> DecisionRun for today's property-local date
    coverage: Revenue + Distribution EVALUATED, Costs + Labor SKIPPED / NOT_REQUESTED
    second dispatch the same day -> SKIPPED ALREADY_ANALYZED_TODAY

The queue is Procrastinate's in-memory connector; everything else is production code (the real
dispatcher evaluation, the task's own Session, `run_automatic_analysis`, the real engines). No
second changed-data analysis is attempted.
"""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from procrastinate import testing
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.modules.analysis import (
    AnalysisPolicyService,
    AnalysisRunRequest,
    run_property_analysis,
)
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.coverage import AnalysisCoverage, AnalysisDomain, CoverageSummary
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import BookingSnapshot
from tests.worker_integration_support import Hotel, create_hotel, purge
from worker import dispatch, runtime
from worker.app import DEFAULT_QUEUE, app


@pytest.fixture
def hotels(db_engine: Engine) -> Iterator[Callable[..., Hotel]]:
    created: list[Hotel] = []

    def make(label: str, **kwargs: str) -> Hotel:
        hotel = create_hotel(db_engine, label, **kwargs)
        created.append(hotel)
        return hotel

    yield make
    for hotel in created:
        purge(db_engine, hotel.tenant.workspace_id)


def _local_today(timezone: str = "Europe/Rome") -> date:
    return datetime.now(UTC).astimezone(ZoneInfo(timezone)).date()


def _enable(hotel: Hotel) -> None:
    with Session(hotel.engine) as session:
        AnalysisPolicyService(session, hotel.tenant).enable(hotel.property_id, hotel.data_source_id)


def _jobs_for(connector: testing.InMemoryConnector, hotel: Hotel) -> list[dict[str, object]]:
    return [
        dict(job)
        for job in connector.jobs.values()
        if job["args"].get("property_id") == str(hotel.property_id)
    ]


def _dispatch(connector: testing.InMemoryConnector, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()  # drop the bootstrap output of the test's own set-up
    with app.replace_connector(connector):
        assert dispatch.dispatch_analysis() == 0
    return capsys.readouterr().out


def _line_of(output: str, hotel: Hotel) -> str:
    [line] = [line for line in output.splitlines() if f"property={hotel.slug} " in line]
    return line


def _run_worker(connector: testing.InMemoryConnector) -> None:
    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())


def _statuses(connector: testing.InMemoryConnector, hotel: Hotel) -> list[str]:
    return [str(job["status"]) for job in _jobs_for(connector, hotel)]


def test_01_the_full_automatic_day_from_disabled_to_already_analyzed(
    hotels: Callable[..., Hotel],
    db_engine: Engine,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    hotel = hotels("day")
    connector = testing.InMemoryConnector()

    # 1-2. No policy at all: automation is disabled by default - nothing is enqueued.
    out = _dispatch(connector, capsys)
    assert hotel.slug not in out and _jobs_for(connector, hotel) == []

    # 3-4. Enabled with the exact source, but no import today: skipped, nothing is persisted.
    _enable(hotel)
    out = _dispatch(connector, capsys)
    assert "result=SKIPPED reason=NO_TODAY_BOOKING_IMPORT" in _line_of(out, hotel)
    assert _jobs_for(connector, hotel) == []
    assert hotel.runs() == []
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(BookingSnapshot)) == 0

    # 5-6. A valid canonical import today: exactly one job is enqueued.
    hotel.import_bookings(tmp_path)
    out = _dispatch(connector, capsys)
    assert "result=ENQUEUED" in _line_of(out, hotel)
    assert len(_jobs_for(connector, hotel)) == 1

    # 7. The worker runs it.
    with caplog.at_level(logging.INFO, logger="worker.tasks"):
        _run_worker(connector)
    assert _statuses(connector, hotel) == ["succeeded"]
    assert any(
        "Policy analysis job completed" in m and "status=succeeded" in m for m in caplog.messages
    )

    # 8. A DecisionRun exists for TODAY's property-local date.
    [run] = hotel.runs()
    assert run.as_of_local_date == _local_today()

    # 9. Coverage: Revenue + Distribution evaluated, Costs + Labor skipped (NOT_REQUESTED).
    assert run.analysis_coverage is not None
    coverage = AnalysisCoverage.from_json(run.analysis_coverage)
    assert coverage.summary is CoverageSummary.PARTIAL
    by_domain = {item.domain: item for item in coverage.domains}
    assert by_domain[AnalysisDomain.REVENUE].status.value == "EVALUATED"
    assert by_domain[AnalysisDomain.DISTRIBUTION].status.value == "EVALUATED"
    assert by_domain[AnalysisDomain.COSTS].status.value == "SKIPPED"
    assert by_domain[AnalysisDomain.LABOR].status.value == "SKIPPED"
    assert by_domain[AnalysisDomain.COSTS].reason.value == "NOT_REQUESTED"  # type: ignore[union-attr]
    assert by_domain[AnalysisDomain.LABOR].reason.value == "NOT_REQUESTED"  # type: ignore[union-attr]

    # The detectors saw the 30-date window: today .. today + 29 (the snapshot rows prove it).
    with Session(db_engine) as session:
        stay_dates = sorted(
            session.scalars(
                select(BookingSnapshot.stay_date).where(
                    BookingSnapshot.property_id == hotel.property_id,
                    BookingSnapshot.snapshot_local_date == _local_today(),
                )
            ).all()
        )
        assert len(stay_dates) == 30
        assert (stay_dates[0], stay_dates[-1]) == (
            _local_today(),
            _local_today() + timedelta(days=29),
        )

        # 11. Oggi's feed reads the very same run.
        feed = DecisionMemoryService(session, hotel.tenant).get_feed(
            hotel.property_id, _local_today()
        )
        assert feed.run is not None and feed.run.id == run.id

    # 10. A second dispatch the same day does not enqueue it again.
    out = _dispatch(connector, capsys)
    assert "result=SKIPPED reason=ALREADY_ANALYZED_TODAY" in _line_of(out, hotel)
    assert len(_jobs_for(connector, hotel)) == 1


def test_02_one_dispatch_across_workspaces_with_mixed_outcomes(
    hotels: Callable[..., Hotel],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ready, no_import, disabled, archived = (
        hotels("ready"),
        hotels("noimport"),
        hotels("disabled"),
        hotels("archived"),
    )
    for hotel in (ready, no_import, disabled, archived):
        _enable(hotel)
    ready.import_bookings(tmp_path, "ready.csv")
    archived.import_bookings(tmp_path, "archived.csv")
    with Session(disabled.engine) as session:
        AnalysisPolicyService(session, disabled.tenant).disable(disabled.property_id)
    with Session(archived.engine) as session:
        PropertyRepository(session, archived.tenant).archive(archived.property_id)
        session.commit()
    connector = testing.InMemoryConnector()

    out = _dispatch(connector, capsys)

    assert "result=ENQUEUED" in _line_of(out, ready)
    assert "reason=NO_TODAY_BOOKING_IMPORT" in _line_of(out, no_import)
    assert disabled.slug not in out  # a disabled policy is not even listed
    assert "reason=PROPERTY_INACTIVE" in _line_of(out, archived)
    assert [len(_jobs_for(connector, h)) for h in (ready, no_import, disabled, archived)] == [
        1,
        0,
        0,
        0,
    ]


def test_03_a_manual_run_today_blocks_the_automatic_run(
    hotels: Callable[..., Hotel],
    db_engine: Engine,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hotel = hotels("manual")
    _enable(hotel)
    hotel.import_bookings(tmp_path)
    with Session(db_engine) as session:  # the Gate 25 shared path, as a manual run would use
        run_property_analysis(
            session,
            AnalysisRunRequest(
                workspace_id=hotel.tenant.workspace_id,
                property_id=hotel.property_id,
                booking_data_source_id=hotel.data_source_id,
                stay_date_start=min(hotel.stay_dates),
                stay_date_end=max(hotel.stay_dates),
            ),
        )
    connector = testing.InMemoryConnector()

    out = _dispatch(connector, capsys)

    assert "reason=ALREADY_ANALYZED_TODAY" in _line_of(out, hotel)
    assert _jobs_for(connector, hotel) == []


def test_04_status_shows_enabled_properties_without_a_run_today(
    hotels: Callable[..., Hotel],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hotel = hotels("status")
    _enable(hotel)
    capsys.readouterr()

    assert dispatch.analysis_status() == 0
    before = _line_of(capsys.readouterr().out, hotel)
    assert "run_today=NO today_import=NO latest_analysis=NONE" in before
    assert "next_dispatch=SKIPPED:NO_TODAY_BOOKING_IMPORT" in before

    hotel.import_bookings(tmp_path)
    capsys.readouterr()
    assert dispatch.analysis_status() == 0
    after = _line_of(capsys.readouterr().out, hotel)
    assert "run_today=NO today_import=YES" in after and "next_dispatch=ELIGIBLE" in after

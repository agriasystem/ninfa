"""The day's analysis, without anyone asking: when it is due, for whom, and how often it is asked
for.

Injected instants on the real database (rolled back). Being due is worked out from what is stored
and from the property's own clock, so it is the same whenever and however often it is asked. The
tick itself is `services/worker/tests/test_daily_tick.py`; the whole day with real commits is below.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from procrastinate import testing
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis import (
    DAILY_ANALYSIS_LOCAL_TIME,
    DAILY_TICK_TASK,
    MAX_DAILY_ATTEMPTS,
    AnalysisPolicyService,
    AnalysisStatusService,
    AnalysisUpdateState,
    AutomaticSkipReason,
    PropertyAnalysisPolicy,
    daily_opportunities,
    enroll_ready_properties,
    prune_finished_ticks,
    run_automatic_analysis,
)
from app.modules.analysis import automatic as automatic_module
from app.modules.analysis.automatic import RETRY_AFTER
from app.modules.analysis.queue import (
    ANALYSIS_POLICY_TASK,
    analysis_lock_of,
    failed_policy_runs_since,
)
from app.modules.ingestion.models import DataSourceDomain, ImportJobStatus
from app.modules.tenancy.repository import WorkspaceRepository
from tests.analysis_policy_support import decision_run_on, enable, import_at, utc
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel
from tests.refresh_support import purge as purge_refresh_hotel
from tests.support import BookingFactory, Tenant
from tests.worker_integration_support import Hotel as PolicyHotel
from tests.worker_integration_support import create_hotel, purge
from worker import daily, runtime
from worker.app import DEFAULT_QUEUE, app

ROME_10 = utc(2026, 10, 5, 8, 0)  # 10:00 in Rome (CEST)
IMPORTED = utc(2026, 10, 1, 7, 0)  # days before: nobody imported that morning


def _ready(session: Session, factory: BookingFactory, zone: str = "Europe/Rome") -> Tenant:
    tenant = factory.tenant()
    tenant.property.timezone = zone
    session.flush()
    import_at(factory, tenant.data_source, IMPORTED)
    enable(session, tenant)
    return tenant


def _of(session: Session, tenant: Tenant, now: datetime) -> Any:
    [evaluation] = [
        item for item in daily_opportunities(session, now) if item.property_id == tenant.property.id
    ]
    return evaluation


# --- when ----------------------------------------------------------------------------------------


def test_the_daily_hour_is_the_one_gate_26b_fixed() -> None:
    assert time(10, 0) == DAILY_ANALYSIS_LOCAL_TIME


def test_it_is_due_from_the_daily_hour_on_with_no_import_that_day(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)

    assert (
        _of(db_session, tenant, ROME_10 - timedelta(minutes=1)).skip_reason
        is AutomaticSkipReason.NOT_DUE_YET
    )
    due = _of(db_session, tenant, ROME_10)
    assert due.eligible and due.qualifying_import_today is False
    assert _of(db_session, tenant, ROME_10 + timedelta(hours=9)).eligible  # later the same day too


@pytest.mark.parametrize(
    "zone, due_at, local_date",
    [
        ("Europe/Rome", utc(2026, 10, 5, 8, 0), date(2026, 10, 5)),
        ("America/New_York", utc(2026, 10, 5, 14, 0), date(2026, 10, 5)),
        ("Asia/Tokyo", utc(2026, 10, 5, 1, 0), date(2026, 10, 5)),
        ("Asia/Kolkata", utc(2026, 10, 5, 4, 30), date(2026, 10, 5)),  # half-hour offset
    ],
)
def test_each_property_has_its_own_clock(
    db_session: Session, factory: BookingFactory, zone: str, due_at: datetime, local_date: date
) -> None:
    tenant = _ready(db_session, factory, zone)

    before = _of(db_session, tenant, due_at - timedelta(minutes=1))
    assert before.skip_reason is AutomaticSkipReason.NOT_DUE_YET
    due = _of(db_session, tenant, due_at)
    assert due.eligible and due.local_date == local_date


def test_one_instant_is_a_different_moment_of_the_day_for_two_properties(
    db_session: Session, factory: BookingFactory
) -> None:
    rome, new_york = _ready(db_session, factory), _ready(db_session, factory, "America/New_York")

    assert _of(db_session, rome, ROME_10).eligible
    assert _of(db_session, new_york, ROME_10).skip_reason is AutomaticSkipReason.NOT_DUE_YET
    # Late in the evening in New York it is already tomorrow in Rome.
    evening = utc(2026, 10, 6, 2, 0)
    assert _of(db_session, new_york, evening).local_date == date(2026, 10, 5)
    assert _of(db_session, rome, evening).local_date == date(2026, 10, 6)


@pytest.mark.parametrize(
    "due_at",
    [
        utc(2026, 10, 25, 9, 0),  # Rome has just left summer time: 10:00 is UTC+1
        utc(2026, 3, 29, 8, 0),  # Rome has just entered it: 10:00 is UTC+2
    ],
)
def test_the_daily_hour_follows_daylight_saving(
    db_session: Session, factory: BookingFactory, due_at: datetime
) -> None:
    tenant = factory.tenant()
    import_at(factory, tenant.data_source, utc(2026, 1, 1))
    enable(db_session, tenant)

    assert (
        _of(db_session, tenant, due_at - timedelta(minutes=1)).skip_reason
        is AutomaticSkipReason.NOT_DUE_YET
    )
    assert _of(db_session, tenant, due_at).eligible


# --- for whom ------------------------------------------------------------------------------------


def test_a_policy_switched_off_is_not_asked_for(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    AnalysisPolicyService(db_session, tenant.context).disable(tenant.property.id)

    assert [
        item
        for item in daily_opportunities(db_session, ROME_10)
        if item.property_id == tenant.property.id
    ] == []


def test_a_day_already_analysed_is_not_asked_for_again(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    decision_run_on(db_session, tenant, date(2026, 10, 5))  # a refresh, an operator: the same row

    evaluation = _of(db_session, tenant, ROME_10)

    assert evaluation.skip_reason is AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    # ...and the next local day it is due again
    assert _of(db_session, tenant, ROME_10 + timedelta(days=1)).eligible


def test_every_property_is_decided_alone(db_session: Session, factory: BookingFactory) -> None:
    due, done, early = (
        _ready(db_session, factory),
        _ready(db_session, factory),
        _ready(db_session, factory, "America/New_York"),
    )
    decision_run_on(db_session, done, date(2026, 10, 5))

    assert _of(db_session, due, ROME_10).eligible
    assert _of(db_session, done, ROME_10).skip_reason is AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    assert _of(db_session, early, ROME_10).skip_reason is AutomaticSkipReason.NOT_DUE_YET


# --- enrolment -----------------------------------------------------------------------------------


def _policy_of(session: Session, tenant: Tenant) -> PropertyAnalysisPolicy | None:
    return session.scalar(
        select(PropertyAnalysisPolicy).where(
            PropertyAnalysisPolicy.property_id == tenant.property.id
        )
    )


def test_a_property_that_has_imported_bookings_is_switched_on_by_itself(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    import_at(factory, tenant.data_source, IMPORTED)

    assert tenant.property.id in enroll_ready_properties(db_session)

    policy = _policy_of(db_session, tenant)
    assert policy is not None and policy.enabled
    assert policy.booking_data_source_id == tenant.data_source.id
    assert policy.workspace_id == tenant.workspace.id
    assert tenant.property.id not in enroll_ready_properties(db_session)  # idempotent


def test_a_property_with_nothing_imported_is_not_switched_on(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    import_at(factory, tenant.data_source, IMPORTED, ImportJobStatus.FAILED)

    assert tenant.property.id not in enroll_ready_properties(db_session)
    assert _policy_of(db_session, tenant) is None


def test_a_policy_switched_off_is_never_switched_on_again(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    AnalysisPolicyService(db_session, tenant.context).disable(tenant.property.id)

    assert tenant.property.id not in enroll_ready_properties(db_session)

    policy = _policy_of(db_session, tenant)
    assert policy is not None and policy.enabled is False


def test_two_active_booking_sources_are_never_chosen_between(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    second = factory.data_source(tenant.property)
    import_at(factory, tenant.data_source, IMPORTED)
    import_at(factory, second, IMPORTED)

    assert tenant.property.id not in enroll_ready_properties(db_session)
    assert _policy_of(db_session, tenant) is None


def test_an_inactive_property_or_workspace_is_not_switched_on(
    db_session: Session, factory: BookingFactory
) -> None:
    closed, archived = factory.tenant(), factory.tenant()
    import_at(factory, closed.data_source, IMPORTED)
    import_at(factory, archived.data_source, IMPORTED)
    closed.property.is_active = False
    WorkspaceRepository(db_session).archive(archived.workspace.id)
    db_session.flush()

    enrolled = enroll_ready_properties(db_session)

    assert closed.property.id not in enrolled and archived.property.id not in enrolled


def test_a_labor_source_says_nothing_about_being_ready(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    labor = factory.data_source(tenant.property, domain=DataSourceDomain.LABOR)
    import_at(factory, labor, IMPORTED)

    assert tenant.property.id not in enroll_ready_properties(db_session)


def test_each_property_is_enrolled_in_its_own_workspace(
    db_session: Session, factory: BookingFactory
) -> None:
    first, second = factory.tenant(), factory.tenant()
    import_at(factory, first.data_source, IMPORTED)
    import_at(factory, second.data_source, IMPORTED)

    enroll_ready_properties(db_session)

    for tenant in (first, second):
        policy = _policy_of(db_session, tenant)
        assert policy is not None
        assert policy.workspace_id == tenant.workspace.id
        assert policy.booking_data_source_id == tenant.data_source.id


# --- how often: a job that fails is asked for again, but not for ever ----------------------------


def _failed_job(session: Session, tenant: Tenant, at: datetime, status: str = "failed") -> None:
    job_id = session.scalar(
        text(
            """
            INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args, status)
            VALUES ('default', :task, :lock, CAST(:args AS jsonb), :status) RETURNING id
            """
        ),
        {
            "task": ANALYSIS_POLICY_TASK,
            "lock": analysis_lock_of(tenant.property.id),
            "args": (
                f'{{"workspace_id": "{tenant.workspace.id}", '
                f'"property_id": "{tenant.property.id}"}}'
            ),
            "status": status,
        },
    )
    session.execute(text("DELETE FROM procrastinate_events WHERE job_id = :i"), {"i": job_id})
    session.execute(
        text("INSERT INTO procrastinate_events (job_id, type, at) VALUES (:i, 'failed', :at)"),
        {"i": job_id, "at": at},
    )


def test_a_failure_waits_before_it_is_asked_again(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    _failed_job(db_session, tenant, ROME_10)

    soon = _of(db_session, tenant, ROME_10 + RETRY_AFTER - timedelta(minutes=1))
    assert soon.skip_reason is AutomaticSkipReason.RETRY_NOT_DUE_YET
    assert _of(db_session, tenant, ROME_10 + RETRY_AFTER).eligible


def test_after_too_many_failures_the_day_gives_up_and_the_next_day_starts_again(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    for attempt in range(MAX_DAILY_ATTEMPTS):
        _failed_job(db_session, tenant, ROME_10 + attempt * RETRY_AFTER)

    late = ROME_10 + timedelta(hours=10)
    assert _of(db_session, tenant, late).skip_reason is AutomaticSkipReason.ATTEMPTS_EXHAUSTED
    assert _of(db_session, tenant, ROME_10 + timedelta(days=1)).eligible


def test_another_propertys_failures_do_not_count(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, other = _ready(db_session, factory), _ready(db_session, factory)
    for attempt in range(MAX_DAILY_ATTEMPTS):
        _failed_job(db_session, other, ROME_10 - timedelta(minutes=attempt))

    assert _of(db_session, tenant, ROME_10 + RETRY_AFTER).eligible


# --- what it analyses ----------------------------------------------------------------------------


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, session: Session, request: Any) -> Any:
        self.requests.append(request)
        return object()


def test_the_days_analysis_looks_at_what_a_refresh_looks_at(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise every day with no import would say "Non analizzati: Costi, Personale", about data
    the property really holds and yesterday's refresh really looked at."""
    tenant = _ready(db_session, factory)
    capture = _Capture()
    monkeypatch.setattr(automatic_module, "run_property_analysis", capture)
    labor_id = factory.data_source(tenant.property, domain=DataSourceDomain.LABOR).id
    monkeypatch.setattr(
        "app.modules.analysis.scope.LaborEvaluationRepository.current_plan",
        lambda self, source_id, today, days: {days[0]: []} if source_id == labor_id else {},
    )
    monkeypatch.setattr(
        "app.modules.analysis.scope.CostLineRepository.months_with_lines",
        lambda self, property_id, before, limit: [],
    )

    run_automatic_analysis(db_session, tenant.workspace.id, tenant.property.id, ROME_10)

    [request] = capture.requests
    assert request.booking_data_source_id == tenant.data_source.id
    assert request.labor_data_source_id == labor_id
    assert request.labor_work_dates == frozenset({date(2026, 10, 5)})


# --- the queue's own rows ------------------------------------------------------------------------


def _tick_job(session: Session, status: str, last_event: datetime) -> int:
    job_id = session.scalar(
        text(
            """
            INSERT INTO procrastinate_jobs (queue_name, task_name, args, status)
            VALUES ('default', :task, '{}'::jsonb, :status) RETURNING id
            """
        ),
        {"task": DAILY_TICK_TASK, "status": status},
    )
    session.execute(text("DELETE FROM procrastinate_events WHERE job_id = :i"), {"i": job_id})
    session.execute(
        text("INSERT INTO procrastinate_events (job_id, type, at) VALUES (:i, 'deferred', :at)"),
        {"i": job_id, "at": last_event},
    )
    assert isinstance(job_id, int)
    return job_id


def _job_exists(session: Session, job_id: int) -> bool:
    found = session.scalar(text("SELECT 1 FROM procrastinate_jobs WHERE id = :i"), {"i": job_id})
    return found is not None


def test_old_ticks_are_removed_and_nothing_else_is(db_session: Session) -> None:
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    old = _tick_job(db_session, "succeeded", now - timedelta(days=2))
    recent = _tick_job(db_session, "succeeded", now - timedelta(hours=1))
    failed = _tick_job(db_session, "failed", now - timedelta(days=2))

    assert prune_finished_ticks(db_session, now) >= 1

    assert not _job_exists(db_session, old)
    assert _job_exists(db_session, recent) and _job_exists(db_session, failed)


# --- a whole day, with real commits --------------------------------------------------------------


@dataclass
class _Day:
    """A due instant of today in the hotel's own zone: never before the real clock, so the imports
    just made have already ended."""

    zone: str

    def at(self, hour: int, minute: int = 0) -> datetime:
        today = datetime.now(UTC).astimezone(ZoneInfo(self.zone)).date()
        moment = datetime(
            today.year, today.month, today.day, hour, minute, tzinfo=ZoneInfo(self.zone)
        )
        return moment.astimezone(UTC)


def _tick(connector: testing.InMemoryConnector, now: datetime) -> int:
    async def scenario() -> int:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                return await daily.run_daily_tick(test_app, now)

    return runtime.run(scenario())


def _work(connector: testing.InMemoryConnector) -> None:
    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())


def _jobs(connector: testing.InMemoryConnector, property_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(job)
        for job in connector.jobs.values()
        if job["args"].get("property_id") == str(property_id)
    ]


@pytest.fixture
def hotels(db_engine: Engine) -> Iterator[Callable[..., PolicyHotel]]:
    created: list[PolicyHotel] = []

    def make(label: str, **kwargs: str) -> PolicyHotel:
        hotel = create_hotel(db_engine, label, **kwargs)
        created.append(hotel)
        return hotel

    yield make
    for hotel in created:
        purge(db_engine, hotel.tenant.workspace_id)


def _latest_due(zone: str, hour: int = 10, minute: int = 5) -> datetime:
    """Today at that local hour, or the real clock if it is later: what the tick would see."""
    return max(_Day(zone).at(hour, minute), datetime.now(UTC))


def test_a_hotel_gets_its_analysis_with_nobody_asking_and_exactly_one(
    hotels: Callable[..., PolicyHotel], tmp_path: Path
) -> None:
    hotel = hotels("alone")
    hotel.import_bookings(tmp_path)
    connector = testing.InMemoryConnector()
    now = _latest_due("Europe/Rome")

    # Enrolled by itself, then one job. Asked again before the worker ran: still one job.
    _tick(connector, now)
    _tick(connector, now)
    assert len(_jobs(connector, hotel.property_id)) == 1

    # The worker comes back and runs it: the day has its run, and it is not asked for again.
    _work(connector)
    statuses = [str(job["status"]) for job in _jobs(connector, hotel.property_id)]
    assert statuses == ["succeeded"]
    [run] = hotel.runs()
    assert run.as_of_local_date == local_today()
    _tick(connector, now)
    assert len(_jobs(connector, hotel.property_id)) == 1
    assert len(hotel.runs()) == 1


def test_a_job_run_twice_does_not_make_two_runs(
    hotels: Callable[..., PolicyHotel], tmp_path: Path, db_engine: Engine
) -> None:
    """A restart can run the same job again: it evaluates again when it runs, and skips."""
    hotel = hotels("twice")
    hotel.import_bookings(tmp_path)
    with Session(db_engine) as session:
        enroll_ready_properties(session)
    for _ in range(2):
        with Session(db_engine) as session:
            run_automatic_analysis(session, hotel.tenant.workspace_id, hotel.property_id)

    assert len(hotel.runs()) == 1


def test_a_worker_that_was_down_catches_up_the_same_local_day(
    hotels: Callable[..., PolicyHotel], tmp_path: Path
) -> None:
    hotel = hotels("late")
    hotel.import_bookings(tmp_path)
    connector = testing.InMemoryConnector()

    # No tick at 10:00: the worker was down. The first one after it, at any hour, asks for the run.
    _tick(connector, _latest_due("Europe/Rome", 21, 30))
    assert len(_jobs(connector, hotel.property_id)) == 1
    _work(connector)

    assert len(hotel.runs()) == 1


def test_two_properties_in_two_time_zones_are_each_asked_for_on_their_own_clock(
    hotels: Callable[..., PolicyHotel], tmp_path: Path, db_engine: Engine
) -> None:
    rome, tokyo = hotels("rome"), hotels("tokyo", timezone="Asia/Tokyo")
    rome.import_bookings(tmp_path, "rome.csv")
    tokyo.import_bookings(tmp_path, "tokyo.csv")

    def reasons(now: datetime) -> tuple[Any, Any]:
        with Session(db_engine) as session:
            enroll_ready_properties(session)
            found = {item.property_id: item for item in daily_opportunities(session, now)}
        return (found[rome.property_id].skip_reason, found[tokyo.property_id].skip_reason)

    # Tomorrow, so the imports just made have already ended at every instant asked about.
    tomorrow = datetime.now(UTC).astimezone(ZoneInfo("Asia/Tokyo")).date() + timedelta(days=1)

    def local(zone: str, hour: int) -> datetime:
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, tzinfo=ZoneInfo(zone))

    not_due = AutomaticSkipReason.NOT_DUE_YET
    assert reasons(local("Asia/Tokyo", 9)) == (not_due, not_due)
    assert reasons(local("Asia/Tokyo", 10)) == (not_due, None)
    assert reasons(local("Europe/Rome", 10)) == (None, None)


def test_a_page_follows_the_days_analysis_like_a_refresh(db_engine: Engine, tmp_path: Path) -> None:
    hotel: Hotel = make_hotel(db_engine, tmp_path)
    try:
        hotel.import_bookings("a.csv", [booking_row("R-1", 2)])
        with hotel.session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock,
                    args) VALUES ('default', :task, :lock, :queueing, CAST(:args AS jsonb))
                    """
                ),
                {
                    "task": ANALYSIS_POLICY_TASK,
                    "lock": analysis_lock_of(hotel.property_id),
                    "queueing": f"{ANALYSIS_POLICY_TASK}:{hotel.property_id}",
                    "args": (
                        f'{{"workspace_id": "{hotel.tenant.workspace_id}", '
                        f'"property_id": "{hotel.property_id}"}}'
                    ),
                },
            )
            session.commit()
            status = AnalysisStatusService(session, hotel.tenant).status(hotel.property_id)
        assert status.state is AnalysisUpdateState.IN_PROGRESS
    finally:
        purge_refresh_hotel(db_engine, hotel.tenant.workspace_id)


def test_the_tenant_of_a_job_comes_from_the_job(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _ready(db_session, factory)
    other = TenantContext(factory.tenant().workspace.id)
    _failed_job(db_session, tenant, ROME_10)

    assert failed_policy_runs_since(db_session, other, tenant.property.id, ROME_10)[0] == 0
    assert failed_policy_runs_since(db_session, tenant.context, tenant.property.id, ROME_10)[0] == 1

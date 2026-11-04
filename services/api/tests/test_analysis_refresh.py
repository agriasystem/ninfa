"""The refresh after an import, against the REAL test database with REAL commits.

Import -> a job on the queue's own table -> `run_refresh` -> the shared orchestration -> a run
the feed reads. What is pinned: the periods are the ones really stored; a property with no
bookings runs nothing; changed bookings are analysed the same day (`test_same_day_bookings.py` has
the whole story); a real failure propagates and leaves the data; the descriptor says each of these
and nothing else.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text

from app.cli.pilot import run_create_data_source
from app.core.tenant import TenantContext
from app.modules.analysis import (
    AnalysisStatusService,
    AnalysisUpdateState,
    RefreshOutcomeKind,
    RefreshSkipReason,
    plan_refresh,
)
from app.modules.analysis.queue import ANALYSIS_REFRESH_TASK, QueuedJobStatus, latest_refresh
from app.modules.analysis.status import DELAYED_AFTER
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import LaborEconomics, LaborRevenueGap
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import AnalysisDomain, DomainCoverageStatus
from app.modules.ingestion.models import DataSourceDomain, ImportJob, ImportJobStatus
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.costs.service import OPERATING_CATEGORIES
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from tests.refresh_support import ROME, Hotel, booking_row, local_today, make_hotel, purge
from worker.tasks import refresh_property_task


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


# --- the queue -----------------------------------------------------------------------------------


def test_a_request_is_one_job_of_the_worker_task_carrying_only_the_identity(hotel: Hotel) -> None:
    job_id = hotel.enqueue()

    assert job_id is not None
    with hotel.session() as session:
        row = session.execute(
            text(
                "SELECT task_name, queue_name, status::text, lock, queueing_lock, args "
                "FROM procrastinate_jobs WHERE id = :i"
            ),
            {"i": job_id},
        ).one()
    assert row[0] == ANALYSIS_REFRESH_TASK
    assert row[1] == "default"
    assert row[2] == "todo"
    assert row[3] == row[4] == f"{ANALYSIS_REFRESH_TASK}:{hotel.property_id}"
    assert row[5] == {
        "workspace_id": str(hotel.tenant.workspace_id),
        "property_id": str(hotel.property_id),
    }


def test_one_job_waits_at_most_per_property(hotel: Hotel) -> None:
    first = hotel.enqueue()
    second = hotel.enqueue()

    assert first is not None
    assert second is None  # it will read whatever is there when it runs: that is enough


def test_a_job_of_another_workspace_is_invisible(hotel: Hotel, db_engine: Engine) -> None:
    hotel.enqueue()

    with hotel.session() as session:
        other = TenantContext(uuid.uuid4())
        assert latest_refresh(session, other, hotel.property_id) is None
        assert latest_refresh(session, hotel.tenant, hotel.property_id) is not None


# --- the plan ------------------------------------------------------------------------------------


def test_with_no_bookings_nothing_runs_and_nothing_is_written(hotel: Hotel) -> None:
    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.SKIPPED
    assert outcome.skip_reason is RefreshSkipReason.NO_BOOKING_SOURCE
    assert hotel.runs() == []


def test_a_source_with_no_successful_import_runs_nothing(hotel: Hotel) -> None:
    hotel.bookings_source()

    outcome = hotel.refresh()

    assert outcome.skip_reason is RefreshSkipReason.NO_BOOKING_IMPORT


def test_several_booking_sources_are_never_chosen_between(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    with hotel.session() as session:
        run_create_data_source(
            session,
            workspace_slug=hotel.slug,
            property_slug=hotel.slug,
            name="Altre prenotazioni",
            domain=DataSourceDomain.BOOKINGS,
        )

    assert hotel.refresh().skip_reason is RefreshSkipReason.SEVERAL_BOOKING_SOURCES
    assert hotel.status().state is AnalysisUpdateState.SEVERAL_SOURCES


def test_bookings_run_the_same_thirty_nights_as_the_automatic_analysis(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    with hotel.session() as session:
        plan = plan_refresh(session, hotel.tenant, hotel.property_id, datetime.now(UTC))

    assert not isinstance(plan, RefreshSkipReason)
    assert plan.request.stay_date_start == local_today()
    assert plan.request.stay_date_end == local_today() + timedelta(days=29)
    # nothing else was imported: nothing else is requested, and nothing is assumed
    assert plan.request.labor_data_source_id is None
    assert plan.request.cost_periods == ()


def test_labor_is_evaluated_only_on_the_dates_it_really_has(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    covered = [local_today() + timedelta(days=2), local_today() + timedelta(days=3)]
    outside = local_today() + timedelta(days=60)
    source_id = hotel.import_labor([*covered, outside])

    with hotel.session() as session:
        plan = plan_refresh(session, hotel.tenant, hotel.property_id, datetime.now(UTC))

    assert not isinstance(plan, RefreshSkipReason)
    assert plan.request.labor_data_source_id == source_id
    assert plan.request.labor_work_dates == frozenset(covered)


def test_a_labor_file_entirely_in_the_past_leaves_labor_out_of_the_run(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.import_labor([local_today() - timedelta(days=5)])

    with hotel.session() as session:
        plan = plan_refresh(session, hotel.tenant, hotel.property_id, datetime.now(UTC))

    assert not isinstance(plan, RefreshSkipReason)
    assert plan.request.labor_data_source_id is None
    assert plan.request.labor_work_dates is None


def test_costs_are_the_concluded_months_the_invoices_touch_never_the_current_one(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    today = local_today()
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    two_months_ago = last_month.replace(day=1) - timedelta(days=1)
    hotel.import_invoices([two_months_ago, last_month, today])

    with hotel.session() as session:
        plan = plan_refresh(session, hotel.tenant, hotel.property_id, datetime.now(UTC))

    assert not isinstance(plan, RefreshSkipReason)
    assert plan.request.cost_periods == (
        (two_months_ago.year, two_months_ago.month),
        (last_month.year, last_month.month),
    )


# --- running it ----------------------------------------------------------------------------------


def test_a_refresh_after_a_bookings_import_reaches_the_feed_home_reads(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3), booking_row("B", 4)])

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.booking_data_source_id == hotel.booking_source_id
    assert outcome.result.as_of_local_date == local_today()
    assert len(hotel.runs()) == 1
    with hotel.session() as session:
        feed = DecisionMemoryService(session, hotel.tenant).get_feed(
            hotel.property_id, local_today()
        )
    assert feed.run is not None
    assert feed.state is not FeedState.NOT_PROCESSED
    # the run records what it looked at: bookings yes; what was not imported was not looked at
    domains = {item.domain: item.status for item in outcome.result.coverage.domains}
    assert domains[AnalysisDomain.REVENUE] is DomainCoverageStatus.EVALUATED
    assert domains[AnalysisDomain.DISTRIBUTION] is DomainCoverageStatus.EVALUATED
    assert domains[AnalysisDomain.LABOR] is DomainCoverageStatus.SKIPPED
    assert domains[AnalysisDomain.COSTS] is DomainCoverageStatus.SKIPPED
    # provenance: the import this run saw
    assert outcome.result.provenance.bookings.import_job_id is not None


def test_a_property_with_no_room_inventory_is_analysed_and_only_capacity_is_limited(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.evaluation_count > 0


def test_running_it_again_on_the_same_data_is_a_replay(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.refresh()

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.is_idempotent_replay is True
    assert len(hotel.runs()) == 1


def test_changed_bookings_on_the_same_day_are_analysed_the_same_day(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    assert hotel.refresh().kind is RefreshOutcomeKind.RAN
    hotel.import_bookings("b.csv", [booking_row("A", 3), booking_row("B", 3)])

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.retry_at is None
    assert len(hotel.runs()) == 2


def test_a_key_that_cannot_be_observed_yet_is_deferred_not_forced_and_not_failed(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What is left of DEFERRED: a stored row NINFA cannot observe over (a reconstruction of what
    is today only after the property's time zone changed). It clears by itself tomorrow."""
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise SnapshotError(SnapshotErrorCode.CONFLICT, "a reconstruction holds the key")

    monkeypatch.setattr("app.modules.analysis.refresh.run_property_analysis", refuse)

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.DEFERRED
    tomorrow = local_today() + timedelta(days=1)
    assert outcome.retry_at.astimezone(ROME).date() == tomorrow
    assert hotel.runs() == []


def test_a_real_failure_propagates_and_the_data_stay(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("app.modules.analysis.refresh.run_property_analysis", explode)

    with pytest.raises(RuntimeError):
        hotel.refresh()

    assert hotel.runs() == []
    with hotel.session() as session:
        jobs = session.scalar(
            select(func.count())
            .select_from(ImportJob)
            .where(
                ImportJob.workspace_id == hotel.tenant.workspace_id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
            )
        )
    assert jobs == 1


# --- the worker's own task, on the real database --------------------------------------------------


def _labor_economics(hotel: Hotel) -> LaborEconomics:
    with hotel.session() as session:
        overview = DataOverviewService(session, hotel.tenant).overview(
            hotel.property_id, local_today()
        )
    return overview.labor.economics


def _task(hotel: Hotel) -> None:
    refresh_property_task(
        workspace_id=str(hotel.tenant.workspace_id), property_id=str(hotel.property_id)
    )


def test_the_worker_task_runs_the_refresh_and_the_home_reads_its_result(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    _task(hotel)

    assert len(hotel.runs()) == 1
    with hotel.session() as session:
        feed = DecisionMemoryService(session, hotel.tenant).get_feed(
            hotel.property_id, local_today()
        )
    assert feed.state is not FeedState.NOT_PROCESSED


def test_the_worker_task_queues_a_deferred_refresh_for_tomorrow(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    _task(hotel)
    hotel.import_bookings("b.csv", [booking_row("A", 3), booking_row("B", 3)])

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise SnapshotError(SnapshotErrorCode.CONFLICT, "a reconstruction holds the key")

    monkeypatch.setattr("app.modules.analysis.refresh.run_property_analysis", refuse)

    _task(hotel)  # no exception: it is not a failure

    with hotel.session() as session:
        job = latest_refresh(session, hotel.tenant, hotel.property_id)
    assert job is not None
    assert job.status is QueuedJobStatus.TODO
    assert job.scheduled_at is not None
    assert job.scheduled_at.astimezone(ROME).date() == local_today() + timedelta(days=1)
    status = hotel.status()
    assert status.state is AnalysisUpdateState.DEFERRED
    assert status.next_attempt_at == job.scheduled_at
    assert len(hotel.runs()) == 1


def test_a_failure_in_the_worker_leaves_the_data_and_no_false_update(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    job_id = hotel.enqueue()
    assert job_id is not None

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("worker.tasks.run_refresh", explode)

    with pytest.raises(RuntimeError):
        _task(hotel)
    hotel.set_job(job_id, QueuedJobStatus.FAILED.value)  # what the queue does with that exception

    status = hotel.status()
    assert status.state is AnalysisUpdateState.FAILED
    assert status.last_analysis_at is None
    assert status.imported_domains == (DataSourceDomain.BOOKINGS,)
    assert hotel.runs() == []


# --- each kind of data, through the whole refresh -------------------------------------------------


def test_labor_is_evaluated_for_the_period_its_file_touches(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.import_labor([local_today() + timedelta(days=2), local_today() + timedelta(days=3)])

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.labor_target_count == 2  # two of the thirty nights: the file's own days
    domains = {item.domain: item.status for item in outcome.result.coverage.domains}
    assert domains[AnalysisDomain.LABOR] is DomainCoverageStatus.EVALUATED


def test_a_file_of_several_months_of_costs_evaluates_each_of_them(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    first_of_month = local_today().replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    two_months_ago = last_month.replace(day=1) - timedelta(days=1)
    hotel.import_invoices([two_months_ago, last_month])

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.cost_currency == "EUR"
    assert outcome.result.cost_category_count == 2 * len(OPERATING_CATEGORIES)
    domains = {item.domain: item.status for item in outcome.result.coverage.domains}
    assert domains[AnalysisDomain.COSTS] is DomainCoverageStatus.EVALUATED


def test_invoices_of_the_month_in_progress_alone_evaluate_no_month(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.import_invoices([local_today()])

    outcome = hotel.refresh()

    assert outcome.result.cost_category_count is None
    domains = {item.domain: item.status for item in outcome.result.coverage.domains}
    assert domains[AnalysisDomain.COSTS] is DomainCoverageStatus.SKIPPED


def test_after_the_refresh_labor_meets_the_revenue_of_the_same_days(hotel: Hotel) -> None:
    day = local_today() + timedelta(days=1)
    hotel.import_bookings("a.csv", [booking_row("A", 1, revenue="150.00")])
    hotel.import_labor([day])  # 8 h, 120.00 EUR on that day (the fixture's)

    before = _labor_economics(hotel)
    assert before.planned_hours == Decimal("8.00")
    assert before.reference_revenue is None  # no observation yet: nothing is invented

    assert hotel.refresh().kind is RefreshOutcomeKind.RAN

    after = _labor_economics(hotel)
    assert after.planned_hours == Decimal("8.00")
    assert after.planned_cost == Decimal("120.00")
    assert after.average_hourly_cost == Decimal("15.00")
    assert after.reference_revenue == Decimal("150.00")
    assert after.cost_to_revenue_pct == Decimal("80.00")
    assert after.revenue_per_hour == Decimal("18.75")
    assert (after.period_start, after.period_end) == (day, day)


def test_labor_of_a_day_with_no_booking_has_no_ratio_rather_than_another_days_revenue(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 1, revenue="150.00")])
    hotel.import_labor([local_today() + timedelta(days=3)])  # nothing is booked for that night

    hotel.refresh()

    after = _labor_economics(hotel)
    assert after.planned_hours == Decimal("8.00")
    assert after.reference_revenue is None
    assert after.revenue_gap is LaborRevenueGap.NO_REVENUE
    assert after.cost_to_revenue_pct is None


# --- the descriptor ------------------------------------------------------------------------------


def test_nothing_imported_is_no_data(hotel: Hotel) -> None:
    status = hotel.status()

    assert status.state is AnalysisUpdateState.NO_DATA
    assert status.imported_domains == ()
    assert status.latest_import_at is None
    assert status.can_retry is False


def test_labor_without_bookings_is_not_empty_it_needs_bookings(hotel: Hotel) -> None:
    hotel.import_labor([local_today() + timedelta(days=1)])

    status = hotel.status()

    assert status.state is AnalysisUpdateState.NEEDS_BOOKINGS
    assert status.imported_domains == (DataSourceDomain.LABOR,)
    assert status.latest_import_at is not None
    assert status.can_retry is False


def test_a_new_import_with_no_refresh_under_way_is_new_data_and_can_be_asked_again(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])

    status = hotel.status()

    assert status.state is AnalysisUpdateState.NEW_DATA
    assert status.can_retry is True


def test_a_job_waiting_or_running_is_in_progress(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    job_id = hotel.enqueue()
    assert job_id is not None
    assert hotel.status().state is AnalysisUpdateState.IN_PROGRESS

    hotel.set_job(job_id, QueuedJobStatus.DOING.value)

    status = hotel.status()
    assert status.state is AnalysisUpdateState.IN_PROGRESS
    assert status.can_retry is False


def test_a_job_that_takes_too_long_is_delayed_not_failed_and_not_in_progress_for_ever(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.enqueue()

    later = datetime.now(UTC) + DELAYED_AFTER + timedelta(minutes=1)

    assert hotel.status(later).state is AnalysisUpdateState.DELAYED


def test_a_succeeded_job_is_up_to_date_even_when_it_was_an_exact_replay(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    job_id = hotel.enqueue()
    assert job_id is not None
    hotel.refresh()
    hotel.set_job(job_id, QueuedJobStatus.SUCCEEDED.value)

    status = hotel.status()

    assert status.state is AnalysisUpdateState.UP_TO_DATE
    assert status.last_analysis_at is not None
    assert status.can_retry is False


def test_a_failed_job_is_failed_the_imports_stand_and_it_can_be_asked_again(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    job_id = hotel.enqueue()
    assert job_id is not None
    hotel.set_job(job_id, QueuedJobStatus.FAILED.value)

    status = hotel.status()

    assert status.state is AnalysisUpdateState.FAILED
    assert status.can_retry is True
    assert status.imported_domains == (DataSourceDomain.BOOKINGS,)
    assert status.last_analysis_at is None  # never a false "updated"


def test_retry_queues_a_job_only_when_nothing_else_would_happen(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    with hotel.session() as session:
        service = AnalysisStatusService(session, hotel.tenant)
        assert service.retry(hotel.property_id).state is AnalysisUpdateState.IN_PROGRESS
        waiting = latest_refresh(session, hotel.tenant, hotel.property_id)
        assert waiting is not None
        # one is waiting already: asking again changes nothing
        assert service.retry(hotel.property_id).state is AnalysisUpdateState.IN_PROGRESS
        same = latest_refresh(session, hotel.tenant, hotel.property_id)
        assert same is not None
        assert same.job_id == waiting.job_id


def test_a_refresh_told_to_wait_for_tomorrow_is_deferred_and_says_until_when(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    tomorrow = datetime.now(UTC) + timedelta(hours=20)
    hotel.enqueue(scheduled_at=tomorrow)

    status = hotel.status()

    assert status.state is AnalysisUpdateState.DEFERRED
    assert status.next_attempt_at == tomorrow
    assert status.can_retry is False


def test_an_import_newer_than_the_last_job_is_new_data_again(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    job_id = hotel.enqueue()
    assert job_id is not None
    hotel.refresh()
    hotel.set_job(job_id, QueuedJobStatus.SUCCEEDED.value)
    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE

    hotel.import_bookings("b.csv", [booking_row("A", 3), booking_row("B", 4)])

    assert hotel.status().state is AnalysisUpdateState.NEW_DATA


def test_a_property_analysed_before_refreshes_existed_is_read_from_its_runs(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.refresh()  # a run, and no job at all

    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE


def test_a_source_switched_off_no_longer_speaks_for_the_property(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    with hotel.session() as session:
        source_id = hotel.bookings_source()
        DataSourceRepository(session, hotel.tenant).deactivate(source_id)
        session.commit()

    assert hotel.status().state is AnalysisUpdateState.NO_DATA

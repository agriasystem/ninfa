"""No new booking data is not zero pickup, and is no position a shortfall can be read from.

A real hotel, real files and the real engines, with real commits. `seed_slow_night` builds a night
whose comparable nights all gained ten rooms in their last week and ended on thirty: the real
detectors speak when this night stays low. What is pinned: they speak only when the source has
really said something new; what was last known stays visible; a day that said nothing is no sample
of history; a day that did is; and nothing here stops the day's analysis or a file arriving later.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from procrastinate import testing
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.analysis import enroll_ready_properties
from app.modules.analysis.observation import (
    BookingObservationFreshness,
    booking_observation_freshness,
)
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import Availability
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import AnalysisDomain, DomainCoverageStatus
from app.modules.decisions.models import Decision
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.decisions.service import DecisionService
from app.modules.ingestion.models import ImportJob, ImportJobStatus
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    PickupFacts,
    ReasonCode,
    RevenueDecisionEvaluation,
    RevenueSignals,
)
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import ObservationHistory
from tests.analysis_policy_support import import_at, utc
from tests.decision_support import sync_run
from tests.expected_support import ELIGIBLE, Scenario
from tests.refresh_support import (
    Hotel,
    analysed_on,
    booking_row,
    comparable_nights,
    curve_prior_days_keeping_anchors,
    local_today,
    make_hotel,
    pickup_decisions,
    purge,
    rooms_on,
    seed_slow_night,
    slow_stay,
)
from tests.support import BookingFactory, Tenant
from worker import daily, runtime
from worker.app import DEFAULT_QUEUE, app

YESTERDAY = "ieri.csv"


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Path) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


@pytest.fixture
def slow_night(hotel: Hotel) -> date:
    return seed_slow_night(hotel)


def latest_changing_job(hotel: Hotel) -> ImportJob:
    with hotel.session() as session:
        job = session.scalar(
            select(ImportJob)
            .where(
                ImportJob.workspace_id == hotel.tenant.workspace_id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
                ImportJob.changed_data.is_not(False),
            )
            .order_by(ImportJob.finished_at.desc())
            .limit(1)
        )
    assert job is not None
    return job


def saw_the_latest_import(hotel: Hotel, day: date) -> None:
    """The run of an earlier day saw what the source holds now."""
    job = latest_changing_job(hotel)
    analysed_on(hotel, day, import_job_id=job.id, finished_at=job.finished_at)


def imported_and_analysed_yesterday(hotel: Hotel, slow: date) -> int:
    """The hotel brought a file yesterday, and yesterday's analysis saw it."""
    offset = (slow - local_today()).days
    hotel.import_bookings(YESTERDAY, rooms_on(offset, 2))
    saw_the_latest_import(hotel, local_today() - timedelta(days=1))
    return offset


def freshness_on(hotel: Hotel, day: date) -> BookingObservationFreshness:
    """What the analysis of `day` would be told, with what the source holds now."""
    with hotel.session() as session:
        return booking_observation_freshness(
            session,
            hotel.tenant,
            property_id=hotel.property_id,
            data_source_id=hotel.bookings_source(),
            as_of_local_date=day,
            import_job_id=latest_changing_job(hotel).id,
        )


def samples(freshness: BookingObservationFreshness) -> frozenset[date]:
    return frozenset(freshness.history.newest_revision)


def signals_of(hotel: Hotel, stay: date) -> RevenueSignals:
    """Both detectors on today's observation of that night, told what the run was told."""
    freshness = freshness_on(hotel, local_today())
    with hotel.session() as session:
        [signals] = RevenueDecisionService(session, hotel.tenant).evaluate_snapshot_date(
            property_id=hotel.property_id,
            data_source_id=hotel.bookings_source(),
            snapshot_local_date=local_today(),
            stay_date_start=stay,
            stay_date_end=stay,
            observation_is_fresh=freshness.fresh,
            history=freshness.history,
        )
    return signals


def pickup_of(hotel: Hotel, stay: date) -> RevenueDecisionEvaluation:
    return signals_of(hotel, stay).pickup_low


def occupancy_of(hotel: Hotel, stay: date) -> RevenueDecisionEvaluation:
    return signals_of(hotel, stay).occupancy_risk


def facts_of(pickup: RevenueDecisionEvaluation) -> PickupFacts:
    assert isinstance(pickup.facts, PickupFacts)
    return pickup.facts


def occupancy_decisions(hotel: Hotel) -> list[Decision]:
    with hotel.session() as session:
        return list(
            session.scalars(
                select(Decision).where(
                    Decision.workspace_id == hotel.tenant.workspace_id,
                    Decision.decision_type == "REV_OCCUPANCY_RISK",
                )
            ).all()
        )


def tomorrow() -> date:
    return local_today() + timedelta(days=1)


# --- A: a new day, nothing new ----------------------------------------------------------------


def test_a_day_with_no_new_booking_data_has_a_run_and_no_pickup(
    hotel: Hotel, slow_night: date
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)

    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is False
    assert result.as_of_local_date == local_today()  # the day's analysis is not stopped
    assert pickup_decisions(hotel) == []  # no decision, and no negative signal
    pickup = pickup_of(hotel, slow_night)
    assert pickup.status is EvaluationStatus.INSUFFICIENT_DATA
    assert pickup.reason_codes == (ReasonCode.BOOKING_DATA_STALE,)
    assert facts_of(pickup).actual_pickup is None  # not measured: not zero


def test_a_day_with_no_new_booking_data_is_no_sample_for_the_days_after_it(
    hotel: Hotel, slow_night: date
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)
    hotel.refresh()

    assert local_today() not in samples(freshness_on(hotel, tomorrow()))


def test_several_days_with_nothing_new_are_each_no_sample(hotel: Hotel, slow_night: date) -> None:
    offset = (slow_night - local_today()).days
    hotel.import_bookings(YESTERDAY, rooms_on(offset, 2))
    first, second, third = (local_today() - timedelta(days=n) for n in (3, 2, 1))
    for day in (first, second, third):
        saw_the_latest_import(hotel, day)

    freshness = freshness_on(hotel, local_today())

    assert samples(freshness) & {first, second, third} == {first}
    assert freshness.fresh is False


# --- the occupancy risk: no new data, no new reading of where a night stands ------------------


def test_no_new_booking_data_leaves_the_occupancy_risk_unevaluated_and_opens_nothing(
    hotel: Hotel, slow_night: date
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)

    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is False
    occupancy = occupancy_of(hotel, slow_night)
    assert occupancy.status is EvaluationStatus.INSUFFICIENT_DATA
    assert occupancy.reason_codes == (ReasonCode.BOOKING_DATA_STALE,)
    assert occupancy_decisions(hotel) == []
    assert result.decisions_created == 0


def test_what_was_last_known_stays_visible_on_a_day_with_no_new_booking_data(
    hotel: Hotel, slow_night: date
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)
    last_file = latest_changing_job(hotel).finished_at

    hotel.refresh()

    with hotel.session() as session:
        overview = DataOverviewService(session, hotel.tenant).overview(
            hotel.property_id, local_today(), 30
        )
    assert overview.occupancy.state is Availability.AVAILABLE
    night = next(row for row in overview.occupancy.nights if row.stay_date == slow_night)
    assert night.has_data is True
    assert night.rooms_on_books == 2
    assert night.room_revenue == 300  # two rooms at 150,00
    assert night.adr == 150
    assert night.occupancy_pct == 5  # 2 of the 40 of that night
    assert overview.occupancy.selected is not None
    assert overview.occupancy.selected.room_nights == 2
    # ...and when it was last known, for whoever reads it. Nothing says "up to date".
    assert overview.freshness.bookings.known is True
    assert overview.freshness.bookings.finished_at == last_file
    assert overview.feed_state is FeedState.DATA_QUALITY_LIMITED


def test_a_new_booking_update_makes_the_occupancy_risk_speak_again(
    hotel: Hotel, slow_night: date
) -> None:
    offset = imported_and_analysed_yesterday(hotel, slow_night)
    hotel.refresh()
    assert occupancy_of(hotel, slow_night).reason_codes == (ReasonCode.BOOKING_DATA_STALE,)

    # today's file changes something: the position of the night is known again, and it is low
    hotel.import_bookings("oggi.csv", [*rooms_on(offset, 2), booking_row("ALTRA", offset + 2)])
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    occupancy = occupancy_of(hotel, slow_night)
    assert occupancy.status is EvaluationStatus.TRIGGERED
    assert occupancy.reason_codes == (ReasonCode.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL,)
    assert len(occupancy_decisions(hotel)) == 1


def test_the_morning_says_nothing_of_occupancy_and_the_afternoons_refresh_evaluates_it(
    hotel: Hotel, slow_night: date
) -> None:
    offset = imported_and_analysed_yesterday(hotel, slow_night)

    morning = hotel.refresh().result
    assert morning is not None and morning.booking_observation_fresh is False
    assert occupancy_decisions(hotel) == []

    hotel.import_bookings(
        "pomeriggio.csv", [*rooms_on(offset, 2), booking_row("ALTRA", offset + 2)]
    )
    assert hotel.enqueue() is not None  # the morning's job holds nothing back
    afternoon = hotel.refresh().result

    assert afternoon is not None and afternoon.booking_observation_fresh is True
    assert afternoon.decision_run_id != morning.decision_run_id
    assert occupancy_of(hotel, slow_night).status is EvaluationStatus.TRIGGERED
    assert len(occupancy_decisions(hotel)) == 1
    assert len(hotel.runs_today()) == 2


def test_an_open_occupancy_risk_is_not_touched_as_if_the_data_were_current(
    hotel: Hotel, slow_night: date
) -> None:
    offset = (slow_night - local_today()).days
    hotel.import_bookings("oggi.csv", rooms_on(offset, 2))
    hotel.refresh()
    [opened] = occupancy_decisions(hotel)
    assert opened.triggered_observation_count == 1

    # the same evaluation, told that the source has nothing new
    with hotel.session() as session:
        [signals] = RevenueDecisionService(session, hotel.tenant).evaluate_snapshot_date(
            property_id=hotel.property_id,
            data_source_id=hotel.bookings_source(),
            snapshot_local_date=local_today(),
            stay_date_start=slow_night,
            stay_date_end=slow_night,
            observation_is_fresh=False,
            history=freshness_on(hotel, local_today()).history,
        )
        evaluations = [signals.pickup_low, signals.occupancy_risk]
        context = PriorityContext(hotel.tenant.workspace_id, hotel.property_id, local_today())
        DecisionService(session, hotel.tenant).sync(
            context, PriorityService().rank(context, evaluations), evaluations
        )

    [after] = occupancy_decisions(hotel)
    assert after.id == opened.id
    assert after.status == opened.status  # not resolved either: nothing says the risk went away
    assert after.triggered_observation_count == 1
    assert after.last_seen_local_date == opened.last_seen_local_date
    assert after.episode_count == 1


def test_labor_and_costs_are_not_told_they_are_stale_because_no_file_came_today(
    hotel: Hotel, slow_night: date
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)
    last_month = local_today().replace(day=1) - timedelta(days=1)
    hotel.import_labor([local_today() + timedelta(days=2), local_today() + timedelta(days=3)])
    hotel.import_invoices([last_month])

    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is False
    assert result.labor_target_count == 2
    assert result.labor_evaluation_count is not None and result.labor_evaluation_count > 0
    assert result.cost_category_count is not None and result.cost_category_count > 0
    domains = {item.domain: item.status for item in result.coverage.domains}
    assert domains[AnalysisDomain.LABOR] is DomainCoverageStatus.EVALUATED
    assert domains[AnalysisDomain.COSTS] is DomainCoverageStatus.EVALUATED


# --- the first run ----------------------------------------------------------------------------


def test_the_first_run_is_not_blocked_and_is_the_first_sample(hotel: Hotel) -> None:
    """Nothing to compare with is not "nothing new": the first valid observation is the start."""
    hotel.import_bookings("primo.csv", rooms_on(10, 2))

    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    assert result.as_of_local_date == local_today()
    stay = local_today() + timedelta(days=10)
    assert occupancy_of(hotel, stay).reason_codes != (ReasonCode.BOOKING_DATA_STALE,)
    assert pickup_of(hotel, stay).reason_codes != (ReasonCode.BOOKING_DATA_STALE,)
    assert samples(freshness_on(hotel, tomorrow())) == {local_today()}


def test_the_first_run_can_already_speak_from_a_reconstructed_history(hotel: Hotel) -> None:
    stay = seed_slow_night(hotel, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE, analysed=False)
    assert hotel.runs() == []

    hotel.import_bookings("primo.csv", rooms_on((stay - local_today()).days, 2))
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    assert occupancy_of(hotel, stay).status is EvaluationStatus.TRIGGERED
    assert len(occupancy_decisions(hotel)) == 1
    # the pickup still needs two OBSERVED ends, as it always did
    assert pickup_of(hotel, stay).reason_codes == (ReasonCode.PICKUP_PRIOR_OBSERVATION_MISSING,)


# --- B: a new day, new data: what the night really did in its week ----------------------------


def test_new_data_with_a_night_that_gained_nothing_in_its_week_is_a_pickup_of_exactly_zero(
    hotel: Hotel,
) -> None:
    """Two rooms a week ago, the same two today, and a booking elsewhere: the source has spoken."""
    stay = seed_slow_night(hotel, rooms_a_week_ago=2)
    offset = imported_and_analysed_yesterday(hotel, stay)

    hotel.import_bookings("oggi.csv", [*rooms_on(offset, 2), booking_row("ALTRA", offset + 2)])
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    pickup = pickup_of(hotel, stay)
    facts = facts_of(pickup)
    assert (facts.prior_rooms_on_books, facts.current_rooms_on_books) == (2, 2)
    assert facts.actual_pickup == 0  # measured, and zero
    assert facts.expected_pickup == 10
    assert facts.missing_rooms == 10
    assert pickup.status is EvaluationStatus.TRIGGERED
    assert len(pickup_decisions(hotel)) == 1


def test_new_data_with_a_night_that_gained_one_room_in_its_week_is_a_pickup_of_one(
    hotel: Hotel, slow_night: date
) -> None:
    """One room a week ago, two today: still since yesterday, but the week is what counts."""
    offset = imported_and_analysed_yesterday(hotel, slow_night)

    hotel.import_bookings("oggi.csv", [*rooms_on(offset, 2), booking_row("ALTRA", offset + 2)])
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    pickup = pickup_of(hotel, slow_night)
    facts = facts_of(pickup)
    assert (facts.prior_rooms_on_books, facts.current_rooms_on_books) == (1, 2)
    assert facts.actual_pickup == 1
    assert facts.expected_pickup == 10
    assert facts.missing_rooms == 9
    assert pickup.status is EvaluationStatus.TRIGGERED
    assert len(pickup_decisions(hotel)) == 1
    # ...and that day is a sample like any other
    assert local_today() in samples(freshness_on(hotel, tomorrow()))


# --- C: nothing in the morning, a file in the afternoon ---------------------------------------


def test_the_morning_says_nothing_and_a_file_in_the_afternoon_is_read_normally(
    hotel: Hotel, slow_night: date
) -> None:
    offset = imported_and_analysed_yesterday(hotel, slow_night)

    morning = hotel.refresh().result
    assert morning is not None and morning.booking_observation_fresh is False
    assert pickup_decisions(hotel) == []
    assert local_today() not in samples(freshness_on(hotel, tomorrow()))

    # the morning's job left nothing behind that holds the afternoon's back
    hotel.import_bookings(
        "pomeriggio.csv", [*rooms_on(offset, 2), booking_row("ALTRA", offset + 2)]
    )
    assert hotel.enqueue() is not None
    afternoon = hotel.refresh().result

    assert afternoon is not None and afternoon.booking_observation_fresh is True
    assert afternoon.decision_run_id != morning.decision_run_id
    assert afternoon.is_idempotent_replay is False
    assert pickup_of(hotel, slow_night).status is EvaluationStatus.TRIGGERED
    assert len(pickup_decisions(hotel)) == 1
    # the day's last run is the one that counts: from then on the day is a sample
    assert local_today() in samples(freshness_on(hotel, tomorrow()))


# --- D: the same file again -------------------------------------------------------------------


def test_the_same_file_again_is_no_new_observation(hotel: Hotel, slow_night: date) -> None:
    offset = imported_and_analysed_yesterday(hotel, slow_night)
    seen = latest_changing_job(hotel).id

    hotel.import_bookings("ieri-di-nuovo.csv", rooms_on(offset, 2))

    assert latest_changing_job(hotel).id == seen  # a no-op, as Smart Import says
    result = hotel.refresh().result
    assert result is not None and result.booking_observation_fresh is False
    assert pickup_decisions(hotel) == []
    assert occupancy_decisions(hotel) == []
    again = hotel.refresh().result
    assert again is not None and again.is_idempotent_replay is True
    assert again.decision_run_id == result.decision_run_id


# --- E: a revision of the same day ------------------------------------------------------------


def test_a_change_the_same_day_is_the_days_next_revision_and_it_is_read(
    hotel: Hotel, slow_night: date
) -> None:
    offset = imported_and_analysed_yesterday(hotel, slow_night)
    hotel.refresh()
    assert pickup_of(hotel, slow_night).reason_codes == (ReasonCode.BOOKING_DATA_STALE,)

    # the rooms arrive: a real pickup, above what history expects
    hotel.import_bookings("pomeriggio.csv", rooms_on(offset, 14))
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    pickup = pickup_of(hotel, slow_night)
    assert pickup.status is EvaluationStatus.CLEAR
    assert facts_of(pickup).actual_pickup == 13
    assert pickup_decisions(hotel) == []
    with hotel.session() as session:
        revisions = session.scalars(
            select(BookingSnapshot.revision)
            .where(
                BookingSnapshot.property_id == hotel.property_id,
                BookingSnapshot.snapshot_local_date == local_today(),
                BookingSnapshot.stay_date == slow_night,
            )
            .order_by(BookingSnapshot.revision)
        ).all()
    assert list(revisions) == [1, 2]


def test_two_new_files_the_same_day_are_each_new(hotel: Hotel, slow_night: date) -> None:
    """With no earlier day, and with files both times, nothing changes from what it always did."""
    offset = (slow_night - local_today()).days

    hotel.import_bookings("mattina.csv", rooms_on(offset, 2))
    morning = hotel.refresh().result
    hotel.import_bookings("pomeriggio.csv", rooms_on(offset, 3))
    afternoon = hotel.refresh().result

    assert morning is not None and morning.booking_observation_fresh is True
    assert afternoon is not None and afternoon.booking_observation_fresh is True
    assert len(pickup_decisions(hotel)) == 1


# --- F: the scheduler, and its restart --------------------------------------------------------


def _at_daily_hour() -> datetime:
    today = local_today()
    rome = datetime(today.year, today.month, today.day, 10, 5, tzinfo=ZoneInfo("Europe/Rome"))
    return max(rome.astimezone(UTC), datetime.now(UTC))


def test_the_scheduler_still_runs_and_a_restart_makes_nothing_new(
    hotel: Hotel, slow_night: date, db_engine: Engine
) -> None:
    imported_and_analysed_yesterday(hotel, slow_night)
    with Session(db_engine) as session:
        enroll_ready_properties(session)
    connector = testing.InMemoryConnector()

    async def tick_and_work() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await daily.run_daily_tick(test_app, _at_daily_hour())
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    # the worker asks by itself, with no file that morning: the day has its run, and no signal
    runtime.run(tick_and_work())
    today_runs = [run.id for run in hotel.runs_today()]
    assert len(today_runs) == 1
    assert pickup_decisions(hotel) == []
    assert occupancy_decisions(hotel) == []

    # a restart asks again: no second run, and nothing has become new
    runtime.run(tick_and_work())
    assert [run.id for run in hotel.runs_today()] == today_runs
    assert pickup_decisions(hotel) == []
    assert pickup_of(hotel, slow_night).reason_codes == (ReasonCode.BOOKING_DATA_STALE,)
    again = hotel.refresh().result
    assert again is not None and again.is_idempotent_replay is True


# --- G: history -------------------------------------------------------------------------------


def test_a_history_of_days_with_nothing_new_teaches_nothing_even_on_a_day_with_new_data(
    hotel: Hotel,
) -> None:
    # the comparable observations (ten days before each night) all come from days with nothing new
    stay = slow_stay()
    anchors = {night - timedelta(days=10) for night in comparable_nights(stay)}
    seed_slow_night(hotel, repeated=anchors)

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 3))
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    pickup = pickup_of(hotel, stay)
    assert pickup.status is EvaluationStatus.INSUFFICIENT_DATA
    assert pickup.reason_codes == (ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,)
    assert pickup_decisions(hotel) == []


def test_a_prior_from_a_day_with_nothing_new_is_no_prior(hotel: Hotel) -> None:
    """A week ago said nothing new: what it says cannot be subtracted from today."""
    stay = seed_slow_night(hotel, repeated={local_today() - timedelta(days=7)})

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 3))
    hotel.refresh()

    pickup = pickup_of(hotel, stay)
    assert pickup.status is EvaluationStatus.INSUFFICIENT_DATA
    assert pickup.reason_codes == (ReasonCode.PICKUP_PRIOR_OBSERVATION_MISSING,)
    assert facts_of(pickup).prior_snapshot_id is None


def test_a_curve_endpoint_from_a_day_with_nothing_new_is_no_pair(hotel: Hotel) -> None:
    """The seven-days-earlier end of each historical pair: without it no pair, so not enough."""
    stay = slow_stay()
    seed_slow_night(hotel, repeated=curve_prior_days_keeping_anchors(stay))

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    hotel.refresh()

    assert pickup_of(hotel, stay).reason_codes == (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,)


@pytest.fixture
def scenario(db_session: Session, factory: BookingFactory) -> Scenario:
    return Scenario.create(db_session, factory)


def _baseline_with(scenario: Scenario, days: list[date]) -> Any:
    """`days`: the historical nights whose observation counts, of those added to the scenario."""
    target = scenario.session.get(BookingSnapshot, scenario.target_id)
    assert target is not None
    lead = (target.stay_date - target.snapshot_local_date).days
    scenario.service().calculate_for_snapshot_date(
        property_id=scenario.tenant.property.id,
        data_source_id=scenario.tenant.data_source.id,
        snapshot_local_date=target.snapshot_local_date,
        stay_date_start=target.stay_date,
        stay_date_end=target.stay_date,
        history=ObservationHistory(
            target.snapshot_local_date, {night - timedelta(days=lead): 1 for night in days}
        ),
    )
    return scenario.baseline()


def test_expected_takes_no_comparable_from_a_day_with_nothing_new(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:8], rooms=[20, 20, 20, 20, 20, 20, 0, 0])

    # the two that read 0 are days with nothing new: a false zero, and they are not samples
    baseline = _baseline_with(scenario, list(ELIGIBLE[:6]))

    assert baseline.sample_size == 6
    assert baseline.expected_rooms_on_books == 20


def test_expected_with_every_day_valid_is_what_it_always_was(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:8], rooms=[20, 20, 20, 20, 20, 20, 0, 0])

    baseline = _baseline_with(scenario, list(ELIGIBLE[:8]))

    assert baseline.sample_size == 8


def test_too_few_days_with_new_data_leave_expected_insufficient(scenario: Scenario) -> None:
    scenario.add_history(ELIGIBLE[:5])

    baseline = _baseline_with(scenario, list(ELIGIBLE[1:5]))

    assert baseline.expected_rooms_on_books is None


# --- the rule itself --------------------------------------------------------------------------


def _run_on(
    session: Session,
    tenant: Tenant,
    day: date,
    job: ImportJob | None,
    *,
    source_id: uuid.UUID | None = None,
    evaluated: int = 0,
) -> None:
    provenance = RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=source_id or tenant.data_source.id,
            import_job_id=None if job is None else job.id,
            last_successful_import_finished_at=None if job is None else job.finished_at,
            snapshot_local_date=day,
            observation_revision=evaluated + 1,
        )
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, day)
    sync_run(session, tenant.context, context, [], provenance=provenance)


TODAY = date(2026, 11, 9)
DAY_1, DAY_2, DAY_3, DAY_4 = (TODAY - timedelta(days=n) for n in (4, 3, 2, 1))


def _read(
    session: Session, tenant: Tenant, seen: ImportJob | None, *, day: date = TODAY
) -> BookingObservationFreshness:
    return booking_observation_freshness(
        session,
        tenant.context,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        as_of_local_date=day,
        import_job_id=None if seen is None else seen.id,
    )


def test_the_first_day_ever_analysed_is_new(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    job = import_at(factory, tenant.data_source, utc(2026, 11, 9, 8))

    freshness = _read(db_session, tenant, job)

    assert freshness.fresh is True
    assert samples(freshness) == frozenset()


def test_a_day_is_new_only_if_it_saw_another_import_than_the_day_before(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = import_at(factory, tenant.data_source, utc(2026, 11, 5, 8))
    second = import_at(factory, tenant.data_source, utc(2026, 11, 7, 8))
    _run_on(db_session, tenant, DAY_1, first)
    _run_on(db_session, tenant, DAY_2, first)  # nothing new
    _run_on(db_session, tenant, DAY_3, second)  # new
    _run_on(db_session, tenant, DAY_4, second)  # nothing new

    freshness = _read(db_session, tenant, second)

    assert samples(freshness) == {DAY_1, DAY_3}
    assert freshness.fresh is False
    assert _read(db_session, tenant, first).fresh is True  # what is not what the day before saw


def test_a_days_last_run_is_what_that_day_saw(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    first = import_at(factory, tenant.data_source, utc(2026, 11, 5, 8))
    second = import_at(factory, tenant.data_source, utc(2026, 11, 6, 14))
    _run_on(db_session, tenant, DAY_1, first)
    _run_on(db_session, tenant, DAY_2, first)  # the morning: nothing new
    _run_on(db_session, tenant, DAY_2, second, evaluated=1)  # the afternoon: a file

    freshness = _read(db_session, tenant, second)

    assert freshness.history.newest_revision == {DAY_1: 1, DAY_2: 2}


def test_the_days_own_earlier_runs_do_not_count_against_it(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = import_at(factory, tenant.data_source, utc(2026, 11, 5, 8))
    second = import_at(factory, tenant.data_source, utc(2026, 11, 9, 8))
    _run_on(db_session, tenant, DAY_1, first)
    _run_on(db_session, tenant, TODAY, second)  # this morning's run, with today's file

    assert _read(db_session, tenant, second).fresh is True  # a second look today is still today's


def test_a_day_that_says_nothing_is_no_sample_and_blocks_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    job = import_at(factory, tenant.data_source, utc(2026, 11, 5, 8))
    context = PriorityContext(tenant.workspace.id, tenant.property.id, DAY_1)
    sync_run(db_session, tenant.context, context, [])  # from before provenance existed
    _run_on(db_session, tenant, DAY_2, None)  # a source with no import yet

    freshness = _read(db_session, tenant, job)

    assert freshness.fresh is True
    assert samples(freshness) == frozenset()
    assert _read(db_session, tenant, None).fresh is True


def test_what_was_seen_of_another_source_says_nothing_of_this_one(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    other = factory.data_source(tenant.property)
    job = import_at(factory, tenant.data_source, utc(2026, 11, 5, 8))
    other_job = import_at(factory, other, utc(2026, 11, 5, 9))
    _run_on(db_session, tenant, DAY_1, other_job, source_id=other.id)
    _run_on(db_session, tenant, DAY_2, other_job, source_id=other.id)

    freshness = _read(db_session, tenant, job)

    assert freshness.fresh is True
    assert samples(freshness) == frozenset()


def test_another_workspace_is_never_read(db_session: Session, factory: BookingFactory) -> None:
    mine, theirs = factory.tenant(), factory.tenant()
    job = import_at(factory, mine.data_source, utc(2026, 11, 5, 8))
    their_job = import_at(factory, theirs.data_source, utc(2026, 11, 5, 8))
    _run_on(db_session, theirs, DAY_1, their_job)
    _run_on(db_session, theirs, DAY_2, their_job)

    freshness = _read(db_session, mine, job)

    assert freshness.fresh is True
    assert samples(freshness) == frozenset()

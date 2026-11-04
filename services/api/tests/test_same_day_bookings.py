"""Several bookings files on one day: REAL commits, the shared orchestration, the real clock.

    first import -> analysis A -> the same data again: nothing moves
                               -> different data: the day's next revision -> analysis B, same day

Old evidence stays what it was and the run that read it keeps saying so. The other half of the
story, what a revised day means for the history of later days, is the anti-leakage block below.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_OID, uuid5

import pytest
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis import (
    AnalysisStatusService,
    AnalysisUpdateState,
    RefreshOutcomeKind,
    enqueue_refresh,
)
from app.modules.analysis.queue import latest_refresh
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.decisions.types import DecisionStatus, LifecycleTransition
from app.modules.ingestion.models import ImportJob, ImportJobStatus
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.decision_support import CLEAR, TRIGGERED, revenue_evaluation, sync_run
from tests.expected_support import (
    ELIGIBLE,
    LEAD,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    Scenario,
    add_snapshots,
    snapshot_row,
)
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel, purge
from tests.support import BookingFactory


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


def rows_of_today(hotel: Hotel, offset: int) -> list[BookingSnapshot]:
    """Every stored row of one stay night for today's snapshot day, oldest revision first."""
    with hotel.session() as session:
        return list(
            session.scalars(
                select(BookingSnapshot)
                .where(
                    BookingSnapshot.workspace_id == hotel.tenant.workspace_id,
                    BookingSnapshot.snapshot_local_date == local_today(),
                    BookingSnapshot.stay_date == local_today() + timedelta(days=offset),
                )
                .order_by(BookingSnapshot.revision)
            ).all()
        )


def provenance_of(run: DecisionRun) -> RunInputProvenance:
    assert run.input_provenance is not None
    return RunInputProvenance.from_json(run.input_provenance)


def count_snapshots(hotel: Hotel) -> int:
    with hotel.session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(BookingSnapshot)
                .where(BookingSnapshot.workspace_id == hotel.tenant.workspace_id)
            )
            or 0
        )


def latest_job(hotel: Hotel) -> ImportJob:
    with hotel.session() as session:
        job = session.scalar(
            select(ImportJob)
            .where(
                ImportJob.workspace_id == hotel.tenant.workspace_id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
            )
            .order_by(ImportJob.finished_at.desc())
            .limit(1)
        )
    assert job is not None
    return job


FIRST = [booking_row("A", 3), booking_row("B", 5)]


# --- identical data: nothing moves ---------------------------------------------------------------


def test_an_import_records_whether_it_changed_anything(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    assert latest_job(hotel).changed_data is True

    hotel.import_bookings("a-again.csv", FIRST)
    assert latest_job(hotel).changed_data is False


def test_the_same_data_again_is_no_revision_and_no_new_run(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    assert hotel.refresh().kind is RefreshOutcomeKind.RAN
    snapshots = count_snapshots(hotel)
    first_run = hotel.runs()[0]

    hotel.import_bookings("another-name.csv", FIRST)
    outcome = hotel.refresh()

    assert outcome.result.is_idempotent_replay is True
    assert outcome.result.decision_run_id == first_run.id
    assert count_snapshots(hotel) == snapshots
    assert len(hotel.runs()) == 1
    assert [row.revision for row in rows_of_today(hotel, 3)] == [1]


def test_the_same_data_in_another_order_is_still_the_same_data(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()

    hotel.import_bookings("reordered.csv", list(reversed(FIRST)))

    assert latest_job(hotel).changed_data is False
    assert len(hotel.runs()) == 1


def test_the_same_data_again_does_not_say_new_data(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE
    before = hotel.status()

    hotel.import_bookings("a-again.csv", FIRST)

    after = hotel.status()
    assert after.state is AnalysisUpdateState.UP_TO_DATE
    assert after.latest_import_at == before.latest_import_at  # history, not news
    assert after.can_retry is False


# --- changed data: a new observation, a new analysis, the same day -------------------------------


def test_a_changed_file_is_analysed_the_same_day_on_a_new_revision(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    run_a = hotel.refresh().result
    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE

    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
    assert hotel.status().state is AnalysisUpdateState.NEW_DATA

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN
    assert outcome.result.is_idempotent_replay is False
    assert outcome.result.decision_run_id != run_a.decision_run_id
    assert outcome.result.as_of_local_date == run_a.as_of_local_date == local_today()
    assert outcome.result.snapshots_created == 1  # only the night that changed
    assert [row.rooms_on_books for row in rows_of_today(hotel, 3)] == [1, 2]
    assert [row.rooms_on_books for row in rows_of_today(hotel, 5)] == [1]


def test_the_old_observation_is_not_touched_and_cannot_be(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    [before] = rows_of_today(hotel, 3)

    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
    hotel.refresh()

    older, newer = rows_of_today(hotel, 3)
    assert older.id == before.id
    assert older.revision == 1
    assert older.rooms_on_books == before.rooms_on_books
    assert older.content_fingerprint == before.content_fingerprint
    assert older.as_of_at == before.as_of_at
    assert newer.as_of_at > older.as_of_at
    with hotel.session() as session, pytest.raises(DBAPIError):
        session.execute(
            text("UPDATE booking_snapshots SET rooms_on_books = 99 WHERE id = :id"),
            {"id": older.id},
        )


def test_each_run_keeps_saying_what_it_read(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    job_a = latest_job(hotel).id
    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
    hotel.refresh()
    job_b = latest_job(hotel).id

    run_a, run_b = hotel.runs()
    a, b = provenance_of(run_a), provenance_of(run_b)

    assert a.bookings.import_job_id == job_a
    assert a.bookings.observation_revision == 1
    assert b.bookings.import_job_id == job_b
    assert b.bookings.observation_revision == 2
    assert a.bookings.snapshot_local_date == b.bookings.snapshot_local_date == local_today()
    assert a.bookings.data_source_id == b.bookings.data_source_id
    first_at = a.bookings.last_successful_import_finished_at
    second_at = b.bookings.last_successful_import_finished_at
    assert first_at is not None and second_at is not None
    assert first_at < second_at


def test_the_input_of_the_older_run_can_be_read_back_as_it_was(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
    hotel.refresh()
    night = local_today() + timedelta(days=3)

    with hotel.session() as session:
        repository = BookingSnapshotRepository(session, hotel.tenant)
        source = hotel.bookings_source()
        as_it_was = repository.list_for_snapshot_date(
            source, local_today(), stay_date_from=night, stay_date_to=night, as_of_revision=1
        )
        as_it_is = repository.list_for_snapshot_date(
            source, local_today(), stay_date_from=night, stay_date_to=night
        )

    assert [(row.revision, row.rooms_on_books) for row in as_it_was] == [(1, 1)]
    assert [(row.revision, row.rooms_on_books) for row in as_it_is] == [(2, 2)]


def test_the_feed_reads_the_newest_run_of_the_day(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
    newest = hotel.refresh().result.decision_run_id

    with hotel.session() as session:
        feed = DecisionMemoryService(session, hotel.tenant).get_feed(
            hotel.property_id, local_today()
        )

    assert feed.run is not None
    assert feed.run.id == newest


def _cancelled(code: str, offset: int) -> dict[str, Any]:
    return {**booking_row(code, offset), "status": "cancelled"}


CHANGES = {
    "a new booking": [*FIRST, booking_row("C", 3)],
    "a cancellation": [_cancelled("A", 3), booking_row("B", 5)],
    "an amount": [booking_row("A", 3, revenue="175.00"), booking_row("B", 5)],
    "the dates": [booking_row("A", 4), booking_row("B", 5)],
    "the rooms": [{**booking_row("A", 3), "rooms": "2"}, booking_row("B", 5)],
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_every_real_change_of_what_is_on_the_books_is_a_new_revision_and_run(
    hotel: Hotel, change: str
) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()

    hotel.import_bookings("b.csv", CHANGES[change])
    assert latest_job(hotel).changed_data is True
    outcome = hotel.refresh()

    assert outcome.result.is_idempotent_replay is False
    assert outcome.result.snapshots_created >= 1
    assert provenance_of(hotel.runs()[-1]).bookings.observation_revision == 2


def test_a_channel_change_is_a_new_run_on_the_same_observation(hotel: Hotel) -> None:
    """A snapshot holds no channel: the night reads the same, and no revision is invented for it.
    The bookings did change, and OTA reads the bookings: so the day is analysed again."""
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    snapshots = count_snapshots(hotel)

    hotel.import_bookings(
        "b.csv", [{**booking_row("A", 3), "channel": "Expedia"}, booking_row("B", 5)]
    )
    assert latest_job(hotel).changed_data is True
    outcome = hotel.refresh()

    assert outcome.result.is_idempotent_replay is False
    assert count_snapshots(hotel) == snapshots
    a, b = (provenance_of(run) for run in hotel.runs())
    assert a.bookings.observation_revision == b.bookings.observation_revision == 1
    assert a.bookings.import_job_id != b.bookings.import_job_id


def test_three_files_in_a_day_are_three_revisions_and_the_last_counts(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3)])
    hotel.refresh()
    hotel.import_bookings("b.csv", [booking_row("A", 3), booking_row("B", 3)])
    hotel.refresh()
    hotel.import_bookings("c.csv", [booking_row("A", 3), booking_row("B", 3), booking_row("C", 3)])
    hotel.refresh()

    assert [(row.revision, row.rooms_on_books) for row in rows_of_today(hotel, 3)] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]
    with hotel.session() as session:
        current = BookingSnapshotRepository(session, hotel.tenant).get_for_stay_date(
            hotel.bookings_source(), local_today(), local_today() + timedelta(days=3)
        )
    assert current is not None and current.revision == 3


def test_going_back_to_the_first_file_is_a_change_too(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", [booking_row("A", 3, revenue="100.00")])
    hotel.refresh()
    hotel.import_bookings("b.csv", [booking_row("A", 3, revenue="200.00")])
    hotel.refresh()

    hotel.import_bookings("a-again.csv", [booking_row("A", 3, revenue="100.00")])
    hotel.refresh()

    assert [row.revision for row in rows_of_today(hotel, 3)] == [1, 2, 3]
    assert len(hotel.runs()) == 3


def test_revisions_of_one_hotel_never_touch_another(
    hotel: Hotel, db_engine: Engine, tmp_path: Any
) -> None:
    other = make_hotel(db_engine, tmp_path, name="Hotel Altro")
    try:
        other.import_bookings("x.csv", [booking_row("X", 3)])
        other.refresh()
        hotel.import_bookings("a.csv", FIRST)
        hotel.refresh()
        hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])
        hotel.refresh()

        assert len(other.runs()) == 1
        assert [row.revision for row in rows_of_today(other, 3)] == [1]
        with other.session() as session:
            foreign = BookingSnapshotRepository(session, other.tenant).get_for_stay_date(
                hotel.bookings_source(), local_today(), local_today() + timedelta(days=3)
            )
        assert foreign is None
    finally:
        purge(db_engine, other.tenant.workspace_id)


def test_a_job_told_to_wait_does_not_hold_back_a_request_for_now(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    waiting = hotel.enqueue(scheduled_at=datetime.now(UTC) + timedelta(days=1))
    assert hotel.status().state is AnalysisUpdateState.DEFERRED

    assert hotel.enqueue() == waiting

    assert hotel.status().state is AnalysisUpdateState.IN_PROGRESS


# --- Decision Memory: a signal is not a decision -------------------------------------------------


class Memory:
    """The lifecycle over two runs of ONE day: only the observation behind the signal changes."""

    STAY = date(2026, 8, 15)
    DAY = date(2026, 8, 1)

    def __init__(self, session: Session, factory: BookingFactory) -> None:
        self.session = session
        self.tenant = factory.tenant()
        self.context = TenantContext(self.tenant.workspace.id)
        self.as_of = PriorityContext(
            workspace_id=self.tenant.workspace.id,
            property_id=self.tenant.property.id,
            as_of_local_date=self.DAY,
        )

    def run(self, status: Any, seed: str) -> Any:
        evaluation = revenue_evaluation(
            workspace_id=self.tenant.workspace.id,
            property_id=self.tenant.property.id,
            data_source_id=self.tenant.data_source.id,
            stay_date=self.STAY,
            snapshot_local_date=self.DAY,
            status=status,
            fingerprint=seed * 64,
            target_snapshot_id=uuid5(NAMESPACE_OID, seed),
        )
        return sync_run(self.session, self.context, self.as_of, [evaluation]).result

    def decisions(self) -> list[Decision]:
        return list(
            self.session.scalars(
                select(Decision).where(Decision.workspace_id == self.tenant.workspace.id)
            ).all()
        )

    def transitions(self) -> list[LifecycleTransition]:
        return list(
            self.session.scalars(
                select(DecisionObservation.lifecycle_transition)
                .join(DecisionRun, DecisionObservation.decision_run_id == DecisionRun.id)
                .where(DecisionObservation.workspace_id == self.tenant.workspace.id)
                .order_by(DecisionRun.run_sequence)
            ).all()
        )


@pytest.fixture
def memory(db_session: Session, factory: BookingFactory) -> Memory:
    return Memory(db_session, factory)


def test_the_same_problem_seen_again_the_same_day_is_the_same_decision(memory: Memory) -> None:
    first = memory.run(TRIGGERED, "a")
    second = memory.run(TRIGGERED, "b")

    assert first.created_decision_count == 1
    assert second.created_decision_count == 0
    assert second.observed_open_count == 1
    [decision] = memory.decisions()
    assert decision.status == DecisionStatus.OPEN
    assert decision.episode_count == 1
    assert memory.transitions() == [LifecycleTransition.OPENED, LifecycleTransition.OBSERVED]


def test_a_new_revision_that_clears_the_problem_resolves_it_the_same_day(memory: Memory) -> None:
    memory.run(TRIGGERED, "a")

    second = memory.run(CLEAR, "b")

    assert second.resolved_count == 1
    [decision] = memory.decisions()
    assert decision.status == DecisionStatus.RESOLVED
    assert decision.resolved_local_date == Memory.DAY


def test_a_problem_that_comes_back_the_same_day_reopens_the_same_decision(memory: Memory) -> None:
    memory.run(TRIGGERED, "a")
    memory.run(CLEAR, "b")

    third = memory.run(TRIGGERED, "c")

    assert third.reopened_count == 1
    [decision] = memory.decisions()
    assert decision.status == DecisionStatus.OPEN
    assert decision.episode_count == 2
    assert decision.resolved_local_date is None


def test_the_same_evaluation_again_is_a_replay_and_observes_nothing(memory: Memory) -> None:
    first = memory.run(TRIGGERED, "a")

    replay = memory.run(TRIGGERED, "a")

    assert replay.is_idempotent_replay is True
    assert replay.decision_run_id == first.decision_run_id
    assert memory.transitions() == [LifecycleTransition.OPENED]


# --- Expected: a day seen three times is still one sample -----------------------------------------


def _revise(scenario: Scenario, stay: date, *, revision: int, rooms: int) -> Any:
    """Another observation of a stay already in the history, on the same snapshot day."""
    row = snapshot_row(scenario.tenant, stay - timedelta(days=LEAD), stay, rooms=rooms)
    row["revision"] = revision
    add_snapshots(scenario.session, scenario.tenant, [row])
    return row["id"]


@pytest.fixture
def scenario(db_session: Session, factory: BookingFactory) -> Scenario:
    return Scenario.create(db_session, factory)


def _comparables(scenario: Scenario) -> dict[Any, int]:
    baseline = scenario.baseline()
    return {
        comparable.snapshot_id: comparable.rooms_on_books
        for comparable in ExpectedRepository(
            scenario.session, scenario.tenant.context
        ).list_comparables(baseline.id)
    }


def test_a_past_day_seen_several_times_is_one_sample_read_from_its_last_revision(
    scenario: Scenario,
) -> None:
    stays = list(ELIGIBLE[:6])
    scenario.add_history(stays, rooms=10)
    revised = stays[0]
    last = _revise(scenario, revised, revision=2, rooms=14)
    final = _revise(scenario, revised, revision=3, rooms=18)

    result = scenario.calculate()

    assert (result.ready, result.insufficient) == (1, 0)
    assert scenario.baseline().sample_size == 6  # six days, not eight rows
    used = _comparables(scenario)
    assert final in used and used[final] == 18
    assert last not in used
    assert scenario.history[revised] not in used


def test_the_expected_result_is_what_the_last_revision_of_each_day_says(
    scenario: Scenario,
) -> None:
    stays = list(ELIGIBLE[:6])
    scenario.add_history(stays, rooms=10)
    for stay in stays:
        _revise(scenario, stay, revision=2, rooms=20)

    scenario.calculate()

    assert scenario.baseline().expected_rooms_on_books == 20
    assert set(_comparables(scenario).values()) == {20}


def test_too_few_days_stay_too_few_however_many_revisions_they_have(scenario: Scenario) -> None:
    stays = list(ELIGIBLE[:4])
    scenario.add_history(stays, rooms=10)
    for stay in stays:
        _revise(scenario, stay, revision=2, rooms=11)
        _revise(scenario, stay, revision=3, rooms=12)

    result = scenario.calculate()

    assert (result.ready, result.insufficient) == (0, 1)
    assert scenario.baseline().sample_size == 4  # twelve rows are still four days


def test_a_target_never_compares_with_another_observation_of_its_own_day(
    scenario: Scenario,
) -> None:
    """Comparables come from strictly earlier snapshot days: the morning's look at a night cannot
    teach the afternoon's look at the same night, nor at any other night of that day."""
    scenario.add_history(list(ELIGIBLE[:5]), rooms=10)
    afternoon = snapshot_row(scenario.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, rooms=30)
    afternoon["revision"] = 2
    add_snapshots(scenario.session, scenario.tenant, [afternoon])
    other_night = snapshot_row(
        scenario.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY - timedelta(days=7), rooms=99
    )
    add_snapshots(scenario.session, scenario.tenant, [other_night])

    scenario.calculate(afternoon["id"])

    baseline = scenario.baseline(afternoon["id"])
    used = {
        comparable.snapshot_id
        for comparable in ExpectedRepository(
            scenario.session, scenario.tenant.context
        ).list_comparables(baseline.id)
    }
    assert scenario.target_id not in used
    assert other_night["id"] not in used
    assert baseline.expected_rooms_on_books == 10


def test_a_target_revised_later_has_its_own_baseline_and_the_old_one_stays(
    scenario: Scenario,
) -> None:
    scenario.add_history(list(ELIGIBLE[:6]), rooms=10)
    scenario.calculate()
    morning = scenario.baseline()
    morning_id = morning.id
    afternoon = snapshot_row(scenario.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, rooms=30)
    afternoon["revision"] = 2
    add_snapshots(scenario.session, scenario.tenant, [afternoon])

    scenario.calculate(afternoon["id"])

    assert scenario.baseline(afternoon["id"]).id != morning_id
    assert scenario.baseline().id == morning_id  # it still stands, for the run that read it
    assert (
        scenario.session.scalar(
            select(func.count())
            .select_from(BookingExpectedBaseline)
            .where(BookingExpectedBaseline.workspace_id == scenario.tenant.workspace.id)
        )
        == 2
    )


def test_a_repeat_on_an_unchanged_target_keeps_its_baseline(scenario: Scenario) -> None:
    scenario.add_history(list(ELIGIBLE[:6]), rooms=10)
    scenario.calculate()

    again = scenario.calculate()

    assert (again.created, again.unchanged) == (0, 1)


# --- the repository never hands out two rows for one night of one day ----------------------------


def test_every_read_by_day_or_key_gives_one_row_per_night_the_newest(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    day, stay = date(2026, 8, 1), date(2026, 8, 15)
    rows = [snapshot_row(tenant, day, stay, rooms=rooms) for rooms in (10, 11, 12)]
    for revision, row in enumerate(rows, start=1):
        row["revision"] = revision
    add_snapshots(db_session, tenant, rows)
    db_session.flush()
    repository = BookingSnapshotRepository(db_session, tenant.context)
    source = tenant.data_source.id

    assert repository.get_for_stay_date(source, day, stay).rooms_on_books == 12  # type: ignore[union-attr]
    assert [row.rooms_on_books for row in repository.list_for_snapshot_date(source, day)] == [12]
    assert [row.rooms_on_books for row in repository.list_by_keys(source, {(day, stay)})] == [12]
    assert [
        point.rooms_on_books for point in repository.list_curve_for_stay_date(source, stay)
    ] == [12]
    assert len(repository.existing_in_range(source, day, day, stay, stay)) == 1
    assert repository.latest_revision(source, day) == 3
    assert repository.latest_revision(source, day + timedelta(days=1)) == 0
    # an older one is still reachable by the id a run or a baseline names
    older = repository.get_by_id(rows[0]["id"])
    assert older is not None and older.rooms_on_books == 10
    assert [row.rooms_on_books for row in repository.list_by_ids(source, {rows[0]["id"]})] == [10]


def test_the_database_refuses_a_reconstruction_with_a_revision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    row = snapshot_row(
        tenant,
        date(2026, 8, 1),
        date(2026, 8, 15),
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
    )
    row["revision"] = 2
    with pytest.raises(DBAPIError, match="only_an_observation_is_revised"):
        add_snapshots(db_session, tenant, [row])
    db_session.rollback()


# --- what the import route and the queue do -------------------------------------------------------


def test_an_analysis_that_did_not_see_the_latest_change_is_not_up_to_date(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    hotel.import_bookings("b.csv", [*FIRST, booking_row("C", 3)])

    with hotel.session() as session:
        status = AnalysisStatusService(session, hotel.tenant).status(hotel.property_id)
        job = latest_refresh(session, hotel.tenant, hotel.property_id)

    assert job is None  # the CLI import queues nothing: the route is what asks for a refresh
    assert status.state is AnalysisUpdateState.NEW_DATA
    assert status.can_retry is True


def test_recovery_after_identical_data_asks_for_nothing(hotel: Hotel) -> None:
    hotel.import_bookings("a.csv", FIRST)
    hotel.refresh()
    hotel.import_bookings("a-again.csv", FIRST)

    with hotel.session() as session:
        status = AnalysisStatusService(session, hotel.tenant).retry(hotel.property_id)
        job = latest_refresh(session, hotel.tenant, hotel.property_id)

    assert status.state is AnalysisUpdateState.UP_TO_DATE
    assert job is None


def test_the_enqueue_helper_still_answers_none_when_a_job_is_waiting_to_run(hotel: Hotel) -> None:
    with hotel.session() as session:
        assert enqueue_refresh(session, hotel.tenant, hotel.property_id) is not None
        assert enqueue_refresh(session, hotel.tenant, hotel.property_id) is None
        session.execute(
            delete(ImportJob).where(ImportJob.workspace_id == hotel.tenant.workspace_id)
        )
        session.commit()

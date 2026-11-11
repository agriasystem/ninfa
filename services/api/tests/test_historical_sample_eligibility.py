"""A run that did not finish is not history.

Observation, baselines and the final sync are separate commits, so a job can die between them and
leave rows that look like any other. Real hotel, real engines, real commits, and a real failure of
the real sync: what is pinned is that those rows are not a sample of anything until a finished run
reads them, that a retry makes one sample and not two, and that Expected, the comparables and the
curves all go by the same rule.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from procrastinate import testing
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.modules.analysis import enroll_ready_properties
from app.modules.analysis.observation import (
    BookingObservationFreshness,
    booking_observation_freshness,
    historical_sample_is_eligible,
)
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.decisions.service import DecisionService
from app.modules.ingestion.models import ImportJob, ImportJobStatus
from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    ReasonCode,
    RevenueSignals,
)
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import (
    BookingSnapshotRepository,
    ObservationHistory,
    SnapshotHistoryRow,
)
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
from worker import daily, runtime
from worker.app import DEFAULT_QUEUE, app

SOURCE = uuid4()
DAY = date(2026, 11, 3)


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Path) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


class SyncDiedError(RuntimeError):
    pass


@pytest.fixture
def dying_sync(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The job dies after the observation and the baselines, before the run is stored."""

    def die(*_args: object, **_kwargs: object) -> None:
        raise SyncDiedError

    def install() -> None:
        monkeypatch.setattr(DecisionService, "sync", die)

    return install


def tomorrow() -> date:
    return local_today() + timedelta(days=1)


def latest_import_id(hotel: Hotel) -> UUID:
    with hotel.session() as session:
        job = session.scalar(
            select(ImportJob.id)
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


def freshness_on(hotel: Hotel, day: date) -> BookingObservationFreshness:
    with hotel.session() as session:
        return booking_observation_freshness(
            session,
            hotel.tenant,
            property_id=hotel.property_id,
            data_source_id=hotel.bookings_source(),
            as_of_local_date=day,
            import_job_id=latest_import_id(hotel),
        )


def signals_of(hotel: Hotel, stay: date) -> RevenueSignals:
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


def rows_today(hotel: Hotel) -> list[tuple[Any, ...]]:
    with hotel.session() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    BookingSnapshot.id,
                    BookingSnapshot.stay_date,
                    BookingSnapshot.revision,
                    BookingSnapshot.rooms_on_books,
                )
                .where(
                    BookingSnapshot.workspace_id == hotel.tenant.workspace_id,
                    BookingSnapshot.snapshot_local_date == local_today(),
                )
                .order_by(BookingSnapshot.stay_date, BookingSnapshot.revision)
            ).all()
        ]


def read_as_tomorrow(hotel: Hotel, stay: date) -> list[SnapshotHistoryRow]:
    """What the analysis of tomorrow would read of today's observation of that night."""
    with hotel.session() as session:
        return BookingSnapshotRepository(session, hotel.tenant).list_by_keys(
            hotel.bookings_source(),
            {(local_today(), stay)},
            history=freshness_on(hotel, tomorrow()).history,
        )


def baseline_of_slow_night(hotel: Hotel, stay: date) -> tuple[Any, list[date]]:
    """The night's baseline, and the snapshot days of its comparables."""
    with hotel.session() as session:
        baseline = session.scalar(
            select(BookingExpectedBaseline)
            .join(BookingSnapshot, BookingSnapshot.id == BookingExpectedBaseline.target_snapshot_id)
            .where(
                BookingSnapshot.workspace_id == hotel.tenant.workspace_id,
                BookingSnapshot.snapshot_local_date == local_today(),
                BookingSnapshot.stay_date == stay,
            )
        )
        assert baseline is not None
        days = session.scalars(
            select(BookingSnapshot.snapshot_local_date)
            .join(
                BookingExpectedComparable,
                BookingExpectedComparable.snapshot_id == BookingSnapshot.id,
            )
            .where(BookingExpectedComparable.baseline_id == baseline.id)
        ).all()
    return baseline, list(days)


# --- a job that dies after its observation ----------------------------------------------------


def test_a_job_that_dies_after_its_observation_leaves_rows_and_no_sample(
    hotel: Hotel, dying_sync: Any
) -> None:
    hotel.import_bookings("oggi.csv", rooms_on(10, 2))
    dying_sync()

    with pytest.raises(SyncDiedError):
        hotel.refresh()

    assert rows_today(hotel) != []  # the observation is there: it looks like any other
    assert hotel.runs() == []
    assert local_today() not in freshness_on(hotel, tomorrow()).history.newest_revision
    assert read_as_tomorrow(hotel, local_today() + timedelta(days=10)) == []


def test_a_failed_day_does_not_count_as_a_day_analysed(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yesterday's analysis saw an old file; today's died on a new one. Tomorrow, what arrived today
    has still never been read: it is new, not a repetition of a day that left nothing."""
    hotel.import_bookings("ieri.csv", rooms_on(10, 2))
    analysed_on(hotel, local_today() - timedelta(days=1), import_job_id=latest_import_id(hotel))
    hotel.import_bookings("oggi.csv", rooms_on(10, 3))
    dying_sync()
    with pytest.raises(SyncDiedError):
        hotel.refresh()
    monkeypatch.undo()

    assert freshness_on(hotel, tomorrow()).fresh is True


# --- the retry --------------------------------------------------------------------------------


def test_a_retry_that_finishes_makes_one_sample_of_the_same_rows(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotel.import_bookings("oggi.csv", rooms_on(10, 2))
    stay = local_today() + timedelta(days=10)
    dying_sync()
    with pytest.raises(SyncDiedError):
        hotel.refresh()
    rows_after_failure = rows_today(hotel)
    baseline_after_failure, _ = baseline_of_slow_night(hotel, stay)
    assert read_as_tomorrow(hotel, stay) == []  # before it finishes: nothing

    monkeypatch.undo()
    result = hotel.refresh().result

    assert result is not None and result.is_idempotent_replay is False
    assert len(hotel.runs()) == 1
    assert rows_today(hotel) == rows_after_failure  # nothing written twice
    baseline, _ = baseline_of_slow_night(hotel, stay)
    assert baseline.id == baseline_after_failure.id
    assert freshness_on(hotel, tomorrow()).history.newest_revision == {local_today(): 1}
    [sample] = read_as_tomorrow(hotel, stay)  # after: exactly one
    assert (sample.revision, sample.rooms_on_books) == (1, 2)


def test_a_second_retry_changes_nothing_more(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotel.import_bookings("oggi.csv", rooms_on(10, 2))
    dying_sync()
    with pytest.raises(SyncDiedError):
        hotel.refresh()
    monkeypatch.undo()
    first = hotel.refresh().result
    assert first is not None

    again = hotel.refresh().result

    assert again is not None and again.is_idempotent_replay is True
    assert again.decision_run_id == first.decision_run_id
    assert len(hotel.runs()) == 1


def test_on_the_workers_own_path_a_job_that_dies_is_retried_and_makes_one_sample(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch, db_engine: Engine
) -> None:
    """The real tick, the real job, the real failure of the real sync, and the next attempt."""
    stay = local_today() + timedelta(days=10)
    hotel.import_bookings("oggi.csv", rooms_on(10, 2))
    with Session(db_engine) as session:
        enroll_ready_properties(session)
    connector = testing.InMemoryConnector()
    today = local_today()
    at_ten = datetime(today.year, today.month, today.day, 10, 5, tzinfo=ZoneInfo("Europe/Rome"))

    async def tick_and_work() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await daily.run_daily_tick(test_app, max(at_ten.astimezone(UTC), datetime.now(UTC)))
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    dying_sync()
    runtime.run(tick_and_work())

    assert "failed" in {job["status"] for job in connector.jobs.values()}
    assert rows_today(hotel) != []  # the observation it left
    assert hotel.runs() == []
    assert read_as_tomorrow(hotel, stay) == []  # before the retry: no sample

    rows = rows_today(hotel)
    monkeypatch.undo()
    runtime.run(tick_and_work())

    assert len(hotel.runs()) == 1
    assert rows_today(hotel) == rows  # the same rows: nothing written twice
    assert freshness_on(hotel, tomorrow()).history.newest_revision == {local_today(): 1}
    assert len(read_as_tomorrow(hotel, stay)) == 1  # after it: one


# --- a later revision whose analysis failed ---------------------------------------------------


def test_a_revision_no_finished_run_read_is_not_read_and_the_day_is_what_was_read(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stay = local_today() + timedelta(days=10)
    hotel.import_bookings("mattina.csv", rooms_on(10, 2))
    assert hotel.refresh().result is not None  # finished: revision 1

    hotel.import_bookings("pomeriggio.csv", rooms_on(10, 5))
    dying_sync()
    with pytest.raises(SyncDiedError):
        hotel.refresh()

    assert [row[2:] for row in rows_today(hotel) if row[1] == stay] == [(1, 2), (2, 5)]
    assert freshness_on(hotel, tomorrow()).history.newest_revision == {local_today(): 1}
    [sample] = read_as_tomorrow(hotel, stay)
    assert (sample.revision, sample.rooms_on_books) == (1, 2)

    # the retry finishes it: now the day is that revision, and still one sample of the night
    monkeypatch.undo()
    assert hotel.refresh().result is not None
    assert freshness_on(hotel, tomorrow()).history.newest_revision == {local_today(): 2}
    [sample] = read_as_tomorrow(hotel, stay)
    assert (sample.revision, sample.rooms_on_books) == (2, 5)


# --- every reader goes by the same rule -------------------------------------------------------


def _anchors(nights: list[date]) -> set[date]:
    return {night - timedelta(days=10) for night in nights}


def test_a_failed_day_is_not_in_expected_and_not_among_the_comparables(hotel: Hotel) -> None:
    stay = slow_stay()
    nights = comparable_nights(stay)
    failed = _anchors(nights[:3])
    seed_slow_night(hotel, unfinished=failed)

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    baseline, days = baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.READY
    assert baseline.sample_size == 5  # of the eight
    assert baseline.observed_sample_size == 5
    assert set(days) == _anchors(nights[3:])
    assert not set(days) & failed


def test_too_many_failed_days_leave_expected_insufficient_and_nothing_is_said(hotel: Hotel) -> None:
    stay = slow_stay()
    seed_slow_night(hotel, unfinished=_anchors(comparable_nights(stay)[:4]))

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    baseline, days = baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA
    assert set(days) == _anchors(comparable_nights(stay)[4:])  # only what finished
    signals = signals_of(hotel, stay)
    assert signals.pickup_low.reason_codes == (ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,)
    assert signals.occupancy_risk.reason_codes == (ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,)
    assert pickup_decisions(hotel) == []


def test_a_failed_day_is_no_prior_of_the_pickup(hotel: Hotel) -> None:
    stay = seed_slow_night(hotel, unfinished={local_today() - timedelta(days=7)})

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    pickup = signals_of(hotel, stay).pickup_low
    assert pickup.status is EvaluationStatus.INSUFFICIENT_DATA
    assert pickup.reason_codes == (ReasonCode.PICKUP_PRIOR_OBSERVATION_MISSING,)
    assert pickup_decisions(hotel) == []


def test_failed_days_are_not_in_the_pickup_history(hotel: Hotel) -> None:
    """The seven-days-earlier end of each pair came from a run that failed: no pair, not enough. The
    occupancy risk, whose pairs do not touch those days, still speaks."""
    stay = slow_stay()
    seed_slow_night(hotel, unfinished=curve_prior_days_keeping_anchors(stay))

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    signals = signals_of(hotel, stay)
    assert signals.pickup_low.reason_codes == (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,)
    assert signals.occupancy_risk.status is EvaluationStatus.TRIGGERED


def test_failed_days_are_not_in_the_occupancy_history(hotel: Hotel) -> None:
    """The final of each pair came from a run that failed. The pickup still speaks."""
    stay = slow_stay()
    seed_slow_night(hotel, unfinished=set(comparable_nights(stay)))

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    signals = signals_of(hotel, stay)
    assert signals.occupancy_risk.reason_codes == (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,)
    assert signals.pickup_low.status is EvaluationStatus.TRIGGERED


def test_a_baseline_stored_before_a_day_stopped_counting_does_not_bring_it_back(
    hotel: Hotel,
) -> None:
    """A baseline names its comparables by id, a read the filter on the keys never sees. Only those
    days stop counting here: every other end of the pairs is still there, so without the check on
    the named rows the pairs would all stand."""
    stay = seed_slow_night(hotel)
    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None
    baseline, days = baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.READY
    counting = dict(freshness_on(hotel, local_today()).history.newest_revision)
    for day in days:
        del counting[day]
    with hotel.session() as session:
        [signals] = RevenueDecisionService(session, hotel.tenant).evaluate_snapshot_date(
            property_id=hotel.property_id,
            data_source_id=hotel.bookings_source(),
            snapshot_local_date=local_today(),
            stay_date_start=stay,
            stay_date_end=stay,
            history=ObservationHistory(local_today(), counting),
        )

    assert signals.occupancy_risk.reason_codes == (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,)


def test_with_no_history_named_an_engine_reads_what_is_stored(hotel: Hotel) -> None:
    """Their own tests and direct callers: only the orchestration has runs to judge by."""
    stay = seed_slow_night(hotel, analysed=False)
    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    with hotel.session() as session:
        repository = BookingSnapshotRepository(session, hotel.tenant)
        source = hotel.bookings_source()
        week_ago = local_today() - timedelta(days=7)
        assert len(repository.list_by_keys(source, {(week_ago, stay)})) == 1
        assert (
            repository.list_by_keys(
                source, {(week_ago, stay)}, history=ObservationHistory(local_today(), {})
            )
            == []
        )


def test_expected_is_stable_when_a_failed_job_is_retried_on_a_real_history(
    hotel: Hotel, dying_sync: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry computes the same baseline for the same target: never a conflict."""
    stay = seed_slow_night(hotel, unfinished=_anchors(comparable_nights(slow_stay())[:2]))
    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    dying_sync()
    with pytest.raises(SyncDiedError):
        hotel.refresh()
    before, days_before = baseline_of_slow_night(hotel, stay)

    monkeypatch.undo()
    assert hotel.refresh().result is not None

    after, days_after = baseline_of_slow_night(hotel, stay)
    assert after.id == before.id
    assert sorted(days_after) == sorted(days_before)
    with hotel.session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(BookingExpectedBaseline)
            .where(BookingExpectedBaseline.target_snapshot_id == after.target_snapshot_id)
        )
    assert count == 1


def test_after_the_failed_day_the_next_finished_day_reads_normally(hotel: Hotel) -> None:
    """A failed day takes itself out, and nothing else with it."""
    stay = slow_stay()
    nights = comparable_nights(stay)
    seed_slow_night(hotel, unfinished={nights[0] - timedelta(days=10)})

    hotel.import_bookings(
        "oggi.csv", [*rooms_on((stay - local_today()).days, 2), booking_row("X", 12)]
    )
    result = hotel.refresh().result

    assert result is not None and result.booking_observation_fresh is True
    signals = signals_of(hotel, stay)
    assert signals.pickup_low.status is EvaluationStatus.TRIGGERED
    assert signals.occupancy_risk.status is EvaluationStatus.TRIGGERED


# --- the rule ---------------------------------------------------------------------------------


def _run(provenance: dict[str, Any] | None, as_of: date = DAY) -> DecisionRun:
    return DecisionRun(as_of_local_date=as_of, input_provenance=provenance)


def _provenance(
    *,
    source: UUID = SOURCE,
    job: UUID | None = None,
    day: date | None = DAY,
    revision: int | None = 1,
) -> dict[str, Any]:
    import_job = job if job is not None else uuid4()
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=source,
            import_job_id=import_job,
            last_successful_import_finished_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
            snapshot_local_date=day,
            observation_revision=revision,
        )
    ).to_json()


def test_a_finished_run_that_says_what_it_read_is_eligible() -> None:
    assert historical_sample_is_eligible(_run(_provenance()), SOURCE) is True


def test_a_run_from_before_a_day_could_be_looked_at_twice_is_eligible() -> None:
    """It says the source and the import, and there was only one observation it could have read."""
    assert historical_sample_is_eligible(_run(_provenance(day=None, revision=None)), SOURCE) is True


@pytest.mark.parametrize(
    "run",
    [
        pytest.param(_run(None), id="no provenance recorded"),
        pytest.param(_run(_provenance(source=uuid4())), id="another source"),
        pytest.param(
            _run(_provenance(day=DAY - timedelta(days=1))), id="an observation of another day"
        ),
        pytest.param(_run({"version": 999, "bookings": {}}), id="a provenance not understood"),
        pytest.param(_run({"version": 1}), id="a provenance with no bookings"),
        pytest.param(
            _run(
                {
                    "version": 1,
                    "bookings": {
                        "data_source_id": str(SOURCE),
                        "last_successful_import_job_id": None,
                        "last_successful_import_finished_at": None,
                    },
                }
            ),
            id="no import known: its zeros are not a measure",
        ),
    ],
)
def test_a_run_that_does_not_say_enough_is_not_eligible(run: DecisionRun) -> None:
    assert historical_sample_is_eligible(run, SOURCE) is False


def _row(*, origin: SnapshotOrigin, day: date, revision: int) -> SnapshotHistoryRow:
    return SnapshotHistoryRow(uuid4(), day, day, origin, 1, 0, None, revision)


def test_the_filter_counts_revisions_and_days_and_admits_no_reconstruction() -> None:
    history = ObservationHistory(date(2026, 11, 9), {DAY: 2})
    observed = SnapshotOrigin.OBSERVED

    assert history.admits(_row(origin=observed, day=DAY, revision=1)) is True
    assert history.admits(_row(origin=observed, day=DAY, revision=2)) is True
    assert history.admits(_row(origin=observed, day=DAY, revision=3)) is False  # nobody read it
    assert history.admits(_row(origin=observed, day=date(2026, 11, 4), revision=1)) is False
    # readable is not eligible: a reconstruction is what is inferred today, never a sample
    # (test_reconstructed_is_not_observed.py pins it on the reads and on the real Expected)
    for day in (DAY, date(2026, 11, 4)):
        reconstructed = _row(origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE, day=day, revision=1)
        assert history.admits(reconstructed) is False
    # the day being read and after it are not history
    assert history.admits(_row(origin=observed, day=date(2026, 11, 9), revision=7)) is True

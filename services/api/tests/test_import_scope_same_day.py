"""A file that takes something away, on the day it arrives: REAL commits, the real engines.

    morning file -> analysis A -> a complete file without a booking: the day's next revision ->
    analysis B, the same day -> the booking back: the next one

A removal is just news about what is on the books. It goes down the path any change goes down, so
the same-day machinery, the run's provenance, the Expected history and Decision Memory need no
special case: these tests pin that they did not get one.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from app.modules.bookings.models import Booking
from app.modules.bookings.repository import BookingRepository
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.decisions.types import DecisionStatus
from app.modules.ingestion.models import FileScope, ImportJob, ImportJobStatus
from app.modules.snapshots.models import BookingSnapshot
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.refresh_support import (
    Hotel,
    booking_row,
    local_today,
    make_hotel,
    pickup_decisions,
    purge,
    rooms_on,
    seed_slow_night,
)

NIGHT = 3
ONE, TWO, THREE = (booking_row(code, NIGHT) for code in ("A", "B", "C"))


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


@pytest.fixture
def slow_night(hotel: Hotel) -> date:
    return seed_slow_night(hotel)


def _observations(hotel: Hotel, offset: int = NIGHT) -> list[tuple[int, int]]:
    """Every observation of one night today, oldest first: (revision, rooms on the books)."""
    with hotel.session() as session:
        return [
            (row.revision, row.rooms_on_books)
            for row in session.scalars(
                select(BookingSnapshot)
                .where(
                    BookingSnapshot.workspace_id == hotel.tenant.workspace_id,
                    BookingSnapshot.snapshot_local_date == local_today(),
                    BookingSnapshot.stay_date == local_today() + timedelta(days=offset),
                )
                .order_by(BookingSnapshot.revision)
            ).all()
        ]


def _provenance(run: DecisionRun) -> RunInputProvenance:
    assert run.input_provenance is not None
    return RunInputProvenance.from_json(run.input_provenance)


def _latest_job(hotel: Hotel) -> ImportJob:
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


def _current(hotel: Hotel) -> set[str]:
    with hotel.session() as session:
        return {
            booking.source_record_id
            for booking in BookingRepository(session, hotel.tenant).list_for_property(
                hotel.property_id
            )
        }


def _removal_of(hotel: Hotel, code: str) -> tuple[Any, Any, Any]:
    with hotel.session() as session:
        booking = session.scalar(
            select(Booking).where(
                Booking.workspace_id == hotel.tenant.workspace_id,
                Booking.source_record_id == code,
            )
        )
        assert booking is not None
        return (
            booking.removed_by_import_job_id,
            booking.removed_at,
            booking.last_seen_import_job_id,
        )


# --- same day ------------------------------------------------------------------------------------


def test_a_complete_file_is_the_next_revision_and_the_next_analysis_of_the_day(
    hotel: Hotel,
) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    morning = hotel.refresh().result
    assert _observations(hotel) == [(1, 3)]

    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    complete = _latest_job(hotel)
    afternoon = hotel.refresh().result

    assert complete.changed_data is True
    assert complete.file_scope is FileScope.FULL
    assert afternoon.decision_run_id != morning.decision_run_id
    assert _observations(hotel) == [(1, 3), (2, 2)]  # the first observation stays what it was
    assert _current(hotel) == {"A", "C"}
    first, second = hotel.runs()
    assert _provenance(first).bookings.observation_revision == 1
    assert _provenance(second).bookings.observation_revision == 2
    assert _provenance(second).bookings.import_job_id == complete.id


def test_a_booking_taken_away_says_which_import_did_it_and_which_last_held_it(hotel: Hotel) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    holding = _latest_job(hotel)

    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)

    removed_by, removed_at, last_seen = _removal_of(hotel, "B")
    assert removed_by == _latest_job(hotel).id
    assert removed_at is not None
    assert last_seen == holding.id


def test_the_same_complete_file_again_is_no_revision_and_no_run(hotel: Hotel) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    first = hotel.refresh().result
    runs = len(hotel.runs())

    hotel.import_bookings("completo-2.csv", [ONE, THREE], file_scope=FileScope.FULL)
    again = hotel.refresh().result

    assert _latest_job(hotel).changed_data is False
    assert again.is_idempotent_replay is True
    assert again.decision_run_id == first.decision_run_id
    assert len(hotel.runs()) == runs


@pytest.mark.parametrize("scope", [FileScope.PARTIAL, FileScope.DELTA])
def test_a_file_that_is_not_complete_changes_only_what_it_says(
    hotel: Hotel, scope: FileScope
) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    hotel.refresh()

    changed = {**ONE, "rooms": "2"}
    hotel.import_bookings("parte.csv", [changed], file_scope=scope)
    hotel.refresh()

    assert _current(hotel) == {"A", "B", "C"}
    assert _observations(hotel) == [(1, 3), (2, 4)]
    assert _removal_of(hotel, "B") == (None, None, None)


def test_a_new_booking_in_a_file_that_is_not_complete_adds_to_the_night(hotel: Hotel) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO])
    hotel.refresh()

    hotel.import_bookings("nuove.csv", [THREE], file_scope=FileScope.DELTA)
    hotel.refresh()

    assert _current(hotel) == {"A", "B", "C"}
    assert _observations(hotel) == [(1, 2), (2, 3)]


def test_a_booking_that_comes_back_is_counted_again_the_same_day(hotel: Hotel) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    hotel.refresh()
    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    hotel.refresh()

    hotel.import_bookings("sera.csv", [ONE, TWO, THREE], file_scope=FileScope.FULL)
    hotel.refresh()

    assert _observations(hotel) == [(1, 3), (2, 2), (3, 3)]
    assert _removal_of(hotel, "B") == (None, None, None)
    assert [_provenance(run).bookings.observation_revision for run in hotel.runs()] == [1, 2, 3]


def test_a_night_outside_the_file_keeps_its_observation(hotel: Hotel) -> None:
    far = booking_row("F", NIGHT + 10)
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE, far])
    hotel.refresh()

    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    hotel.refresh()

    assert "F" in _current(hotel)
    assert _observations(hotel, NIGHT + 10) == [(1, 1)]


def test_every_read_of_the_history_gives_the_last_word_of_the_day(hotel: Hotel) -> None:
    """The anti-leakage rule read once per day; a removal adds no sample, only a revision."""
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    hotel.refresh()
    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    hotel.refresh()

    stay = local_today() + timedelta(days=NIGHT)
    with hotel.session() as session:
        stored = BookingSnapshotRepository(session, hotel.tenant).get_for_stay_date(
            hotel.bookings_source(), local_today(), stay
        )
    assert stored is not None
    assert (stored.revision, stored.rooms_on_books) == (2, 2)


def test_a_removal_in_one_hotel_touches_nothing_in_another(
    hotel: Hotel, db_engine: Engine, tmp_path: Any
) -> None:
    other = make_hotel(db_engine, tmp_path, name="Hotel Altro")
    try:
        other.import_bookings("mattina.csv", [ONE, TWO, THREE])
        hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])

        hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)

        assert _current(hotel) == {"A", "C"}
        assert _current(other) == {"A", "B", "C"}
    finally:
        purge(db_engine, other.tenant.workspace_id)


# --- Decision Memory: the normal rule, nothing more ----------------------------------------------


def test_a_removal_with_no_signal_opens_no_decision(hotel: Hotel) -> None:
    hotel.import_bookings("mattina.csv", [ONE, TWO, THREE])
    morning = hotel.refresh().result

    hotel.import_bookings("completo.csv", [ONE, THREE], file_scope=FileScope.FULL)
    afternoon = hotel.refresh().result

    assert afternoon.decisions_created == morning.decisions_created == 0


def test_what_a_removal_really_changes_is_one_decision_through_the_day(
    hotel: Hotel, slow_night: date
) -> None:
    offset = (slow_night - local_today()).days

    # fourteen rooms: nothing to say about this night's pace
    hotel.import_bookings("mattina.csv", rooms_on(offset, 14))
    hotel.refresh()
    assert pickup_decisions(hotel) == []

    # the complete file holds two of them: the night is really behind, and the normal rule says so
    hotel.import_bookings("pomeriggio.csv", rooms_on(offset, 2), file_scope=FileScope.FULL)
    hotel.refresh()
    [(decision, status, episodes, resolved)] = pickup_decisions(hotel)
    assert (status, episodes, resolved) == (DecisionStatus.OPEN, 1, None)

    # they come back: the same Decision closes, the same day
    hotel.import_bookings("sera.csv", rooms_on(offset, 14), file_scope=FileScope.FULL)
    evening = hotel.refresh().result
    assert evening.decisions_created == 0
    assert evening.decisions_resolved >= 1
    assert pickup_decisions(hotel) == [(decision, DecisionStatus.RESOLVED, 1, local_today())]

    # and the same file again moves nothing
    runs = len(hotel.runs())
    hotel.import_bookings("sera-2.csv", rooms_on(offset, 14), file_scope=FileScope.FULL)
    assert hotel.refresh().result.is_idempotent_replay is True
    assert len(hotel.runs()) == runs

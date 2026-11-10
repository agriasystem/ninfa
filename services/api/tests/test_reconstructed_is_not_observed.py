"""RECONSTRUCTED IS NOT OBSERVED AS-OF: a night inferred today can be read, it is not a sample.

What the bookings imported today say about the 25th of October is not what NINFA knew on the 25th of
October. Those rows stay readable wherever a figure wants how a day ended (the cost per occupied
room), and are never a sample of the Expected value, the pickup or the curves. Real hotel, real
engines, real commits: what is pinned is the rule itself (a row and a read), what the real Expected
does with a thin observed history that a reconstruction could have completed, and that a really
observed night counts exactly as before.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import (
    BookingSnapshotRepository,
    ObservationHistory,
    SnapshotHistoryRow,
)
from tests.expected_support import add_snapshots, snapshot_row
from tests.refresh_support import (
    Hotel,
    comparable_nights,
    local_today,
    make_hotel,
    purge,
    rooms_on,
    seed_slow_night,
    slow_stay,
)

OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
DAY = date(2026, 11, 3)


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Path) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


def _row(origin: SnapshotOrigin, day: date, revision: int = 1) -> SnapshotHistoryRow:
    return SnapshotHistoryRow(uuid4(), day, day, origin, 1, 0, None, revision)


# --- the rule, on a row ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "is_a_sample"),
    [
        pytest.param(OBSERVED, True, id="an observation a finished analysis read"),
        pytest.param(RECONSTRUCTED, False, id="a reconstruction, never"),
    ],
)
def test_only_an_observation_that_counts_is_a_sample_of_history(
    origin: SnapshotOrigin, is_a_sample: bool
) -> None:
    history = ObservationHistory(date(2026, 11, 9), {DAY: 1})

    assert history.admits(_row(origin, DAY)) is is_a_sample


def test_a_reconstruction_is_no_sample_on_the_day_being_read_or_after_it_either() -> None:
    history = ObservationHistory(date(2026, 11, 9), {})

    assert history.admits(_row(OBSERVED, date(2026, 11, 9), revision=7)) is True
    assert history.admits(_row(RECONSTRUCTED, date(2026, 11, 9))) is False
    assert history.admits(_row(RECONSTRUCTED, date(2026, 11, 12))) is False


# --- the rule, on a read --------------------------------------------------------------------------


def _store(hotel: Hotel, rows: list[tuple[date, date, SnapshotOrigin, int]]) -> None:
    tenant = SimpleNamespace(
        workspace=SimpleNamespace(id=hotel.tenant.workspace_id),
        property=SimpleNamespace(id=hotel.property_id),
        data_source=SimpleNamespace(id=hotel.bookings_source()),
    )
    with hotel.session() as session:
        add_snapshots(
            session,
            tenant,  # type: ignore[arg-type]
            [
                snapshot_row(tenant, day, stay, rooms=rooms, origin=origin)  # type: ignore[arg-type]
                for day, stay, origin, rooms in rows
            ],
        )
        session.commit()


@pytest.mark.parametrize(
    ("origin", "read_as_history"),
    [(OBSERVED, 1), (RECONSTRUCTED, 0)],
    ids=["an observed night", "a reconstructed night"],
)
def test_a_reconstruction_is_readable_and_is_not_read_as_history(
    hotel: Hotel, origin: SnapshotOrigin, read_as_history: int
) -> None:
    night = local_today() - timedelta(days=20)
    key = (night - timedelta(days=10), night)
    _store(hotel, [(*key, origin, 7)])
    named = ObservationHistory(local_today(), {key[0]: 1})  # the day counts, the row still may not

    with hotel.session() as session:
        repository = BookingSnapshotRepository(session, hotel.tenant)
        source = hotel.bookings_source()
        readable = repository.list_by_keys(source, {key})
        as_history = repository.list_by_keys(source, {key}, history=named)

    assert [(row.origin, row.rooms_on_books) for row in readable] == [(origin, 7)]  # always read
    assert len(as_history) == read_as_history


# --- what the real Expected does with it ----------------------------------------------------------


def _baseline_of_slow_night(hotel: Hotel, stay: date) -> tuple[BookingExpectedBaseline, list[Any]]:
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
        named = session.execute(
            select(BookingSnapshot.stay_date, BookingSnapshot.origin)
            .join(
                BookingExpectedComparable,
                BookingExpectedComparable.snapshot_id == BookingSnapshot.id,
            )
            .where(BookingExpectedComparable.baseline_id == baseline.id)
        ).all()
    return baseline, [tuple(row) for row in named]


def _nights_beyond_the_eight(stay: date) -> list[date]:
    """Same-weekday nights the seed leaves alone: where a reconstruction would fill a sample."""
    return [night for night in eligible_stay_dates(stay) if night < local_today()][8:12]


def test_reconstructed_nights_do_not_complete_a_thin_observed_history(hotel: Hotel) -> None:
    """Three observed comparables and four reconstructed ones: under the old rule seven, a baseline
    that speaks. NINFA never knew those four on their day, so it has three, and says nothing."""
    stay = slow_stay()
    nights = comparable_nights(stay)
    anchors_lost = {night - timedelta(days=10) for night in nights[:5]}
    seed_slow_night(hotel, unfinished=anchors_lost)  # five of the eight were never finished
    reconstructed = _nights_beyond_the_eight(stay)
    assert len(reconstructed) == 4
    _store(
        hotel,
        [(night - timedelta(days=10), night, RECONSTRUCTED, 25) for night in reconstructed],
    )

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    baseline, named = _baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA
    assert (baseline.sample_size, baseline.observed_sample_size) == (3, 3)
    assert sorted(stay_date for stay_date, _ in named) == sorted(nights[5:])
    assert {origin for _, origin in named} == {OBSERVED}


def test_the_first_run_cannot_speak_from_a_history_that_is_only_reconstructed(
    hotel: Hotel,
) -> None:
    stay = seed_slow_night(hotel, origin=RECONSTRUCTED, analysed=False)

    hotel.import_bookings("primo.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    baseline, named = _baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.INSUFFICIENT_DATA
    assert baseline.sample_size == 0 and named == []
    with hotel.session() as session:  # and they are still there, to be read
        rows = BookingSnapshotRepository(session, hotel.tenant).list_by_keys(
            hotel.bookings_source(),
            {(night - timedelta(days=10), night) for night in comparable_nights(stay)},
        )
    assert {row.origin for row in rows} == {RECONSTRUCTED} and len(rows) == 8


def test_a_really_observed_history_still_counts_exactly_as_before(hotel: Hotel) -> None:
    stay = seed_slow_night(hotel)

    hotel.import_bookings("oggi.csv", rooms_on((stay - local_today()).days, 2))
    assert hotel.refresh().result is not None

    baseline, named = _baseline_of_slow_night(hotel, stay)
    assert baseline.status == ExpectedStatus.READY
    assert (baseline.sample_size, baseline.observed_sample_size) == (8, 8)
    assert {origin for _, origin in named} == {OBSERVED}

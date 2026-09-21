"""BookingSnapshotReconstructionService: what can be INFERRED today about earlier days.

A reconstruction is never an observation: every row is RECONSTRUCTED_APPROXIMATE (even with no
uncertainty at all), an existing observation always wins, and what cannot be known is counted
as uncertain instead of being guessed.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import BookingStatus
from app.modules.ingestion.models import DataSourceDomain
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.snapshot_support import World
from tests.support import BookingFactory

NOW = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)  # 11:00 in Rome, 15 March
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
STAY = date(2026, 4, 10)
ROME = ZoneInfo("Europe/Rome")


def march(day: int) -> date:
    return date(2026, 3, day)


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> World:
    return World.create(db_session, factory, NOW)


def stored(world: World, snapshot_date: date, stay_date: date = STAY) -> BookingSnapshot:
    row = world.stored(snapshot_date, stay_date)
    assert row is not None, (snapshot_date, stay_date)
    return row


def rooms_curve(world: World, first: int, last: int, stay_date: date = STAY) -> list[int]:
    return [stored(world, march(day), stay_date).rooms_on_books for day in range(first, last + 1)]


def uncertain_curve(world: World, first: int, last: int, stay_date: date = STAY) -> list[int]:
    return [stored(world, march(day), stay_date).uncertain_rooms for day in range(first, last + 1)]


def count_snapshots(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(BookingSnapshot)) or 0)


# --- origin: never OBSERVED, never exact ------------------------------------------------------


def test_every_reconstructed_row_is_approximate_even_with_no_uncertainty(world: World) -> None:
    world.book(STAY, STAY + timedelta(days=1))

    result = world.reconstruct(march(3), march(7), STAY, STAY)

    assert result.origin == RECONSTRUCTED and result.created == 5
    for day in range(3, 8):
        row = stored(world, march(day))
        assert row.origin == RECONSTRUCTED
        assert row.uncertain_rooms == 0  # nothing uncertain here, and still not "observed"


def test_a_row_per_snapshot_day_and_stay_night_even_with_no_booking_at_all(
    world: World, db_session: Session
) -> None:
    result = world.reconstruct(march(3), march(5), STAY, STAY + timedelta(days=3))

    assert result.created == 3 * 4 == count_snapshots(db_session)
    row = stored(world, march(4), STAY + timedelta(days=2))
    assert (row.booking_count_on_books, row.rooms_on_books) == (0, 0)
    assert row.allocated_room_revenue_on_books == Decimal("0.00") and row.adr_on_books is None


def test_as_of_at_of_a_reconstruction_is_the_exclusive_cutoff_of_its_day_in_utc(
    world: World,
) -> None:
    world.reconstruct(march(10), march(10), STAY, STAY)

    row = stored(world, march(10))

    assert row.as_of_at == datetime(2026, 3, 10, 23, 0, tzinfo=UTC)  # 00:00 of the 11th in Rome
    assert row.as_of_at == end_of_local_day(march(10), ROME)


# --- I. booked_at ------------------------------------------------------------------------------


def test_a_booking_made_after_the_cutoff_is_absent_and_one_made_before_is_present(
    world: World,
) -> None:
    world.book(STAY, STAY + timedelta(days=1), booked_at=datetime(2026, 3, 5, 10, 0, tzinfo=UTC))

    world.reconstruct(march(3), march(7), STAY, STAY)

    assert rooms_curve(world, 3, 7) == [0, 0, 1, 1, 1]


def test_the_local_day_decides_not_the_utc_day(world: World) -> None:
    """23:30 UTC on the 4th is 00:30 on the 5th in Rome: made on the 5th, not on the 4th."""
    world.book(
        STAY, STAY + timedelta(days=1), booked_at=datetime(2026, 3, 4, 23, 30, tzinfo=UTC), rooms=2
    )
    world.book(
        STAY, STAY + timedelta(days=1), booked_at=datetime(2026, 3, 4, 22, 30, tzinfo=UTC), rooms=5
    )  # 23:30 on the 4th in Rome

    world.reconstruct(march(3), march(6), STAY, STAY)

    assert rooms_curve(world, 3, 6) == [0, 5, 7, 7]


def test_a_booking_made_exactly_at_the_cutoff_belongs_to_the_next_day(world: World) -> None:
    world.book(STAY, STAY + timedelta(days=1), booked_at=end_of_local_day(march(5), ROME))

    world.reconstruct(march(4), march(7), STAY, STAY)

    assert rooms_curve(world, 4, 7) == [0, 0, 1, 1]


# --- I. cancellations --------------------------------------------------------------------------


def test_a_cancellation_before_the_cutoff_is_absent_and_after_the_cutoff_is_present(
    world: World,
) -> None:
    world.book(
        STAY,
        STAY + timedelta(days=1),
        status=BookingStatus.CANCELLED,
        booked_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        cancelled_at=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
    )

    world.reconstruct(march(3), march(7), STAY, STAY)

    # on the books at the end of the 3rd and 4th, cancelled during the 5th
    assert rooms_curve(world, 3, 7) == [1, 1, 0, 0, 0]
    assert uncertain_curve(world, 3, 7) == [0, 0, 0, 0, 0]  # the date is known: nothing uncertain


def test_a_cancelled_booking_without_a_date_is_uncertain_and_never_certain(world: World) -> None:
    world.book(
        STAY,
        STAY + timedelta(days=1),
        status=BookingStatus.CANCELLED,
        booked_at=datetime(2026, 3, 4, 9, 0, tzinfo=UTC),
        cancelled_at=None,
        rooms=2,
    )

    world.reconstruct(march(3), march(7), STAY, STAY)

    assert rooms_curve(world, 3, 7) == [0, 0, 0, 0, 0]  # not counted as on the books ...
    assert uncertain_curve(world, 3, 7) == [0, 2, 2, 2, 2]  # ... nor as absent
    row = stored(world, march(5))
    assert (row.uncertain_booking_count, row.uncertain_rooms) == (1, 2)
    assert row.origin == RECONSTRUCTED


def test_uncertainty_only_touches_the_nights_the_booking_belongs_to(world: World) -> None:
    world.book(
        STAY,
        STAY + timedelta(days=2),  # nights STAY and STAY+1
        status=BookingStatus.CANCELLED,
        booked_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        rooms=3,
    )

    world.reconstruct(march(5), march(5), STAY, STAY + timedelta(days=3))

    assert [
        stored(world, march(5), STAY + timedelta(days=i)).uncertain_rooms for i in range(4)
    ] == [3, 3, 0, 0]


def test_a_night_with_only_uncertain_bookings_has_zero_certain_rooms(world: World) -> None:
    world.book(
        STAY,
        STAY + timedelta(days=1),
        status=BookingStatus.CANCELLED,
        booked_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        revenue="400.00",
    )

    world.reconstruct(march(5), march(5), STAY, STAY)

    row = stored(world, march(5))
    assert (row.booking_count_on_books, row.rooms_on_books) == (0, 0)
    assert row.allocated_room_revenue_on_books == Decimal("0.00")  # uncertain money is not counted
    assert row.adr_on_books is None and row.uncertain_rooms == 1


def test_certain_and_uncertain_bookings_are_counted_apart(world: World) -> None:
    world.book(STAY, STAY + timedelta(days=1), rooms=2, revenue="200.00")
    world.book(
        STAY, STAY + timedelta(days=1), status=BookingStatus.CANCELLED, rooms=3, revenue="300.00"
    )

    world.reconstruct(march(5), march(5), STAY, STAY)

    row = stored(world, march(5))
    assert (row.booking_count_on_books, row.rooms_on_books) == (1, 2)
    assert (row.uncertain_booking_count, row.uncertain_rooms) == (1, 3)
    assert row.allocated_room_revenue_on_books == Decimal("200.00")
    assert row.adr_on_books == Decimal("100.00")


def test_a_no_show_is_certain_before_its_check_in_day_and_uncertain_from_then_on(
    world: World,
) -> None:
    arrival = march(8)
    world.book(
        arrival,
        arrival + timedelta(days=1),
        status=BookingStatus.NO_SHOW,
        booked_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
    )

    world.reconstruct(march(6), march(10), arrival, arrival)

    assert rooms_curve(world, 6, 10, arrival) == [1, 1, 0, 0, 0]
    assert uncertain_curve(world, 6, 10, arrival) == [0, 0, 1, 1, 1]


# --- I. the calculation copies today's inventory, and modified bookings are not history -------


def test_inventory_is_copied_at_calculation_time_and_a_missing_night_stays_null(
    world: World,
) -> None:
    world.book(STAY, STAY + timedelta(days=1), rooms=10)
    world.set_inventory(STAY, STAY, 40)

    world.reconstruct(march(5), march(5), STAY, STAY + timedelta(days=1))

    known, unknown = (
        stored(world, march(5), STAY),
        stored(world, march(5), STAY + timedelta(days=1)),
    )
    assert (known.rooms_available, known.occupancy_on_books) == (40, Decimal("25.00"))
    assert (unknown.rooms_available, unknown.occupancy_on_books) == (None, None)


def test_a_booking_modified_today_does_not_turn_a_reconstruction_into_an_observation(
    world: World, db_session: Session
) -> None:
    booking = world.book(STAY, STAY + timedelta(days=1), rooms=1)
    world.reconstruct(march(5), march(6), STAY, STAY)

    booking.rooms = 4  # the source system changed the booking after the fact
    world.commit()

    with pytest.raises(SnapshotError) as info:
        world.reconstruct(march(5), march(6), STAY, STAY)

    assert info.value.error_code == SnapshotErrorCode.CONFLICT
    assert info.value.details is not None and info.value.details["conflict_count"] == 2
    for day in (5, 6):  # nothing was rewritten and nothing was promoted
        row = stored(world, march(day))
        assert (row.origin, row.rooms_on_books) == (RECONSTRUCTED, 1)
    assert count_snapshots(db_session) == 2


def test_the_same_reconstruction_twice_is_an_idempotent_no_op(
    world: World, db_session: Session
) -> None:
    world.book(STAY, STAY + timedelta(days=2))
    first = world.reconstruct(march(3), march(6), STAY, STAY + timedelta(days=1))
    fingerprints = set(db_session.scalars(select(BookingSnapshot.content_fingerprint)))

    second = world.reconstruct(march(3), march(6), STAY, STAY + timedelta(days=1))

    assert (first.created, first.unchanged) == (8, 0)
    assert (second.created, second.unchanged) == (0, 8)
    assert set(db_session.scalars(select(BookingSnapshot.content_fingerprint))) == fingerprints


def test_a_wider_run_only_adds_the_missing_days(world: World, db_session: Session) -> None:
    world.reconstruct(march(3), march(5), STAY, STAY)

    result = world.reconstruct(march(4), march(7), STAY, STAY)

    assert (result.created, result.unchanged) == (2, 2)
    assert count_snapshots(db_session) == 5


# --- I. an observation always wins ------------------------------------------------------------


def test_an_existing_observation_is_not_replaced_and_no_parallel_row_is_created(
    world: World, db_session: Session
) -> None:
    world.book(STAY, STAY + timedelta(days=1), rooms=2, booked_at=datetime(2026, 3, 1, tzinfo=UTC))
    world.clock.instant = datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
    world.observe(STAY, STAY)  # a real observation on the 8th
    observed = stored(world, march(8))
    world.book(STAY, STAY + timedelta(days=1), rooms=7)  # bookings changed afterwards
    world.clock.instant = NOW

    result = world.reconstruct(march(6), march(10), STAY, STAY)

    assert (result.created, result.skipped_observed, result.unchanged) == (4, 1, 0)
    after = stored(world, march(8))
    assert after.id == observed.id  # the very same row
    assert (after.origin, after.rooms_on_books, after.as_of_at) == (
        SnapshotOrigin.OBSERVED,
        2,
        datetime(2026, 3, 8, 10, 0, tzinfo=UTC),
    )
    assert count_snapshots(db_session) == 5  # one row per (day, night): no parallel reconstruction
    assert [stored(world, march(d)).origin for d in (6, 7, 8, 9, 10)] == [
        RECONSTRUCTED,
        RECONSTRUCTED,
        SnapshotOrigin.OBSERVED,
        RECONSTRUCTED,
        RECONSTRUCTED,
    ]


def test_a_run_made_only_of_observed_days_creates_nothing(world: World) -> None:
    world.clock.instant = datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
    world.observe(STAY, STAY)
    world.clock.instant = NOW

    result = world.reconstruct(march(8), march(8), STAY, STAY)

    assert (result.created, result.unchanged, result.skipped_observed) == (0, 0, 1)


# --- I. daylight saving ------------------------------------------------------------------------


def test_the_cutoff_is_right_around_the_spring_forward_of_rome(world: World) -> None:
    """Rome moves to CEST at 02:00 on 29 March: that local day lasts 23 hours."""
    on_the_29th = datetime(2026, 3, 29, 21, 30, tzinfo=UTC)  # 23:30 CEST on the 29th
    on_the_30th = datetime(2026, 3, 29, 22, 0, tzinfo=UTC)  # 00:00 CEST on the 30th
    world.book(STAY, STAY + timedelta(days=1), rooms=1, booked_at=on_the_29th)
    world.book(STAY, STAY + timedelta(days=1), rooms=10, booked_at=on_the_30th)
    world.clock.instant = datetime(2026, 4, 5, 10, 0, tzinfo=UTC)

    world.reconstruct(march(28), date(2026, 3, 31), STAY, STAY)

    assert [
        stored(world, d).rooms_on_books for d in (march(28), march(29), march(30), march(31))
    ] == [
        0,
        1,
        11,
        11,
    ]
    assert stored(world, march(29)).as_of_at == datetime(2026, 3, 29, 22, 0, tzinfo=UTC)
    assert stored(world, march(28)).as_of_at == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)


def test_the_cutoff_is_right_around_the_fall_back_of_rome(world: World) -> None:
    """Rome moves back to CET on 25 October: that local day lasts 25 hours."""
    late = datetime(2026, 10, 25, 22, 30, tzinfo=UTC)  # 23:30 CET on the 25th (still the 25th)
    next_day = datetime(2026, 10, 25, 23, 0, tzinfo=UTC)  # 00:00 CET on the 26th
    world.book(STAY, STAY + timedelta(days=1), rooms=1, booked_at=late)
    world.book(STAY, STAY + timedelta(days=1), rooms=10, booked_at=next_day)
    world.clock.instant = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)

    world.reconstruct(date(2026, 10, 24), date(2026, 10, 26), STAY, STAY)

    assert [stored(world, date(2026, 10, d)).rooms_on_books for d in (24, 25, 26)] == [0, 1, 11]
    assert stored(world, date(2026, 10, 25)).as_of_at == datetime(2026, 10, 25, 23, 0, tzinfo=UTC)


def test_a_time_zone_whose_midnight_does_not_exist_gets_its_cutoff_at_the_jump(
    world: World,
) -> None:
    """Sao Paulo, 2018-11-04: clocks went 00:00 -> 01:00, so the 3rd ends at the jump."""
    world.tenant.property.timezone = "America/Sao_Paulo"
    stay = date(2018, 11, 20)
    before = datetime(2018, 11, 4, 2, 59, tzinfo=UTC)  # 23:59 on the 3rd
    at_the_jump = datetime(2018, 11, 4, 3, 0, tzinfo=UTC)  # 01:00 on the 4th
    world.book(stay, stay + timedelta(days=1), rooms=1, booked_at=before)
    world.book(stay, stay + timedelta(days=1), rooms=10, booked_at=at_the_jump)

    world.reconstruct(date(2018, 11, 3), date(2018, 11, 4), stay, stay)

    assert stored(world, date(2018, 11, 3), stay).rooms_on_books == 1
    assert stored(world, date(2018, 11, 4), stay).rooms_on_books == 11
    assert stored(world, date(2018, 11, 3), stay).as_of_at == at_the_jump


def test_a_calendar_day_that_never_existed_is_refused_and_nothing_is_stored(
    world: World, db_session: Session
) -> None:
    world.tenant.property.timezone = "Pacific/Apia"  # skipped 2011-12-30

    with pytest.raises(SnapshotError) as info:
        world.reconstruct(date(2011, 12, 29), date(2011, 12, 31), STAY, STAY)

    assert info.value.error_code == SnapshotErrorCode.LOCAL_DATE_DOES_NOT_EXIST
    assert count_snapshots(db_session) == 0


# --- only completed days can be reconstructed --------------------------------------------------


def test_a_day_that_has_not_ended_yet_cannot_be_reconstructed(
    world: World, db_session: Session
) -> None:
    for day in (march(15), march(16), march(30)):
        with pytest.raises(SnapshotError) as info:
            world.reconstruct(day, day, STAY, STAY)
        assert info.value.error_code == SnapshotErrorCode.INVALID_RANGE
        assert info.value.details == {"reason": "snapshot_date_not_completed"}
    assert count_snapshots(db_session) == 0


def test_yesterday_is_reconstructable_and_the_boundary_is_the_cutoff_instant(
    world: World,
) -> None:
    assert world.reconstruct(march(14), march(14), STAY, STAY).created == 1

    world.clock.instant = end_of_local_day(march(15), ROME) - timedelta(microseconds=1)
    with pytest.raises(SnapshotError):
        world.reconstruct(march(15), march(15), STAY, STAY)
    world.clock.instant = end_of_local_day(march(15), ROME)  # the day has just ended
    assert world.reconstruct(march(15), march(15), STAY, STAY).created == 1


# --- allocation, scope, validation -------------------------------------------------------------


def test_the_revenue_allocation_is_kept_at_every_reconstructed_day(world: World) -> None:
    world.book(
        STAY, STAY + timedelta(days=3), revenue="100.00", booked_at=datetime(2026, 3, 4, tzinfo=UTC)
    )

    world.reconstruct(march(3), march(5), STAY, STAY + timedelta(days=2))

    assert [
        stored(world, march(3), STAY + timedelta(days=i)).allocated_room_revenue_on_books
        for i in range(3)
    ] == [Decimal("0.00")] * 3
    assert [
        stored(world, march(5), STAY + timedelta(days=i)).allocated_room_revenue_on_books
        for i in range(3)
    ] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


def test_reconstruction_is_scoped_to_one_data_source(world: World, factory: BookingFactory) -> None:
    second = factory.data_source(world.tenant.property)
    world.book(STAY, STAY + timedelta(days=1), rooms=2)
    world.book_in(second, STAY, STAY + timedelta(days=1), rooms=7)

    world.reconstruct(march(5), march(5), STAY, STAY)
    world.reconstruct(march(5), march(5), STAY, STAY, data_source_id=second.id)

    other = BookingSnapshotRepository(world.session, world.context).get_for_stay_date(
        second.id, march(5), STAY
    )
    assert stored(world, march(5)).rooms_on_books == 2
    assert other is not None and other.rooms_on_books == 7


def test_a_reconstruction_of_a_foreign_or_wrong_source_is_refused(
    world: World, factory: BookingFactory
) -> None:
    costs = factory.data_source(world.tenant.property, DataSourceDomain.COSTS)

    with pytest.raises(SnapshotError) as info:
        world.reconstruct(march(5), march(5), STAY, STAY, data_source_id=costs.id)

    assert info.value.error_code == SnapshotErrorCode.INVALID_DATA_SOURCE
    assert info.value.details == {"reason": "wrong_domain"}


def test_ranges_are_validated(world: World) -> None:
    with pytest.raises(SnapshotError) as info:
        world.reconstruct(march(7), march(5), STAY, STAY)
    assert info.value.details == {"range": "snapshot_date", "reason": "start_after_end"}
    with pytest.raises(SnapshotError) as info:
        world.reconstruct(march(5), march(7), STAY + timedelta(days=1), STAY)
    assert info.value.details == {"range": "stay_date", "reason": "start_after_end"}


def test_a_run_that_would_store_too_many_rows_is_refused(world: World) -> None:
    with pytest.raises(SnapshotError) as info:
        world.reconstruct(
            date(2025, 3, 1), date(2026, 2, 28), STAY, STAY + timedelta(days=600)
        )  # 365 x 601 rows

    assert info.value.details == {"reason": "too_many_rows", "max_rows": 200_000}


# --- K. the booking curve mixes observations and reconstructions without confusing them -------


def test_a_curve_can_hold_reconstructions_and_an_observation_and_tells_them_apart(
    world: World,
) -> None:
    world.book(STAY, STAY + timedelta(days=1), rooms=2, booked_at=datetime(2026, 3, 4, tzinfo=UTC))
    world.set_inventory(STAY, STAY, 10)
    world.reconstruct(march(3), march(6), STAY, STAY)
    world.clock.instant = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    world.observe(STAY, STAY)  # observed today, 15 March

    curve = BookingSnapshotRepository(world.session, world.context).list_curve_for_stay_date(
        world.tenant.data_source.id, STAY
    )

    assert [p.snapshot_local_date for p in curve] == [march(d) for d in (3, 4, 5, 6, 15)]
    assert [p.origin for p in curve] == [RECONSTRUCTED] * 4 + [SnapshotOrigin.OBSERVED]
    assert [p.rooms_on_books for p in curve] == [0, 2, 2, 2, 2]
    assert [p.occupancy_on_books for p in curve] == [Decimal("0.00")] + [Decimal("20.00")] * 4
    assert all(p.uncertain_rooms == 0 for p in curve)

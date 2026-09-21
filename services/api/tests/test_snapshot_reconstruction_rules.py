"""The reconstruction rules of `aggregate_reconstruction`, without a database.

Snapshot days are UTC days here (cutoff = next UTC midnight) so that instants are easy to read:
day k of the run ends at 2026-03-(2+k) 00:00 UTC. The time-zone/DST behaviour of the cutoffs is
tested in test_snapshot_localtime.py and, end to end, in the service tests.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.modules.bookings.models import BookingStatus
from app.modules.snapshots.aggregate import aggregate_reconstruction
from app.modules.snapshots.calculation import StayRecord
from app.modules.snapshots.localtime import end_of_local_day

UTC_TZ = ZoneInfo("UTC")
SNAPSHOT_DAYS = [date(2026, 3, day) for day in range(1, 6)]  # 1..5 March
CUTOFFS = [end_of_local_day(day, UTC_TZ) for day in SNAPSHOT_DAYS]
STAY_NIGHT = date(2026, 3, 20)


def at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def record(
    booked_at: datetime,
    status: BookingStatus = BookingStatus.CONFIRMED,
    *,
    cancelled_at: datetime | None = None,
    check_in: date = STAY_NIGHT,
    check_out: date = date(2026, 3, 21),
    rooms: int = 1,
    revenue: str = "100.00",
) -> StayRecord:
    return StayRecord(status, booked_at, cancelled_at, check_in, check_out, rooms, Decimal(revenue))


def rooms_curve(*stays: StayRecord) -> list[int]:
    grid = aggregate_reconstruction(stays, SNAPSHOT_DAYS, CUTOFFS, STAY_NIGHT, STAY_NIGHT)
    return [row[0].rooms for row in grid]


def uncertain_curve(*stays: StayRecord) -> list[int]:
    grid = aggregate_reconstruction(stays, SNAPSHOT_DAYS, CUTOFFS, STAY_NIGHT, STAY_NIGHT)
    return [row[0].uncertain_rooms for row in grid]


# --- I. booked_at -----------------------------------------------------------------------------


def test_a_booking_made_after_the_cutoff_is_absent_and_one_made_before_is_present() -> None:
    # made 3 March 10:00: absent at the end of 1 and 2 March, present from the end of 3 March
    assert rooms_curve(record(at(3, 10))) == [0, 0, 1, 1, 1]


def test_a_booking_made_before_the_first_cutoff_is_present_everywhere() -> None:
    assert rooms_curve(record(datetime(2026, 1, 1, tzinfo=UTC))) == [1, 1, 1, 1, 1]


def test_a_booking_made_after_every_cutoff_is_absent_everywhere() -> None:
    assert rooms_curve(record(at(9))) == [0, 0, 0, 0, 0]


def test_the_cutoff_instant_itself_is_excluded_from_the_day_that_it_closes() -> None:
    """Made exactly at 4 March 00:00 = the cutoff of 3 March: not yet on the books that day."""
    assert rooms_curve(record(at(4, 0, 0))) == [0, 0, 0, 1, 1]
    assert rooms_curve(record(at(3, 23, 59))) == [0, 0, 1, 1, 1]


# --- I. cancellations with a known cancelled_at ------------------------------------------------


def test_a_cancellation_before_the_cutoff_removes_the_booking_from_that_day_on() -> None:
    # booked 1 March 09:00, cancelled 3 March 15:00: on the books at the end of 1 and 2 March
    cancelled = record(at(1, 9), BookingStatus.CANCELLED, cancelled_at=at(3, 15))

    assert rooms_curve(cancelled) == [1, 1, 0, 0, 0]
    assert uncertain_curve(cancelled) == [0, 0, 0, 0, 0]  # nothing uncertain: the date is known


def test_a_cancellation_after_the_cutoff_leaves_the_booking_on_the_books() -> None:
    cancelled = record(at(1, 9), BookingStatus.CANCELLED, cancelled_at=at(9, 12))

    assert rooms_curve(cancelled) == [1, 1, 1, 1, 1]


def test_a_cancellation_stamped_exactly_at_the_cutoff_happened_on_the_next_day() -> None:
    """Cancelled at 3 March 00:00 = the cutoff of 2 March: still on the books at the end of 2."""
    cancelled = record(at(1, 9), BookingStatus.CANCELLED, cancelled_at=at(3, 0, 0))

    assert rooms_curve(cancelled) == [1, 1, 0, 0, 0]


def test_a_booking_cancelled_the_day_it_was_made_was_never_on_the_books_at_a_cutoff() -> None:
    cancelled = record(at(2, 9), BookingStatus.CANCELLED, cancelled_at=at(2, 18))

    assert rooms_curve(cancelled) == [0, 0, 0, 0, 0]
    assert uncertain_curve(cancelled) == [0, 0, 0, 0, 0]


# --- I. uncertainty: no historical fiction -----------------------------------------------------


def test_a_cancelled_booking_without_a_date_is_uncertain_never_present_never_absent() -> None:
    """It was on the books at some point after being made, but for how long is not known."""
    undated = record(at(2, 9), BookingStatus.CANCELLED, cancelled_at=None)

    assert rooms_curve(undated) == [0, 0, 0, 0, 0]  # NOT counted as certainly on the books
    assert uncertain_curve(undated) == [0, 1, 1, 1, 1]  # and not counted as absent either


def test_uncertainty_counts_bookings_and_rooms_but_never_touches_certain_totals() -> None:
    undated = record(at(1, 9), BookingStatus.CANCELLED, cancelled_at=None, rooms=3)
    confirmed = record(at(1, 9), rooms=2)

    grid = aggregate_reconstruction(
        [undated, confirmed], SNAPSHOT_DAYS, CUTOFFS, STAY_NIGHT, STAY_NIGHT
    )
    cell = grid[0][0]

    assert (cell.booking_count, cell.rooms, cell.revenue_cents) == (1, 2, 10_000)
    assert (cell.uncertain_booking_count, cell.uncertain_rooms) == (1, 3)


def test_a_cancellation_that_precedes_the_booking_is_an_inconsistency_treated_as_unknown() -> None:
    """cancelled_at < booked_at cannot be true: it is neither trusted nor silently dropped."""
    broken = record(at(3, 9), BookingStatus.CANCELLED, cancelled_at=at(1, 9))

    assert rooms_curve(broken) == [0, 0, 0, 0, 0]
    assert uncertain_curve(broken) == [0, 0, 1, 1, 1]


def test_a_no_show_is_certain_until_its_check_in_day_then_uncertain() -> None:
    """Nobody can know a no-show before the arrival day; the canonical row does not say when
    it was recorded, so from the snapshot day of the check-in date on it is uncertain."""
    no_show = record(
        at(1, 9),
        BookingStatus.NO_SHOW,
        check_in=date(2026, 3, 3),
        check_out=date(2026, 3, 4),
    )
    grid = aggregate_reconstruction(
        [no_show], SNAPSHOT_DAYS, CUTOFFS, date(2026, 3, 3), date(2026, 3, 3)
    )

    assert [row[0].rooms for row in grid] == [1, 1, 0, 0, 0]
    assert [row[0].uncertain_rooms for row in grid] == [0, 0, 1, 1, 1]


def test_confirmed_checked_in_and_checked_out_bookings_are_on_the_books_once_made() -> None:
    for status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.CHECKED_OUT):
        assert rooms_curve(record(at(2, 9), status)) == [0, 1, 1, 1, 1], status


# --- structure of the result -------------------------------------------------------------------


def test_every_snapshot_day_and_stay_night_has_a_cell_even_with_no_booking() -> None:
    grid = aggregate_reconstruction(
        [], SNAPSHOT_DAYS, CUTOFFS, date(2026, 3, 20), date(2026, 3, 22)
    )

    assert len(grid) == 5 and all(len(row) == 3 for row in grid)
    assert all(cell.rooms == 0 and cell.uncertain_rooms == 0 for row in grid for cell in row)


def test_revenue_is_allocated_per_night_at_every_cutoff() -> None:
    stays = [record(at(2, 9), check_in=date(2026, 3, 20), check_out=date(2026, 3, 23))]
    grid = aggregate_reconstruction(
        stays, SNAPSHOT_DAYS, CUTOFFS, date(2026, 3, 20), date(2026, 3, 22)
    )

    # 100.00 over 3 nights = 33.34 / 33.33 / 33.33, present from the end of 2 March
    assert [cell.revenue_cents for cell in grid[0]] == [0, 0, 0]
    assert [cell.revenue_cents for cell in grid[1]] == [3334, 3333, 3333]
    assert sum(cell.revenue_cents for cell in grid[4]) == 10_000


def test_the_state_at_a_cutoff_does_not_depend_on_which_other_days_are_requested() -> None:
    stays = [
        record(at(2, 9)),
        record(at(1, 9), BookingStatus.CANCELLED, cancelled_at=at(3, 15)),
        record(at(2, 9), BookingStatus.CANCELLED, cancelled_at=None),
    ]
    full = aggregate_reconstruction(stays, SNAPSHOT_DAYS, CUTOFFS, STAY_NIGHT, STAY_NIGHT)
    part = aggregate_reconstruction(stays, SNAPSHOT_DAYS[2:4], CUTOFFS[2:4], STAY_NIGHT, STAY_NIGHT)

    assert [row[0] for row in part] == [full[2][0], full[3][0]]

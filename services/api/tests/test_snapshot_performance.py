"""No N+1: the number of SQL statements of a run does not grow with bookings or stay dates.

1000 bookings x 365 stay dates must complete with a small, bounded number of statements. No
timing is measured (milliseconds are machine noise); the statement count is what would explode
with a query per booking or per stay night. The numbers are also checked against a deliberately
naive calculation written in the test itself.
"""

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, event, insert, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking, BookingStatus
from app.modules.snapshots.models import BookingSnapshot
from tests.snapshot_support import World
from tests.support import BookingFactory, booking_values

NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
FIRST_NIGHT = date(2026, 3, 1)
STATUSES = [
    BookingStatus.CONFIRMED,
    BookingStatus.CONFIRMED,
    BookingStatus.CONFIRMED,
    BookingStatus.CHECKED_OUT,
    BookingStatus.CANCELLED,
    BookingStatus.NO_SHOW,
]


def seed(world: World, count: int) -> list[dict[str, Any]]:
    """`count` reproducible bookings spread over more than a year, inserted in one statement."""
    rng = random.Random(20260920)
    rows = []
    for index in range(count):
        status = rng.choice(STATUSES)
        check_in = FIRST_NIGHT - timedelta(days=10) + timedelta(days=rng.randrange(0, 400))
        booked_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=rng.randrange(0, 24 * 300))
        cancelled = status == BookingStatus.CANCELLED and rng.random() < 0.6
        rows.append(
            booking_values(
                world.tenant.data_source,
                world.channel,
                world.tenant.import_job,
                source_record_id=f"P-{index:05d}",
                status=status,
                check_in=check_in,
                check_out=check_in + timedelta(days=rng.randint(1, 9)),
                rooms=rng.randint(1, 3),
                room_revenue=Decimal(rng.randint(5_000, 200_000)) / 100,
                booked_at=booked_at,
                cancelled_at=booked_at + timedelta(days=rng.randint(1, 30)) if cancelled else None,
            )
        )
    world.session.execute(insert(Booking), rows)
    world.commit()
    return rows


@contextmanager
def count_statements(session: Session) -> Iterator[list[str]]:
    connection = session.get_bind()
    assert isinstance(connection, Connection)
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


def naive_expected(rows: list[dict[str, Any]], night: date) -> tuple[int, int, int]:
    """(bookings, rooms, cents) of one night, the slowest and plainest way."""
    bookings = rooms = cents = 0
    for row in rows:
        if row["status"] not in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_OUT):
            continue
        if not row["check_in"] <= night < row["check_out"]:
            continue
        length = (row["check_out"] - row["check_in"]).days
        position = (night - row["check_in"]).days
        total = int(row["room_revenue"] * 100)
        bookings += 1
        rooms += row["rooms"]
        cents += total // length + (1 if position < total % length else 0)
    return bookings, rooms, cents


def test_1000_bookings_over_365_stay_dates_use_a_bounded_number_of_statements(
    db_session: Session, factory: BookingFactory
) -> None:
    world = World.create(db_session, factory, NOW)
    rows = seed(world, 1000)
    world.set_inventory(FIRST_NIGHT, FIRST_NIGHT + timedelta(days=364), 30)
    last = FIRST_NIGHT + timedelta(days=364)

    with count_statements(db_session) as statements:
        result = world.observe(FIRST_NIGHT, last)

    assert result.created == 365
    assert len(statements) <= 12, statements  # property, source, lock, 3 reads, insert, commit...
    stored = {
        r.stay_date: r
        for r in db_session.scalars(
            select(BookingSnapshot).where(BookingSnapshot.origin == "OBSERVED")
        )
    }
    assert len(stored) == 365
    for offset in (0, 1, 59, 100, 200, 300, 364):  # a spread of nights, against the naive result
        night = FIRST_NIGHT + timedelta(days=offset)
        bookings, rooms, cents = naive_expected(rows, night)
        row = stored[night]
        assert (row.booking_count_on_books, row.rooms_on_books) == (bookings, rooms), night
        assert row.allocated_room_revenue_on_books == Decimal(cents) / 100, night
        assert row.rooms_available == 30
    assert any(r.rooms_on_books > 0 for r in stored.values())  # the data is not trivially empty


def test_the_statement_count_does_not_depend_on_the_number_of_bookings_or_stay_dates(
    db_session: Session, factory: BookingFactory
) -> None:
    small_world = World.create(db_session, factory, NOW)
    seed(small_world, 20)
    with count_statements(db_session) as small:
        small_world.observe(FIRST_NIGHT, FIRST_NIGHT + timedelta(days=9))

    big_world = World.create(db_session, factory, NOW)
    seed(big_world, 1000)
    with count_statements(db_session) as big:
        big_world.observe(FIRST_NIGHT, FIRST_NIGHT + timedelta(days=364))

    assert len(big) == len(small), (small, big)


def test_a_reconstruction_of_60_days_over_365_nights_stays_bounded_and_correct(
    db_session: Session, factory: BookingFactory
) -> None:
    world = World.create(db_session, factory, NOW)
    seed(world, 1000)
    world.set_inventory(FIRST_NIGHT, FIRST_NIGHT + timedelta(days=364), 30)
    first_day = date(2026, 6, 1)
    last_day = first_day + timedelta(days=59)
    last_night = FIRST_NIGHT + timedelta(days=364)

    with count_statements(db_session) as statements:
        result = world.reconstruct(first_day, last_day, FIRST_NIGHT, last_night)

    rows = 60 * 365
    assert result.created == rows
    assert len(statements) <= 12 + rows // 1000, len(statements)  # inserts are batched


def test_the_reconstruction_agrees_with_a_naive_calculation_on_a_sample(
    db_session: Session, factory: BookingFactory
) -> None:
    """The difference-array implementation against per-cell brute force, on real rows."""
    world = World.create(db_session, factory, NOW)
    bookings = seed(world, 300)
    first_day, last_day = date(2026, 5, 1), date(2026, 5, 20)
    first_night, last_night = date(2026, 5, 5), date(2026, 6, 30)
    world.reconstruct(first_day, last_day, first_night, last_night)
    from zoneinfo import ZoneInfo

    from app.modules.snapshots.localtime import end_of_local_day

    rome = ZoneInfo("Europe/Rome")
    checked = 0
    for snapshot_offset in range(20):
        snapshot_day = first_day + timedelta(days=snapshot_offset)
        cutoff = end_of_local_day(snapshot_day, rome)
        for night_offset in range(0, 57, 7):
            night = first_night + timedelta(days=night_offset)
            count = rooms = ucount = urooms = 0
            for b in bookings:
                if not (b["check_in"] <= night < b["check_out"]) or not b["booked_at"] < cutoff:
                    continue
                status = b["status"]
                if status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_OUT):
                    on_books, unsure = True, False
                elif status == BookingStatus.CANCELLED:
                    cancelled_at = b["cancelled_at"]
                    if cancelled_at is None:
                        on_books, unsure = False, True
                    else:
                        on_books, unsure = cutoff <= cancelled_at, False
                else:  # NO_SHOW: a normal booking until its arrival day, unknown afterwards
                    on_books, unsure = snapshot_day < b["check_in"], snapshot_day >= b["check_in"]
                if on_books:
                    count += 1
                    rooms += b["rooms"]
                if unsure:
                    ucount += 1
                    urooms += b["rooms"]
            row = world.stored(snapshot_day, night)
            assert row is not None
            assert (
                row.booking_count_on_books,
                row.rooms_on_books,
                row.uncertain_booking_count,
                row.uncertain_rooms,
            ) == (count, rooms, ucount, urooms), (snapshot_day, night)
            checked += 1
    assert checked == 20 * 9

"""The history a past month's cost per occupied room needs, once the inventory says how many rooms
there were.

October's cost divides by the rooms on the books of every day of October. A property analysed from
the 9th of November has none of those snapshots, so the cost stays "month incomplete" however many
invoices it has. What the bookings imported say about those days can be stored as a reconstruction -
but only for a night that has an inventory (the reconstruction copies it, and is never rewritten),
only inside the nights the bookings speak about, never over a snapshot that exists, and nothing
already analysed changes. When something is still missing, the response says exactly what.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.analysis.history import HistoryBackfill, backfill_lead_zero_history
from app.modules.analysis.refresh import RefreshOutcomeKind
from app.modules.analysis.room_inventory import RoomInventoryService
from app.modules.bookings.models import BookingStatus
from app.modules.data_overview.types import CostOccupancyBasis, CostOverview, CporStatus
from app.modules.decisions.models import DecisionRun
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.invoices.cost_categories import CostCategory
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from tests.cost_support import CostWorld, month
from tests.data_overview_support import AS_OF, overview_of, seed_run
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel
from tests.refresh_support import purge as purge_hotel
from tests.support import BookingFactory

D = Decimal
TODAY = date(2026, 11, 9)
NOON = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)  # 12:00 in Rome
OCTOBER = month(2026, 10)
OCT = date(2026, 10, 1)


def oct_day(number: int) -> date:
    return date(2026, 10, number)


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


StayMaker = Callable[..., None]


@pytest.fixture
def stay(world: CostWorld, factory: BookingFactory) -> StayMaker:
    channel = factory.channel(world.tenant.property)

    def make(
        first_night: date,
        last_night: date,
        *,
        code: str = "B-1",
        rooms: int = 2,
        status: BookingStatus = BookingStatus.CONFIRMED,
        cancelled_at: datetime | None = None,
    ) -> None:
        """One booking, made long before, that holds `rooms` rooms from `first_night` to
        `last_night`."""
        factory.booking(
            world.booking_source,
            channel,
            world.tenant.import_job,
            source_record_id=code,
            check_in=first_night,
            check_out=last_night + timedelta(days=1),
            booked_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            rooms=rooms,
            status=status,
            cancelled_at=cancelled_at,
        )

    return make


def _october_costs(world: CostWorld) -> None:
    world.invoice(date(2026, 10, 10), [(CostCategory.UTILITIES, "1240.00")])


def _run_of_today(db_session: Session, world: CostWorld) -> None:
    seed_run(db_session, world.tenant, as_of=TODAY)


def _inventory(
    db_session: Session, world: CostWorld, valid_from: date | None, rooms: int = 10
) -> None:
    RoomInventoryService(db_session, world.context).save(
        world.tenant.property.id, rooms, NOON, valid_from=valid_from
    )


def _rebuild(
    db_session: Session,
    world: CostWorld,
    months: tuple[tuple[int, int], ...] = ((2026, 10),),
) -> HistoryBackfill:
    return backfill_lead_zero_history(
        db_session,
        world.context,
        property_id=world.tenant.property.id,
        data_source_id=world.booking_source.id,
        cost_months=months,
        local_today=TODAY,
        now=NOON,
    )


def _costs(db_session: Session, world: CostWorld) -> CostOverview:
    return overview_of(db_session, world.tenant, as_of=TODAY).costs


def _stored(db_session: Session, world: CostWorld) -> dict[date, BookingSnapshot]:
    db_session.expire_all()
    rows = db_session.scalars(
        select(BookingSnapshot).where(BookingSnapshot.data_source_id == world.booking_source.id)
    ).all()
    return {row.stay_date: row for row in rows if row.snapshot_local_date == row.stay_date}


def _basis(costs: CostOverview) -> CostOccupancyBasis:
    assert costs.occupancy_basis is not None
    return costs.occupancy_basis


# --- the way from a month with no history to a cost per occupied room ----------------------------


def test_a_past_month_gets_its_denominator_once_the_inventory_says_how_many_rooms_there_were(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))  # 2 rooms every night of October
    _october_costs(world)
    _run_of_today(db_session, world)

    before = _costs(db_session, world)
    assert _basis(before) == CostOccupancyBasis(
        total_days=31,
        known_days=0,
        observed_days=0,
        reconstructed_days=0,
        uncertain_days=0,
        days_outside_bookings=0,
        days_without_inventory=31,
        days_awaiting_rebuild=0,
        first_day_without_inventory=OCT,
    )
    assert before.categories[0].cpor is None
    assert before.categories[0].cpor_status is CporStatus.INCOMPLETE

    # nothing is rebuilt while the inventory is silent: it would keep "no capacity" for good
    assert _rebuild(db_session, world) == HistoryBackfill(considered=31, rebuilt=0)
    assert _stored(db_session, world) == {}

    _inventory(db_session, world, valid_from=OCT)
    assert _basis(_costs(db_session, world)).days_awaiting_rebuild == 31  # on its way, not missing

    assert _rebuild(db_session, world) == HistoryBackfill(considered=31, rebuilt=31)

    after = _costs(db_session, world)
    assert _basis(after) == CostOccupancyBasis(
        total_days=31,
        known_days=31,
        observed_days=0,
        reconstructed_days=31,
        uncertain_days=0,
        days_outside_bookings=0,
        days_without_inventory=0,
        days_awaiting_rebuild=0,
        first_day_without_inventory=None,
    )
    row = after.categories[0]
    assert row.cpor_status is CporStatus.READY
    assert row.cpor == D("20.00")  # 1240 / (2 rooms x 31 nights)


def test_what_is_stored_is_a_reconstruction_of_the_day_with_its_capacity_and_nothing_else(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    _october_costs(world)
    _inventory(db_session, world, valid_from=OCT)

    _rebuild(db_session, world)

    stored = _stored(db_session, world)
    assert set(stored) == {oct_day(number) for number in range(1, 32)}
    assert {row.origin for row in stored.values()} == {SnapshotOrigin.RECONSTRUCTED_APPROXIMATE}
    assert {(row.rooms_on_books, row.rooms_available) for row in stored.values()} == {(2, 10)}
    # the lead-time-0 day only: no grid of lead times nobody reads
    all_rows = db_session.scalars(
        select(BookingSnapshot).where(BookingSnapshot.data_source_id == world.booking_source.id)
    ).all()
    assert len(all_rows) == 31


def test_a_second_call_finds_everything_stored_and_writes_nothing(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    _inventory(db_session, world, valid_from=OCT)
    assert _rebuild(db_session, world).rebuilt == 31
    before = {day: row.id for day, row in _stored(db_session, world).items()}

    assert _rebuild(db_session, world) == HistoryBackfill(considered=31, rebuilt=0)

    assert {day: row.id for day, row in _stored(db_session, world).items()} == before


def test_an_observed_day_is_never_replaced_by_a_reconstruction(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    _inventory(db_session, world, valid_from=OCT)
    world.snapshot(oct_day(5), oct_day(5), 7)  # what NINFA really saw that evening

    assert _rebuild(db_session, world).rebuilt == 30

    kept = _stored(db_session, world)[oct_day(5)]
    assert kept.origin is SnapshotOrigin.OBSERVED and kept.rooms_on_books == 7


def test_a_stored_reconstruction_is_history_that_is_not_revised(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31), rooms=2)
    _inventory(db_session, world, valid_from=OCT)
    _rebuild(db_session, world)
    first = {day: row.content_fingerprint for day, row in _stored(db_session, world).items()}

    # the bookings change afterwards, and the inventory with them: the stored days do not move
    stay(oct_day(1), oct_day(31), code="B-2", rooms=3)
    _inventory(db_session, world, valid_from=OCT, rooms=12)
    assert _rebuild(db_session, world).rebuilt == 0

    assert {day: row.content_fingerprint for day, row in _stored(db_session, world).items()} == (
        first
    )


# --- what it does not invent ---------------------------------------------------------------------


def test_nights_the_bookings_say_nothing_about_are_unknown_not_zero(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(10), oct_day(20))  # the file covers 11 nights
    _october_costs(world)
    _run_of_today(db_session, world)
    _inventory(db_session, world, valid_from=OCT)

    assert _rebuild(db_session, world) == HistoryBackfill(considered=31, rebuilt=11)

    assert set(_stored(db_session, world)) == {oct_day(number) for number in range(10, 21)}
    costs = _costs(db_session, world)
    basis = _basis(costs)
    assert (basis.known_days, basis.days_outside_bookings) == (11, 20)
    assert (basis.days_without_inventory, basis.days_awaiting_rebuild) == (0, 0)
    assert costs.categories[0].cpor_status is CporStatus.INCOMPLETE
    assert costs.categories[0].cpor is None


def test_nights_before_the_inventory_began_are_not_rebuilt_and_the_first_is_named(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    _october_costs(world)
    _run_of_today(db_session, world)
    _inventory(db_session, world, valid_from=oct_day(15))

    assert _rebuild(db_session, world).rebuilt == 17  # 15 to 31 October

    basis = _basis(_costs(db_session, world))
    assert basis.known_days == 17
    assert basis.days_without_inventory == 14
    assert basis.first_day_without_inventory == OCT
    assert min(_stored(db_session, world)) == oct_day(15)


def test_a_booking_cancelled_with_no_date_leaves_the_rooms_of_those_nights_unknown(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    stay(
        oct_day(5),
        oct_day(7),
        code="B-CANCELLED",
        rooms=1,
        status=BookingStatus.CANCELLED,
    )
    _october_costs(world)
    _run_of_today(db_session, world)
    _inventory(db_session, world, valid_from=OCT)

    assert _rebuild(db_session, world).rebuilt == 31

    costs = _costs(db_session, world)
    basis = _basis(costs)
    assert (basis.known_days, basis.uncertain_days) == (28, 3)
    assert basis.days_outside_bookings == basis.days_without_inventory == 0
    assert costs.categories[0].cpor_status is CporStatus.INCOMPLETE  # an unknown is never a guess


def test_with_no_bookings_there_is_nothing_to_rebuild_from(
    db_session: Session, world: CostWorld
) -> None:
    _inventory(db_session, world, valid_from=OCT)

    assert _rebuild(db_session, world) == HistoryBackfill(considered=31, rebuilt=0)
    assert _stored(db_session, world) == {}


def test_only_the_days_that_have_ended_are_ever_asked_for(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(date(2026, 11, 1), date(2026, 11, 30))
    _inventory(db_session, world, valid_from=date(2026, 11, 1))

    result = _rebuild(db_session, world, months=((2026, 11),))

    assert result == HistoryBackfill(considered=8, rebuilt=8)  # 1 to 8 November, today is the 9th
    assert max(_stored(db_session, world)) == date(2026, 11, 8)


def test_with_no_cost_month_there_is_nothing_to_ask_for(
    db_session: Session, stay: StayMaker, world: CostWorld
) -> None:
    stay(oct_day(1), oct_day(31))
    _inventory(db_session, world, valid_from=OCT)

    assert _rebuild(db_session, world, months=()) == HistoryBackfill(considered=0, rebuilt=0)


# --- the answer, with no cost to explain ---------------------------------------------------------


def test_with_no_booking_source_the_costs_say_nothing_about_a_denominator(
    db_session: Session, world: CostWorld
) -> None:
    _october_costs(world)
    seed_run(db_session, world.tenant, as_of=AS_OF)  # the run of 1 August: July is the month

    assert overview_of(db_session, world.tenant).costs.occupancy_basis is None


# --- with real commits: the way the product goes -------------------------------------------------


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Path) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge_hotel(db_engine, built.tenant.workspace_id)


def _costs_of(hotel: Hotel) -> CostOverview:
    from app.modules.data_overview.service import DataOverviewService

    with hotel.session() as session:
        return (
            DataOverviewService(session, hotel.tenant)
            .overview(hotel.property_id, local_today(), 30)
            .costs
        )


def _last_month_stay(code: str, last: CalendarMonth) -> dict[str, Any]:
    return {
        "source_record_id": code,
        "booked_at": (last.start - timedelta(days=30)).isoformat(),
        "check_in": last.start.isoformat(),
        "check_out": (last.end + timedelta(days=1)).isoformat(),
        "status": "confirmed",
        "rooms": "2",
        "room_revenue": "6200.00",
        "channel": "Booking.com",
    }


def test_the_refresh_after_a_retroactive_inventory_rebuilds_the_month_and_leaves_the_runs_alone(
    hotel: Hotel,
) -> None:
    """The whole way: bookings and an invoice of last month, an analysis with no capacity, the
    inventory said to be valid from the first of last month, the refresh it asks for - and the cost
    of last month rests on every one of its days, while the run before is exactly what it was."""
    last = CalendarMonth.of(local_today()).shifted(-1)
    hotel.import_bookings("b.csv", [_last_month_stay("MONTH", last), booking_row("TODAY", 3)])
    hotel.import_invoices([last.start + timedelta(days=9)])

    first = hotel.refresh()
    assert first.result is not None and first.history_days_rebuilt == 0  # no inventory yet
    before = _costs_of(hotel)
    assert _basis(before).days_without_inventory == last.days
    assert _basis(before).known_days == 0
    runs_before = [(run.id, run.run_sequence) for run in hotel.runs()]

    with hotel.session() as session:
        saved = RoomInventoryService(session, hotel.tenant).save(
            hotel.property_id, 10, valid_from=last.start
        )
    assert saved.analysis_requested is True

    second = hotel.refresh()

    assert second.result is not None
    assert second.history_days_rebuilt == last.days
    after = _basis(_costs_of(hotel))
    assert (after.known_days, after.reconstructed_days) == (last.days, last.days)
    assert after.days_without_inventory == after.days_awaiting_rebuild == 0
    # every run there was is still there, and a new one only ever adds to them
    kept = [(run.id, run.run_sequence) for run in hotel.runs()]
    assert kept[: len(runs_before)] == runs_before
    # and a third refresh has nothing left to rebuild
    third = hotel.refresh()
    assert third.history_days_rebuilt == 0
    assert all(isinstance(run, DecisionRun) for run in hotel.runs())


def test_history_is_never_added_under_a_day_already_analysed_so_a_refresh_never_disagrees_with_it(
    hotel: Hotel,
) -> None:
    """A stored baseline names its comparables and is never rewritten. With an analysis of today
    already there, the refresh makes today's analysis first - on the same history, so it agrees -
    and only then adds the history. A refresh made later the same day, on bookings that did not
    change, would now read a different history: it waits for tomorrow instead of failing."""
    last = CalendarMonth.of(local_today()).shifted(-1)
    hotel.import_bookings(
        "b.csv",
        [_last_month_stay("MONTH", last), booking_row("NOW", 0), booking_row("SOON", 3)],
    )
    hotel.import_invoices([last.start + timedelta(days=9)])
    assert hotel.refresh().result is not None  # the analysis of today, with no inventory yet
    runs_before = [(run.id, run.run_sequence) for run in hotel.runs()]

    with hotel.session() as session:
        RoomInventoryService(session, hotel.tenant).save(
            hotel.property_id, 10, valid_from=last.start
        )
    second = hotel.refresh()

    assert second.kind is RefreshOutcomeKind.RAN  # today's analysis did not move
    assert second.history_days_rebuilt == last.days  # and the history came after it
    assert [(run.id, run.run_sequence) for run in hotel.runs()][: len(runs_before)] == runs_before

    third = hotel.refresh()  # the same day, the same bookings, a history that is not the same

    assert third.kind is RefreshOutcomeKind.DEFERRED
    assert third.retry_at is not None and third.result is None
    assert third.history_days_rebuilt == 0
    assert [(run.id, run.run_sequence) for run in hotel.runs()][: len(runs_before)] == runs_before


def test_a_baseline_that_history_would_change_waits_for_tomorrow_it_is_not_a_failure(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.analysis import refresh as module
    from app.modules.intelligence.expected.errors import ExpectedError, ExpectedErrorCode

    hotel.import_bookings("b.csv", [booking_row("SOON", 3)])
    assert hotel.refresh().result is not None

    def conflicting(*args: Any, **kwargs: Any) -> None:
        raise ExpectedError(ExpectedErrorCode.BASELINE_CONFLICT, "a stored baseline differs")

    monkeypatch.setattr(module, "run_property_analysis", conflicting)

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.DEFERRED
    assert outcome.result is None and outcome.retry_at is not None


def test_any_other_expected_failure_still_fails_the_job(
    hotel: Hotel, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.analysis import refresh as module
    from app.modules.intelligence.expected.errors import ExpectedError, ExpectedErrorCode

    hotel.import_bookings("b.csv", [booking_row("SOON", 3)])
    hotel.refresh()

    def broken(*args: Any, **kwargs: Any) -> None:
        raise ExpectedError(ExpectedErrorCode.INVALID_RANGE, "not a conflict")

    monkeypatch.setattr(module, "run_property_analysis", broken)

    with pytest.raises(ExpectedError):
        hotel.refresh()


def test_with_no_analysis_yet_today_the_history_comes_first_and_today_reads_it(
    hotel: Hotel,
) -> None:
    last = CalendarMonth.of(local_today()).shifted(-1)
    hotel.import_bookings("b.csv", [_last_month_stay("MONTH", last), booking_row("SOON", 3)])
    hotel.import_invoices([last.start + timedelta(days=9)])
    with hotel.session() as session:
        RoomInventoryService(session, hotel.tenant).save(
            hotel.property_id, 10, valid_from=last.start
        )
    assert hotel.runs_today() == []

    outcome = hotel.refresh()

    assert outcome.kind is RefreshOutcomeKind.RAN and outcome.history_days_rebuilt == last.days
    assert len(hotel.runs_today()) == 1

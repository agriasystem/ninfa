"""ObservedSnapshotService: an observation of what the canonical bookings say right now.

An observation is evidence: one row per stay night (zero-booking nights included), computed at
the injected clock's instant, copied from the inventory of that moment, never rewritten.
"""

import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingStatus
from app.modules.ingestion.models import DataSourceDomain
from app.modules.snapshots.calculation import CALCULATION_VERSION, SnapshotContent
from app.modules.snapshots.common import SnapshotServiceBase
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.snapshot_support import World, insert_snapshot
from tests.support import BookingFactory, Tenant

NOW = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)  # 11:00 in Rome
TODAY = date(2026, 3, 15)
FIRST = date(2026, 3, 20)


def night(offset: int) -> date:
    return FIRST + timedelta(days=offset)


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> World:
    return World.create(db_session, factory, NOW)


def snapshot_of(world: World, stay_date: date, snapshot_date: date = TODAY) -> BookingSnapshot:
    row = world.stored(snapshot_date, stay_date)
    assert row is not None, (snapshot_date, stay_date)
    return row


def count_snapshots(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(BookingSnapshot)) or 0)


# --- F. one row per stay date, absence of bookings is data ------------------------------------


def test_every_stay_date_of_the_range_gets_a_row_even_without_bookings(world: World) -> None:
    world.book(night(1), night(3), rooms=2, revenue="200.00")

    result = world.observe(night(0), night(4))

    assert (result.created, result.unchanged, result.skipped_observed) == (5, 0, 0)
    rows = [snapshot_of(world, night(offset)) for offset in range(5)]
    assert [(r.booking_count_on_books, r.rooms_on_books) for r in rows] == [
        (0, 0),
        (1, 2),
        (1, 2),
        (0, 0),
        (0, 0),
    ]
    empty = rows[0]
    assert empty.allocated_room_revenue_on_books == Decimal("0.00")
    assert empty.adr_on_books is None  # never 0
    assert (empty.uncertain_booking_count, empty.uncertain_rooms) == (0, 0)


def test_the_result_reports_what_was_done_and_never_more(world: World) -> None:
    result = world.observe(night(0), night(2))

    assert result.origin == SnapshotOrigin.OBSERVED
    assert result.total == 3
    assert (result.snapshot_date_first, result.snapshot_date_last) == (TODAY, TODAY)
    assert (result.stay_date_first, result.stay_date_last) == (night(0), night(2))
    assert result.calculation_version == CALCULATION_VERSION
    assert (result.property_id, result.data_source_id) == (
        world.tenant.property.id,
        world.tenant.data_source.id,
    )


def test_a_single_night_range_is_valid(world: World) -> None:
    assert world.observe(night(0), night(0)).created == 1


def test_stored_rows_are_observed_versioned_and_carry_a_matching_fingerprint(world: World) -> None:
    world.book(night(0), night(2), rooms=2, revenue="250.00")
    world.set_inventory(night(0), night(0), 10)
    world.observe(night(0), night(1))

    row = snapshot_of(world, night(0))

    assert row.origin == SnapshotOrigin.OBSERVED
    assert row.calculation_version == "booking-snapshot-v1"
    assert (row.workspace_id, row.property_id, row.data_source_id) == (
        world.tenant.workspace.id,
        world.tenant.property.id,
        world.tenant.data_source.id,
    )
    recomputed = SnapshotContent(
        origin=row.origin,
        snapshot_local_date=row.snapshot_local_date,
        stay_date=row.stay_date,
        data_source_id=row.data_source_id,
        booking_count_on_books=row.booking_count_on_books,
        rooms_on_books=row.rooms_on_books,
        allocated_room_revenue_on_books=row.allocated_room_revenue_on_books,
        rooms_available=row.rooms_available,
        occupancy_on_books=row.occupancy_on_books,
        adr_on_books=row.adr_on_books,
        uncertain_booking_count=row.uncertain_booking_count,
        uncertain_rooms=row.uncertain_rooms,
        calculation_version=row.calculation_version,
    )
    assert recomputed.fingerprint() == row.content_fingerprint


# --- F. time: UTC instants, property-local dates ----------------------------------------------


def test_as_of_at_is_the_clock_instant_in_utc(world: World) -> None:
    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))

    assert row.as_of_at == NOW and row.as_of_at.utcoffset() == timedelta(0)


def test_a_clock_in_another_offset_is_converted_to_utc(world: World) -> None:
    world.clock.instant = datetime(2026, 3, 15, 11, 0, tzinfo=ZoneInfo("Europe/Rome"))

    world.observe(night(0), night(0))

    assert snapshot_of(world, night(0)).as_of_at == datetime(2026, 3, 15, 10, 0, tzinfo=UTC)


def test_the_snapshot_day_is_the_date_in_the_property_time_zone_not_in_utc(world: World) -> None:
    """23:30 UTC is 00:30 the next day in Rome (CET, UTC+1)."""
    world.clock.instant = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)

    result = world.observe(night(0), night(0))

    assert result.snapshot_date_first == date(2026, 3, 16)
    assert world.stored(date(2026, 3, 16), night(0)) is not None
    assert world.stored(date(2026, 3, 15), night(0)) is None
    assert snapshot_of(world, night(0), date(2026, 3, 16)).as_of_at == world.clock.instant


def test_the_snapshot_day_follows_daylight_saving_time(world: World) -> None:
    # 22:30 UTC on the night Rome moves to CEST (UTC+2) is already 00:30 on the 30th
    world.clock.instant = datetime(2026, 3, 29, 22, 30, tzinfo=UTC)
    assert world.observe(night(0), night(0)).snapshot_date_first == date(2026, 3, 30)
    # the same UTC time one day earlier is still the 29th (00:30 CET on the 29th... 23:30 the 28th)
    world.clock.instant = datetime(2026, 3, 28, 22, 30, tzinfo=UTC)
    assert world.observe(night(1), night(1)).snapshot_date_first == date(2026, 3, 28)


def test_another_time_zone_gives_another_snapshot_day(world: World) -> None:
    world.tenant.property.timezone = "America/Sao_Paulo"  # UTC-3
    world.clock.instant = datetime(2026, 3, 15, 1, 30, tzinfo=UTC)  # 22:30 on the 14th there

    result = world.observe(night(0), night(0))

    assert result.snapshot_date_first == date(2026, 3, 14)


def test_a_naive_clock_is_refused_and_nothing_is_stored(world: World, db_session: Session) -> None:
    world.clock.instant = datetime(2026, 3, 15, 10, 0)  # no tzinfo

    with pytest.raises(ValueError):
        world.observe(night(0), night(1))

    assert count_snapshots(db_session) == 0


def test_the_caller_cannot_choose_the_moment_of_an_observation() -> None:
    """No as_of_at, no snapshot date: there is no way to fake a past state."""
    parameters = set(inspect.signature(ObservedSnapshotService.take_snapshot).parameters)
    init_parameters = set(inspect.signature(SnapshotServiceBase.__init__).parameters)

    assert parameters == {
        "self",
        "property_id",
        "data_source_id",
        "stay_date_start",
        "stay_date_end",
    }
    assert init_parameters == {"self", "session", "tenant", "clock"}


# --- F. idempotency, conflicts, immutability ---------------------------------------------------


def test_the_same_run_twice_is_an_idempotent_no_op(world: World, db_session: Session) -> None:
    world.book(night(0), night(2))
    first = world.observe(night(0), night(3))
    fingerprints = list(
        db_session.scalars(
            select(BookingSnapshot.content_fingerprint).order_by(BookingSnapshot.stay_date)
        )
    )

    world.clock.advance(hours=3)  # later the same local day: as_of_at differs, content does not
    second = world.observe(night(0), night(3))

    assert (first.created, first.unchanged) == (4, 0)
    assert (second.created, second.unchanged) == (0, 4)
    assert count_snapshots(db_session) == 4
    assert fingerprints == list(
        db_session.scalars(
            select(BookingSnapshot.content_fingerprint).order_by(BookingSnapshot.stay_date)
        )
    )
    assert snapshot_of(world, night(0)).as_of_at == NOW  # the first observation is kept as it was


def test_a_second_run_with_a_wider_range_only_adds_the_new_nights(
    world: World, db_session: Session
) -> None:
    world.observe(night(0), night(2))

    result = world.observe(night(1), night(4))

    assert (result.created, result.unchanged) == (2, 2)
    assert count_snapshots(db_session) == 5


def test_a_different_content_for_the_same_key_is_a_conflict_and_the_row_is_not_updated(
    world: World, db_session: Session
) -> None:
    world.observe(night(0), night(2))
    before = snapshot_of(world, night(1)).content_fingerprint

    world.book(night(1), night(2), rooms=3)  # the bookings changed after the observation

    with pytest.raises(SnapshotError) as info:
        world.observe(night(0), night(2))

    assert info.value.error_code == SnapshotErrorCode.CONFLICT
    assert info.value.code == "BOOKING_SNAPSHOT_CONFLICT"
    assert info.value.status_code == 409
    assert info.value.details == {
        "conflict_count": 1,
        "conflicts": [
            {
                "snapshot_local_date": "2026-03-15",
                "stay_date": str(night(1)),
                "existing_origin": "OBSERVED",
            }
        ],
    }
    stored = snapshot_of(world, night(1))
    assert stored.content_fingerprint == before and stored.rooms_on_books == 0  # untouched
    assert count_snapshots(db_session) == 3


def test_a_conflict_stores_nothing_of_the_run_not_even_the_new_nights(
    world: World, db_session: Session
) -> None:
    world.observe(night(0), night(1))
    world.book(night(1), night(2))  # changes night 1 only

    with pytest.raises(SnapshotError):
        world.observe(night(1), night(4))  # night 1 conflicts, 2..4 would be new

    assert count_snapshots(db_session) == 2
    assert world.stored(TODAY, night(2)) is None


def test_the_next_local_day_observes_again_without_touching_the_old_observation(
    world: World, db_session: Session
) -> None:
    world.observe(night(0), night(1))
    world.book(night(0), night(1), rooms=4)
    world.clock.advance(days=1)

    result = world.observe(night(0), night(1))

    assert (result.created, result.unchanged) == (2, 0)
    assert snapshot_of(world, night(0), TODAY).rooms_on_books == 0  # yesterday's evidence
    assert snapshot_of(world, night(0), TODAY + timedelta(days=1)).rooms_on_books == 4
    assert count_snapshots(db_session) == 4


def test_an_existing_reconstruction_of_the_same_key_blocks_an_observation_it_is_a_conflict(
    world: World, db_session: Session
) -> None:
    insert_snapshot(
        db_session,
        world.tenant,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        snapshot_local_date=TODAY,
        stay_date=night(0),
        booking_count_on_books=0,
        rooms_on_books=0,
        allocated_room_revenue_on_books=Decimal("0.00"),
        rooms_available=None,
        occupancy_on_books=None,
        adr_on_books=None,
    )

    with pytest.raises(SnapshotError) as info:
        world.observe(night(0), night(0))

    assert info.value.error_code == SnapshotErrorCode.CONFLICT
    conflicts: Any = info.value.details["conflicts"]  # type: ignore[index]
    assert conflicts[0]["existing_origin"] == "RECONSTRUCTED_APPROXIMATE"
    assert snapshot_of(world, night(0)).origin == SnapshotOrigin.RECONSTRUCTED_APPROXIMATE


def test_the_session_is_usable_after_a_conflict(world: World, db_session: Session) -> None:
    world.observe(night(0), night(0))
    world.book(night(0), night(1))
    with pytest.raises(SnapshotError):
        world.observe(night(0), night(0))

    result = world.observe(night(5), night(5))  # a different night is fine

    assert result.created == 1


# --- C. status policy through the service -----------------------------------------------------


@pytest.mark.parametrize(
    ("status", "counted"),
    [
        (BookingStatus.CONFIRMED, True),
        (BookingStatus.CHECKED_IN, True),
        (BookingStatus.CHECKED_OUT, True),
        (BookingStatus.CANCELLED, False),
        (BookingStatus.NO_SHOW, False),
    ],
)
def test_only_confirmed_checked_in_and_checked_out_bookings_are_on_the_books(
    world: World, status: BookingStatus, counted: bool
) -> None:
    world.book(night(0), night(1), status=status, rooms=2)

    world.observe(night(0), night(0))

    assert snapshot_of(world, night(0)).rooms_on_books == (2 if counted else 0)


def test_an_observation_has_no_uncertainty_even_with_a_cancelled_booking_without_a_date(
    world: World,
) -> None:
    world.book(night(0), night(1), status=BookingStatus.CANCELLED, cancelled_at=None)

    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))
    assert (row.rooms_on_books, row.uncertain_booking_count, row.uncertain_rooms) == (0, 0, 0)


# --- B/D/E through the service -----------------------------------------------------------------


def test_stay_nights_revenue_and_metrics_end_to_end(world: World) -> None:
    world.book(night(0), night(3), rooms=1, revenue="100.00")  # 33.34 / 33.33 / 33.33
    world.book(night(1), night(2), rooms=2, revenue="200.00")  # 200.00 on night 1 only
    world.set_inventory(night(0), night(2), 10)

    world.observe(night(0), night(3))

    rows = [snapshot_of(world, night(i)) for i in range(4)]
    assert [r.rooms_on_books for r in rows] == [1, 3, 1, 0]
    assert [r.booking_count_on_books for r in rows] == [1, 2, 1, 0]
    assert [r.allocated_room_revenue_on_books for r in rows] == [
        Decimal("33.34"),
        Decimal("233.33"),
        Decimal("33.33"),
        Decimal("0.00"),
    ]
    assert [r.adr_on_books for r in rows] == [
        Decimal("33.34"),
        Decimal("77.78"),
        Decimal("33.33"),
        None,
    ]
    assert [r.rooms_available for r in rows] == [10, 10, 10, None]
    assert [r.occupancy_on_books for r in rows] == [
        Decimal("10.00"),
        Decimal("30.00"),
        Decimal("10.00"),
        None,  # no inventory row for that night: unknown, not zero
    ]


def test_the_allocated_revenue_of_a_booking_sums_exactly_over_its_nights(world: World) -> None:
    world.book(night(0), night(6), revenue="100.00")

    world.observe(night(0), night(5))

    total = sum(snapshot_of(world, night(i)).allocated_room_revenue_on_books for i in range(6))
    assert total == Decimal("100.00")


def test_occupancy_over_100_percent_is_kept_not_clamped(world: World) -> None:
    world.book(night(0), night(1), rooms=45, revenue="4500.00")
    world.set_inventory(night(0), night(0), 40)

    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))
    assert (row.rooms_on_books, row.rooms_available) == (45, 40)
    assert row.occupancy_on_books == Decimal("112.50")


def test_half_full_is_fifty_percent(world: World) -> None:
    world.book(night(0), night(1), rooms=20)
    world.set_inventory(night(0), night(0), 40)

    world.observe(night(0), night(0))

    assert snapshot_of(world, night(0)).occupancy_on_books == Decimal("50.00")


def test_missing_inventory_is_null_never_a_guess(world: World) -> None:
    world.book(night(0), night(1), rooms=5)

    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))
    assert (row.rooms_available, row.occupancy_on_books) == (None, None)
    assert row.rooms_on_books == 5 and row.adr_on_books is not None  # the rest is still known


def test_zero_inventory_is_a_closed_night_and_occupancy_is_undefined(world: World) -> None:
    world.book(night(0), night(1), rooms=5)
    world.set_inventory(night(0), night(0), 0)

    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))
    assert row.rooms_available == 0  # kept as 0, which is different from NULL
    assert row.occupancy_on_books is None  # and there is no division by zero


def test_no_bookings_on_a_night_with_capacity_is_zero_percent_and_no_adr(world: World) -> None:
    world.set_inventory(night(0), night(0), 40)

    world.observe(night(0), night(0))

    row = snapshot_of(world, night(0))
    assert row.occupancy_on_books == Decimal("0.00") and row.adr_on_books is None


def test_a_later_inventory_change_does_not_alter_an_existing_observation(world: World) -> None:
    world.book(night(0), night(1), rooms=10)
    world.set_inventory(night(0), night(0), 20)
    world.observe(night(0), night(0))

    world.set_inventory(night(0), night(0), 50)  # the property re-declares its capacity
    world.commit()

    row = snapshot_of(world, night(0))
    assert (row.rooms_available, row.occupancy_on_books) == (20, Decimal("50.00"))
    # and re-running the same day is a conflict, not a silent refresh
    with pytest.raises(SnapshotError):
        world.observe(night(0), night(0))
    assert snapshot_of(world, night(0)).rooms_available == 20


def test_the_next_observation_copies_the_new_inventory(world: World) -> None:
    world.book(night(0), night(1), rooms=10)
    world.set_inventory(night(0), night(0), 20)
    world.observe(night(0), night(0))
    world.set_inventory(night(0), night(0), 50)
    world.clock.advance(days=1)

    world.observe(night(0), night(0))

    assert snapshot_of(world, night(0), TODAY + timedelta(days=1)).rooms_available == 50
    assert snapshot_of(world, night(0), TODAY).rooms_available == 20


# --- G. data source scope ----------------------------------------------------------------------


def test_bookings_of_another_data_source_of_the_same_property_are_never_added(
    world: World, factory: BookingFactory
) -> None:
    second = factory.data_source(world.tenant.property)
    world.book(night(0), night(1), rooms=2)
    world.book_in(second, night(0), night(1), rooms=7)

    world.observe(night(0), night(0))
    world.observe(night(0), night(0), data_source_id=second.id)

    own = snapshot_of(world, night(0))
    other = BookingSnapshotRepository(world.session, world.context).get_for_stay_date(
        second.id, TODAY, night(0)
    )
    assert own.rooms_on_books == 2  # not 9
    assert other is not None and other.rooms_on_books == 7


def test_the_curve_of_one_source_never_contains_rows_of_another(
    world: World, factory: BookingFactory
) -> None:
    second = factory.data_source(world.tenant.property)
    world.observe(night(0), night(0))
    world.observe(night(0), night(0), data_source_id=second.id)
    repository = BookingSnapshotRepository(world.session, world.context)

    first_curve = repository.list_curve_for_stay_date(world.tenant.data_source.id, night(0))
    second_curve = repository.list_curve_for_stay_date(second.id, night(0))

    assert len(first_curve) == len(second_curve) == 1
    assert count_snapshots(world.session) == 2


def test_inventory_of_another_property_is_not_used(world: World, factory: BookingFactory) -> None:
    other_property = factory.property(world.tenant.workspace)
    from app.modules.snapshots.repository import RoomInventoryRepository

    RoomInventoryRepository(world.session, world.context).set_for_date(
        other_property.id, night(0), rooms_available=99
    )
    world.book(night(0), night(1))

    world.observe(night(0), night(0))

    assert snapshot_of(world, night(0)).rooms_available is None


def data_source_error(world: World, data_source_id: Any, property_id: Any = None) -> SnapshotError:
    world.commit()
    with pytest.raises(SnapshotError) as info:
        ObservedSnapshotService(world.session, world.context, clock=world.clock).take_snapshot(
            property_id=property_id or world.tenant.property.id,
            data_source_id=data_source_id,
            stay_date_start=night(0),
            stay_date_end=night(1),
        )
    return info.value


@pytest.mark.parametrize("domain", [DataSourceDomain.COSTS, DataSourceDomain.LABOR])
def test_a_data_source_of_another_domain_is_refused(
    world: World, factory: BookingFactory, domain: DataSourceDomain
) -> None:
    other_domain = factory.data_source(world.tenant.property, domain)

    error = data_source_error(world, other_domain.id)

    assert error.error_code == SnapshotErrorCode.INVALID_DATA_SOURCE
    assert error.details == {"reason": "wrong_domain"}


def test_an_inactive_data_source_is_refused(world: World, db_session: Session) -> None:
    world.tenant.data_source.is_active = False

    error = data_source_error(world, world.tenant.data_source.id)

    assert error.details == {"reason": "inactive"}


def test_a_data_source_of_another_property_of_the_workspace_is_refused(
    world: World, factory: BookingFactory
) -> None:
    other_property = factory.property(world.tenant.workspace)
    foreign_source = factory.data_source(other_property)

    error = data_source_error(world, foreign_source.id)

    assert error.details == {"reason": "property_mismatch"}


def test_a_data_source_of_another_workspace_is_indistinguishable_from_an_unknown_one(
    world: World, two_tenants: tuple[Tenant, Tenant]
) -> None:
    _, foreign = two_tenants

    of_other_workspace = data_source_error(world, foreign.data_source.id)
    unknown = data_source_error(world, uuid4())

    assert (
        of_other_workspace.error_code == unknown.error_code == SnapshotErrorCode.INVALID_DATA_SOURCE
    )
    assert of_other_workspace.details == unknown.details == {"reason": "not_found"}
    assert of_other_workspace.message == unknown.message


def test_a_property_of_another_workspace_is_refused(
    world: World, two_tenants: tuple[Tenant, Tenant]
) -> None:
    _, foreign = two_tenants

    error = data_source_error(world, foreign.data_source.id, property_id=foreign.property.id)

    assert error.error_code == SnapshotErrorCode.INVALID_PROPERTY
    assert error.details == {"reason": "not_found"}


def test_an_archived_property_is_refused(world: World) -> None:
    world.tenant.property.is_active = False
    world.tenant.property.archived_at = datetime(2026, 1, 1, tzinfo=UTC)

    error = data_source_error(world, world.tenant.data_source.id)

    assert error.error_code == SnapshotErrorCode.INVALID_PROPERTY
    assert error.details == {"reason": "archived"}


def test_the_service_works_for_the_tenant_it_was_built_with_only(
    world: World, two_tenants: tuple[Tenant, Tenant], db_session: Session
) -> None:
    _, foreign = two_tenants
    world.commit()

    with pytest.raises(SnapshotError):
        ObservedSnapshotService(
            db_session, TenantContext(foreign.workspace.id), clock=world.clock
        ).take_snapshot(
            property_id=world.tenant.property.id,
            data_source_id=world.tenant.data_source.id,
            stay_date_start=night(0),
            stay_date_end=night(0),
        )


def test_a_failed_validation_stores_nothing(world: World, db_session: Session) -> None:
    data_source_error(world, uuid4())

    assert count_snapshots(db_session) == 0


# --- input validation --------------------------------------------------------------------------


def test_a_range_that_ends_before_it_starts_is_refused(world: World) -> None:
    with pytest.raises(SnapshotError) as info:
        world.observe(night(3), night(2))

    assert info.value.error_code == SnapshotErrorCode.INVALID_RANGE
    assert info.value.details == {"range": "stay_date", "reason": "start_after_end"}


def test_a_range_longer_than_the_limit_is_refused(world: World) -> None:
    with pytest.raises(SnapshotError) as info:
        world.observe(night(0), night(0) + timedelta(days=731))

    assert info.value.details == {"range": "stay_date", "reason": "too_long", "max_days": 731}
    assert world.observe(night(0), night(0) + timedelta(days=730)).created == 731


def test_a_datetime_is_not_accepted_where_a_date_is_expected(world: World) -> None:
    with pytest.raises(TypeError):
        world.observe(datetime(2026, 3, 20, 12, 0), night(1))


def test_a_snapshot_service_cannot_be_built_without_a_tenant_context(db_session: Session) -> None:
    with pytest.raises(TypeError):
        ObservedSnapshotService(db_session, uuid4())  # type: ignore[arg-type]

"""Tenant-scoped repositories of Gate 3: inventory, snapshots, the booking-curve read.

Nothing here computes pickup, velocity, trend, expected values or forecasts: the curve is stored
facts in order.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingStatus
from app.modules.snapshots.calculation import DayTotals, build_content
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from app.modules.snapshots.repository import (
    BookingCurvePoint,
    BookingSnapshotRepository,
    BookingStayRepository,
    NewSnapshot,
    RoomInventoryRepository,
)
from tests.support import BookingFactory, Tenant

STAY = date(2026, 4, 10)


def new_snapshot(
    tenant: Tenant,
    snapshot_date: date,
    stay_date: date = STAY,
    *,
    rooms: int = 2,
    capacity: int | None = 10,
    origin: SnapshotOrigin = SnapshotOrigin.OBSERVED,
    data_source_id: UUID | None = None,
) -> NewSnapshot:
    content = build_content(
        origin=origin,
        snapshot_local_date=snapshot_date,
        stay_date=stay_date,
        data_source_id=data_source_id or tenant.data_source.id,
        totals=DayTotals(booking_count=min(rooms, 1), rooms=rooms, revenue_cents=rooms * 10_000),
        rooms_available=capacity,
    )
    as_of = datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    return NewSnapshot.of(content, as_of)


# --- inventory ---------------------------------------------------------------------------------


def test_set_for_date_creates_then_replaces_one_row_per_night(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = RoomInventoryRepository(db_session, tenant.context)

    first = repository.set_for_date(tenant.property.id, STAY, rooms_available=20)
    second = repository.set_for_date(
        tenant.property.id, STAY, rooms_available=18, rooms_out_of_order=2
    )

    assert second.id == first.id
    assert (second.rooms_available, second.rooms_out_of_order) == (18, 2)
    assert db_session.scalar(select(func.count()).select_from(RoomInventoryDaily)) == 1


def test_zero_is_a_real_capacity_and_a_missing_night_is_none_not_zero(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = RoomInventoryRepository(db_session, tenant.context)
    repository.set_for_date(tenant.property.id, STAY, rooms_available=0)

    closed = repository.get_for_date(tenant.property.id, STAY)
    unknown = repository.get_for_date(tenant.property.id, STAY + timedelta(days=1))

    assert closed is not None and closed.rooms_available == 0
    assert unknown is None


def test_negative_room_counts_are_refused_before_the_database(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = RoomInventoryRepository(db_session, tenant.context)

    with pytest.raises(ValueError):
        repository.set_for_date(tenant.property.id, STAY, rooms_available=-1)
    with pytest.raises(ValueError):
        repository.set_for_date(tenant.property.id, STAY, rooms_available=1, rooms_out_of_order=-1)


def test_inventory_of_a_property_of_another_workspace_is_not_found(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with pytest.raises(NotFoundError):
        RoomInventoryRepository(db_session, a.context).set_for_date(
            b.property.id, STAY, rooms_available=10
        )


def test_inventory_is_invisible_to_another_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    RoomInventoryRepository(db_session, a.context).set_for_date(
        a.property.id, STAY, rooms_available=10
    )
    other = RoomInventoryRepository(db_session, b.context)

    assert other.get_for_date(a.property.id, STAY) is None
    assert other.list_for_range(a.property.id, STAY, STAY) == []


def test_list_for_range_is_inclusive_ordered_and_skips_unknown_nights(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = RoomInventoryRepository(db_session, tenant.context)
    for offset in (3, 0, 1, 5):  # inserted out of order, night +2 and +4 are missing
        repository.set_for_date(
            tenant.property.id, STAY + timedelta(days=offset), rooms_available=10 + offset
        )

    rows = repository.list_for_range(tenant.property.id, STAY, STAY + timedelta(days=4))

    assert [r.stay_date - STAY for r in rows] == [timedelta(days=d) for d in (0, 1, 3)]
    assert [r.rooms_available for r in rows] == [10, 11, 13]


# --- snapshots ---------------------------------------------------------------------------------


def test_insert_if_absent_stores_new_keys_and_never_touches_stored_ones(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    day = date(2026, 3, 1)

    inserted = repository.insert_if_absent(tenant.property.id, [new_snapshot(tenant, day, rooms=2)])
    again = repository.insert_if_absent(
        tenant.property.id,
        [new_snapshot(tenant, day, rooms=9)],  # same key, other content
    )

    assert inserted == {(day, STAY)}
    assert again == set()
    stored = repository.get_for_stay_date(tenant.data_source.id, day, STAY)
    assert stored is not None and stored.rooms_on_books == 2  # untouched


def test_insert_if_absent_persists_every_column(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    snapshot = new_snapshot(tenant, date(2026, 3, 1), rooms=3, capacity=4)
    repository.insert_if_absent(tenant.property.id, [snapshot])

    stored = repository.get_for_stay_date(tenant.data_source.id, date(2026, 3, 1), STAY)

    assert stored is not None
    assert (stored.workspace_id, stored.property_id, stored.data_source_id) == (
        tenant.workspace.id,
        tenant.property.id,
        tenant.data_source.id,
    )
    assert (stored.rooms_on_books, stored.rooms_available) == (3, 4)
    assert stored.occupancy_on_books == Decimal("75.00")
    assert stored.adr_on_books == Decimal("100.00")
    assert stored.allocated_room_revenue_on_books == Decimal("300.00")
    assert stored.calculation_version == "booking-snapshot-v1"
    assert stored.content_fingerprint == snapshot.content_fingerprint
    assert stored.as_of_at == snapshot.as_of_at and stored.origin == SnapshotOrigin.OBSERVED


def test_snapshots_are_invisible_to_another_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    day = date(2026, 3, 1)
    BookingSnapshotRepository(db_session, a.context).insert_if_absent(
        a.property.id, [new_snapshot(a, day)]
    )
    other = BookingSnapshotRepository(db_session, b.context)

    assert other.get_for_stay_date(a.data_source.id, day, STAY) is None
    assert other.list_for_snapshot_date(a.data_source.id, day) == []
    assert other.list_curve_for_stay_date(a.data_source.id, STAY) == []
    assert other.existing_in_range(a.data_source.id, day, day, STAY, STAY) == {}


def test_list_for_snapshot_date_returns_the_nights_of_that_day_in_order(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    day = date(2026, 3, 1)
    repository.insert_if_absent(
        tenant.property.id,
        [new_snapshot(tenant, day, STAY + timedelta(days=d)) for d in (2, 0, 1)]
        + [new_snapshot(tenant, date(2026, 3, 2), STAY)],
    )

    rows = repository.list_for_snapshot_date(tenant.data_source.id, day)
    limited = repository.list_for_snapshot_date(
        tenant.data_source.id, day, stay_date_from=STAY + timedelta(days=1)
    )

    assert [r.stay_date for r in rows] == [STAY + timedelta(days=d) for d in (0, 1, 2)]
    assert [r.stay_date for r in limited] == [STAY + timedelta(days=d) for d in (1, 2)]


# --- K. booking-curve access -------------------------------------------------------------------


def test_the_curve_is_ordered_by_snapshot_day_and_keeps_the_origins_apart(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    repository.insert_if_absent(
        tenant.property.id,
        [
            new_snapshot(tenant, date(2026, 3, 3), rooms=6),  # observed
            new_snapshot(
                tenant, date(2026, 3, 1), rooms=2, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
            ),
            new_snapshot(
                tenant, date(2026, 3, 2), rooms=4, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
            ),
        ],
    )

    curve = repository.list_curve_for_stay_date(tenant.data_source.id, STAY)

    assert [p.snapshot_local_date for p in curve] == [date(2026, 3, d) for d in (1, 2, 3)]
    assert [p.rooms_on_books for p in curve] == [2, 4, 6]
    assert [p.origin for p in curve] == [
        SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        SnapshotOrigin.OBSERVED,
    ]


def test_a_curve_point_carries_exactly_the_stored_facts_and_no_derived_metric(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    snapshot = new_snapshot(tenant, date(2026, 3, 1), rooms=5, capacity=10)
    repository.insert_if_absent(tenant.property.id, [snapshot])

    (point,) = repository.list_curve_for_stay_date(tenant.data_source.id, STAY)

    assert point == BookingCurvePoint(
        snapshot_local_date=date(2026, 3, 1),
        as_of_at=snapshot.as_of_at,
        rooms_on_books=5,
        allocated_room_revenue_on_books=Decimal("500.00"),
        rooms_available=10,
        occupancy_on_books=Decimal("50.00"),
        origin=SnapshotOrigin.OBSERVED,
        uncertain_rooms=0,
    )
    assert set(BookingCurvePoint.__dataclass_fields__) == {
        "snapshot_local_date",
        "as_of_at",
        "rooms_on_books",
        "allocated_room_revenue_on_books",
        "rooms_available",
        "occupancy_on_books",
        "origin",
        "uncertain_rooms",
    }  # in particular: no pickup, velocity, trend, expected, forecast


def test_the_curve_never_mixes_data_sources(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    second_source = factory.data_source(tenant.property)
    repository = BookingSnapshotRepository(db_session, tenant.context)
    day = date(2026, 3, 1)
    repository.insert_if_absent(tenant.property.id, [new_snapshot(tenant, day, rooms=2)])
    repository.insert_if_absent(
        tenant.property.id, [new_snapshot(tenant, day, rooms=7, data_source_id=second_source.id)]
    )

    first_curve = repository.list_curve_for_stay_date(tenant.data_source.id, STAY)
    second_curve = repository.list_curve_for_stay_date(second_source.id, STAY)

    assert [p.rooms_on_books for p in first_curve] == [2]
    assert [p.rooms_on_books for p in second_curve] == [7]  # never 9


def test_the_curve_can_be_limited_to_a_range_of_snapshot_days(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    repository.insert_if_absent(
        tenant.property.id, [new_snapshot(tenant, date(2026, 3, d)) for d in range(1, 8)]
    )

    curve = repository.list_curve_for_stay_date(
        tenant.data_source.id,
        STAY,
        snapshot_date_from=date(2026, 3, 3),
        snapshot_date_to=date(2026, 3, 5),
    )

    assert [p.snapshot_local_date.day for p in curve] == [3, 4, 5]


def test_existing_in_range_reports_origin_and_fingerprint(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    repository = BookingSnapshotRepository(db_session, tenant.context)
    day = date(2026, 3, 1)
    stored = new_snapshot(tenant, day, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    repository.insert_if_absent(tenant.property.id, [stored])

    found = repository.existing_in_range(tenant.data_source.id, day, day, STAY, STAY)
    outside = repository.existing_in_range(
        tenant.data_source.id, day + timedelta(days=1), day + timedelta(days=5), STAY, STAY
    )

    assert set(found) == {(day, STAY)}
    assert found[(day, STAY)].origin == SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
    assert found[(day, STAY)].content_fingerprint == stored.content_fingerprint
    assert outside == {}
    assert db_session.scalar(select(func.count()).select_from(BookingSnapshot)) == 1


# --- the bookings the calculation reads ---------------------------------------------------------


def test_stays_are_scoped_to_one_data_source_and_one_workspace(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    channel_a = factory.channel(a.property)
    channel_b = factory.channel(b.property)
    second_source = factory.data_source(a.property)
    second_job = factory.import_job(second_source)
    factory.booking(a.data_source, channel_a, a.import_job, source_record_id="A-1", rooms=1)
    factory.booking(second_source, channel_a, second_job, source_record_id="A-2", rooms=2)
    factory.booking(b.data_source, channel_b, b.import_job, source_record_id="B-1", rooms=4)

    stays = BookingStayRepository(db_session, a.context).list_stays(
        a.property.id, a.data_source.id, date(2026, 3, 1), date(2026, 3, 31)
    )
    foreign = BookingStayRepository(db_session, a.context).list_stays(
        b.property.id, b.data_source.id, date(2026, 3, 1), date(2026, 3, 31)
    )

    assert [s.rooms for s in stays] == [1]  # neither the other data source nor workspace B
    assert foreign == []


def test_stays_overlap_uses_stay_nights_so_the_check_out_day_is_outside(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    channel = factory.channel(a.property)
    for record_id, check_in, check_out in [
        ("ends-on-first", date(2026, 3, 5), date(2026, 3, 10)),  # check-out = first night: out
        ("ends-day-after", date(2026, 3, 5), date(2026, 3, 11)),  # sleeps the night of the 10th
        ("starts-on-last", date(2026, 3, 20), date(2026, 3, 22)),  # check-in = last night: in
        ("starts-after", date(2026, 3, 21), date(2026, 3, 22)),
        ("spans-all", date(2026, 3, 1), date(2026, 4, 1)),
    ]:
        factory.booking(
            a.data_source,
            channel,
            a.import_job,
            source_record_id=record_id,
            check_in=check_in,
            check_out=check_out,
        )

    stays = BookingStayRepository(db_session, a.context).list_stays(
        a.property.id, a.data_source.id, date(2026, 3, 10), date(2026, 3, 20)
    )

    assert sorted((s.check_in.day, s.check_out.day) for s in stays) == [(1, 1), (5, 11), (20, 22)]


def test_stays_can_be_filtered_by_status(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    channel = factory.channel(a.property)
    for status in BookingStatus:
        factory.booking(
            a.data_source,
            channel,
            a.import_job,
            source_record_id=status.value,
            status=status,
        )
    repository = BookingStayRepository(db_session, a.context)

    only = repository.list_stays(
        a.property.id,
        a.data_source.id,
        date(2026, 3, 1),
        date(2026, 3, 31),
        statuses=frozenset({BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN}),
    )
    everything = repository.list_stays(
        a.property.id, a.data_source.id, date(2026, 3, 1), date(2026, 3, 31)
    )

    assert {s.status for s in only} == {BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN}
    assert len(everything) == len(BookingStatus)


def test_a_repository_needs_a_tenant_context(db_session: Session) -> None:
    for repository in (RoomInventoryRepository, BookingSnapshotRepository, BookingStayRepository):
        with pytest.raises(TypeError):
            repository(db_session)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        TenantContext("not-a-uuid")  # type: ignore[arg-type]

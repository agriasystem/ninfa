"""Part U: bounded, set-based query count (no query per stay date, booking or comparable)."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
from tests.distribution_support import (
    ChannelType,
    DistributionFactory,
    DistributionWorld,
    Tenant,
    statements_of,
)

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def _build_world(
    session: Session, tenant: Tenant, factory: DistributionFactory, n_weeks: int
) -> None:
    world = DistributionWorld(session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(n_weeks)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    session.flush()


def test_the_query_count_is_bounded_and_does_not_grow_with_comparables(
    db_session: Session, factory: DistributionFactory
) -> None:
    small_tenant = factory.tenant()
    _build_world(db_session, small_tenant, factory, n_weeks=5)
    small_service = OtaDependencyService(db_session, small_tenant.context)
    with statements_of(db_session) as small_statements:
        small_service.evaluate(
            property_id=small_tenant.property.id,
            booking_data_source_id=small_tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )

    large_tenant = factory.tenant()
    _build_world(db_session, large_tenant, factory, n_weeks=6)  # the max within the season window
    large_service = OtaDependencyService(db_session, large_tenant.context)
    with statements_of(db_session) as large_statements:
        large_service.evaluate(
            property_id=large_tenant.property.id,
            booking_data_source_id=large_tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )

    assert len(small_statements) == len(large_statements)
    assert len(large_statements) <= 10


def test_no_statement_touches_bookings_more_than_once(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory, n_weeks=6)
    service = OtaDependencyService(db_session, tenant.context)
    with statements_of(db_session) as statements:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )
    touching_bookings = [sql for sql, _ in statements if " bookings " in f" {sql.lower()} "]
    assert len(touching_bookings) == 1


def test_no_statement_touches_booking_channels_more_than_once(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory, n_weeks=6)
    service = OtaDependencyService(db_session, tenant.context)
    with statements_of(db_session) as statements:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )
    touching_channels = [sql for sql, _ in statements if "booking_channels" in sql.lower()]
    assert len(touching_channels) == 1


def test_the_snapshot_read_is_one_batched_statement_not_one_per_period(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory, n_weeks=6)
    service = OtaDependencyService(db_session, tenant.context)
    with statements_of(db_session) as statements:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )
    touching_snapshots = [sql for sql, _ in statements if "booking_snapshots" in sql.lower()]
    # ONE statement for the whole batch of (as-of, stay date) keys: the target's 30 plus every
    # historical candidate's 30, never one query per period (7 periods here) or per stay date.
    assert len(touching_snapshots) == 1

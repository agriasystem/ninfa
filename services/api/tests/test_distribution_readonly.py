"""Parts S/T: the evaluation is completely read-only, and tenant-scoped."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking, BookingChannel
from app.modules.intelligence.distribution.errors import OtaDependencyError, OtaDependencyErrorCode
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.snapshots.models import BookingSnapshot
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld, Tenant

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def _build_world(session: Session, tenant: Tenant, factory: DistributionFactory) -> None:
    world = DistributionWorld(session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    session.flush()


def _counts(session: Session) -> tuple[int, int, int]:
    bookings = session.scalar(select(func.count()).select_from(Booking)) or 0
    channels = session.scalar(select(func.count()).select_from(BookingChannel)) or 0
    snapshots = session.scalar(select(func.count()).select_from(BookingSnapshot)) or 0
    return bookings, channels, snapshots


# --- S: read-only ---------------------------------------------------------------------------------


def test_bookings_are_unchanged_by_an_evaluation(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    before = [
        (row.id, row.status, row.rooms, row.room_revenue, row.channel_id)
        for row in db_session.scalars(select(Booking)).all()
    ]
    service = OtaDependencyService(db_session, tenant.context)
    service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    after = [
        (row.id, row.status, row.rooms, row.room_revenue, row.channel_id)
        for row in db_session.scalars(select(Booking)).all()
    ]
    assert before == after


def test_booking_channels_are_unchanged_by_an_evaluation(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    before = [
        (row.id, row.channel_type, row.is_verified, row.normalized_name)
        for row in db_session.scalars(select(BookingChannel)).all()
    ]
    service = OtaDependencyService(db_session, tenant.context)
    service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    after = [
        (row.id, row.channel_type, row.is_verified, row.normalized_name)
        for row in db_session.scalars(select(BookingChannel)).all()
    ]
    assert before == after
    # A NEW, real-world channel this classifier would recognise as OTA is never auto-verified
    # or reclassified: the classifier never writes, whatever it concludes in memory.
    unmapped = factory.channel(tenant.property, "Expedia")
    db_session.flush()
    assert unmapped.is_verified is False


def test_booking_snapshots_are_unchanged_by_an_evaluation(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    before = [
        (row.id, row.rooms_on_books, row.uncertain_rooms, row.origin)
        for row in db_session.scalars(select(BookingSnapshot)).all()
    ]
    service = OtaDependencyService(db_session, tenant.context)
    service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    after = [
        (row.id, row.rooms_on_books, row.uncertain_rooms, row.origin)
        for row in db_session.scalars(select(BookingSnapshot)).all()
    ]
    assert before == after


def test_an_evaluation_creates_zero_rows_anywhere(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    before = _counts(db_session)
    service = OtaDependencyService(db_session, tenant.context)
    service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    after = _counts(db_session)
    assert before == after


def test_the_service_never_commits_or_rolls_back(
    db_session: Session, factory: DistributionFactory
) -> None:
    """The service does not manage the transaction: an uncommitted change made by the caller
    before evaluating is still visible (and still uncommitted) after it, in the SAME session."""
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    channel = factory.channel(tenant.property, "Uncommitted Marker")
    assert db_session.in_transaction()
    service = OtaDependencyService(db_session, tenant.context)
    service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert db_session.in_transaction()  # the same outer transaction, never committed/rolled back
    assert db_session.get(BookingChannel, channel.id) is not None


# --- T: tenant isolation --------------------------------------------------------------------------


def test_a_tenant_context_is_mandatory(db_session: Session) -> None:
    with pytest.raises(TypeError):
        OtaDependencyService(db_session, None)  # type: ignore[arg-type]


def test_history_never_crosses_a_workspace_boundary(
    db_session: Session, factory: DistributionFactory
) -> None:
    """Two workspaces with the IDENTICAL property/data-source/channel/booking shape: evaluating
    one must never see the other's data (each independently hits INSUFFICIENT_DATA/etc, never a
    doubled sample from the other tenant)."""
    tenant_a = factory.tenant()
    tenant_b = factory.tenant()
    _build_world(db_session, tenant_a, factory)
    _build_world(db_session, tenant_b, factory)

    service_a = OtaDependencyService(db_session, tenant_a.context)
    evaluation_a = service_a.evaluate(
        property_id=tenant_a.property.id,
        booking_data_source_id=tenant_a.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation_a.sample_count == 6  # only tenant A's own 6 historical weeks


def test_a_property_of_another_workspace_cannot_be_targeted(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    other = factory.tenant()
    service = OtaDependencyService(db_session, tenant.context)
    # An unknown/foreign property id raises the same code as "not found": indistinguishable.
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=other.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )
    assert exc.value.error_code == OtaDependencyErrorCode.INVALID_PROPERTY


def test_a_data_source_never_mixes_with_another_of_the_same_property(
    db_session: Session, factory: DistributionFactory
) -> None:
    """A second BOOKINGS source of the SAME property is a genuinely different source: its
    bookings must never be pulled into an evaluation targeting the first one."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)

    other_source = factory.data_source(tenant.property)
    other_job = factory.import_job(other_source)
    # A booking on the OTHER source, in the SAME property/workspace: must not count.
    factory.booking(
        other_source,
        world.channel("Airbnb", channel_type=ChannelType.OTA, is_verified=True),
        other_job,
        source_record_id="OTHER-SOURCE-1",
        check_in=TARGET_AS_OF,
        check_out=WINDOW_END + timedelta(days=1),
        rooms=1000,
    )
    db_session.flush()

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.certain_room_nights == 30 * 30  # unaffected by the other source's booking

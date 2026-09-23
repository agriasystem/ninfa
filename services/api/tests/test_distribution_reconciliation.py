"""Part F: reconciliation of the reconstructed channel mix against the stored snapshots."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import EvaluationStatus, ReasonCode
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def test_reconstructed_rooms_equal_to_the_snapshot_reconciles(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)  # matches 20+10

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.certain_room_nights == 30 * 30


def test_target_mismatch_is_insufficient_data(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 20), (direct, 10)])
    # The stored snapshot claims 99 rooms; the real bookings only ever produce 30.
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 99)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_CHANNEL_MIX_RECONCILIATION_FAILED,)
    # No silent normalisation: the mismatched mix is never "fixed" into a room-night fact.
    assert evaluation.ota_room_nights is None


def test_a_mismatched_historical_period_is_excluded_and_counted(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    mismatched, clean = historical[0], historical[1:]
    world.snapshot_window(mismatched, mismatched, mismatched + timedelta(days=29), 999)
    for as_of in clean:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.rejected_reconciliation_count == 1
    assert mismatched not in {period.as_of_local_date for period in evaluation.comparable_periods}
    assert evaluation.sample_count == 5

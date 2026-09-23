"""Smoke tests for OtaDependencyService.evaluate (end-to-end plumbing, before the full suite)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import EvaluationStatus, ReasonCode
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld

TARGET_AS_OF = date(2026, 9, 5)  # a Saturday
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def test_a_normal_mix_is_clear(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)

    historical = _historical_saturdays(6)
    first_night = min(historical)
    world.uniform_bookings(first_night, WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)
    assert evaluation.ota_share_display == Decimal("66.67")
    assert evaluation.sample_count == 6  # weeks 1-6 back, all within the 42-day season window
    assert evaluation.calculation_fingerprint != ""


def test_structural_dependency_triggers(db_session: Session, factory: DistributionFactory) -> None:
    """A recent OTA pickup (booked only days before the target's own as-of, hence absent from
    every earlier historical cutoff by Gate 3's own temporal rule - never by carving out a
    calendar range) pushes the TARGET's own OTA share past the structural threshold, while every
    historical period (booked_at gates it out) stays at the base mix."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)

    historical = _historical_saturdays(6)
    first_night = min(historical)
    # The base mix (16 OTA / 10 DIRECT = 61.54% OTA) is certain at every cutoff, historical or
    # target: booked long ago, spans the whole combined range.
    world.uniform_bookings(first_night, WINDOW_END, [(ota, 16), (direct, 10)])
    # A recent OTA booking, booked on the target's own as-of day: certain for the TARGET's
    # cutoff, but made well after every historical as-of's own cutoff (the most recent one is a
    # full week before the target), so it never enters any historical reconciliation.
    world.booking(
        ota,
        TARGET_AS_OF,
        WINDOW_END + timedelta(days=1),
        rooms=8,
        booked_at=datetime.combine(TARGET_AS_OF, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=10),
    )

    for as_of in historical:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 26)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 34)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)
    assert evaluation.structural_condition is True
    assert evaluation.ota_share_display == Decimal("70.59")  # (16+8)/34


def test_zero_demand_is_not_applicable(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 0)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.OTA_NO_ON_BOOKS_DEMAND,)


def test_missing_one_snapshot_is_insufficient_data(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    # 29 of the 30 nights, deliberately one short.
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END - timedelta(days=1), 10)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_SNAPSHOT_WINDOW_INCOMPLETE,)

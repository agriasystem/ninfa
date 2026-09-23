"""Part I: the OTA share and direct share (exact Decimal, HALF_UP display, display never decides).

Share facts are computed and carried on the evaluation even when the historical sample later
turns out insufficient (the detector's own step order): these tests need only a valid TARGET
window, never a full historical baseline, to check the share arithmetic itself.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation, ReasonCode
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld, Tenant

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _evaluate(
    world: DistributionWorld, tenant: Tenant, factory: DistributionFactory
) -> OtaDependencyEvaluation:
    service = OtaDependencyService(world.session, tenant.context)
    return service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )


def test_all_ota_gives_a_100_percent_share(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 20)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 20)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_exact == 100
    assert evaluation.direct_share_exact == 0
    # This target's own sample is fine; the ONLY reason it stops here is the missing history.
    assert evaluation.reason_codes == (ReasonCode.OTA_COMPARABLE_SAMPLE_INSUFFICIENT,)


def test_all_direct_gives_a_0_percent_share(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(direct, 20)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 20)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_exact == 0
    assert evaluation.direct_share_exact == 100


def test_a_mixed_share_is_computed_correctly(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 30), (direct, 10)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 40)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_exact == 75  # 30/40
    assert evaluation.direct_share_exact == 25  # 10/40


def test_ota_and_direct_shares_always_sum_to_100(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 17), (direct, 13)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_exact is not None
    assert evaluation.direct_share_exact is not None
    assert evaluation.ota_share_exact + evaluation.direct_share_exact == 100


def test_the_share_is_kept_at_full_precision_not_rounded(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 2), (direct, 1)])  # 2/3
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 3)

    evaluation = _evaluate(world, tenant, factory)
    assert str(evaluation.ota_share_exact).startswith("66.6666666666666666666666666666666666666666")


def test_the_display_share_is_half_up_two_decimals(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 2), (direct, 1)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 3)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_display == Decimal("66.67")


def test_the_display_share_never_decides_the_status(
    db_session: Session, factory: DistributionFactory
) -> None:
    """69.995 displays as 70.00 (HALF_UP) but the EXACT value is still below the structural
    threshold: the decision must use the exact value, never the rounded display."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    # 13999/20000 = 69.995% exactly: rounds to 70.00 for display, but is < 70 exactly.
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(ota, 13999), (direct, 6001)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 20000)

    evaluation = _evaluate(world, tenant, factory)
    assert evaluation.ota_share_display == Decimal("70.00")
    assert evaluation.ota_share_exact is not None
    assert evaluation.ota_share_exact < 70

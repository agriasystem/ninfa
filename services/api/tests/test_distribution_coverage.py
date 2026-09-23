"""Part G: classification coverage of the target's own window. Part H: volume / no demand.

Historical 30-day windows overlap the target's own window by design (a weekly step, a 30-night
window): the shared BASE mix below spans the WHOLE combined range so every period - historical or
target - reconciles against it. Whenever a test wants the TARGET's window to differ from history
(an extra channel, extra volume), that extra booking is given a RECENT `booked_at` (on the
target's own as-of day): Gate 3's own temporal rule then excludes it from every historical
period's certain count regardless of calendar overlap, exactly as a real recent booking would be.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.modules.bookings.models import BookingChannel, BookingStatus
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import EvaluationStatus, ReasonCode
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)
RECENT_BOOKED_AT = datetime.combine(TARGET_AS_OF, time(10, 0), tzinfo=UTC)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def _base_history(world: DistributionWorld) -> tuple[BookingChannel, BookingChannel]:
    """A base OTA/DIRECT mix spanning the WHOLE combined range, plus 6 historical snapshots
    matching it exactly: every historical period reconciles regardless of what the target adds
    on top (as long as the target's addition is booked recently - see the module docstring)."""
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in historical:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    return ota, direct


def _target_snapshot(world: DistributionWorld, rooms: Mapping[date, int] | int) -> None:
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, rooms)


# --- G: classification coverage ------------------------------------------------------------------


def test_all_ota_and_direct_gives_100_percent_coverage(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _base_history(world)  # the target inherits the same base mix: 20 OTA + 10 DIRECT = 30
    _target_snapshot(world, 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classification_coverage_pct_exact == 100
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA


def test_unknown_channel_reduces_coverage(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _base_history(world)
    unknown = world.channel("Some Regional Reseller Nobody Coded")
    world.booking(
        unknown, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=20, booked_at=RECENT_BOOKED_AT
    )
    _target_snapshot(world, 50)  # base 30 + recent 20

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classification_coverage_pct_exact == 60  # 30 classified / 50 certain
    assert evaluation.unknown_room_nights == 20 * 30


def test_other_channel_reduces_coverage(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _base_history(world)
    other = world.channel("Wholesaler", channel_type=ChannelType.TOUR_OPERATOR, is_verified=True)
    world.booking(
        other, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=20, booked_at=RECENT_BOOKED_AT
    )
    _target_snapshot(world, 50)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classification_coverage_pct_exact == 60
    assert evaluation.other_room_nights == 20 * 30


def test_coverage_just_under_80_is_insufficient(
    db_session: Session, factory: DistributionFactory
) -> None:
    """classified=79, certain=100 (79 OTA/DIRECT already exist from history's base=30, plus a
    recent unknown addition): 79% coverage, strictly under 80."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota, direct = _base_history(world)
    world.booking(
        ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=49, booked_at=RECENT_BOOKED_AT
    )
    unknown = world.channel("Unmapped Reseller")
    world.booking(
        unknown, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=21, booked_at=RECENT_BOOKED_AT
    )
    _target_snapshot(world, 100)  # 30 base + 49 recent OTA + 21 recent unknown

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classification_coverage_pct_exact == 79
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW,)


def test_coverage_of_exactly_80_is_valid(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota, direct = _base_history(world)
    world.booking(
        ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=50, booked_at=RECENT_BOOKED_AT
    )
    unknown = world.channel("Unmapped Reseller")
    world.booking(
        unknown, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=20, booked_at=RECENT_BOOKED_AT
    )
    _target_snapshot(world, 100)  # 30 base + 50 recent OTA + 20 recent unknown = 80 classified/100

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classification_coverage_pct_exact == 80
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes != (ReasonCode.OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW,)


def test_coverage_denominator_is_certain_room_nights(
    db_session: Session, factory: DistributionFactory
) -> None:
    """A booking whose certainty is UNCERTAIN never enters the denominator at all (Part "NO
    SHOW / TEMPORAL UNCERTAINTY"): coverage is computed only over `certain_room_nights`."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota, direct = _base_history(world)
    # A cancelled-without-timestamp booking overlapping the window: certainly excluded, and it
    # must not silently lower the coverage denominator either.
    world.booking(
        ota,
        TARGET_AS_OF,
        WINDOW_END + timedelta(days=1),
        rooms=1000,
        status=BookingStatus.CANCELLED,
        booked_at=RECENT_BOOKED_AT,
    )
    _target_snapshot(world, 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.certain_room_nights == 30 * 30
    assert evaluation.classification_coverage_pct_exact == 100


def test_classified_denominator_of_the_ota_share_is_ota_plus_direct_only(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota, direct = _base_history(world)
    other = world.channel("Corporate", channel_type=ChannelType.CORPORATE, is_verified=True)
    world.booking(
        ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=40, booked_at=RECENT_BOOKED_AT
    )
    world.booking(
        direct, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=10, booked_at=RECENT_BOOKED_AT
    )
    world.booking(
        other, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=20, booked_at=RECENT_BOOKED_AT
    )
    _target_snapshot(world, 100)  # base 20+10 + recent 40+10+20

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classified_room_nights == 80 * 30
    assert evaluation.ota_share_exact == 75  # 60 OTA / 80 classified, OTHER never in it


# --- H: low volume / no demand -------------------------------------------------------------------


def test_19_classified_room_nights_is_insufficient(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(ota, TARGET_AS_OF, TARGET_AS_OF + timedelta(days=1), rooms=19)
    world.snapshot_window(
        TARGET_AS_OF,
        TARGET_AS_OF,
        WINDOW_END,
        {TARGET_AS_OF: 19, **{TARGET_AS_OF + timedelta(days=i): 0 for i in range(1, 30)}},
    )

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classified_room_nights == 19
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_BOOKING_VOLUME_LOW,)


def test_20_classified_room_nights_is_valid(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(ota, TARGET_AS_OF, TARGET_AS_OF + timedelta(days=1), rooms=20)
    world.snapshot_window(
        TARGET_AS_OF,
        TARGET_AS_OF,
        WINDOW_END,
        {TARGET_AS_OF: 20, **{TARGET_AS_OF + timedelta(days=i): 0 for i in range(1, 30)}},
    )

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.classified_room_nights == 20
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA  # sample<5: no history at all
    assert evaluation.reason_codes == (ReasonCode.OTA_COMPARABLE_SAMPLE_INSUFFICIENT,)
    assert evaluation.reason_codes != (ReasonCode.OTA_BOOKING_VOLUME_LOW,)

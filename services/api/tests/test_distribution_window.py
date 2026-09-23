"""Part C: the target 30-day window (exact dates, completeness, uncertainty, provenance)."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import (
    FORWARD_STAY_WINDOW_DAYS,
    EvaluationStatus,
    ReasonCode,
)
from app.modules.snapshots.models import SnapshotOrigin
from tests.distribution_support import ChannelType, DistributionFactory, DistributionWorld

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(1, n + 1)]


def _historical_only(world: DistributionWorld) -> None:
    """Six clean, fully-observed historical periods (never the target's own window)."""
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = _historical_saturdays(6)
    first_night = min(historical)
    world.uniform_bookings(first_night, WINDOW_END, [(ota, 20), (direct, 10)])
    for as_of in historical:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)


def test_the_window_is_exactly_30_stay_dates(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.window_days == FORWARD_STAY_WINDOW_DAYS == 30
    assert evaluation.window_start == TARGET_AS_OF
    assert evaluation.window_end == TARGET_AS_OF + timedelta(days=29)
    assert (evaluation.window_end - evaluation.window_start).days + 1 == 30


def test_missing_one_of_the_30_snapshots_is_insufficient_not_zero(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    # 29 snapshots: the LAST night of the window is missing entirely.
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END - timedelta(days=1), 30)

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_SNAPSHOT_WINDOW_INCOMPLETE,)
    # Never silently treated as a zero-room night: no room-night facts are even produced.
    assert evaluation.ota_room_nights is None
    assert evaluation.certain_room_nights is None


def test_an_uncertain_target_snapshot_is_insufficient_data(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    nights = [TARGET_AS_OF + timedelta(days=i) for i in range(30)]
    uncertain = dict.fromkeys(nights, 0)
    uncertain[WINDOW_END] = 2  # exactly one night is uncertain
    world.snapshot_window(
        TARGET_AS_OF,
        TARGET_AS_OF,
        WINDOW_END,
        30,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        uncertain_rooms=uncertain,
    )

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_SNAPSHOT_WINDOW_UNCERTAIN,)


def test_fully_observed_target_provenance(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)  # OBSERVED by default

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.observed_day_count == 30
    assert evaluation.reconstructed_day_count == 0
    assert evaluation.snapshot_provenance_score_exact == 100


def test_fully_reconstructed_target_provenance(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    world.snapshot_window(
        TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
    )

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.observed_day_count == 0
    assert evaluation.reconstructed_day_count == 30
    assert evaluation.snapshot_provenance_score_exact == 60


def test_mixed_target_provenance(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _historical_only(world)
    # Two disjoint sub-ranges (still exactly 30 rows total): 20 OBSERVED, 10 RECONSTRUCTED.
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, TARGET_AS_OF + timedelta(days=19), 30)
    world.snapshot_window(
        TARGET_AS_OF,
        TARGET_AS_OF + timedelta(days=20),
        WINDOW_END,
        30,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
    )

    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.observed_day_count == 20
    assert evaluation.reconstructed_day_count == 10
    # (20*100 + 10*60) / 30 = 86.666...67
    provenance = evaluation.snapshot_provenance_score_exact
    assert provenance is not None
    assert provenance.quantize(Decimal("0.01")) == Decimal("86.67")

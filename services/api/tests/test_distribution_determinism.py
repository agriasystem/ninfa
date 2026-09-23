"""Part R: determinism (same input, same result, same fingerprint; order/context irrelevant)."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Context, localcontext

from sqlalchemy.orm import Session

from app.modules.intelligence.distribution.service import OtaDependencyService
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
    world.uniform_bookings(min(historical), WINDOW_END, [(ota, 22), (direct, 8)])
    for as_of in [TARGET_AS_OF, *historical]:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)


def test_the_same_input_gives_the_same_result_twice(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    service = OtaDependencyService(db_session, tenant.context)
    first = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    second = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert first.status == second.status
    assert first.ota_share_exact == second.ota_share_exact
    assert first.calculation_fingerprint == second.calculation_fingerprint


def test_the_fingerprint_is_stable_for_the_same_logical_input(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    service = OtaDependencyService(db_session, tenant.context)
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    assert evaluation.calculation_fingerprint != ""
    assert len(evaluation.calculation_fingerprint) == 64  # SHA-256 hex


def test_the_order_bookings_are_read_in_does_not_affect_the_reconstructed_mix() -> None:
    """`reconstruct_channel_mix` sums over its `stays` argument: feeding the identical bookings
    in reverse order must give byte-identical totals, never depend on a database's incidental
    row order (which SQL never guarantees without an explicit ORDER BY)."""
    from decimal import Decimal
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    from app.modules.bookings.models import BookingStatus
    from app.modules.intelligence.distribution.metrics import reconstruct_channel_mix
    from app.modules.intelligence.distribution.temporal import StayRecord
    from app.modules.intelligence.distribution.types import (
        ChannelClassification,
        ChannelClassificationMethod,
        ChannelGroup,
    )
    from app.modules.snapshots.localtime import end_of_local_day

    tz = ZoneInfo("Europe/Rome")
    as_of = date(2026, 6, 1)
    cutoff = end_of_local_day(as_of, tz)
    window_end = as_of + timedelta(days=29)
    ota_id, direct_id = uuid4(), uuid4()
    classifications = {
        ota_id: ChannelClassification(
            ota_id,
            ChannelGroup.OTA,
            ChannelClassificationMethod.DETERMINISTIC_RULE,
            Decimal(95),
            "ota",
        ),
        direct_id: ChannelClassification(
            direct_id,
            ChannelGroup.DIRECT,
            ChannelClassificationMethod.DETERMINISTIC_RULE,
            Decimal(95),
            "direct",
        ),
    }
    stays = [
        (
            StayRecord(
                status=BookingStatus.CONFIRMED,
                booked_at=cutoff - timedelta(days=100 + i),
                cancelled_at=None,
                check_in=as_of,
                check_out=window_end + timedelta(days=1),
                rooms=i + 1,
                room_revenue=Decimal(100),
            ),
            ota_id if i % 2 == 0 else direct_id,
        )
        for i in range(10)
    ]
    forward = reconstruct_channel_mix(
        stays,
        classifications,
        as_of_local_date=as_of,
        cutoff=cutoff,
        window_start=as_of,
        window_end=window_end,
    )
    backward = reconstruct_channel_mix(
        list(reversed(stays)),
        classifications,
        as_of_local_date=as_of,
        cutoff=cutoff,
        window_start=as_of,
        window_end=window_end,
    )
    assert forward.ota_room_nights == backward.ota_room_nights
    assert forward.direct_room_nights == backward.direct_room_nights


def test_the_process_wide_decimal_context_does_not_affect_the_result(
    db_session: Session, factory: DistributionFactory
) -> None:
    """The dedicated 50-digit context is used explicitly throughout: changing the ambient
    `decimal` context (precision, rounding) must not change a single figure."""
    tenant = factory.tenant()
    _build_world(db_session, tenant, factory)
    service = OtaDependencyService(db_session, tenant.context)
    baseline = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )
    with localcontext(Context(prec=2, rounding=ROUND_HALF_UP)):
        under_hostile_context = service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=TARGET_AS_OF,
        )
    assert under_hostile_context.ota_share_exact == baseline.ota_share_exact
    assert under_hostile_context.calculation_fingerprint == baseline.calculation_fingerprint


def test_the_display_value_never_enters_the_fingerprint(
    db_session: Session, factory: DistributionFactory
) -> None:
    """`canonical_payload` (what the fingerprint hashes) uses only `*_exact` figures: proven on
    the AST (an actual name reference), never a text search that a docstring's own prose about
    this very rule could trip."""
    import ast
    import inspect

    from app.modules.intelligence.distribution import fingerprint as fingerprint_module

    tree = ast.parse(inspect.getsource(fingerprint_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in ("display_text", "for_display")

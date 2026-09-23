"""Part E: room-night allocation (pure, no database)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.modules.bookings.models import BookingStatus
from app.modules.intelligence.distribution.metrics import ChannelMixWindow, reconstruct_channel_mix
from app.modules.intelligence.distribution.temporal import StayRecord
from app.modules.intelligence.distribution.types import (
    ChannelClassification,
    ChannelClassificationMethod,
    ChannelGroup,
)
from app.modules.snapshots.localtime import end_of_local_day

TZ = ZoneInfo("Europe/Rome")
AS_OF = date(2026, 6, 1)
CUTOFF = end_of_local_day(AS_OF, TZ)
WINDOW_START = AS_OF
WINDOW_END = AS_OF + timedelta(days=29)
LONG_AGO = datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))

OTA_ID = uuid4()
DIRECT_ID = uuid4()
_RULE = ChannelClassificationMethod.DETERMINISTIC_RULE
_CLASSIFICATIONS = {
    OTA_ID: ChannelClassification(OTA_ID, ChannelGroup.OTA, _RULE, Decimal(95), "ota"),
    DIRECT_ID: ChannelClassification(DIRECT_ID, ChannelGroup.DIRECT, _RULE, Decimal(95), "direct"),
}


def _stay(
    channel_id: UUID,
    check_in: date,
    check_out: date,
    rooms: int = 1,
    revenue: Decimal | None = None,
    status: BookingStatus = BookingStatus.CONFIRMED,
) -> tuple[StayRecord, UUID]:
    nights = (check_out - check_in).days
    return (
        StayRecord(
            status=status,
            booked_at=LONG_AGO,
            cancelled_at=None,
            check_in=check_in,
            check_out=check_out,
            rooms=rooms,
            room_revenue=revenue if revenue is not None else Decimal(rooms * nights * 100),
        ),
        channel_id,
    )


def _mix(stays: list[tuple[StayRecord, UUID]]) -> ChannelMixWindow:
    return reconstruct_channel_mix(
        stays,
        _CLASSIFICATIONS,
        as_of_local_date=AS_OF,
        cutoff=CUTOFF,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )


def test_one_room_one_night_counts_as_one() -> None:
    stays = [_stay(OTA_ID, AS_OF, AS_OF + timedelta(days=1), rooms=1)]
    mix = _mix(stays)
    assert mix.ota_room_nights == 1


def test_multi_room_booking_counts_every_room_every_night() -> None:
    stays = [_stay(OTA_ID, AS_OF, AS_OF + timedelta(days=1), rooms=5)]
    mix = _mix(stays)
    assert mix.ota_room_nights == 5


def test_multi_night_booking_allocates_to_every_night() -> None:
    stays = [_stay(OTA_ID, AS_OF, AS_OF + timedelta(days=4), rooms=2)]  # 4 nights, 2 rooms each
    mix = _mix(stays)
    assert mix.ota_room_nights == 8
    for day in (AS_OF, AS_OF + timedelta(days=1), AS_OF + timedelta(days=2)):
        assert mix.by_day[day].rooms_by_group[ChannelGroup.OTA] == 2


def test_partial_overlap_with_the_window_counts_only_the_overlapping_nights() -> None:
    # Stay starts 2 nights before the window and ends 2 nights inside it: only 2 nights count.
    stays = [_stay(OTA_ID, AS_OF - timedelta(days=2), AS_OF + timedelta(days=2), rooms=3)]
    mix = _mix(stays)
    assert mix.ota_room_nights == 6  # 2 overlapping nights * 3 rooms


def test_nights_entirely_outside_the_window_are_excluded() -> None:
    stays = [_stay(OTA_ID, AS_OF - timedelta(days=10), AS_OF - timedelta(days=5), rooms=9)]
    mix = _mix(stays)
    assert mix.ota_room_nights == 0
    assert mix.direct_room_nights == 0
    assert mix.other_room_nights == 0
    assert mix.unknown_room_nights == 0


def test_totals_are_exact_deterministic_sums_across_channels() -> None:
    stays = [
        _stay(OTA_ID, AS_OF, AS_OF + timedelta(days=3), rooms=4),
        _stay(DIRECT_ID, AS_OF, AS_OF + timedelta(days=3), rooms=2),
    ]
    mix = _mix(stays)
    assert mix.ota_room_nights == 12  # 3 nights * 4 rooms
    assert mix.direct_room_nights == 6  # 3 nights * 2 rooms
    for day in (AS_OF, AS_OF + timedelta(days=1), AS_OF + timedelta(days=2)):
        assert mix.by_day[day].total_rooms == 6

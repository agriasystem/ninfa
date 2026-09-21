"""Property-local days as half-open UTC intervals, across daylight-saving changes (no database).

The cutoff of a snapshot day is the start of the NEXT local day, excluded. Consecutive days tile
the time line with no gap and no overlap, and a skipped calendar day is refused, not guessed.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.localtime import (
    end_of_local_day,
    local_date_of,
    local_day_start,
    require_existing_local_date,
)

ROME = ZoneInfo("Europe/Rome")
UTC_TZ = ZoneInfo("UTC")


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def length(day: date, tz: ZoneInfo) -> timedelta:
    return end_of_local_day(day, tz) - local_day_start(day, tz)


def test_an_ordinary_day_is_midnight_to_midnight_local() -> None:
    assert local_day_start(date(2026, 7, 10), ROME) == utc(2026, 7, 9, 22)
    assert end_of_local_day(date(2026, 7, 10), ROME) == utc(2026, 7, 10, 22)  # CEST = UTC+2
    assert local_day_start(date(2026, 1, 10), ROME) == utc(2026, 1, 9, 23)  # CET = UTC+1


def test_the_cutoff_is_the_next_midnight_excluded_not_23_59_59() -> None:
    cutoff = end_of_local_day(date(2026, 7, 10), ROME)

    assert cutoff == local_day_start(date(2026, 7, 11), ROME)
    assert local_date_of(cutoff - timedelta(microseconds=1), ROME) == date(2026, 7, 10)
    assert local_date_of(cutoff, ROME) == date(2026, 7, 11)  # the cutoff instant is next day


def test_a_utc_evening_can_already_be_the_next_day_in_the_property_time_zone() -> None:
    instant = utc(2026, 7, 10, 23, 30)

    assert local_date_of(instant, UTC_TZ) == date(2026, 7, 10)
    assert local_date_of(instant, ROME) == date(2026, 7, 11)  # 01:30 CEST
    assert local_date_of(utc(2026, 1, 10, 22, 59), ROME) == date(2026, 1, 10)
    assert local_date_of(utc(2026, 1, 10, 23, 0), ROME) == date(2026, 1, 11)


def test_local_date_needs_an_aware_instant() -> None:
    with pytest.raises(ValueError):
        local_date_of(datetime(2026, 7, 10, 12), ROME)


def test_rome_spring_forward_day_lasts_23_hours() -> None:
    assert length(date(2026, 3, 29), ROME) == timedelta(hours=23)
    assert length(date(2026, 3, 28), ROME) == timedelta(hours=24)


def test_rome_fall_back_day_lasts_25_hours() -> None:
    assert length(date(2026, 10, 25), ROME) == timedelta(hours=25)
    assert end_of_local_day(date(2026, 10, 25), ROME) == utc(2026, 10, 25, 23)


def test_midnight_that_does_not_exist_starts_the_day_at_the_jump() -> None:
    """Sao Paulo, 2018-11-04: clocks went 00:00 -> 01:00, so local midnight never happened."""
    sao_paulo = ZoneInfo("America/Sao_Paulo")

    assert local_day_start(date(2018, 11, 4), sao_paulo) == utc(2018, 11, 4, 3)
    assert local_date_of(utc(2018, 11, 4, 3), sao_paulo) == date(2018, 11, 4)
    assert local_date_of(utc(2018, 11, 4, 2, 59), sao_paulo) == date(2018, 11, 3)
    assert length(date(2018, 11, 4), sao_paulo) == timedelta(hours=23)
    assert length(date(2018, 11, 3), sao_paulo) == timedelta(hours=24)


def test_a_repeated_midnight_starts_the_day_at_its_first_occurrence() -> None:
    """Havana, 2023-11-05: 01:00 -> 00:00, so 00:00-01:00 happened twice."""
    havana = ZoneInfo("America/Havana")

    assert local_day_start(date(2023, 11, 5), havana) == utc(2023, 11, 5, 4)  # first 00:00
    assert length(date(2023, 11, 5), havana) == timedelta(hours=25)
    assert length(date(2023, 11, 4), havana) == timedelta(hours=24)


def test_a_repeated_hour_before_midnight_keeps_the_midnight_unambiguous() -> None:
    """Sao Paulo, 2018-02-18: 00:00 -> 23:00 of the 17th, so the 17th lasts 25 hours."""
    sao_paulo = ZoneInfo("America/Sao_Paulo")

    assert length(date(2018, 2, 17), sao_paulo) == timedelta(hours=25)
    assert length(date(2018, 2, 18), sao_paulo) == timedelta(hours=24)


def test_a_thirty_minute_daylight_saving_shift_is_handled() -> None:
    """Lord Howe shifts by 30 minutes: DST ends on 2026-04-05 and starts on 2026-10-04."""
    lord_howe = ZoneInfo("Australia/Lord_Howe")

    assert length(date(2026, 4, 5), lord_howe) == timedelta(hours=24, minutes=30)  # fall back 30'
    assert length(date(2026, 10, 4), lord_howe) == timedelta(hours=23, minutes=30)  # spring 30'


@pytest.mark.parametrize(
    ("zone", "first", "days"),
    [
        ("Europe/Rome", date(2026, 3, 20), 20),
        ("Europe/Rome", date(2026, 10, 20), 15),
        ("America/Sao_Paulo", date(2018, 10, 28), 12),
        ("America/Sao_Paulo", date(2018, 2, 10), 12),
        ("America/Havana", date(2023, 10, 30), 12),
        ("Australia/Lord_Howe", date(2026, 3, 30), 12),
    ],
)
def test_consecutive_days_tile_the_time_line_without_gap_or_overlap(
    zone: str, first: date, days: int
) -> None:
    tz = ZoneInfo(zone)
    previous_end = local_day_start(first, tz)

    for offset in range(days):
        day = first + timedelta(days=offset)
        assert local_day_start(day, tz) == previous_end, (zone, day)
        assert local_date_of(local_day_start(day, tz), tz) == day, (zone, day)
        previous_end = end_of_local_day(day, tz)
        assert previous_end > local_day_start(day, tz)


def test_a_calendar_day_that_never_existed_is_refused() -> None:
    """Samoa skipped 2011-12-30 entirely (the date line moved)."""
    apia = ZoneInfo("Pacific/Apia")

    with pytest.raises(SnapshotError) as info:
        end_of_local_day(date(2011, 12, 30), apia)
    assert info.value.error_code == SnapshotErrorCode.LOCAL_DATE_DOES_NOT_EXIST
    assert info.value.details == {"date": "2011-12-30", "timezone": "Pacific/Apia"}
    with pytest.raises(SnapshotError):
        require_existing_local_date(date(2011, 12, 30), apia)
    # its neighbours are fine and 12-29 ends exactly where 12-31 starts
    assert end_of_local_day(date(2011, 12, 29), apia) == local_day_start(date(2011, 12, 31), apia)
    require_existing_local_date(date(2011, 12, 31), apia)

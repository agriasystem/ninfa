"""Normalisation of mapped values into a canonical booking (no database)."""

import datetime as dt
import hashlib
from collections import defaultdict
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.bookings.errors import BookingErrorCode, RowIssue
from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.models import BookingStatus, ChannelType
from app.modules.bookings.normalization import (
    DateOrder,
    NormalizationContext,
    NormalizedBooking,
    detect_date_order,
    needs_date_format,
    needs_number_format,
    normalize_row,
    parse_amount,
)
from tests.booking_support import make_config, make_context

F = CanonicalField
UTC = dt.UTC


def good_row(**overrides: Any) -> dict[CanonicalField, Any]:
    row: dict[CanonicalField, Any] = {
        F.SOURCE_RECORD_ID: "BK-1001",
        F.BOOKED_AT: "2026-01-15 10:30",
        F.CHECK_IN: "2026-03-10",
        F.CHECK_OUT: "2026-03-13",
        F.STATUS: "Confirmed",
        F.ROOMS: "1",
        F.ROOM_REVENUE: "450.00",
        F.CHANNEL: "Booking.com",
    }
    row.update({CanonicalField(k): v for k, v in overrides.items()})
    return row


def normalize_ok(
    row: dict[CanonicalField, Any], ctx: NormalizationContext | None = None
) -> NormalizedBooking:
    booking, issues = normalize_row(row, ctx or make_context())
    assert issues == [] and booking is not None
    return booking


def issues_of(
    row: dict[CanonicalField, Any], ctx: NormalizationContext | None = None
) -> list[RowIssue]:
    booking, issues = normalize_row(row, ctx or make_context())
    assert booking is None
    return issues


def codes(issues: list[RowIssue]) -> set[tuple[str, BookingErrorCode]]:
    return {(i.field, i.code) for i in issues}


# --- date and time (tests 31-33) -------------------------------------------------------------


def test_an_aware_datetime_is_converted_to_utc() -> None:
    booking = normalize_ok(good_row(booked_at="2026-03-10T14:30:00+02:00"))

    assert booking.booked_at == dt.datetime(2026, 3, 10, 12, 30, tzinfo=UTC)
    assert booking.booked_at.utcoffset() == dt.timedelta(0)


def test_z_suffix_is_utc() -> None:
    assert normalize_ok(good_row(booked_at="2026-03-10T14:30:00Z")).booked_at == dt.datetime(
        2026, 3, 10, 14, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        ("2026-01-15 10:30", dt.datetime(2026, 1, 15, 9, 30, tzinfo=UTC)),  # CET  = UTC+1
        ("2026-07-15 10:30", dt.datetime(2026, 7, 15, 8, 30, tzinfo=UTC)),  # CEST = UTC+2
        ("2026-07-15T10:30:15", dt.datetime(2026, 7, 15, 8, 30, 15, tzinfo=UTC)),
    ],
)
def test_a_naive_datetime_is_read_in_the_property_timezone(local: str, utc: dt.datetime) -> None:
    assert normalize_ok(good_row(booked_at=local)).booked_at == utc


def test_the_property_timezone_decides_not_a_hardcoded_one() -> None:
    ctx = make_context(timezone="America/New_York")

    assert normalize_ok(good_row(booked_at="2026-01-15 10:30"), ctx).booked_at == dt.datetime(
        2026, 1, 15, 15, 30, tzinfo=UTC
    )


def test_a_date_without_time_means_local_midnight() -> None:
    assert normalize_ok(good_row(booked_at="2026-01-15")).booked_at == dt.datetime(
        2026, 1, 14, 23, 0, tzinfo=UTC
    )


def test_excel_datetimes_follow_the_same_rules_as_text() -> None:
    naive = normalize_ok(good_row(booked_at=dt.datetime(2026, 7, 15, 10, 30)))
    aware = normalize_ok(
        good_row(
            booked_at=dt.datetime(2026, 7, 15, 10, 30, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        )
    )
    only_date = normalize_ok(good_row(booked_at=dt.date(2026, 7, 15)))

    assert naive.booked_at == aware.booked_at == dt.datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
    assert only_date.booked_at == dt.datetime(2026, 7, 14, 22, 0, tzinfo=UTC)


# --- daylight-saving changes: an instant is never guessed (V1 policy) -------------------------
# Europe/Rome 2026: on 29 March the clocks jump from 02:00 to 03:00 (02:00-02:59 never happens);
# on 25 October they go back from 03:00 to 02:00 (02:00-02:59 happens twice).

NONEXISTENT = BookingErrorCode.NONEXISTENT_LOCAL_TIME
AMBIGUOUS = BookingErrorCode.AMBIGUOUS_LOCAL_TIME


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        ("2026-03-29 01:59:59", dt.datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC)),  # last CET second
        ("2026-03-29 03:00", dt.datetime(2026, 3, 29, 1, 0, tzinfo=UTC)),  # first CEST time
        ("2026-03-29T04:15:00", dt.datetime(2026, 3, 29, 2, 15, tzinfo=UTC)),
        ("2026-10-25 01:59:59", dt.datetime(2026, 10, 24, 23, 59, 59, tzinfo=UTC)),  # last before
        ("2026-10-25 03:00", dt.datetime(2026, 10, 25, 2, 0, tzinfo=UTC)),  # first after
    ],
)
def test_local_times_next_to_a_dst_change_that_identify_one_instant_are_converted(
    local: str, utc: dt.datetime
) -> None:
    assert normalize_ok(good_row(booked_at=local)).booked_at == utc


@pytest.mark.parametrize(
    "local", ["2026-03-29 02:00", "2026-03-29 02:00:00", "2026-03-29 02:30", "2026-03-29T02:59:59"]
)
def test_a_local_time_skipped_by_the_spring_change_is_rejected(local: str) -> None:
    issues = issues_of(good_row(booked_at=local))

    assert [(i.field, i.code) for i in issues] == [("booked_at", NONEXISTENT)]


@pytest.mark.parametrize(
    "local", ["2026-10-25 02:00", "2026-10-25 02:30", "2026-10-25T02:59:59", "2026-10-25 02:30:15"]
)
def test_a_local_time_repeated_by_the_autumn_change_is_rejected(local: str) -> None:
    issues = issues_of(good_row(booked_at=local))

    assert [(i.field, i.code) for i in issues] == [("booked_at", AMBIGUOUS)]


def test_the_two_codes_are_stable_strings() -> None:
    assert NONEXISTENT.value == "BOOKING_NONEXISTENT_LOCAL_TIME"
    assert AMBIGUOUS.value == "BOOKING_AMBIGUOUS_LOCAL_TIME"


def test_neither_candidate_reading_is_chosen_for_a_naive_value() -> None:
    """Not the earlier offset, not the later one, not the first, not the second occurrence."""
    for local in ("2026-03-29 02:30", "2026-10-25 02:30"):
        booking, issues = normalize_row(good_row(booked_at=local), make_context())
        assert booking is None and len(issues) == 1


def test_native_spreadsheet_datetimes_follow_the_same_rule() -> None:
    assert (F.BOOKED_AT.value, NONEXISTENT) in codes(
        issues_of(good_row(booked_at=dt.datetime(2026, 3, 29, 2, 30)))
    )
    assert (F.BOOKED_AT.value, AMBIGUOUS) in codes(
        issues_of(good_row(booked_at=dt.datetime(2026, 10, 25, 2, 30)))
    )
    assert normalize_ok(good_row(booked_at=dt.datetime(2026, 3, 29, 3, 30))).booked_at == (
        dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    )


def test_a_configured_date_pattern_does_not_bypass_the_rule() -> None:
    ctx = make_context(
        make_config(format_options={"date_formats": {"booked_at": "%d/%m/%Y %H:%M"}})
    )

    assert (F.BOOKED_AT.value, NONEXISTENT) in codes(
        issues_of(good_row(booked_at="29/03/2026 02:30"), ctx)
    )
    assert (F.BOOKED_AT.value, AMBIGUOUS) in codes(
        issues_of(good_row(booked_at="25/10/2026 02:30"), ctx)
    )
    assert normalize_ok(good_row(booked_at="25/10/2026 03:30"), ctx).booked_at == dt.datetime(
        2026, 10, 25, 2, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("value", "utc"),
    [
        # An explicit offset determines the instant even where the local time is skipped/repeated.
        ("2026-03-29T02:30:00+01:00", dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)),
        ("2026-03-29T02:30:00+02:00", dt.datetime(2026, 3, 29, 0, 30, tzinfo=UTC)),
        ("2026-10-25T02:30:00+02:00", dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)),
        ("2026-10-25T02:30:00+01:00", dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC)),
        ("2026-10-25T02:30:00Z", dt.datetime(2026, 10, 25, 2, 30, tzinfo=UTC)),
        (
            dt.datetime(2026, 10, 25, 2, 30, tzinfo=dt.timezone(dt.timedelta(hours=1))),
            dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        ),
    ],
)
def test_a_timezone_aware_value_is_always_accepted(value: object, utc: dt.datetime) -> None:
    assert normalize_ok(good_row(booked_at=value)).booked_at == utc


def test_cancelled_at_follows_the_same_rule() -> None:
    skipped = issues_of(good_row(status="Cancelled", cancelled_at="2026-03-29 02:30"))
    repeated = issues_of(good_row(status="Cancelled", cancelled_at="2026-10-25 02:30"))
    fine = normalize_ok(good_row(status="Cancelled", cancelled_at="2026-10-25 03:30"))

    assert [(i.field, i.code) for i in skipped] == [("cancelled_at", NONEXISTENT)]
    assert [(i.field, i.code) for i in repeated] == [("cancelled_at", AMBIGUOUS)]
    assert fine.cancelled_at == dt.datetime(2026, 10, 25, 2, 30, tzinfo=UTC)


def test_every_problem_is_reported_and_no_value_is_echoed() -> None:
    issues = issues_of(
        good_row(status="Cancelled", booked_at="2026-03-29 02:30", cancelled_at="2026-10-25 02:30")
    )

    assert codes(issues) == {("booked_at", NONEXISTENT), ("cancelled_at", AMBIGUOUS)}
    rendered = str([issue.to_json() for issue in issues])
    assert "2026-03-29" not in rendered and "2026-10-25" not in rendered and "02:30" not in rendered


def test_dates_without_a_time_and_calendar_dates_are_not_affected() -> None:
    # Local midnight exists in Rome even on the change days; check-in/out carry no instant at all.
    assert normalize_ok(good_row(booked_at="2026-03-29")).booked_at == dt.datetime(
        2026, 3, 28, 23, 0, tzinfo=UTC
    )
    assert normalize_ok(good_row(booked_at="2026-10-25")).booked_at == dt.datetime(
        2026, 10, 24, 22, 0, tzinfo=UTC
    )
    booking = normalize_ok(
        good_row(check_in="2026-03-29 02:30", check_out=dt.datetime(2026, 10, 25, 2, 30))
    )
    assert (booking.check_in, booking.check_out) == (dt.date(2026, 3, 29), dt.date(2026, 10, 25))


def test_the_rule_follows_the_property_timezone() -> None:
    new_york = make_context(timezone="America/New_York")  # skips 2026-03-08 02:00-02:59
    assert (F.BOOKED_AT.value, NONEXISTENT) in codes(
        issues_of(good_row(booked_at="2026-03-08 02:30"), new_york)
    )
    assert (F.BOOKED_AT.value, AMBIGUOUS) in codes(  # repeats 2026-11-01 01:00-01:59
        issues_of(good_row(booked_at="2026-11-01 01:30"), new_york)
    )
    # The same wall-clock strings are perfectly fine in Rome, on those days.
    assert normalize_ok(good_row(booked_at="2026-03-08 02:30")).booked_at == dt.datetime(
        2026, 3, 8, 1, 30, tzinfo=UTC
    )
    # A zone without daylight saving never rejects anything.
    for zone in ("UTC", "Asia/Tokyo"):
        ctx = make_context(timezone=zone)
        for local in ("2026-03-29 02:30", "2026-10-25 02:30", "2026-03-08 02:30"):
            assert normalize_ok(
                good_row(booked_at=local), ctx
            ).booked_at.utcoffset() == dt.timedelta(0)


def test_a_thirty_minute_daylight_saving_change_is_detected_too() -> None:
    lord_howe = make_context(timezone="Australia/Lord_Howe")  # shifts by 30 minutes, not 60

    assert (F.BOOKED_AT.value, NONEXISTENT) in codes(  # 2026-10-04: 02:00 -> 02:30
        issues_of(good_row(booked_at="2026-10-04 02:15"), lord_howe)
    )
    assert (F.BOOKED_AT.value, AMBIGUOUS) in codes(  # 2026-04-05: 02:00 -> 01:30
        issues_of(good_row(booked_at="2026-04-05 01:45"), lord_howe)
    )
    assert normalize_ok(good_row(booked_at="2026-10-04 02:30"), lord_howe).booked_at == dt.datetime(
        2026,
        10,
        3,
        15,
        30,
        tzinfo=UTC,  # LHDT is UTC+11:00
    )


@pytest.mark.parametrize(
    ("zone", "transitions"),
    [
        ("Europe/Rome", 2),
        ("America/New_York", 2),
        ("Europe/London", 2),
        ("Australia/Lord_Howe", 2),
        ("Pacific/Chatham", 2),
        ("Asia/Tokyo", 0),
    ],
)
def test_the_classification_matches_the_clock_for_every_minute_around_every_change(
    zone: str, transitions: int
) -> None:
    """Ground truth from the other direction: map every UTC minute to its local wall time; a
    local time reached by no instant must be rejected as skipped, by two as repeated, and by one
    must convert to exactly that instant.
    """
    tz = ZoneInfo(zone)
    ctx = make_context(timezone=zone)
    moments = utc_offset_changes(tz, 2026)
    assert len(moments) == transitions

    checked = 0
    for moment in moments:
        start = moment - dt.timedelta(hours=4)
        instants: dict[dt.datetime, list[dt.datetime]] = defaultdict(list)
        for minute in range(8 * 60):
            instant = start + dt.timedelta(minutes=minute)
            instants[instant.astimezone(tz).replace(tzinfo=None)].append(instant)
        cursor = min(instants) + dt.timedelta(hours=1)
        last = max(instants) - dt.timedelta(hours=1)
        while cursor <= last:
            booking, issues = normalize_row(good_row(booked_at=cursor.isoformat(sep=" ")), ctx)
            reached_by = instants.get(cursor, [])
            if not reached_by:
                assert codes(issues) == {("booked_at", NONEXISTENT)}, cursor
            elif len(reached_by) == 2:
                assert codes(issues) == {("booked_at", AMBIGUOUS)}, cursor
            else:
                assert booking is not None and booking.booked_at == reached_by[0], cursor
            checked += 1
            cursor += dt.timedelta(minutes=1)
    assert (checked > 0) == (transitions > 0)


def utc_offset_changes(tz: ZoneInfo, year: int) -> list[dt.datetime]:
    """The UTC instants (to 15 minutes) at which the zone's UTC offset changes during a year."""
    moment, end = dt.datetime(year, 1, 1, tzinfo=UTC), dt.datetime(year + 1, 1, 1, tzinfo=UTC)
    previous, found = moment.astimezone(tz).utcoffset(), []
    while moment < end:
        moment += dt.timedelta(minutes=15)
        offset = moment.astimezone(tz).utcoffset()
        if offset != previous:
            found.append(moment)
            previous = offset
    return found


def test_check_in_and_check_out_are_calendar_dates_without_conversion() -> None:
    late = normalize_ok(
        good_row(check_in="2026-03-10 23:30", check_out=dt.datetime(2026, 3, 12, 0, 15))
    )

    assert (late.check_in, late.check_out) == (dt.date(2026, 3, 10), dt.date(2026, 3, 12))


def test_an_aware_check_in_is_expressed_in_the_property_timezone() -> None:
    booking = normalize_ok(good_row(check_in="2026-03-10T23:30:00Z", check_out="2026-03-13"))

    assert booking.check_in == dt.date(2026, 3, 11)  # 00:30 in Rome


def test_iso_dates_with_slashes_are_year_first_and_unambiguous() -> None:
    assert normalize_ok(good_row(check_in="2026/03/10")).check_in == dt.date(2026, 3, 10)


@pytest.mark.parametrize("value", ["10/03/2026", "03/10/2026", "10.03.2026", "10-03-2026"])
def test_day_month_first_text_is_ambiguous_without_a_configured_format(value: str) -> None:
    ctx = make_context()

    assert needs_date_format(F.CHECK_IN, [value], ctx) is True
    assert (F.CHECK_IN.value, BookingErrorCode.INVALID_DATE) in codes(
        issues_of(good_row(check_in=value), ctx)
    )


def test_ambiguity_disappears_once_the_format_is_configured() -> None:
    dmy = make_context(make_config(format_options={"date_formats": {"check_in": "%d/%m/%Y"}}))
    mdy = make_context(make_config(format_options={"date_formats": {"check_in": "%m/%d/%Y"}}))

    assert needs_date_format(F.CHECK_IN, ["03/04/2026"], dmy) is False
    row = good_row(check_in="03/04/2026", check_out="2026-05-01")
    assert normalize_ok(row, dmy).check_in == dt.date(2026, 4, 3)
    assert normalize_ok(row, mdy).check_in == dt.date(2026, 3, 4)


def test_a_configured_datetime_pattern_reads_time_in_the_property_timezone() -> None:
    ctx = make_context(
        make_config(format_options={"date_formats": {"booked_at": "%d/%m/%Y %H:%M"}})
    )

    assert normalize_ok(good_row(booked_at="15/01/2026 10:30"), ctx).booked_at == dt.datetime(
        2026, 1, 15, 9, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "value",
    ["2026-02-30", "2026-13-01", "not a date", "20260310", "10 luglio 2026", 46213, 1.5, True],
)
def test_impossible_or_unrecognised_dates_are_invalid(value: Any) -> None:
    assert (F.CHECK_IN.value, BookingErrorCode.INVALID_DATE) in codes(
        issues_of(good_row(check_in=value))
    )


def test_a_pattern_that_does_not_fit_the_value_is_invalid() -> None:
    ctx = make_context(make_config(format_options={"date_formats": {"check_in": "%d/%m/%Y"}}))

    assert (F.CHECK_IN.value, BookingErrorCode.INVALID_DATE) in codes(
        issues_of(good_row(check_in="31/02/2026"), ctx)
    )
    assert (F.CHECK_IN.value, BookingErrorCode.INVALID_DATE) in codes(
        issues_of(good_row(check_in="2026-03-10"), ctx)
    )


@pytest.mark.parametrize(
    ("values", "order"),
    [
        (["13/01/2026", "05/02/2026"], DateOrder.DMY),
        (["01/13/2026", "02/05/2026"], DateOrder.MDY),
        (["01/02/2026", "03/04/2026"], DateOrder.AMBIGUOUS),
        (["13/01/2026", "01/13/2026"], DateOrder.CONFLICT),
        (["2026-01-02", "2026-03-04"], DateOrder.ISO),
        (["", "abc"], DateOrder.UNKNOWN),
    ],
)
def test_date_order_is_evidence_for_a_suggestion_only(values: list[str], order: DateOrder) -> None:
    assert detect_date_order(values) == order


# --- numbers (tests 34-35) -------------------------------------------------------------------


def amount(value: Any, **format_options: Any) -> Decimal:
    ctx = make_context(make_config(format_options=format_options))
    return parse_amount(F.ROOM_REVENUE, value, ctx)


@pytest.mark.parametrize(
    ("text", "options", "expected"),
    [
        ("1234.56", {}, "1234.56"),
        ("1234", {}, "1234.00"),
        ("0", {}, "0.00"),
        ("1,234.56", {"decimal_separator": ".", "thousands_separator": ","}, "1234.56"),
        ("1,234,567.80", {"decimal_separator": ".", "thousands_separator": ","}, "1234567.80"),
        ("1234.56", {"decimal_separator": ".", "thousands_separator": ","}, "1234.56"),
        ("1.234,56", {"decimal_separator": ",", "thousands_separator": "."}, "1234.56"),
        ("1234,56", {"decimal_separator": ","}, "1234.56"),
        ("1 234,56", {"decimal_separator": ",", "thousands_separator": " "}, "1234.56"),
        ("1 234,56", {"decimal_separator": ",", "thousands_separator": " "}, "1234.56"),
        ("120,5", {"decimal_separator": ","}, "120.50"),
    ],
)
def test_decimal_formats_are_read_only_as_configured(
    text: str, options: dict[str, Any], expected: str
) -> None:
    result = amount(text, **options)

    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert str(result) == expected


@pytest.mark.parametrize(
    ("text", "options"),
    [
        ("1.234,56", {}),  # IT grouping without configuration
        ("1,234.56", {"decimal_separator": ","}),
        ("12,34.56", {"decimal_separator": ".", "thousands_separator": ","}),  # bad grouping
        ("1.23.456,7", {"decimal_separator": ",", "thousands_separator": "."}),
        ("€ 100,00", {"decimal_separator": ","}),  # currency symbols are not accepted
        ("100 EUR", {}),
        ("abc", {}),
        ("", {}),
        ("1e3", {}),
        ("--5", {}),
    ],
)
def test_text_that_does_not_fit_the_configured_format_is_invalid(
    text: str, options: dict[str, Any]
) -> None:
    ctx = make_context(make_config(format_options=options))

    assert (F.ROOM_REVENUE.value, BookingErrorCode.INVALID_NUMBER) in codes(
        issues_of(good_row(room_revenue=text or "x"), ctx)
    )


def test_numeric_text_needs_separator_settings_when_it_could_mean_two_things() -> None:
    plain = make_context()
    configured = make_context(make_config(format_options={"decimal_separator": ","}))

    assert needs_number_format(["1.234,56"], plain) is True
    assert needs_number_format(["1,5"], plain) is True
    assert needs_number_format(["1.234.567"], plain) is True
    assert needs_number_format(["1234.56", "99", 10, 2.5, None], plain) is False
    assert needs_number_format(["1.234,56"], configured) is False


def test_no_float_reaches_the_result() -> None:
    booking = normalize_ok(
        good_row(room_revenue=0.1 + 0.2, commission_amount=12.5, commission_rate="17.5")
    )

    for value in (booking.room_revenue, booking.commission_amount, booking.commission_rate):
        assert isinstance(value, Decimal)
    assert booking.room_revenue == Decimal("0.30")  # binary float noise, exact to the cent
    assert booking.commission_rate == Decimal("17.5000")


def test_excel_floats_must_be_exact_to_the_cent() -> None:
    assert amount(123.45) == Decimal("123.45")
    assert amount(1234567.89) == Decimal("1234567.89")
    assert (F.ROOM_REVENUE.value, BookingErrorCode.AMOUNT_PRECISION) in codes(
        issues_of(good_row(room_revenue=1.234))
    )


@pytest.mark.parametrize("value", ["100.001", "0.005", 10.123, Decimal("1.999")])
def test_more_than_two_decimals_is_rejected_never_rounded(value: Any) -> None:
    assert (F.ROOM_REVENUE.value, BookingErrorCode.AMOUNT_PRECISION) in codes(
        issues_of(good_row(room_revenue=value))
    )


def test_trailing_zeros_beyond_two_decimals_are_harmless() -> None:
    assert amount("100.5000") == Decimal("100.50")
    assert amount("100.000") == Decimal("100.00")


def test_negative_amounts_are_rejected_and_zero_is_allowed() -> None:
    assert (F.ROOM_REVENUE.value, BookingErrorCode.NEGATIVE_VALUE) in codes(
        issues_of(good_row(room_revenue="-1.00"))
    )
    assert normalize_ok(good_row(room_revenue="0.00")).room_revenue == Decimal("0.00")


def test_amounts_beyond_the_column_range_are_rejected() -> None:
    assert (F.ROOM_REVENUE.value, BookingErrorCode.OUT_OF_RANGE) in codes(
        issues_of(good_row(room_revenue="10000000000.00"))
    )
    assert (F.ROOM_REVENUE.value, BookingErrorCode.OUT_OF_RANGE) in codes(
        issues_of(good_row(room_revenue="9" * 60))
    )
    assert normalize_ok(good_row(room_revenue="9999999999.99")).room_revenue == Decimal(
        "9999999999.99"
    )


def test_commission_rate_is_a_percentage_between_0_and_100() -> None:
    for ok in ("0", "15", "17.5", "100", "12.3456"):
        assert normalize_ok(good_row(commission_rate=ok)).commission_rate is not None
    assert (F.COMMISSION_RATE.value, BookingErrorCode.OUT_OF_RANGE) in codes(
        issues_of(good_row(commission_rate="100.01"))
    )
    assert (F.COMMISSION_RATE.value, BookingErrorCode.NEGATIVE_VALUE) in codes(
        issues_of(good_row(commission_rate="-1"))
    )
    assert (F.COMMISSION_RATE.value, BookingErrorCode.AMOUNT_PRECISION) in codes(
        issues_of(good_row(commission_rate="12.34567"))
    )


def test_optional_amounts_may_be_absent_or_blank() -> None:
    booking = normalize_ok(good_row(total_revenue=None, commission_amount="", commission_rate=None))

    assert (booking.total_revenue, booking.commission_amount, booking.commission_rate) == (
        None,
        None,
        None,
    )


def test_total_revenue_is_not_forced_to_exceed_room_revenue() -> None:
    booking = normalize_ok(good_row(room_revenue="500.00", total_revenue="450.00"))

    assert booking.total_revenue is not None
    assert booking.total_revenue < booking.room_revenue  # other fiscal semantics are allowed


# --- integers --------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["2", " 2 ", "2.0", "2,0", 2, 2.0, Decimal("2")])
def test_whole_numbers_are_read_from_text_and_spreadsheet_cells(value: Any) -> None:
    assert normalize_ok(good_row(rooms=value)).rooms == 2


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("0", BookingErrorCode.NOT_POSITIVE),
        (0, BookingErrorCode.NOT_POSITIVE),
        ("1.5", BookingErrorCode.INVALID_INTEGER),
        ("abc", BookingErrorCode.INVALID_INTEGER),
        ("-1", BookingErrorCode.INVALID_INTEGER),
        (True, BookingErrorCode.INVALID_INTEGER),
        (float("nan"), BookingErrorCode.INVALID_INTEGER),
        ("9999999999", BookingErrorCode.OUT_OF_RANGE),
    ],
)
def test_rooms_must_be_a_positive_integer(value: Any, code: BookingErrorCode) -> None:
    assert (F.ROOMS.value, code) in codes(issues_of(good_row(rooms=value)))


def test_guests_are_optional_but_positive_when_present() -> None:
    assert normalize_ok(good_row(guests=None)).guests is None
    assert normalize_ok(good_row(guests="3")).guests == 3
    assert (F.GUESTS.value, BookingErrorCode.NOT_POSITIVE) in codes(issues_of(good_row(guests="0")))


# --- status (tests 36-37) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "status"),
    [
        ("confirmed", BookingStatus.CONFIRMED),
        ("Confermato", BookingStatus.CONFIRMED),
        ("CONFERMATA", BookingStatus.CONFIRMED),
        ("cancelled", BookingStatus.CANCELLED),
        ("canceled", BookingStatus.CANCELLED),
        ("Annullato", BookingStatus.CANCELLED),
        ("annullata", BookingStatus.CANCELLED),
        ("Cancellato", BookingStatus.CANCELLED),
        ("cancellata", BookingStatus.CANCELLED),
        ("no show", BookingStatus.NO_SHOW),
        ("No-Show", BookingStatus.NO_SHOW),
        ("NO_SHOW", BookingStatus.NO_SHOW),
        ("checked in", BookingStatus.CHECKED_IN),
        ("Checked-In", BookingStatus.CHECKED_IN),
        ("checked out", BookingStatus.CHECKED_OUT),
        ("CHECKED-OUT", BookingStatus.CHECKED_OUT),
    ],
)
def test_common_status_synonyms_are_recognised_deterministically(
    label: str, status: BookingStatus
) -> None:
    assert normalize_ok(good_row(status=label)).status == status


@pytest.mark.parametrize(
    "label", ["Pending", "In attesa", "Provisional", "Waitlist", "OK", "0", "Modified"]
)
def test_an_unknown_status_is_never_defaulted_to_confirmed(label: str) -> None:
    issues = issues_of(good_row(status=label))

    assert [(i.field, i.code, i.value) for i in issues] == [
        ("status", BookingErrorCode.UNKNOWN_STATUS, label)
    ]


def test_the_mapping_profile_can_teach_new_status_labels_and_override_builtins() -> None:
    ctx = make_context(
        make_config(status_mapping={"In attesa": "CONFIRMED", "Confermato": "CHECKED_IN"})
    )

    assert normalize_ok(good_row(status="in attesa"), ctx).status == BookingStatus.CONFIRMED
    assert normalize_ok(good_row(status="Confermato"), ctx).status == BookingStatus.CHECKED_IN
    assert normalize_ok(good_row(status="cancelled"), ctx).status == BookingStatus.CANCELLED


def test_a_status_constant_applies_to_every_row() -> None:
    ctx = make_context(make_config(add_columns={"status": {"constant": "CONFIRMED"}}))
    row = good_row()
    del row[F.STATUS]

    assert normalize_ok(row, ctx).status == BookingStatus.CONFIRMED


# --- other fields ----------------------------------------------------------------------------


def test_rooms_and_channel_constants_apply_to_every_row() -> None:
    ctx = make_context(
        make_config(add_columns={"rooms": {"constant": 1}, "channel": {"constant": "Direct"}})
    )
    row = good_row()
    del row[F.ROOMS], row[F.CHANNEL]

    booking = normalize_ok(row, ctx)

    assert (booking.rooms, booking.channel.name, booking.channel.channel_type) == (
        1,
        "Direct",
        ChannelType.DIRECT,
    )


def test_source_record_id_is_required_and_kept_as_text() -> None:
    assert normalize_ok(good_row(source_record_id="  0012  ")).source_record_id == "0012"
    assert normalize_ok(good_row(source_record_id=12345)).source_record_id == "12345"
    assert normalize_ok(good_row(source_record_id=12345.0)).source_record_id == "12345"
    for blank in (None, "", "   "):
        assert (F.SOURCE_RECORD_ID.value, BookingErrorCode.REQUIRED_VALUE_MISSING) in codes(
            issues_of(good_row(source_record_id=blank))
        )
    assert (F.SOURCE_RECORD_ID.value, BookingErrorCode.VALUE_TOO_LONG) in codes(
        issues_of(good_row(source_record_id="x" * 256))
    )


def test_channel_is_required_and_needs_letters_or_digits() -> None:
    assert (F.CHANNEL.value, BookingErrorCode.REQUIRED_VALUE_MISSING) in codes(
        issues_of(good_row(channel=""))
    )
    assert (F.CHANNEL.value, BookingErrorCode.REQUIRED_VALUE_MISSING) in codes(
        issues_of(good_row(channel="---"))
    )
    assert (
        normalize_ok(good_row(channel="  Booking.com  ")).channel.normalized_name == "booking com"
    )


def test_optional_text_fields() -> None:
    booking = normalize_ok(good_row(room_type=" Camera Doppia ", rate_plan=None))

    assert (booking.room_type, booking.rate_plan) == ("Camera Doppia", None)
    assert (F.ROOM_TYPE.value, BookingErrorCode.VALUE_TOO_LONG) in codes(
        issues_of(good_row(room_type="x" * 201))
    )


def test_check_out_must_be_after_check_in() -> None:
    for check_out in ("2026-03-10", "2026-03-09"):
        assert (F.CHECK_OUT.value, BookingErrorCode.CHECK_OUT_NOT_AFTER_CHECK_IN) in codes(
            issues_of(good_row(check_out=check_out))
        )


def test_cancelled_at_requires_a_cancelled_status() -> None:
    assert (F.CANCELLED_AT.value, BookingErrorCode.CANCELLED_AT_WITHOUT_CANCELLED_STATUS) in codes(
        issues_of(good_row(cancelled_at="2026-02-01 09:00", status="Confirmed"))
    )
    cancelled = normalize_ok(good_row(cancelled_at="2026-02-01 09:00", status="Cancelled"))
    assert cancelled.cancelled_at == dt.datetime(2026, 2, 1, 8, 0, tzinfo=UTC)
    # A cancelled booking without a cancellation date is legitimate: many PMS do not export it.
    assert normalize_ok(good_row(status="Cancelled")).cancelled_at is None


def test_every_problem_of_a_row_is_reported_at_once_without_its_values() -> None:
    issues = issues_of(
        good_row(
            check_in="garbage",
            rooms="0",
            room_revenue="-5",
            status="Weird",
            source_record_id="",
        )
    )

    assert codes(issues) == {
        ("check_in", BookingErrorCode.INVALID_DATE),
        ("rooms", BookingErrorCode.NOT_POSITIVE),
        ("room_revenue", BookingErrorCode.NEGATIVE_VALUE),
        ("status", BookingErrorCode.UNKNOWN_STATUS),
        ("source_record_id", BookingErrorCode.REQUIRED_VALUE_MISSING),
    }
    rendered = str([i.to_json() for i in issues])
    for secret in ("garbage", "-5"):
        assert secret not in rendered
    assert "Weird" in rendered  # the categorical status label is the one value reported


# --- payload and fingerprint -----------------------------------------------------------------


def test_the_payload_round_trips_exactly() -> None:
    booking = normalize_ok(
        good_row(
            guests=2,
            total_revenue="500.00",
            commission_amount="67.50",
            commission_rate="15",
            cancelled_at="2026-02-01 09:00",
            status="Cancelled",
            room_type="Suite",
            rate_plan="BB",
        )
    )

    assert NormalizedBooking.from_payload(booking.to_payload()) == booking


def test_the_payload_holds_only_json_types() -> None:
    import json

    payload = normalize_ok(good_row(total_revenue="500")).to_payload()

    assert json.loads(json.dumps(payload)) == payload
    assert payload["room_revenue"] == "450.00" and payload["total_revenue"] == "500.00"


# The exact document that is hashed (sorted keys, compact separators). Changing the algorithm
# means changing "v" and this test: existing bookings would otherwise look modified.
FINGERPRINT_V1_DOCUMENT = (
    '{"booked_at":"2026-01-15T09:30:00+00:00","cancelled_at":null,"channel":"booking com",'
    '"check_in":"2026-03-10","check_out":"2026-03-13","commission_amount":null,'
    '"commission_rate":null,"guests":null,"rate_plan":null,"room_revenue":"450.00",'
    '"room_type":null,"rooms":1,"source_record_id":"BK-1001","status":"CONFIRMED",'
    '"total_revenue":null,"v":1}'
)


def test_fingerprint_is_the_sha256_of_a_documented_canonical_document() -> None:
    booking = normalize_ok(good_row())

    expected = hashlib.sha256(FINGERPRINT_V1_DOCUMENT.encode("utf-8")).hexdigest()

    assert booking.fingerprint() == expected
    assert len(expected) == 64
    assert booking.fingerprint() == normalize_ok(good_row()).fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "Cancelled"},
        {"room_revenue": "451.00"},
        {"check_out": "2026-03-14"},
        {"check_in": "2026-03-09"},
        {"rooms": "2"},
        {"booked_at": "2026-01-15 10:31"},
        {"channel": "Expedia"},
        {"guests": "2"},
        {"total_revenue": "500.00"},
        {"commission_amount": "10.00"},
        {"commission_rate": "10"},
        {"room_type": "Suite"},
        {"rate_plan": "BB"},
        {"source_record_id": "BK-1002"},
    ],
)
def test_any_business_change_changes_the_fingerprint(change: dict[str, Any]) -> None:
    base = normalize_ok(good_row()).fingerprint()

    assert normalize_ok(good_row(**change)).fingerprint() != base


def test_cosmetic_differences_do_not_change_the_fingerprint() -> None:
    base = normalize_ok(good_row()).fingerprint()

    same = [
        good_row(channel="BOOKING.COM"),
        good_row(channel=" booking . com "),
        good_row(room_revenue="450"),
        good_row(room_revenue=450.0),
        good_row(status="confirmed"),
        good_row(rooms="1.0"),
        good_row(booked_at="2026-01-15T10:30:00+01:00"),
        good_row(check_in="2026/03/10"),
    ]
    assert {normalize_ok(row).fingerprint() for row in same} == {base}

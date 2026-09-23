"""Part D: temporal as-of semantics, reused from Gate 3 (pure, no database).

`booking_certainty_at` is a thin, single-cutoff specialisation of Gate 3's OWN
`booking_certainty_window` (`app.modules.snapshots.aggregate`): these tests exercise it exactly
as Gate 3's own reconstruction rules already are in `test_snapshot_reconstruction_rules.py`, to
confirm the specialisation preserves the same answers, never a second algorithm.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.modules.bookings.models import BookingStatus
from app.modules.intelligence.distribution.temporal import (
    BookingCertainty,
    StayRecord,
    booking_certainty_at,
)
from app.modules.snapshots.localtime import end_of_local_day

TZ = ZoneInfo("Europe/Rome")
AS_OF = date(2026, 6, 15)
CUTOFF = end_of_local_day(AS_OF, TZ)  # start of 2026-06-16 local, in UTC


def _stay(
    *,
    status: BookingStatus = BookingStatus.CONFIRMED,
    booked_at: datetime,
    cancelled_at: datetime | None = None,
) -> StayRecord:
    return StayRecord(
        status=status,
        booked_at=booked_at,
        cancelled_at=cancelled_at,
        check_in=date(2026, 6, 15),
        check_out=date(2026, 6, 18),
        rooms=1,
        room_revenue=Decimal("100.00"),
    )


def test_booked_before_the_cutoff_is_certain() -> None:
    stay = _stay(booked_at=CUTOFF - timedelta(days=1))
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.CERTAIN


def test_booked_after_the_cutoff_is_not_on_the_books() -> None:
    stay = _stay(booked_at=CUTOFF + timedelta(seconds=1))
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.NOT_ON_BOOKS


def test_cancelled_before_the_cutoff_is_not_on_the_books() -> None:
    stay = _stay(
        status=BookingStatus.CANCELLED,
        booked_at=CUTOFF - timedelta(days=10),
        cancelled_at=CUTOFF - timedelta(days=1),
    )
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.NOT_ON_BOOKS


def test_cancelled_after_the_cutoff_is_still_counted_certain() -> None:
    """At the historical as-of, the booking had not been cancelled yet: it WAS on the books."""
    stay = _stay(
        status=BookingStatus.CANCELLED,
        booked_at=CUTOFF - timedelta(days=10),
        cancelled_at=CUTOFF + timedelta(days=1),
    )
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.CERTAIN


def test_cancelled_without_a_timestamp_is_uncertain() -> None:
    """Gate 3's own uncertainty rule, unmodified: never assumed present, never assumed absent."""
    stay = _stay(status=BookingStatus.CANCELLED, booked_at=CUTOFF - timedelta(days=10))
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.UNCERTAIN


def test_no_show_semantics_match_gate_3() -> None:
    """A NO_SHOW is certain before its own check-in date, uncertain from it on - Gate 3's own
    rule (the canonical row does not say when the no-show was recorded)."""
    before_check_in = end_of_local_day(date(2026, 6, 14), TZ)
    stay = _stay(status=BookingStatus.NO_SHOW, booked_at=before_check_in - timedelta(days=5))
    assert booking_certainty_at(stay, date(2026, 6, 14), before_check_in) == (
        BookingCertainty.CERTAIN
    )
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.UNCERTAIN


def test_checked_in_and_checked_out_are_certain_like_confirmed() -> None:
    for status in (BookingStatus.CHECKED_IN, BookingStatus.CHECKED_OUT):
        stay = _stay(status=status, booked_at=CUTOFF - timedelta(days=1))
        assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.CERTAIN


def test_timezone_cutoff_is_the_start_of_the_next_local_day() -> None:
    """A booking made in the last minute of the local as-of day is still certain; one made in
    the first minute of the NEXT local day is not - the half-open cutoff, not "23:59:59"."""
    tz = ZoneInfo("Pacific/Auckland")  # far from UTC, exercises the boundary for real
    cutoff = end_of_local_day(AS_OF, tz)
    just_before = _stay(booked_at=cutoff - timedelta(seconds=1))
    just_after = _stay(booked_at=cutoff)
    assert booking_certainty_at(just_before, AS_OF, cutoff) == BookingCertainty.CERTAIN
    assert booking_certainty_at(just_after, AS_OF, cutoff) == BookingCertainty.NOT_ON_BOOKS


def test_no_future_leakage_a_booking_made_years_later_never_counts() -> None:
    stay = _stay(booked_at=CUTOFF + timedelta(days=365 * 2))
    assert booking_certainty_at(stay, AS_OF, CUTOFF) == BookingCertainty.NOT_ON_BOOKS

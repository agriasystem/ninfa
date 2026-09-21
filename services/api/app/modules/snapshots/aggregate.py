"""Turning canonical bookings into per-night totals (pure functions, no database).

Two entry points that must never be mixed up:

* `aggregate_observed`        the bookings as they are NOW (one cutoff: the present);
* `aggregate_reconstruction`  what can be inferred about the state at EARLIER cutoffs.

The reconstruction never sees more than the canonical table keeps: the CURRENT check-in,
check-out, rooms, revenue and status of each booking, plus `booked_at` and (for cancellations)
`cancelled_at`. It has no history of changes, so every result is approximate by construction.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta

from app.modules.bookings.models import BookingStatus
from app.modules.snapshots.calculation import (
    OBSERVED_STATUSES,
    DayTotals,
    StayRecord,
    date_range,
    night_revenue_cents,
    stay_nights,
    to_cents,
)


def _overlap(stay: StayRecord, first: date, last: date) -> range:
    """Indexes (0-based nights of the stay) that fall inside [first, last]."""
    start = max(stay.check_in, first)
    end = min(stay.check_out - timedelta(days=1), last)
    if end < start:
        return range(0)
    return range((start - stay.check_in).days, (end - stay.check_in).days + 1)


def aggregate_observed(
    stays: Iterable[StayRecord], first: date, last: date
) -> dict[date, DayTotals]:
    """Totals per stay night in [first, last] from the CURRENT canonical state.

    Only CONFIRMED, CHECKED_IN and CHECKED_OUT count; CANCELLED and NO_SHOW are excluded. Every
    night of the range gets an entry, including nights with no booking at all.
    """
    days = {day: DayTotals() for day in date_range(first, last)}
    for stay in stays:
        if stay.status not in OBSERVED_STATUSES:
            continue
        nights = stay_nights(stay.check_in, stay.check_out)
        total_cents = to_cents(stay.room_revenue)
        for index in _overlap(stay, first, last):
            totals = days[stay.check_in + timedelta(days=index)]
            totals.booking_count += 1
            totals.rooms += stay.rooms
            totals.revenue_cents += night_revenue_cents(total_cents, nights, index)
    return days


def aggregate_reconstruction(
    stays: Iterable[StayRecord],
    snapshot_dates: Sequence[date],
    cutoffs: Sequence[datetime],
    first: date,
    last: date,
) -> list[list[DayTotals]]:
    """Totals per snapshot day and stay night, as far as they can be inferred today.

    `cutoffs[k]` is the exclusive end (UTC) of local snapshot day `snapshot_dates[k]`; both are
    strictly increasing. Result: `result[k][j]` is the state at the end of snapshot day k for
    stay night `first + j`.

    Rules, per booking and cutoff C (the booking must have been made: `booked_at < C`):

    * CONFIRMED / CHECKED_IN / CHECKED_OUT   on the books.
    * CANCELLED with `cancelled_at`          on the books while `C <= cancelled_at`, gone after.
    * CANCELLED without `cancelled_at` (or with one that precedes `booked_at`, which cannot be
      true)                                 UNCERTAIN: counted only in the uncertain totals,
                                             never assumed present and never assumed absent.
    * NO_SHOW                                on the books until the check-in date has started
                                             (a no-show cannot be known earlier); from the
                                             snapshot day of the check-in date on, UNCERTAIN,
                                             because the canonical row does not say when it was
                                             recorded.

    A booking's on-books window is a contiguous run of snapshot days, so it is applied as a
    difference array per stay night: O(bookings x nights + cells), not O(bookings x cells).
    """
    count = len(snapshot_dates)
    nights = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    width = len(nights)
    # certain / uncertain running deltas per stay night, indexed by snapshot day (+1 sentinel)
    d_count = [[0] * (count + 1) for _ in range(width)]
    d_rooms = [[0] * (count + 1) for _ in range(width)]
    d_cents = [[0] * (count + 1) for _ in range(width)]
    d_ucount = [[0] * (count + 1) for _ in range(width)]
    d_urooms = [[0] * (count + 1) for _ in range(width)]

    for stay in stays:
        booked = bisect_right(cutoffs, stay.booked_at)  # first day whose cutoff is after it
        if booked >= count:
            continue  # made after every cutoff of the run: not on the books at any of them
        certain, uncertain = _windows(stay, snapshot_dates, cutoffs, booked)
        total_cents = to_cents(stay.room_revenue)
        night_count = stay_nights(stay.check_in, stay.check_out)
        for index in _overlap(stay, first, last):
            column = (stay.check_in + timedelta(days=index) - first).days
            if certain[0] < certain[1]:
                cents = night_revenue_cents(total_cents, night_count, index)
                d_count[column][certain[0]] += 1
                d_count[column][certain[1]] -= 1
                d_rooms[column][certain[0]] += stay.rooms
                d_rooms[column][certain[1]] -= stay.rooms
                d_cents[column][certain[0]] += cents
                d_cents[column][certain[1]] -= cents
            if uncertain[0] < uncertain[1]:
                d_ucount[column][uncertain[0]] += 1
                d_ucount[column][uncertain[1]] -= 1
                d_urooms[column][uncertain[0]] += stay.rooms
                d_urooms[column][uncertain[1]] -= stay.rooms

    result = [[DayTotals() for _ in range(width)] for _ in range(count)]
    for column in range(width):
        running = [0, 0, 0, 0, 0]
        for k in range(count):
            running[0] += d_count[column][k]
            running[1] += d_rooms[column][k]
            running[2] += d_cents[column][k]
            running[3] += d_ucount[column][k]
            running[4] += d_urooms[column][k]
            cell = result[k][column]
            cell.booking_count, cell.rooms, cell.revenue_cents = running[0], running[1], running[2]
            cell.uncertain_booking_count, cell.uncertain_rooms = running[3], running[4]
    return result


def _windows(
    stay: StayRecord,
    snapshot_dates: Sequence[date],
    cutoffs: Sequence[datetime],
    booked: int,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """(certain, uncertain) windows of snapshot-day indexes `[from, to)` of one booking."""
    count = len(cutoffs)
    empty = (0, 0)
    if stay.status in OBSERVED_STATUSES:
        return (booked, count), empty
    if stay.status == BookingStatus.CANCELLED:
        if stay.cancelled_at is None or stay.cancelled_at < stay.booked_at:
            return empty, (booked, count)
        # On the books at every cutoff up to (and including) the cancellation instant.
        return (booked, max(booked, bisect_right(cutoffs, stay.cancelled_at))), empty
    if stay.status == BookingStatus.NO_SHOW:
        known_from = max(booked, bisect_left(snapshot_dates, stay.check_in))
        return (booked, known_from), (known_from, count)
    raise ValueError(f"unhandled booking status {stay.status!r}")

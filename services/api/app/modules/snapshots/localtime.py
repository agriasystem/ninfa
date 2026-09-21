"""Property-local calendar days as half-open UTC intervals (pure functions, no database).

A snapshot day is a *property-local* date. Its end is the half-open cutoff

    [ start of local day D , start of local day D+1 )        (next local midnight EXCLUDED)

never "23:59:59.999999": a booking made at 23:59:59.9999999 or a cancellation stamped exactly at
the next midnight must land on the right side. Consecutive days tile the time line with no gap
and no overlap, whatever the daylight-saving rules are.

Daylight saving needs no guessing here (unlike a naive timestamp found in a file, where Gate 2
refuses a nonexistent or ambiguous time): the boundary is *defined* as the earliest instant whose
local date is D.

* midnight exists once                  -> that instant;
* midnight is repeated (clocks go back at 01:00 to 00:00) -> its FIRST occurrence (fold=0): the
  local day then lasts 25 hours;
* midnight does not exist (clocks jump 00:00 -> 01:00)    -> the instant of the jump, which is
  where local date D really begins: the local day then lasts 23 hours;
* the whole date never existed (Pacific/Apia skipped 2011-12-30) -> the day has no instants and
  is refused explicitly by `require_existing_local_date`.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode


def local_day_start(day: date, tz: ZoneInfo) -> datetime:
    """The earliest instant (UTC) whose local date in `tz` is `day` or later.

    `fold=0` selects the first occurrence of a repeated midnight, and for a nonexistent midnight
    it selects the offset in force *before* the jump, which is exactly the instant of the jump.
    """
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def local_date_of(instant: datetime, tz: ZoneInfo) -> date:
    """The property-local calendar date of an absolute instant."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("an instant must be timezone-aware")
    return instant.astimezone(tz).date()


def require_existing_local_date(day: date, tz: ZoneInfo) -> None:
    """Refuse a local date on which no instant exists in `tz` (a skipped calendar day)."""
    if local_date_of(local_day_start(day, tz), tz) != day:
        raise SnapshotError(
            SnapshotErrorCode.LOCAL_DATE_DOES_NOT_EXIST,
            "The property's time zone has no such calendar day",
            details={"date": day.isoformat(), "timezone": tz.key},
        )


def end_of_local_day(day: date, tz: ZoneInfo) -> datetime:
    """Exclusive cutoff (UTC) of local day `day`: the start of the next local day."""
    require_existing_local_date(day, tz)
    return local_day_start(day + timedelta(days=1), tz)

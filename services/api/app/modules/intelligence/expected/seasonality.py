"""Calendar rules of the comparable selection (pure functions, no database).

* **Horizon**: a comparable stay date lies in `[target - 730 days, target)`. The lower bound is
  INCLUDED (exactly 730 days back is inside), the target itself and anything later are outside.
* **Weekday**: the comparable stay date has the same weekday as the target.
* **Season**: the comparable's month/day is within +-42 calendar days of the target's month/day,
  whatever the year.

Seasonal distance is a distance between two month/days, independent of the year, measured on the
two canonical calendars a year can have and taking the smaller result:

* a COMMON year (2001, 365 positions, no 29 February);
* a LEAP year (2000, 366 positions, 29 February is position 60).

On each calendar the distance is circular, `min(|a - b|, length - |a - b|)`, so 31 December and
1 January are 1 day apart. A pair that includes 29 February exists only in the leap calendar and
is measured there. The result is the true calendar distance in a common year or in a leap year,
whichever is smaller, so it is what one expects: 28 February <-> 1 March is 1, 28 February <->
29 February is 1, 29 February <-> 1 March is 1. It is an integer, symmetric and deterministic, and
uses no year, no library and no special case for the boundary of the year.
"""

from datetime import date, timedelta

HORIZON_DAYS = 730
SEASONAL_WINDOW_DAYS = 42
_LEAP_YEAR = 2000
_COMMON_YEAR = 2001
_LEAP_LENGTH = 366
_COMMON_LENGTH = 365


def _is_leap_day(day: date) -> bool:
    return day.month == 2 and day.day == 29


def _position(day: date, year: int) -> int:
    """Position 1..length of the month/day in the canonical `year` (which must have that day)."""
    return date(year, day.month, day.day).toordinal() - date(year, 1, 1).toordinal() + 1


def _circular(first: int, second: int, length: int) -> int:
    gap = abs(first - second)
    return min(gap, length - gap)


def season_position(day: date, *, leap: bool = True) -> int:
    """Position of the month/day on the canonical leap (366) or common (365) calendar."""
    if not leap and _is_leap_day(day):
        raise ValueError("29 February has no position in a common year")
    return _position(day, _LEAP_YEAR if leap else _COMMON_YEAR)


def seasonal_distance_days(first: date, second: date) -> int:
    """Distance in days between two month/days, year ignored; 0..183."""
    distance = _circular(_position(first, _LEAP_YEAR), _position(second, _LEAP_YEAR), _LEAP_LENGTH)
    if not (_is_leap_day(first) or _is_leap_day(second)):
        common = _circular(
            _position(first, _COMMON_YEAR), _position(second, _COMMON_YEAR), _COMMON_LENGTH
        )
        distance = min(distance, common)
    return distance


def within_seasonal_window(candidate: date, target: date) -> bool:
    return seasonal_distance_days(candidate, target) <= SEASONAL_WINDOW_DAYS


def same_weekday(candidate: date, target: date) -> bool:
    return candidate.weekday() == target.weekday()


def within_horizon(candidate_stay_date: date, target_stay_date: date) -> bool:
    """`target - 730 days <= candidate < target`: the lower bound is included."""
    return target_stay_date - timedelta(days=HORIZON_DAYS) <= candidate_stay_date < target_stay_date


def eligible_stay_dates(target_stay_date: date) -> list[date]:
    """Every stay date that passes horizon + weekday + season for this target, newest first.

    This is how the selection asks the database for candidates: a few dozen exact dates instead
    of a scan of the history.
    """
    oldest = target_stay_date - timedelta(days=HORIZON_DAYS)
    dates = []
    day = target_stay_date - timedelta(days=7)
    while day >= oldest:
        if within_seasonal_window(day, target_stay_date):
            dates.append(day)
        day -= timedelta(days=7)
    return dates

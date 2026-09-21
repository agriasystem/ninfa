"""Calendar rules of the comparable selection: weekday, +-42 day season, 730-day horizon.

Pure functions, no database. The season is the smaller circular distance between two month/days
on a common (365) and a leap (366) canonical calendar; a pair with 29 February uses the leap one.
"""

from datetime import date, timedelta

import pytest

from app.modules.intelligence.expected.seasonality import (
    HORIZON_DAYS,
    SEASONAL_WINDOW_DAYS,
    eligible_stay_dates,
    same_weekday,
    season_position,
    seasonal_distance_days,
    within_horizon,
    within_seasonal_window,
)

# 2026-08-15 is a Saturday.
TARGET = date(2026, 8, 15)


def test_the_constants_are_the_documented_policy() -> None:
    assert (HORIZON_DAYS, SEASONAL_WINDOW_DAYS) == (730, 42)


# --- C. same weekday --------------------------------------------------------------------------


def test_the_same_weekday_is_comparable_and_a_different_one_is_not() -> None:
    assert TARGET.weekday() == 5  # Saturday
    assert same_weekday(date(2026, 8, 8), TARGET)
    assert same_weekday(date(2025, 8, 16), TARGET)
    assert not same_weekday(date(2026, 8, 7), TARGET)  # Friday
    assert not same_weekday(date(2026, 8, 9), TARGET)  # Sunday


# --- C. seasonal window -----------------------------------------------------------------------


def test_the_season_position_ignores_the_year_on_each_canonical_calendar() -> None:
    assert season_position(date(2026, 1, 1)) == season_position(date(1999, 1, 1)) == 1
    assert season_position(date(2025, 3, 1)) == season_position(date(2024, 3, 1)) == 61  # leap
    assert season_position(date(2025, 3, 1), leap=False) == 60  # common: no 29 February
    assert season_position(date(2024, 2, 29)) == 60  # a real position of the leap calendar
    assert season_position(date(2026, 12, 31)) == 366
    assert season_position(date(2026, 12, 31), leap=False) == 365


def test_29_february_has_no_position_in_a_common_year() -> None:
    with pytest.raises(ValueError):
        season_position(date(2024, 2, 29), leap=False)


def test_a_stay_exactly_42_days_away_is_inside_the_window() -> None:
    assert seasonal_distance_days(date(2026, 7, 4), TARGET) == 42
    assert within_seasonal_window(date(2026, 7, 4), TARGET)
    assert within_seasonal_window(date(2026, 9, 26), TARGET)  # 42 days after (in another year)


def test_a_stay_43_days_away_is_outside_the_window() -> None:
    assert seasonal_distance_days(date(2025, 9, 27), TARGET) == 43
    assert not within_seasonal_window(date(2025, 9, 27), TARGET)
    assert not within_seasonal_window(date(2026, 6, 27), TARGET)  # 49 days before


def test_the_distance_is_symmetric() -> None:
    pairs = [
        (date(2026, 3, 1), date(2025, 1, 20)),
        (date(2026, 12, 20), date(2025, 1, 25)),
        (date(2024, 2, 29), date(2025, 4, 3)),
    ]
    for a, b in pairs:
        assert seasonal_distance_days(a, b) == seasonal_distance_days(b, a)


def test_31_december_and_1_january_are_adjacent_across_the_year_boundary() -> None:
    assert seasonal_distance_days(date(2025, 12, 31), date(2026, 1, 1)) == 1
    assert seasonal_distance_days(date(2025, 12, 31), date(2026, 1, 1)) == seasonal_distance_days(
        date(2026, 1, 1), date(2025, 12, 31)
    )
    # the window really wraps: a New Year's target sees late December and mid January
    new_year = date(2027, 1, 1)
    assert within_seasonal_window(date(2025, 11, 20), new_year)  # 42 days before, previous year
    assert not within_seasonal_window(date(2025, 11, 19), new_year)  # 43
    assert within_seasonal_window(date(2026, 2, 12), new_year)  # 42 days after, same year
    assert not within_seasonal_window(date(2026, 2, 13), new_year)  # 43


def test_the_naive_day_of_year_difference_would_get_the_boundary_wrong() -> None:
    december, january = date(2025, 12, 31), date(2026, 1, 1)

    assert abs(december.timetuple().tm_yday - january.timetuple().tm_yday) == 364  # naive: far away
    assert seasonal_distance_days(december, january) == 1  # circular: next to each other


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (date(2026, 2, 28), date(2026, 3, 1), 1),  # a common year: adjacent
        (date(2024, 2, 28), date(2024, 3, 1), 1),  # the year is ignored: same answer in a leap year
        (date(2024, 2, 28), date(2024, 2, 29), 1),
        (date(2024, 2, 29), date(2024, 3, 1), 1),
        (date(2024, 2, 29), date(2025, 3, 1), 1),  # different years, same month/days
        (date(2024, 2, 29), date(2025, 2, 28), 1),
        (date(2024, 2, 29), date(2028, 2, 29), 0),
        (date(2025, 12, 31), date(2026, 1, 1), 1),
        (date(2024, 2, 27), date(2024, 3, 1), 2),  # 3 days in a leap year, 2 in a common one
    ],
)
def test_the_distance_around_the_end_of_february_is_the_intuitive_one(
    first: date, second: date, expected: int
) -> None:
    assert seasonal_distance_days(first, second) == expected
    assert seasonal_distance_days(second, first) == expected  # symmetric


def test_a_leap_day_target_compares_with_the_same_season_of_other_years() -> None:
    leap_day = date(2028, 2, 29)  # a Tuesday
    assert leap_day.weekday() == 1

    assert within_seasonal_window(date(2027, 3, 30), leap_day)  # 30 days after 1 March...
    assert within_seasonal_window(date(2027, 1, 19), leap_day)  # ...and 41 before
    assert not within_seasonal_window(date(2027, 4, 20), leap_day)  # 50 days after


# --- B. horizon -------------------------------------------------------------------------------


def test_the_horizon_includes_exactly_730_days_back_and_excludes_731() -> None:
    assert within_horizon(TARGET - timedelta(days=730), TARGET)  # the limit itself: inside
    assert not within_horizon(TARGET - timedelta(days=731), TARGET)
    assert within_horizon(TARGET - timedelta(days=1), TARGET)


def test_the_target_itself_and_the_future_are_never_inside_the_horizon() -> None:
    assert not within_horizon(TARGET, TARGET)
    assert not within_horizon(TARGET + timedelta(days=1), TARGET)


def test_eligible_stay_dates_are_the_same_weekday_within_season_and_horizon_newest_first() -> None:
    dates = eligible_stay_dates(TARGET)

    assert dates == sorted(dates, reverse=True)
    assert all(same_weekday(d, TARGET) for d in dates)
    assert all(within_seasonal_window(d, TARGET) for d in dates)
    assert all(within_horizon(d, TARGET) for d in dates)
    assert dates[0] == date(2026, 8, 8) and dates[-1] == date(2024, 8, 17)
    # nothing eligible is missing: brute force over every day of the horizon
    brute = [
        TARGET - timedelta(days=offset)
        for offset in range(1, 731)
        if same_weekday(TARGET - timedelta(days=offset), TARGET)
        and within_seasonal_window(TARGET - timedelta(days=offset), TARGET)
    ]
    assert dates == brute


def test_the_oldest_eligible_date_respects_the_weekday_even_at_the_horizon_limit() -> None:
    """730 days back is a Thursday: the limit day is inside the horizon but not comparable."""
    limit = TARGET - timedelta(days=730)

    assert within_horizon(limit, TARGET) and not same_weekday(limit, TARGET)
    assert limit not in eligible_stay_dates(TARGET)
    assert TARGET - timedelta(days=728) in eligible_stay_dates(TARGET)  # 104 weeks back
    assert TARGET - timedelta(days=735) not in eligible_stay_dates(TARGET)  # 105 weeks back


def test_a_new_year_target_finds_candidates_on_both_sides_of_the_boundary() -> None:
    target = date(2027, 1, 2)  # Saturday
    assert target.weekday() == 5

    dates = eligible_stay_dates(target)

    assert date(2026, 12, 26) in dates and date(2026, 1, 3) in dates  # late Dec and early Jan
    # 730 days before 2 Jan 2027 is 2 Jan 2025: 4 Jan 2025 is inside, 28 Dec 2024 is not
    assert date(2025, 12, 27) in dates and date(2025, 1, 4) in dates
    assert date(2024, 12, 28) not in dates
    assert all(within_seasonal_window(d, target) for d in dates)


# --- the distance is the true calendar distance in a common or a leap year --------------------


def real_distance(first: date, second: date, year: int) -> int:
    """Circular distance of two month/days placed in a REAL year, by plain date arithmetic."""
    length = (date(year + 1, 1, 1) - date(year, 1, 1)).days
    gap = abs((date(year, first.month, first.day) - date(year, second.month, second.day)).days)
    return min(gap, length - gap)


def every_month_day() -> list[date]:
    return [date(2000, 1, 1) + timedelta(days=offset) for offset in range(366)]  # includes 29 Feb


def test_the_distance_is_the_smaller_real_calendar_distance_of_a_common_and_a_leap_year() -> None:
    """Checked against plain date arithmetic on real years 2001 and 2000, for EVERY pair."""
    days = every_month_day()
    for first in days:
        for second in days:
            if (first.month, first.day) == (2, 29) or (second.month, second.day) == (2, 29):
                expected = real_distance(first, second, 2000)  # only the leap year has that day
            else:
                expected = min(
                    real_distance(first, second, 2000), real_distance(first, second, 2001)
                )
            assert seasonal_distance_days(first, second) == expected, (first, second)


def test_the_distance_is_symmetric_for_every_pair_of_month_days() -> None:
    days = every_month_day()

    assert all(
        seasonal_distance_days(a, b) == seasonal_distance_days(b, a) for a in days for b in days
    )


def test_the_distance_is_an_integer_between_0_and_183_and_zero_only_for_the_same_day() -> None:
    days = every_month_day()

    for first in days:
        assert seasonal_distance_days(first, first) == 0
        for second in days:
            value = seasonal_distance_days(first, second)
            assert isinstance(value, int) and 0 <= value <= 183
            assert (value == 0) == ((first.month, first.day) == (second.month, second.day))


def test_the_distance_never_depends_on_the_year_of_either_date() -> None:
    pairs = [(2, 28, 3, 1), (12, 31, 1, 1), (1, 20, 3, 3), (7, 4, 8, 15)]

    for m1, d1, m2, d2 in pairs:
        distances = {
            seasonal_distance_days(date(y1, m1, d1), date(y2, m2, d2))
            for y1 in (2023, 2024, 2025, 2026, 2028)
            for y2 in (2023, 2024, 2025, 2027)
        }
        assert len(distances) == 1, (m1, d1, m2, d2, distances)
    # a pair with 29 February can only come from leap years, and is just as year-independent
    assert {
        seasonal_distance_days(date(y1, 2, 29), date(y2, 3, 1))
        for y1 in (2024, 2028, 2032)
        for y2 in (2023, 2024, 2025)
    } == {1}


def test_across_the_end_of_february_the_window_edge_follows_the_smaller_calendar_distance() -> None:
    # 20 January -> 3 March: 43 days in a leap year, 42 in a common one: inside (42)
    assert seasonal_distance_days(date(2025, 1, 20), date(2026, 3, 3)) == 42
    assert within_seasonal_window(date(2025, 1, 20), date(2026, 3, 3))
    # one day further: 44 and 43: outside
    assert seasonal_distance_days(date(2025, 1, 19), date(2026, 3, 3)) == 43
    assert not within_seasonal_window(date(2025, 1, 19), date(2026, 3, 3))
    # 27 February -> 10 April: 43 in a leap year, 42 in a common one
    assert within_seasonal_window(date(2025, 2, 27), date(2026, 4, 10))
    assert not within_seasonal_window(date(2025, 2, 26), date(2026, 4, 10))


def test_the_edge_is_exact_at_42_and_43_on_both_sides_of_a_target() -> None:
    target = date(2026, 6, 15)

    assert within_seasonal_window(date(2026, 6, 15) - timedelta(days=42), target)
    assert within_seasonal_window(date(2026, 6, 15) + timedelta(days=42), target)
    assert not within_seasonal_window(date(2026, 6, 15) - timedelta(days=43), target)
    assert not within_seasonal_window(date(2026, 6, 15) + timedelta(days=43), target)


def test_a_target_at_the_end_of_february_sees_the_same_season_in_every_kind_of_year() -> None:
    target = date(2026, 2, 28)  # a Saturday
    around = [
        date(2025, 3, 1),  # adjacent in a common year
        date(2024, 2, 29),  # the leap day
        date(2024, 3, 1),
        date(2025, 1, 17),  # 42 days before
        date(2025, 4, 11),  # 42 days after
    ]

    assert all(within_seasonal_window(day, target) for day in around)
    assert not within_seasonal_window(date(2025, 1, 16), target)
    assert not within_seasonal_window(date(2025, 4, 12), target)


def test_the_number_of_eligible_stay_dates_is_24_for_every_target_of_four_years() -> None:
    """Two seasonal windows of same-weekday dates inside 730 days: a stable, structural maximum."""
    counts = {
        len(eligible_stay_dates(date(2026, 1, 1) + timedelta(days=offset)))
        for offset in range(1461)
    }

    assert counts == {24}

"""Mia V3 period resolution: the MODEL names a period, the APPLICATION turns it into dates.

Pure tests (no database): the same `(argument, business date)` always resolves the same way, in the
property-local calendar the business date lives in, and anything ambiguous or out of bounds is
refused with a reason the model can act on (it asks the user) instead of silently reading a
different period than the one meant.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.ai.mia.periods import (
    PeriodArg,
    PeriodError,
    reference_calendar,
    resolve_month,
    resolve_period,
    resolve_single_day,
)

FRIDAY = date(2026, 10, 9)


def arg(**fields: object) -> PeriodArg:
    return PeriodArg.model_validate(fields)


def span(period_arg: PeriodArg, as_of: date = FRIDAY) -> tuple[date, date, str]:
    period = resolve_period(period_arg, as_of)
    return period.start, period.end, period.label


# --- relative days --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected", "label"),
    [
        ("today", date(2026, 10, 9), "oggi"),
        ("tomorrow", date(2026, 10, 10), "domani"),
        ("day_after_tomorrow", date(2026, 10, 11), "dopodomani"),
        ("yesterday", date(2026, 10, 8), "ieri"),
    ],
)
def test_relative_days_resolve_against_the_business_date(
    kind: str, expected: date, label: str
) -> None:
    assert span(arg(kind=kind)) == (expected, expected, label)


def test_days_ago_names_the_snapshot_day_without_the_model_doing_arithmetic() -> None:
    assert span(arg(kind="days_ago", days=7)) == (
        date(2026, 10, 2),
        date(2026, 10, 2),
        "7 giorni fa",
    )
    assert span(arg(kind="days_ago", days=1))[2] == "ieri"


def test_days_ahead_names_a_future_day_without_the_model_doing_calendar_arithmetic() -> None:
    assert span(arg(kind="days_ahead", days=10)) == (
        date(2026, 10, 19),
        date(2026, 10, 19),
        "tra 10 giorni",
    )
    assert span(arg(kind="days_ahead", days=14), date(2026, 12, 25))[0] == date(2027, 1, 8)
    assert resolve_single_day(arg(kind="days_ahead", days=3), FRIDAY) == date(2026, 10, 12)


def test_days_ahead_is_bounded_like_every_other_date() -> None:
    assert span(arg(kind="days_ahead", days=400))[0] == date(2027, 11, 13)
    with pytest.raises(ValidationError):
        arg(kind="days_ahead", days=401)


def test_the_business_date_not_the_server_clock_decides_what_today_is() -> None:
    assert span(arg(kind="tomorrow"), date(2027, 1, 31)) == (
        date(2027, 2, 1),
        date(2027, 2, 1),
        "domani",
    )
    assert span(arg(kind="tomorrow"), date(2028, 2, 28))[0] == date(2028, 2, 29)  # leap year


# --- explicit dates, ranges, weekdays -------------------------------------------------------------


def test_an_explicit_date_is_labelled_with_its_weekday() -> None:
    assert span(arg(kind="date", date="2026-10-10")) == (
        date(2026, 10, 10),
        date(2026, 10, 10),
        "sabato 10 ottobre",
    )


def test_an_explicit_date_in_another_year_keeps_the_year_in_its_label() -> None:
    assert span(arg(kind="date", date="2027-01-15"))[2] == "venerdì 15 gennaio 2027"


def test_a_date_range_is_inclusive_and_bounded() -> None:
    assert span(arg(kind="date_range", date="2026-10-12", end_date="2026-10-14")) == (
        date(2026, 10, 12),
        date(2026, 10, 14),
        "dal 12 ottobre al 14 ottobre",
    )
    with pytest.raises(PeriodError, match="before the start"):
        resolve_period(arg(kind="date_range", date="2026-10-14", end_date="2026-10-12"), FRIDAY)
    with pytest.raises(PeriodError, match="longer than"):
        resolve_period(arg(kind="date_range", date="2026-10-01", end_date="2026-11-15"), FRIDAY)


def test_a_date_far_from_today_is_refused_so_a_typo_d_year_is_not_read_silently() -> None:
    with pytest.raises(PeriodError, match="check the year"):
        resolve_period(arg(kind="date", date="2031-10-10"), FRIDAY)
    with pytest.raises(PeriodError, match="check the year"):
        resolve_period(arg(kind="date", date="2024-01-01"), FRIDAY)
    with pytest.raises(PeriodError, match="check the year"):
        resolve_period(
            arg(kind="date_range", date="2026-10-01", end_date="2026-10-20"), date(2028, 1, 1)
        )


def test_a_weekday_is_its_next_occurrence_counting_today() -> None:
    assert span(arg(kind="weekday", weekday="sabato"))[0] == date(2026, 10, 10)
    assert span(arg(kind="weekday", weekday="venerdi"))[0] == FRIDAY  # today IS that weekday
    assert span(arg(kind="weekday", weekday="lunedi"))[0] == date(2026, 10, 12)
    assert span(arg(kind="weekday", weekday="giovedi"))[0] == date(2026, 10, 15)


# --- windows --------------------------------------------------------------------------------------


def test_next_n_days_starts_today() -> None:
    assert span(arg(kind="next_n_days", days=7)) == (
        FRIDAY,
        date(2026, 10, 15),
        "i prossimi 7 giorni",
    )
    assert span(arg(kind="next_n_days", days=1))[2] == "oggi"


def test_weeks_run_monday_to_sunday() -> None:
    assert span(arg(kind="this_week")) == (
        date(2026, 10, 5),
        date(2026, 10, 11),
        "questa settimana",
    )
    assert span(arg(kind="next_week")) == (
        date(2026, 10, 12),
        date(2026, 10, 18),
        "la prossima settimana",
    )
    # a Sunday still belongs to the week that started on the Monday before it
    assert span(arg(kind="this_week"), date(2026, 10, 11))[0] == date(2026, 10, 5)


def test_months_are_calendar_months_across_year_boundaries() -> None:
    assert span(arg(kind="this_month")) == (date(2026, 10, 1), date(2026, 10, 31), "questo mese")
    assert span(arg(kind="next_month"), date(2026, 12, 15))[:2] == (
        date(2027, 1, 1),
        date(2027, 1, 31),
    )
    assert span(arg(kind="last_month"), date(2026, 1, 15))[:2] == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    assert span(arg(kind="last_month"), date(2028, 3, 1))[:2] == (
        date(2028, 2, 1),
        date(2028, 2, 29),
    )


# --- a single day / a single month ----------------------------------------------------------------


def test_a_comparison_day_must_be_one_day() -> None:
    assert resolve_single_day(arg(kind="yesterday"), FRIDAY) == date(2026, 10, 8)
    assert resolve_single_day(arg(kind="date", date="2026-10-01"), FRIDAY) == date(2026, 10, 1)
    with pytest.raises(PeriodError, match="single day"):
        resolve_single_day(arg(kind="this_week"), FRIDAY)
    with pytest.raises(PeriodError, match="single day"):
        resolve_single_day(arg(kind="next_n_days", days=3), FRIDAY)


def test_costs_are_read_one_calendar_month_at_a_time() -> None:
    assert resolve_month(arg(kind="this_month"), FRIDAY) == (2026, 10)
    assert resolve_month(arg(kind="last_month"), FRIDAY) == (2026, 9)
    assert resolve_month(arg(kind="date", date="2026-09-20"), FRIDAY) == (2026, 9)
    # a week that straddles two months is NOT silently read as one of them
    with pytest.raises(PeriodError, match="single month"):
        resolve_month(arg(kind="this_week"), date(2026, 10, 28))


# --- validation: the model's argument is never trusted --------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "date"},  # missing the date
        {"kind": "date_range", "date": "2026-10-10"},  # missing the end
        {"kind": "weekday"},  # missing the weekday
        {"kind": "next_n_days"},  # missing the count
        {"kind": "next_n_days", "days": 32},  # beyond a month
        {"kind": "days_ago"},
        {"kind": "days_ahead"},
        {"kind": "days_ahead", "days": 0},
        {"kind": "today", "days": 3},  # a field the kind does not use
        {"kind": "tomorrow", "date": "2026-10-10"},
        {"kind": "date", "date": "2026-10-10", "weekday": "sabato"},
        {"kind": "date", "date": "not-a-date"},
        {"kind": "fortnight"},  # unknown kind
        {"kind": "today", "tenant_id": "x"},  # extra keys are refused
        {"kind": "weekday", "weekday": "sabato", "days": 0},
    ],
)
def test_a_malformed_period_is_rejected_before_anything_runs(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PeriodArg.model_validate(fields)


# --- the reference calendar the model reads -------------------------------------------------------


def test_the_reference_calendar_lets_the_model_name_any_nearby_date_without_arithmetic() -> None:
    calendar = reference_calendar(FRIDAY)
    assert calendar["oggi"] == "2026-10-09, venerdì"
    assert calendar["ieri"] == "2026-10-08, giovedì"
    assert calendar["domani"] == "2026-10-10, sabato"
    assert calendar["dopodomani"] == "2026-10-11, domenica"
    upcoming = calendar["prossima occorrenza di ogni giorno (da oggi compreso)"]
    assert upcoming["venerdì"] == "2026-10-09"
    assert upcoming["sabato"] == "2026-10-10"
    assert upcoming["giovedì"] == "2026-10-15"
    recent = calendar["ultima occorrenza di ogni giorno (da ieri indietro)"]
    assert recent["giovedì"] == "2026-10-08"
    assert recent["venerdì"] == "2026-10-02"  # NOT today: strictly before it
    assert recent["sabato"] == "2026-10-03"
    assert calendar["questa settimana"] == "dal 2026-10-05 al 2026-10-11"
    assert calendar["prossima settimana"] == "dal 2026-10-12 al 2026-10-18"
    assert calendar["questo mese"] == "dal 2026-10-01 al 2026-10-31"

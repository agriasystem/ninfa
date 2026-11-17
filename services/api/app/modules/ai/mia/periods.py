"""Period arguments of the Mia V3 tools: what the MODEL names, what the APPLICATION resolves.

A language model is good at understanding "e il giorno dopo?" and bad at calendar arithmetic. So a
tool never takes a computed range from the model: it takes a small, closed `PeriodArg` ("domani",
"un giorno preciso", "i prossimi 7 giorni", "la prossima settimana", ...) and THIS module turns it
into concrete property-local dates, against the explicit business date the user is looking at
(`as_of`, never `date.today()`, never the server's timezone). An explicit date is accepted only
inside a bounded window around `as_of`, and a period longer than a month is refused: the model is
told why and asks the user, instead of silently getting a different period than the one meant.

`reference_calendar` is the other half: a small table of the dates around `as_of` (today, tomorrow,
each weekday's next and last occurrence, this and next week, this month), handed to the model in the
trusted turn context so that "sabato scorso" or "il 10" can be named as an exact date without any
arithmetic of its own.
"""

import datetime as dt
from calendar import monthrange
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.ai.ask_ninfa.home_period import (
    MAX_PERIOD_DAYS,
    ResolvedPeriod,
    italian_day,
    italian_weekday_day,
)

# An explicit date (or "N days ago") must lie within this many days of `as_of`: the data NINFA holds
# is the recent past and the near future, and a typo'd year must not silently read an empty period.
MAX_DATE_DISTANCE_DAYS = 400


class PeriodError(ValueError):
    """The period the model named cannot be used. The message is a short, safe, Italian-free
    explanation for the MODEL (it decides whether to ask the user); it never echoes user text."""


class PeriodKind(StrEnum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    DAY_AFTER_TOMORROW = "day_after_tomorrow"
    YESTERDAY = "yesterday"
    DAYS_AGO = "days_ago"
    DAYS_AHEAD = "days_ahead"
    DATE = "date"
    DATE_RANGE = "date_range"
    WEEKDAY = "weekday"
    NEXT_N_DAYS = "next_n_days"
    THIS_WEEK = "this_week"
    NEXT_WEEK = "next_week"
    THIS_MONTH = "this_month"
    NEXT_MONTH = "next_month"
    LAST_MONTH = "last_month"


class Weekday(StrEnum):
    """Italian weekday names without accents: the model types them, so they must be typeable."""

    LUNEDI = "lunedi"
    MARTEDI = "martedi"
    MERCOLEDI = "mercoledi"
    GIOVEDI = "giovedi"
    VENERDI = "venerdi"
    SABATO = "sabato"
    DOMENICA = "domenica"


_WEEKDAY_INDEX = {weekday: index for index, weekday in enumerate(Weekday)}
_WEEKDAY_NAMES = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")

_SINGLE_DAY_KINDS = frozenset(
    {
        PeriodKind.TODAY,
        PeriodKind.TOMORROW,
        PeriodKind.DAY_AFTER_TOMORROW,
        PeriodKind.YESTERDAY,
        PeriodKind.DAYS_AGO,
        PeriodKind.DAYS_AHEAD,
        PeriodKind.DATE,
        PeriodKind.WEEKDAY,
    }
)


class PeriodArg(BaseModel):
    """A period as the model names it. Which of the optional fields are required depends on `kind`
    (checked by the validator below, never trusted from the schema alone)."""

    model_config = ConfigDict(extra="forbid")

    kind: PeriodKind = Field(
        description=(
            "Il tipo di periodo. today/tomorrow/day_after_tomorrow/yesterday: un giorno relativo a "
            "oggi. days_ago: un giorno N giorni fa (serve 'days'). days_ahead: un giorno tra N "
            "giorni, per 'tra 10 giorni' o 'tra due settimane' (days=14): serve 'days', non "
            "calcolare tu la data. date: un giorno preciso (serve "
            "'date'). date_range: da 'date' a 'end_date' inclusi (massimo 31 giorni). weekday: la "
            "prossima occorrenza di quel giorno della settimana (serve 'weekday'). next_n_days: i "
            "prossimi N giorni a partire da oggi (serve 'days', 1-31). this_week/next_week: la "
            "settimana da lunedì a domenica. this_month/next_month/last_month: il mese di "
            "calendario."
        )
    )
    date: dt.date | None = Field(
        default=None, description="Data ISO AAAA-MM-GG. Solo per kind=date e date_range (inizio)."
    )
    end_date: dt.date | None = Field(
        default=None, description="Data ISO AAAA-MM-GG di fine. Solo per kind=date_range."
    )
    weekday: Weekday | None = Field(
        default=None, description="Giorno della settimana. Solo per kind=weekday."
    )
    days: int | None = Field(
        default=None,
        ge=1,
        le=MAX_DATE_DISTANCE_DAYS,
        description="Numero di giorni. Solo per kind=next_n_days (1-31), days_ago e days_ahead.",
    )

    @model_validator(mode="after")
    def _fields_match_kind(self) -> "PeriodArg":
        extras = {
            "date": self.date is not None,
            "end_date": self.end_date is not None,
            "weekday": self.weekday is not None,
            "days": self.days is not None,
        }
        allowed: set[str]
        match self.kind:
            case PeriodKind.DATE:
                allowed = {"date"}
            case PeriodKind.DATE_RANGE:
                allowed = {"date", "end_date"}
            case PeriodKind.WEEKDAY:
                allowed = {"weekday"}
            case PeriodKind.NEXT_N_DAYS | PeriodKind.DAYS_AGO | PeriodKind.DAYS_AHEAD:
                allowed = {"days"}
            case _:
                allowed = set()
        for name, present in extras.items():
            if present and name not in allowed:
                raise ValueError(f"'{name}' is not used by kind={self.kind.value}")
        for name in allowed:
            if not extras[name]:
                raise ValueError(f"kind={self.kind.value} requires '{name}'")
        if self.kind is PeriodKind.NEXT_N_DAYS and (self.days or 0) > MAX_PERIOD_DAYS:
            raise ValueError(f"next_n_days allows at most {MAX_PERIOD_DAYS} days")
        return self


def _label_for_date(day: dt.date, as_of: dt.date) -> str:
    base = italian_weekday_day(day)
    return base if day.year == as_of.year else f"{base} {day.year}"


def _check_distance(day: dt.date, as_of: dt.date) -> None:
    if abs((day - as_of).days) > MAX_DATE_DISTANCE_DAYS:
        raise PeriodError(
            f"the date is more than {MAX_DATE_DISTANCE_DAYS} days away from today: "
            "check the year with the user"
        )


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, month, 1), dt.date(year, month, monthrange(year, month)[1])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def resolve_period(arg: PeriodArg, as_of: dt.date) -> ResolvedPeriod:
    """The concrete nights (inclusive, property-local) the argument means. Pure and deterministic:
    the same `(arg, as_of)` always resolves the same way."""
    kind = arg.kind
    if kind is PeriodKind.TODAY:
        return ResolvedPeriod(as_of, as_of, "oggi", explicit=True)
    if kind is PeriodKind.TOMORROW:
        day = as_of + dt.timedelta(days=1)
        return ResolvedPeriod(day, day, "domani", explicit=True)
    if kind is PeriodKind.DAY_AFTER_TOMORROW:
        day = as_of + dt.timedelta(days=2)
        return ResolvedPeriod(day, day, "dopodomani", explicit=True)
    if kind is PeriodKind.YESTERDAY:
        day = as_of - dt.timedelta(days=1)
        return ResolvedPeriod(day, day, "ieri", explicit=True)
    if kind is PeriodKind.DAYS_AGO:
        assert arg.days is not None
        day = as_of - dt.timedelta(days=arg.days)
        _check_distance(day, as_of)
        label = "ieri" if arg.days == 1 else f"{arg.days} giorni fa"
        return ResolvedPeriod(day, day, label, explicit=True)
    if kind is PeriodKind.DAYS_AHEAD:
        assert arg.days is not None
        day = as_of + dt.timedelta(days=arg.days)
        _check_distance(day, as_of)
        return ResolvedPeriod(day, day, f"tra {arg.days} giorni", explicit=True)
    if kind is PeriodKind.DATE:
        assert arg.date is not None
        _check_distance(arg.date, as_of)
        return ResolvedPeriod(arg.date, arg.date, _label_for_date(arg.date, as_of), explicit=True)
    if kind is PeriodKind.DATE_RANGE:
        assert arg.date is not None and arg.end_date is not None
        if arg.end_date < arg.date:
            raise PeriodError("the end date is before the start date")
        if (arg.end_date - arg.date).days + 1 > MAX_PERIOD_DAYS:
            raise PeriodError(
                f"a range longer than {MAX_PERIOD_DAYS} days is not supported: "
                "ask for a shorter one"
            )
        _check_distance(arg.date, as_of)
        _check_distance(arg.end_date, as_of)
        label = f"dal {italian_day(arg.date)} al {italian_day(arg.end_date)}"
        return ResolvedPeriod(arg.date, arg.end_date, label, explicit=True)
    if kind is PeriodKind.WEEKDAY:
        assert arg.weekday is not None
        day = as_of + dt.timedelta(days=(_WEEKDAY_INDEX[arg.weekday] - as_of.weekday()) % 7)
        return ResolvedPeriod(day, day, italian_weekday_day(day), explicit=True)
    if kind is PeriodKind.NEXT_N_DAYS:
        assert arg.days is not None
        end = as_of + dt.timedelta(days=arg.days - 1)
        label = "oggi" if arg.days == 1 else f"i prossimi {arg.days} giorni"
        return ResolvedPeriod(as_of, end, label, explicit=True)
    if kind in (PeriodKind.THIS_WEEK, PeriodKind.NEXT_WEEK):
        monday = as_of - dt.timedelta(days=as_of.weekday())
        if kind is PeriodKind.NEXT_WEEK:
            monday += dt.timedelta(days=7)
        label = "questa settimana" if kind is PeriodKind.THIS_WEEK else "la prossima settimana"
        return ResolvedPeriod(monday, monday + dt.timedelta(days=6), label, explicit=True)
    delta = {PeriodKind.THIS_MONTH: 0, PeriodKind.NEXT_MONTH: 1, PeriodKind.LAST_MONTH: -1}[kind]
    year, month = _shift_month(as_of.year, as_of.month, delta)
    first, last = _month_bounds(year, month)
    label = {0: "questo mese", 1: "il prossimo mese", -1: "il mese scorso"}[delta]
    return ResolvedPeriod(first, last, label, explicit=True)


def resolve_single_day(arg: PeriodArg, as_of: dt.date) -> dt.date:
    """For arguments that must name exactly one day (a comparison snapshot day, a decisions day)."""
    if arg.kind not in _SINGLE_DAY_KINDS:
        raise PeriodError("a single day is required here, not a range")
    return resolve_period(arg, as_of).start


def resolve_month(arg: PeriodArg, as_of: dt.date) -> tuple[int, int]:
    """The ONE calendar month a cost period means: a month kind, or any period inside one month."""
    period = resolve_period(arg, as_of)
    if (period.start.year, period.start.month) != (period.end.year, period.end.month):
        raise PeriodError("costs are read one calendar month at a time: name a single month")
    return period.start.year, period.start.month


def _iso_with_weekday(day: dt.date) -> str:
    return f"{day.isoformat()}, {_WEEKDAY_NAMES[day.weekday()]}"


def reference_calendar(as_of: dt.date) -> dict[str, Any]:
    """The dates around `as_of`, with plain-Italian keys, for the model's trusted turn context."""
    monday = as_of - dt.timedelta(days=as_of.weekday())
    next_monday = monday + dt.timedelta(days=7)
    month_first, month_last = _month_bounds(as_of.year, as_of.month)
    upcoming = {
        _WEEKDAY_NAMES[(as_of + dt.timedelta(days=offset)).weekday()]: (
            as_of + dt.timedelta(days=offset)
        ).isoformat()
        for offset in range(7)
    }
    recent = {
        _WEEKDAY_NAMES[(as_of - dt.timedelta(days=offset)).weekday()]: (
            as_of - dt.timedelta(days=offset)
        ).isoformat()
        for offset in range(1, 8)
    }
    return {
        "oggi": _iso_with_weekday(as_of),
        "ieri": _iso_with_weekday(as_of - dt.timedelta(days=1)),
        "domani": _iso_with_weekday(as_of + dt.timedelta(days=1)),
        "dopodomani": _iso_with_weekday(as_of + dt.timedelta(days=2)),
        "prossima occorrenza di ogni giorno (da oggi compreso)": upcoming,
        "ultima occorrenza di ogni giorno (da ieri indietro)": recent,
        "questa settimana": (
            f"dal {monday.isoformat()} al {(monday + dt.timedelta(days=6)).isoformat()}"
        ),
        "prossima settimana": (
            f"dal {next_monday.isoformat()} al {(next_monday + dt.timedelta(days=6)).isoformat()}"
        ),
        "questo mese": f"dal {month_first.isoformat()} al {month_last.isoformat()}",
    }


__all__ = [
    "MAX_DATE_DISTANCE_DAYS",
    "PeriodArg",
    "PeriodError",
    "PeriodKind",
    "Weekday",
    "reference_calendar",
    "resolve_month",
    "resolve_period",
    "resolve_single_day",
]

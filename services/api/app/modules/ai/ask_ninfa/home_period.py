"""Italian time expressions -> a concrete, property-local stay-night period (pure, no clock).

"domani", "sabato", "i prossimi 7 giorni", "la prossima settimana", "12 ottobre", "questo mese" are
resolved against the EXPLICIT business date the Home is showing (`as_of`), never `date.today()`: the
period a question means is always relative to the analysis the user is looking at.

Deliberately small. Only expressions with one unambiguous calendar meaning are resolved; anything
that would need a business definition ("weekend" - which nights?) is NOT guessed (see
`home_vocabulary.UnsupportedTopic.WEEKEND`). Weekdays resolve to the next occurrence on or after
`as_of`; "questo mese" means from `as_of` to the end of the month (the nights already gone are not
described by NINFA's forward-looking snapshots, and Mia says so).
"""

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

# Snapshots describe the stay nights of the analysis window (30 nights). A longer period is
# clamped for the question "i prossimi N giorni" so a stray "prossimi 200 giorni" stays bounded.
MAX_PERIOD_DAYS = 31

_WEEKDAYS = {
    "lunedi": 0,
    "martedi": 1,
    "mercoledi": 2,
    "giovedi": 3,
    "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
}
_WEEKDAY_NAMES = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}
_MONTH_NAMES = tuple(_MONTHS)

_NEXT_N_DAYS = re.compile(r"\bprossim[ie]\s+(\d{1,3})\s+giorni\b")
_LONG_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b")
_NUMBER_WORDS = {
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "quindici": 15,
    "venti": 20,
    "trenta": 30,
}
_NEXT_WORD_DAYS = re.compile(r"\bprossim[ie]\s+(" + "|".join(_NUMBER_WORDS) + r")\s+giorni\b")


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    """`start`/`end` are stay NIGHTS (inclusive), property-local. `label` is the Italian phrase Mia
    can quote ("domani", "sabato 10 ottobre", "da oggi a domenica"). `explicit` is False for the
    default windows chosen when the question names no period."""

    start: date
    end: date
    label: str
    explicit: bool

    @property
    def nights(self) -> int:
        return (self.end - self.start).days + 1


def italian_day(value: date) -> str:
    """ "2026-10-10" -> "10 ottobre"."""
    return f"{value.day} {_MONTH_NAMES[value.month - 1]}"


def italian_weekday_day(value: date) -> str:
    """ "2026-10-10" -> "sabato 10 ottobre"."""
    return f"{_WEEKDAY_NAMES[value.weekday()]} {italian_day(value)}"


def default_periods(as_of: date) -> tuple[ResolvedPeriod, ...]:
    """When a bookings/occupancy/revenue question names no period: the next 7 nights and the next
    30 (the analysis window), both starting on `as_of`."""
    return (
        ResolvedPeriod(as_of, as_of + timedelta(days=6), "i prossimi 7 giorni", explicit=False),
        ResolvedPeriod(as_of, as_of + timedelta(days=29), "i prossimi 30 giorni", explicit=False),
    )


def _single(day: date, label: str) -> ResolvedPeriod:
    return ResolvedPeriod(day, day, label, explicit=True)


def parse_period(normalized: str, as_of: date) -> ResolvedPeriod | None:
    """The period a NORMALISED question (see `home_vocabulary.normalize_text`) explicitly names, or
    None. Most specific expression first."""
    match = _NEXT_N_DAYS.search(normalized)
    word_match = _NEXT_WORD_DAYS.search(normalized)
    if match is not None or word_match is not None:
        if match is not None:
            requested = int(match.group(1))
        else:
            assert word_match is not None
            requested = _NUMBER_WORDS[word_match.group(1)]
        days = max(1, min(requested, MAX_PERIOD_DAYS))
        label = "oggi" if days == 1 else f"i prossimi {days} giorni"
        return ResolvedPeriod(as_of, as_of + timedelta(days=days - 1), label, explicit=True)
    if "prossimi giorni" in normalized:
        return ResolvedPeriod(as_of, as_of + timedelta(days=6), "i prossimi 7 giorni", True)

    if "settimana prossima" in normalized or "prossima settimana" in normalized:
        monday = as_of + timedelta(days=7 - as_of.weekday())
        return ResolvedPeriod(
            monday, monday + timedelta(days=6), "la prossima settimana", explicit=True
        )
    if "questa settimana" in normalized:
        sunday = as_of + timedelta(days=6 - as_of.weekday())
        return ResolvedPeriod(as_of, sunday, "da oggi a domenica", explicit=True)

    if "mese prossimo" in normalized or "prossimo mese" in normalized:
        year, month = (as_of.year + 1, 1) if as_of.month == 12 else (as_of.year, as_of.month + 1)
        last = monthrange(year, month)[1]
        return ResolvedPeriod(
            date(year, month, 1), date(year, month, last), "il prossimo mese", explicit=True
        )
    if "questo mese" in normalized:
        last = monthrange(as_of.year, as_of.month)[1]
        return ResolvedPeriod(
            as_of, date(as_of.year, as_of.month, last), "da oggi a fine mese", explicit=True
        )

    if "dopodomani" in normalized:
        return _single(as_of + timedelta(days=2), "dopodomani")
    if re.search(r"\bdomani\b", normalized):
        return _single(as_of + timedelta(days=1), "domani")
    if re.search(r"\b(ieri)\b", normalized):
        return _single(as_of - timedelta(days=1), "ieri")
    if re.search(r"\b(oggi|stasera|stanotte|stamattina)\b", normalized):
        return _single(as_of, "oggi")

    long_date = _LONG_DATE.search(normalized)
    if long_date is not None:
        day, month = int(long_date.group(1)), _MONTHS[long_date.group(2)]
        try:
            resolved = date(as_of.year, month, day)
        except ValueError:
            return None
        return _single(resolved, italian_weekday_day(resolved))

    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", normalized):
            resolved = as_of + timedelta(days=(weekday - as_of.weekday()) % 7)
            return _single(resolved, italian_weekday_day(resolved))
    return None


__all__ = [
    "MAX_PERIOD_DAYS",
    "ResolvedPeriod",
    "default_periods",
    "italian_day",
    "italian_weekday_day",
    "parse_period",
]

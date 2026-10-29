"""Small readings of the TEXT of a cell, shared by the importers and by the understanding of a
file, so that what NINFA recognises is exactly what the import then reads:

* a weekday written before a date - "Lun 26/10/2026", "Martedì 27/10/2026", "Fri 23/10/2026";
* a date whose month is a NAME - "26 ottobre 2026", "26-Oct-2026" (day, month name, four-digit year:
  nothing to guess; no year, or a two-digit year, is NOT a date here);
* hours written with their unit - "8 h", "7,5 ore", "6 hrs" (a number, a unit and nothing else: a
  rate such as "14 €/h", a time such as "8:30" or a range such as "08:00-16:00" is not hours);
* the hotel's own currency written next to an amount - "1.250,00 EUR", "€ 850", "850 euro".

Both only take away words that say nothing the number or the date does not already say, and the
remainder still has to be a date (or an amount) in the format the person confirmed: nothing is
guessed. A weekday that does not belong to the date ("Lun 29/10/2026", a Thursday) is NOT accepted
(`weekday_agrees`), and another currency ($, GBP...) is not taken away: it stays in the text, so
the value is not a number and is reported, instead of becoming euros without a word.
"""

import re
import unicodedata
from datetime import date, datetime

_WEEKDAYS = {
    "lun": 0,
    "lunedi": 0,
    "mon": 0,
    "monday": 0,
    "mar": 1,
    "martedi": 1,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "mer": 2,
    "mercoledi": 2,
    "wed": 2,
    "wednesday": 2,
    "gio": 3,
    "giovedi": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "ven": 4,
    "venerdi": 4,
    "fri": 4,
    "friday": 4,
    "sab": 5,
    "sabato": 5,
    "sat": 5,
    "saturday": 5,
    "dom": 6,
    "domenica": 6,
    "sun": 6,
    "sunday": 6,
}
# A word, a full stop or a comma, then a date: "gio 29/10/2026", "Martedì, 27/10/2026".
_WEEKDAY_PREFIX = re.compile(r"^\s*([^\W\d_]{3,10})\.?,?\s+(?=\d)")
_CURRENCY_PREFIX = re.compile(r"^\s*([-+]?)\s*(?:€|eur(?:o)?\b\.?)\s*(?=\d)", re.IGNORECASE)
_CURRENCY_SUFFIX = re.compile(r"(?<=\d)\s*(?:€|eur(?:o)?\b\.?)\s*$", re.IGNORECASE)


# Month names and their usual abbreviations, Italian and English, without accents.
_MONTHS = {
    **dict.fromkeys(("gennaio", "gen", "january", "jan"), 1),
    **dict.fromkeys(("febbraio", "feb", "february"), 2),
    **dict.fromkeys(("marzo", "mar", "march"), 3),
    **dict.fromkeys(("aprile", "apr", "april"), 4),
    **dict.fromkeys(("maggio", "mag", "may"), 5),
    **dict.fromkeys(("giugno", "giu", "june", "jun"), 6),
    **dict.fromkeys(("luglio", "lug", "july", "jul"), 7),
    **dict.fromkeys(("agosto", "ago", "august", "aug"), 8),
    **dict.fromkeys(("settembre", "set", "sett", "september", "sep", "sept"), 9),
    **dict.fromkeys(("ottobre", "ott", "october", "oct"), 10),
    **dict.fromkeys(("novembre", "nov", "november"), 11),
    **dict.fromkeys(("dicembre", "dic", "december", "dec"), 12),
}
# "26 ottobre 2026", "26-Oct-2026", "26.ott.2026", "26 Oct 2026 14:30", "26-ott-26": day, month
# name, year (and, optionally, a time). Separators: spaces, "-", ".", "/" or ",".
_NAMED_DATE = re.compile(
    r"^(\d{1,2})(?:\s*[-./,]\s*|\s+)([^\W\d_]{3,9})\.?(?:\s*[-./,]\s*|\s+)(\d{4}|\d{2})"
    r"(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
# "Nov 4, 2026", "November 4 2026", "Oct. 26th, 2026 14:30": month name first, as written in the
# United States - the month is a name, so the order of day and month is not in doubt.
_NAMED_DATE_MONTH_FIRST = re.compile(
    r"^([^\W\d_]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})"
    r"(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_HOURS_UNIT = re.compile(
    r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hour|hours|ora|ore)\.?\s*$", re.IGNORECASE
)


def _plain(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def split_weekday(text: str) -> tuple[str, int | None]:
    """The text without a weekday name in front of it, and which weekday it was (Monday is 0)."""
    match = _WEEKDAY_PREFIX.match(text)
    if match is not None:
        weekday = _WEEKDAYS.get(_plain(match.group(1)))
        if weekday is not None:
            return text[match.end() :].strip(), weekday
    return text, None


def month_name_date(text: str) -> datetime | None:
    """A date whose month is written as a name ("26 ottobre 2026", "26-Oct-2026"), at midnight (or
    at the time written after it); None when the text is not of that shape - no year, a two-digit
    year, a month nobody knows - or is not a day of the calendar."""
    match = _NAMED_DATE.match(text.strip())
    if match is not None:
        month_name, day, year = match.group(2), match.group(1), match.group(3)
    else:
        match = _NAMED_DATE_MONTH_FIRST.match(text.strip())
        if match is None:
            return None
        month_name, day, year = match.group(1), match.group(2), match.group(3)
    month = _MONTHS.get(_plain(month_name))
    if month is None:
        return None
    hour, minute, second = (int(part) if part else 0 for part in match.group(4, 5, 6))
    whole_year = int(year)
    if len(year) == 2:  # (as strptime reads %y: 00-68 are 2000-2068, 69-99 are 1969-1999)
        whole_year += 2000 if whole_year < 69 else 1900
    try:
        return datetime(whole_year, month, int(day), hour, minute, second)
    except ValueError:
        return None


def has_hours_unit(text: str) -> bool:
    return _HOURS_UNIT.match(text) is not None


def strip_hours_unit(text: str) -> str:
    """The hours without their unit ("7,5 ore" -> "7,5"); any other text comes back as it was."""
    match = _HOURS_UNIT.match(text)
    return match.group(1) if match else text


def weekday_agrees(parsed: date, weekday: int | None) -> bool:
    """True when no weekday was written, or when it is the weekday of the date."""
    return weekday is None or parsed.weekday() == weekday


def strip_currency(text: str) -> str:
    """The amount without the hotel's currency written next to it (EUR, euro, €)."""
    cleaned = _CURRENCY_PREFIX.sub(r"\1", text, count=1)
    return _CURRENCY_SUFFIX.sub("", cleaned, count=1).strip()


__all__ = [
    "has_hours_unit",
    "month_name_date",
    "split_weekday",
    "strip_currency",
    "strip_hours_unit",
    "weekday_agrees",
]

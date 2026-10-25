"""Two small readings of the TEXT of a cell, shared by the importers and by the understanding of a
file, so that what NINFA recognises is exactly what the import then reads:

* a weekday written before a date - "Lun 26/10/2026", "Martedì 27/10/2026", "Fri 23/10/2026";
* the hotel's own currency written next to an amount - "1.250,00 EUR", "€ 850", "850 euro".

Both only take away words that say nothing the number or the date does not already say, and the
remainder still has to be a date (or an amount) in the format the person confirmed: nothing is
guessed. A weekday that does not belong to the date ("Lun 29/10/2026", a Thursday) is NOT accepted
(`weekday_agrees`), and another currency ($, GBP...) is not taken away: it stays in the text, so
the value is not a number and is reported, instead of becoming euros without a word.
"""

import re
import unicodedata
from datetime import date

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


def weekday_agrees(parsed: date, weekday: int | None) -> bool:
    """True when no weekday was written, or when it is the weekday of the date."""
    return weekday is None or parsed.weekday() == weekday


def strip_currency(text: str) -> str:
    """The amount without the hotel's currency written next to it (EUR, euro, €)."""
    cleaned = _CURRENCY_PREFIX.sub(r"\1", text, count=1)
    return _CURRENCY_SUFFIX.sub("", cleaned, count=1).strip()


__all__ = ["split_weekday", "strip_currency", "weekday_agrees"]

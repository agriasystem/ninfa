"""The last gate before an answer about a file leaves the server: no personal value goes out.

What NINFA understands of a file is shown to the person as example values, department words,
a title, the names of the sheets. Personal data (a name, an e-mail address, a telephone number, a
tax code, an IBAN) is recognised column by column FIRST, and a column that carries it is never
sampled. This gate is the second line: whatever text is about to be sent is read once more, and a
personal value found in it - in a column nobody recognised, in a title, in a note - is replaced
by a mark, whatever put it there. It does not rely on the page to hide anything.

Two things are looked for:

* values that have a recognisable SHAPE (an e-mail address, an international or mobile telephone
  number, a tax code, an IBAN of a country with its right length), wherever they are;
* the personal values of THIS file: the names, addresses and numbers of the columns that were found
  to carry them. They exist only in memory while the file is read and are kept nowhere.

Only the text meant to be shown is read: see `app.modules.data_sources.understanding_redaction`,
which applies this guard to an answer. Headers, field names and codes are never touched, because
the import matches the file by them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.modules.document_understanding.pii import PiiKind, looks_like_person

MARK: Final = "•••"
_MAX_VALUES = 4000
_MIN_VALUE_LENGTH = 4

_EMAIL = re.compile(r"[\w.+'\-]+@[\w\-]+(?:\.[\w\-]+)+")
_TAX_CODE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z](?![A-Za-z0-9])"
)
# An IBAN is two letters, two digits and the rest of the account: its LENGTH is fixed by country,
# which is what tells it from an invoice number such as "FT20260101234567".
_IBAN_LENGTHS: Final = {
    "IT": 27,
    "SM": 27,
    "FR": 27,
    "MC": 27,
    "DE": 22,
    "GB": 22,
    "IE": 22,
    "ES": 24,
    "PT": 25,
    "CH": 21,
    "LI": 21,
    "AT": 20,
    "LU": 20,
    "NL": 18,
    "BE": 16,
    "GR": 27,
    "PL": 28,
}
_IBAN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2})\d{2}(?:\s?[A-Za-z0-9]){10,30}(?![A-Za-z0-9])")
# An international number ("+39 333 1234567", "0039 06 1234567") and an Italian mobile one
# ("333 1234567", "333-123-4567"). A landline without a country code is NOT looked for in text: a
# month and a year ("09/2026") are written just like it.
_PHONES: Final = (
    re.compile(r"(?<![\w.])(?:\+|00)\d{1,3}[\s.\-]?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,}){1,4}(?![\w])"),
    re.compile(r"(?<!\d)3\d{2}[\s.\-/]\d{3}[\s.\-/]?\d{3,4}(?!\d)"),
    re.compile(r"(?<!\d)3\d{2}[\s.\-/]\d{6,7}(?!\d)"),
)


def _iban_sub(match: re.Match[str]) -> str:
    compact = re.sub(r"\s", "", match.group(0))
    length = _IBAN_LENGTHS.get(match.group(1).upper())
    return MARK if length is not None and len(compact) == length else match.group(0)


@dataclass(frozen=True, slots=True)
class PersonalDataGuard:
    """Reads a text and replaces the personal values in it."""

    # The personal values of this file, longest first, as one case-insensitive pattern.
    known: re.Pattern[str] | None = None

    @classmethod
    def for_columns(cls, columns: Iterable[tuple[PiiKind, Iterable[str]]]) -> "PersonalDataGuard":
        """From the columns found to carry personal data: their kind and their cell texts. Only
        values that LOOK personal are kept - a column that a header called "Operatore" but that
        holds "Reception" and "Cucina" must not make those words disappear from the page."""
        found: set[str] = set()
        for kind, texts in columns:
            for raw in texts:
                text = " ".join(raw.split())
                if len(text) < _MIN_VALUE_LENGTH or len(found) >= _MAX_VALUES:
                    continue
                if kind == PiiKind.PERSON_NAME and not looks_like_person(text):
                    continue
                found.add(text)
        return cls(_pattern(found))

    def clean(self, text: str) -> str:
        """The text with every personal value replaced by a mark."""
        if not text:
            return text
        cleaned = _EMAIL.sub(MARK, text)
        cleaned = _TAX_CODE.sub(MARK, cleaned)
        cleaned = _IBAN.sub(_iban_sub, cleaned)
        for pattern in _PHONES:
            cleaned = pattern.sub(MARK, cleaned)
        if self.known is not None:
            cleaned = self.known.sub(MARK, cleaned)
        return cleaned

    def clean_all(self, texts: Iterable[str]) -> tuple[str, ...]:
        return tuple(self.clean(text) for text in texts)

    def clean_optional(self, text: str | None) -> str | None:
        return None if text is None else self.clean(text)


def _pattern(values: set[str]) -> re.Pattern[str] | None:
    """One pattern for the personal values of the file; a name of two or three words also written
    the other way round ("Surname Name")."""
    variants: set[str] = set()
    for value in values:
        variants.add(value)
        words = value.split()
        if 2 <= len(words) <= 3:
            variants.add(" ".join(reversed(words)))
    if not variants:
        return None
    ordered = sorted(variants, key=lambda item: (-len(item), item))
    alternatives = "|".join(
        r"\s+".join(re.escape(part) for part in item.split()) for item in ordered
    )
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


__all__ = ["MARK", "PersonalDataGuard"]

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
which applies this guard to an answer. Headers, field names and codes are never touched HERE,
because the import matches the file by them - so a header cell that is itself a personal value
(an address, a number) is made safe where the labels of the table are made
(`structure._build_columns`), and the import, which reads the file the same way, finds the column
by the same safe word.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.document_understanding.personal_shapes import (
    MARK,
    SHAPE_RULES,
    Rule,
    is_personal_value,
)
from app.modules.document_understanding.pii import PiiKind, looks_like_person
from app.modules.document_understanding.pii_text import mask_matches, normalize

_MAX_VALUES = 4000
_MIN_VALUE_LENGTH = 4


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
                text = " ".join(normalize(raw).split())  # the same value hidden in another way
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
        # Read as a person reads it - invisible characters gone, look-alike letters Latin - and
        # masked in the text as it was: a zero-width space inside an address hides nothing.
        rules: list[Rule] = list(SHAPE_RULES)
        if self.known is not None:
            rules.append((self.known, None))
        return mask_matches(text, rules, MARK)

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


__all__ = ["MARK", "PersonalDataGuard", "is_personal_value"]

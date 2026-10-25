"""Folding, tokens and a light Italian/English stemmer, for comparing what people write in headers.

"Reparto o mansione", "Reparto/Mansione" and "REPARTO - MANSIONE" must all contain the token
`repart`, whatever surrounds it. Only ever used to COMPARE: nothing here changes what is displayed.
"""

import re
import unicodedata
from collections.abc import Iterable

_NON_WORD = re.compile(r"[^a-z0-9]+")

# "n.", "nr", "num", "numero", "nº" are one word for a header: "number".
_NUMBER_WORDS = frozenset({"n", "nr", "nro", "num", "numero", "no", "number", "nbr"})
_TOTAL_WORDS = frozenset({"tot", "totale", "totali", "total", "totals", "totalizzato"})
# Words that join header words without carrying a meaning of their own.
STOP_WORDS = frozenset(
    {
        "o",
        "e",
        "ed",
        "di",
        "del",
        "dello",
        "della",
        "dei",
        "degli",
        "delle",
        "dell",
        "da",
        "per",
        "la",
        "il",
        "lo",
        "le",
        "i",
        "gli",
        "un",
        "una",
        "the",
        "of",
        "and",
        "or",
        "a",
        "all",
        "alla",
        "nel",
        "nella",
    }
)


def fold(text: str) -> str:
    """Lower case, no accents, punctuation as single spaces ("N° Camere" -> "n camere")."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", plain.casefold()).strip()


def stem(word: str) -> str:
    """One word without its Italian gender/number ending ("previste" -> "previst", "reparti" ->
    "repart"). Short words and words ending in a consonant are left alone."""
    if word in _NUMBER_WORDS:
        return "numer"
    if word in _TOTAL_WORDS:
        return "total"
    if len(word) >= 5 and word[-1] in "aeio":
        return word[:-1]
    return word


def token_list(text: str) -> tuple[str, ...]:
    """The meaningful stemmed words of a header, in order ("Costo previsto" -> cost, previst).
    A "#" is the word "number" ("Res #") and a "%" on its own the word "percentage" ("Commissione
    %"); the "22%" of "Imponibile 22%" is a rate that names the amount, not a column of
    percentages."""
    words = tuple(stem(word) for word in fold(text).split() if word not in STOP_WORDS)
    extra = [
        word
        for sign, word in (("#", "numer"), ("%", "perc"))
        if word not in words and _standing_sign(text, sign)
    ]
    return (*words, *extra)


def _standing_sign(text: str, sign: str) -> bool:
    """The sign is written, and not glued to a digit ("22%")."""
    return any(
        position == 0 or not text[position - 1].isdigit()
        for position, ch in enumerate(text)
        if ch == sign
    )


def tokens(text: str) -> frozenset[str]:
    return frozenset(token_list(text))


def stems(words: str | Iterable[str]) -> frozenset[str]:
    """The stems of a list of words written the way a human would ("reparto mansione ruolo")."""
    parts = words.split() if isinstance(words, str) else list(words)
    return frozenset(stem(fold(word)) for word in parts if fold(word))


def has_word(text: str, words: Iterable[str]) -> bool:
    """True when the folded text contains any of these WHOLE words ("Totale reparto" has
    "totale")."""
    present = set(fold(text).split())
    return any(fold(word) in present for word in words)


__all__ = ["STOP_WORDS", "fold", "has_word", "stem", "stems", "token_list", "tokens"]

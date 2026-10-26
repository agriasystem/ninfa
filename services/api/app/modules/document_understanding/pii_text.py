"""Personal-data hygiene for TEXT: what must still be recognised when someone hides it.

The ordinary `text.fold` is made for comparing headers with the words NINFA knows; it is free to be
generous. Personal data is different: a column that is personal must be seen as personal however
its header was typed - with a zero-width space inside, a no-break space, a soft hyphen, a BOM, the
words glued together ("CodiceFiscale"), or letters borrowed from another alphabet ("Cоdice" with a
Cyrillic o). This module is the ONE place that knows how to undo that, for the privacy decisions
only: the generic semantic matching is not touched by it.

Two things come out of it:

* `normalize` / `projection` - a text as a person reads it (invisible characters gone, spaces
  unified, look-alike letters mapped to Latin ones), with a map back to the original characters so
  a personal value found in the normalised text can be masked in the ORIGINAL one;
* `header_variants` / `header_word_sets` - every reading of a header that could mean a personal-data
  word: invisible characters removed, or taken for a space, camelCase split, and a glued run of
  letters split into words ONLY when every piece is a known personal-data word. The readings are
  kept apart: a wrong one invents words and must never be mixed into the right one.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable
from functools import cache

from app.modules.document_understanding.text import stem, tokens

# Letters of the Cyrillic and Greek alphabets that look like a Latin one. Not a full confusables
# table (that would also touch real Cyrillic or Greek words): exactly the look-alikes that let a
# word or a value pass for something it is not.
_CONFUSABLES: dict[str, str] = {
    **dict(zip("авекмнорстухіјѕԁɡ", "abekmhopctuxijsdg", strict=True)),
    **dict(zip("АВЕКМНОРСТХУІЈЅ", "ABEKMHOPCTXYIJS", strict=True)),
    **dict(zip("οανικρτυχ", "oavikptux", strict=True)),
    **dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX", strict=True)),
    "ı": "i",
}

# Words that can make up a personal-data header. A glued run of letters ("codicefiscale",
# "nomeospite", "lastname") is split into words only when EVERY piece is one of these.
_SEGMENT_WORDS = frozenset(
    [
        "nome",
        "nomi",
        "cognome",
        "cognomi",
        "name",
        "names",
        "surname",
        "first",
        "last",
        "full",
        "given",
        "family",
        "middle",
        "ospite",
        "ospiti",
        "guest",
        "guests",
        "cliente",
        "clienti",
        "customer",
        "customers",
        "dipendente",
        "dipendenti",
        "employee",
        "employees",
        "staff",
        "collaboratore",
        "operatore",
        "persona",
        "referente",
        "intestatario",
        "nominativo",
        "titolare",
        "codice",
        "cod",
        "code",
        "tax",
        "fiscale",
        "fiscal",
        "cf",
        "id",
        "email",
        "mail",
        "pec",
        "telefono",
        "tel",
        "cellulare",
        "cell",
        "phone",
        "mobile",
        "iban",
        "del",
        "di",
    ]
)
_MIN_PIECE = 2
_MIN_GLUED = 6
_MAX_GLUED = 40

# "NomeOspite" -> "Nome Ospite": a capital that starts a word of at least three letters, after at
# least three lower-case ones. (Not "nOmE": letters in alternating case are not words.)
_CAMEL = re.compile(r"(?<=[a-zà-ÿ]{3})(?=[A-ZÀ-Ý][a-zà-ÿ]{2})")


def _is_invisible(ch: str) -> bool:
    """A character that prints nothing: format characters (zero-width space / joiners, BOM, soft
    hyphen, bidi marks...) and control characters other than the usual white space."""
    category = unicodedata.category(ch)
    if category == "Cf":
        return True
    return category == "Cc" and not ch.isspace()


def _unit(ch: str, *, invisible_as: str) -> str:
    """One original character as the normalised text has it ('' when it prints nothing)."""
    if _is_invisible(ch):
        return invisible_as
    if unicodedata.category(ch) in {"Mn", "Me"}:
        return ""  # a combining mark floating on its own: it breaks a word, it adds no letter
    if ch.isspace() or unicodedata.category(ch) in {"Zs", "Zl", "Zp"}:
        return " "
    return unicodedata.normalize("NFKC", ch)


def _is_latin_or_digit(ch: str) -> bool:
    if ch.isdigit():
        return ch.isascii()
    return ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN")


def _units(text: str, invisible_as: str) -> list[tuple[str, int]]:
    """Every character of the normalised text with the position of the original it came from.
    A look-alike letter (Cyrillic or Greek) is made Latin only inside a word that already has a
    Latin letter or a digit - that is how a word is disguised ("Cоdice", "RSSМRA85T10A562S"); a
    whole word in Cyrillic or Greek is just that language and is left alone."""
    units: list[tuple[str, int]] = []
    for position, ch in enumerate(text):
        units.extend((out, position) for out in _unit(ch, invisible_as=invisible_as))
    result: list[tuple[str, int]] = []
    word: list[tuple[str, int]] = []

    def flush() -> None:
        if any(c in _CONFUSABLES for c, _ in word) and any(_is_latin_or_digit(c) for c, _ in word):
            result.extend((_CONFUSABLES.get(c, c), i) for c, i in word)
        else:
            result.extend(word)
        word.clear()

    for item in units:
        if item[0] == " ":
            flush()
            result.append(item)
        else:
            word.append(item)
    flush()
    return result


def normalize(text: str, *, invisible_as: str = "") -> str:
    """The text as a person reads it. Invisible characters are removed (or replaced by
    `invisible_as`), every kind of space is one space, compatibility forms (full-width letters,
    ligatures, superscripts) become plain ones and look-alike letters hiding in a Latin word
    become Latin ones. Case and accents are kept."""
    return "".join(c for c, _ in _units(text, invisible_as))


def projection(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """`normalize(text)` plus, for every character of it, the [start, end) span of the ORIGINAL text
    it came from - so a match found in the normalised text can be masked in the original one."""
    units = _units(text, "")
    return (
        "".join(c for c, _ in units),
        tuple(i for _, i in units),
        tuple(i + 1 for _, i in units),
    )


def mask_matches(
    text: str,
    rules: Iterable[tuple[re.Pattern[str], Callable[[re.Match[str]], bool] | None]],
    mark: str,
) -> str:
    """The ORIGINAL text with every personal value replaced by `mark`, where the values are looked
    for in the normalised reading of it: an e-mail address with a zero-width space inside, a tax
    code with a Cyrillic letter, a full-width "@" are found - and masked whole."""
    if not text:
        return text
    normalized, starts, ends = projection(text)
    spans: list[tuple[int, int]] = []
    for pattern, accept in rules:
        for match in pattern.finditer(normalized):
            if match.end() > match.start() and (accept is None or accept(match)):
                spans.append((starts[match.start()], ends[match.end() - 1]))
    return mask_spans(text, spans, mark) if spans else text


def mask_spans(text: str, spans: list[tuple[int, int]], mark: str) -> str:
    """The original text with each [start, end) span replaced by `mark` (overlaps merged)."""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out.append(text[cursor:start])
        out.append(mark)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _segments(glued: str) -> tuple[str, ...] | None:
    """A glued run of letters as personal-data words, or None unless EVERY piece is one."""
    if not _MIN_GLUED <= len(glued) <= _MAX_GLUED or not glued.isalpha():
        return None

    @cache
    def split(start: int) -> tuple[str, ...] | None:
        if start == len(glued):
            return ()
        for end in range(len(glued), start + _MIN_PIECE - 1, -1):
            piece = glued[start:end]
            if piece in _SEGMENT_WORDS:
                rest = split(end)
                if rest is not None:
                    return (piece, *rest)
        return None

    pieces = split(0)
    return pieces if pieces is not None and len(pieces) >= 2 else None


def header_variants(header: str) -> tuple[str, ...]:
    """Every plausible reading of a header, original first, without repeats: with the invisible
    characters removed (they were inside a word), taken for a space (they separated two), and with
    the capitals of a camelCase run split ("NomeOspite" -> "Nome Ospite")."""
    glued = normalize(header)
    spaced = normalize(header, invisible_as=" ")
    candidates = (
        header,
        glued,
        spaced,
        _CAMEL.sub(" ", glued),
        _CAMEL.sub(" ", spaced),
    )
    return tuple(dict.fromkeys(" ".join(c.split()) for c in candidates if c.strip()))


def header_word_sets(header: str) -> tuple[frozenset[str], ...]:
    """The stemmed words of a header, ONE set per reading of it (see `header_variants`), each with
    the pieces of any glued run of letters that is made of personal-data words only.

    The readings are kept apart on purpose: a wrong reading ("No me Dipendente") invents words
    ("no" is the word "number") that must never be mixed into the right one. A caller asks its
    question of every set and takes the first yes."""
    sets: list[frozenset[str]] = []
    for variant in header_variants(header):
        words = set(tokens(variant))
        for run in re.findall(r"[^\W\d_]+", variant.casefold()):
            plain = unicodedata.normalize("NFKD", run).encode("ascii", "ignore").decode()
            pieces = _segments(plain)
            if pieces is not None:
                words |= {stem(piece) for piece in pieces}
        sets.append(frozenset(words))
    return tuple(dict.fromkeys(sets))


__all__ = [
    "header_variants",
    "header_word_sets",
    "mask_matches",
    "mask_spans",
    "normalize",
    "projection",
]

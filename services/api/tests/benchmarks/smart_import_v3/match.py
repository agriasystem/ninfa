"""Comparing a header written in the document with the name Smart Import gave the column.

The system joins the two levels of a header ("Ore - Previste"), renames a repeated one ("Ore (2)")
and removes invisible characters; the truth keeps the cells as they were drawn. Matching ignores
case, accents, punctuation, spacing and zero-width characters, accepts the joined or the lower
level alone for a two-level header, and an optional "(n)" suffix.

It does NOT ignore the few symbols that change WHAT a column is: "Commissione %" is a rate and
"Commissione" an amount, "Res #" a number, "Imponibile €" says its currency. `norm` (for words and
values) is lossy on purpose; `header_key` (for the identity of a column) keeps those symbols. Two
columns whose headers differ only by one of them are two columns - the first version of this module
dropped the "%" and could not tell the two apart.
"""

import re
import unicodedata

_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁩﻿]")
_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", _INVISIBLE.sub("", text))
    return "".join(c for c in folded if not unicodedata.combining(c)).casefold()


def norm(text: str) -> str:
    return re.sub(r"[^0-9a-z&]+", " ", _fold(text)).strip()


def header_key(text: str) -> str:
    """The identity of a column from its header: like `norm`, but a "%", a "#" or a currency sign
    is part of what the column is."""
    return re.sub(r"[^0-9a-z&%#€$£]+", " ", _fold(text)).strip()


def _strip_suffix(text: str) -> str:
    return _SUFFIX.sub("", text)


def header_matches(parts: tuple[str, ...], observed: str) -> bool:
    """Is `observed` the system's name for a column whose header cell(s) are `parts`?"""
    candidate = header_key(_strip_suffix(_INVISIBLE.sub("", observed)))
    wanted = {header_key(" ".join(p for p in parts if p)), header_key(parts[-1]) if parts else ""}
    return candidate in wanted and candidate != ""


def rank_among_equals(columns: list[str], position: int, parts: tuple[str, ...]) -> int:
    """1 for the first column matching `parts`, 2 for the second..."""
    rank = 0
    for index, header in enumerate(columns):
        if header_matches(parts, header):
            rank += 1
            if index == position:
                return rank
    return 0

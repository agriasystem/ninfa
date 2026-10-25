"""Comparing a header written in the document with the name Smart Import gave the column.

The system joins the two levels of a header ("Ore - Previste"), renames a repeated one ("Ore (2)")
and removes invisible characters; the truth keeps the cells as they were drawn. Matching ignores
case, accents, punctuation, spacing and zero-width characters, accepts the joined or the lower
level alone for a two-level header, and an optional "(n)" suffix.
"""

import re
import unicodedata

_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁩﻿]")
_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", _INVISIBLE.sub("", text))
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^0-9a-z&]+", " ", folded).strip()


def _strip_suffix(text: str) -> str:
    return _SUFFIX.sub("", text)


def header_matches(parts: tuple[str, ...], observed: str) -> bool:
    """Is `observed` the system's name for a column whose header cell(s) are `parts`?"""
    candidate = norm(_strip_suffix(_INVISIBLE.sub("", observed)))
    wanted = {norm(" ".join(p for p in parts if p)), norm(parts[-1]) if parts else ""}
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

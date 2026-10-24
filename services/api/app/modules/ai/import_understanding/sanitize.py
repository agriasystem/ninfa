"""What of the file's own text may reach a language model: very little, and cleaned.

Sheet names, titles, headers and a few example values are free text that someone typed into a
spreadsheet. They are cut short, stripped of control characters, and anything shaped like personal
data (an e-mail address, a telephone number, an IBAN, a tax code) is replaced before it can leave
NINFA. A column that carries personal data is never shown at all - only its CLASS is.

Cleaning does not make text safe to OBEY (a cell can say "ignore your instructions"): the model is
told the evidence is data, its answer is a closed choice among what NINFA offered, and nothing it
returns is ever shown to a person or run. Cleaning only keeps personal data and long free text out.
"""

import re

MAX_TEXT = 60
REMOVED = "[removed]"

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁠-⁩﻿]")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{2,4}){3,8}\b")
_TAX_CODE = re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b")
_PHONE = re.compile(r"(?<![\w/])(?:\+|00)?\d[\d\s().\-]{7,}\d(?![\w/])")


def clean_text(text: str, limit: int = MAX_TEXT) -> str:
    """The text as the model may see it: one line, bounded, with personal-data shapes removed."""
    flat = " ".join(_CONTROL.sub(" ", text).split())
    for pattern in (_EMAIL, _IBAN, _TAX_CODE, _PHONE):
        flat = pattern.sub(REMOVED, flat)
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


__all__ = ["MAX_TEXT", "REMOVED", "clean_text"]

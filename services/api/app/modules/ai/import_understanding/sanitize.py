"""What of the file's own text may reach a language model: very little, and cleaned.

Sheet names, titles, headers and a few example values are free text that someone typed into a
spreadsheet. They are read the way a person reads them (an invisible character - a zero-width
space, a soft hyphen, a BOM - is simply not there; a letter borrowed from another alphabet is the
Latin one it imitates), cut short, and anything shaped like personal data (an e-mail address, a
telephone number, an IBAN, a tax code) is replaced before it can leave NINFA. A column that carries
personal data is never shown at all - only its CLASS is.

Cleaning does not make text safe to OBEY (a cell can say "ignore your instructions"): the model is
told the evidence is data, its answer is a closed choice among what NINFA offered, and nothing it
returns is ever shown to a person or run. Cleaning only keeps personal data and long free text out.
"""

import re

from app.modules.document_understanding.pii_text import normalize

MAX_TEXT = 60
REMOVED = "[removed]"

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{2,4}){3,8}\b")
_TAX_CODE = re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b")
_PHONE = re.compile(r"(?<![\w/])(?:\+|00)?\d[\d\s().\-]{7,}\d(?![\w/])")
# In the order they are removed: an address first (it may contain digits), a phone number last.
_SHAPES = (("EMAIL", _EMAIL), ("IBAN", _IBAN), ("TAX_CODE", _TAX_CODE), ("PHONE", _PHONE))


def flatten(text: str) -> str:
    """The text as one plain line with the personal-data shapes removed, whole (not yet cut)."""
    flat = " ".join(normalize(text).split())
    for _, pattern in _SHAPES:
        flat = pattern.sub(REMOVED, flat)
    return flat


def truncate(flat: str, limit: int = MAX_TEXT) -> str:
    if len(flat) > limit:
        return flat[: limit - 1].rstrip() + "…"
    return flat


def clean_text(text: str, limit: int = MAX_TEXT) -> str:
    """The text as the model may see it: one line, bounded, with personal-data shapes removed."""
    return truncate(flatten(text), limit)


def personal_shapes_in(text: str) -> tuple[str, ...]:
    """Which personal-data shapes are STILL recognisable in a text (read as a person reads it).
    Used on the final text about to be sent: an empty answer is the only acceptable one."""
    reading = " ".join(normalize(text).split())
    return tuple(name for name, pattern in _SHAPES if pattern.search(reading))


__all__ = ["MAX_TEXT", "REMOVED", "clean_text", "flatten", "personal_shapes_in", "truncate"]

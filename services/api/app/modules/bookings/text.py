"""Text keys: one deterministic normalisation used for headers, statuses and channel names."""

import re
import unicodedata

_NON_WORD = re.compile(r"[\W_]+")


def normalize_key(raw: str) -> str:
    """Comparison key for free text: case, accents, punctuation and spacing do not matter.

    "Booking.com", "BOOKING.COM", "booking com" and " Booking . com " share one key, while
    letters, digits and the words themselves are preserved ("B&B Hotels" -> "b and b hotels").
    Only ever used to *compare*; display values keep their original spelling.
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = without_accents.casefold().replace("&", " and ")
    return _NON_WORD.sub(" ", text).strip()

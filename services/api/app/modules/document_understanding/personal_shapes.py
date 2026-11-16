"""The SHAPES of personal data: what an address, a number, a code looks like, with no knowledge of
any file.

A leaf of the package (it imports nothing but the text hygiene), so that the lowest layer - the one
that builds the labels of a table - and the last gate before an answer leaves the server read
personal values by the SAME rules. `redaction` masks them in a text; `structure` refuses to use one
as the name of a column.

Looked for, wherever they are:

* an e-mail address, a tax code, an IBAN of a country with its right length;
* an international or mobile telephone number. A landline without a country code is NOT looked
  for in text: a month and a year ("09/2026") are written just like it.
"""

import re
from collections.abc import Callable
from typing import Final

from app.modules.document_understanding.pii_text import mask_matches

MARK: Final = "•••"

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
# ("333 1234567", "333-123-4567").
_PHONES: Final = (
    re.compile(r"(?<![\w.])(?:\+|00)\d{1,3}[\s.\-]?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,}){1,4}(?![\w])"),
    re.compile(r"(?<!\d)3\d{2}[\s.\-/]\d{3}[\s.\-/]?\d{3,4}(?!\d)"),
    re.compile(r"(?<!\d)3\d{2}[\s.\-/]\d{6,7}(?!\d)"),
)


def _iban_accepts(match: re.Match[str]) -> bool:
    compact = re.sub(r"\s", "", match.group(0))
    length = _IBAN_LENGTHS.get(match.group(1).upper())
    return length is not None and len(compact) == length


Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], bool] | None]

# In the order they are looked for.
SHAPE_RULES: Final[tuple[Rule, ...]] = (
    (_EMAIL, None),
    (_TAX_CODE, None),
    (_IBAN, _iban_accepts),
    *((pattern, None) for pattern in _PHONES),
)


def is_personal_value(text: str) -> bool:
    """Is this text - a header cell, say - or any part of it a personal value by its SHAPE? Read as
    a person reads it (an invisible character, a look-alike letter, change nothing). A header that
    is one is not a label of anything: a column is not called by a person's address, and what it is
    called by is what the browser would be sent."""
    return bool(text) and mask_matches(text, list(SHAPE_RULES), MARK) != text


__all__ = ["MARK", "SHAPE_RULES", "Rule", "is_personal_value"]

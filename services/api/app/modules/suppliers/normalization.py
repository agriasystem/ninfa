"""Deterministic normalisation of supplier identity data (no I/O, no float, stdlib only).

The normalised NAME helps matching; it never replaces the fiscal identifiers. Legal forms are NOT
stripped: "ROSSI FOOD SRL" and "ROSSI FOOD SPA" stay two different names (a similar name is a
reason to ask a person, never a reason to merge). The IBAN is hashed here, at the boundary, and
the raw string is never returned, stored or put in an error.
"""

import hashlib
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from app.modules.bookings.text import normalize_key

_WHITESPACE = re.compile(r"\s+")
_VAT_STRUCTURE = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,28}$")
_ITALIAN_VAT = re.compile(r"^IT\d{11}$")
_BARE_ITALIAN_VAT = re.compile(r"^\d{11}$")
_TAX_CODE_STRUCTURE = re.compile(r"^[A-Z0-9]{5,20}$")
_IBAN_STRUCTURE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_FOUR_PLACES = Decimal("0.0001")

# The versioned resolution policy (docs/architecture/cost-ingestion-v1.md, ADR 0012).
RESOLUTION_POLICY_VERSION = "supplier-resolution-v1"
FUZZY_REVIEW_MIN_SIMILARITY = Decimal("0.85")
MAX_REVIEWS_PER_SUPPLIER = 3


def display_name(name: str) -> str:
    """The supplier name as shown: trimmed, whitespace collapsed, original letters kept."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", name)).strip()


def normalize_supplier_name(name: str) -> str:
    """Comparison key of a legal name: case, accents, punctuation and spacing do not matter.

    Dots are removed first, so "S.r.l." and "SRL" (and "S.p.A." / "SPA") are the same spelling;
    every other punctuation mark becomes a space. Words and legal forms are preserved.
    """
    return normalize_key(name.replace(".", ""))


def normalize_country(value: str | None) -> str | None:
    if value is None:
        return None
    country = value.strip().upper()
    return country if _COUNTRY.match(country) else None


def normalize_vat_number(raw: str, country: str | None = None) -> str:
    """`IdPaese + IdCodice` in upper case without spaces or punctuation ("IT01234567890").

    Structural validation only (no national checksum: foreign suppliers are supported). An
    11-digit value without a country prefix is read as Italian. Raises ValueError otherwise.
    """
    compact = re.sub(r"[\s.\-/]", "", raw).upper()
    if _BARE_ITALIAN_VAT.match(compact):
        compact = f"{(country or 'IT')}{compact}"
    elif country is not None and not compact[:2].isalpha():
        compact = f"{country}{compact}"
    if not _VAT_STRUCTURE.match(compact):
        raise ValueError("not a structurally valid VAT number")
    if compact.startswith("IT") and not _ITALIAN_VAT.match(compact):
        raise ValueError("an Italian VAT number has 11 digits")
    return compact


def normalize_tax_code(raw: str) -> str:
    """Upper case, no whitespace. Not always a personal fiscal code: only its shape is checked."""
    compact = re.sub(r"\s+", "", raw).upper()
    if not _TAX_CODE_STRUCTURE.match(compact):
        raise ValueError("not a structurally valid tax code")
    return compact


def _iban_checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def normalize_iban(raw: str) -> str | None:
    """The IBAN in its electronic form, or None when it is not a valid IBAN (never guessed)."""
    compact = re.sub(r"[\s.\-]", "", raw).upper()
    if not _IBAN_STRUCTURE.match(compact) or not _iban_checksum_ok(compact):
        return None
    return compact


def hash_iban(raw: str) -> str | None:
    """SHA-256 hex of the normalised IBAN, or None when the IBAN is not valid.

    The only thing that ever leaves this function: the raw account number is dropped here.
    """
    normalized = normalize_iban(raw)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def similarity(left: str, right: str) -> Decimal:
    """Ratio of the matching blocks of two normalised names, 0..1 with four decimals.

    `difflib` finds the blocks; the ratio itself is integer arithmetic (2 * matches / total), so
    there is no float in the result. It is used ONLY to propose a possible-duplicate review.
    """
    total = len(left) + len(right)
    if total == 0:
        return Decimal(0)
    matches = sum(
        block.size
        for block in SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks()
    )
    return (Decimal(2 * matches) / Decimal(total)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)

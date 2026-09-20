"""Reusable Pydantic field types: they normalise first, then validate.

The same rules are enforced again by PostgreSQL CHECK constraints where the database can
express them (email/slug/currency format, ...); IANA timezones and ISO 4217 membership are
checked only here.
"""

import re
import zoneinfo
from functools import lru_cache
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, StringConstraints

from app.core.iso4217 import ISO_4217_CODES

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    """Canonical stored form of an email: trimmed and lower-cased."""
    return value.strip().lower()


def _normalize_email(value: object) -> object:
    return normalize_email(value) if isinstance(value, str) else value


def _check_email(value: str) -> str:
    if not _EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


def _strip_lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


def _strip_upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


@lru_cache(maxsize=1)
def _iana_timezones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def _check_timezone(value: str) -> str:
    if value not in _iana_timezones():
        raise ValueError("not a valid IANA timezone identifier (e.g. Europe/Rome)")
    return value


def _check_currency(value: str) -> str:
    if value not in ISO_4217_CODES:
        raise ValueError("not a supported ISO 4217 currency code (e.g. EUR)")
    return value


NormalizedEmail = Annotated[
    str,
    BeforeValidator(_normalize_email),
    StringConstraints(max_length=254),
    AfterValidator(_check_email),
]
Slug = Annotated[
    str,
    BeforeValidator(_strip_lower),
    StringConstraints(min_length=2, max_length=63, pattern=SLUG_PATTERN),
]
Timezone = Annotated[
    str, BeforeValidator(_strip), StringConstraints(max_length=64), AfterValidator(_check_timezone)
]
CurrencyCode = Annotated[
    str,
    BeforeValidator(_strip_upper),
    StringConstraints(pattern=r"^[A-Z]{3}$"),
    AfterValidator(_check_currency),
]
Sha256Hex = Annotated[
    str, BeforeValidator(_strip_lower), StringConstraints(pattern=r"^[0-9a-f]{64}$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

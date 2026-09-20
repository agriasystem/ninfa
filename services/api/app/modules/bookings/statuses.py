"""Booking status recognition: a few deterministic synonyms, overridable by the mapping profile.

Nothing here guesses. A value that is neither a built-in synonym nor in the profile's
`status_mapping` resolves to None and the row is reported as having an unknown status: it is
never turned into CONFIRMED by default.
"""

from collections.abc import Mapping

from app.modules.bookings.models import BookingStatus
from app.modules.bookings.text import normalize_key

_SYNONYMS: Mapping[BookingStatus, tuple[str, ...]] = {
    BookingStatus.CONFIRMED: ("confirmed", "confermato", "confermata"),
    BookingStatus.CANCELLED: (
        "cancelled",
        "canceled",
        "annullato",
        "annullata",
        "cancellato",
        "cancellata",
    ),
    BookingStatus.NO_SHOW: ("no show", "noshow"),
    BookingStatus.CHECKED_IN: ("checked in", "checkedin"),
    BookingStatus.CHECKED_OUT: ("checked out", "checkedout"),
}

BUILTIN_STATUS_KEYS: Mapping[str, BookingStatus] = {
    normalize_key(synonym): status for status, names in _SYNONYMS.items() for synonym in names
}


def resolve_status(raw: str, overrides: Mapping[str, BookingStatus]) -> BookingStatus | None:
    """Canonical status for a source value, or None if it is not recognised.

    `overrides` (the profile's status_mapping, keyed by `normalize_key`) wins over the built-ins.
    """
    key = normalize_key(raw)
    if key in overrides:
        return overrides[key]
    return BUILTIN_STATUS_KEYS.get(key)

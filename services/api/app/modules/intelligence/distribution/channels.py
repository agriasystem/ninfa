"""Read-only, conservative channel classification (Part "CHANNEL CLASSIFICATION").

REV_OTA_DEPENDENCY never writes to `BookingChannel` and never invents a mapping: it classifies
each channel in memory, every time, from what is already there. Order (the first that applies
decides):

    1. CANONICAL_SOURCE   `channel_type` when `is_verified` (the customer's own decision, made at
                          import time by Gate 2 - see `app.modules.bookings.channels`). An
                          UNVERIFIED `channel_type` is Gate 2's own *hint* (its own tiny built-in
                          list), not a confirmed fact, so it is NOT "reliable" here: it falls
                          through to step 2 exactly like an unclassified channel would.
    2. DETERMINISTIC_RULE a small, high-precision, EXACT dictionary on the channel's own
                          `normalized_name` (never a substring, never a fuzzy match).
    3. UNCLASSIFIED       UNKNOWN. A generic or ambiguous label ("Booking Engine", "Online",
                          "Reservation") is never guessed into OTA or DIRECT.

`ChannelType` (Gate 2, `app.modules.bookings.models`) has six values; REV_OTA_DEPENDENCY only
ever reasons about the four coarser `ChannelGroup`s. TOUR_OPERATOR, AGENCY and CORPORATE are
OTHER: real, identifiable intermediaries that are deliberately never guessed to be OTA.
"""

from collections.abc import Mapping
from typing import NamedTuple
from uuid import UUID

from app.modules.bookings.models import ChannelType
from app.modules.intelligence.distribution.types import (
    CONFIDENCE_CANONICAL_SOURCE,
    CONFIDENCE_DETERMINISTIC_RULE,
    CONFIDENCE_UNCLASSIFIED,
    ChannelClassificationMethod,
    ChannelGroup,
)
from app.modules.intelligence.distribution.types import (
    ChannelClassification as ChannelClassification,
)

# ChannelType -> ChannelGroup, used ONLY when the row is verified (a customer decision, reliable
# by construction). OTHER intermediaries collapse to one coarser group: REV_OTA_DEPENDENCY does
# not try to distinguish a wholesaler from a corporate account, only "not OTA, not DIRECT".
_CANONICAL_GROUP: Mapping[ChannelType, ChannelGroup] = {
    ChannelType.DIRECT: ChannelGroup.DIRECT,
    ChannelType.OTA: ChannelGroup.OTA,
    ChannelType.TOUR_OPERATOR: ChannelGroup.OTHER,
    ChannelType.AGENCY: ChannelGroup.OTHER,
    ChannelType.CORPORATE: ChannelGroup.OTHER,
    ChannelType.OTHER: ChannelGroup.OTHER,
}

# The deterministic dictionary (Part "DETERMINISTIC OTA/DIRECT RULES"): deliberately small,
# matched EXACTLY on the normalised label (`app.modules.bookings.text.normalize_key`, the same
# normalisation `BookingChannel.normalized_name` was stored with - never re-normalised here).
# A generic label ("web", "online", "reservation") is intentionally absent: on its own it is
# ambiguous and stays UNKNOWN.
OTA_NORMALIZED_NAMES: frozenset[str] = frozenset(
    {
        "booking com",
        "booking",
        "expedia",
        "hotels com",
        "agoda",
        "airbnb",
        "vrbo",
        "hostelworld",
    }
)

DIRECT_NORMALIZED_NAMES: frozenset[str] = frozenset(
    {
        "direct",
        "diretto",
        "website direct",
        "sito diretto",
        "phone direct",
        "walk in",
    }
)

# Real, named intermediaries that are clearly NOT OTA: OTHER, never guessed into OTA.
OTHER_NORMALIZED_NAMES: frozenset[str] = frozenset(
    {
        "wholesaler",
        "tour operator",
        "corporate",
        "agency",
    }
)


def _deterministic_group(normalized_name: str) -> ChannelGroup | None:
    if normalized_name in OTA_NORMALIZED_NAMES:
        return ChannelGroup.OTA
    if normalized_name in DIRECT_NORMALIZED_NAMES:
        return ChannelGroup.DIRECT
    if normalized_name in OTHER_NORMALIZED_NAMES:
        return ChannelGroup.OTHER
    return None


class ChannelRow(NamedTuple):
    """The minimal projection of a `BookingChannel` the classifier needs."""

    channel_id: UUID
    normalized_name: str
    channel_type: ChannelType
    is_verified: bool


def classify_channel(row: ChannelRow) -> ChannelClassification:
    if row.is_verified:
        return ChannelClassification(
            channel_id=row.channel_id,
            group=_CANONICAL_GROUP[row.channel_type],
            method=ChannelClassificationMethod.CANONICAL_SOURCE,
            confidence=CONFIDENCE_CANONICAL_SOURCE,
            normalized_label=row.normalized_name,
        )
    deterministic = _deterministic_group(row.normalized_name)
    if deterministic is not None:
        return ChannelClassification(
            channel_id=row.channel_id,
            group=deterministic,
            method=ChannelClassificationMethod.DETERMINISTIC_RULE,
            confidence=CONFIDENCE_DETERMINISTIC_RULE,
            normalized_label=row.normalized_name,
        )
    return ChannelClassification(
        channel_id=row.channel_id,
        group=ChannelGroup.UNKNOWN,
        method=ChannelClassificationMethod.UNCLASSIFIED,
        confidence=CONFIDENCE_UNCLASSIFIED,
        normalized_label=row.normalized_name,
    )


def classify_channels(rows: list[ChannelRow]) -> dict[UUID, ChannelClassification]:
    """Classify every channel of a property in memory; never touches the database."""
    return {row.channel_id: classify_channel(row) for row in rows}

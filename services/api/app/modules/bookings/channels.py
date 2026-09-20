"""Booking channel naming and classification (deterministic, no guessing)."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.bookings.models import ChannelType
from app.modules.bookings.text import normalize_key

# The ONLY built-in classification: a handful of names that are unambiguous. Everything else is
# OTHER + unverified. A type that comes from here is a hint (still unverified); a type given
# explicitly in the mapping profile is the customer's decision (verified).
KNOWN_CHANNEL_TYPES: Mapping[str, ChannelType] = {
    "booking com": ChannelType.OTA,
    "expedia": ChannelType.OTA,
    "airbnb": ChannelType.OTA,
    "direct": ChannelType.DIRECT,
    "diretto": ChannelType.DIRECT,
}


def normalize_channel_name(raw: str) -> str:
    """ "Booking.com", "BOOKING.COM" and "booking com" all give "booking com"."""
    return normalize_key(raw)


@dataclass(frozen=True)
class ChannelOverride:
    """What the mapping profile says about one raw channel label."""

    name: str | None = None
    channel_type: ChannelType | None = None


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    normalized_name: str
    channel_type: ChannelType
    is_verified: bool


def resolve_channel(raw_label: str, channel_mapping: Mapping[str, ChannelOverride]) -> ChannelSpec:
    """Turn a raw source label into the channel it denotes.

    Raises ValueError if the label has no letters or digits at all.
    """
    label = " ".join(raw_label.split())
    key = normalize_channel_name(label)
    if not key:
        raise ValueError("empty channel label")

    override = channel_mapping.get(key)
    name = override.name if override is not None and override.name else label
    normalized_name = normalize_channel_name(name)
    if not normalized_name:
        raise ValueError("empty channel name")

    if override is not None and override.channel_type is not None:
        return ChannelSpec(name, normalized_name, override.channel_type, is_verified=True)
    known = KNOWN_CHANNEL_TYPES.get(normalized_name)
    if known is not None:
        return ChannelSpec(name, normalized_name, known, is_verified=False)
    return ChannelSpec(name, normalized_name, ChannelType.OTHER, is_verified=False)

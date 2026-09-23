"""Part A: the channel classifier (pure, no database, no fuzzy matching)."""

from uuid import uuid4

from app.modules.bookings.models import ChannelType
from app.modules.bookings.text import normalize_key
from app.modules.intelligence.distribution.channels import ChannelRow, classify_channel
from app.modules.intelligence.distribution.types import ChannelClassificationMethod, ChannelGroup

_ID = uuid4()


def _row(
    name: str, *, channel_type: ChannelType = ChannelType.OTHER, is_verified: bool = False
) -> ChannelRow:
    return ChannelRow(_ID, normalize_key(name), channel_type, is_verified)


def test_known_ota_exact_match_is_classified_ota() -> None:
    result = classify_channel(_row("Booking.com"))
    assert result.group == ChannelGroup.OTA
    assert result.method == ChannelClassificationMethod.DETERMINISTIC_RULE
    assert result.confidence == 95


def test_known_direct_exact_match_is_classified_direct() -> None:
    result = classify_channel(_row("Direct"))
    assert result.group == ChannelGroup.DIRECT
    assert result.method == ChannelClassificationMethod.DETERMINISTIC_RULE


def test_other_intermediary_is_classified_other_not_ota() -> None:
    for name in ("Wholesaler", "Tour Operator", "Corporate", "Agency"):
        result = classify_channel(_row(name))
        assert result.group == ChannelGroup.OTHER, name
        assert result.method == ChannelClassificationMethod.DETERMINISTIC_RULE


def test_unknown_channel_stays_unknown() -> None:
    result = classify_channel(_row("Some Random Wholesaler Nobody Coded"))
    assert result.group == ChannelGroup.UNKNOWN
    assert result.method == ChannelClassificationMethod.UNCLASSIFIED
    assert result.confidence == 0


def test_case_is_normalised_before_matching() -> None:
    assert classify_channel(_row("BOOKING.COM")).group == ChannelGroup.OTA
    assert classify_channel(_row("booking.com")).group == ChannelGroup.OTA


def test_whitespace_and_punctuation_are_normalised() -> None:
    assert classify_channel(_row(" Booking . com ")).group == ChannelGroup.OTA
    assert classify_channel(_row("website-direct")).group == ChannelGroup.DIRECT


def test_ambiguous_booking_engine_is_never_booking_com() -> None:
    result = classify_channel(_row("Booking Engine"))
    assert result.group == ChannelGroup.UNKNOWN


def test_no_fuzzy_matching_of_a_near_miss() -> None:
    # "Bookings.com" (plural) and "Expedi a" are one edit away from real OTA names: never guessed.
    assert classify_channel(_row("Bookings.com")).group == ChannelGroup.UNKNOWN
    assert classify_channel(_row("Expedi a")).group == ChannelGroup.UNKNOWN


def test_classification_is_deterministic_across_repeated_calls() -> None:
    row = _row("Airbnb")
    first, second = classify_channel(row), classify_channel(row)
    assert first == second


def test_classification_performs_no_database_access() -> None:
    """`classify_channel` takes a plain `ChannelRow`, never a session: it cannot write."""
    import inspect

    from app.modules.intelligence.distribution import channels as channels_module

    source = inspect.getsource(channels_module)
    assert "Session" not in source
    assert "session" not in source


# --- canonical (verified) tier: the customer's own decision always wins -------------------------


def test_verified_canonical_source_wins_over_the_deterministic_dictionary() -> None:
    """A verified `channel_type` overrides even a name the dictionary would classify itself:
    the customer's own decision is respected, never second-guessed."""
    row = _row("Booking.com", channel_type=ChannelType.OTHER, is_verified=True)
    result = classify_channel(row)
    assert result.group == ChannelGroup.OTHER
    assert result.method == ChannelClassificationMethod.CANONICAL_SOURCE
    assert result.confidence == 100


def test_unverified_channel_type_hint_is_not_treated_as_reliable() -> None:
    """Gate 2's own unverified hint (`is_verified=False`) is NOT "canonical/reliable": step 2
    (this module's own dictionary) decides instead, exactly as if no hint existed at all."""
    row = _row("Airbnb", channel_type=ChannelType.OTA, is_verified=False)
    result = classify_channel(row)
    assert result.method == ChannelClassificationMethod.DETERMINISTIC_RULE


def test_tour_operator_agency_corporate_types_collapse_to_other_when_verified() -> None:
    for channel_type in (ChannelType.TOUR_OPERATOR, ChannelType.AGENCY, ChannelType.CORPORATE):
        row = _row("Some Named Intermediary", channel_type=channel_type, is_verified=True)
        assert classify_channel(row).group == ChannelGroup.OTHER

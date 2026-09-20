"""Channel name normalisation and classification (pure functions, no database)."""

import pytest

from app.modules.bookings.channels import (
    KNOWN_CHANNEL_TYPES,
    ChannelOverride,
    normalize_channel_name,
    resolve_channel,
)
from app.modules.bookings.models import ChannelType


@pytest.mark.parametrize(
    "raw",
    ["Booking.com", "BOOKING.COM", "booking com", " Booking . com ", "booking-com", "Booking_com"],
)
def test_case_punctuation_and_spacing_do_not_change_the_normalised_name(raw: str) -> None:
    assert normalize_channel_name(raw) == "booking com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Expedia, Inc.", "expedia inc"),
        ("B&B Hotels", "b and b hotels"),
        ("Café Ünïcode", "cafe unicode"),
        ("Tour Operator #1", "tour operator 1"),
        ("Яндекс Путешествия", "яндекс путешествия"),
    ],
)
def test_normalisation_keeps_words_digits_and_other_scripts(raw: str, expected: str) -> None:
    assert normalize_channel_name(raw) == expected


def test_normalisation_does_not_merge_different_channels() -> None:
    names = ["Booking.com", "Booking.com B.V.", "Booking", "Bookings.com", "Direct", "Direct Web"]

    assert len({normalize_channel_name(name) for name in names}) == len(names)


def test_a_label_without_letters_or_digits_has_an_empty_key() -> None:
    assert normalize_channel_name("---  ...  ") == ""
    with pytest.raises(ValueError):
        resolve_channel("---", {})


def test_unknown_channels_are_other_and_unverified() -> None:
    spec = resolve_channel("Portale Ignoto XY", {})

    assert (spec.channel_type, spec.is_verified) == (ChannelType.OTHER, False)
    assert spec.name == "Portale Ignoto XY"
    assert spec.normalized_name == "portale ignoto xy"


def test_a_portal_is_not_classified_just_because_it_looks_like_one() -> None:
    for label in ("Hotel Portal", "Vacanze Online", "TravelNet OTA", "www.example-travel.com"):
        spec = resolve_channel(label, {})
        assert (spec.channel_type, spec.is_verified) == (ChannelType.OTHER, False), label


def test_the_builtin_dictionary_is_tiny_explicit_and_unverified() -> None:
    assert dict(KNOWN_CHANNEL_TYPES) == {
        "booking com": ChannelType.OTA,
        "expedia": ChannelType.OTA,
        "airbnb": ChannelType.OTA,
        "direct": ChannelType.DIRECT,
        "diretto": ChannelType.DIRECT,
    }
    for label in ("BOOKING.COM", "expedia", "Direct"):
        assert resolve_channel(label, {}).is_verified is False


def test_a_type_given_by_the_mapping_profile_is_the_customers_decision() -> None:
    mapping = {"agenzia rossi": ChannelOverride(channel_type=ChannelType.AGENCY)}

    spec = resolve_channel("Agenzia  Rossi", mapping)

    assert (spec.channel_type, spec.is_verified) == (ChannelType.AGENCY, True)


def test_the_mapping_profile_can_merge_labels_into_one_channel() -> None:
    mapping = {"bkg": ChannelOverride(name="Booking.com")}

    first, second = resolve_channel("BKG", mapping), resolve_channel("Booking.com", {})

    assert first.normalized_name == second.normalized_name == "booking com"
    assert first.name == "Booking.com"


def test_a_profile_type_beats_the_builtin_dictionary() -> None:
    mapping = {"booking com": ChannelOverride(channel_type=ChannelType.CORPORATE)}

    assert resolve_channel("Booking.com", mapping).channel_type == ChannelType.CORPORATE

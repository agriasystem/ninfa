"""What the VALUES of a channel column look like.

A header that says "Canale" or "Provenienza" is only half of the evidence: "Provenienza" over
"Booking.com / Expedia / Diretto" is the booking channel, over "Italia / Germania / Francia" it is
where the guest comes from. NINFA is sure only when the header AND the values agree, so the values
are checked against the words a hotel really uses for the way a booking arrived.

The words are for READING a column, not for importing it: the importer keeps the label as written
(and its own, smaller list says which of them is an OTA). Whole words only - "ota" is a channel,
"hotel" is not.
"""

from collections.abc import Iterable

from app.modules.bookings.channels import KNOWN_CHANNEL_TYPES
from app.modules.bookings.text import normalize_key
from app.modules.data_sources.semantics import fit_label
from app.modules.document_understanding.stats import ColumnStats

# By the comparison key (`normalize_key`): "Booking.com" -> "booking com", "Walk-in" -> "walk in".
_NAMES = (
    # online travel agencies and metasearch
    "booking com",
    "bookingcom",
    "booking",
    "expedia",
    "expedia com",
    "airbnb",
    "agoda",
    "hotels com",
    "hotelscom",
    "tripadvisor",
    "trivago",
    "kayak",
    "hrs",
    "ctrip",
    "trip com",
    "despegar",
    "vrbo",
    "google hotels",
    "ota",
    "gds",
    # the hotel's own
    "diretto",
    "direct",
    "sito",
    "sito web",
    "sito ufficiale",
    "sito internet",
    "website",
    "web site",
    "web",
    "booking engine",
    "motore di prenotazione",
    "whatsapp",
    # people who call, write or arrive
    "telefono",
    "telefonico",
    "phone",
    "telephone",
    "tel",
    "email",
    "e mail",
    "mail",
    "walk in",
    "walkin",
    "passante",
    # agencies, operators, companies
    "agenzia",
    "agenzie",
    "agency",
    "tour operator",
    "operator",
    "corporate",
    "aziendale",
    "azienda",
)

# The codes a channel manager or a front-desk program writes for the same: only read as channels
# next to a header that already says "channel", never on their own.
_CODES = frozenset({"bdc", "exp", "abb", "abnb", "ago", "agd", "dir"})

_CHANNEL_WORDS = frozenset({*(normalize_key(name) for name in _NAMES), *_CODES}) | frozenset(
    KNOWN_CHANNEL_TYPES
)

# Where a guest comes from: the other thing "Provenienza" and "Origine" are used for.
_PLACES = frozenset(
    normalize_key(name)
    for name in (
        "Italia",
        "Italy",
        "Germania",
        "Germany",
        "Francia",
        "France",
        "Spagna",
        "Spain",
        "Regno Unito",
        "United Kingdom",
        "UK",
        "Inghilterra",
        "England",
        "USA",
        "Stati Uniti",
        "United States",
        "Svizzera",
        "Switzerland",
        "Austria",
        "Olanda",
        "Paesi Bassi",
        "Netherlands",
        "Belgio",
        "Belgium",
        "Polonia",
        "Poland",
        "Russia",
        "Cina",
        "China",
        "Giappone",
        "Japan",
        "Canada",
        "Australia",
        "Brasile",
        "Brazil",
        "Svezia",
        "Sweden",
        "Danimarca",
        "Denmark",
        "Norvegia",
        "Norway",
        "Finlandia",
        "Finland",
        "Irlanda",
        "Ireland",
        "Portogallo",
        "Portugal",
        "Grecia",
        "Greece",
        "Repubblica Ceca",
        "Czech Republic",
        "Ungheria",
        "Hungary",
        "Romania",
        "Turchia",
        "Turkey",
        "Israele",
        "Israel",
        "India",
        "Argentina",
        "Messico",
        "Mexico",
    )
)

# How much of a column must read as channels (or as places) to say what it is.
_MAJORITY = 0.6


def _padded(text: str) -> str:
    return f" {normalize_key(text)} "


def is_channel_word(text: str) -> bool:
    """Is this value a way a booking arrives (an OTA, the website, the phone, an agency...)?"""
    padded = _padded(text)
    return any(f" {word} " in padded for word in _CHANNEL_WORDS if word)


def is_place(text: str) -> bool:
    return normalize_key(text) in _PLACES


def channel_share(texts: Iterable[str], taught: frozenset[str] = frozenset()) -> float:
    """The part of these distinct values that are channels, by NINFA's words or by what the hotel
    has already taught (the normalised labels of its channel mapping)."""
    values = list(texts)
    if not values:
        return 0.0
    known = sum(1 for text in values if is_channel_word(text) or normalize_key(text) in taught)
    return known / len(values)


def fit_channel(stats: ColumnStats) -> float:
    """How well the values of a column fit "the channel of a booking".

    1.0   most of the distinct values are channels (the header is then confirmed by the rows)
    0.1   most are countries: where the guest comes from, not how the booking arrived
    else  text that repeats but that NINFA cannot read as channels: a maybe, never a certainty
    """
    base = fit_label(stats)
    if not base or not stats.texts:
        return base
    if channel_share(stats.texts) >= _MAJORITY:
        return 1.0
    if sum(1 for text in stats.texts if is_place(text)) / len(stats.texts) >= _MAJORITY:
        return 0.1
    return 0.8 * base


__all__ = ["channel_share", "fit_channel", "is_channel_word", "is_place"]

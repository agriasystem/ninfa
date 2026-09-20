"""Deterministic mapping suggestions (no AI, no learning).

A suggestion is only a proposal shown to the customer. It never becomes a mapping by itself:
only an explicitly saved profile does (`BookingImportService.save_mapping`).
"""

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.bookings.mapping import FIELD_ORDER, CanonicalField, normalize_header

F = CanonicalField


class SuggestionConfidence(StrEnum):
    HIGH = "HIGH"  # the header is a known alias of the field
    MEDIUM = "MEDIUM"  # very similar to a known alias
    LOW = "LOW"  # somewhat similar to a known alias
    NONE = "NONE"  # nothing suggested


class SuggestionReason(StrEnum):
    KNOWN_ALIAS = "KNOWN_ALIAS"
    FUZZY_MATCH = "FUZZY_MATCH"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class MappingSuggestion:
    canonical_field: CanonicalField
    suggested_source_column: str | None
    confidence: SuggestionConfidence
    reason: SuggestionReason
    score: float = 0.0


# Known headers of common PMS/channel exports, Italian and English. Compared after
# `normalize_header` (case, accents and punctuation ignored), so "Check-in" == "check in".
FIELD_ALIASES: Mapping[CanonicalField, tuple[str, ...]] = {
    F.SOURCE_RECORD_ID: (
        "booking id",
        "booking number",
        "booking reference",
        "reservation id",
        "reservation number",
        "reservation code",
        "confirmation number",
        "confirmation code",
        "reference",
        "id prenotazione",
        "codice prenotazione",
        "numero prenotazione",
        "n prenotazione",
        "riferimento prenotazione",
        "riferimento",
        "id",
    ),
    F.BOOKED_AT: (
        "booked at",
        "booked on",
        "booking date",
        "booking created",
        "created at",
        "created on",
        "creation date",
        "reservation date",
        "date booked",
        "data prenotazione",
        "data di prenotazione",
        "data creazione",
        "data inserimento",
        "prenotato il",
    ),
    F.CHECK_IN: (
        "check in",
        "checkin",
        "arrival",
        "arrival date",
        "date of arrival",
        "data arrivo",
        "data di arrivo",
        "arrivo",
        "data check in",
        "data checkin",
    ),
    F.CHECK_OUT: (
        "check out",
        "checkout",
        "departure",
        "departure date",
        "date of departure",
        "data partenza",
        "data di partenza",
        "partenza",
        "data check out",
        "data checkout",
    ),
    F.STATUS: (
        "status",
        "booking status",
        "reservation status",
        "stato",
        "stato prenotazione",
    ),
    F.ROOMS: (
        "rooms",
        "room count",
        "number of rooms",
        "no of rooms",
        "n rooms",
        "camere",
        "n camere",
        "num camere",
        "numero camere",
        "numero di camere",
        "n° camere",
    ),
    F.GUESTS: (
        "guests",
        "number of guests",
        "no of guests",
        "pax",
        "ospiti",
        "n ospiti",
        "num ospiti",
        "numero ospiti",
        "numero di ospiti",
        "persone",
        "n persone",
    ),
    F.ROOM_REVENUE: (
        "room revenue",
        "room amount",
        "room total",
        "room price",
        "accommodation",
        "revenue",
        "importo camera",
        "totale camera",
        "ricavo camera",
        "importo soggiorno",
        "totale soggiorno",
        "prezzo camera",
        "importo pernottamento",
    ),
    F.TOTAL_REVENUE: (
        "total revenue",
        "total amount",
        "total price",
        "grand total",
        "total",
        "importo totale",
        "totale prenotazione",
        "totale",
        "prezzo totale",
        "totale generale",
    ),
    F.CHANNEL: (
        "channel",
        "booking channel",
        "booking source",
        "source",
        "distribution channel",
        "canale",
        "canale di vendita",
        "provenienza",
        "fonte",
        "origine",
    ),
    F.COMMISSION_AMOUNT: (
        "commission",
        "commission amount",
        "commissions",
        "commissione",
        "commissioni",
        "importo commissione",
        "importo commissioni",
    ),
    F.COMMISSION_RATE: (
        "commission rate",
        "commission percent",
        "commission pct",
        "commission percentage",
        "percentuale commissione",
        "commissione percentuale",
        "aliquota commissione",
        "perc commissione",
    ),
    F.CANCELLED_AT: (
        "cancelled at",
        "canceled at",
        "cancelled on",
        "canceled on",
        "cancellation date",
        "date cancelled",
        "data cancellazione",
        "data annullamento",
        "cancellato il",
        "annullato il",
    ),
    F.ROOM_TYPE: (
        "room type",
        "room category",
        "room name",
        "accommodation type",
        "tipo camera",
        "tipologia camera",
        "tipologia",
        "categoria camera",
        "camera",
    ),
    F.RATE_PLAN: (
        "rate plan",
        "rate code",
        "rate name",
        "rate",
        "tariffa",
        "piano tariffario",
        "codice tariffa",
        "nome tariffa",
    ),
}

_NORMALISED_ALIASES: dict[CanonicalField, tuple[str, ...]] = {
    field: tuple(normalize_header(alias) for alias in aliases)
    for field, aliases in FIELD_ALIASES.items()
}

MEDIUM_THRESHOLD = 0.88
LOW_THRESHOLD = 0.78


@dataclass(frozen=True)
class _Candidate:
    field: CanonicalField
    header: str
    score: float
    exact: bool


def _candidates(headers: Sequence[str]) -> list[_Candidate]:
    result: list[_Candidate] = []
    for header in headers:
        key = normalize_header(header)
        if not key:
            continue
        for field, aliases in _NORMALISED_ALIASES.items():
            if key in aliases:
                result.append(_Candidate(field, header, 1.0, exact=True))
                continue
            best = max(difflib.SequenceMatcher(None, key, alias).ratio() for alias in aliases)
            if best >= LOW_THRESHOLD:
                result.append(_Candidate(field, header, best, exact=False))
    return result


def suggest_mapping(headers: Sequence[str]) -> list[MappingSuggestion]:
    """One suggestion per canonical field (in canonical order), each header used at most once.

    Known aliases outrank fuzzy matches; among equals the canonical field order and the file's
    column order decide, so the result is fully deterministic.
    """
    order = {field: position for position, field in enumerate(FIELD_ORDER)}
    column = {header: position for position, header in reversed(list(enumerate(headers)))}
    ranked = sorted(
        _candidates(headers),
        key=lambda c: (not c.exact, -c.score, order[c.field], column[c.header]),
    )

    chosen: dict[CanonicalField, _Candidate] = {}
    used_headers: set[str] = set()
    for candidate in ranked:
        if candidate.field in chosen or candidate.header in used_headers:
            continue
        chosen[candidate.field] = candidate
        used_headers.add(candidate.header)

    suggestions: list[MappingSuggestion] = []
    for field in FIELD_ORDER:
        pick = chosen.get(field)
        if pick is None:
            suggestions.append(
                MappingSuggestion(field, None, SuggestionConfidence.NONE, SuggestionReason.NO_MATCH)
            )
        elif pick.exact:
            suggestions.append(
                MappingSuggestion(
                    field,
                    pick.header,
                    SuggestionConfidence.HIGH,
                    SuggestionReason.KNOWN_ALIAS,
                    1.0,
                )
            )
        else:
            confidence = (
                SuggestionConfidence.MEDIUM
                if pick.score >= MEDIUM_THRESHOLD
                else SuggestionConfidence.LOW
            )
            suggestions.append(
                MappingSuggestion(
                    field,
                    pick.header,
                    confidence,
                    SuggestionReason.FUZZY_MATCH,
                    pick.score,
                )
            )
    return suggestions

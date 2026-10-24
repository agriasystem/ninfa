"""Deterministic mapping suggestions (no AI, no learning).

A suggestion is only a proposal shown to the customer. It never becomes a mapping by itself:
only an explicitly saved profile does (`BookingImportService.save_mapping`).

The ranking itself is shared with the other file domains (`app.modules.ingestion.suggestions`);
this module only brings the booking fields and the known names of their columns.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.modules.bookings.mapping import FIELD_ORDER, CanonicalField
from app.modules.ingestion.suggestions import (
    LOW_THRESHOLD,
    MEDIUM_THRESHOLD,
    SuggestionConfidence,
    SuggestionReason,
    suggest_fields,
)

F = CanonicalField

__all__ = [
    "FIELD_ALIASES",
    "LOW_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "MappingSuggestion",
    "SuggestionConfidence",
    "SuggestionReason",
    "suggest_mapping",
]


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


def suggest_mapping(headers: Sequence[str]) -> list[MappingSuggestion]:
    """One suggestion per canonical field (in canonical order), each header used at most once.

    Known aliases outrank fuzzy matches; among equals the canonical field order and the file's
    column order decide, so the result is fully deterministic.
    """
    return [
        MappingSuggestion(
            suggestion.field,
            suggestion.column,
            suggestion.confidence,
            suggestion.reason,
            suggestion.score,
        )
        for suggestion in suggest_fields(headers, aliases=FIELD_ALIASES, order=FIELD_ORDER)
    ]

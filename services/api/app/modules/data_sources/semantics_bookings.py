"""What the columns of a bookings file mean, read by words and checked against their values.

The same booking says "Arrivo", "Check-in", "Check in date", "Arrival", "Dal" depending on who
exported it; its channel says "Canale", "Provenienza", "Source", "Portale"; its code says "Codice
prenotazione", "Reservation ID", "Confirmation number". NINFA keeps no guest identity (a column of
guest names is recognised so it can be left out), and a column that says "Ospiti" over small
whole numbers is a COUNT of guests, not a name.
"""

from app.modules.bookings.mapping import FIELD_ORDER, CanonicalField
from app.modules.bookings.statuses import BUILTIN_STATUS_KEYS
from app.modules.bookings.suggestions import FIELD_ALIASES
from app.modules.bookings.text import normalize_key
from app.modules.data_sources.channel_words import fit_channel
from app.modules.data_sources.relations import Relation, stay_dates
from app.modules.data_sources.semantics import (
    AmbiguousColumn,
    DomainSem,
    FieldSem,
    fit_date,
    fit_label,
    fit_money,
    fit_percentage,
    fit_small_integer,
    fit_text,
    fit_unique_identifier,
    fit_vocabulary,
    rule,
)
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.text import stems
from app.modules.ingestion.models import DataSourceDomain

F = CanonicalField


def _exact(field: CanonicalField, *extra: str) -> tuple[str, ...]:
    return (*FIELD_ALIASES.get(field, ()), *extra, field.value)


def _is_status(text: str) -> bool:
    return normalize_key(text) in BUILTIN_STATUS_KEYS


_OTHER_DATES = "arrivo partenza arrival departure check cancellazione cancellato annullamento"

BOOKINGS = DomainSem(
    domain=DataSourceDomain.BOOKINGS,
    fields={
        F.SOURCE_RECORD_ID.value: FieldSem(
            F.SOURCE_RECORD_ID.value,
            _exact(F.SOURCE_RECORD_ID),
            (
                rule(
                    "prenotazione prenotazioni reservation booking book conferma confirmation pren "
                    "conf pratica dossier",
                    "codice id numero riferimento rif code reference number cod",
                    none="gruppo group",  # a group is a set of bookings, not one
                    weight=0.9,
                ),
                rule("res reservation", "numero id codice", weight=0.85),
                # the number a file is known by at the desk or the agency
                rule("pratica pratiche dossier", weight=0.85),
                rule("localizzatore locator", weight=0.88),
                # "Ref." alone: the reference of the reservation.
                rule("ref rif riferimento reference", weight=0.85),
                # "Codice" alone in a bookings file is very likely the reservation code, but only
                # likely: it is proposed, to be checked.
                rule("codice code cod", none="gruppo group", weight=0.7),
            ),
            fit_unique_identifier,
        ),
        F.BOOKED_AT.value: FieldSem(
            F.BOOKED_AT.value,
            _exact(F.BOOKED_AT),
            (
                rule(
                    "data date",
                    "prenotazione prenotazioni booking reservation creazione inserimento pren "
                    "registrazione registration entry",
                    none=_OTHER_DATES,
                    weight=0.9,
                ),
                rule(
                    "creata creato created prenotato booked inserita bkd bkg registrata "
                    "registrato inserito entered recorded",
                    none="cancellata",
                    weight=0.8,
                ),
                # "Prenotata in data", "Booked on date": the verb says it, the date is the noun
                rule(
                    "creata creato created prenotato booked registrata registrato",
                    "data date il on",
                    none="cancellata arrivo arrival partenza departure",
                    weight=0.86,
                ),
            ),
            fit_date,
        ),
        F.CHECK_IN.value: FieldSem(
            F.CHECK_IN.value,
            _exact(F.CHECK_IN),
            (
                rule(
                    "arrivo arrival checkin arrivi arr ingresso entrata",
                    none="partenza departure out uscita",
                    weight=0.93,
                ),
                rule("check", "in", none="out", weight=0.93),
                # "CI": only a maybe by itself (an identity card is "C.I." too); its values and
                # its partner "CO" settle it
                rule("ci", none="co", weight=0.75),
                rule("inizio start", "soggiorno stay", weight=0.85),
                rule("start begin", "date data", weight=0.8),
                rule("stay soggiorno", "from dal", weight=0.85),
                # "Dal" alone: only a likely arrival when its partner "Al" is there (`pairs`).
                rule("dal from", weight=0.7),
            ),
            fit_date,
            value_only=True,
        ),
        F.CHECK_OUT.value: FieldSem(
            F.CHECK_OUT.value,
            _exact(F.CHECK_OUT),
            (
                rule(
                    "partenza departure checkout partenze part dep uscita",
                    none="arrivo arrival in ingresso entrata",
                    weight=0.93,
                ),
                rule("check", "out", weight=0.93),
                rule("co", none="ci", weight=0.75),
                rule("fine end", "soggiorno stay", weight=0.85),
                rule("end", "date data", weight=0.8),
                rule("stay soggiorno", "to al fino", weight=0.85),
                rule("al to", weight=0.7),
            ),
            fit_date,
        ),
        F.STATUS.value: FieldSem(
            F.STATUS.value,
            _exact(F.STATUS),
            (rule("stato status situazione", none="pagamento civile", weight=0.9),),
            fit_vocabulary(_is_status),
        ),
        F.ROOMS.value: FieldSem(
            F.ROOMS.value,
            _exact(F.ROOMS),
            (
                rule(
                    "camere camera rooms room cam stanze stanza rms",
                    "numero num qta quantita n prenotate prenotata booked count totale",
                    none="tipo tipologia categoria type",
                    weight=0.9,
                ),
                # the plural / the abbreviation on its own is a count of rooms ("Camera" is not:
                # it is as often the room itself)
                rule("stanze rms rooms camere", none="tipo tipologia categoria type", weight=0.9),
            ),
            fit_small_integer(100),
        ),
        F.ROOM_REVENUE.value: FieldSem(
            F.ROOM_REVENUE.value,
            _exact(F.ROOM_REVENUE),
            (
                rule(
                    "ricavo importo totale revenue prezzo amount tot imp earnings corrispettivo "
                    "fatturato incasso incassi charges charge valore value rev",
                    "camera camere room rooms cam soggiorno pernottamento lodging accommodation "
                    "alloggio",
                    none="commissione commission",
                    weight=0.9,
                ),
            ),
            fit_money,
        ),
        F.CHANNEL.value: FieldSem(
            F.CHANNEL.value,
            _exact(F.CHANNEL),
            (
                rule(
                    "canale channel provenienza source portale origine fonte ota agenzia src can",
                    none="data codice id numero",
                    weight=0.9,
                ),
                # "Prenotato tramite", "Booked via": the channel the booking came through
                rule(
                    "tramite via through attraverso",
                    "prenotato booked venduto sold prenotazione booking",
                    weight=0.88,
                ),
            ),
            fit_channel,
        ),
        F.GUESTS.value: FieldSem(
            F.GUESTS.value,
            _exact(F.GUESTS),
            (rule("ospiti guests pax persone adulti", none="nome name cognome", weight=0.9),),
            fit_small_integer(60),
        ),
        F.TOTAL_REVENUE.value: FieldSem(
            F.TOTAL_REVENUE.value,
            _exact(F.TOTAL_REVENUE),
            (
                rule(
                    "totale importo total revenue",
                    "prenotazione booking generale grand soggiorno",
                    none="camera camere room",
                    weight=0.88,
                ),
            ),
            fit_money,
        ),
        F.COMMISSION_AMOUNT.value: FieldSem(
            F.COMMISSION_AMOUNT.value,
            _exact(F.COMMISSION_AMOUNT),
            (
                rule(
                    "commissione commissioni commission provvigione comm",
                    # ("Netto dopo commissioni" is what is left AFTER the commission)
                    none="percentuale perc rate aliquota netto net dopo after",
                    weight=0.9,
                ),
            ),
            fit_money,
        ),
        F.COMMISSION_RATE.value: FieldSem(
            F.COMMISSION_RATE.value,
            _exact(F.COMMISSION_RATE),
            (
                rule(
                    "commissione commissioni commission",
                    "percentuale perc percent rate aliquota",
                    weight=0.9,
                ),
            ),
            fit_percentage,
        ),
        F.CANCELLED_AT.value: FieldSem(
            F.CANCELLED_AT.value,
            _exact(F.CANCELLED_AT),
            (
                rule(
                    "cancellazione cancellato cancelled annullamento annullato canceled",
                    "data date il on",
                    weight=0.9,
                ),
            ),
            fit_date,
        ),
        F.ROOM_TYPE.value: FieldSem(
            F.ROOM_TYPE.value,
            _exact(F.ROOM_TYPE),
            (rule("tipo tipologia categoria type", "camera room", weight=0.9),),
            fit_label,
        ),
        F.RATE_PLAN.value: FieldSem(
            F.RATE_PLAN.value,
            _exact(F.RATE_PLAN),
            (
                rule(
                    "tariffa rate piano trattamento pensione board meal",
                    none="commissione commission",
                    weight=0.85,
                ),
            ),
            fit_text,
        ),
    },
    order=tuple(field.value for field in FIELD_ORDER),
    title_words=stems(
        "prenotazioni prenotazione booking reservations reservation arrivi registro camere ospiti "
        "pms channel canali"
    ),
    locked={
        PiiKind.PERSON_NAME: "PERSON",
        PiiKind.EMAIL: "CONTACT",
        PiiKind.PHONE: "CONTACT",
        PiiKind.TAX_CODE: "IDENTITY",
        PiiKind.IBAN: "IDENTITY",
    },
    pairs=(((F.CHECK_IN.value, "dal"), (F.CHECK_OUT.value, "al")),),
    relations=(Relation(F.CHECK_IN.value, F.CHECK_OUT.value, stay_dates),),
    context=stems("prenotazione prenotazioni booking bookings reservation reservations"),
    financial=frozenset(
        {
            F.ROOM_REVENUE.value,
            F.TOTAL_REVENUE.value,
            F.COMMISSION_AMOUNT.value,
            F.COMMISSION_RATE.value,
        }
    ),
    ambiguous=(
        AmbiguousColumn(
            "AMOUNT",
            stems("importo prezzo amount revenue ricavo totale price imp earnings"),
            stems("camera camere room rooms soggiorno commissione commission prenotazione booking"),
            (F.ROOM_REVENUE.value, F.TOTAL_REVENUE.value),
            fit_money,
        ),
    ),
)


__all__ = ["BOOKINGS"]

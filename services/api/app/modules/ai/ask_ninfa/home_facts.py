"""The deterministic, semantic facts Mia Home may be handed on top of the Decision Feed context.

ENGINE CALCULATES. MIA EXPLAINS. Every number in an `OperationalSection` was computed (or read) by
application code - a stored snapshot, an existing detector service, a plain sum in
`home_data_service.py` - never by the language model, and never from raw records handed to it. The
model receives only these small, labelled sections: "occupazione sulle prenotazioni attuali, i
prossimi 7 giorni: 62,50 %", never the bookings behind it.

A section carries its own GROUNDING REF (`metric:occupancy:2026-10-09:2026-10-15`,
`coverage:distribution`, ...): the structured response metadata saying which facts an answer drew
on. Refs are never shown to the end user. The per-request vocabulary of refs a model may name is the
fixed base set plus exactly the refs present in THIS request's context (`grounding_vocabulary`).

"Not available" is a first-class value: `not_available` lists, in plain Italian, what NINFA cannot
determine for the question asked (an unsupported concept, a period with no data, an area not
analysed), so Mia says precisely what is missing instead of falling back to a generic sentence.
"""

from dataclasses import dataclass

from app.modules.ai.ask_ninfa.home_vocabulary import HomeIntent, UnsupportedTopic
from app.modules.ai.ask_ninfa.types import AskDataPoint

# One table row: ordered (label, value) pairs, serialised as a JSON object with Italian keys.
Row = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OperationalSection:
    """One group of related facts. `ref` is its grounding ref; `period` the Italian phrase of the
    period it covers, if any; `data` the headline figures; `rows` an optional small table (for
    example one row per night); `note` one plain caveat about how to read THIS section."""

    ref: str
    title: str
    period: str | None
    data: tuple[AskDataPoint, ...]
    rows: tuple[Row, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class OperationalContext:
    """What the question needed beyond the Decision Feed. `topics` are the Italian labels of what
    the question was understood to be about (empty = not placed: Mia answers from the overview and
    from `supported_topics`); `from_previous_question` says the topic was taken from the user's
    previous question (a follow-up such as "Perché?")."""

    topics: tuple[str, ...]
    from_previous_question: bool
    sections: tuple[OperationalSection, ...]
    not_available: tuple[str, ...]
    supported_topics: tuple[str, ...] = ()

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(section.ref for section in self.sections)


INTENT_LABELS: dict[HomeIntent, str] = {
    HomeIntent.DECISIONS: "decisioni e problemi di oggi",
    HomeIntent.PRIORITY: "priorità di oggi",
    HomeIntent.DISTRIBUTION: "distribuzione e canali (OTA, diretto)",
    HomeIntent.BOOKINGS: "prenotazioni",
    HomeIntent.OCCUPANCY: "occupazione",
    HomeIntent.REVENUE: "ricavi camera sulle prenotazioni",
    HomeIntent.COSTS: "costi",
    HomeIntent.LABOR: "personale",
    HomeIntent.FRESHNESS: "ultimo import dei dati",
    HomeIntent.COVERAGE: "dati e aree analizzati",
    HomeIntent.COMPARISON: "confronto tra le aree",
}

# What Mia can actually answer today - handed over when a question could not be placed, so the model
# can say exactly what NINFA CAN do instead of improvising or falling back to a generic sentence.
SUPPORTED_TOPICS: tuple[str, ...] = (
    "decisioni di oggi e loro priorità (ordine di NINFA)",
    "distribuzione: quota OTA e diretta, peso dei singoli canali (prossimi 30 giorni)",
    "prenotazioni, occupazione e ricavi camera sulle prenotazioni attuali (da oggi in avanti)",
    "stato dell'analisi di costi e personale (tramite le decisioni)",
    "dati usati, aree analizzate, ultimo import delle prenotazioni",
)

# Plain Italian, one fixed sentence per concept NINFA does not compute (never guessed by the model).
UNSUPPORTED_NOTES: dict[UnsupportedTopic, str] = {
    UnsupportedTopic.ACCOUNTING_REVENUE: (
        "NINFA non ha un dato di fatturato, incassi, margine o utile: non sono la stessa cosa dei "
        "ricavi camera registrati sulle prenotazioni, e non vanno confusi"
    ),
    UnsupportedTopic.REVPAR: "NINFA non calcola il RevPAR",
    UnsupportedTopic.CANCELLATIONS: (
        "NINFA non calcola un indicatore su cancellazioni o no-show: non posso dire quante ce ne "
        "siano"
    ),
    UnsupportedTopic.MARKET: (
        "NINFA non ha dati su mercato o concorrenti: non posso confrontare la struttura con altre"
    ),
    UnsupportedTopic.COMMISSIONS: (
        "NINFA non calcola l'importo delle commissioni pagate ai canali; può solo dire quanto "
        "pesano i canali sulle prenotazioni"
    ),
    UnsupportedTopic.INCIDENCE: (
        "NINFA non definisce un'incidenza (quanto 'pesa' il personale o i costi sul totale): "
        "dispone solo delle decisioni e del loro stato"
    ),
    UnsupportedTopic.FORECAST: (
        "NINFA non fornisce previsioni di ricavi o di occupazione finale fuori dalle decisioni: i "
        "valori di occupazione e ricavi qui sono quelli delle prenotazioni attuali, non una "
        "previsione"
    ),
    UnsupportedTopic.WEEKEND: (
        "'weekend' non è un periodo che NINFA definisca: chiedi un giorno preciso (per esempio "
        "sabato) o un intervallo (per esempio i prossimi 7 giorni)"
    ),
}

__all__ = [
    "INTENT_LABELS",
    "SUPPORTED_TOPICS",
    "UNSUPPORTED_NOTES",
    "OperationalContext",
    "OperationalSection",
    "Row",
]

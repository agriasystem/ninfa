"""The hospitality vocabulary Mia Home understands: explicit, hand-audited aliases (never a model's
guess) that map the words of a hotel owner onto NINFA's closed topics.

"Gli OTA sono a posto?", "Quanto pesa Booking?", "come stanno andando i portali", "gli OTS sono
apposto?" must all mean the same thing without the owner learning NINFA's internal vocabulary. The
words below are the whole of that knowledge:

- INTENT_WORDS / INTENT_PHRASES: topic aliases (normalised: lower case, no accents, punctuation
  turned into spaces - see `normalize_text`).
- CHANNEL_WORDS: named distribution channels (Booking, Expedia, ...), the same names the channel
  classification already treats as OTA (`distribution/channels.py`).
- TYPOS: a short, explicit table of typos that are common AND unambiguous. A 3-letter acronym like
  "ota" cannot be matched by edit distance without false positives, so its typos are listed.
- UNSUPPORTED_*: concepts a hotel owner will ask about that NINFA does NOT compute (fatturato,
  RevPAR, cancellazioni, ...). Recognising them lets Mia say exactly what is missing instead of
  falling back to a generic sentence - and keeps accounting concepts from being silently merged
  ("ricavi camera sulle prenotazioni" is not "fatturato").

Typo tolerance beyond the table is deliberately modest (`fuzzy_alias`): one edit for words of 5-8
letters, two for longer ones, only against single-word aliases of 5+ letters, never when it would be
ambiguous between two topics. Anything subtler is left to the model, which still receives the
generic overview context.
"""

import re
import unicodedata
from enum import StrEnum

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_text(text: str) -> str:
    """Lower case, accents stripped, every run of punctuation/space a single space.
    "Qual è la priorità?" -> "qual e la priorita"; "OTA's" -> "ota s";
    "booking.com" -> "booking com"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", stripped).strip()


class HomeIntent(StrEnum):
    """The closed set of things Mia Home can be asked about. A question maps to one or more of
    these (or UNKNOWN); an intent only ever SELECTS which deterministic facts are fetched - it never
    carries a business fact itself."""

    DECISIONS = "DECISIONS"
    PRIORITY = "PRIORITY"
    DISTRIBUTION = "DISTRIBUTION"
    BOOKINGS = "BOOKINGS"
    OCCUPANCY = "OCCUPANCY"
    REVENUE = "REVENUE"
    COSTS = "COSTS"
    LABOR = "LABOR"
    FRESHNESS = "FRESHNESS"
    COVERAGE = "COVERAGE"
    COMPARISON = "COMPARISON"
    UNKNOWN = "UNKNOWN"


class UnsupportedTopic(StrEnum):
    ACCOUNTING_REVENUE = "ACCOUNTING_REVENUE"  # fatturato, incassi, margine, utile
    REVPAR = "REVPAR"
    CANCELLATIONS = "CANCELLATIONS"
    MARKET = "MARKET"  # concorrenti, mercato
    COMMISSIONS = "COMMISSIONS"  # the amount paid in commissions
    INCIDENCE = "INCIDENCE"  # "quanto pesa il personale / i costi"
    FORECAST = "FORECAST"  # previsioni, "a fine mese"
    WEEKEND = "WEEKEND"  # not a defined period


# --- topic aliases (single words) --------------------------------------------------------------

INTENT_WORDS: dict[HomeIntent, frozenset[str]] = {
    HomeIntent.DISTRIBUTION: frozenset(
        {
            "ota",
            "portali",
            "portale",
            "intermediari",
            "intermediario",
            "intermediazione",
            "canali",
            "canale",
            "distribuzione",
            "diretto",
            "diretta",
            "direct",
            "dirette",
        }
    ),
    HomeIntent.BOOKINGS: frozenset(
        {"prenotazioni", "prenotazione", "prenotate", "prenotato", "prenotati", "pickup", "ritmo"}
    ),
    HomeIntent.OCCUPANCY: frozenset(
        {
            "occupazione",
            "occupate",
            "occupata",
            "occupati",
            "occupato",
            "riempimento",
            "riempite",
            "occupancy",
        }
    ),
    HomeIntent.REVENUE: frozenset(
        {"ricavi", "ricavo", "revenue", "fatturato", "incassi", "incasso", "adr", "fatturare"}
    ),
    HomeIntent.COSTS: frozenset(
        {"costi", "costo", "spese", "spesa", "cpor", "spendendo", "spendo", "spendiamo", "speso"}
    ),
    HomeIntent.LABOR: frozenset(
        {
            "personale",
            "staff",
            "turni",
            "turno",
            "ore",
            "dipendenti",
            "organico",
            "sovradimensionato",
            "sovradimensionata",
            "overstaffing",
        }
    ),
    HomeIntent.DECISIONS: frozenset(
        {
            "decisioni",
            "decisione",
            "problemi",
            "problema",
            "criticita",
            "anomalie",
            "anomalia",
            "segnalazioni",
            "alert",
            "attenzione",
        }
    ),
    HomeIntent.PRIORITY: frozenset(
        {"priorita", "prioritaria", "prioritario", "prioritari", "urgente", "urgenza", "urgenti"}
    ),
    HomeIntent.FRESHNESS: frozenset(
        {
            "import",
            "importati",
            "importato",
            "importazione",
            "importazioni",
            "aggiornati",
            "aggiornato",
            "aggiornamento",
            "aggiornamenti",
        }
    ),
    HomeIntent.COVERAGE: frozenset(
        {"analizzato", "analizzati", "analizzata", "analizzate", "copertura", "aree"}
    ),
}

# --- topic aliases (multi-word, matched on the normalised text) ----------------------------------

INTENT_PHRASES: dict[HomeIntent, tuple[str, ...]] = {
    HomeIntent.DISTRIBUTION: (
        "online travel agency",
        "online travel agencies",
        "agenzie online",
        "agenzia online",
        "distribuzione indiretta",
        "dipendenza ota",
        "quota ota",
        "mix canali",
        "mix distributivo",
        "sito diretto",
    ),
    HomeIntent.BOOKINGS: ("booking pace", "ritmo prenotazioni", "camere prenotate"),
    HomeIntent.OCCUPANCY: (
        "tasso di occupazione",
        "camere occupate",
        "siamo pieni",
        "quanto siamo pieni",
        "giorni piu deboli",
        "giorni deboli",
        "giorno piu debole",
        "giorni piu bassi",
        "giorni piu vuoti",
    ),
    HomeIntent.REVENUE: ("prezzo medio", "tariffa media"),
    HomeIntent.COSTS: ("costo camera", "costo per camera", "costo per camera occupata"),
    HomeIntent.LABOR: ("ore di lavoro", "ore di personale", "costo del personale"),
    HomeIntent.DECISIONS: (
        "cosa non va",
        "cosa devo guardare",
        "cosa devo sapere",
        "situazione di oggi",
        "richiedono attenzione",
    ),
    HomeIntent.PRIORITY: (
        "da dove parto",
        "cosa guardo per prima",
        "prima cosa",
        "piu importante",
        "piu grave",
        "cosa fare prima",
    ),
    HomeIntent.FRESHNESS: ("ultimo import", "ultimi dati", "dati aggiornati", "quando sono stati"),
    HomeIntent.COVERAGE: (
        "dati ha usato",
        "dati usati",
        "dati utilizzati",
        "quali dati",
        "che dati",
        "cosa ha analizzato",
    ),
    HomeIntent.COMPARISON: (
        "area piu critica",
        "aree piu critiche",
        "quale area",
        "quali aree",
        "piu critica",
        "piu critico",
    ),
}

# "come siamo messi" is an overview of the near future, not one topic: bookings + occupancy.
OVERVIEW_PHRASES: tuple[str, ...] = ("come siamo messi", "come stiamo messi", "come siamo andando")

# "giorni piu deboli" etc. ask for the lowest-occupancy nights (descriptive, not an Engine verdict).
WEAK_DAYS_PHRASES: tuple[str, ...] = (
    "giorni piu deboli",
    "giorni deboli",
    "giorno piu debole",
    "giorni piu bassi",
    "giorni piu vuoti",
)

# Phrases where an alias would be misread ("che ore sono", "a che ora"): removed before matching.
NEUTRALISED_PHRASES: tuple[str, ...] = ("a che ora", "a che ore", "che ore", "alle ore", "che ora")

# --- named channels ----------------------------------------------------------------------------

# channel key -> the normalised words/phrases that denote it. Keys are the SAME normalised names the
# channel classification already knows as OTA (`OTA_NORMALIZED_NAMES`), so a requested channel can
# be matched against the property's own channels by its normalised name.
CHANNEL_WORDS: dict[str, tuple[str, ...]] = {
    "booking": ("booking", "booking com", "bookingcom"),
    "expedia": ("expedia",),
    "airbnb": ("airbnb",),
    "agoda": ("agoda",),
    "hotels com": ("hotels com",),
    "vrbo": ("vrbo",),
    "hostelworld": ("hostelworld",),
}

# --- explicit typos ----------------------------------------------------------------------------

TYPOS: dict[str, str] = {
    "ots": "ota",
    "oat": "ota",
    "oota": "ota",
    "otta": "ota",
    "otas": "ota",
    "bokking": "booking",
    "bookin": "booking",
    "expdia": "expedia",
    "expedya": "expedia",
}

# Everyday words one edit away from an alias that must NOT be read as that alias ("costa" is "it
# costs", not "costi"/"costo"). Exact aliases never go through the fuzzy path at all.
FUZZY_STOPLIST: frozenset[str] = frozenset({"costa", "coste", "costar", "posto", "apposto"})

# "Quali giorni sono piu deboli?": a day word and a weak word anywhere in the question (descriptive:
# the nights with the lowest occupancy on the books - NOT an Engine verdict about risk).
WEAK_DAY_NOUNS: frozenset[str] = frozenset({"giorni", "giorno", "notti", "notte", "date", "data"})
WEAK_DAY_ADJECTIVES: frozenset[str] = frozenset(
    {"deboli", "debole", "vuoti", "vuoto", "bassi", "basso", "scarichi", "scarico"}
)

# --- concepts NINFA does not compute -----------------------------------------------------------

UNSUPPORTED_WORDS: dict[UnsupportedTopic, frozenset[str]] = {
    UnsupportedTopic.ACCOUNTING_REVENUE: frozenset(
        {
            "fatturato",
            "fatturare",
            "fatturati",
            "incassi",
            "incasso",
            "incassato",
            "margine",
            "profitto",
            "utile",
            "guadagno",
            "guadagni",
            "guadagnato",
            "gop",
        }
    ),
    UnsupportedTopic.REVPAR: frozenset({"revpar"}),
    UnsupportedTopic.CANCELLATIONS: frozenset(
        {"cancellazioni", "cancellazione", "cancellate", "cancellato", "noshow"}
    ),
    UnsupportedTopic.MARKET: frozenset(
        {"concorrenti", "concorrenza", "mercato", "competitor", "competitors", "compset"}
    ),
    UnsupportedTopic.COMMISSIONS: frozenset({"commissioni", "commissione"}),
    UnsupportedTopic.FORECAST: frozenset(
        {"previsione", "previsioni", "prevedi", "prevista", "previsto", "previste"}
    ),
}
UNSUPPORTED_PHRASES: dict[UnsupportedTopic, tuple[str, ...]] = {
    UnsupportedTopic.CANCELLATIONS: ("no show",),
    UnsupportedTopic.FORECAST: ("a fine mese", "fine mese", "fine anno", "a fine anno"),
    UnsupportedTopic.WEEKEND: ("weekend", "week end", "fine settimana"),
}
# "quanto pesa il personale / i costi": an incidence ratio NINFA does not define.
INCIDENCE_WORDS: frozenset[str] = frozenset({"pesa", "pesano", "incide", "incidono", "incidenza"})

# --- bare follow-ups -----------------------------------------------------------------------------

# A question made of (only) these words has no topic of its own: it refers to the previous one.
FOLLOW_UP_WORDS: frozenset[str] = frozenset(
    {
        "perche",
        "percio",
        "mai",
        "come",
        "cioe",
        "quindi",
        "allora",
        "spiegami",
        "spiegamelo",
        "spiega",
        "meglio",
        "approfondisci",
        "dimmi",
        "di",
        "piu",
        "e",
        "ok",
        "poi",
        "ancora",
        "che",
        "vuol",
        "dire",
        "senso",
        "in",
        "questo",
        "quello",
        "quella",
        "si",
        "no",
        "grazie",
    }
)


def damerau_levenshtein(a: str, b: str) -> int:
    """Edit distance with adjacent transpositions (optimal string alignment) - enough for typos."""
    rows = len(a) + 1
    cols = len(b) + 1
    table = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        table[i][0] = i
    for j in range(cols):
        table[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[-1][-1]


def _fuzzy_budget(length: int) -> int:
    # Two edits only for long words: "dipendenza" is two edits from "dipendenti" and means something
    # else entirely, whereas "sovradimensionato" has room for a real slip.
    if length < 5:
        return 0
    return 1 if length <= 10 else 2


def fuzzy_alias(token: str, aliases: dict[str, HomeIntent]) -> HomeIntent | None:
    """The topic of the single alias `token` is a plausible typo of, or None.

    Only aliases of 5+ letters are considered, the budget grows with the word, an exact alias is
    handled by the caller, and a token equally close to aliases of TWO different topics is left
    alone (ambiguous: the model's own language understanding takes over)."""
    budget = _fuzzy_budget(len(token))
    if budget == 0 or token in FUZZY_STOPLIST:
        return None
    best: int | None = None
    topics: set[HomeIntent] = set()
    for alias, topic in aliases.items():
        # A typo almost never changes the first letter ("ocupazione", "prenotazini"), whereas two
        # real words one letter apart usually do ("posto" / "costo"): same initial or no match.
        if len(alias) < 5 or alias[0] != token[0] or abs(len(alias) - len(token)) > budget:
            continue
        distance = damerau_levenshtein(token, alias)
        if distance > budget:
            continue
        if best is None or distance < best:
            best = distance
            topics = {topic}
        elif distance == best:
            topics.add(topic)
    if len(topics) == 1:
        return next(iter(topics))
    return None


__all__ = [
    "CHANNEL_WORDS",
    "FOLLOW_UP_WORDS",
    "FUZZY_STOPLIST",
    "INCIDENCE_WORDS",
    "INTENT_PHRASES",
    "INTENT_WORDS",
    "NEUTRALISED_PHRASES",
    "OVERVIEW_PHRASES",
    "TYPOS",
    "UNSUPPORTED_PHRASES",
    "UNSUPPORTED_WORDS",
    "WEAK_DAYS_PHRASES",
    "WEAK_DAY_ADJECTIVES",
    "WEAK_DAY_NOUNS",
    "HomeIntent",
    "UnsupportedTopic",
    "damerau_levenshtein",
    "fuzzy_alias",
    "normalize_text",
]

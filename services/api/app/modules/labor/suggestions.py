"""Deterministic labor column suggestions (no AI, no learning), Italian and English.

The ranking is the shared one (`app.modules.ingestion.suggestions`). What is specific to labor, and
deliberate:

* Planned and actual are different facts (the staffing analysis reads the PLANNED minutes of a day,
  an actual timesheet is something else), so only names that SAY which one they are are suggested.
  A bare "ore" / "hours" / "costo" is left to the person: guessing would silently change what an
  analysis reads.
* NINFA keeps no employee identity and has no hourly rate: a column of names, and any "costo
  orario" / "hourly rate", is never suggested as anything. The person can only ignore it.
"""

from collections.abc import Mapping, Sequence

from app.modules.bookings.mapping import normalize_header
from app.modules.ingestion.suggestions import FieldSuggestion, suggest_fields
from app.modules.labor.mapping import LaborField

F = LaborField

FIELD_ORDER: tuple[LaborField, ...] = tuple(LaborField)

FIELD_ALIASES: Mapping[LaborField, tuple[str, ...]] = {
    F.WORK_DATE: (
        "work date",
        "shift date",
        "date",
        "day",
        "data",
        "giorno",
        "data turno",
        "data del turno",
        "data lavoro",
        "data lavorativa",
        "data servizio",
        "data presenza",
    ),
    # A hotel names its teams in its own words ("Reception", "Cucina", "Piani"): that is a ROLE,
    # which NINFA reads into one of its own categories. Only a column that already holds NINFA's
    # category names (HOUSEKEEPING, KITCHEN...) is the category itself.
    F.ROLE: (
        "role",
        "job role",
        "job title",
        "position",
        "department",
        "dept",
        "team",
        "ruolo",
        "mansione",
        "qualifica",
        "posizione",
        "funzione",
        "reparto",
        "dipartimento",
        "settore",
        "area",
        "area operativa",
        "categoria",
        "categoria personale",
        "squadra",
    ),
    F.LABOR_CATEGORY: ("labor category",),
    F.PLANNED_HOURS: (
        "planned hours",
        "scheduled hours",
        "shift hours",
        "ore previste",
        "ore pianificate",
        "ore programmate",
        "ore turno",
        "ore di turno",
        "ore del turno",
        "ore a turno",
    ),
    F.ACTUAL_HOURS: (
        "actual hours",
        "worked hours",
        "hours worked",
        "ore lavorate",
        "ore effettive",
        "ore effettuate",
        "ore reali",
        "ore a consuntivo",
        "ore consuntivo",
        "ore timbrate",
    ),
    F.PLANNED_COST: (
        "planned cost",
        "scheduled cost",
        "costo previsto",
        "costo pianificato",
        "costo programmato",
        "costo a preventivo",
        "costo preventivo",
        "costo turno",
        "costo del turno",
    ),
    F.ACTUAL_COST: (
        "actual cost",
        "costo effettivo",
        "costo reale",
        "costo a consuntivo",
        "costo consuntivo",
    ),
    F.CURRENCY: ("currency", "valuta", "divisa", "moneta"),
}

# Hourly rates and names of people: NINFA reads neither, so they are never offered as a match for a
# field they only resemble ("costo h" is not a cost of the day, "nome dipendente" is not a role).
_HOURLY_RATE_NAMES = (
    "hourly cost",
    "hourly rate",
    "cost per hour",
    "rate per hour",
    "costo orario",
    "costo ora",
    "costo h",
    "costo hr",
    "costo all ora",
    "costo per ora",
    "costo/ora",
    "costo/h",
    "tariffa oraria",
    "paga oraria",
    "retribuzione oraria",
)
_PERSON_NAMES = (
    "employee",
    "employee name",
    "staff name",
    "name",
    "dipendente",
    "nome dipendente",
    "nome",
    "cognome",
    "nome e cognome",
    "cognome nome",
    "collaboratore",
    "matricola",
    "codice fiscale",
    "cf",
)
_HOURLY: frozenset[str] = frozenset(normalize_header(name) for name in _HOURLY_RATE_NAMES)
_PERSON: frozenset[str] = frozenset(normalize_header(name) for name in _PERSON_NAMES)
EXCLUDED_HEADERS: frozenset[str] = _HOURLY | _PERSON

# Why a column is not offered as a field (the page words it; this is only the stable reason).
HOURLY_RATE = "HOURLY_RATE"
PERSON = "PERSON"


def excluded_reason(header: str) -> str | None:
    key = normalize_header(header)
    if key in _HOURLY:
        return HOURLY_RATE
    if key in EXCLUDED_HEADERS:
        return PERSON
    return None


def suggest_labor_mapping(headers: Sequence[str]) -> list[FieldSuggestion[LaborField]]:
    """One suggestion per labor field, in canonical order, each header used at most once."""
    return suggest_fields(
        headers, aliases=FIELD_ALIASES, order=FIELD_ORDER, excluded=EXCLUDED_HEADERS
    )


__all__ = [
    "EXCLUDED_HEADERS",
    "FIELD_ALIASES",
    "FIELD_ORDER",
    "HOURLY_RATE",
    "PERSON",
    "excluded_reason",
    "suggest_labor_mapping",
]

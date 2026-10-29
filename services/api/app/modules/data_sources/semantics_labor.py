"""What the columns of a staff file mean, read by words and checked against their values.

Staff keeps NO identity and no hourly rate (ADR 0014): the columns that carry them are recognised so
they can be left out, never so they can be read. "Reparto o mansione", "Reparto/Mansione",
"Area / reparto", "Tot. ore previste", "Costo programmato" are all understood - and the label
NINFA's own page uses for the field is one of them.
"""

from app.modules.bookings.text import normalize_key
from app.modules.data_sources.semantics import (
    AmbiguousColumn,
    DomainSem,
    FieldSem,
    fit_currency,
    fit_date,
    fit_hours,
    fit_money,
    fit_vocabulary,
    rule,
)
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.pii_text import header_variants
from app.modules.document_understanding.text import fold, stems
from app.modules.ingestion.models import DataSourceDomain
from app.modules.labor.classification import matching_categories
from app.modules.labor.mapping import LaborField
from app.modules.labor.roles import LaborCategory
from app.modules.labor.suggestions import FIELD_ALIASES, excluded_reason

F = LaborField

_HOURS = "ore ora hours hour hrs hr"
# ("H previste": the letter is a word for hours only next to the plan or the time worked)
_HOURS_WORDS = f"{_HOURS} h"
_PLANNED = (
    "previste previsto pianificate programmate prog pian prev programmed planned scheduled "
    "budget preventivo plan rostered"
)
_ACTUAL = (
    "effettive effettivo eff lavorate lav svolte svolto reali reale consuntivo timbrate actual "
    "worked effettuate rilevate rilevato clocked punched"
)
_COST = "costo costi cost"
_NOT_A_LABEL = "ore costo data totale"
# Hours that are neither the plan nor the time worked: a column of them is not "hours that do not
# say which" - it is another thing, and it is left alone.
_OTHER_HOURS = (
    "contratto contratti contrattuali contractual contract straordinario straordinari overtime "
    "ferie permessi permesso malattia assenza assenze pausa pause break notturne notturno festive "
    "festivo recupero residue residuo saldo cumulate cumulato"
)

_CATEGORY_NAMES = frozenset(category.value for category in LaborCategory)


def _exact(field: LaborField) -> tuple[str, ...]:
    return (*FIELD_ALIASES.get(field, ()), field.value)


def _is_department(text: str) -> bool:
    return bool(matching_categories(normalize_key(text)))


def _is_category_name(text: str) -> bool:
    return text.strip().upper() in _CATEGORY_NAMES


LABOR = DomainSem(
    domain=DataSourceDomain.LABOR,
    fields={
        F.WORK_DATE.value: FieldSem(
            F.WORK_DATE.value,
            _exact(F.WORK_DATE),
            (
                rule(
                    "data giorno giornata gg date day dt",
                    none="nascita assunzione scadenza cessazione fattura prenotazione",
                    weight=0.9,
                ),
            ),
            fit_date,
            value_only=True,
        ),
        # A hotel's department or job, in its own words: the department is worked out from it.
        F.ROLE.value: FieldSem(
            F.ROLE.value,
            _exact(F.ROLE),
            (
                rule(
                    "reparto dipartimento department dept rep area settore squadra team division "
                    "divisione section sezione uo servizio",
                    none=_NOT_A_LABEL,
                    weight=0.95,
                ),
                rule(
                    "mansione ruolo qualifica funzione posizione job",
                    none=_NOT_A_LABEL,
                    weight=0.88,
                ),
                # "Centro operativo": where the work is done - the department, if its values say so
                rule(
                    "centro unita unit struttura",
                    "operativo operativa operating lavoro work",
                    weight=0.85,
                ),
                rule("operating", "unit", weight=0.85),
                rule("centro", "lavoro work", weight=0.85),
            ),
            fit_vocabulary(_is_department),
        ),
        F.LABOR_CATEGORY.value: FieldSem(
            F.LABOR_CATEGORY.value,
            _exact(F.LABOR_CATEGORY),
            (),
            fit_vocabulary(_is_category_name),
        ),
        F.PLANNED_HOURS.value: FieldSem(
            F.PLANNED_HOURS.value,
            _exact(F.PLANNED_HOURS),
            (
                rule(_HOURS_WORDS, _PLANNED, none=_COST, weight=0.93),
                # "Prev." alone is only a maybe; with "Eff." next to it, it is the plan (`pairs`)
                rule("prev", none=_COST, weight=0.7),
            ),
            fit_hours,
        ),
        F.ACTUAL_HOURS.value: FieldSem(
            F.ACTUAL_HOURS.value,
            _exact(F.ACTUAL_HOURS),
            (
                rule(_HOURS_WORDS, _ACTUAL, none=_COST, weight=0.93),
                rule("eff", none=_COST, weight=0.7),
            ),
            fit_hours,
        ),
        F.PLANNED_COST.value: FieldSem(
            F.PLANNED_COST.value,
            _exact(F.PLANNED_COST),
            (rule(_COST, _PLANNED, none="ore orario hourly rate", weight=0.93),),
            fit_money,
        ),
        F.ACTUAL_COST.value: FieldSem(
            F.ACTUAL_COST.value,
            _exact(F.ACTUAL_COST),
            (rule(_COST, _ACTUAL, none="ore orario hourly rate", weight=0.93),),
            fit_money,
        ),
        F.CURRENCY.value: FieldSem(
            F.CURRENCY.value,
            _exact(F.CURRENCY),
            (rule("valuta currency divisa moneta", weight=0.9),),
            fit_currency,
        ),
    },
    order=tuple(field.value for field in LaborField),
    title_words=stems(
        "personale turni turno staff organico presenze pianificazione dipendenti reparto reparti "
        "ore lavoro orari rooster"
    ),
    locked={
        PiiKind.PERSON_NAME: "PERSON",
        PiiKind.EMAIL: "CONTACT",
        PiiKind.PHONE: "CONTACT",
        PiiKind.TAX_CODE: "IDENTITY",
        PiiKind.IBAN: "IDENTITY",
    },
    financial=frozenset({F.PLANNED_COST.value, F.ACTUAL_COST.value}),
    person_limits={F.PLANNED_HOURS.value: 24, F.ACTUAL_HOURS.value: 24},
    # "Prev." and "Eff." together, both columns of hours: the plan and the time worked. Alone, each
    # is a maybe (one confirmation): they have no word for hours of their own.
    pairs=(((F.PLANNED_HOURS.value, "prev"), (F.ACTUAL_HOURS.value, "eff")),),
    ambiguous=(
        AmbiguousColumn(
            "HOURS",
            stems(_HOURS_WORDS),
            stems(f"{_PLANNED} {_ACTUAL} {_COST} orario tariffa {_OTHER_HOURS}"),
            (F.PLANNED_HOURS.value, F.ACTUAL_HOURS.value),
            fit_hours,
        ),
        AmbiguousColumn(
            "COST",
            stems(_COST),
            stems(f"{_PLANNED} {_ACTUAL} orario tariffa ore"),
            (F.PLANNED_COST.value, F.ACTUAL_COST.value),
            fit_money,
        ),
    ),
    # An hourly rate is never read (NINFA does not turn it into a cost): V2's exact names, and any
    # header that says "cost / rate / pay" AND "hour".
    never=(
        (
            "HOURLY_RATE",
            rule("costo cost tariffa paga retribuzione rate eur", "orari ora h hr hourly hour"),
        ),
    ),
)


_PER_HOUR = frozenset({"orario", "oraria", "orari", "orarie", "hourly"})
_MONEY_WORDS = frozenset(
    {
        "costo",
        "costi",
        "tariffa",
        "tariffe",
        "paga",
        "retribuzione",
        "compenso",
        "stipendio",
        "rate",
        "pay",
        "wage",
        "salary",
        "cost",
        "euro",
        "eur",
    }
)


def hourly_or_known_exclusion(header: str) -> str | None:
    """A column that is never read, whatever way its header was typed: an invisible character
    inside it, words glued together or look-alike letters do not hide an hourly rate or a person
    (every reading of the header is tried, see `pii_text.header_variants`)."""
    for variant in header_variants(header):
        reason = _exclusion(variant)
        if reason is not None:
            return reason
    return None


def _exclusion(header: str) -> str | None:
    """V2's exact lists first (hourly rates and person columns by name), then the sign of a rate
    per hour written as a symbol ("EUR/h", "euro / ora")."""
    known = excluded_reason(header)
    if known is not None:
        return known
    lowered = header.lower().replace(" ", "")
    if any(sign in lowered for sign in ("/h", "/ora", "/hr")):
        return "HOURLY_RATE"
    # "Costo orario previsto": a money word next to "per hour" is a rate, whatever follows.
    # ("Orario" alone is a schedule, "Ore" alone is hours - neither is a rate.)
    words = set(fold(header).split())
    if words & _PER_HOUR and words & _MONEY_WORDS:
        return "HOURLY_RATE"
    return None


__all__ = ["LABOR", "hourly_or_known_exclusion"]

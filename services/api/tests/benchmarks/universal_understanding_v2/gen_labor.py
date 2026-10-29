"""Unseen staff (labor) documents: shift rotas, timesheets and hours exports.

120 documents (30 EASY, 40 MEDIUM, 30 HARD, 20 ADVERSARIAL). A staff document says, for a day and
a department, how many hours were planned and how many were worked. Hotels write it in many
shapes: a flat export of a time-clock or payroll system, a hand-made rota with a title and a total,
one sheet per department, a people x days grid, a table with a two-line header. The headers are
drawn from what such systems and sheets really write (Italian and English, abbreviated, with units
and punctuation); the shape of the document and the way its values are written change from one
document to the next.

The truth of each document is written next to the file by the recipe: a person's name, e-mail,
phone, tax code, IBAN or badge number is personal data (never imported); an hourly rate is a cost,
never hours (it must stay unmapped); a header that is only a part of a name ("Ore", "Hrs") over
values that cannot say more is a question, not a guess.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col, flat_document, headers, parts, records
from tests.benchmarks.smart_import_v3.draw import (
    Note,
    Section,
    Sheet,
    Styled,
    Subtotal,
    TableRef,
    Total,
    write_table,
    xlsx_bytes,
)
from tests.benchmarks.smart_import_v3.kit import Built, facts, pii
from tests.benchmarks.smart_import_v3.model import (
    GRID,
    SECTION,
    SHEET,
    TITLE,
    Doc,
    Golden,
    Source,
    column,
)
from tests.benchmarks.smart_import_v3.pool import email_of, full_name, person, phone_of, tax_code_of
from tests.benchmarks.universal_understanding_v2.common import (
    H,
    Maker,
    assemble,
    date_cell,
    maybe,
    order_of,
    pick,
    pick_language,
    without_table,
)

# --- the data of a shift --------------------------------------------------------------------------

# department word -> the category a careful person puts it in. Words every hotel reads the same way.
CATEGORY_WORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "FRONT_OFFICE": {
        "it": ("Reception", "Front Office", "Ricevimento", "Portineria"),
        "en": ("Front Desk", "Front Office", "Reception"),
    },
    "HOUSEKEEPING": {"it": ("Housekeeping", "Piani"), "en": ("Housekeeping",)},
    "KITCHEN": {"it": ("Cucina",), "en": ("Kitchen",)},
    "FOOD_BEVERAGE": {
        "it": ("Sala", "Bar", "Ristorante"),
        "en": ("Restaurant", "Bar", "F&B"),
    },
    "MAINTENANCE": {"it": ("Manutenzione",), "en": ("Maintenance", "Engineering")},
    "SPA_WELLNESS": {"it": ("Spa",), "en": ("Spa",)},
    "MANAGEMENT": {"it": ("Direzione",), "en": ("Management",)},
}
CATEGORY_OF = {
    word: category
    for category, languages in CATEGORY_WORDS.items()
    for words in languages.values()
    for word in words
}
# departments of any hotel that the truth does not put in a category (and so never asks about)
ADMIN_WORDS = {"it": "Amministrazione", "en": "Admin"}
CATEGORIES = tuple(CATEGORY_WORDS) + ("OTHER",)

HOTELS = (
    "Hotel Gabbiano",
    "Grand Hotel Riviera",
    "Villa Delle Palme",
    "Residence Porto Azzurro",
    "Albergo La Rocca",
    "Hotel Tre Torri",
    "Park Hotel Ginestra",
    "Hotel Belmare",
)
MONTHS_LONG = {
    "it": (
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}

PLANNED = (4.0, 5.0, 6.0, 6.0, 6.5, 7.0, 7.5, 7.5, 8.0, 8.0, 8.5, 9.0)
DRIFT = (-1.5, -1.0, -0.5, -0.5, 0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.5, 2.0)
RATES = (9.5, 10.0, 11.5, 12.0, 13.5, 14.0, 15.5, 17.0, 18.5, 21.0)
HOURS_FIELDS = {"planned_hours", "actual_hours"}


@dataclass(frozen=True, slots=True)
class Shift:
    day: date
    person: int
    dept: str
    planned: float
    actual: float
    rate: float

    @property
    def name(self) -> str:
        return full_name(self.person)


def period(rng: random.Random, count: int, *, monday: bool = False) -> list[date]:
    """`count` consecutive days of 2026, always with a day above 12 (so a text date written
    day-first or month-first proves its own order)."""
    while True:
        start = date(2026, 3, 2) + timedelta(days=rng.randint(0, 210))
        if monday:
            start -= timedelta(days=start.weekday())
        days = [start + timedelta(days=i) for i in range(count)]
        if any(d.day > 12 for d in days):
            return days


def pick_departments(rng: random.Random, lang: str, count: int, *, admin: bool = True) -> list[str]:
    """`count` departments of a hotel, one word per category, written in the language."""
    categories = rng.sample(list(CATEGORY_WORDS), min(count, len(CATEGORY_WORDS)))
    words = [rng.choice(CATEGORY_WORDS[c][lang]) for c in categories]
    if admin and count >= 3 and maybe(rng, 0.2):
        words[-1] = ADMIN_WORDS[lang]
    return words


def with_a_half(shifts: list[Shift]) -> list[Shift]:
    """Text hours must show their decimal mark somewhere: at least one fractional value."""
    if shifts and all(s.planned % 1 == 0 and s.actual % 1 == 0 for s in shifts):
        shifts[0] = replace(shifts[0], actual=shifts[0].actual + 0.5)
    return shifts


def roster(
    rng: random.Random,
    *,
    people: int,
    days: Sequence[date],
    depts: Sequence[str],
    first_person: int | None = None,
    day_off: float = 0.0,
    order: str = "day",
) -> list[Shift]:
    """Who worked how long on which day (`order`: day | person | dept)."""
    first = rng.randint(0, 2000) if first_person is None else first_person
    people = max(people, len(depts))  # every department has someone
    staff = [(first + i, depts[i % len(depts)], rng.choice(RATES)) for i in range(people)]
    shifts: list[Shift] = []
    for day in days:
        for index, dept, rate in staff:
            if day_off and maybe(rng, day_off):
                continue
            planned = rng.choice(PLANNED)
            actual = min(12.0, max(2.0, planned + rng.choice(DRIFT)))
            shifts.append(Shift(day, index, dept, planned, actual, rate))
    kinds = list(depts)
    if order == "person":
        shifts.sort(key=lambda s: (s.person, s.day))
    elif order == "dept":
        shifts.sort(key=lambda s: (kinds.index(s.dept), s.day, s.person))
    return with_a_half(shifts)


def by_department(shifts: Sequence[Shift]) -> list[Shift]:
    """One row per day and department, the people added up: a department-level export."""
    totals: dict[tuple[date, str], list[float]] = {}
    for s in shifts:
        acc = totals.setdefault((s.day, s.dept), [0.0, 0.0])
        acc[0] += s.planned
        acc[1] += s.actual
    depts = sorted({s.dept for s in shifts})
    return [
        Shift(day, depts.index(dept), dept, planned, actual, 0.0)
        for (day, dept), (planned, actual) in sorted(totals.items())
    ]


def labels_of(shifts: Sequence[Shift]) -> dict[str, dict[str, str]]:
    known = {w: CATEGORY_OF[w] for w in sorted({s.dept for s in shifts}) if w in CATEGORY_OF}
    return {"role_mapping": known} if known else {}


# --- headers --------------------------------------------------------------------------------------

DATE_PLAIN = (
    H("Data", "it"),
    H("Giorno", "it"),
    H("Gg", "it"),
    H("Data turno", "it"),
    H("Data servizio", "it"),
    H("Giornata", "it"),
    H("Data lavoro", "it"),
    H("Dt. turno", "it"),
    H("Giorno turno", "it"),
    H("Data prestazione", "it"),
    H("Date", "en"),
    H("Day", "en"),
    H("Shift Date", "en"),
    H("Work Date", "en"),
    H("Duty Date", "en"),
    H("Roster Date", "en"),
    H("Date Worked", "en"),
)
# a header that says it is the date OF THE SHIFT (needed when other dates sit in the same table)
DATE_SPECIFIC = (
    H("Data turno", "it"),
    H("Data servizio", "it"),
    H("Data lavoro", "it"),
    H("Dt. turno", "it"),
    H("Giorno turno", "it"),
    H("Data prestazione", "it"),
    H("Shift Date", "en"),
    H("Work Date", "en"),
    H("Duty Date", "en"),
    H("Roster Date", "en"),
    H("Date Worked", "en"),
)
DEPT_H = (
    H("Reparto", "it"),
    H("Dept.", "any"),
    H("Unità operativa", "it"),
    H("Servizio", "it"),
    H("Funzione", "it"),
    H("Centro di lavoro", "it"),
    H("Area", "any"),
    H("Settore", "it"),
    H("U.O.", "it"),
    H("Department", "en"),
    H("Dept", "en"),
    H("Section", "en"),
    H("Work Area", "en"),
    H("Division", "en"),
    H("Operating Unit", "en"),
)
PLANNED_H = (
    H("Ore previste", "it"),
    H("Ore Prev. H", "it"),
    H("Ore prev.", "it"),
    H("Ore pianificate", "it"),
    H("Ore pian.", "it"),
    H("Ore programmate", "it"),
    H("H previste", "it"),
    H("Prev. (h)", "it"),
    H("Ore di turno previste", "it"),
    H("Planned Hours", "en"),
    H("Planned Hrs", "en"),
    H("Sched. Hrs", "en"),
    H("Scheduled Hours", "en"),
    H("Rostered Hrs", "en"),
    H("Plan (h)", "en"),
    H("Hours Scheduled", "en"),
    H("Hrs Planned", "en"),
    H("Rostered Hours", "en"),
)
ACTUAL_H = (
    H("Ore effettive", "it"),
    H("Ore Eff. H", "it"),
    H("Ore eff.", "it"),
    H("Ore lavorate", "it"),
    H("Ore a consuntivo", "it"),
    H("Ore svolte", "it"),
    H("Ore reali", "it"),
    H("Ore timbrate", "it"),
    H("H lavorate", "it"),
    H("Eff. (h)", "it"),
    H("Ore effettuate", "it"),
    H("Ore rilevate", "it"),
    H("Actual Hours", "en"),
    H("Actual Hrs", "en"),
    H("Hrs worked", "en"),
    H("Worked Hours", "en"),
    H("Clocked Hrs", "en"),
    H("Hours Worked", "en"),
    H("Hrs Actual", "en"),
    H("Actual (h)", "en"),
    H("Time Worked (hrs)", "en"),
)
PERSON_H = (
    H("Dipendente", "it"),
    H("Nominativo", "it"),
    H("Collaboratore", "it"),
    H("Addetto", "it"),
    H("Cognome e Nome", "it"),
    H("Risorsa", "it"),
    H("Operatore", "it"),
    H("Cognome Nome", "it"),
    H("Personale", "it"),
    H("Employee", "en"),
    H("Staff Member", "en"),
    H("Employee Name", "en"),
    H("Team Member", "en"),
    H("Associate", "en"),
    H("Name", "en"),
    H("Staff", "any"),
)
EMAIL_H = (
    H("E-mail", "any"),
    H("Email aziendale", "it"),
    H("Indirizzo e-mail", "it"),
    H("Mail", "it"),
    H("Work Email", "en"),
    H("Email Address", "en"),
)
PHONE_H = (
    H("Cellulare", "it"),
    H("Telefono", "it"),
    H("Recapito", "it"),
    H("Mobile", "en"),
    H("Phone", "en"),
    H("Contact No.", "en"),
)
TAX_H = (
    H("Codice fiscale", "it"),
    H("C.F.", "it"),
    H("CF", "it"),
    H("Tax Code", "en"),
    H("Fiscal Code", "en"),
)
IBAN_H = (
    H("IBAN", "any"),
    H("IBAN accredito", "it"),
    H("Coordinate bancarie", "it"),
    H("Bank Account (IBAN)", "en"),
)
BADGE_H = (
    H("Matricola", "it"),
    H("Badge", "any"),
    H("Cod. dipendente", "it"),
    H("Employee ID", "en"),
    H("Staff ID", "en"),
    H("Payroll No.", "en"),
)
SPLIT_NAME_H = {
    "it": (("Nome", "Cognome"), ("Nome", "Cognome")),
    "en": (("First Name", "Last Name"), ("Given Name", "Surname")),
}
JOB_TITLES = {
    "FRONT_OFFICE": ("Receptionist", "Night Auditor", "Concierge"),
    "HOUSEKEEPING": ("Room Attendant", "Floor Supervisor"),
    "KITCHEN": ("Line Cook", "Sous Chef"),
    "FOOD_BEVERAGE": ("Waiter", "Barista", "Bartender"),
    "MAINTENANCE": ("Technician", "Maintenance Engineer"),
    "SPA_WELLNESS": ("Therapist", "Spa Attendant"),
    "MANAGEMENT": ("Duty Manager", "Operations Manager"),
    "ADMIN": ("Accountant", "HR Assistant"),
}
RATE_H = (
    H("Costo orario", "it"),
    H("Tariffa oraria", "it"),
    H("€/h", "any"),
    H("Paga oraria", "it"),
    H("Costo/ora", "it"),
    H("Retribuzione oraria", "it"),
    H("Hourly Rate", "en"),
    H("Rate/hr", "en"),
    H("Pay rate (EUR/h)", "en"),
    H("Cost per hour", "en"),
    H("Hourly Cost", "en"),
    H("Wage per hour", "en"),
)
BARE_COST_H = (
    H("Costo", "it"),
    H("Tariffa", "it"),
    H("Paga", "it"),
    H("Rate", "en"),
    H("Cost", "en"),
    H("Pay", "en"),
)

# columns of a staff export that are none of date / department / planned / actual
NOTES = ("ok", "cambio turno", "formazione", "evento sala", "ferie parziali", "da verificare", "")
JUNK: tuple[tuple[str, str, Callable[[Shift], Any]], ...] = (
    ("Sel.", "Sel.", lambda s: None),
    ("#", "#", lambda s: s.person % 9 + 1),
    ("Turno", "Shift", lambda s: "MPN"[(s.person + s.day.toordinal()) % 3]),
    ("Pausa (min)", "Break (min)", lambda s: (30, 45, 60)[s.person % 3]),
    ("Stato", "Status", lambda s: ("Confermato", "Da verificare")[s.person % 2]),
    ("Rev.", "Rev.", lambda s: 1 + s.person % 3),
    ("Compilato da", "Entered by", lambda s: ("hr1", "hr2")[s.person % 2]),
    ("Flag", "Flag", lambda s: "X" if s.person % 4 == 0 else None),
    ("Cod. interno", "Internal code", lambda s: f"C{s.person % 90 + 10}"),
    ("Note", "Remarks", lambda s: NOTES[(s.person + s.day.day) % len(NOTES)]),
)
EXTRA_HOURS: tuple[tuple[str, str, Callable[[Shift], Any]], ...] = (
    ("Ore straordinarie", "Overtime (h)", lambda s: max(0.0, s.actual - 8.0)),
    ("Ore ferie", "Holiday hrs", lambda s: 0.0),
    ("Ore notturne", "Night hrs", lambda s: 2.0 if s.person % 5 == 0 else 0.0),
    ("Ore permesso", "Leave hrs", lambda s: 1.0 if s.person % 7 == 0 else 0.0),
)


# --- cells ----------------------------------------------------------------------------------------


@dataclass(slots=True)
class Style:
    """How the values of a document are written."""

    lang: str = "it"
    dates: str = "xl"
    hours: str = "num"

    @property
    def decimal(self) -> str | None:
        return HOURS_DECIMAL.get(self.hours)


HOURS_DECIMAL = {"comma": ",", "h_it": ",", "ore": ",", "point": ".", "h_en": ".", "hrs": "."}
REAL_DATES = ("xl", "xl", "xl_iso", "xl_long", "iso")
TEXT_DATES = {
    "it": (
        "it",
        "dotted",
        "short",
        "weekday",
        "text_it",
        "text_it_long",
        "dash_mon",
        "iso",
        "slash_iso",
    ),
    "en": ("it", "text_en", "dash_mon", "iso", "slash_iso", "us"),
}
TEXT_HOURS = {"it": ("comma", "h_it", "ore"), "en": ("point", "h_en", "hrs")}


def hours_cell(value: float, style: str) -> Any:
    """A number of hours as a document writes it."""
    if style == "num":
        return value
    if style == "num_fmt":
        return Styled(value, fmt="0.00")
    if style == "num_h":
        return Styled(value, fmt='0.0" h"')
    plain = f"{value:g}"
    comma = plain.replace(".", ",")
    if style == "comma":
        return f"{value:.1f}".replace(".", ",")
    if style == "point":
        return f"{value:.1f}"
    if style == "h_it":
        return f"{comma}h"
    if style == "h_en":
        return f"{plain}h"
    if style == "ore":
        return f"{comma} ore"
    if style == "hrs":
        return f"{plain} hrs"
    raise ValueError(style)


def pick_style(
    rng: random.Random,
    *,
    lang: str | None = None,
    dates: str | None = None,
    hours: str | None = None,
) -> Style:
    return Style(
        lang or pick_language(rng),
        dates or rng.choice(REAL_DATES),
        hours or rng.choice(("num", "num", "num_fmt")),
    )


def core_cols(
    rng: random.Random,
    style: Style,
    *,
    date_h: str | None = None,
    planned: bool = True,
    actual: bool = True,
    dept: bool = True,
) -> list[Col]:
    lang = style.lang
    cols = [
        Col(
            date_h or pick(rng, DATE_PLAIN, lang),
            lambda s: date_cell(s.day, style.dates),
            "work_date",
        )
    ]
    if dept:
        cols.append(Col(pick(rng, DEPT_H, lang), lambda s: s.dept, "department"))
    if planned:
        cols.append(
            Col(
                pick(rng, PLANNED_H, lang),
                lambda s: hours_cell(s.planned, style.hours),
                "planned_hours",
            )
        )
    if actual:
        cols.append(
            Col(
                pick(rng, ACTUAL_H, lang),
                lambda s: hours_cell(s.actual, style.hours),
                "actual_hours",
            )
        )
    return cols


def person_col(rng: random.Random, lang: str) -> Col:
    header = pick(rng, PERSON_H, lang)
    last_first = "Cognome" in header
    return Col(header, lambda s: full_name(s.person, last_first=last_first), pii=True)


def iban_of(index: int) -> str:
    return f"IT00X0000000000{index % 10**12:012d}"


def personal_cols(rng: random.Random, lang: str, kinds: Sequence[str]) -> list[Col]:
    """Personal data columns of a staff export: nothing of this is ever imported."""
    cols: list[Col] = []
    for kind in kinds:
        if kind == "name":
            cols.append(person_col(rng, lang))
        elif kind == "split":
            first_h, last_h = rng.choice(SPLIT_NAME_H[lang])
            cols.append(Col(last_h, lambda s: person(s.person)[1], pii=True))
            cols.append(Col(first_h, lambda s: person(s.person)[0], pii=True))
        elif kind == "email":
            cols.append(
                Col(pick(rng, EMAIL_H, lang), lambda s: email_of(*person(s.person)), pii=True)
            )
        elif kind == "phone":
            cols.append(Col(pick(rng, PHONE_H, lang), lambda s: phone_of(s.person), pii=True))
        elif kind == "tax":
            cols.append(Col(pick(rng, TAX_H, lang), lambda s: tax_code_of(s.person), pii=True))
        elif kind == "iban":
            cols.append(Col(pick(rng, IBAN_H, lang), lambda s: iban_of(s.person), pii=True))
        else:
            cols.append(
                Col(pick(rng, BADGE_H, lang), lambda s: f"E{s.person + 10000:05d}", pii=True)
            )
    return cols


def job_title(s: Shift) -> str:
    """The job title of someone in the department (a column that is not the department)."""
    titles = JOB_TITLES[CATEGORY_OF.get(s.dept, "ADMIN")]
    return titles[s.person % len(titles)]


def rate_col(
    rng: random.Random, lang: str, header: str | None = None, *, scale: float = 1.0
) -> Col:
    """An hourly rate: a cost, never hours."""
    shown = rng.choice(("num", "eur", "num"))

    def rate(s: Shift) -> Any:
        value = round(s.rate * scale, 2)
        return Styled(value, fmt='#,##0.00 "€"') if shown == "eur" else value

    return Col(header or pick(rng, RATE_H, lang), rate)


def junk_cols(rng: random.Random, lang: str, count: int) -> list[Col]:
    return [Col(it if lang == "it" else en, cell) for it, en, cell in rng.sample(list(JUNK), count)]


def extra_hours_cols(rng: random.Random, lang: str, count: int) -> list[Col]:
    """Hours of something else (overtime, holiday...): next to planned and actual, never them."""
    return [
        Col(it if lang == "it" else en, cell)
        for it, en, cell in rng.sample(list(EXTRA_HOURS), count)
    ]


def clock_cols(lang: str) -> list[Col]:
    """Start and end of the shift, as a time of day: not a number of hours."""

    def start(s: Shift) -> float:
        return 6.0 + (s.person % 4) * 2

    def clock(value: float) -> str:
        return f"{int(value) % 24:02d}:{int((value % 1) * 60):02d}"

    return [
        Col("Ora inizio" if lang == "it" else "Start time", lambda s: clock(start(s))),
        Col("Ora fine" if lang == "it" else "End time", lambda s: clock(start(s) + s.actual + 0.5)),
    ]


# --- layout helpers -------------------------------------------------------------------------------

SHEETS = {
    "it": (
        "Turni",
        "Presenze",
        "Foglio1",
        "Rooster",
        "Export",
        "Ore",
        "Personale",
        "Rilevazione",
        "Dati",
        "Piano",
        "Consuntivo",
        "Settimana",
    ),
    "en": (
        "Roster",
        "Timesheet",
        "Sheet1",
        "Staff Hours",
        "Export",
        "Shifts",
        "Hours",
        "Attendance",
        "Data",
        "Report",
    ),
}
STEMS = {
    "it": (
        "turni",
        "presenze",
        "rooster",
        "ore_personale",
        "piano_turni",
        "consuntivo_ore",
        "foglio_ore",
        "export_hr",
        "rilevazione_presenze",
        "ore_lavorate",
    ),
    "en": (
        "roster",
        "timesheet",
        "staff_hours",
        "shift_report",
        "attendance",
        "hours_report",
        "workforce_export",
    ),
}
SUFFIXES = ("", "", "_ottobre", "_sett42", "_2026", "_v2", "_def", "_export", "_agosto", "_nov")
TITLES = {
    "it": (
        "PIANO TURNI",
        "RILEVAZIONE PRESENZE",
        "CONSUNTIVO ORE PERSONALE",
        "FOGLIO ORE",
        "ELENCO TURNI E ORE",
    ),
    "en": ("STAFF ROSTER", "TIMESHEET REPORT", "WORKFORCE HOURS", "SHIFT HOURS EXPORT"),
}


def sheet_name(rng: random.Random, lang: str) -> str:
    return rng.choice(SHEETS[lang])


def file_name(rng: random.Random, lang: str, ext: str) -> str:
    return f"{rng.choice(STEMS[lang])}{rng.choice(SUFFIXES)}.{ext}"


def long_date(lang: str, day: date) -> str:
    return f"{day.day} {MONTHS_LONG[lang][day.month - 1]} {day.year}"


def period_text(rng: random.Random, lang: str, first: date, last: date) -> str:
    """The period a title states: with the month named, or numeric when a day above 12 proves it."""
    if (first.day > 12 or last.day > 12) and maybe(rng, 0.5):
        if lang == "it":
            return f"dal {first:%d/%m/%Y} al {last:%d/%m/%Y}"
        return f"{first:%Y-%m-%d} to {last:%Y-%m-%d}"
    if lang == "it":
        return f"dal {long_date(lang, first)} al {long_date(lang, last)}"
    return f"{long_date(lang, first)} to {long_date(lang, last)}"


def preamble_of(rng: random.Random, lang: str, days: Sequence[date], lines: int) -> list[Any]:
    """Title lines above a table (never naming a department)."""
    hotel = rng.choice(HOTELS)
    exported = days[-1] + timedelta(days=rng.randint(1, 6))
    says = "esportato il" if lang == "it" else "exported on"
    options: list[Any] = [
        ("title", rng.choice(TITLES[lang])),
        ("subtitle", f"{hotel} - {says} {long_date(lang, exported)}"),
        (
            "note",
            ("Periodo: " if lang == "it" else "Period: ")
            + period_text(rng, lang, days[0], days[-1]),
        ),
    ]
    return options[:lines]


def sum_row(
    cols: Sequence[Col],
    shifts: Sequence[Shift],
    style: Style,
    label: str,
    *,
    planned_shift: float = 0.0,
    actual_shift: float = 0.0,
) -> list[Any]:
    """A total / sub-total line: the label under the date column, the sums under the hours."""
    cells: list[Any] = [None] * len(cols)
    cells[next((i for i, c in enumerate(cols) if c.field == "work_date"), 0)] = label
    for index, col in enumerate(cols):
        if col.field == "planned_hours":
            total = round(sum(s.planned for s in shifts) + planned_shift, 2)
            cells[index] = hours_cell(total, style.hours)
        elif col.field == "actual_hours":
            total = round(sum(s.actual for s in shifts) + actual_shift, 2)
            cells[index] = hours_cell(total, style.hours)
    return cells


def totals_label(rng: random.Random, lang: str) -> str:
    return rng.choice(
        ("TOTALE", "Totale ore", "TOT.") if lang == "it" else ("TOTAL", "Total hours")
    )


def totals_wrap(
    cols: Sequence[Col],
    shifts: Sequence[Shift],
    style: Style,
    label: str,
    *,
    planned_shift: float = 0.0,
    actual_shift: float = 0.0,
) -> Callable[[list[list[Any]]], list[Any]]:
    def wrap(body: list[list[Any]]) -> list[Any]:
        row = sum_row(
            cols, shifts, style, label, planned_shift=planned_shift, actual_shift=actual_shift
        )
        return [*body, Total(row)]

    return wrap


def document(
    rng: random.Random,
    cols: list[Col],
    shifts: list[Shift],
    style: Style,
    *,
    name: str,
    outcome: str = "READY",
    **layout: Any,
) -> Built:
    """A flat table in a sheet (or, with `csv=`, in a CSV) with the truth that goes with it."""
    labels = layout.pop("labels", None)
    if labels is None:
        labels = labels_of(shifts) if any(c.field == "department" for c in cols) else {}
    return flat_document(
        "labor",
        name,
        cols,
        shifts,
        outcome=outcome,
        sheet_title=layout.pop("sheet_title", sheet_name(rng, style.lang)),
        date_order=layout.pop("date_order", order_of(style.dates)),
        decimal=layout.pop("decimal", style.decimal),
        labels=labels,
        **layout,
    )


def golden_from(
    cols: Sequence[Col],
    items: Sequence[Any],
    ref: TableRef,
    outcome: str = "READY",
    *,
    domain: str = "labor",
    csv: bool = False,
    sheets: Sequence[str] | None = None,
    add_fields: dict[str, Source] | None = None,
    **extra: Any,
) -> Golden:
    """The truth of a hand-drawn document: the meaning comes from the columns."""
    meaning = parts(cols, items)
    values: dict[str, Any] = {
        "fields": {**meaning["fields"], **(add_fields or {})},
        "ambiguous": meaning["ambiguous"],
        "unmapped": meaning["unmapped"],
        "pii_columns": meaning["pii_columns"],
        "pii_values": meaning["pii_values"],
    }
    values.update(extra)
    return Golden(domain, outcome, **facts(ref, csv=csv, sheets=sheets), **values)


def finish(name: str, sheets: Sequence[Sheet], golden: Golden, card: str | None = None) -> Built:
    return Built(name, xlsx_bytes(sheets), golden, list(sheets), card=card)


def deduplicated(built: Built) -> Built:
    """Two columns standing for one fact (a plan and its revision) list that fact once."""
    built.golden.ambiguous = tuple(dict.fromkeys(built.golden.ambiguous))
    return built


# ==================================================================================================
# EASY: a clean table the benchmark has never seen
# ==================================================================================================


def easy_xlsx_roster(rng: random.Random) -> Built:
    style = pick_style(rng)
    days = period(rng, rng.randint(3, 8))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = core_cols(rng, style)
    if maybe(rng, 0.85):
        cols.insert(rng.choice((0, 1)), person_col(rng, style.lang))
    return document(rng, cols, shifts, style, name=file_name(rng, style.lang, "xlsx"))


def easy_csv_semicolon(rng: random.Random) -> Built:
    style = pick_style(rng, dates="xl", hours="num")
    dates = rng.choice(("it", "iso", "dotted"))
    days = period(rng, rng.randint(3, 8))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, style.lang)]
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, style.lang, "csv"),
        csv={"delimiter": ";", "decimal": ",", "dates": dates},
        date_order=order_of(dates),
        decimal=",",
    )


def easy_xlsx_title_block(rng: random.Random) -> Built:
    style = pick_style(rng)
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, style.lang)]
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, style.lang, "xlsx"),
        preamble=preamble_of(rng, style.lang, days, rng.randint(1, 3)),
        left=rng.choice((0, 0, 1)),
    )


def easy_daily_by_department(rng: random.Random) -> Built:
    """No person at all: the hours of each department for each day."""
    style = pick_style(rng)
    days = period(rng, rng.randint(4, 9))
    depts = pick_departments(rng, style.lang, rng.randint(3, 5))
    shifts = by_department(
        roster(rng, people=rng.randint(len(depts), len(depts) * 3), days=days, depts=depts)
    )
    cols = core_cols(rng, style)
    if maybe(rng, 0.4):
        cols.extend(junk_cols(rng, style.lang, 1))
    return document(rng, cols, shifts, style, name=file_name(rng, style.lang, "xlsx"))


def easy_one_hours_column(rng: random.Random) -> Built:
    """Only the plan, or only what was worked: the other fact is simply not in the document."""
    style = pick_style(rng)
    which = rng.choice(("planned", "actual"))
    days = period(rng, rng.randint(3, 8))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [
        *core_cols(rng, style, planned=which == "planned", actual=which == "actual"),
        person_col(rng, style.lang),
    ]
    absent = ("actual_hours",) if which == "planned" else ("planned_hours",)
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, style.lang, "xlsx"),
        absent=absent,
        note=f"Only the {which} hours are in the document.",
    )


# ==================================================================================================
# MEDIUM: aliases, reordering, noise
# ==================================================================================================


def medium_reorder_noise(rng: random.Random) -> Built:
    style = pick_style(rng)
    days = period(rng, rng.randint(3, 8))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts, day_off=0.1)
    cols = [
        *core_cols(rng, style),
        person_col(rng, style.lang),
        *junk_cols(rng, style.lang, rng.randint(1, 3)),
    ]
    rng.shuffle(cols)
    wrap = None
    if maybe(rng, 0.6):
        wrap = totals_wrap(cols, shifts, style, totals_label(rng, style.lang))
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, style.lang, "xlsx"),
        preamble=preamble_of(rng, style.lang, days, rng.randint(0, 2)),
        left=rng.choice((0, 1, 2)),
        wrap=wrap,
    )


def medium_personal_data(rng: random.Random) -> Built:
    style = pick_style(rng)
    days = period(rng, rng.randint(3, 6))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    kinds = rng.sample(
        ["name", "split", "email", "phone", "tax", "iban", "badge"], rng.randint(2, 5)
    )
    cols = [*core_cols(rng, style), *personal_cols(rng, style.lang, kinds)]
    rng.shuffle(cols)
    return document(rng, cols, shifts, style, name=file_name(rng, style.lang, "xlsx"))


def medium_hourly_rate(rng: random.Random) -> Built:
    """A cost per hour next to the hours: a column that must never become hours."""
    style = pick_style(rng)
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, style.lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, style.lang)]
    fitting = [h.text for h in RATE_H if h.lang in {"any", style.lang}]
    cols.extend(
        rate_col(rng, style.lang, h, scale=1.0 + 0.3 * n)
        for n, h in enumerate(rng.sample(fitting, rng.randint(1, 2)))
    )
    rng.shuffle(cols)
    return document(rng, cols, shifts, style, name=file_name(rng, style.lang, "xlsx"))


def medium_text_formats(rng: random.Random) -> Built:
    lang = pick_language(rng)
    dates = rng.choice(TEXT_DATES[lang])
    style = Style(lang, dates, rng.choice(TEXT_HOURS[lang]))
    days = period(rng, rng.randint(4, 9))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    return document(rng, cols, shifts, style, name=file_name(rng, lang, "xlsx"))


def medium_csv_dialects(rng: random.Random) -> Built:
    lang = pick_language(rng)
    delimiter = rng.choice((";", ",", "\t"))
    decimal = "," if delimiter == ";" else "." if delimiter == "," else rng.choice((",", "."))
    month_first = decimal == "." and lang == "en"
    dates = rng.choice(("it", "iso", "dotted", "us") if month_first else ("it", "iso", "dotted"))
    style = Style(lang, "xl", "num")
    days = period(rng, rng.randint(3, 8))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    person_cell = person_col(rng, lang)
    if delimiter == ",":  # "Ferretti, Giulia": the comma inside a name forces the quotes
        person_cell = Col(
            person_cell.header,
            lambda s: f"{person(s.person)[1]}, {person(s.person)[0]}",
            pii=True,
        )
    remark = rng.choice(("ok", 'ha chiesto "cambio turno"', "turno spezzato"))
    cols = [
        *core_cols(rng, style),
        person_cell,
        Col("Note" if lang == "it" else "Remarks", lambda s: f"{remark}{delimiter}{s.person % 5}"),
    ]
    if maybe(rng, 0.4):
        cols.append(Col("", lambda s: None, junk=False))  # a trailing delimiter on every line
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "csv"),
        csv={
            "delimiter": delimiter,
            "decimal": decimal,
            "dates": dates,
            "encoding": rng.choice(("utf-8-sig", "utf-8")),
            "newline": rng.choice(("\r\n", "\n")),
        },
        preamble=preamble_of(rng, lang, days, 1) if maybe(rng, 0.3) else (),
        date_order=order_of(dates),
        decimal=decimal,
    )


def medium_hidden_extra_sheets(rng: random.Random) -> Built:
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    data = Sheet(sheet_name(rng, lang))
    ref = write_table(data, headers(cols), records(cols, shifts))
    older = roster(
        rng,
        people=3,
        days=[d - timedelta(days=45) for d in days[:3]],
        depts=depts,
        first_person=rng.randint(0, 2000),
    )
    archive = Sheet("Archivio" if lang == "it" else "Archive", hidden=True)
    write_table(archive, headers(cols), records(cols, older))
    summary = Sheet("Riepilogo" if lang == "it" else "Summary")
    write_table(
        summary,
        [cols[1].header, cols[2].header, cols[3].header],
        [
            [
                dept,
                round(sum(s.planned for s in shifts if s.dept == dept), 1),
                round(sum(s.actual for s in shifts if s.dept == dept), 1),
            ]
            for dept in depts
        ],
    )
    sheets = rng.choice(
        ([data, summary, archive], [summary, data, archive], [archive, data, summary])
    )
    golden = golden_from(
        cols,
        shifts,
        ref,
        sheets=[data.title],
        labels=labels_of(shifts),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note="The shifts are on one sheet; a per-department summary and a hidden archive are not.",
    )
    return finish(file_name(rng, lang, "xlsx"), sheets, golden)


def medium_other_hours_and_dates(rng: random.Random) -> Built:
    """Overtime, holiday hours, start / end times and other dates sit next to the real columns."""
    lang = pick_language(rng)
    style = pick_style(rng, lang=lang)
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    hired = "Data assunzione" if lang == "it" else "Hire date"
    changed = "Ultima modifica" if lang == "it" else "Last updated"
    decoys = [
        Col(
            hired, lambda s: date_cell(date(2015 + s.person % 9, 1 + s.person % 12, 3), style.dates)
        ),
        Col(changed, lambda s: date_cell(s.day + timedelta(days=1), style.dates)),
    ]
    cols = [
        *core_cols(rng, style, date_h=pick(rng, DATE_SPECIFIC, lang)),
        person_col(rng, lang),
        *extra_hours_cols(rng, lang, rng.randint(1, 3)),
        *rng.sample(decoys, rng.randint(1, 2)),
    ]
    if maybe(rng, 0.5):
        cols.extend(clock_cols(lang))
    rng.shuffle(cols)
    return document(rng, cols, shifts, style, name=file_name(rng, lang, "xlsx"))


def medium_english_export(rng: random.Random) -> Built:
    """A workforce-management export: staff id, job title and pay rate next to the hours."""
    use_csv = maybe(rng, 0.4)
    style = Style(
        "en", "xl" if use_csv else rng.choice(("iso", "dash_mon", "xl", "xl_long")), "num"
    )
    days = period(rng, rng.randint(4, 9))
    depts = pick_departments(rng, "en", rng.randint(3, 5))
    shifts = roster(rng, people=rng.randint(4, 7), days=days, depts=depts)
    cols = [
        *personal_cols(rng, "en", ["badge", "name"]),
        *core_cols(rng, style, date_h=pick(rng, DATE_SPECIFIC, "en")),
        Col("Job Title", lambda s: job_title(s)),
        rate_col(rng, "en"),
    ]
    rng.shuffle(cols)
    if use_csv:
        return document(
            rng,
            cols,
            shifts,
            style,
            name=file_name(rng, "en", "csv"),
            csv={"delimiter": ",", "decimal": ".", "dates": "iso"},
            date_order=None,
            decimal=".",
        )
    return document(rng, cols, shifts, style, name=file_name(rng, "en", "xlsx"))


# ==================================================================================================
# HARD: the department is not a column, grids, two-level headers, several tables
# ==================================================================================================

SECTION_FORMS = {
    "it": ("{d}", "{D}", "Reparto: {d}", "REPARTO {D}"),
    "en": ("{d}", "{D}", "Department: {d}", "DEPT - {D}"),
}
TITLE_FORMS = {
    "it": ("TURNI {D}", "Piano turni - {d}", "ORE {D} - PERSONALE", "Rooster reparto {d}"),
    "en": ("{D} ROSTER", "Staff hours - {d}", "SHIFT PLAN {D}", "{d} department timesheet"),
}


def hard_sections(rng: random.Random) -> Built:
    """The department is a line of its own over the people it holds."""
    style = pick_style(rng)
    lang = style.lang
    depts = pick_departments(rng, lang, rng.randint(3, 4))
    days = period(rng, rng.randint(2, 4))
    shifts = roster(
        rng, people=rng.randint(len(depts) + 2, 9), days=days, depts=depts, order="dept"
    )
    cols = [c for c in core_cols(rng, style) if c.field != "department"]
    cols.insert(1, person_col(rng, lang))
    form = rng.choice(SECTION_FORMS[lang])
    subtotal = rng.choice(
        ("Subtotale {d}", "Tot. {d}", "Tot.") if lang == "it" else ("Subtotal {d}", "Total")
    )
    with_subtotals = maybe(rng, 0.6)
    with_total = maybe(rng, 0.5)
    note = "Ore espresse in decimali." if lang == "it" else "Hours are written as decimals."

    def wrap(_: list[list[Any]]) -> list[Any]:
        body: list[Any] = []
        for dept in depts:
            block = [s for s in shifts if s.dept == dept]
            body.append(Section(form.format(d=dept, D=dept.upper())))
            body.extend([c.cell(s) for c in cols] for s in block)
            if with_subtotals:
                body.append(Subtotal(sum_row(cols, block, style, subtotal.format(d=dept))))
        if with_total:
            body.append(Total(sum_row(cols, shifts, style, totals_label(rng, lang))))
        body.append(Note(note))
        return body

    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        wrap=wrap,
        extra_fields={"department": SECTION},
        preamble=preamble_of(rng, lang, days, rng.randint(0, 2)),
        left=rng.choice((0, 0, 1)),
    )


def hard_sheet_per_department(rng: random.Random) -> Built:
    """One sheet per department, the same columns on each: ONE table, the sheet name is the
    department."""
    style = pick_style(rng)
    lang = style.lang
    depts = pick_departments(rng, lang, rng.randint(3, 4))
    days = period(rng, rng.randint(3, 6))
    prefix = rng.choice(
        ("", "", "Turni ", "Ore ") if lang == "it" else ("", "", "Staff ", "Hours ")
    )
    cols = [c for c in core_cols(rng, style) if c.field != "department"]
    cols.insert(1, person_col(rng, lang))
    base = rng.randint(0, 1900)
    sheets: list[Sheet] = []
    refs: list[TableRef] = []
    every: list[Shift] = []
    for number, dept in enumerate(depts):
        mine = roster(
            rng,
            people=rng.randint(2, 4),
            days=days,
            depts=[dept],
            first_person=base + number * 6,
        )
        every.extend(mine)
        sheet = Sheet(f"{prefix}{dept}")
        if prefix:
            sheet.title_line(f"{prefix}{dept}".upper(), len(cols))
            sheet.blank()
        refs.append(write_table(sheet, headers(cols), records(cols, mine)))
        sheets.append(sheet)
    names = [s.title for s in sheets]
    tolerated: tuple[str, ...] = ("DEPARTMENT_CONFIRM",) if prefix else ()
    if maybe(rng, 0.3):
        summary = Sheet("Riepilogo" if lang == "it" else "Summary")
        write_table(
            summary,
            ["Reparto" if lang == "it" else "Department", cols[-2].header, cols[-1].header],
            [
                [
                    d,
                    round(sum(s.planned for s in every if s.dept == d), 1),
                    round(sum(s.actual for s in every if s.dept == d), 1),
                ]
                for d in depts
            ],
        )
        sheets.append(summary)
        tolerated = (*tolerated, "TABLE")
    golden = golden_from(
        cols,
        every,
        refs[0].merged(*refs[1:]),
        sheets=names,
        add_fields={"department": SHEET},
        tolerated=tolerated,
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note="One sheet per department: one table, and the sheet name is the department.",
    )
    return finish(file_name(rng, lang, "xlsx"), sheets, golden)


def hard_title_department(rng: random.Random) -> Built:
    """A document for one department: the title names it, no column does."""
    style = pick_style(rng)
    lang = style.lang
    dept = pick_departments(rng, lang, 1, admin=False)[0]
    days = period(rng, rng.randint(4, 8))
    shifts = roster(rng, people=rng.randint(3, 5), days=days, depts=[dept])
    cols = [c for c in core_cols(rng, style) if c.field != "department"]
    cols.insert(1, person_col(rng, lang))
    title = rng.choice(TITLE_FORMS[lang]).format(d=dept, D=dept.upper())
    hotel = rng.choice(HOTELS)
    preamble: list[Any] = [
        ("title", title),
        ("subtitle", f"{hotel} - {period_text(rng, lang, days[0], days[-1])}"),
    ]
    return document(
        rng,
        cols,
        shifts,
        style,
        name=f"{rng.choice(STEMS[lang])}_{dept.lower().replace(' ', '_')}.xlsx",
        preamble=preamble[: rng.randint(1, 2)],
        extra_fields={"department": TITLE},
        tolerated=("DEPARTMENT_CONFIRM",),
        note="The title names the department; asking the person to confirm it is acceptable.",
    )


# --- grids: people x days -------------------------------------------------------------------------

DAY_NAMES = {
    "it": (
        ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"),
        ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"),
    ),
    "en": (
        ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    ),
}
BASIS_PHRASES = {
    ("it", "planned_hours"): (
        "ORE PREVISTE",
        "Piano turni (ore pianificate)",
        "Turni programmati - ore previste",
    ),
    ("it", "actual_hours"): ("CONSUNTIVO ORE", "ORE LAVORATE", "Ore effettive per giorno"),
    ("en", "planned_hours"): ("PLANNED HOURS", "ROSTER - scheduled hours"),
    ("en", "actual_hours"): ("HOURS WORKED", "ACTUAL HOURS BY DAY"),
}
NEUTRAL_TITLES = {
    "it": ("Griglia settimanale", "Ore per giorno", "Foglio ore"),
    "en": ("Weekly grid", "Staff hours by day", "Daily hours grid"),
}


@dataclass(slots=True)
class Grid:
    sheet: Sheet
    ref: TableRef
    names: list[str]
    person_header: str
    dept_header: str | None
    total_header: str | None


def draw_grid(
    rng: random.Random,
    *,
    lang: str,
    days: Sequence[date],
    header_kind: str,
    basis: str,
    title_lines: Sequence[str],
    dept_mode: str,
    total_column: bool,
    total_row: bool,
) -> Grid:
    """People in rows, days in columns, the hours of `basis` in the cells."""
    depts = pick_departments(rng, lang, 3, admin=False)
    shifts = roster(
        rng, people=rng.randint(5, 8), days=days, depts=depts, day_off=0.12, order="person"
    )
    dept_of = {s.person: s.dept for s in shifts}
    people = sorted(dept_of, key=lambda p: (depts.index(dept_of[p]), p))
    person_h = pick(rng, PERSON_H, lang)
    dept_h = pick(rng, DEPT_H, lang) if dept_mode == "column" else None
    total_h = (
        rng.choice(("Totale", "Tot.", "Totale ore") if lang == "it" else ("Total", "Total hrs"))
        if total_column
        else None
    )
    if header_kind == "real":
        fmt = rng.choice(("DD/MM/YYYY", "DDD DD/MM/YYYY", "DD-MMM-YY", "DD/MM"))
        day_cells: list[Any] = [Styled(datetime(d.year, d.month, d.day), fmt=fmt) for d in days]
    elif header_kind == "weekday":
        names = DAY_NAMES[lang][rng.randint(0, 1)]
        day_cells = [names[d.weekday()] for d in days]
    else:
        day_cells = [d.day for d in days]
    header: list[Any] = [
        person_h,
        *([dept_h] if dept_h else []),
        *day_cells,
        *([total_h] if total_h else []),
    ]

    def value_of(s: Shift) -> float:
        return s.planned if basis == "planned_hours" else s.actual

    body: list[Any] = []
    names_out: list[str] = []
    last_dept = None
    for index in people:
        mine = {s.day: s for s in shifts if s.person == index}
        dept = next(iter(mine.values())).dept
        if dept_mode == "section" and dept != last_dept:
            body.append(Section(dept.upper()))
            last_dept = dept
        cells: list[Any] = [full_name(index)]
        names_out.append(full_name(index))
        if dept_h:
            cells.append(dept)
        cells.extend(value_of(mine[d]) if d in mine else None for d in days)
        if total_h:
            cells.append(sum(value_of(s) for s in mine.values()))
        body.append(cells)
    if total_row:
        row: list[Any] = ["TOTALE" if lang == "it" else "TOTAL"]
        if dept_h:
            row.append(None)
        row.extend(round(sum(value_of(s) for s in shifts if s.day == d), 1) for d in days)
        if total_h:
            row.append(round(sum(value_of(s) for s in shifts), 1))
        body.append(Total(row))
    sheet = Sheet(rng.choice(SHEETS[lang]))
    for number, line in enumerate(title_lines):
        sheet.add([line], style="title" if number == 0 else "subtitle")
    if title_lines:
        sheet.blank()
    ref = write_table(sheet, header, body)
    return Grid(sheet, ref, names_out, person_h, dept_h, total_h)


def grid_truth(
    grid: Grid, outcome: str = "READY", *, fields: dict[str, Source], **extra: Any
) -> Golden:
    unmapped = ((grid.total_header,),) if grid.total_header else ()
    return Golden(
        "labor",
        outcome,
        **facts(grid.ref),
        fields=fields,
        unmapped=unmapped,
        **pii([(grid.person_header,)], grid.names),
        **extra,
    )


def grid_fields(grid: Grid, basis: str | None, *, work_date: bool = True) -> dict[str, Source]:
    fields: dict[str, Source] = {}
    if work_date:
        fields["work_date"] = GRID
    if basis:
        fields[basis] = GRID
    fields["department"] = column(grid.dept_header) if grid.dept_header else SECTION
    return fields


def hard_grid_stated(rng: random.Random) -> Built:
    """People x days, and the document says which days and which hours they are."""
    lang = pick_language(rng)
    basis = rng.choice(("planned_hours", "actual_hours"))
    phrase = rng.choice(BASIS_PHRASES[(lang, basis)])
    kind = rng.choice(("real", "weekday", "number"))
    dept_mode = rng.choice(("column", "column", "section"))
    if kind == "number":
        month = rng.randint(4, 9)
        start = rng.randint(1, 14)
        days = [date(2026, month, start + i) for i in range(rng.randint(7, 14))]
        title = [f"{phrase} - {MONTHS_LONG[lang][month - 1].upper()} 2026"]
        note = "Day numbers 1..n and the month and year in the title: real days."
    elif kind == "weekday":
        days = period(rng, rng.randint(4, 7), monday=maybe(rng, 0.5))
        title = [f"{phrase} - {period_text(rng, lang, days[0], days[-1])}", rng.choice(HOTELS)]
        note = "Weekday names, and the period is written in the title."
    else:
        days = period(rng, rng.randint(4, 7))
        title = [phrase, rng.choice(HOTELS)]
        note = "Real dates in the header, and the title says which hours they are."
    grid = draw_grid(
        rng,
        lang=lang,
        days=days,
        header_kind=kind,
        basis=basis,
        title_lines=title,
        dept_mode=dept_mode,
        total_column=maybe(rng, 0.5),
        total_row=maybe(rng, 0.5),
    )
    golden = grid_truth(
        grid,
        fields=grid_fields(grid, basis),
        period_start=days[0].isoformat(),
        note=note,
    )
    return finish(file_name(rng, lang, "xlsx"), [grid.sheet], golden)


def grid_asks_hours(
    rng: random.Random, lang: str, grid: Grid, days: Sequence[date], basis: str
) -> Built:
    """People x days with real dates and nothing that says whether the cells are the plan or the
    hours worked."""
    golden = grid_truth(
        grid,
        "ASK",
        fields=grid_fields(grid, None),
        ambiguous=("planned_hours", "actual_hours"),
        questions=("GRID_HOURS",),
        answers={"grid_hours": basis},
        period_start=days[0].isoformat(),
        note="Nothing says whether the hours in the cells are planned or worked.",
    )
    return finish(file_name(rng, lang, "xlsx"), [grid.sheet], golden)


def hard_grid_ask(rng: random.Random) -> Built:
    """People x days where a fact the importer needs is not in the document."""
    lang = pick_language(rng)
    basis = rng.choice(("planned_hours", "actual_hours"))
    variant = rng.choice(("hours", "week", "both"))
    dept_mode = rng.choice(("column", "section"))
    if variant == "hours":
        days = period(rng, rng.randint(4, 7))
        grid = draw_grid(
            rng,
            lang=lang,
            days=days,
            header_kind="real",
            basis=basis,
            title_lines=[rng.choice(NEUTRAL_TITLES[lang]), rng.choice(HOTELS)],
            dept_mode=dept_mode,
            total_column=maybe(rng, 0.5),
            total_row=maybe(rng, 0.5),
        )
        return grid_asks_hours(rng, lang, grid, days, basis)
    days = period(rng, 7, monday=True)
    week = days[0].isocalendar().week
    word = "SETTIMANA" if lang == "it" else "WEEK"
    if variant == "week":
        phrase = rng.choice(BASIS_PHRASES[(lang, basis)])
        title = [f"{word} {week} - {phrase}", rng.choice(HOTELS)]
    else:
        title = [rng.choice(NEUTRAL_TITLES[lang])]
    grid = draw_grid(
        rng,
        lang=lang,
        days=days,
        header_kind="weekday",
        basis=basis,
        title_lines=title,
        dept_mode=dept_mode,
        total_column=maybe(rng, 0.5),
        total_row=maybe(rng, 0.5),
    )
    if variant == "week":
        golden = grid_truth(
            grid,
            "ASK",
            fields=grid_fields(grid, basis, work_date=False),
            ambiguous=("work_date",),
            questions=("PERIOD",),
            answers={"period_start": days[0].isoformat()},
            note="Mon..Sun and a week number without a year: the week is the person's to name.",
        )
    else:
        golden = grid_truth(
            grid,
            "ASK",
            fields=grid_fields(grid, None, work_date=False),
            ambiguous=("work_date", "planned_hours", "actual_hours"),
            questions=("PERIOD", "GRID_HOURS"),
            answers={"period_start": days[0].isoformat(), "grid_hours": basis},
            note="No date, no week and nothing about the hours: both must be asked.",
        )
    return finish(file_name(rng, lang, "xlsx"), [grid.sheet], golden)


# --- two-level headers ----------------------------------------------------------------------------

LOWER_PLANNED = {
    "it": ("Previste", "Pianificate", "Programmate", "Prev."),
    "en": ("Planned", "Scheduled", "Rostered"),
}
LOWER_ACTUAL = {
    "it": ("Effettive", "Consuntivo", "Svolte", "Lavorate", "Eff."),
    "en": ("Actual", "Worked", "Clocked"),
}
UPPER_HOURS = {"it": ("Ore", "Ore di lavoro", "Ore turno"), "en": ("Hours", "Working hours", "Hrs")}
UPPER_OTHER = {
    "it": ("Anagrafica", "Turno", "Dati turno", "Personale"),
    "en": ("Staff", "Shift", "Employee"),
}


def hard_two_level_header(rng: random.Random) -> Built:
    """Hours over Planned | Worked: the meaning is in the two lines together."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    hours_group = rng.choice(UPPER_HOURS[lang])
    other = rng.choice(UPPER_OTHER[lang])
    lower_planned = rng.choice(LOWER_PLANNED[lang])
    lower_actual = rng.choice(LOWER_ACTUAL[lang])
    date_col, dept_col, planned_col, actual_col = core_cols(rng, style)
    who = person_col(rng, lang)
    ordered: list[tuple[Col, str | None]]
    if maybe(rng, 0.5):
        ordered = [(date_col, None), (who, other), (dept_col, other)]
    else:
        elsewhere = rng.choice([g for g in UPPER_OTHER[lang] if g != other])
        ordered = [(date_col, other), (dept_col, other), (who, elsewhere)]
    ordered += [(replace(planned_col, header=lower_planned), hours_group)]
    ordered += [(replace(actual_col, header=lower_actual), hours_group)]
    cols = [c for c, _ in ordered]
    groups = [g for _, g in ordered]
    # a group label sits on the first column of its run (the others are merged under it)
    labels_row: list[str | None] = []
    merges: list[tuple[int, int]] = []
    for index, group in enumerate(groups):
        continues = index > 0 and group is not None and group == groups[index - 1]
        labels_row.append(None if continues else group)
        ends = index + 1 == len(groups) or groups[index + 1] != group
        if group is not None and ends:
            first = index
            while first > 0 and groups[first - 1] == group:
                first -= 1
            if first < index:
                merges.append((first + 1, index + 1))
    sheet = Sheet(sheet_name(rng, lang))
    ref = write_table(
        sheet, headers(cols), records(cols, shifts), upper=labels_row, upper_merges=merges
    )
    meaning = parts(cols, shifts)
    fields: dict[str, Source] = {}
    for col, group in ordered:
        if col.field:
            fields[col.field] = column(group, col.header) if group else column(col.header)
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=fields,
        pii_columns=tuple(
            (group, col.header) if group else (col.header,) for col, group in ordered if col.pii
        ),
        pii_values=meaning["pii_values"],
        labels=labels_of(shifts),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note="Two header lines: groups over the columns.",
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden)


# --- more than one table --------------------------------------------------------------------------

LEGENDS = {
    "it": (
        ("M", "Mattino 06:00-14:00"),
        ("P", "Pomeriggio 14:00-22:00"),
        ("N", "Notte 22:00-06:00"),
        ("R", "Riposo"),
        ("F", "Ferie"),
    ),
    "en": (
        ("E", "Early 06:00-14:00"),
        ("L", "Late 14:00-22:00"),
        ("N", "Night 22:00-06:00"),
        ("OFF", "Day off"),
        ("AL", "Annual leave"),
    ),
}


def hard_decoy_tables(rng: random.Random) -> Built:
    """A small table or a band of figures sits next to the real table of shifts."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 6))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    decoy = rng.choice(("legend", "summary", "band"))
    where = "above" if decoy == "band" else rng.choice(("above", "below", "sheet"))
    sheet = Sheet(sheet_name(rng, lang))
    other = Sheet("Riepilogo" if lang == "it" else "Summary")

    def draw(target: Sheet) -> None:
        if decoy == "legend":
            codes = rng.sample(LEGENDS[lang], 4)
            head = ["Codice", "Significato"] if lang == "it" else ["Code", "Meaning"]
            write_table(target, head, [list(r) for r in codes], header_style="header_soft")
        elif decoy == "summary":
            head = [cols[1].header, cols[2].header, cols[3].header]
            rows = [
                [
                    d,
                    round(sum(s.planned for s in shifts if s.dept == d), 1),
                    round(sum(s.actual for s in shifts if s.dept == d), 1),
                ]
                for d in depts
            ]
            write_table(target, head, rows, header_style="header_soft")
        else:
            target.add(
                [
                    "Ore previste totali",
                    round(sum(s.planned for s in shifts), 1),
                    None,
                    "Persone",
                    len({s.person for s in shifts}),
                ]
                if lang == "it"
                else [
                    "Planned hours total",
                    round(sum(s.planned for s in shifts), 1),
                    None,
                    "Staff",
                    len({s.person for s in shifts}),
                ],
                style="band",
            )

    if where == "above":
        sheet.title_line(rng.choice(TITLES[lang]), 5)
        sheet.blank()
        draw(sheet)
        sheet.blank()
    elif where == "sheet":
        draw(other)
    ref = write_table(sheet, headers(cols), records(cols, shifts))
    if where == "below":
        sheet.blank(2)
        draw(sheet)
    sheets = [other, sheet] if where == "sheet" else [sheet]
    golden = golden_from(
        cols,
        shifts,
        ref,
        sheets=[sheet.title],
        tolerated=("TABLE",),
        labels=labels_of(shifts),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note=f"A {decoy} sits {where} the real table: the table with the shifts is the data.",
    )
    return finish(file_name(rng, lang, "xlsx"), sheets, golden)


def hard_two_tables_ask(rng: random.Random) -> Built:
    """Two periods of the same rota stacked on a sheet: which one to import is the person's call."""
    style = pick_style(rng)
    lang = style.lang
    kind = rng.choice(("weeks", "months"))
    count = rng.randint(3, 5)
    if kind == "weeks":
        first = period(rng, count, monday=True)
        second = [d + timedelta(days=7) for d in first]
    else:  # the same days of two consecutive months
        month, start = rng.randint(3, 9), rng.randint(13, 22)
        first = [date(2026, month, start + i) for i in range(count)]
        second = [date(2026, month + 1, start + i) for i in range(count)]
    depts = pick_departments(rng, lang, rng.randint(2, 3))
    base = rng.randint(0, 1900)
    people = rng.randint(3, 5)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    sheet = Sheet(sheet_name(rng, lang))
    refs: list[TableRef] = []
    every: list[Shift] = []
    for number, days in enumerate((first, second)):
        mine = roster(rng, people=people, days=days, depts=depts, first_person=base)
        every.extend(mine)
        if kind == "weeks":
            label = f"{'Settimana' if lang == 'it' else 'Week'} {days[0].isocalendar().week}"
        else:
            label = f"{MONTHS_LONG[lang][days[0].month - 1].capitalize()} {days[0].year}"
        if number:
            sheet.blank(2)
        sheet.add([label], style="label")
        refs.append(write_table(sheet, headers(cols), records(cols, mine)))
    chosen = rng.choice((0, 1))
    golden = golden_from(
        cols,
        every,
        refs[chosen],
        "ASK",
        questions=("TABLE",),
        answers={"table_first_row": refs[chosen].first_row},
        labels=labels_of(every),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note=f"Two {kind} of the same columns on one sheet; the person picks the "
        f"{'first' if chosen == 0 else 'second'} (row {refs[chosen].first_row}).",
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden)


def hard_deep_header(rng: random.Random) -> Built:
    """The header is far down: company details, a legend and a band of totals come first."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 6))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    cols.extend(junk_cols(rng, lang, 1))
    rng.shuffle(cols)
    hotel = rng.choice(HOTELS)
    planned = round(sum(s.planned for s in shifts), 1)
    actual = round(sum(s.actual for s in shifts), 1)
    if lang == "it":
        pre: list[Any] = [
            ("title", f"{hotel.upper()} S.R.L."),
            ("subtitle", f"Via del Porto {rng.randint(1, 90)} - 00100 Esempio"),
            "Ufficio personale",
            f"Rif. interno HR-2026-{rng.randint(10, 99)}",
            f"Revisione {rng.randint(1, 5)} del {long_date(lang, days[0] - timedelta(days=3))}",
            "Redatto da: Direzione",
            "Legenda: ore in decimali",
            ("band", "Ore previste totali", planned, None, "Ore effettive totali", actual),
        ]
    else:
        pre = [
            ("title", f"{hotel.upper()} LTD"),
            ("subtitle", f"{rng.randint(1, 90)} Harbour Road - Example"),
            "Human resources",
            f"Internal ref HR-2026-{rng.randint(10, 99)}",
            f"Revision {rng.randint(1, 5)} of {long_date(lang, days[0] - timedelta(days=3))}",
            "Prepared by: Management",
            "Legend: hours in decimals",
            ("band", "Planned hours total", planned, None, "Actual hours total", actual),
        ]
    sign = "Firma responsabile: ____________" if lang == "it" else "Manager signature: ________"
    label = totals_label(rng, lang)

    def wrap(body: list[list[Any]]) -> list[Any]:
        return [*body, Total(sum_row(cols, shifts, style, label)), Note(sign)]

    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        preamble=pre,
        wrap=wrap,
        left=rng.choice((0, 0, 1, 2)),
    )


def hard_bare_ore(rng: random.Random) -> Built:
    """Hours under a header that is only part of a name: plan or worked is not in the file."""
    lang = pick_language(rng)
    style = pick_style(rng, lang=lang)
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    bare = rng.choice(("Ore", "Ore", "H") if lang == "it" else ("Hours", "Hrs", "Hours"))
    date_col, dept_col, *_ = core_cols(rng, style)
    who = person_col(rng, lang)
    if maybe(rng, 0.55):
        cols = [
            date_col,
            who,
            dept_col,
            Col(
                bare, lambda s: hours_cell(s.planned, style.hours), "planned_hours", ambiguous=True
            ),
            Col(bare, lambda s: hours_cell(s.actual, style.hours), "actual_hours", ambiguous=True),
        ]
        answers: dict[str, Any] = {
            "column_fields": [
                {"header": [bare], "occurrence": 1, "field": "planned_hours"},
                {"header": [bare], "occurrence": 2, "field": "actual_hours"},
            ]
        }
        ambiguous = ("planned_hours", "actual_hours")
        note = (
            f"Two columns called '{bare}': which is the plan and which the time worked is a call."
        )
    else:
        field = rng.choice(("actual_hours", "actual_hours", "planned_hours"))
        cols = [
            date_col,
            who,
            dept_col,
            Col(
                bare,
                lambda s: hours_cell(
                    s.actual if field == "actual_hours" else s.planned, style.hours
                ),
                field,
                ambiguous=True,
            ),
        ]
        answers = {"column_fields": [{"header": [bare], "occurrence": 1, "field": field}]}
        ambiguous = ("planned_hours", "actual_hours")
        note = f"A single '{bare}' column: planned or worked is not in the document."
    sheet = Sheet(sheet_name(rng, lang))
    ref = write_table(sheet, headers(cols), records(cols, shifts))
    golden = golden_from(
        cols,
        shifts,
        ref,
        "ASK",
        questions=("COLUMN_MEANING",),
        answers=answers,
        ambiguous=ambiguous,
        labels=labels_of(shifts),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note=note,
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden)


def hard_ambiguous_date_order(rng: random.Random) -> Built:
    """Every day is 12 or less: 03/09 is the 3rd of September or the 9th of March."""
    lang = pick_language(rng)
    style = Style(lang, "it", "num")
    first, second = sorted(rng.sample(range(1, 13), 2))
    month_a, month_b = sorted(rng.sample(range(2, 13), 2))
    days = [date(2026, m, d) for m in (month_a, month_b) for d in (first, second)]
    depts = pick_departments(rng, lang, rng.randint(2, 3))
    shifts = roster(rng, people=rng.randint(3, 5), days=days, depts=depts, order="person")
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    as_csv = maybe(rng, 0.4)
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "csv" if as_csv else "xlsx"),
        outcome="ASK",
        csv={"delimiter": ";", "decimal": ",", "dates": "it"} if as_csv else None,
        questions=("DATE_ORDER",),
        answers={"date_order": "DMY"},
        date_order="DMY",
        decimal="," if as_csv else None,
        note="Every day is 12 or less: day-first or month-first cannot be proved.",
    )


def hard_total_contradicts(rng: random.Random) -> Built:
    """The TOTAL line does not add up the rows above it: the document contradicts itself."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 6))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    off_planned = rng.choice((17.5, 24.0, -12.5, 31.0))
    off_actual = rng.choice((-22.0, 9.5, 40.0, -16.5))
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        outcome="WARN",
        wrap=totals_wrap(
            cols,
            shifts,
            style,
            totals_label(rng, lang),
            planned_shift=off_planned,
            actual_shift=off_actual,
        ),
        note=f"The total line is off by {off_planned:+g} planned and {off_actual:+g} worked hours.",
    )


# ==================================================================================================
# ADVERSARIAL: decoys, contradictions, columns that look like something they are not
# ==================================================================================================

SUMMARY_WORDS = {
    ("it", "WEEK"): ("settimana", "sett.", "nel periodo", "totali"),
    ("it", "MONTH"): ("mese", "nel periodo", "totali"),
    ("en", "WEEK"): ("week", "for period", "total"),
    ("en", "MONTH"): ("month", "for period", "total"),
}


def adv_period_summary_only(rng: random.Random) -> Built:
    """Hours per person (or per department) for a whole week or month: no day anywhere."""
    style = pick_style(rng)
    lang = style.lang
    kind = rng.choice(("person_week", "person_month", "dept_month"))
    count = 7 if kind == "person_week" else 28
    days = period(rng, count)
    depts = pick_departments(rng, lang, rng.randint(3, 4))
    shifts = roster(rng, people=rng.randint(5, 8), days=days, depts=depts)
    word = rng.choice(SUMMARY_WORDS[(lang, "WEEK" if kind == "person_week" else "MONTH")])
    planned_h = f"{pick(rng, PLANNED_H, lang)} {word}"
    actual_h = f"{pick(rng, ACTUAL_H, lang)} {word}"
    sheet = Sheet(sheet_name(rng, lang))
    if kind == "person_week":
        heading = "RIEPILOGO ORE SETTIMANA" if lang == "it" else "WEEKLY HOURS SUMMARY"
        heading = f"{heading} {days[0].isocalendar().week}"
    else:
        heading = "RIEPILOGO ORE DEL MESE" if lang == "it" else "MONTHLY HOURS SUMMARY"
        heading = f"{heading} - {MONTHS_LONG[lang][days[0].month - 1].upper()}"
    sheet.title_line(heading, 4)
    sheet.blank()
    if kind == "dept_month":
        month = f"{MONTHS_LONG[lang][days[0].month - 1]} {days[0].year}"
        head = [pick(rng, DEPT_H, lang), "Mese" if lang == "it" else "Month", planned_h, actual_h]
        rows = [
            [
                d,
                month,
                round(sum(s.planned for s in shifts if s.dept == d), 1),
                round(sum(s.actual for s in shifts if s.dept == d), 1),
            ]
            for d in depts
        ]
        ref = write_table(sheet, head, rows)
        golden = Golden(
            "labor",
            "REJECT",
            **facts(ref),
            blockers=("PERIOD_SUMMARY_ONLY",),
            note="Hours per department for a whole month: no day.",
        )
        return finish(file_name(rng, lang, "xlsx"), [sheet], golden)
    person_h = pick(rng, PERSON_H, lang)
    head = [person_h, pick(rng, DEPT_H, lang), planned_h, actual_h]
    rows = []
    names = []
    for index in sorted({s.person for s in shifts}):
        mine = [s for s in shifts if s.person == index]
        names.append(mine[0].name)
        rows.append(
            [
                mine[0].name,
                mine[0].dept,
                round(sum(s.planned for s in mine), 1),
                round(sum(s.actual for s in mine), 1),
            ]
        )
    ref = write_table(sheet, head, rows)
    golden = Golden(
        "labor",
        "REJECT",
        **facts(ref),
        blockers=("PERIOD_SUMMARY_ONLY",),
        **pii([(person_h,)], names),
        note="One line of hours per person for the whole period: hours are never spread over days.",
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden)


def adv_bare_rate_next_to_hours(rng: random.Random) -> Built:
    """A bare 'Costo' / 'Tariffa' sits next to clear hours: it is money per hour, not hours."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    bare = pick(rng, BARE_COST_H, lang)
    cols = [*core_cols(rng, style), person_col(rng, lang), Col(bare, lambda s: s.rate)]
    if maybe(rng, 0.4):
        cols.append(rate_col(rng, lang))
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        note=f"'{bare}' is an amount per hour: it is not the hours and it is never read.",
    )


def adv_names_in_department_column(rng: random.Random) -> Built:
    """The 'Reparto' column holds people's names: there is no department in the document."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 7))
    shifts = roster(rng, people=rng.randint(4, 7), days=days, depts=["-"])
    header = pick(rng, DEPT_H, lang)
    cols = [
        *core_cols(rng, style, dept=False),
        Col(header, lambda s: s.name, pii=True),
    ]
    if maybe(rng, 0.5):
        cols.append(
            Col("Livello" if lang == "it" else "Grade", lambda s: f"Liv. {s.person % 4 + 2}")
        )
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        outcome="NOT_AUTOMATIC",
        absent=("department",),
        note=f"'{header}' holds the names of people: the document has no department.",
    )


KPI_ROWS = (
    ("Assenteismo", "Absenteeism", (2, 6), "4%"),
    ("Incidenza costo lavoro", "Labour cost ratio", (26, 38), "32%"),
    ("Straordinari", "Overtime", (3, 9), "5%"),
    ("Turnover", "Turnover", (8, 25), "15%"),
    ("Ore di formazione per addetto", "Training hours per head", (2, 12), "8"),
    ("Saturazione turni", "Roster fill rate", (82, 99), "95%"),
    ("Ore perse per malattia", "Sick-leave rate", (1, 5), "3%"),
)
KPI_MONTH_COLUMNS = (
    ("Costo lavoro %", "Labour cost %", (26, 38)),
    ("Assenteismo %", "Absenteeism %", (2, 6)),
    ("Turnover %", "Turnover %", (8, 25)),
    ("FTE", "FTE", (18, 60)),
    ("Straordinari %", "Overtime %", (3, 9)),
    ("Costo medio per addetto", "Average cost per head", (1800, 2600)),
)
KPI_TITLES = {
    "it": ("DASHBOARD PERSONALE", "INDICATORI DEL PERSONALE", "CRUSCOTTO RISORSE UMANE"),
    "en": ("STAFF DASHBOARD", "WORKFORCE INDICATORS", "HR SCORECARD"),
}


def adv_kpi_dashboard(rng: random.Random) -> Built:
    """A dashboard of staff indicators: figures for the month, not shifts."""
    lang = pick_language(rng)
    sheet = Sheet("Dashboard" if maybe(rng, 0.6) else sheet_name(rng, lang))
    sheet.title_line(rng.choice(KPI_TITLES[lang]), 5)
    sheet.blank()
    index = 0 if lang == "it" else 1
    if maybe(rng, 0.5):
        chosen = rng.sample(KPI_ROWS, rng.randint(4, 6))
        rows: list[list[Any]] = []
        for row in chosen:
            low, high = row[2]
            shown = f"{rng.uniform(low, high):.1f}" + ("%" if row[3].endswith("%") else "")
            goal = row[3]
            if lang == "it":
                shown, goal = shown.replace(".", ","), goal.replace(".", ",")
            rows.append([row[index], shown, goal])
        rows.append(["FTE", round(rng.uniform(18, 60), 1), rng.choice((35, 40, 45))])
        head = ["Indicatore", "Valore", "Obiettivo"] if lang == "it" else ["KPI", "Value", "Target"]
    else:
        columns = rng.sample(KPI_MONTH_COLUMNS, rng.randint(3, 5))
        head = [
            "Mese" if lang == "it" else "Month",
            *(c[0] if lang == "it" else c[1] for c in columns),
        ]
        first = rng.randint(1, 5)
        rows = [
            [
                MONTHS_LONG[lang][m].capitalize(),
                *(round(rng.uniform(c[2][0], c[2][1]), 1) for c in columns),
            ]
            for m in range(first, first + rng.randint(4, 7))
        ]
    ref = write_table(sheet, head, rows)
    golden = Golden(
        "other", "REJECT", **facts(ref), note="Staff indicators of the period: no shift in it."
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden)


def adv_impossible_hours(rng: random.Random) -> Built:
    """Some rows hold hours nobody can work in a day: negative, or more than 24."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(4, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 3))
    shifts = roster(rng, people=rng.randint(4, 6), days=days, depts=depts)
    for index in rng.sample(range(len(shifts)), rng.randint(2, 4)):
        bad = rng.choice((-8.0, -3.5, -1.0, 25.0, 30.0, 36.5, 48.0))
        if maybe(rng, 0.7):
            shifts[index] = replace(shifts[index], actual=bad)
        else:
            shifts[index] = replace(shifts[index], planned=bad)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        outcome="NOT_AUTOMATIC",
        note="A few rows hold a negative or more than 24 hours in a day: never imported blindly.",
    )


def adv_identical_planned_actual(rng: random.Random) -> Built:
    """Planned and worked hours are the same number on every row (two clear columns, one value)."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(4, 8))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = [
        replace(s, actual=s.planned)
        for s in roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    ]
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    if maybe(rng, 0.4):
        cols.extend(junk_cols(rng, lang, 1))
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, lang, "xlsx"),
        note="Planned and actual hours are identical copies; both headers are clear: both read.",
    )


BOOKING_HEADERS = {
    "it": (
        ("N. Prenotazione", "Prenotata il", "Check-in", "Check-out", "Canale", "Ricavo camera"),
        ("Cod. pren.", "Data creazione", "Arrivo", "Partenza", "Fonte", "Importo soggiorno"),
        ("Rif. prenotazione", "Inserita il", "Dal", "Al", "Portale", "Totale camere"),
    ),
    "en": (
        ("Reservation No.", "Booked On", "Arrival", "Departure", "Channel", "Room Revenue"),
        ("Booking Ref", "Created", "Check In", "Check Out", "Source", "Room Amount"),
        ("Conf. No.", "Date Booked", "Arr.", "Dep.", "Sales Channel", "Accommodation Revenue"),
    ),
}
STAFFLIKE_TITLES = {
    "it": (
        "PIANO TURNI RECEPTION",
        "TURNI SALA - SETTIMANA",
        "ROTA ADDETTI AL RICEVIMENTO",
        "PRESENZE PERSONALE DI FRONT OFFICE",
        "ORE REPARTO PIANI",
    ),
    "en": (
        "FRONT DESK ROSTER",
        "STAFF SHIFTS THIS WEEK",
        "HOUSEKEEPING HOURS",
        "ATTENDANCE - RECEPTION TEAM",
    ),
}


def adv_bookings_under_staff_title(rng: random.Random) -> Built:
    """A staff-looking title and sheet name over a table of reservations."""
    lang = pick_language(rng)
    heads = list(rng.choice(BOOKING_HEADERS[lang]))
    extra = rng.choice(("none", "status", "guests"))
    if extra == "status":
        heads.append("Stato" if lang == "it" else "Status")
    elif extra == "guests":
        heads.append("Ospiti" if lang == "it" else "Guests")
    channels = ("Booking.com", "Diretto", "Expedia", "Sito web", "Airbnb", "Telefono")
    statuses = ("Confermata", "Cancellata") if lang == "it" else ("Confirmed", "Cancelled")
    sheet = Sheet(
        rng.choice(("Turni", "Presenze", "Foglio1") if lang == "it" else ("Roster", "Shifts"))
    )
    sheet.title_line(rng.choice(STAFFLIKE_TITLES[lang]), len(heads))
    sheet.blank()
    body = []
    start = date(2026, 6, 1) + timedelta(days=rng.randint(0, 120))
    for i in range(rng.randint(8, 14)):
        arrival = start + timedelta(days=rng.randint(0, 20))
        nights = rng.choice((1, 2, 3, 4, 7))
        row: list[Any] = [
            f"BK{rng.randint(100000, 999999)}",
            datetime.combine(arrival - timedelta(days=rng.randint(3, 60)), datetime.min.time()),
            datetime.combine(arrival, datetime.min.time()),
            datetime.combine(arrival + timedelta(days=nights), datetime.min.time()),
            channels[(i + rng.randint(0, 2)) % len(channels)],
            round(rng.choice((89.0, 119.0, 149.0, 189.0)) * nights, 2),
        ]
        if extra == "status":
            row.append(rng.choice(statuses))
        elif extra == "guests":
            row.append(rng.randint(1, 4))
        body.append(row)
    ref = write_table(sheet, heads, body)
    golden = Golden(
        "bookings",
        "NOT_AUTOMATIC",
        **facts(ref),
        questions=("DOMAIN",),
        note="The title and the sheet name say staff; the columns and the values are reservations.",
    )
    return finish(file_name(rng, lang, "xlsx"), [sheet], golden, card="labor")


HOTEL_CODES = (
    "U.O. 3",
    "CC 410",
    "Squadra Blu",
    "Gruppo Delta",
    "Sett. 7",
    "Blocco C",
    "Linea 2",
    "R-14",
    "Cod. 22",
    "Team Alfa",
    "T-05",
    "Zona Nord",
)


def adv_department_codes(rng: random.Random) -> Built:
    """Department codes only this hotel can read: the person has to say what they are."""
    style = pick_style(rng, lang="it")
    days = period(rng, rng.randint(3, 6))
    codes = rng.sample(HOTEL_CODES, rng.randint(2, 3))
    known = pick_departments(rng, "it", rng.randint(0, 2), admin=False) if maybe(rng, 0.5) else []
    depts = [*known, *codes]
    shifts = roster(rng, people=max(len(depts) + 1, rng.randint(4, 7)), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, "it")]
    truth = {**{w: CATEGORY_OF[w] for w in known}, **{c: "?" for c in codes}}
    taught = {c: rng.choice(CATEGORIES) for c in codes}
    return document(
        rng,
        cols,
        shifts,
        style,
        name=file_name(rng, "it", "xlsx"),
        outcome="ASK",
        labels={"role_mapping": truth},
        questions=("VALUE_LABELS",),
        answers={"labels": {"role_mapping": taught}},
        note="The department words are internal codes: what they are is the person's to say.",
    )


def adv_revised_planned_hours(rng: random.Random) -> Built:
    """'Ore previste' and its revision side by side: which one is the plan is the person's call."""
    lang = pick_language(rng)
    style = pick_style(rng, lang=lang)
    pairs = {
        "it": (
            ("Ore previste", "Ore previste (rev.)"),
            ("Ore pianificate", "Ore pianificate - rev."),
            ("Ore prev.", "Ore prev. rev.2"),
        ),
        "en": (
            ("Planned Hours", "Planned Hours (revised)"),
            ("Sched. Hrs", "Sched. Hrs (rev.)"),
        ),
    }[lang]
    original_h, revised_h = rng.choice(pairs)
    days = period(rng, rng.randint(3, 7))
    depts = pick_departments(rng, lang, rng.randint(2, 4))
    shifts = roster(rng, people=rng.randint(3, 6), days=days, depts=depts)
    date_col, dept_col, _, actual_col = core_cols(rng, style)

    def revised(s: Shift) -> float:
        return max(2.0, s.planned + ((s.person + s.day.day) % 5 - 2) * 0.5)

    cols = [
        date_col,
        person_col(rng, lang),
        dept_col,
        Col(
            original_h,
            lambda s: hours_cell(s.planned, style.hours),
            "planned_hours",
            ambiguous=True,
        ),
        Col(
            revised_h,
            lambda s: hours_cell(revised(s), style.hours),
            "planned_hours",
            ambiguous=True,
        ),
        actual_col,
    ]
    chosen = rng.choice((original_h, revised_h))
    return deduplicated(
        document(
            rng,
            cols,
            shifts,
            style,
            name=file_name(rng, lang, "xlsx"),
            outcome="ASK",
            questions=("COLUMN_MEANING",),
            answers={
                "column_fields": [{"header": [chosen], "occurrence": 1, "field": "planned_hours"}]
            },
            note=f"'{original_h}' and '{revised_h}': which one is the plan is the person's call.",
        )
    )


def adv_data_on_a_hidden_sheet(rng: random.Random) -> Built:
    """The shifts are on a hidden sheet; the visible one only talks about them."""
    style = pick_style(rng)
    lang = style.lang
    days = period(rng, rng.randint(3, 6))
    depts = pick_departments(rng, lang, rng.randint(2, 3))
    shifts = roster(rng, people=rng.randint(3, 5), days=days, depts=depts)
    cols = [*core_cols(rng, style), person_col(rng, lang)]
    hidden = Sheet(sheet_name(rng, lang), hidden=True)
    ref = write_table(hidden, headers(cols), records(cols, shifts))
    cover = Sheet(
        rng.choice(
            ("LEGGIMI", "Istruzioni", "Info") if lang == "it" else ("README", "Notes", "Info")
        )
    )
    cover.add(
        [
            f"I turni sono nel foglio nascosto '{hidden.title}'."
            if lang == "it"
            else f"The shifts are on the hidden sheet '{hidden.title}'."
        ]
    )
    golden = golden_from(
        cols,
        shifts,
        ref,
        "NOT_AUTOMATIC",
        sheets=[hidden.title],
        labels=labels_of(shifts),
        date_order=order_of(style.dates),
        decimal=style.decimal,
        note="The records are on a hidden sheet: nothing is imported without a person.",
    )
    return finish(file_name(rng, lang, "xlsx"), [cover, hidden], without_table(golden))


RECIPES: dict[str, Sequence[Maker]] = {
    "EASY": (
        easy_xlsx_roster,
        easy_csv_semicolon,
        easy_xlsx_title_block,
        easy_daily_by_department,
        easy_one_hours_column,
    ),
    "MEDIUM": (
        medium_reorder_noise,
        medium_personal_data,
        medium_hourly_rate,
        medium_text_formats,
        medium_csv_dialects,
        medium_hidden_extra_sheets,
        medium_other_hours_and_dates,
        medium_english_export,
    ),
    "HARD": (
        hard_sections,
        hard_sheet_per_department,
        hard_title_department,
        hard_grid_stated,
        hard_grid_ask,
        hard_two_level_header,
        hard_decoy_tables,
        hard_two_tables_ask,
        hard_deep_header,
        hard_bare_ore,
        hard_ambiguous_date_order,
        hard_total_contradicts,
    ),
    "ADVERSARIAL": (
        adv_period_summary_only,
        adv_bare_rate_next_to_hours,
        adv_names_in_department_column,
        adv_kpi_dashboard,
        adv_impossible_hours,
        adv_identical_planned_actual,
        adv_bookings_under_staff_title,
        adv_department_codes,
        adv_revised_planned_hours,
        adv_data_on_a_hidden_sheet,
    ),
}


def build() -> list[Doc]:
    return assemble("UL", "labor", RECIPES)


__all__ = ["RECIPES", "build"]

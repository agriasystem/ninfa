"""Synthetic people, places and formats for the corpus.

Everything here is invented. Names are plausible but combined at random; e-mail addresses live on
`example.org`; telephone numbers use a block of subscriber numbers starting `000`; tax codes use a
month letter (`Z`) that does not exist in a real one, so none of them can belong to a real person.
"""

import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tests.benchmarks.smart_import_v3.draw import Styled

HOTEL = "Hotel Aurora"
WEEK = date(2026, 10, 19)  # a Monday, ISO week 43 of 2026

FIRST_NAMES = [
    "Giulia",
    "Marco",
    "Elena",
    "Davide",
    "Chiara",
    "Matteo",
    "Sara",
    "Luca",
    "Francesca",
    "Alessio",
    "Ilaria",
    "Tommaso",
    "Valentina",
    "Riccardo",
    "Martina",
    "Federico",
    "Silvia",
    "Nicola",
    "Beatrice",
    "Emanuele",
    "Camilla",
    "Stefano",
    "Arianna",
    "Gabriele",
    "Noemi",
    "Simone",
    "Alice",
    "Filippo",
    "Serena",
    "Andrea",
    "Lucia",
    "Pietro",
    "Veronica",
    "Daniele",
    "Margherita",
    "Michele",
    "Elisa",
    "Antonio",
    "Paola",
    "Claudio",
    "Roberta",
    "Enrico",
    "Monica",
    "Fabio",
    "Cristina",
    "Massimo",
    "Laura",
    "Giorgio",
]
LAST_NAMES = [
    "Ferretti",
    "Bellandi",
    "Cattaneo",
    "Brambilla",
    "Montanari",
    "Sabatini",
    "Ghidini",
    "Rinaldi",
    "Tognazzi",
    "Zanetti",
    "Pellegrini",
    "Barbieri",
    "Lombardini",
    "Gasparri",
    "Orlandi",
    "Valenti",
    "Cremonesi",
    "Marchetti",
    "Santini",
    "Baldini",
    "Colombini",
    "Dallari",
    "Paganelli",
    "Rizzi",
    "Silvestri",
    "Fabbrini",
    "Lazzari",
    "Bertolini",
    "Carrara",
    "Donati",
    "Filippini",
    "Innocenti",
    "Landi",
    "Magnani",
    "Nardi",
    "Olivieri",
    "Parisi",
    "Rosati",
    "Sartori",
    "Tedeschi",
    "Alberti",
    "Boscolo",
    "Cerutti",
    "Danesi",
    "Farnesi",
    "Gentili",
    "Maffei",
    "Pozzi",
]
GUEST_FIRST = [
    "James",
    "Emma",
    "Lukas",
    "Sofie",
    "Pierre",
    "Camille",
    "Hans",
    "Greta",
    "Oliver",
    "Isla",
    "Mateo",
    "Lucia",
    "Jan",
    "Eva",
    "Noah",
    "Mia",
    "Thomas",
    "Hannah",
    "Erik",
    "Ingrid",
    "Jonas",
    "Clara",
    "Paul",
    "Anja",
    "Victor",
    "Elodie",
    "Tobias",
    "Lena",
    "Mathis",
    "Sandra",
]
GUEST_LAST = [
    "Whitfield",
    "Brandt",
    "Lefevre",
    "Kowalski",
    "Andersson",
    "Novak",
    "Hartmann",
    "Moreau",
    "Fischer",
    "Larsen",
    "Jansen",
    "Duarte",
    "Petersen",
    "Lindqvist",
    "Vasquez",
    "Okafor",
    "Albrecht",
    "Delmas",
    "Eriksen",
    "Holloway",
    "Ivanov",
    "Janssens",
    "Keller",
    "Lorenz",
    "Mertens",
    "Nilsson",
    "Ostrowski",
    "Prieto",
    "Quint",
    "Ramsey",
]
SUPPLIERS = [
    "Edilgas Servizi S.r.l.",
    "Lavanderia Marinelli S.n.c.",
    "Forniture Alberghiere Tirreno S.p.A.",
    "Pulizie Riviera Soc. Coop.",
    "Elettra Energia S.p.A.",
    "Panificio Delle Dune di Rossi G.",
    "Software Ospitalità Cloud S.r.l.",
    "Studio Grafico Linea Blu",
    "Ortofrutta Bellavista S.r.l.",
    "Termoidraulica Santini & C.",
    "Agenzia Pubblicità Costa Verde",
    "Bevande del Borgo S.r.l.",
    "Giardinaggio Villa Fiorita",
    "Assicurazioni Adria Group S.p.A.",
    "Caffè Torrefazione Arabica S.r.l.",
]


def person(index: int) -> tuple[str, str]:
    """The index-th synthetic staff member (distinct for the first 2300)."""
    return FIRST_NAMES[index % 48], LAST_NAMES[(index * 7 + index // 48) % 48]


def guest(index: int) -> tuple[str, str]:
    return GUEST_FIRST[index % 30], GUEST_LAST[(index * 7 + index // 30) % 30]


def full_name(index: int, *, last_first: bool = False) -> str:
    first, last = person(index)
    return f"{last} {first}" if last_first else f"{first} {last}"


def guest_name(index: int, *, last_first: bool = False) -> str:
    first, last = guest(index)
    return f"{last} {first}" if last_first else f"{first} {last}"


def email_of(first: str, last: str) -> str:
    return f"{first}.{last}@example.org".lower()


def phone_of(index: int) -> str:
    return f"+39 333 000{index % 10000:04d}"


def tax_code_of(index: int) -> str:
    first, last = person(index)
    return (
        f"{last[:3]}{first[:3]}".upper()
        + f"{70 + index % 30:02d}Z{1 + index % 28:02d}Z{index % 1000:03d}X"
    )


def seeded(case_id: str, seed: str = "smart-import-v3-benchmark-v1") -> random.Random:
    """A generator that depends on the case alone (adding a case never changes another)."""
    return random.Random(f"{seed}:{case_id}")


# --- dates ----------------------------------------------------------------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS_IT = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


def week(start: date = WEEK, days: int = 7) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def when(day: date, style: str) -> Any:
    """A date as a document writes it."""
    if style == "xl":
        return datetime(day.year, day.month, day.day)
    if style == "xl_iso":
        return Styled(datetime(day.year, day.month, day.day), fmt="YYYY-MM-DD")
    if style == "xl_long":
        return Styled(datetime(day.year, day.month, day.day), fmt="DDDD DD MMMM YYYY")
    if style == "it":
        return day.strftime("%d/%m/%Y")
    if style == "iso":
        return day.isoformat()
    if style == "dotted":
        return day.strftime("%d.%m.%Y")
    if style == "us":
        return day.strftime("%m/%d/%Y")
    if style == "dash_mon":
        return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"
    if style == "weekday":
        return f"{_DAYS_IT[day.weekday()]} {day.strftime('%d/%m/%Y')}"
    if style == "short":
        return day.strftime("%d/%m/%y")
    raise ValueError(style)


def stamp(day: date, hour: int, minute: int, style: str = "xl") -> Any:
    """A date with a time of day (when a booking was made)."""
    moment = datetime(day.year, day.month, day.day, hour, minute)
    if style == "xl":
        return moment
    if style == "iso":
        return moment.strftime("%Y-%m-%d %H:%M")
    if style == "it":
        return moment.strftime("%d/%m/%Y %H:%M")
    raise ValueError(style)


# --- numbers --------------------------------------------------------------------------------------


def money(value: Decimal | float | int, style: str) -> Any:
    """An amount as a document writes it."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    sign = "-" if amount < 0 else ""
    grouped_it = f"{int(whole):,}".replace(",", ".")
    grouped_us = f"{int(whole):,}"
    if style == "num":
        return float(amount)
    if style == "num_eur":
        return Styled(float(amount), fmt='#,##0.00 "€"')
    if style == "num_fmt":
        return Styled(float(amount), fmt="#,##0.00")
    if style == "it":
        return f"{sign}{grouped_it},{cents}"
    if style == "it_plain":
        return f"{sign}{whole},{cents}"
    if style == "us":
        return f"{sign}{grouped_us}.{cents}"
    if style == "point":
        return f"{sign}{whole}.{cents}"
    if style == "eur_prefix":
        return f"{sign}€ {grouped_it},{cents}"
    if style == "eur_suffix":
        return f"{sign}{grouped_it},{cents} €"
    if style == "eur_prefix_point":
        return f"{sign}€{grouped_us}.{cents}"
    raise ValueError(style)


def hours(value: float, style: str = "num") -> Any:
    if style == "num":
        return value
    if style == "comma":
        return f"{value:.1f}".replace(".", ",")
    if style == "point":
        return f"{value:.1f}"
    raise ValueError(style)

"""Universal Understanding 2 - what a header means, read by words, abbreviations and VALUES.

Every rule added in this gate has its counter-example here: the words that look like it and must
not do the same. A rule without a counter-example is a vocabulary list; with one it is a rule.

No database, no network, no model.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from app.modules.bookings.normalization import DateOrder, detect_date_order
from app.modules.data_sources.column_profile import ColumnSample, date_pattern
from app.modules.data_sources.proposal import propose
from app.modules.data_sources.relations import stay_dates
from app.modules.data_sources.semantics import (
    DomainSem,
    Level,
    expand_abbreviations,
    fit_unique_identifier,
)
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.stats import column_stats
from app.modules.ingestion.value_text import month_name_date

DAY = date(2026, 10, 20)


def column(header: str, values: Sequence[Any], position: int = 0) -> ColumnSample:
    return ColumnSample(
        position, header, tuple(str(v) for v in values[:3]), tuple(values), tuple(values)
    )


def field_of(sem: DomainSem, header: str, values: Sequence[Any]) -> tuple[str | None, Level | None]:
    proposal = propose(sem, [column(header, values)])
    only = proposal.columns[0]
    return only.field, only.level


ARRIVALS = [datetime.combine(DAY + timedelta(days=i * 3), datetime.min.time()) for i in range(6)]
DEPARTURES = [arrival + timedelta(days=2 + i % 3) for i, arrival in enumerate(ARRIVALS)]
CODES = [f"RES-{1000 + i}" for i in range(6)]
SMALL = [1, 1, 2, 1, 3, 1]
MONEY = [120.5, 99.0, 310.25, 87.0, 150.0, 205.75]
HOURS = [8, 7.5, 6, 8, 7, 8]
DEPARTMENTS = ["Sala", "Bar", "Cucina", "Reception", "Sala", "Bar"]
INVOICES = [f"FT/26/{i:04d}" for i in range(6)]
SUPPLIERS = ["Alfa Srl", "Beta Spa", "Gamma Srl", "Alfa Srl", "Delta Snc", "Beta Spa"]
TEXT = ["Pulizie", "Forniture", "Consulenza", "Energia", "Manutenzione", "Lavanderia"]

# --- the words of each concept family: a header and what its values must be --------------------

BOOKING_CASES: list[tuple[str, list[Any], str]] = [
    ("Data ingresso", ARRIVALS, "check_in"),
    ("Data uscita", DEPARTURES, "check_out"),
    ("Stanze", SMALL, "rooms"),
    ("Camere prenotate", SMALL, "rooms"),
    ("Q.tà camere", SMALL, "rooms"),
    ("Rms", SMALL, "rooms"),
    ("Corrispettivo camere", MONEY, "room_revenue"),
    ("Fatturato camere", MONEY, "room_revenue"),
    ("Accommodation Revenue", MONEY, "room_revenue"),
    ("Pratica n.", CODES, "source_record_id"),
    ("Localizzatore", CODES, "source_record_id"),
    ("Conf. No.", CODES, "source_record_id"),
    ("Registrata il", ARRIVALS, "booked_at"),
    (
        "Prenotato tramite",
        ["Booking.com", "Expedia", "Diretto", "Booking.com", "Expedia", "Diretto"],
        "channel",
    ),
    (
        "Booked Via",
        ["Booking.com", "Expedia", "Diretto", "Booking.com", "Expedia", "Diretto"],
        "channel",
    ),
]


@pytest.mark.parametrize(("header", "values", "expected"), BOOKING_CASES)
def test_bookings_headers_of_other_exporters_are_read(
    header: str, values: list[Any], expected: str
) -> None:
    field, level = field_of(BOOKINGS, header, values)

    assert field == expected and level is not Level.LOW


LABOR_CASES: list[tuple[str, list[Any], str]] = [
    ("Clocked Hrs", HOURS, "actual_hours"),
    ("Time Worked (hrs)", HOURS, "actual_hours"),
    ("Rostered Hrs", HOURS, "planned_hours"),
    ("Plan (h)", HOURS, "planned_hours"),
    ("Giornata", ARRIVALS, "work_date"),
    ("U.O.", DEPARTMENTS, "role"),
    ("Operating Unit", DEPARTMENTS, "role"),
    ("Section", DEPARTMENTS, "role"),
]


@pytest.mark.parametrize(("header", "values", "expected"), LABOR_CASES)
def test_staff_headers_of_other_exporters_are_read(
    header: str, values: list[Any], expected: str
) -> None:
    field, level = field_of(LABOR, header, values)

    assert field == expected and level is not Level.LOW


COST_CASES: list[tuple[str, list[Any], str]] = [
    ("Descr.", TEXT, "line_description"),
    ("Prestazione", TEXT, "line_description"),
    ("Goods / Services", TEXT, "line_description"),
    ("Ditta", SUPPLIERS, "supplier_name"),
    ("Billed By", SUPPLIERS, "supplier_name"),
    ("Payee", SUPPLIERS, "supplier_name"),
    ("Rag. sociale", SUPPLIERS, "supplier_name"),
    ("Inv Ref", INVOICES, "invoice_number"),
    ("Bill No.", INVOICES, "invoice_number"),
    ("Fattura del", ARRIVALS, "invoice_date"),
    ("Issue Date", ARRIVALS, "invoice_date"),
    ("Aliq. IVA", [22, 22, 10, 22, 10, 22], "vat_rate"),
    ("Total with Tax", MONEY, "invoice_gross_amount"),
]


@pytest.mark.parametrize(("header", "values", "expected"), COST_CASES)
def test_cost_headers_of_other_exporters_are_read(
    header: str, values: list[Any], expected: str
) -> None:
    field, level = field_of(COSTS, header, values)

    assert field == expected and level is not Level.LOW


# --- counter-examples: look alike, but not the same thing ---------------------------------------


@pytest.mark.parametrize(
    ("sem", "header", "values"),
    [
        # "Camera" is as often the room itself as a count of rooms: not a count by its word
        (BOOKINGS, "Camera", ["101", "102", "103", "104", "105", "106"]),
        # a "Stanze" column of names is not a count
        (BOOKINGS, "Stanze", ["Rossa", "Blu", "Verde", "Gialla", "Rossa", "Blu"]),
        # the values of an arrival are dates
        (BOOKINGS, "Data ingresso", ["si", "no", "si", "no", "si", "no"]),
        # a revenue is money, not words
        (BOOKINGS, "Corrispettivo camere", ["a", "b", "c", "d", "e", "f"]),
        # hours are small numbers
        (LABOR, "Clocked Hrs", [400, 520, 380, 610, 450, 500]),
        # a department is a word, not a number
        (LABOR, "U.O.", [1, 2, 3, 4, 5, 6]),
        # the "Ditta" of a column of amounts is not a supplier
        (COSTS, "Ditta", MONEY),
    ],
)
def test_look_alike_headers_over_the_wrong_values_are_not_read(
    sem: DomainSem, header: str, values: list[Any]
) -> None:
    field, level = field_of(sem, header, values)

    assert field is None or level is Level.LOW


def test_a_payslip_is_not_an_amount_of_a_cost_register() -> None:
    for header in ("Netto in busta", "Netto busta paga", "Stipendio netto"):
        field, _level = field_of(COSTS, header, MONEY)
        assert field not in {"line_total", "invoice_net_amount", "invoice_gross_amount"}


# --- abbreviations: only a written abbreviation, only one meaning ------------------------------


def test_an_abbreviation_with_a_point_is_read_as_the_word_it_cuts() -> None:
    assert "descrizion" in expand_abbreviations(COSTS, "Descr. articolo")
    assert "aliquot" in expand_abbreviations(COSTS, "Aliq. IVA")


@pytest.mark.parametrize("header", ["Descr articolo", "Descrizione", "Imp. netto", "Xyz. nome"])
def test_what_is_not_a_clear_abbreviation_is_not_expanded(header: str) -> None:
    # no point (a bare "Descr" is a word of its own), already a word, three different words
    # ("imponibile", "imposta", "importo") or no word at all
    assert not expand_abbreviations(COSTS, header)


# --- relations: the VALUES of two columns confirm each other -----------------------------------


def test_an_arrival_and_a_departure_confirm_each_other_whatever_they_are_called() -> None:
    proposal = propose(BOOKINGS, [column("CI", ARRIVALS, 0), column("CO", DEPARTURES, 1)])

    assert {c.field: c.level for c in proposal.columns} == {
        "check_in": Level.HIGH,
        "check_out": Level.HIGH,
    }


def test_the_abbreviations_alone_stay_a_question_when_the_dates_do_not_agree() -> None:
    reversed_ = propose(BOOKINGS, [column("CI", DEPARTURES, 0), column("CO", ARRIVALS, 1)])
    unrelated = propose(
        BOOKINGS, [column("CI", ARRIVALS, 0), column("CO", list(reversed(ARRIVALS)), 1)]
    )

    for proposal in (reversed_, unrelated):
        assert all(c.level is not Level.HIGH for c in proposal.columns)


def test_a_lone_abbreviation_is_never_certain() -> None:
    proposal = propose(BOOKINGS, [column("CI", ARRIVALS)])

    assert proposal.columns[0].level is not Level.HIGH


def test_stay_dates_need_most_rows_to_agree() -> None:
    assert stay_dates(ARRIVALS, DEPARTURES)
    assert not stay_dates(ARRIVALS, ARRIVALS)  # the same day
    assert not stay_dates(ARRIVALS[:2], DEPARTURES[:2])  # too few rows to prove anything
    mixed = [*DEPARTURES[:3], *ARRIVALS[3:]]  # half of them end BEFORE they begin
    assert not stay_dates(ARRIVALS, mixed)


# --- plausibility: hours a person cannot have worked ------------------------------------------


def _staff(hours: list[Any], *, with_person: bool) -> list[ColumnSample]:
    columns = [column("Data", ARRIVALS, 0), column("Reparto", DEPARTMENTS, 1)]
    columns.append(column("Ore effettive", hours, 2))
    if with_person:
        names = [
            "Giulia Ferretti",
            "Marco Rossi",
            "Elena Gallo",
            "Luca Neri",
            "Sara Conti",
            "Paolo Riva",
        ]
        columns.append(column("Dipendente", names, 3))
    return columns


def test_more_hours_than_a_day_have_on_a_row_that_names_the_person_are_a_question() -> None:
    proposal = propose(LABOR, _staff([8, 48, 7, 9, 31, 8], with_person=True))

    hours = next(c for c in proposal.columns if c.header == "Ore effettive")
    assert hours.field == "actual_hours" and hours.level is Level.LOW


def test_the_same_hours_of_a_whole_department_are_not_questioned() -> None:
    proposal = propose(LABOR, _staff([48, 56, 40, 64, 48, 72], with_person=False))

    hours = next(c for c in proposal.columns if c.header == "Ore effettive")
    assert hours.field == "actual_hours" and hours.level is Level.HIGH


# --- identifiers -------------------------------------------------------------------------------


def test_a_booking_code_repeated_on_the_rows_is_not_a_sure_booking_code() -> None:
    assert fit_unique_identifier(column_stats(CODES)) > 0.9
    assert fit_unique_identifier(column_stats(["G1", "G1", "G2", "G2", "G3", "G3"])) <= 0.25


# --- personal data of staff --------------------------------------------------------------------


@pytest.mark.parametrize(
    "header", ["Badge", "Matricola", "Codice dipendente", "Employee ID", "Staff code"]
)
def test_the_number_that_identifies_an_employee_is_personal(header: str) -> None:
    finding = detect_pii(header, column_stats(["E10334", "E10335", "E10336", "E10337"]))

    assert finding is not None and finding.kind == PiiKind.EMPLOYEE_ID


@pytest.mark.parametrize("header", ["Numero ospiti", "Codice prenotazione", "Codice articolo"])
def test_a_count_or_a_booking_code_is_not_an_employee_number(header: str) -> None:
    finding = detect_pii(header, column_stats(["A1", "A2", "A3", "A4"]))

    assert finding is None or finding.kind != PiiKind.EMPLOYEE_ID


# --- dates written in other ways ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nov 4, 2026", datetime(2026, 11, 4)),
        ("November 4 2026", datetime(2026, 11, 4)),
        ("Oct. 26th, 2026", datetime(2026, 10, 26)),
        ("06-apr-26", datetime(2026, 4, 6)),
        ("6 ott 98", datetime(1998, 10, 6)),
    ],
)
def test_a_month_written_as_a_name_is_a_date_in_any_order_of_words(
    text: str, expected: datetime
) -> None:
    assert month_name_date(text) == expected


@pytest.mark.parametrize("text", ["Foo 4, 2026", "Nov 32, 2026", "4 2026", "Nov 4, 26"])
def test_what_is_not_a_date_is_not_one(text: str) -> None:
    assert month_name_date(text) is None


def test_a_two_digit_year_needs_the_same_decision_as_a_four_digit_one() -> None:
    assert detect_date_order(["04/02/26", "08/03/26", "01/03/26"]) == DateOrder.AMBIGUOUS
    assert detect_date_order(["27/02/26", "08/03/26"]) == DateOrder.DMY
    assert date_pattern(("04/02/26", "27/02/26"), "DMY") == "%d/%m/%y"
    assert date_pattern(("04/02/2026", "27/02/2026"), "DMY") == "%d/%m/%Y"
    assert date_pattern(("04/02/26", "27/02/2026"), "DMY") is None  # two ways in one column

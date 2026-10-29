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
        ("06-apr-2026", datetime(2026, 4, 6)),
    ],
)
def test_a_month_written_as_a_name_is_a_date_in_any_order_of_words(
    text: str, expected: datetime
) -> None:
    assert month_name_date(text) == expected


@pytest.mark.parametrize(
    "text", ["Foo 4, 2026", "Nov 32, 2026", "4 2026", "Nov 4, 26", "06-apr-26", "6 ott 98"]
)
def test_what_is_not_a_date_is_not_one(text: str) -> None:
    assert month_name_date(text) is None


def test_a_two_digit_year_needs_the_same_decision_as_a_four_digit_one() -> None:
    assert detect_date_order(["04/02/26", "08/03/26", "01/03/26"]) == DateOrder.AMBIGUOUS
    assert detect_date_order(["27/02/26", "08/03/26"]) == DateOrder.DMY
    assert date_pattern(("04/02/26", "27/02/26"), "DMY") == "%d/%m/%y"
    assert date_pattern(("04/02/2026", "27/02/2026"), "DMY") == "%d/%m/%Y"
    assert date_pattern(("04/02/26", "27/02/2026"), "DMY") is None  # two ways in one column


# --- fewer needless questions (Question Reduction 2) ------------------------------------------

CREDIT_NOTES = [-120.0, 340.5, -50.0, 99.0, 12.0, 78.0]


def test_a_credit_note_is_a_negative_amount_in_a_register_of_costs() -> None:
    assert field_of(COSTS, "Imponibile", CREDIT_NOTES) == ("line_total", Level.HIGH)


def test_negative_money_is_still_suspect_where_nothing_is_taken_back() -> None:
    field, level = field_of(BOOKINGS, "Ricavo camere", CREDIT_NOTES)
    assert field is None or level is not Level.HIGH


def test_the_lines_of_one_invoice_carry_its_number() -> None:
    repeated = ["FT/001", "FT/001", "FT/001", "FT/002", "FT/002", "FT/003"]

    assert field_of(COSTS, "N. documento", repeated) == ("invoice_number", Level.HIGH)


@pytest.mark.parametrize(
    "values",
    [
        ["Pagata", "Aperta", "Pagata", "Aperta", "Pagata", "Aperta"],  # words, no number
        [1, 2, 3, 4, 5, 6],  # a row counter
        ["FT/001"] * 6,  # one value: it identifies nothing
    ],
)
def test_what_is_not_a_document_number_is_still_not_one(values: list[Any]) -> None:
    field, level = field_of(COSTS, "N. documento", values)

    assert field is None or level is not Level.HIGH


def test_the_loose_words_of_a_hand_made_sheet_are_read_but_confirmed() -> None:
    # (an earlier decision: two loose names are confirmed once, not trusted)
    assert field_of(COSTS, "Da chi", SUPPLIERS) == ("supplier_name", Level.MEDIUM)
    assert field_of(COSTS, "Cosa", TEXT) == ("line_description", Level.MEDIUM)


def test_a_department_the_block_states_outright_is_the_department_of_the_rows() -> None:
    from app.modules.document_understanding.titles import department_words

    block = ["Reparto: SPA E BENESSERE", "Periodo: 19-25 ottobre 2026", "Responsabile: Direzione"]

    assert department_words(block) == ["SPA"]
    # the same words without the label are as many departments as there are words
    assert department_words(["SPA", "Direzione"]) == ["SPA", "Direzione"]
    assert department_words(["Reparto: Sala e Bar"]) == ["Sala", "Bar"]


# --- not the thing it sounds like -------------------------------------------------------------


def test_what_is_left_after_a_commission_is_not_the_commission() -> None:
    field, _level = field_of(BOOKINGS, "Netto dopo commissioni", MONEY)

    assert field != "commission_amount"
    assert field_of(BOOKINGS, "Commissione OTA", MONEY)[0] == "commission_amount"


@pytest.mark.parametrize("header", ["Cod. gruppo", "Group code", "Codice gruppo"])
def test_a_code_of_a_group_is_not_a_booking_code(header: str) -> None:
    field, _level = field_of(BOOKINGS, header, ["G1", "G2", "G3", "G4", "G5", "G6"])

    assert field != "source_record_id"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Issuer", "supplier_name"),
        ("Natura costo", "cost_category"),
        ("Pagabile entro", "due_date"),
        ("Pay By", "due_date"),
    ],
)
def test_more_words_for_the_costs_of_a_register(header: str, expected: str) -> None:
    by_field: dict[str, list[Any]] = {
        "supplier_name": SUPPLIERS,
        "cost_category": ["FOOD", "UTILITIES", "CLEANING", "FOOD", "SOFTWARE", "OTHER"],
        "due_date": ARRIVALS,
    }
    values = by_field[expected]

    assert field_of(COSTS, header, values)[0] == expected


# --- the net of an invoice, in a register ------------------------------------------------------


def _register(numbers: list[str], nets: list[float]) -> Any:
    from app.modules.data_sources.understanding_costs import plan_costs

    rows = [(number, net, "Descrizione") for number, net in zip(numbers, nets, strict=True)]
    columns = [
        ColumnSample(0, "Numero fattura", (), tuple(r[0] for r in rows), tuple(r[0] for r in rows)),
        ColumnSample(1, "Netto fattura", (), tuple(r[1] for r in rows), tuple(r[1] for r in rows)),
    ]
    proposal = propose(COSTS, columns)
    return plan_costs(proposal=proposal, rows=rows, asked_basis=None, asked_columns={})


def test_the_net_of_the_invoice_is_the_net_of_the_line_when_every_row_is_an_invoice() -> None:
    plan = _register(INVOICES, MONEY)

    assert plan.assigned == {"Netto fattura": "line_total"}


def test_the_lines_of_an_invoice_with_a_net_each_are_lines() -> None:
    plan = _register(["FT/1", "FT/1", "FT/2", "FT/2", "FT/3", "FT/3"], MONEY)

    assert plan.assigned == {"Netto fattura": "line_total"}


def test_the_same_net_on_every_line_of_an_invoice_is_the_net_of_the_invoice() -> None:
    plan = _register(["FT/1", "FT/1", "FT/2", "FT/2", "FT/3", "FT/3"], [100.0, 100.0] * 3)

    assert not plan.assigned


# --- explainability: why a column is read as it is (internal, never a value) -------------------


def test_every_reading_says_what_it_rests_on_without_showing_a_value() -> None:
    proposal = propose(
        BOOKINGS,
        [
            column("CI", ARRIVALS, 0),
            column("CO", DEPARTURES, 1),
            column("Pratica n.", CODES, 2),
            column("Stanze", SMALL, 3),
        ],
    )

    by_header = {c.header: c.evidence for c in proposal.columns}
    assert any("confirmed by the values" in why for why in by_header["CI"])
    assert any("confirmed by the values" in why for why in by_header["CO"])
    assert any("values fit" in why for why in by_header["Pratica n."])
    assert any("name TOKEN" in why for why in by_header["Stanze"])
    everything = " ".join(why for evidence in by_header.values() for why in evidence)
    assert not any(str(code) in everything for code in CODES)  # no value of the file in it


def test_a_reading_demoted_by_plausibility_says_so() -> None:
    proposal = propose(LABOR, _staff([8, 48, 7, 9, 31, 8], with_person=True))

    hours = next(c for c in proposal.columns if c.header == "Ore effettive")
    assert any("per person" in why for why in hours.evidence)

"""Smart Import V3: what a column MEANS - words, values, certainty - with no file, no API, no DB.

Headers are read as WORDS ("Reparto o mansione" says "department" however it is punctuated), the
guess is checked against the column's VALUES, and how sure NINFA is follows from both: a name alone
or a handful of values alone never makes a column "recognised". Personal data is classified before
anything else, by the header AND by what the values look like.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

import pytest

from app.modules.bookings.parsers import Cell
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.domain_detection import DomainScore, score_domain, verdict
from app.modules.data_sources.proposal import Proposal, propose
from app.modules.data_sources.semantics import DomainSem, Level
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_labor import LABOR, hourly_or_known_exclusion
from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.stats import MIN_EVIDENCE, column_stats
from app.modules.document_understanding.text import tokens
from app.modules.ingestion.models import DataSourceDomain


def _sample(position: int, header: str, values: Sequence[Cell]) -> ColumnSample:
    cells = tuple(v for v in values if v is not None)
    return ColumnSample(position, header, tuple(str(v) for v in cells[:5]), cells)


DAYS = [datetime(2026, 10, 26 + i) for i in range(6)]
DEPARTMENTS = ["Reception", "Housekeeping", "Cucina", "Reception", "Sala e bar", "Manutenzione"]
HOURS = [8, 6, 8, 8, 6, 8]
MONEY = [120.0, 130.5, 99.0, 150.0, 110.0, 140.0]
PEOPLE = ["Marta Conti", "Luca Ferri", "Anna Bianchi", "Rosa Greco", "Elena Riva", "Paolo Neri"]


def _one(
    sem: DomainSem,
    header: str,
    values: Sequence[Cell],
    *,
    excluded: Callable[[str], str | None] | None = None,
) -> Proposal:
    if excluded is None:
        return propose(sem, [_sample(0, header, values)])
    return propose(sem, [_sample(0, header, values)], excluded_reason=excluded)


# --- headers are read as words --------------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "Reparto o mansione",
        "Reparto/Mansione",
        "Reparto - Mansione",
        "REPARTO O MANSIONE",
        "Area / reparto",
        "Area reparto",
        "Reparto",
        "Mansione",
        "Dipartimento",
        "Department",
        "Team",
        "Ruolo",
    ],
)
def test_every_way_of_writing_the_department_is_the_department(header: str) -> None:
    proposal = _one(LABOR, header, DEPARTMENTS)

    assert proposal.field_of(header) == "role"
    assert proposal.columns[0].level == Level.HIGH


def test_the_word_reparto_is_in_every_spelling_of_the_label_the_page_itself_uses() -> None:
    assert "repart" in tokens("Reparto o mansione")
    assert "repart" in tokens("Reparto/Mansione")
    assert "repart" in tokens("Area / reparto")


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Tot. ore previste", "planned_hours"),
        ("Ore programmate", "planned_hours"),
        ("Planned hours", "planned_hours"),
        ("Ore effettive", "actual_hours"),
        ("Ore lavorate", "actual_hours"),
        ("Hours worked", "actual_hours"),
        ("Costo programmato", "planned_cost"),
        ("Costo previsto", "planned_cost"),
        ("Costo effettivo", "actual_cost"),
        ("Actual cost", "actual_cost"),
    ],
)
def test_hours_and_costs_say_planned_or_actual_in_many_words(header: str, field: str) -> None:
    values: Sequence[Cell] = (
        HOURS if "ore" in header.lower() or "hours" in header.lower() else MONEY
    )

    proposal = _one(LABOR, header, values)

    assert proposal.field_of(header) == field


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Check-in date", "check_in"),
        ("Check in", "check_in"),
        ("Arrival", "check_in"),
        ("Check-out date", "check_out"),
        ("Departure", "check_out"),
        ("Provenienza prenotazione", "channel"),
        ("Canale vendita", "channel"),
        ("Source", "channel"),
        ("Portale", "channel"),
    ],
)
def test_bookings_words_in_italian_and_english(header: str, field: str) -> None:
    values: Sequence[Cell] = (
        ["Booking.com", "Expedia", "Diretto", "Airbnb", "Booking.com", "Expedia"]
        if field == "channel"
        else [datetime(2026, 11, 2 + i) for i in range(6)]
    )

    proposal = _one(BOOKINGS, header, values)

    assert proposal.field_of(header) == field


def test_a_column_called_ore_over_numbers_is_hours_but_does_not_say_which() -> None:
    proposal = _one(LABOR, "Ore", HOURS)

    column = proposal.columns[0]
    assert column.field is None
    assert column.ambiguous_group == "HOURS"
    assert set(column.ambiguous_fields) == {"planned_hours", "actual_hours"}


# --- the name is checked against the values -------------------------------------------------------


def test_a_header_that_says_data_over_a_column_of_names_is_not_a_date() -> None:
    proposal = _one(LABOR, "Data", PEOPLE)

    assert proposal.field_of("Data") != "work_date"


def test_a_few_values_never_make_a_column_recognised() -> None:
    proposal = _one(LABOR, "Reparto o mansione", DEPARTMENTS[: MIN_EVIDENCE - 1])

    assert proposal.columns[0].level != Level.HIGH


def test_values_alone_never_give_a_column_a_name_with_certainty() -> None:
    proposal = _one(BOOKINGS, "Colonna 7", [d for d in DAYS])

    column = proposal.columns[0]
    assert column.level != Level.HIGH


# --- personal data is classified first, before any guess about meaning ----------------------------


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        ("Nome e cognome", PiiKind.PERSON_NAME),
        ("Dipendente", PiiKind.PERSON_NAME),
        ("Nominativo", PiiKind.PERSON_NAME),
        ("Guest name", PiiKind.PERSON_NAME),
        ("Cliente", PiiKind.PERSON_NAME),
        ("Email", PiiKind.EMAIL),
        ("PEC", PiiKind.EMAIL),
        ("Telefono", PiiKind.PHONE),
        ("Cellulare", PiiKind.PHONE),
        ("Codice fiscale", PiiKind.TAX_CODE),
        ("IBAN", PiiKind.IBAN),
    ],
)
def test_the_header_alone_classifies_personal_data(header: str, kind: PiiKind) -> None:
    finding = detect_pii(header, column_stats(PEOPLE))

    assert finding is not None and finding.kind == kind and finding.by == "HEADER"


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        (["m.rossi@example.com", "a.verdi@example.org", "l.neri@example.it"], PiiKind.EMAIL),
        (["+39 333 1234567", "333 7654321", "+39 06 12345678"], PiiKind.PHONE),
        (["RSSMRA80A01H501U", "VRDLGU75B02F205Z", "NRILCU90C03L219K"], PiiKind.TAX_CODE),
        (
            [
                "IT60X0542811101000000123456",
                "DE89370400440532013000",
                "FR7630006000011234567890189",
            ],
            PiiKind.IBAN,
        ),
    ],
)
def test_the_values_alone_classify_personal_data_under_any_header(
    values: list[str], kind: PiiKind
) -> None:
    finding = detect_pii("Colonna 3", column_stats(values))

    assert finding is not None and finding.kind == kind and finding.by == "VALUES"


def test_a_column_of_full_names_is_a_guess_from_the_shape_and_still_left_out() -> None:
    finding = detect_pii("Colonna 2", column_stats(PEOPLE))

    assert finding is not None and finding.kind == PiiKind.PERSON_NAME and finding.strong is False


@pytest.mark.parametrize(
    "values",
    [
        DEPARTMENTS,
        ["Booking.com", "Expedia", "Diretto", "Airbnb", "Booking.com", "Expedia"],
        ["Housekeeping", "Cucina", "Sala e bar", "Reception", "Manutenzione", "Direzione"],
        ["Doppia Superior", "Suite Deluxe", "Camera Singola", "Doppia Standard", "Tripla", "Suite"],
    ],
)
def test_departments_channels_and_room_types_are_not_names_of_people(values: list[str]) -> None:
    assert detect_pii("Colonna 4", column_stats(values)) is None


def test_a_count_of_guests_is_not_a_guest() -> None:
    assert detect_pii("Ospiti", column_stats([2, 3, 2, 4, 2, 3])) is None
    assert detect_pii("Ospite", column_stats(PEOPLE)) is not None


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        ("Costo orario", "HOURLY_RATE"),
        ("Tariffa oraria", "HOURLY_RATE"),
        ("Paga oraria", "HOURLY_RATE"),
        ("Hourly rate", "HOURLY_RATE"),
        ("Costo orario previsto", "HOURLY_RATE"),
        ("Nome e cognome", "PERSON"),
        ("Email", "CONTACT"),
        ("Codice fiscale", "PERSON"),
    ],
)
def test_staff_columns_that_must_never_be_read_are_locked_with_their_reason(
    header: str, reason: str
) -> None:
    values: Sequence[Cell] = (
        MONEY if "orari" in header.lower() or "rate" in header.lower() else PEOPLE
    )

    proposal = _one(LABOR, header, values, excluded=hourly_or_known_exclusion)

    column = proposal.columns[0]
    assert column.field is None and column.locked == reason


def test_a_locked_column_is_never_offered_as_a_field_even_when_its_name_looks_like_one() -> None:
    proposal = _one(LABOR, "Costo orario previsto", MONEY, excluded=hourly_or_known_exclusion)

    assert proposal.columns[0].locked == "HOURLY_RATE"
    assert proposal.field_of("Costo orario previsto") is None


# --- which kind of data a whole file is -----------------------------------------------------------


def _scores(columns: list[ColumnSample], context: list[str]) -> dict[DataSourceDomain, DomainScore]:
    scores: dict[DataSourceDomain, DomainScore] = {}
    for sem, groups in (
        (BOOKINGS, [("source_record_id",), ("check_in",), ("check_out",), ("channel",)]),
        (LABOR, [("work_date",), ("role", "labor_category"), ("planned_hours", "actual_hours")]),
    ):
        proposal = propose(sem, columns)
        scores[sem.domain] = score_domain(sem, groups, proposal, context)
    return scores


def test_a_staff_file_is_detected_as_staff_and_a_bookings_file_as_bookings() -> None:
    staff = [
        _sample(0, "Data", DAYS),
        _sample(1, "Reparto o mansione", DEPARTMENTS),
        _sample(2, "Ore previste", HOURS),
        _sample(3, "Costo previsto", MONEY),
    ]
    bookings = [
        _sample(0, "Codice prenotazione", [f"R{i}" for i in range(6)]),
        _sample(1, "Arrivo", [datetime(2026, 11, 2 + i) for i in range(6)]),
        _sample(2, "Partenza", [datetime(2026, 11, 4 + i) for i in range(6)]),
        _sample(
            3, "Canale", ["Booking.com", "Expedia", "Diretto", "Airbnb", "Booking.com", "Expedia"]
        ),
    ]

    staff_verdict = verdict(_scores(staff, ["Turni"]))
    bookings_verdict = verdict(_scores(bookings, ["Prenotazioni"]))

    assert (staff_verdict.domain, staff_verdict.level) == (DataSourceDomain.LABOR, Level.HIGH)
    assert (bookings_verdict.domain, bookings_verdict.level) == (
        DataSourceDomain.BOOKINGS,
        Level.HIGH,
    )


def test_a_file_that_is_neither_has_no_kind_of_data() -> None:
    unknown = [_sample(0, "Colore", ["rosso"] * 6), _sample(1, "Forma", ["tondo"] * 6)]

    result = verdict(_scores(unknown, ["Foglio1"]))

    assert result.domain is None and result.level == Level.LOW

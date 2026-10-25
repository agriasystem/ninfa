"""Smart Import V3 - question reduction 1: ask only what the answer can change.

    SAFE + PROVEN        -> silent
    AMBIGUOUS + CRITICAL -> ask
    UNSUPPORTED          -> manual / blocked

Every rule here removes a question NINFA had the evidence to skip, and every rule has its neighbour
that must still be asked: a header over values that do not confirm it, a country where a channel
should be, a word that could be two departments, an amount that does not say what it includes.
No database, no model, no network.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pytest

from app.modules.bookings.parsers import Cell
from app.modules.data_sources.channel_words import (
    channel_share,
    fit_channel,
    is_channel_word,
    is_place,
)
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.proposal import propose
from app.modules.data_sources.semantics import Level
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.data_sources.understanding_bookings import channel_by_taught
from app.modules.data_sources.understanding_costs import category_of as cost_category_of
from app.modules.data_sources.understanding_labor import (
    category_of,
    classifies,
    lexicon_roles,
    names_a_department,
)
from app.modules.document_understanding.stats import column_stats
from app.modules.document_understanding.text import fold, tokens
from tests.hardening_support import (
    BOOKING_HEADER,
    COSTS,
    LABOR,
    PEOPLE,
    booking_row,
    bookings,
    by_header,
    costs,
    field_of,
    level_of,
    question_kinds,
    service,
    staff,
    understand,
    xlsx,
)
from tests.hardening_support import (
    BOOKINGS as BOOKINGS_DOMAIN,
)

CHANNEL_WORDS = ["Booking.com", "Expedia", "Diretto", "Telefono", "Email", "Sito web", "Walk-in"]


def _bookings(
    channel_header: str = "Canale", channels: Sequence[str] = CHANNEL_WORDS, count: int = 24
) -> list[list[Any]]:
    rows = bookings(count)
    rows[0][4] = channel_header
    for index, row in enumerate(rows[1:]):
        row[4] = channels[index % len(channels)]
    return rows


def _state(answer: FileInspection) -> tuple[str, list[str]]:
    return level_of(answer), question_kinds(answer)


# --- channel: the header AND the values --------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["Canale", "Channel", "Canale di vendita", "Provenienza", "Source", "Origine", "Portale"],
)
def test_a_channel_header_over_channel_values_is_certain_and_asks_nothing(header: str) -> None:
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings(header)))

    assert field_of(answer, header) == "channel"
    assert by_header(answer)[header].level is not None
    assert _state(answer) == ("READY", [])


@pytest.mark.parametrize(
    "values",
    [
        ["Booking.com", "Airbnb", "Website"],
        ["Expedia", "Agenzia", "Telefono", "Diretto"],
        ["BOOKING.COM", "expedia.it", "Walk in", "e-mail"],
        ["Hotels.com", "Agoda", "Sito ufficiale"],
    ],
)
def test_the_words_hotels_use_for_how_a_booking_arrived_are_channels(values: list[str]) -> None:
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings("Canale", values)))

    assert _state(answer) == ("READY", [])


def test_a_provenance_column_of_countries_is_not_a_channel() -> None:
    countries = ["Italia", "Germania", "Francia", "Spagna", "Regno Unito"]
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings("Provenienza", countries)))

    assert field_of(answer, "Provenienza") is None  # where the guest comes from, not a channel
    assert level_of(answer) in {"MANUAL", "BLOCKED"}  # and the file has no channel at all


def test_a_channel_header_over_words_nobody_knows_is_still_asked() -> None:
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings("Canale", ["Alfa", "Beta", "Gamma"])))

    assert field_of(answer, "Canale") == "channel"
    assert _state(answer) == ("ASK", ["COLUMN_MEANING"])  # a maybe is not a certainty


def test_the_values_alone_never_make_a_channel_without_a_header_that_says_so() -> None:
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings("Colonna K")))

    assert field_of(answer, "Colonna K") is None
    assert level_of(answer) != "READY"  # (the file has no channel as far as NINFA can tell)


def test_a_word_is_a_channel_only_as_a_whole_word() -> None:
    assert is_channel_word("Booking.com") and is_channel_word("Sito web") and is_channel_word("OTA")
    assert not is_channel_word("Hotel Rossi")  # "ota" is inside "hotel"
    assert not is_channel_word("Directory")  # "direct" is inside "directory"
    assert is_place("Germania") and not is_place("Booking.com")


def test_codes_of_a_channel_manager_are_channels_under_a_channel_header() -> None:
    answer = understand(BOOKINGS_DOMAIN, xlsx(_bookings("Can.", ["BDC", "EXP", "ABB", "DIR"])))

    assert field_of(answer, "Can.") == "channel"
    assert _state(answer) == ("READY", [])


def test_fit_channel_tells_channels_from_places_from_anything_else() -> None:
    def fit(values: Sequence[Cell]) -> float:
        return fit_channel(column_stats(list(values)))

    assert fit(["Booking.com", "Expedia", "Diretto", "Booking.com"]) == 1.0
    assert fit(["Italia", "Germania", "Francia", "Italia"]) < 0.2
    assert 0.2 < fit(["Alfa", "Beta", "Gamma", "Alfa"]) < 0.85


# --- channel: what the hotel has already taught -------------------------------------------------


def _proposal(header: str, values: Sequence[Cell]) -> Any:
    cells = tuple(values)
    dates = tuple(datetime(2026, 10, 1 + i % 20) for i in range(len(cells)))
    samples = [
        ColumnSample(0, "Codice prenotazione", (), tuple(f"BK-{i}" for i in range(len(cells)))),
        ColumnSample(1, "Data prenotazione", (), dates),
        ColumnSample(2, "Arrivo", (), dates),
        ColumnSample(3, "Partenza", (), dates),
        ColumnSample(4, header, tuple(str(v) for v in cells[:3]), cells),
    ]
    return propose(BOOKINGS, samples)


def test_a_channel_the_hotel_taught_is_one_more_word_for_the_column() -> None:
    values = ["Hotelbeds", "Sunrise Travel", "Alpitour"] * 4
    proposal = _proposal("Canale", values)
    assert proposal.assigned()["channel"].level == Level.MEDIUM  # NINFA knows none of these

    taught = frozenset({"hotelbeds", "sunrise travel", "alpitour"})
    learned = channel_by_taught(proposal, taught)

    assert learned.assigned()["channel"].level == Level.HIGH
    assert channel_by_taught(proposal, frozenset()).assigned()["channel"].level == Level.MEDIUM
    assert channel_share(values[:3], taught) == 1.0


def test_what_was_taught_does_not_make_a_column_a_channel_by_itself() -> None:
    values = ["Hotelbeds", "Sunrise Travel", "Alpitour"] * 4
    proposal = _proposal("Note", values)

    assert "channel" not in proposal.assigned()
    assert channel_by_taught(proposal, frozenset({"hotelbeds"})) is proposal


# --- which kind of data: the card is a weak prior ----------------------------------------------


def test_a_file_that_points_nowhere_is_not_asked_what_it_is_and_is_not_ready() -> None:
    rows: list[list[Any]] = [["Piatto", "Categoria", "Prezzo"]] + [
        [f"Piatto {i}", ["Primi", "Secondi", "Dessert"][i % 3], 8 + i] for i in range(10)
    ]

    answer = understand(LABOR, xlsx(rows))

    assert "DOMAIN" not in question_kinds(answer)
    assert level_of(answer) == "MANUAL"


def test_a_file_that_is_clearly_another_kind_of_data_is_asked_about_that_alone() -> None:
    answer = understand(LABOR, xlsx(bookings(24)))

    assert question_kinds(answer) == ["DOMAIN"]  # no department rows, no column checks: later
    question = answer.understanding.questions[0]  # type: ignore[union-attr]
    assert question.candidate == "BOOKINGS"


def test_a_domain_the_person_has_confirmed_is_not_asked_again() -> None:
    inspection = service().understand(
        LABOR,
        "file.xlsx",
        xlsx(bookings(24)),
        UnderstandAnswers(),
        True,
        None,
        False,
        currency="EUR",
    )

    assert "DOMAIN" not in question_kinds(inspection)


# --- cost categories ---------------------------------------------------------------------------

CATEGORIES = ["Energia", "Lavanderia", "Colazioni", "Manutenzione", "Pulizie", "Software"]


def _register(categories: Sequence[str], count: int = 12) -> list[list[Any]]:
    rows = costs(
        ["Categoria", "Imponibile"],
        [[categories[i % len(categories)], 100.0 + i] for i in range(count)],
    )
    return rows


def test_known_cost_categories_are_not_asked_about() -> None:
    answer = understand(COSTS, xlsx(_register(CATEGORIES)))

    assert field_of(answer, "Categoria") == "cost_category"
    assert _state(answer) == ("READY", [])
    assert answer.proposal is not None
    assert answer.proposal.labels["category_mapping"]["Colazioni"] == "FOOD"


@pytest.mark.parametrize(
    ("word", "category"),
    [
        ("Colazioni", "FOOD"),
        ("Ristorazione", "FOOD"),
        ("Housekeeping", "CLEANING"),
        ("Energia elettrica", "UTILITIES"),
        ("Commissioni Booking", "OTA_COMMISSIONS"),
        ("Lavanderia", "LAUNDRY"),
        ("Altro", "OTHER"),
    ],
)
def test_the_words_of_a_cost_register_have_one_category_each(word: str, category: str) -> None:
    found = cost_category_of(word, {})

    assert found is not None and found.value == category


@pytest.mark.parametrize("word", ["Food & Beverage", "Forniture", "Pool Service"])
def test_a_word_that_could_be_two_categories_is_not_decided(word: str) -> None:
    assert cost_category_of(word, {}) is None


def test_with_some_known_and_some_unknown_categories_only_the_unknown_one_is_asked() -> None:
    answer = understand(
        COSTS, xlsx(_register(["Energia", "Lavanderia", "Colazioni", "Pool Service"]))
    )

    assert _state(answer) == ("ASK", ["VALUE_LABELS"])
    question = answer.understanding.questions[0]  # type: ignore[union-attr]
    assert [label.label for label in question.labels] == ["Pool Service"]


def test_a_category_the_hotel_taught_is_not_asked_again() -> None:
    answer = understand(
        COSTS,
        xlsx(_register(["Energia", "Pool Service"])),
        labels={"category_mapping": {"Pool Service": "OTHER"}},
    )

    assert _state(answer) == ("READY", [])


# --- departments --------------------------------------------------------------------------------


def _roster(department_words: Sequence[str]) -> list[list[Any]]:
    rows = staff(["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"], days=2)
    for index, row in enumerate(rows[1:]):
        row[2] = department_words[index % len(department_words)]
    return rows


@pytest.mark.parametrize(
    "words",
    [
        ["Ristorante", "Ricevimento", "Cucina"],
        ["Governante", "Portineria", "Bar"],
        ["Barista", "Manutentore", "Direzione"],
        ["Reception", "Housekeeping", "Sala", "SPA", "Wellness", "Amministrazione", "Booking"],
    ],
)
def test_the_departments_of_a_hotel_are_known_words(words: list[str]) -> None:
    answer = understand(LABOR, xlsx(_roster(words)))

    assert _state(answer) == ("READY", [])


def test_the_departments_read_by_ninfa_travel_with_the_decision_so_the_import_files_them() -> None:
    answer = understand(LABOR, xlsx(_roster(["Ristorante", "Ricevimento", "Cucina"])))

    assert answer.proposal is not None
    roles = answer.proposal.labels["role_mapping"]
    assert roles == {
        "Ristorante": "FOOD_BEVERAGE",
        "Ricevimento": "FRONT_OFFICE",
    }  # (Cucina: its rules)


@pytest.mark.parametrize(
    ("word", "category"),
    [
        ("Ricevimento", "FRONT_OFFICE"),
        ("Receptionist", "FRONT_OFFICE"),  # the job reads as its department...
        ("Chef", "KITCHEN"),
        ("Governante", "HOUSEKEEPING"),
        ("Amministrazione", "MANAGEMENT"),
        ("Centro benessere", "SPA_WELLNESS"),
    ],
)
def test_a_job_and_its_department_read_as_the_same_category(word: str, category: str) -> None:
    assert category_of(word, {}, lexicon=True) == category


@pytest.mark.parametrize("word", ["HK", "FO", "Turno A", "MAN", "Cameriere ai piani"])
def test_a_code_or_a_word_that_could_be_two_departments_is_still_asked(word: str) -> None:
    assert not classifies(word, {}, lexicon=True)


def test_a_department_code_the_hotel_taught_is_not_asked_again() -> None:
    answer = understand(
        LABOR,
        xlsx(_roster(["HK", "Reception", "Cucina"])),
        labels={"role_mapping": {"HK": "HOUSEKEEPING"}},
    )

    assert _state(answer) == ("READY", [])
    asked = understand(LABOR, xlsx(_roster(["HK", "Reception", "Cucina"])))
    assert _state(asked) == ("ASK", ["VALUE_LABELS"])
    assert [label.label for label in asked.understanding.questions[0].labels] == ["HK"]  # type: ignore[union-attr]


def test_the_name_of_a_sheet_is_a_department_only_by_the_rules_of_the_import() -> None:
    # "Booking" and "Amministrazione" also name the sheets of reservation and cost files
    assert names_a_department("Reception") and names_a_department("Cucina")
    assert not names_a_department("Booking") and not names_a_department("Amministrazione")
    assert lexicon_roles([("Booking", 3), ("Cucina", 2)], {}) == {"Booking": "FRONT_OFFICE"}


# --- a loose reservation code, in a file that is plainly a list of reservations ------------------


@pytest.mark.parametrize("header", ["Codice", "Cod.", "Book Number", "Code"])
def test_a_loose_name_for_the_reservation_code_over_unique_values_is_the_code(header: str) -> None:
    rows = bookings(24)
    rows[0][0] = header

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert field_of(answer, header) == "source_record_id"
    assert _state(answer) == ("READY", [])


def test_a_loose_code_is_still_asked_when_the_values_repeat() -> None:
    rows = bookings(24)
    rows[0][0] = "Codice"
    for row in rows[1:]:
        row[0] = "A"

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert level_of(answer) != "READY"


def test_a_loose_code_is_still_asked_without_the_dates_of_a_stay() -> None:
    rows = [["Codice", "Canale"], *[[f"BK-{i}", "Diretto"] for i in range(10)]]

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert level_of(answer) != "READY"


# --- the basis of an amount ----------------------------------------------------------------------


def test_a_header_that_says_the_amount_includes_vat_is_not_asked_about() -> None:
    answer = understand(
        COSTS, xlsx(costs(["Totale IVA inclusa"], [[121.0 + i] for i in range(10)]))
    )

    assert "AMOUNT_BASIS" not in question_kinds(answer)
    assert level_of(answer) == "BLOCKED"  # the net amount of a line is not NINFA's to work out
    assert answer.understanding.blockers[0].code.value == "AMOUNT_NOT_NET"  # type: ignore[union-attr]


def test_a_bare_amount_is_still_asked_net_or_gross() -> None:
    answer = understand(COSTS, xlsx(costs(["Importo"], [[100.0 + i] for i in range(10)])))

    assert question_kinds(answer) == ["AMOUNT_BASIS"]


def test_the_basis_of_an_amount_is_not_asked_while_the_file_cannot_be_imported_anyway() -> None:
    # no supplier, no document number: whatever the answer, the file is not a register
    rows: list[list[Any]] = [["Utenza", "Periodo", "Importo"]] + [
        [f"Luce {i}", "ottobre", 100.0 + i] for i in range(8)
    ]

    answer = understand(COSTS, xlsx(rows))

    assert "AMOUNT_BASIS" not in question_kinds(answer)
    assert level_of(answer) == "MANUAL"


# --- what must still be asked --------------------------------------------------------------------


def test_a_lone_total_is_still_one_confirmation() -> None:
    header = [
        "Res.ID",
        "Booking date",
        "Check-in",
        "Check-out",
        "Channel",
        "Status",
        "Rooms",
        "Total",
    ]
    rows: list[list[Any]] = [header]
    for index in range(14):
        base = booking_row(index)
        rows.append(
            [base[0], base[1], base[2], base[3], "Booking.com", "Confirmed", 1, 100.0 + index]
        )

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert _state(answer) == ("ASK", ["COLUMN_MEANING"])
    assert answer.understanding.questions[0].column == "Total"  # type: ignore[union-attr]


def test_an_amount_that_does_not_say_which_is_still_asked() -> None:
    rows = bookings(24)
    rows[0][5] = "Importo"

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert "COLUMN_MEANING" in question_kinds(answer)
    assert level_of(answer) != "READY"


def test_a_stay_that_ends_before_it_begins_is_still_asked_about() -> None:
    rows: list[list[Any]] = [list(BOOKING_HEADER)]
    for index in range(14):
        base = booking_row(index)
        rows.append([base[0], base[1], base[3], base[2], *base[4:]])

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert "DATES_REVERSED" in question_kinds(answer)
    assert level_of(answer) == "ASK"


def test_two_columns_that_say_the_same_thing_are_still_a_choice() -> None:
    header = ["Data", "Dipendente", "Reparto", "Ore previste", "Ore previste (rev.)"]
    answer = understand(LABOR, xlsx(staff(header, planned=8, worked=7.5)))

    assert level_of(answer) == "ASK"
    assert "COLUMN_MEANING" in question_kinds(answer)


def test_a_room_amount_and_a_stay_total_are_two_columns_not_a_contest() -> None:
    # "Importo camere" is only the room revenue; "Totale soggiorno" is, by its own words, the total
    rows = bookings(24)
    rows[0][5] = "Importo camere"
    rows[0].insert(6, "Totale soggiorno")
    for index, row in enumerate(rows[1:]):
        row.insert(6, row[5] + 30 + index)

    answer = understand(BOOKINGS_DOMAIN, xlsx(rows))

    assert field_of(answer, "Importo camere") == "room_revenue"
    assert field_of(answer, "Totale soggiorno") == "total_revenue"
    assert _state(answer) == ("READY", [])


def test_questions_about_meaning_wait_while_the_file_lacks_what_it_cannot_do_without() -> None:
    # a roster with an unknown department word but no date at all: the word is not worth asking yet
    rows = [["Dipendente", "Reparto", "Ore previste", "Ore effettive"]] + [
        [PEOPLE[i % 6], "Turno A", 8, 7] for i in range(8)
    ]

    answer = understand(LABOR, xlsx(rows))

    assert "VALUE_LABELS" not in question_kinds(answer)
    assert level_of(answer) in {"MANUAL", "BLOCKED"}


# --- small things ---------------------------------------------------------------------------------


def test_a_character_that_prints_nothing_is_not_part_of_a_header() -> None:
    assert fold("Re​parto") == "reparto"
    assert tokens("Re​parto") == tokens("Reparto")


def test_hours_and_dates_in_everyday_abbreviations_are_read() -> None:
    header = ["gg", "Dipendente", "Reparto", "H previste", "Ore Lav."]
    rows = staff(header, planned=8, worked=7.5)

    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "gg") == "work_date"
    assert field_of(answer, "H previste") == "planned_hours"
    assert field_of(answer, "Ore Lav.") == "actual_hours"
    assert _state(answer) == ("READY", [])


def test_an_operating_centre_of_departments_is_the_department() -> None:
    header = ["Data", "Dipendente", "Centro operativo", "Ore previste", "Ore effettive"]

    answer = understand(LABOR, xlsx(staff(header)))

    assert field_of(answer, "Centro operativo") == "role"
    assert _state(answer) == ("READY", [])


def test_a_cost_centre_is_not_an_operating_centre() -> None:
    header = ["Data", "Dipendente", "Centro di costo", "Ore previste", "Ore effettive"]

    answer = understand(LABOR, xlsx(staff(header)))

    assert field_of(answer, "Centro di costo") != "role"


def test_a_word_too_long_to_travel_in_the_decision_is_not_read_by_the_list() -> None:
    long_label = "Responsabile ricevimento " + "turno " * 25

    assert len(long_label) > 120
    assert not classifies(long_label, {}, lexicon=True)  # the import would not know it
    assert lexicon_roles([(long_label, 1)], {}) == {}

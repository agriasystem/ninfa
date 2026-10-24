"""Smart Import, the parts that need no database: what a column probably means, and what the values
of a column prove about how dates and numbers are written.

Everything is deterministic: no AI, no network, no learning. A suggestion is a proposal only.
"""

from datetime import date, datetime

import pytest

from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.normalization import DateOrder
from app.modules.bookings.suggestions import suggest_mapping
from app.modules.data_sources.column_profile import (
    NumberStyle,
    date_order_of,
    date_pattern,
    display_cell,
    looks_like_dates,
    number_style,
    sample_columns,
)
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.ingestion.suggestions import SuggestionConfidence
from app.modules.labor.mapping import LaborField
from app.modules.labor.suggestions import excluded_reason, suggest_labor_mapping
from tests.smart_import_support import bookings_it_file, csv_bytes, labor_it_file, xlsx_bytes


def labor_suggestions(*headers: str) -> dict[str, tuple[str, SuggestionConfidence]]:
    """column -> (field, confidence) for the columns that got a suggestion."""
    return {
        s.column: (s.field.value, s.confidence)
        for s in suggest_labor_mapping(list(headers))
        if s.column is not None
    }


# --- what a column probably means -----------------------------------------------------------------


def test_the_booking_suggestions_are_the_ones_the_import_always_had() -> None:
    """The ranking moved to a shared module: the booking behaviour must be exactly the same."""
    headers = ["Data arrivo", "Data partenza", "Canale", "Importo camera", "Stato", "Note"]
    by_field = {s.canonical_field: s for s in suggest_mapping(headers)}

    assert by_field[CanonicalField.CHECK_IN].suggested_source_column == "Data arrivo"
    assert by_field[CanonicalField.CHECK_IN].confidence == SuggestionConfidence.HIGH
    assert by_field[CanonicalField.CHANNEL].suggested_source_column == "Canale"
    assert by_field[CanonicalField.ROOM_REVENUE].suggested_source_column == "Importo camera"
    assert by_field[CanonicalField.ROOMS].suggested_source_column is None


def test_a_file_already_in_ninfas_own_column_names_is_recognised_exactly() -> None:
    suggestions = labor_suggestions("work_date", "planned_hours", "labor_category", "currency")

    assert suggestions == {
        "work_date": ("work_date", SuggestionConfidence.HIGH),
        "planned_hours": ("planned_hours", SuggestionConfidence.HIGH),
        "labor_category": ("labor_category", SuggestionConfidence.HIGH),
        "currency": ("currency", SuggestionConfidence.HIGH),
    }


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Giorno", "work_date"),
        ("Data turno", "work_date"),
        ("DATE", "work_date"),
        ("Ore turno", "planned_hours"),
        ("Ore previste", "planned_hours"),
        ("Ore lavorate", "actual_hours"),
        ("Reparto", "role"),
        ("Mansione", "role"),
        ("Costo previsto", "planned_cost"),
        ("Valuta", "currency"),
    ],
)
def test_italian_and_english_names_of_a_labor_column_are_known(header: str, field: str) -> None:
    assert labor_suggestions(header)[header][0] == field


def test_a_department_is_a_role_that_ninfa_reads_not_a_standard_category() -> None:
    """A hotel writes "Reception" or "Cucina", not HOUSEKEEPING: it is read as a role and
    classified by NINFA's own rules, so the suggestion must not claim it is the category."""
    suggestions = labor_suggestions("Reparto")

    assert suggestions["Reparto"][0] == LaborField.ROLE.value


def test_planned_and_actual_are_never_guessed_from_a_bare_hours_or_cost_column() -> None:
    """The staffing analysis reads PLANNED minutes: a bare "Ore" or "Costo" could silently be
    either, so nothing is suggested and the person says which."""
    assert labor_suggestions("Ore", "Hours", "Costo", "Cost", "Totale") == {}


def test_an_hourly_rate_and_a_persons_name_are_never_suggested_as_anything() -> None:
    suggestions = labor_suggestions("Costo orario", "Costo h", "Nome dipendente", "Dipendente")

    assert suggestions == {}
    assert excluded_reason("Costo orario") == "HOURLY_RATE"
    assert excluded_reason("COSTO H") == "HOURLY_RATE"
    assert excluded_reason("Nome dipendente") == "PERSON"
    assert excluded_reason("Reparto") is None


def test_unknown_headers_get_no_suggestion_and_the_person_chooses() -> None:
    assert labor_suggestions("Colonna A", "xyz", "Note", "???") == {}


def test_a_header_is_used_for_one_field_only() -> None:
    suggestions = suggest_labor_mapping(["Data", "Giorno"])
    used = [s.column for s in suggestions if s.column is not None]

    assert len(used) == len(set(used)) == 1  # one date column wins, the other is left alone


def test_the_suggestions_are_deterministic() -> None:
    headers = ["Giorno", "Ore turno", "Reparto", "Costo previsto", "Valuta", "Note"]

    assert suggest_labor_mapping(headers) == suggest_labor_mapping(list(headers))


def test_a_similar_name_is_a_less_certain_suggestion() -> None:
    suggestions = labor_suggestions("Ore lavorat")  # a typo of a known name

    assert suggestions["Ore lavorat"] == ("actual_hours", SuggestionConfidence.MEDIUM)


# --- the page's reading of a file ---------------------------------------------------------------


def test_a_column_of_dates_with_a_meaningless_name_is_offered_as_the_date_to_check() -> None:
    """The one value-based hint: the only date field of a domain, a column made only of dates."""
    from app.modules.data_sources.domain_adapters import LaborDomain
    from app.modules.data_sources.mapping_types import SuggestionLevel

    content = csv_bytes([["Colonna1", "Colonna2"], ["26/10/2026", "8"], ["27/10/2026", "7"]])
    table = SmartImportService.read_table(content, "x.csv")
    samples = sample_columns(table)

    service = SmartImportService.__new__(SmartImportService)
    adapter = LaborDomain.__new__(LaborDomain)
    proposal = service._proposal(adapter, list(table.headers), samples)

    assert proposal == {"Colonna1": ("work_date", SuggestionLevel.TO_CHECK)}


def test_the_examples_of_a_column_are_a_few_short_plain_values() -> None:
    long_value = "x" * 200
    content = csv_bytes([["A", "B"], ["1", long_value], ["2", ""], ["3", "y"], ["4", "z"]])
    samples = sample_columns(SmartImportService.read_table(content, "x.csv"))

    assert samples[0].examples == ("1", "2", "3")
    assert len(samples[1].examples[0]) == 40 and samples[1].examples[0].endswith("…")
    assert samples[1].examples[1:] == ("y", "z")  # an empty cell is not an example


def test_cells_are_shown_as_text_and_a_formula_looking_value_is_only_text() -> None:
    assert display_cell('=HYPERLINK("http://x")') == '=HYPERLINK("http://x")'
    assert display_cell("@SUM(A1)") == "@SUM(A1)"
    assert display_cell(None) == ""
    assert display_cell(8.0) == "8" and display_cell(7.5) == "7.5"
    assert display_cell(datetime(2026, 10, 26)) == "2026-10-26"
    assert display_cell(datetime(2026, 10, 26, 14, 30)) == "2026-10-26 14:30"
    assert display_cell(date(2026, 10, 26)) == "2026-10-26"


def test_only_the_first_rows_are_read_to_describe_the_columns() -> None:
    rows = [["Giorno"]] + [["26/10/2026"]] * 5000
    samples = sample_columns(SmartImportService.read_table(csv_bytes(rows), "x.csv"))

    assert len(samples[0].values) == 2000


@pytest.mark.parametrize(
    ("delimiter", "bom"), [(";", True), (",", False), ("\t", False), (";", False)]
)
def test_delimiter_and_bom_are_read_whatever_the_hotel_exports(delimiter: str, bom: bool) -> None:
    table = SmartImportService.read_table(labor_it_file(delimiter=delimiter, bom=bom), "turni.csv")

    assert table.headers == ["Giorno", "Nome dipendente", "Ore turno", "Costo orario", "Reparto"]


def test_empty_rows_are_ignored_and_the_header_row_is_found() -> None:
    content = csv_bytes([[], ["Giorno", "Ore turno"], [], ["26/10/2026", "8"], [], []], bom=True)
    samples = sample_columns(SmartImportService.read_table(content, "x.csv"))

    assert [s.examples for s in samples] == [("26/10/2026",), ("8",)]


def test_an_excel_file_gives_real_dates_not_text() -> None:
    content = xlsx_bytes(
        {
            "Turni": [
                ["Giorno", "Ore turno"],
                [datetime(2026, 10, 26), 8],
                [datetime(2026, 10, 27), 7.5],
            ]
        }
    )
    samples = sample_columns(SmartImportService.read_table(content, "turni.xlsx"))

    assert samples[0].examples == ("2026-10-26", "2026-10-27")
    assert samples[1].examples == ("8", "7.5")
    assert looks_like_dates(samples[0].values)


# --- how dates are written ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "order"),
    [
        (["25/10/2026", "01/11/2026"], DateOrder.DMY),  # 25 cannot be a month
        (["10/25/2026", "11/01/2026"], DateOrder.MDY),  # 25 cannot be a day
        (["01/10/2026", "02/11/2026"], DateOrder.AMBIGUOUS),  # either reading is possible
        (["2026-10-25", "2026-11-01"], DateOrder.ISO),
        (["25/10/2026", "10/25/2026"], DateOrder.CONFLICT),  # both orders proven: inconsistent
        (["lunedì", ""], DateOrder.UNKNOWN),
    ],
)
def test_the_values_of_a_date_column_prove_the_order_or_say_they_cannot(
    values: list[str], order: DateOrder
) -> None:
    assert date_order_of(values) == order


def test_a_date_pattern_follows_the_separator_and_the_time_the_file_really_uses() -> None:
    assert date_pattern(["25/10/2026"], "DMY") == "%d/%m/%Y"
    assert date_pattern(["25-10-2026"], "DMY") == "%d-%m-%Y"
    assert date_pattern(["25.10.2026"], "DMY") == "%d.%m.%Y"
    assert date_pattern(["10/25/2026"], "MDY") == "%m/%d/%Y"
    assert date_pattern(["25/10/2026 14:30"], "DMY") == "%d/%m/%Y %H:%M"
    assert date_pattern(["25/10/2026 14:30:15"], "DMY") == "%d/%m/%Y %H:%M:%S"


def test_a_column_that_writes_its_dates_in_more_than_one_way_has_no_single_pattern() -> None:
    assert date_pattern(["25/10/2026", "26-10-2026"], "DMY") is None
    assert date_pattern(["25/10/2026", "26/10/2026 14:30"], "DMY") is None
    assert date_pattern(["25/10/2026", "2026-10-26"], "DMY") is None
    assert date_pattern(["2026-10-26"], "DMY") is None  # nothing day-first to read


# --- how numbers are written --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "style"),
    [
        (["14,50", "8,5"], NumberStyle.COMMA),
        (["1.234,56", "10,00"], NumberStyle.COMMA),
        (["14.50", "8.5"], NumberStyle.POINT),
        (["1,234.56", "10.00"], NumberStyle.POINT),
        (["1.234", "850"], NumberStyle.AMBIGUOUS),  # a thousand, or one and a bit
        (["1,234"], NumberStyle.AMBIGUOUS),
        (["14,50", "8.5"], NumberStyle.MIXED),
        (["8", "12", "150"], NumberStyle.UNKNOWN),
    ],
)
def test_the_values_of_a_number_column_prove_the_decimal_mark_or_say_they_cannot(
    values: list[str], style: NumberStyle
) -> None:
    assert number_style(values) == style


def test_the_italian_bookings_file_is_read_with_its_semicolons_dates_and_commas() -> None:
    samples = sample_columns(SmartImportService.read_table(bookings_it_file(), "p.csv"))
    by_header = {s.header: s for s in samples}

    assert date_order_of(by_header["Data arrivo"].values) == DateOrder.DMY
    assert date_order_of(by_header["Data prenotazione"].values) == DateOrder.AMBIGUOUS
    assert number_style(by_header["Importo camera"].values) == NumberStyle.COMMA

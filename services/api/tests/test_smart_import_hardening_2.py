"""Smart Import V3 - deterministic hardening 2: five valid files that still ended in the matching
screen, now read - without giving up any of the prudence of hardening 1.

* LO13 hours written with their unit ("8 h", "7,5 ore")
* B34  dates whose month is a name ("26 ottobre 2026", "26-Oct-2026")
* B41  a lone "Total" in a list of reservations
* B50  an arrival after the departure on every row
* L57  "Prev." / "Eff." over two sheets

Every case has its neighbours that must NOT be read: a time, a range, a rate; a date without its
year; a total beside other amounts; a stay that is only wrong once. No database, no model, no
network.
"""

from datetime import datetime

import pytest

from app.modules.data_sources.mapping_types import FileInspection, SuggestionLevel
from tests.hardening_support import (
    BOOKING_HEADER,
    BOOKINGS,
    COSTS,
    LABOR,
    PEOPLE,
    asked_columns,
    booking_row,
    bookings,
    by_header,
    costs,
    field_of,
    level_of,
    question_kinds,
    staff,
    understand,
    xlsx,
    xlsx_sheets,
)

# --- LO13: hours with their unit -----------------------------------------------------------------

HOURS_HEADER = ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"]


@pytest.mark.parametrize(
    ("planned", "worked"),
    [
        ("8 h", "7,5 h"),
        ("8h", "7.5h"),
        ("8 ore", "7,5 ore"),
        ("8 ora", "1 ora"),
        ("8 hours", "7.5 hours"),
        ("8 hrs", "7,5 hrs"),
    ],
)
def test_hours_written_with_their_unit_are_hours_and_the_file_is_automatic(
    planned: str, worked: str
) -> None:
    answer = understand(LABOR, xlsx(staff(HOURS_HEADER, planned=planned, worked=worked)))

    assert field_of(answer, "Ore previste") == "planned_hours"
    assert field_of(answer, "Ore effettive") == "actual_hours"
    assert level_of(answer) == "READY"


@pytest.mark.parametrize(
    "value", ["08:00-16:00", "mezza giornata", "turno completo", "8:30", "8 h 30"]
)
def test_what_is_not_a_number_of_hours_is_not_read_as_one(value: str) -> None:
    answer = understand(LABOR, xlsx(staff(HOURS_HEADER, planned=value, worked=value)))

    assert not {"planned_hours", "actual_hours"} & _assigned(answer)
    assert level_of(answer) in {"MANUAL", "BLOCKED"}


def test_an_hourly_rate_is_not_a_number_of_hours() -> None:
    # "14 €/h" has an h in it; it is a price per hour, and a column of them is not read as hours
    header = ["Data", "Dipendente", "Reparto", "Ore previste", "Tariffa"]
    rows = staff(header, planned="8 h", worked="14 €/h")
    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "Ore previste") == "planned_hours"
    assert field_of(answer, "Tariffa") is None


def test_hours_with_a_unit_in_a_cost_column_are_not_read_as_an_amount() -> None:
    header = ["Data", "Dipendente", "Reparto", "Ore previste", "Costo previsto"]
    answer = understand(LABOR, xlsx(staff(header, planned="8 h", worked="120 h")))

    assert field_of(answer, "Costo previsto") is None


# --- B34: dates whose month is a name ------------------------------------------------------------


_FULL_IT = (
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre"
)
_FULL_EN = "January February March April May June July August September October November December"


def _assigned(answer: FileInspection) -> set[str]:
    return {column.field for column in answer.columns if column.field is not None}


def _named_bookings(style: str, count: int = 14) -> list[list[object]]:
    months_it = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
    months_en = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    full_it = _FULL_IT.split()
    full_en = _FULL_EN.split()

    def write(moment: datetime) -> str:
        month = moment.month - 1
        return {
            "it-short": f"{moment.day} {months_it[month]} {moment.year}",
            "it-full": f"{moment.day} {full_it[month]} {moment.year}",
            "en-short": f"{moment.day} {months_en[month]} {moment.year}",
            "en-full": f"{moment.day} {full_en[month]} {moment.year}",
            "dashed": f"{moment.day:02d}-{months_en[month]}-{moment.year}",
        }[style]

    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(count):
        base = booking_row(index)
        rows.append([base[0], write(base[1]), write(base[2]), write(base[3]), *base[4:]])
    return rows


@pytest.mark.parametrize("style", ["it-short", "it-full", "en-short", "en-full", "dashed"])
def test_dates_with_the_month_written_as_a_name_are_dates(style: str) -> None:
    answer = understand(BOOKINGS, xlsx(_named_bookings(style)))

    assert field_of(answer, "Data prenotazione") == "booked_at"
    assert field_of(answer, "Arrivo") == "check_in"
    assert field_of(answer, "Partenza") == "check_out"
    assert level_of(answer) != "MANUAL"
    assert "DATE_ORDER" not in question_kinds(answer)  # a month name leaves nothing to tell apart


@pytest.mark.parametrize("missing", ["{day} ottobre", "{day} ott 26", "ottobre {day}"])
def test_a_date_without_its_year_is_not_invented(missing: str) -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(14):
        base = booking_row(index)
        day = missing.format(day=base[2].day)
        rows.append([base[0], base[1], day, day, *base[4:]])
    answer = understand(BOOKINGS, xlsx(rows))

    assert not {"check_in", "check_out"} & _assigned(answer)
    assert level_of(answer) in {"MANUAL", "BLOCKED"}  # the person matches the columns


# --- B41: a lone "Total" -------------------------------------------------------------------------

TOTAL_HEADER = ["Res.ID", "Booking date", "Check-in", "Check-out", "Channel", "Status", "Rooms"]


def _with_amounts(extra: list[str], values: list[object]) -> list[list[object]]:
    rows: list[list[object]] = [[*TOTAL_HEADER, *extra]]
    for index in range(14):
        base = booking_row(index)
        rows.append(
            [
                base[0],
                base[1],
                base[2],
                base[3],
                "Booking.com",
                "Confirmed",
                1,
                *values_of(values, index),
            ]
        )
    return rows


def values_of(values: list[object], index: int) -> list[object]:
    return [(value + 10 * index) if isinstance(value, float) else value for value in values]


def test_a_lone_total_in_a_list_of_reservations_is_proposed_as_the_room_revenue() -> None:
    answer = understand(BOOKINGS, xlsx(_with_amounts(["Total"], [237.5])))

    assert field_of(answer, "Total") == "room_revenue"
    assert by_header(answer)["Total"].level == SuggestionLevel.TO_CHECK  # never certain: a question
    assert asked_columns(answer) == ["Total"]
    assert level_of(answer) == "ASK"


def test_the_person_confirming_the_total_makes_the_file_automatic() -> None:
    answer = understand(
        BOOKINGS, xlsx(_with_amounts(["Total"], [237.5])), column_fields={"Total": "room_revenue"}
    )

    assert field_of(answer, "Total") == "room_revenue"
    assert level_of(answer) == "READY"


@pytest.mark.parametrize(
    ("extra", "values"),
    [
        (["Total", "Extras"], [237.5, 12.5]),
        (["Total", "Tax"], [237.5, 3.5]),
        (["Total", "Tax"], [237.5, 3.0]),  # a tax of a whole number is still not a count
        (["Total", "City tax"], [237.5, 5]),
        (["Total", "Commissione"], [237.5, 30.5]),
        (["Total", "Supplementi"], [237.5, 40]),
        (["Total", "Net", "VAT"], [200.5, 37.5, 3]),
    ],
)
def test_a_total_beside_other_amounts_is_never_chosen(
    extra: list[str], values: list[object]
) -> None:
    answer = understand(BOOKINGS, xlsx(_with_amounts(extra, values)))

    revenue = [c.header for c in answer.columns if c.field == "room_revenue"]
    assert "Total" not in revenue
    assert level_of(answer) != "READY"


def test_with_a_room_total_the_room_total_is_the_room_revenue_and_the_total_is_the_total() -> None:
    answer = understand(BOOKINGS, xlsx(_with_amounts(["Room total", "Total"], [200.5, 237.5])))

    assert field_of(answer, "Room total") == "room_revenue"
    assert field_of(answer, "Total") == "total_revenue"


def test_a_total_is_not_the_room_revenue_of_a_file_that_is_not_a_list_of_reservations() -> None:
    # no booking id, no booking date: a table with dates and a total, not reservations
    rows: list[list[object]] = [["Check-in", "Check-out", "Channel", "Status", "Rooms", "Total"]]
    for index in range(14):
        base = booking_row(index)
        rows.append([base[2], base[3], "Booking.com", "Confirmed", 1, 237.5 + index])
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Total") != "room_revenue"


def test_in_a_cost_register_the_total_is_still_the_gross_amount() -> None:
    amounts = [(1000.0 + i, 220.0, 1220.0 + i) for i in range(14)]
    answer = understand(COSTS, xlsx(costs(["Imponibile", "IVA", "Total"], amounts)))

    assert field_of(answer, "Total") == "invoice_gross_amount"
    assert field_of(answer, "Imponibile") == "line_total"


# --- B50: an arrival after the departure ---------------------------------------------------------


def _stay(arrival: str, departure: str, count: int = 14) -> list[list[object]]:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(count):
        base = booking_row(index)
        written = (
            arrival.format(day=base[2], later=base[3]),
            departure.format(day=base[2], later=base[3]),
        )
        rows.append([base[0], base[1], *written, *base[4:]])
    return rows


def _reversed(count: int = 14) -> list[list[object]]:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(count):
        base = booking_row(index)
        rows.append([base[0], base[1], base[3], base[2], *base[4:]])  # arrival = the later date
    return rows


def test_an_arrival_after_the_departure_on_every_row_is_asked_about_and_nothing_is_swapped() -> (
    None
):
    answer = understand(BOOKINGS, xlsx(_reversed()))

    assert question_kinds(answer)[0] == "DATES_REVERSED"
    asked = answer.understanding.questions[0]  # type: ignore[union-attr]
    assert asked.column == "Arrivo" and [c.value for c in asked.choices] == ["Partenza"]
    # neither column is trusted, and each one still says what its header says
    assert field_of(answer, "Arrivo") == "check_in"
    assert field_of(answer, "Partenza") == "check_out"
    assert by_header(answer)["Arrivo"].level == SuggestionLevel.TO_CHECK
    assert by_header(answer)["Partenza"].level == SuggestionLevel.TO_CHECK
    assert level_of(answer) == "ASK"


def test_answering_the_other_questions_does_not_make_a_reversed_file_automatic() -> None:
    answer = understand(BOOKINGS, xlsx(_reversed()), column_fields={"Canale": "channel"})

    assert "DATES_REVERSED" in question_kinds(answer)
    assert level_of(answer) == "ASK"


def test_a_normal_stay_is_not_questioned() -> None:
    answer = understand(BOOKINGS, xlsx(bookings(14)))

    assert "DATES_REVERSED" not in question_kinds(answer)


def test_one_wrong_row_is_a_row_to_report_not_a_reversed_file() -> None:
    rows = bookings(14)
    rows[3][2], rows[3][3] = rows[3][3], rows[3][2]
    answer = understand(BOOKINGS, xlsx(rows))

    assert "DATES_REVERSED" not in question_kinds(answer)


def test_a_stay_of_a_single_day_is_not_reversed() -> None:
    rows = bookings(14)
    for row in rows[1:]:
        row[3] = row[2]
    answer = understand(BOOKINGS, xlsx(rows))

    assert "DATES_REVERSED" not in question_kinds(answer)


@pytest.mark.parametrize(
    ("arrival", "departure", "expected"),
    [
        ("{later:%d/%m/%Y}", "{day:%d/%m/%Y}", True),  # written day-first, reversed
        ("{later:%Y-%m-%d}", "{day:%Y-%m-%d}", True),
        ("{day:%d/%m/%Y}", "{later:%d/%m/%Y}", False),
        ("{later:%d-%b-%Y}", "{day:%d-%b-%Y}", True),  # a month name
    ],
)
def test_text_dates_are_compared_as_dates(arrival: str, departure: str, expected: bool) -> None:
    answer = understand(BOOKINGS, xlsx(_stay(arrival, departure)))

    assert ("DATES_REVERSED" in question_kinds(answer)) is expected


def test_dates_that_can_be_read_two_ways_are_reversed_only_if_they_are_both_ways() -> None:
    # 03/04 against 01/04: after in either reading
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(10):
        base = booking_row(index)
        rows.append([base[0], base[1], "03/04/2026", "01/04/2026", *base[4:]])
    assert "DATES_REVERSED" in question_kinds(understand(BOOKINGS, xlsx(rows)))

    # 03/04 against 05/04: day-first it is a stay, month-first (4 Mar - 4 May) it is one too
    rows = [list(BOOKING_HEADER)]
    for index in range(10):
        base = booking_row(index)
        rows.append([base[0], base[1], "03/04/2026", "05/04/2026", *base[4:]])
    assert "DATES_REVERSED" not in question_kinds(understand(BOOKINGS, xlsx(rows)))

    # 06/05 against 05/06: day-first 6 May is before 5 June, month-first 6 June is after 5 May - the
    # two readings disagree, so it cannot be called reversed
    rows = [list(BOOKING_HEADER)]
    for index in range(10):
        base = booking_row(index)
        rows.append([base[0], base[1], "06/05/2026", "05/06/2026", *base[4:]])
    assert "DATES_REVERSED" not in question_kinds(understand(BOOKINGS, xlsx(rows)))


# --- L57: "Prev." and "Eff." over two sheets ----------------------------------------------------


def _kitchen_and_dining_room(header: list[str]) -> bytes:
    sheets = {}
    merges = {}
    for sheet, title, people in (
        ("Turni Cucina", "ORE CUCINA - SETTIMANA 43", PEOPLE[:3]),
        ("Turni Sala", "ORE SALA - SETTIMANA 43", PEOPLE[3:]),
    ):
        body = staff(header, people=people, days=3)
        rows = [[title, "", "", ""], [], *[[r[0], r[1], r[3], r[4]] for r in body]]
        sheets[sheet] = rows
        merges[sheet] = ["A1:D1"]
    return xlsx_sheets(sheets, merges=merges)


def test_prev_and_eff_together_are_the_plan_and_the_time_worked() -> None:
    answer = understand(
        LABOR, _kitchen_and_dining_room(["Giorno", "Nome", "Reparto", "Prev.", "Eff."])
    )

    assert field_of(answer, "Prev.") == "planned_hours"
    assert field_of(answer, "Eff.") == "actual_hours"
    assert level_of(answer) == "READY"
    # the two sheets are one table: the department is the name of the sheet
    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.data_rows == 18 and table.partition
    assert field_of(answer, "Reparto (foglio)") == "role"


def test_a_lone_prev_is_only_a_maybe() -> None:
    header = ["Data", "Dipendente", "Reparto", "Prev."]
    rows = [header] + [[r[0], r[1], r[2], r[3]] for r in staff(header)[1:]]
    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "Prev.") == "planned_hours"
    assert by_header(answer)["Prev."].level == SuggestionLevel.TO_CHECK
    assert level_of(answer) == "ASK" and asked_columns(answer) == ["Prev."]


def test_prev_and_eff_over_things_that_are_not_hours_are_not_hours() -> None:
    header = ["Data", "Dipendente", "Reparto", "Prev.", "Eff."]
    rows = staff(header, planned="si", worked="no")
    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "Prev.") is None
    assert field_of(answer, "Eff.") is None

    huge = understand(LABOR, xlsx(staff(header, planned=1500, worked=1600)))  # money, not hours
    assert by_header(huge)["Prev."].level is None  # nothing is proposed
    assert level_of(huge) != "READY"


def test_prev_and_eff_are_not_hours_in_a_file_of_another_kind() -> None:
    rows = bookings(14)
    rows[0].extend(["Prev.", "Eff."])
    for index, row in enumerate(rows[1:]):
        row.extend([100 + index, 90 + index])
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Prev.") is None
    assert field_of(answer, "Eff.") is None


def test_two_sheets_with_other_columns_are_still_not_merged() -> None:
    # not the same table: nothing is invented, the person is asked which one to import
    sheets = {
        "Turni": staff(HOURS_HEADER, days=3),
        "Costi": costs(["Imponibile"], [(1000.0 + i,) for i in range(8)]),
    }
    answer = understand(LABOR, xlsx_sheets(sheets))

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and not table.partition
    assert field_of(answer, "Ore previste") == "planned_hours"

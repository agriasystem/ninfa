"""Smart Import V3 - deterministic hardening 1: what the benchmark found, kept from coming back.

The Smart Import Intelligence Benchmark V1 measured five documents offered as "a summary and one
button" with a reading that was wrong or incomplete, and three documents whose personal values
reached the browser. Each test below is one of those findings, written as a small document of its
own (the benchmark corpus stays an independent measure), plus the neighbouring cases that must
NOT change - a table that really ends, a second table that really is another table.

No database, no model, no network: the real understanding service on real bytes.
"""

from datetime import datetime

import pytest

from app.modules.document_understanding.pii import detect_pii
from app.modules.document_understanding.stats import column_stats
from tests.hardening_support import (
    BOOKING_HEADER,
    BOOKINGS,
    COSTS,
    LABOR,
    PEOPLE,
    asked_columns,
    booking_row,
    by_header,
    costs,
    field_of,
    level_of,
    payload_of,
    question_kinds,
    staff,
    understand,
    with_weekday,
    xlsx,
)

# --- P0: a column that says "hours" must not disappear -------------------------------------------


def test_ore_prog_is_the_planned_hours_and_the_file_is_still_automatic() -> None:
    header = ["Data", "Dipendente", "Reparto / Mansione", "Ore prog.", "Ore effettive"]
    answer = understand(LABOR, xlsx(staff(header)))

    assert field_of(answer, "Ore prog.") == "planned_hours"
    assert field_of(answer, "Ore effettive") == "actual_hours"
    assert level_of(answer) == "READY"
    assert question_kinds(answer) == []


def test_an_hours_column_that_does_not_say_which_is_asked_about_even_when_the_other_is_there() -> (
    None
):
    # "Ore" next to "Ore effettive": the plan is surely the other one - but NINFA does not drop it.
    answer = understand(
        LABOR, xlsx(staff(["Data", "Dipendente", "Reparto", "Ore", "Ore effettive"]))
    )

    assert level_of(answer) == "ASK"
    assert asked_columns(answer) == ["Ore"]
    question = answer.understanding.questions[0]  # type: ignore[union-attr]
    assert question.candidate == "planned_hours"  # "Is «Ore» the planned hours?"
    assert field_of(answer, "Ore") is None  # nothing is decided before the person answers


def test_the_person_confirming_the_hours_column_makes_the_file_automatic() -> None:
    header = ["Data", "Dipendente", "Reparto", "Ore", "Ore effettive"]
    answer = understand(LABOR, xlsx(staff(header)), column_fields={"Ore": "planned_hours"})

    assert field_of(answer, "Ore") == "planned_hours"
    assert level_of(answer) == "READY"


def test_hours_of_another_kind_are_left_alone_without_a_question() -> None:
    # Contractual hours are not the plan, and nobody asked for them: no guess, no question.
    header = ["Data", "Dipendente", "Reparto", "Ore da contratto", "Ore lavorate"]
    answer = understand(LABOR, xlsx(staff(header)))

    assert field_of(answer, "Ore da contratto") is None
    assert field_of(answer, "Ore lavorate") == "actual_hours"
    assert question_kinds(answer) == []


# --- P0: two columns that say the same thing are a choice, not a guess ---------------------------


def test_two_columns_for_the_planned_hours_are_both_asked_about_and_none_is_taken() -> None:
    header = [
        "Data",
        "Dipendente",
        "Reparto",
        "Ore previste",
        "Ore previste (rev.)",
        "Ore effettive",
    ]
    rows = [
        [*row[:4], row[3] + 1, row[4]] if index else row for index, row in enumerate(staff(header))
    ]
    answer = understand(LABOR, xlsx(rows))

    assert level_of(answer) == "ASK"
    assert question_kinds(answer) == ["COLUMN_MEANING", "COLUMN_MEANING"]
    assert set(asked_columns(answer)) == {"Ore previste", "Ore previste (rev.)"}
    assert field_of(answer, "Ore previste") is None
    assert field_of(answer, "Ore previste (rev.)") is None
    # ...and every column is still shown as an example of what the file holds, nothing else is lost
    assert field_of(answer, "Ore effettive") == "actual_hours"


def test_the_person_picking_one_of_the_two_columns_settles_it() -> None:
    header = [
        "Data",
        "Dipendente",
        "Reparto",
        "Ore previste",
        "Ore previste (rev.)",
        "Ore effettive",
    ]
    rows = [
        [*row[:4], row[3] + 1, row[4]] if index else row for index, row in enumerate(staff(header))
    ]
    answer = understand(LABOR, xlsx(rows), column_fields={"Ore previste (rev.)": "planned_hours"})

    assert field_of(answer, "Ore previste (rev.)") == "planned_hours"
    assert field_of(answer, "Ore previste") is None
    assert level_of(answer) == "READY"


def test_two_check_in_columns_are_asked_about_and_neither_is_taken() -> None:
    header = [
        "Codice prenotazione",
        "Data prenotazione",
        "Check-in",
        "Check-in effettivo",
        "Partenza",
        "Canale",
        "Importo camere",
        "Stato",
        "Camere",
    ]
    rows = [header]
    for i in range(14):
        base = booking_row(i)
        rows.append(
            [base[0], base[1], base[2], base[2], base[3], base[4], base[5], base[6], base[7]]
        )
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Check-in") is None
    assert field_of(answer, "Check-in effettivo") is None
    assert {"Check-in", "Check-in effettivo"} <= set(asked_columns(answer))


def test_a_column_and_its_look_alike_with_a_different_rule_are_not_a_choice() -> None:
    # "Reparto" is the department; "Mansione" is the job: a staff file very often has both.
    rows = staff(["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"])
    rows[0].insert(3, "Mansione")
    for row in rows[1:]:
        row.insert(3, "Addetto sala")
    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "Reparto") == "role"
    assert level_of(answer) in {"READY", "ASK"}
    assert "Reparto" not in asked_columns(answer)


# --- P0: money is never chosen between two look-alikes -------------------------------------------


NET_ROWS = [(1000.0 + 10 * i, 1000.0 + 10 * i - 20, 220.0 + 2 * i) for i in range(16)]


def test_an_original_and_an_adjusted_net_are_never_chosen_between() -> None:
    answer = understand(
        COSTS,
        xlsx(costs(["Imponibile", "Imponibile (rettificato)", "IVA"], NET_ROWS)),
    )

    assert field_of(answer, "Imponibile") is None
    assert field_of(answer, "Imponibile (rettificato)") is None
    assert level_of(answer) == "MANUAL"  # the person matches the columns, seeing all of them
    assert "AMOUNT_BASIS" not in question_kinds(answer)  # not a yes/no about one of the two


def test_one_net_column_is_still_automatic() -> None:
    answer = understand(COSTS, xlsx(costs(["Imponibile", "IVA"], [(a, c) for a, _, c in NET_ROWS])))

    assert field_of(answer, "Imponibile") == "line_total"
    assert level_of(answer) == "READY"


def test_a_vat_register_with_a_net_per_rate_has_no_single_net_to_import() -> None:
    rows = [(1000.0 + 10 * i, 220.0 + 2 * i, 500.0, 50.0, 1770.0 + 12 * i) for i in range(18)]
    answer = understand(
        COSTS,
        xlsx(
            costs(["Imponibile 22%", "IVA 22%", "Imponibile 10%", "IVA 10%", "Totale doc."], rows)
        ),
    )

    for header in ("Imponibile 22%", "Imponibile 10%"):
        assert field_of(answer, header) is None  # no rate is taken for the whole document
    assert level_of(answer) == "MANUAL"
    assert "AMOUNT_BASIS" not in question_kinds(answer)


def test_a_vat_register_with_one_rate_column_reads_it() -> None:
    rows = [(1000.0 + 10 * i, 220.0 + 2 * i) for i in range(18)]
    answer = understand(COSTS, xlsx(costs(["Imponibile 22%", "IVA 22%"], rows)))

    assert field_of(answer, "Imponibile 22%") == "line_total"


def test_two_columns_for_commissions_do_not_stop_a_file_that_does_not_need_them() -> None:
    # An optional amount that appears twice is left out, not a reason to match by hand.
    header = [*BOOKING_HEADER, "Commissione", "Commissione (2)"]
    rows = [header] + [[*booking_row(i), 10.0, 12.0] for i in range(14)]
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Commissione") is None
    assert field_of(answer, "Commissione (2)") is None
    assert field_of(answer, "Importo camere") == "room_revenue"
    assert level_of(answer) != "MANUAL"


# --- P0: a table does not end at a page break ----------------------------------------------------


def _paged(
    count: int, *, every: int, repeat_header: bool, title: bool = False
) -> list[list[object]]:
    rows: list[list[object]] = [["ELENCO PRENOTAZIONI (stampa)"], [], list(BOOKING_HEADER)]
    for index in range(count):
        if index and index % every == 0:
            rows.append(["--- pagina successiva ---"])
            if title:
                rows.append(["Hotel Aurora - elenco prenotazioni"])
            if repeat_header:
                rows.append(list(BOOKING_HEADER))
        rows.append(booking_row(index))
    return rows


@pytest.mark.parametrize("repeat_header", [False, True])
@pytest.mark.parametrize("title", [False, True])
def test_a_page_break_every_few_records_does_not_cut_the_table(
    repeat_header: bool, title: bool
) -> None:
    answer = understand(
        BOOKINGS, xlsx(_paged(24, every=8, repeat_header=repeat_header, title=title))
    )

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None
    assert table.data_rows == 24  # (it used to read 8)
    assert table.header_rows == (3,)
    assert field_of(answer, "Codice prenotazione") == "source_record_id"


def test_the_header_printed_again_straight_after_the_records_is_not_a_record() -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(12):
        if index == 6:
            rows.append(list(BOOKING_HEADER))
        rows.append(booking_row(index))
    answer = understand(BOOKINGS, xlsx(rows))

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.data_rows == 12


def test_a_second_table_with_the_same_columns_is_still_another_table() -> None:
    # A title and a blank line between them: this is NOT a page break, the person is asked.
    rows: list[list[object]] = [["PRENOTAZIONI CONFERMATE"], list(BOOKING_HEADER)]
    rows += [booking_row(i) for i in range(8)]
    rows += [[], ["PRENOTAZIONI CANCELLATE"], list(BOOKING_HEADER)]
    rows += [booking_row(100 + i) for i in range(8)]
    answer = understand(BOOKINGS, xlsx(rows))

    assert "TABLE" in question_kinds(answer)
    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.data_rows == 8


def test_a_note_at_the_end_still_ends_the_table() -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    rows += [booking_row(i) for i in range(10)]
    rows += [["Nota: i dati sono provvisori"], ["Generato il 25/10/2026"], ["Firma"]]
    answer = understand(BOOKINGS, xlsx(rows))

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.data_rows == 10


# --- P1: the abbreviations of a PMS / channel manager ---------------------------------------------


def test_a_channel_manager_export_is_plainly_a_bookings_file() -> None:
    header = ["Res #", "Bkd", "Arr", "Dep", "Src", "Tot", "Stato", "Camere"]
    rows = [header]
    for i in range(14):
        base = booking_row(i)
        rows.append(
            [f"{10000 + i}", base[1], base[2], base[3], base[4], f"{base[5]}.00", base[6], base[7]]
        )
    answer = understand(BOOKINGS, xlsx(rows))

    detection = answer.understanding.detection  # type: ignore[union-attr]
    assert detection.domain == "BOOKINGS" and detection.level == "HIGH"
    assert field_of(answer, "Res #") == "source_record_id"
    assert field_of(answer, "Bkd") == "booked_at"
    assert field_of(answer, "Arr") == "check_in"
    assert field_of(answer, "Dep") == "check_out"
    assert field_of(answer, "Src") == "channel"
    assert "Tot" in asked_columns(answer)  # a bare total: room revenue or the whole stay's?


def test_codes_and_amounts_written_as_abbreviations_are_found() -> None:
    header = ["Cod.", "Data pren.", "Arr.", "Part.", "Can.", "Imp.", "Stato", "Camere"]
    rows = [header]
    for i in range(14):
        base = booking_row(i)
        rows.append(
            [
                base[0],
                base[1],
                base[2],
                base[3],
                ("DIR", "EXP", "BDC")[i % 3],
                f"{base[5]},00",
                base[6],
                base[7],
            ]
        )
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Cod.") == "source_record_id"
    assert field_of(answer, "Can.") == "channel"
    assert "Imp." in asked_columns(answer)
    # nothing is certain about the three, so the person confirms them - the file is not "manual"
    assert level_of(answer) == "ASK"


def test_an_english_export_is_recognised_as_bookings() -> None:
    header = ["Confirmation code", "Status", "Start date", "End date", "Booked", "Earnings"]
    rows = [header]
    for i in range(14):
        base = booking_row(i)
        rows.append([base[0], "Confirmed", base[2], base[3], base[1], f"{base[5]}.00"])
    answer = understand(BOOKINGS, xlsx(rows))

    detection = answer.understanding.detection  # type: ignore[union-attr]
    assert detection.domain == "BOOKINGS"
    assert field_of(answer, "Start date") == "check_in"
    assert field_of(answer, "End date") == "check_out"


def test_the_department_written_rep_is_a_staff_file() -> None:
    header = ["Data", "Rep.", "Ore pian.", "Ore eff."]
    rows = [header] + [[row[0], row[2], row[3], row[4]] for row in staff(header)[1:]]
    answer = understand(LABOR, xlsx(rows))

    detection = answer.understanding.detection  # type: ignore[union-attr]
    assert detection.domain == "LABOR" and detection.level == "HIGH"
    assert field_of(answer, "Rep.") == "role"
    assert field_of(answer, "Ore pian.") == "planned_hours"
    assert field_of(answer, "Ore eff.") == "actual_hours"


# --- P1: dates with their weekday, amounts with their currency ------------------------------------


def test_dates_written_with_their_weekday_are_dates() -> None:
    rows = [list(BOOKING_HEADER)]
    for i in range(14):
        base = booking_row(i)
        rows.append(
            [
                base[0],
                base[1],
                with_weekday(base[2]),
                with_weekday(base[3], long=True),
                *base[4:],
            ]
        )
    answer = understand(BOOKINGS, xlsx(rows))

    assert field_of(answer, "Arrivo") == "check_in"
    assert field_of(answer, "Partenza") == "check_out"
    assert level_of(answer) != "MANUAL"


def test_a_day_roster_written_with_weekdays_is_a_roster_by_day() -> None:
    rows = staff(["Giorno", "Dipendente", "Reparto", "Ore previste", "Ore effettive"])
    for row in rows[1:]:
        row[0] = with_weekday(row[0])
    answer = understand(LABOR, xlsx(rows))

    assert field_of(answer, "Giorno") == "work_date"
    assert "PERIOD_SUMMARY_ONLY" not in [
        b.code.value
        for b in answer.understanding.blockers  # type: ignore[union-attr]
    ]


def test_amounts_with_the_currency_written_after_them_are_amounts() -> None:
    rows = costs(
        ["Imponibile"],
        [
            (f"{1000 + 25 * i:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", "."),)
            for i in range(16)
        ],
    )
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "Imponibile") == "line_total"
    assert level_of(answer) == "READY"


# --- P1: costs -----------------------------------------------------------------------------------


def test_an_amount_that_says_it_excludes_vat_is_the_net_and_nobody_is_asked() -> None:
    rows = costs(["Amount excl. VAT", "VAT", "Total"], [(a, c, a + c) for a, _, c in NET_ROWS])
    rows[0][:4] = ["Date", "Invoice no.", "Supplier", "Description"]
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "Amount excl. VAT") == "line_total"
    assert field_of(answer, "VAT") == "invoice_tax_amount"
    assert "AMOUNT_BASIS" not in question_kinds(answer)


def test_item_is_the_description_when_the_values_are_descriptions() -> None:
    rows = costs(["Net amount"], [(a,) for a, _, _ in NET_ROWS])
    rows[0][:4] = ["Invoice date", "Invoice number", "Vendor", "Item"]
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "Item") == "line_description"
    assert level_of(answer) == "READY"


@pytest.mark.parametrize("label", ["Numero", "Num.", "N.", "Doc.", "Fatt. n.", "Documento"])
def test_the_document_number_is_found_under_the_names_a_register_uses(label: str) -> None:
    rows = costs(["Imponibile"], [(a,) for a, _, _ in NET_ROWS])
    rows[0][1] = label
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, label) == "invoice_number"


def test_a_column_of_one_two_three_is_a_row_counter_and_not_the_document_number() -> None:
    rows = costs(["Imponibile"], [(a,) for a, _, _ in NET_ROWS])
    rows[0][1] = "N."
    for index, row in enumerate(rows[1:], start=1):
        row[1] = index
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "N.") is None


def test_the_holder_and_the_hand_made_headings_are_read_as_what_they_are() -> None:
    rows = costs(["Imponibile"], [(a,) for a, _, _ in NET_ROWS])
    rows[0][:4] = ["Data", "Documento", "Intestatario", "Causale"]
    answer = understand(COSTS, xlsx(rows))
    assert field_of(answer, "Intestatario") == "supplier_name"
    assert field_of(answer, "Causale") == "line_description"
    # the names of suppliers are shown (a business) - but never when they are people's
    assert by_header(answer)["Intestatario"].examples == ()

    manual = costs(["Importo netto"], [(a,) for a, _, _ in NET_ROWS])
    manual[0][:4] = ["Data", "Fatt. n.", "Da chi", "Cosa"]
    answer = understand(COSTS, xlsx(manual))
    assert field_of(answer, "Da chi") == "supplier_name"
    assert field_of(answer, "Cosa") == "line_description"
    assert level_of(answer) == "ASK"  # two loose names: confirmed, not trusted


def test_a_cost_centre_is_not_a_category_of_spend() -> None:
    rows = costs(["Centro di costo", "Imponibile"], [("CC01", a) for a, _, _ in NET_ROWS])
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "Centro di costo") is None
    assert field_of(answer, "Imponibile") == "line_total"
    assert level_of(answer) == "READY"


def test_a_category_is_still_a_category_next_to_a_cost_centre() -> None:
    categories = ["Energia", "Lavanderia", "Alimentari", "Manutenzione"]
    rows = costs(
        ["Categoria", "Centro di costo", "Imponibile"],
        [(categories[i % 4], "CC01", a) for i, (a, _, _) in enumerate(NET_ROWS)],
    )
    answer = understand(COSTS, xlsx(rows))

    assert field_of(answer, "Categoria") == "cost_category"
    assert field_of(answer, "Centro di costo") is None


def test_a_single_group_over_the_amounts_is_a_two_level_header() -> None:
    body = costs(["Imponibile", "IVA", "Totale"], [(a, c, a + c) for a, _, c in NET_ROWS])
    rows = [
        ["", "", "", "", "Importi", "", ""],
        ["Data", "Numero", "Fornitore", "Descrizione", "Imponibile", "IVA", "Totale"],
        *body[1:],
    ]
    answer = understand(COSTS, xlsx(rows, merges=["E1:G1"]))

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.header_rows == (1, 2)
    assert field_of(answer, "Importi - Imponibile") == "line_total"
    assert field_of(answer, "Numero") == "invoice_number"


def test_a_title_merged_over_the_whole_table_is_still_a_title() -> None:
    rows = [
        ["ELENCO FATTURE", "", "", "", ""],
        ["Data", "Numero", "Fornitore", "Descrizione", "Imponibile"],
        *[row[:4] + [row[4]] for row in costs(["Imponibile"], [(a,) for a, _, _ in NET_ROWS])[1:]],
    ]
    answer = understand(COSTS, xlsx(rows, merges=["A1:E1"]))

    table = answer.understanding.document.table  # type: ignore[union-attr]
    assert table is not None and table.header_rows == (2,)


# --- P0: personal values never reach the browser --------------------------------------------------


def _leaks(answer: object, values: list[str]) -> list[str]:
    text = payload_of(answer).casefold()  # type: ignore[arg-type]
    return [value for value in values if value.casefold() in text]


def test_the_names_under_a_header_nobody_knows_are_recognised_and_stay_home() -> None:
    # "Addetto" is not a word of any list; the same four people come back on every day
    rows = staff(["Data", "Addetto", "Ore previste", "Ore effettive"], people=PEOPLE[:4], days=6)
    rows = [rows[0]] + [[row[0], row[1], row[3], row[4]] for row in rows[1:]]
    answer = understand(LABOR, xlsx(rows))

    assert by_header(answer)["Addetto"].not_used_reason == "PERSON"
    assert by_header(answer)["Addetto"].examples == ()
    assert _leaks(answer, PEOPLE[:4]) == []


def test_names_in_a_column_called_reparto_do_not_become_departments() -> None:
    # the headers say Reparto / Dipendente over what are really a person and a department
    answer = understand(
        LABOR, xlsx(staff(["Data", "Reparto", "Dipendente", "Ore previste", "Ore effettive"]))
    )

    assert field_of(answer, "Reparto") != "role"  # people's names, whatever the header says
    assert by_header(answer)["Reparto"].not_used_reason == "PERSON"
    assert _leaks(answer, PEOPLE) == []
    assert level_of(answer) != "READY"


def test_a_payroll_uploaded_on_the_costs_card_shows_no_name() -> None:
    rows = [["Dipendente", "Mese", "Lordo", "Netto in busta", "Contributi"]]
    for index, person in enumerate(PEOPLE):
        surname, name = person.split()[1], person.split()[0]
        rows.append(
            [f"{surname} {name}", "Ottobre", f"{2200 + index}.00", f"{1600 + index}.00", "520.00"]
        )
    answer = understand(COSTS, xlsx(rows))

    assert _leaks(answer, [f"{p.split()[1]} {p.split()[0]}" for p in PEOPLE]) == []
    assert by_header(answer)["Dipendente"].examples == ()


def test_a_name_in_the_title_or_the_sheet_name_of_a_roster_does_not_leave() -> None:
    rows = staff(["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"])
    rows.insert(0, [f"Turni di {PEOPLE[0]} - settimana 43"])
    answer = understand(LABOR, xlsx(rows, sheet=PEOPLE[1]))

    assert _leaks(answer, [PEOPLE[0], PEOPLE[1]]) == []


def test_an_address_a_number_a_tax_code_or_an_iban_in_a_free_column_never_leaves() -> None:
    notes = [
        "scrivere a giulia.ferretti@example.org",
        "tel. +39 333 0001234",
        "FRRGLI90Z41H501X",
        "IT60X0542811101000000123456",
        "chiamare 333 0001234 dopo le 18",
    ]
    rows = staff(["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"])
    rows[0].append("Annotazioni")
    for index, row in enumerate(rows[1:]):
        row.append(notes[index % len(notes)])
    answer = understand(LABOR, xlsx(rows))

    secrets = [
        "giulia.ferretti@example.org",
        "+39 333 0001234",
        "FRRGLI90Z41H501X",
        "IT60X0542811101000000123456",
        "333 0001234",
    ]
    assert _leaks(answer, secrets) == []


def test_the_headers_and_the_decision_the_import_needs_are_not_touched_by_the_gate() -> None:
    rows = staff(["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"])
    answer = understand(LABOR, xlsx(rows))

    assert answer.proposal is not None
    assert {c.header for c in answer.proposal.columns} == {
        "Data",
        "Dipendente",
        "Reparto",
        "Ore previste",
        "Ore effettive",
    }


@pytest.mark.parametrize(
    ("header", "values", "expected"),
    [
        ("Addetto", ["Giulia Ferretti", "Marco Rinaldi", "Elena Orlandi"] * 6, True),
        ("Reparto", ["Reception", "Housekeeping", "Cucina"] * 6, False),
        ("Camera", ["Camera Doppia", "Suite Deluxe", "Camera Singola"] * 6, False),
        ("Tariffa", ["Best Available", "Early Bird", "Non Rimborsabile"] * 6, False),
        ("Sede", ["Front Office", "Back Office", "Food Beverage"] * 6, False),
    ],
)
def test_a_column_of_people_is_told_from_a_column_of_departments_rooms_and_rates(
    header: str, values: list[str], expected: bool
) -> None:
    finding = detect_pii(header, column_stats(values))

    assert (finding is not None) is expected


def test_dates_are_never_taken_for_people() -> None:
    assert detect_pii("Colonna", column_stats([datetime(2026, 10, 1)] * 6)) is None

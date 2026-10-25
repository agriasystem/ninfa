"""Office-realistic documents: the files people actually keep, not the ones a developer would write.

Merged cells running down a column, a header with a line break inside it, a legend or a KPI block
drawn beside the table, a blank row between every record, two dates and two numbers where only one
of each is the invoice's, a register that is really a payment schedule... None of them is tuned to
Smart Import: each is plausible on its own and the truth says only what a careful person would say.
"""

import random
from datetime import date, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col, flat_document, headers, parts, records
from tests.benchmarks.smart_import_v3.corpus_bookings import (
    STATUS_LABELS_IT,
    Stay,
    c_booked,
    c_booked_day,
    c_channel,
    c_id,
    c_in,
    c_out,
    c_revenue,
    c_rooms,
    c_status,
    core_it,
    p_name,
    six_it,
    stays,
    with_state,
)
from tests.benchmarks.smart_import_v3.corpus_costs import (
    CATEGORY_TRUTH,
    Line,
    base,
    k_category,
    k_date,
    k_desc,
    k_gross,
    k_net,
    k_number,
    k_supplier,
    k_vat,
    lines,
)
from tests.benchmarks.smart_import_v3.corpus_labor import (
    DEPARTMENTS,
    Shift,
    names_of,
    record,
    roster,
    standard_fields,
)
from tests.benchmarks.smart_import_v3.draw import (
    Note,
    Section,
    Sheet,
    TableRef,
    write_table,
    xlsx_bytes,
)
from tests.benchmarks.smart_import_v3.kit import Built, Registry, facts, pii
from tests.benchmarks.smart_import_v3.model import GRID, SECTION, TITLE, Golden, column
from tests.benchmarks.smart_import_v3.pool import HOTEL, WEEK, hours, money, person, week, when

LABOR_OFFICE = Registry("LO", "labor")
BOOKINGS_OFFICE = Registry("BO", "bookings")
COSTS_OFFICE = Registry("CO", "costs")

__all__ = ["BOOKINGS_OFFICE", "COSTS_OFFICE", "LABOR_OFFICE", "GRID"]


# ==================================================================================================
# Staff
# ==================================================================================================


@LABOR_OFFICE.case("reception_roster_bare_ore_title_department", "office")
def lo_bare_ore(r: random.Random) -> Built:
    shifts = roster(r, people=4, days=week(WEEK, 5), depts=["Reception"])
    sheet = Sheet("Foglio1", left=1)
    sheet.title_line("TURNI RECEPTION - SETT. 43", 4)
    sheet.add([HOTEL], style="subtitle")
    sheet.blank()
    ref = write_table(
        sheet,
        ["Giorno", "Cognome Nome", "Orario", "Ore"],
        [
            [when(s.day, "it"), s.name, "08-16" if s.planned < 8 else "07-15", s.planned]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "ASK",
        **facts(ref),
        fields={"work_date": column("Giorno"), "department": TITLE},
        ambiguous=("planned_hours", "actual_hours"),
        unmapped=(("Orario",),),
        questions=("COLUMN_MEANING",),
        tolerated=("DEPARTMENT_CONFIRM",),
        answers={"column_fields": [{"header": ["Ore"], "occurrence": 1, "field": "planned_hours"}]},
        **pii([("Cognome Nome",)], names_of(shifts)),
        note="A bare 'Ore' in a roster: planned or worked is the person's call.",
    )
    return Built("TURNI RECEPTION SETT 43.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("payroll_monthly_summary_by_qualifica", "office", "negative")
def lo_payroll_summary(r: random.Random) -> Built:
    sheet = Sheet("Ore Ottobre")
    sheet.title_line("RIEPILOGO ORE MENSILI - OTTOBRE 2026", 6)
    sheet.blank()
    body: list[list[Any]] = []
    values: list[str] = []
    for i in range(8):
        first, last = person(i)
        values.extend([first, last])
        body.append(
            [
                last,
                first,
                ("Receptionist", "Cameriera ai piani", "Cuoco", "Barista")[i % 4],
                150 + i,
                i % 3 * 4,
                150 + i + i % 3 * 4,
            ]
        )
    ref = write_table(
        sheet, ["Cognome", "Nome", "Qualifica", "Ore ord.", "Ore straord.", "Totale"], body
    )
    golden = Golden(
        "labor",
        "REJECT",
        **facts(ref),
        blockers=("PERIOD_SUMMARY_ONLY",),
        **pii([("Cognome",), ("Nome",)], values),
        note="Monthly hours per person: no day, nothing to analyse day by day.",
    )
    return Built("Ore mensili ottobre.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("clock_in_out_times_no_hours", "office", "negative")
def lo_clock_times(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 3))
    sheet = Sheet("Timbrature")
    ref = write_table(
        sheet,
        ["Data", "Dipendente", "Reparto", "Entrata", "Uscita"],
        [
            [
                when(s.day, "it"),
                s.name,
                s.dept,
                f"{7 + int(s.planned) % 3:02d}:0{s.person % 6}",
                f"{15 + int(s.planned) % 3:02d}:1{s.person % 6}",
            ]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "REJECT",
        **facts(ref),
        blockers=("MISSING_REQUIRED",),
        **pii([("Dipendente",)], names_of(shifts)),
        note="Clock-in and clock-out times: hours are arithmetic V3.0 does not do.",
    )
    return Built("timbrature_ottobre.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("weekday_name_and_date_in_two_columns", "office")
def lo_weekday_and_date(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 4))
    names = ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica")
    sheet = Sheet("Piano")
    ref = write_table(
        sheet,
        ["Giorno", "Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"],
        [
            [names[s.day.weekday()], when(s.day, "xl"), s.name, s.dept, s.planned, s.actual]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields("Data"),
        unmapped=(("Giorno",),),
        **pii([("Dipendente",)], names_of(shifts)),
        note="'Giorno' is the name of the weekday, 'Data' is the date.",
    )
    return Built("piano_turni.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("future_days_have_no_actual_hours_yet", "office")
def lo_future_blank(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 7))
    sheet = Sheet("Ottobre")
    ref = write_table(
        sheet,
        ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"],
        [
            [
                when(s.day, "xl"),
                s.name,
                s.dept,
                s.planned,
                s.actual if s.day < WEEK + timedelta(days=4) else None,
            ]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields(),
        **pii([("Dipendente",)], names_of(shifts)),
        note="The last three days are planned only: their actual hours are blank.",
    )
    return Built("ottobre_in_corso.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("job_titles_in_qualifica_column", "office")
def lo_job_titles(r: random.Random) -> Built:
    titles = ("Receptionist", "Cameriera ai piani", "Cuoco", "Barista", "Manutentore")
    shifts = roster(r, people=5, days=week(WEEK, 3), depts=titles)
    sheet = Sheet("Turni")
    ref = write_table(
        sheet,
        ["Data", "Nominativo", "Qualifica", "Ore previste", "Ore effettive"],
        [record(s) for s in shifts],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields("Data", "Qualifica"),
        labels={
            "role_mapping": {
                "Receptionist": "FRONT_OFFICE",
                "Cameriera ai piani": "HOUSEKEEPING",
                "Cuoco": "KITCHEN",
                "Barista": "FOOD_BEVERAGE",
                "Manutentore": "MAINTENANCE",
            }
        },
        **pii([("Nominativo",)], names_of(shifts)),
        note="The department is given as each person's job title.",
    )
    return Built("turni_qualifiche.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("department_in_a_label_value_block", "office")
def lo_key_value_block(r: random.Random) -> Built:
    shifts = roster(r, people=4, days=week(WEEK, 4), depts=["Spa"])
    sheet = Sheet("Turni")
    sheet.add(["Reparto:", "SPA E BENESSERE"], style="label")
    sheet.add(["Periodo:", "19-25 ottobre 2026"], style="label")
    sheet.add(["Responsabile:", "Direzione"], style="label")
    sheet.blank()
    ref = write_table(
        sheet,
        ["Data", "Operatore", "Ore previste", "Ore effettive"],
        [[when(s.day, "it"), s.name, s.planned, s.actual] for s in shifts],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields={
            "work_date": column("Data"),
            "department": TITLE,
            "planned_hours": column("Ore previste"),
            "actual_hours": column("Ore effettive"),
        },
        tolerated=("DEPARTMENT_CONFIRM", "VALUE_LABELS"),
        **pii([("Operatore",)], names_of(shifts)),
        note="'Reparto: SPA E BENESSERE' written as a label and a value above the table.",
    )
    return Built("spa_turni.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("one_sheet_per_week_sett43_sett44", "office")
def lo_sheet_per_week(r: random.Random) -> Built:
    sheets: list[Sheet] = []
    refs: list[TableRef] = []
    every: list[Shift] = []
    for number, start in enumerate((WEEK, WEEK + timedelta(days=7))):
        shifts = roster(r, people=4, days=week(start, 3))
        every.extend(shifts)
        sheet = Sheet(f"Sett {43 + number}")
        refs.append(
            write_table(
                sheet,
                ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"],
                [record(s) for s in shifts],
            )
        )
        sheets.append(sheet)
    golden = Golden(
        "labor",
        "READY",
        **facts(refs[0].merged(refs[1]), sheets=[s.title for s in sheets]),
        fields=standard_fields(),
        **pii([("Dipendente",)], names_of(every)),
        note="Two weeks, one sheet each, the same columns: one table.",
    )
    return Built("turni_sett43_44.xlsx", xlsx_bytes(sheets), golden, sheets)


@LABOR_OFFICE.case("legend_block_drawn_beside_the_table", "office")
def lo_legend_beside(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 3))
    sheet = Sheet("Turni")
    sheet.title_line("Turni settimana 43", 5)
    sheet.blank()
    ref = write_table(
        sheet,
        ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"],
        [record(s) for s in shifts],
    )
    legend = [
        ("Legenda", None),
        ("Giallo", "sostituzione"),
        ("Verde", "ferie"),
        ("Rosso", "malattia"),
    ]
    for offset, (label, text) in enumerate(legend):
        sheet.put(ref.header_rows[0] + offset, 7, label, style="label")
        if text:
            sheet.put(ref.header_rows[0] + offset, 8, text)
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields(),
        **pii([("Dipendente",)], names_of(shifts)),
        note="A four-line colour legend sits to the right of the first rows of the table.",
    )
    return Built("turni_con_legenda_laterale.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("header_repeated_in_every_department_block", "office", "negative")
def lo_header_per_block(r: random.Random) -> Built:
    shifts = roster(r, people=8, days=week(WEEK, 2), block=True)
    sheet = Sheet("Turni")
    first: TableRef | None = None
    for dept in DEPARTMENTS:
        sheet.add([dept.upper()], style="section")
        ref = write_table(
            sheet,
            ["Data", "Dipendente", "Ore previste", "Ore effettive"],
            [[when(s.day, "xl"), s.name, s.planned, s.actual] for s in shifts if s.dept == dept],
        )
        first = first or ref
        sheet.blank()
    assert first is not None
    golden = Golden(
        "labor",
        "NOT_AUTOMATIC",
        **facts(first),
        tolerated=("TABLE", "DEPARTMENT_CONFIRM"),
        **pii([("Dipendente",)], names_of(shifts)),
        note="Four tables with the same columns, each under its own department line and header: "
        "V3.0 cannot join them, so it must not import one and drop the rest silently.",
    )
    return Built("turni_blocchi_reparto.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("department_cells_merged_down_the_column", "office")
def lo_merged_departments(r: random.Random) -> Built:
    shifts = roster(r, people=8, days=week(WEEK, 2), block=True)
    sheet = Sheet("Piano", freeze="A2")
    body: list[list[Any]] = []
    spans: list[tuple[int, int]] = []
    cursor = 2
    for dept in DEPARTMENTS:
        block = [s for s in shifts if s.dept == dept]
        for index, s in enumerate(block):
            body.append(
                [dept if index == 0 else None, when(s.day, "xl"), s.name, s.planned, s.actual]
            )
        spans.append((cursor, cursor + len(block) - 1))
        cursor += len(block)
    ref = write_table(
        sheet, ["Reparto", "Data", "Dipendente", "Ore previste", "Ore effettive"], body
    )
    for first_row, last_row in spans:
        sheet.merge_range(first_row, 1, last_row, 1)
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields={
            "department": column("Reparto"),
            "work_date": column("Data"),
            "planned_hours": column("Ore previste"),
            "actual_hours": column("Ore effettive"),
        },
        **pii([("Dipendente",)], names_of(shifts)),
        note="Each department is written once in a cell merged over its rows.",
    )
    return Built("piano_reparti_uniti.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("blank_row_between_every_record", "office")
def lo_airy(r: random.Random) -> Built:
    shifts = roster(r, people=4, days=week(WEEK, 3))
    sheet = Sheet("Turni")
    sheet.title_line("Turni", 5)
    header = ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"]
    sheet.add(header, style="header")
    rows_written = 0
    first_row = 0
    for s in shifts:
        sheet.blank()
        row = sheet.add(record(s))
        first_row = first_row or row
        rows_written += 1
    golden = Golden(
        "labor",
        "READY",
        sheets=(sheet.title,),
        header_rows=(2,),
        first_row=first_row,
        data_rows=rows_written,
        skipped={"totals": 0, "sections": 0},
        fields=standard_fields(),
        **pii([("Dipendente",)], names_of(shifts)),
        note="An empty row between every two records.",
    )
    return Built("turni_spaziati.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("hours_written_with_a_unit", "office")
def lo_units(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 3))
    sheet = Sheet("Turni")
    ref = write_table(
        sheet,
        ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"],
        [
            [
                when(s.day, "it"),
                s.name,
                s.dept,
                f"{s.planned:g} h".replace(".", ","),
                f"{s.actual:g} ore".replace(".", ","),
            ]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields(),
        **pii([("Dipendente",)], names_of(shifts)),
        note="'8 h', '7,5 ore': hours with their unit typed after them.",
    )
    return Built("turni_unita.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("header_cells_with_line_breaks", "office")
def lo_header_breaks(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 3))
    sheet = Sheet("Turni")
    ref = write_table(
        sheet,
        [
            "Data\n(gg/mm/aaaa)",
            "Dipendente",
            "Reparto\no mansione",
            "Ore previste\n(da piano)",
            "Ore effettive\n(da timbratura)",
        ],
        [record(s, date_style="it") for s in shifts],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields={
            "work_date": column("Data\n(gg/mm/aaaa)"),
            "department": column("Reparto\no mansione"),
            "planned_hours": column("Ore previste\n(da piano)"),
            "actual_hours": column("Ore effettive\n(da timbratura)"),
        },
        **pii([("Dipendente",)], names_of(shifts)),
    )
    return Built("turni_intestazioni_a_capo.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("abbreviated_department_header_and_codes", "office")
def lo_rep_codes(r: random.Random) -> Built:
    shifts = roster(r, people=6, days=week(WEEK, 3), depts=["REC", "HK", "FO"])
    sheet = Sheet("Foglio1")
    body: list[list[Any]] = []
    values: list[str] = []
    for s in shifts:
        first, last = person(s.person)
        values.extend([first, last])
        body.append([when(s.day, "it"), last, first, s.dept, s.planned, s.actual])
    ref = write_table(sheet, ["Data", "Cognome", "Nome", "Rep.", "Ore pian.", "Ore eff."], body)
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields("Data", "Rep.", "Ore pian.", "Ore eff."),
        labels={
            "role_mapping": {"REC": "FRONT_OFFICE", "HK": "HOUSEKEEPING", "FO": "FRONT_OFFICE"}
        },
        **pii([("Cognome",), ("Nome",)], values),
    )
    return Built("presenze.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@LABOR_OFFICE.case("extra_numeric_columns_overtime_leave", "office")
def lo_extra_numeric(r: random.Random) -> Built:
    shifts = roster(r, people=5, days=week(WEEK, 3))
    sheet = Sheet("Turni")
    ref = write_table(
        sheet,
        [
            "Data",
            "Dipendente",
            "Reparto",
            "Ore previste",
            "Ore effettive",
            "Straordinari",
            "Ferie residue",
            "% presenza",
        ],
        [
            [
                when(s.day, "xl"),
                s.name,
                s.dept,
                s.planned,
                s.actual,
                max(0.0, s.actual - s.planned),
                12 + s.person,
                0.96,
            ]
            for s in shifts
        ],
    )
    golden = Golden(
        "labor",
        "READY",
        **facts(ref),
        fields=standard_fields(),
        unmapped=(("Straordinari",), ("Ferie residue",), ("% presenza",)),
        **pii([("Dipendente",)], names_of(shifts)),
        note="Overtime, leave and attendance %: numbers, but not planned or worked hours.",
    )
    return Built("turni_con_extra.xlsx", xlsx_bytes([sheet]), golden, [sheet])


# ==================================================================================================
# Bookings
# ==================================================================================================


@BOOKINGS_OFFICE.case("channel_written_as_codes", "office")
def bo_codes(r: random.Random) -> Built:
    codes = {"Booking.com": "BDC", "Expedia": "EXP", "Airbnb": "ABB", "Diretto": "DIR"}
    items = stays(r, 20, channels=tuple(codes))
    return flat_document(
        "bookings",
        "pren_codici_canale.xlsx",
        with_state(
            [
                c_id("Cod."),
                c_booked_day("Data pren.", "it"),
                c_in("Arr.", "it"),
                c_out("Part.", "it"),
                Col("Can.", lambda s: codes[s.channel], "channel"),
                c_revenue("Imp.", "it"),
            ]
        ),
        items,
    )


@BOOKINGS_OFFICE.case("arrivals_by_day_sections_no_ids", "office", "negative")
def bo_arrivals_sections(r: random.Random) -> Built:
    sheet = Sheet("Arrivi")
    sheet.title_line("ARRIVI DELLA SETTIMANA", 5)
    sheet.blank()
    body: list[Any] = []
    values: list[str] = []
    for day in range(3):
        body.append(Section(f"ARRIVI {when(date(2026, 10, 19) + timedelta(days=day), 'it')}"))
        for i in range(4):
            name = f"{person(day * 4 + i)[1]} {person(day * 4 + i)[0]}"
            values.append(name)
            body.append(
                [
                    name,
                    100 + day * 4 + i,
                    1 + i % 3,
                    r.choice(["Booking.com", "Diretto"]),
                    money(180.0 + 20 * i, "it"),
                ]
            )
    ref = write_table(sheet, ["Nominativo", "Camera", "Notti", "Provenienza", "Tot. €"], body)
    golden = Golden(
        "bookings",
        "REJECT",
        **facts(ref),
        blockers=("MISSING_REQUIRED",),
        **pii([("Nominativo",)], values),
        note="The arrival date is a line above each block; there is no booking id or booking date.",
    )
    return Built("arrivi_settimana.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@BOOKINGS_OFFICE.case("channel_manager_abbreviations", "office")
def bo_cm_abbreviations(r: random.Random) -> Built:
    items = stays(r, 20, prefix="")
    return flat_document(
        "bookings",
        "cm_dump.csv",
        with_state(
            [
                c_id("Res #"),
                c_booked_day("Bkd", "iso"),
                c_in("Arr", "iso"),
                c_out("Dep", "iso"),
                c_channel("Src"),
                c_revenue("Tot", "point"),
            ]
        ),
        items,
        csv={"delimiter": ",", "decimal": ".", "dates": "iso"},
    )


@BOOKINGS_OFFICE.case("front_desk_arrivals_list_no_booking_date", "office", "negative")
def bo_front_desk_arrivals(r: random.Random) -> Built:
    items = stays(r, 14)
    return flat_document(
        "bookings",
        "arrivi_settimana_43.xlsx",
        [
            p_name("Nominativo"),
            Col("Camere", lambda s: 1, None, junk=False),
            Col("Notti", lambda s: s.nights, None, junk=False),
            c_in("Dal", "it"),
            c_out("Al", "it"),
            c_channel("Provenienza"),
            c_revenue("Tot. €", "it"),
        ],
        items,
        outcome="REJECT",
        blockers=("MISSING_REQUIRED",),
        absent=("source_record_id", "booked_at"),
        note="A front-desk list: no booking code and no booking date.",
    )


@BOOKINGS_OFFICE.case("kpi_block_beside_the_table", "office")
def bo_kpi_beside(r: random.Random) -> Built:
    items = stays(r, 18)
    cols = core_it()
    sheet = Sheet("Prenotazioni")
    sheet.title_line("PRENOTAZIONI OTTOBRE", 6)
    sheet.blank()
    ref = write_table(sheet, headers(cols), records(cols, items))
    for offset, (label, value) in enumerate(
        [
            ("KPI", None),
            ("Prenotazioni", len(items)),
            ("Notti", sum(s.nights for s in items)),
            ("Ricavo", round(sum(s.revenue for s in items), 2)),
        ]
    ):
        sheet.put(ref.header_rows[0] + offset, 10, label, style="label")
        if value is not None:
            sheet.put(ref.header_rows[0] + offset, 11, value)
    meaning = parts(cols, items)
    golden = Golden("bookings", "READY", **facts(ref), fields=meaning["fields"])
    return Built("prenotazioni_kpi.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@BOOKINGS_OFFICE.case("table_starts_in_column_c_frozen_panes", "office")
def bo_indented(r: random.Random) -> Built:
    items = stays(r, 18)
    return flat_document(
        "bookings",
        "Prenotazioni 2026.xlsx",
        core_it(),
        items,
        preamble=[("title", "PRENOTAZIONI 2026"), ("note", "dati estratti dal gestionale")],
        left=2,
        freeze="C5",
        sheet_title="Prenotazioni 2026",
    )


@BOOKINGS_OFFICE.case("weekday_prefixed_dates", "office")
def bo_weekday_dates(r: random.Random) -> Built:
    items = stays(r, 18)
    return flat_document(
        "bookings",
        "pren_giorni_settimana.xlsx",
        with_state(
            [
                c_id(),
                c_booked_day("Data prenotazione", "it"),
                c_in("Arrivo", "weekday"),
                c_out("Partenza", "weekday"),
                c_channel(),
                c_revenue("Importo camere", "it"),
            ]
        ),
        items,
        note="'ven 23/10/2026': the weekday abbreviation in front of the date.",
    )


@BOOKINGS_OFFICE.case("room_and_breakfast_revenue_columns", "office")
def bo_room_breakfast(r: random.Random) -> Built:
    items = stays(r, 18)
    return flat_document(
        "bookings",
        "pren_ricavi_separati.xlsx",
        [
            *six_it()[:5],
            c_revenue("Importo camera"),
            Col("Importo colazione", lambda s: round(s.nights * s.pax * 8.0, 2), None),
            Col("Totale", lambda s: round(s.revenue + s.nights * s.pax * 8.0, 2), "total_revenue"),
            c_status(),
            c_rooms(),
        ],
        items,
    )


@BOOKINGS_OFFICE.case("status_written_as_ok_canc_ns", "office")
def bo_status_codes(r: random.Random) -> Built:
    codes = {"CONFIRMED": "OK", "CANCELLED": "CANC", "NO_SHOW": "NS"}
    items = stays(r, 20, statuses=("CONFIRMED", "CONFIRMED", "CANCELLED", "NO_SHOW"))
    return flat_document(
        "bookings",
        "pren_stati_abbreviati.xlsx",
        [*core_it(status=False), Col("Stato", lambda s: codes[s.status], "status")],
        items,
        labels={"status_mapping": {"OK": "CONFIRMED", "CANC": "CANCELLED", "NS": "NO_SHOW"}},
    )


@BOOKINGS_OFFICE.case("one_sheet_per_week", "office")
def bo_sheet_per_week(r: random.Random) -> Built:
    sheets: list[Sheet] = []
    refs: list[TableRef] = []
    cols = core_it()
    for number, start in enumerate((date(2026, 10, 13), date(2026, 10, 20))):
        items = stays(r, 8, start=start, first=60000 + number * 100)
        sheet = Sheet(f"Sett {42 + number}")
        refs.append(write_table(sheet, headers(cols), records(cols, items)))
        sheets.append(sheet)
    golden = Golden(
        "bookings",
        "READY",
        **facts(refs[0].merged(refs[1]), sheets=[s.title for s in sheets]),
        fields=parts(cols, [])["fields"],
    )
    return Built("prenotazioni_settimane.xlsx", xlsx_bytes(sheets), golden, sheets)


@BOOKINGS_OFFICE.case("header_cells_with_line_breaks", "office")
def bo_header_breaks(r: random.Random) -> Built:
    items = stays(r, 18)
    return flat_document(
        "bookings",
        "pren_intestazioni_a_capo.xlsx",
        with_state(
            [
                c_id("N.\npren."),
                c_booked_day("Data\nprenotazione", "xl"),
                c_in("Arrivo"),
                c_out("Partenza"),
                c_channel("Canale\ndi vendita"),
                c_revenue("Importo\ncamere (€)"),
            ]
        ),
        items,
    )


@BOOKINGS_OFFICE.case("channel_merged_down_the_column", "office")
def bo_merged_channel(r: random.Random) -> Built:
    items = sorted(
        stays(r, 18, channels=("Booking.com", "Diretto", "Expedia")), key=lambda s: s.channel
    )
    cols = [
        c_channel(),
        c_id(),
        c_booked_day("Data prenotazione", "xl"),
        c_in(),
        c_out(),
        c_revenue(),
        c_status(),
        c_rooms(),
    ]
    sheet = Sheet("Per canale")
    body: list[list[Any]] = []
    spans: list[tuple[int, int]] = []
    cursor = 2
    for channel in ("Booking.com", "Diretto", "Expedia"):
        block = [s for s in items if s.channel == channel]
        for index, s in enumerate(block):
            row = [c.cell(s) for c in cols]
            if index:
                row[0] = None
            body.append(row)
        spans.append((cursor, cursor + len(block) - 1))
        cursor += len(block)
    ref = write_table(sheet, headers(cols), body)
    for first_row, last_row in spans:
        sheet.merge_range(first_row, 1, last_row, 1)
    golden = Golden("bookings", "READY", **facts(ref), fields=parts(cols, items)["fields"])
    return Built("pren_per_canale.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@BOOKINGS_OFFICE.case("blank_row_between_every_record", "office")
def bo_airy(r: random.Random) -> Built:
    items = stays(r, 12)
    cols = core_it()
    sheet = Sheet("Elenco")
    sheet.add(headers(cols), style="header")
    first_row = 0
    for s in items:
        sheet.blank()
        row = sheet.add([c.cell(s) for c in cols])
        first_row = first_row or row
    golden = Golden(
        "bookings",
        "READY",
        sheets=(sheet.title,),
        header_rows=(1,),
        first_row=first_row,
        data_rows=len(items),
        skipped={"totals": 0, "sections": 0},
        fields=parts(cols, items)["fields"],
    )
    return Built("elenco_spaziato.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@BOOKINGS_OFFICE.case("two_months_side_by_side", "office", "negative")
def bo_side_by_side(r: random.Random) -> Built:
    october = stays(r, 8, start=date(2026, 10, 13), first=70000)
    november = stays(r, 8, start=date(2026, 11, 13), first=71000)
    cols = core_it()
    sheet = Sheet("Ott-Nov")
    sheet.add(
        [
            *["OTTOBRE" if i == 0 else None for i in range(6)],
            None,
            *["NOVEMBRE" if i == 0 else None for i in range(6)],
        ],
        style="label",
    )
    body = [
        [*[c.cell(a) for c in cols], None, *[c.cell(b) for c in cols]]
        for a, b in zip(october, november, strict=True)
    ]
    ref = write_table(sheet, [*headers(cols), "", *headers(cols)], body)
    ref = TableRef(ref.sheet, (1, 2), ref.first_row, ref.last_row, ref.data_rows, ref.skipped)
    golden = Golden(
        "bookings",
        "NOT_AUTOMATIC",
        **facts(ref),
        note="Two months drawn side by side: a label above each block, every header twice.",
    )
    return Built("ott_nov_affiancati.xlsx", xlsx_bytes([sheet]), golden, [sheet])


# ==================================================================================================
# Costs
# ==================================================================================================


@COSTS_OFFICE.case("protocol_number_and_supplier_document_number", "office")
def co_protocol(r: random.Random) -> Built:
    items = lines(r, 20)
    return flat_document(
        "costs",
        "registro_acquisti.xlsx",
        [
            k_date("Data doc."),
            Col("Prot.", lambda x: f"P{int(x.number[-3:]):05d}", None),
            k_number("N. doc. fornitore"),
            k_supplier("Fornitore"),
            k_desc("Descrizione"),
            k_net("Imponibile"),
            k_vat("IVA"),
        ],
        items,
        note="'Prot.' is the hotel's own protocol; the invoice number is the supplier's.",
    )


@COSTS_OFFICE.case("payment_schedule_not_a_register", "office", "negative")
def co_schedule(r: random.Random) -> Built:
    items = lines(r, 16)
    return flat_document(
        "costs",
        "scadenziario_fornitori.xlsx",
        [
            k_supplier("Fornitore"),
            k_number("N. fattura"),
            Col("Scadenza", lambda x: when(x.due, "it"), "due_date"),
            Col("Importo da pagare", lambda x: x.gross, "invoice_gross_amount"),
            Col("Stato", lambda x: "da pagare", None),
        ],
        items,
        outcome="REJECT",
        blockers=("MISSING_REQUIRED",),
        absent=("invoice_date", "line_description"),
        note="A payment schedule: no invoice date, no description.",
    )


@COSTS_OFFICE.case("cost_centre_and_department_columns", "office")
def co_cost_centre(r: random.Random) -> Built:
    items = lines(r, 20)
    return flat_document(
        "costs",
        "costi_per_centro.xlsx",
        [
            k_date("Data"),
            k_number("Doc."),
            k_supplier("Fornitore"),
            k_desc("Descrizione"),
            Col("Centro di costo", lambda x: "CC" + x.number[-1], None),
            Col(
                "Reparto",
                lambda x: ("Camere", "Ristorante", "Generale")[int(x.number[-1]) % 3],
                None,
            ),
            k_net("Netto"),
        ],
        items,
    )


@COSTS_OFFICE.case("vat_register_two_rates_two_dates", "office", "negative")
def co_vat_register(r: random.Random) -> Built:
    items = lines(r, 18)
    return flat_document(
        "costs",
        "registro_iva_acquisti.xlsx",
        [
            Col("Data reg.", lambda x: when(x.day + timedelta(days=4), "it"), None),
            k_date("Data doc.", "it"),
            Col("Prot.", lambda x: f"{int(x.number[-3:]):04d}", None),
            k_number("N. doc."),
            k_supplier("Fornitore"),
            k_desc("Descrizione"),
            Col(
                "Imponibile 22%",
                lambda x: x.net if x.rate == 22.0 else 0.0,
                "net_amount",
                ambiguous=True,
            ),
            Col("IVA 22%", lambda x: x.vat if x.rate == 22.0 else 0.0, None, junk=False),
            Col(
                "Imponibile 10%",
                lambda x: x.net if x.rate == 10.0 else 0.0,
                "net_amount",
                ambiguous=True,
            ),
            Col("IVA 10%", lambda x: x.vat if x.rate == 10.0 else 0.0, None, junk=False),
            k_gross("Totale doc."),
        ],
        items,
        outcome="NOT_AUTOMATIC",
        note="The net is split into one column per VAT rate: no single net column exists.",
    )


@COSTS_OFFICE.case("cash_book_not_invoices", "office", "negative")
def co_cash_book(r: random.Random) -> Built:
    sheet = Sheet("Prima nota")
    sheet.title_line("PRIMA NOTA CASSA - OTTOBRE", 5)
    sheet.blank()
    body = [
        [
            when(date(2026, 10, 1 + i), "it"),
            ("Incasso giornaliero", "Spesa minuta", "Versamento banca")[i % 3],
            money(300.0 + 11 * i, "it") if i % 3 == 0 else None,
            money(45.0 + i, "it") if i % 3 else None,
            money(1500.0 + 13 * i, "it"),
        ]
        for i in range(14)
    ]
    ref = write_table(sheet, ["Data", "Descrizione", "Entrate", "Uscite", "Saldo"], body)
    golden = Golden(
        "other",
        "REJECT",
        **facts(ref),
        note="A cash book: movements, no supplier and no invoice number.",
    )
    return Built("prima_nota_cassa.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


@COSTS_OFFICE.case("utilities_summary_without_number_or_supplier", "office", "negative")
def co_utilities(r: random.Random) -> Built:
    sheet = Sheet("Utenze")
    ref = write_table(
        sheet,
        ["Utenza", "Periodo", "Consumo", "Importo", "Scadenza"],
        [
            [
                ("Luce", "Acqua", "Gas")[i % 3],
                f"{1 + i % 3}° trim.",
                4200 + 100 * i,
                money(900.0 + 35 * i, "it"),
                when(date(2026, 11, 15), "it"),
            ]
            for i in range(9)
        ],
    )
    golden = Golden(
        "other",
        "REJECT",
        **facts(ref),
        note="Utility consumption: no supplier, no document number.",
    )
    return Built("utenze_2026.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


@COSTS_OFFICE.case("supplier_written_as_section_lines", "office", "negative")
def co_supplier_sections(r: random.Random) -> Built:
    items = lines(r, 18)
    sheet = Sheet("Per fornitore")
    body: list[Any] = []
    for supplier in sorted({x.supplier for x in items}):
        body.append(Section(supplier.upper()))
        body.extend(
            [when(x.day, "xl"), x.number, x.description, x.net]
            for x in items
            if x.supplier == supplier
        )
    ref = write_table(sheet, ["Data", "N. documento", "Descrizione", "Imponibile"], body)
    golden = Golden(
        "costs",
        "REJECT",
        **facts(ref),
        blockers=("MISSING_REQUIRED",),
        absent=("supplier_name",),
        note="The supplier is the line above each block of invoices, not a column.",
    )
    return Built("fatture_per_fornitore.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@COSTS_OFFICE.case("supplier_cells_merged_down_the_column", "office")
def co_merged_supplier(r: random.Random) -> Built:
    items = sorted(lines(r, 18), key=lambda x: x.supplier)
    cols = [
        k_supplier("Fornitore"),
        k_date("Data"),
        k_number("N. documento"),
        k_desc("Descrizione"),
        k_net("Imponibile"),
    ]
    sheet = Sheet("Fatture")
    body: list[list[Any]] = []
    spans: list[tuple[int, int]] = []
    cursor = 2
    for supplier in sorted({x.supplier for x in items}):
        block = [x for x in items if x.supplier == supplier]
        for index, x in enumerate(block):
            row = [c.cell(x) for c in cols]
            if index:
                row[0] = None
            body.append(row)
        spans.append((cursor, cursor + len(block) - 1))
        cursor += len(block)
    ref = write_table(sheet, headers(cols), body)
    for first_row, last_row in spans:
        if last_row > first_row:
            sheet.merge_range(first_row, 1, last_row, 1)
    golden = Golden("costs", "READY", **facts(ref), fields=parts(cols, items)["fields"])
    return Built("fatture_per_fornitore_unite.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@COSTS_OFFICE.case("amounts_with_eur_suffix_text", "office")
def co_eur_suffix(r: random.Random) -> Built:
    items = lines(r, 18)
    return flat_document(
        "costs",
        "costi_eur_testo.xlsx",
        [*base(), Col("Imponibile", lambda x: f"{money(x.net, 'it')} EUR", "net_amount")],
        items,
    )


@COSTS_OFFICE.case("header_cells_with_line_breaks", "office")
def co_header_breaks(r: random.Random) -> Built:
    items = lines(r, 18)
    return flat_document(
        "costs",
        "costi_intestazioni_a_capo.xlsx",
        [
            k_date("Data\ndocumento"),
            k_number("N.\ndocumento"),
            k_supplier("Fornitore"),
            k_desc("Descrizione"),
            k_net("Importo\nnetto (€)"),
            k_vat("IVA\n(€)"),
        ],
        items,
    )


@COSTS_OFFICE.case("blank_row_between_every_record", "office")
def co_airy(r: random.Random) -> Built:
    items = lines(r, 12)
    cols = [*base(), k_net()]
    sheet = Sheet("Registro")
    sheet.add(headers(cols), style="header")
    first_row = 0
    for x in items:
        sheet.blank()
        row = sheet.add([c.cell(x) for c in cols])
        first_row = first_row or row
    golden = Golden(
        "costs",
        "READY",
        sheets=(sheet.title,),
        header_rows=(1,),
        first_row=first_row,
        data_rows=len(items),
        skipped={"totals": 0, "sections": 0},
        fields=parts(cols, items)["fields"],
    )
    return Built("registro_spaziato.xlsx", xlsx_bytes([sheet]), golden, [sheet])


@COSTS_OFFICE.case("attachment_and_approval_columns", "office")
def co_attachments(r: random.Random) -> Built:
    items = lines(r, 18)
    return flat_document(
        "costs",
        "fatture_da_approvare.xlsx",
        [
            k_date("Data"),
            k_number("N. fattura"),
            k_supplier("Fornitore"),
            k_desc("Descrizione"),
            k_category("Categoria"),
            k_net("Imponibile"),
            Col("Allegato", lambda x: x.number.replace("/", "_") + ".pdf", None),
            Col("Approvata", lambda x: "x" if int(x.number[-1]) % 2 else "", None),
            Col("Note", lambda x: "", None),
        ],
        items,
        labels={"category_mapping": CATEGORY_TRUTH},
    )


@COSTS_OFFICE.case("category_by_month_matrix_not_a_register", "office", "negative")
def co_matrix(r: random.Random) -> Built:
    sheet = Sheet("Confronto")
    sheet.title_line("COSTI PER CATEGORIA - CONFRONTO TRIMESTRE", 4)
    sheet.blank()
    ref = write_table(
        sheet,
        ["Categoria", "Ottobre", "Novembre", "Dicembre"],
        [
            [c, money(1000 + 130 * i, "it"), money(1100 + 90 * i, "it"), money(980 + 70 * i, "it")]
            for i, c in enumerate(CATEGORY_TRUTH)
        ],
    )
    golden = Golden(
        "other", "REJECT", **facts(ref), note="A category by month matrix: totals, not invoices."
    )
    return Built("confronto_costi.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


__unused = (Line, Note, Stay, SECTION, STATUS_LABELS_IT, c_booked, c_status, hours, k_category, pii)

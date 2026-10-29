"""Files for the Source Learning layout tests and benchmark: hotels' documents in DIFFERENT shapes,
one source (property + kind of data) bringing back several of them.

Real `.xlsx` and `.csv` bytes. Nothing here is a real person: the only names are made up, and the
staff documents never carry any (the layout is what is under test, not the people).

* bookings: the PMS export (a title above its table, sheet "Prenotazioni"), another export (sheet
  "Export", the table lower in the sheet, one blank column on its left) and a CSV;
* staff: a people x days grid, a document whose department is only in its title, and ordinary
  tables in the house's own words (xlsx and csv).

`month` makes every file another file (other dates, other references), so two imports never
collide; `extra` adds a column nobody asked for.
"""

import io
from datetime import date, datetime, timedelta
from typing import Any

from openpyxl import Workbook

from tests.source_learning_support import KINDS

CHANNELS = ("Booking.com", "Expedia", "Diretto")
PEOPLE = (
    ("Persona 1", "Reception", 8),
    ("Persona 2", "Reception", 8),
    ("Persona 3", "Housekeeping", 6),
    ("Persona 4", "Housekeeping", 6),
    ("Persona 5", "Cucina", 8),
    ("Persona 6", "Cucina", 6),
)


def _bytes(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _csv(rows: list[list[Any]]) -> bytes:
    lines = [";".join("" if cell is None else str(cell) for cell in row) for row in rows]
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8")


# --- bookings -------------------------------------------------------------------------------------


def reservations_pms(
    month: int = 11,
    *,
    rows: int = 8,
    extra: bool = False,
    sheet_name: str = "Prenotazioni",
    guests: bool = False,
    rate_plan: bool = False,
) -> bytes:
    """Sheet "Prenotazioni": a title and the hotel above the table (header on row 5), then a second
    sheet "Note" with two lines of text. `guests` / `rate_plan` add an optional column the engine
    reads as another field (two exports that differ by one of them are lookalikes)."""
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name
    sheet["A1"] = "ELENCO PRENOTAZIONI"
    sheet["A2"] = "Hotel Aurora - generato il 24/10/2026"
    sheet.append([])
    header = [
        "Codice prenotazione",
        "Data prenotazione",
        "Arrivo",
        "Partenza",
        "Stato",
        "Camere",
        "Ricavo camera",
        "Canale",
    ]
    optional = [*(["Ospiti"] if guests else []), *(["Tariffa"] if rate_plan else [])]
    sheet.append([*header, *optional, *(["Note interne"] if extra else [])])
    for i in range(rows):
        arrival = datetime(2026, month, 2 + i)
        line: list[Any] = [
            f"RES-{month:02d}{i:03d}",
            datetime(2026, month, 1) - timedelta(days=8 + i),
            arrival,
            arrival + timedelta(days=2),
            "Confermata",
            1,
            120.0 + i,
            CHANNELS[i % 3],
        ]
        more = [*([2 + i % 2] if guests else []), *(["Standard"] if rate_plan else [])]
        sheet.append([*line, *more, *(["da verificare"] if extra else [])])
    notes = book.create_sheet("Note")
    notes.append(["Promemoria"])
    notes.append(["da controllare a fine mese"])
    return _bytes(book)


def reservations_export(month: int = 11, *, rows: int = 7, extra: bool = False) -> bytes:
    """Sheet "Export": empty rows, a line of text, then the table (one blank column on its left),
    and a second sheet "Info"."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Export"
    for _ in range(5):
        sheet.append([])
    sheet["B6"] = "Esportazione gestionale"
    header = [
        None,
        "Rif",
        "Dal",
        "Al",
        "Provenienza",
        "Camere",
        "Importo camere",
        "Data prenotazione",
        "Stato",
    ]
    sheet.append([*header, *(["Annotazioni"] if extra else [])])
    for i in range(rows):
        arrival = datetime(2026, month, 3 + i)
        line: list[Any] = [
            None,
            f"EX-{month:02d}{i:03d}",
            arrival,
            arrival + timedelta(days=3),
            CHANNELS[i % 3],
            1,
            140.0 + i,
            datetime(2026, month, 1) - timedelta(days=5 + i),
            "Confermata",
        ]
        sheet.append([*line, *(["ok"] if extra else [])])
    book.create_sheet("Info").append(["Generato da", "gestionale"])
    return _bytes(book)


def reservations_csv(month: int = 11, *, rows: int = 7, extra: bool = False) -> bytes:
    """A channel manager's semicolon CSV, in English, with day-first dates and comma decimals."""
    header = [
        "Reservation ID",
        "Booking date",
        "Arrival",
        "Departure",
        "Status",
        "Rooms",
        "Room revenue",
        "Source",
    ]
    table: list[list[Any]] = [[*header, *(["Osservazioni"] if extra else [])]]
    for i in range(rows):
        arrival = datetime(2026, month, 4 + i)
        line = [
            f"CS-{month:02d}{i:03d}",
            (datetime(2026, month, 1) - timedelta(days=6 + i)).strftime("%d/%m/%Y"),
            arrival.strftime("%d/%m/%Y"),
            (arrival + timedelta(days=2)).strftime("%d/%m/%Y"),
            "Confirmed",
            1,
            f"{150 + i},50",
            CHANNELS[i % 3],
        ]
        table.append([*line, *(["-"] if extra else [])])
    return _csv(table)


# --- staff ----------------------------------------------------------------------------------------


def _monday(month: int) -> date:
    first = date(2026, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7)


def staff_grid(month: int = 11, *, weekday_names: bool = True) -> bytes:
    """A people x days grid for the first full week of `month`; the period is in its title."""
    start = _monday(month)
    end = start + timedelta(days=6)
    book = Workbook()
    sheet = book.active
    sheet.title = "Settimana"
    sheet["A1"] = f"TURNI SETTIMANA - dal {start:%d/%m/%Y} al {end:%d/%m/%Y}"
    sheet.merge_cells("A1:J1")
    sheet.append([])
    names = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
    days: list[Any] = names if weekday_names else [start + timedelta(days=i) for i in range(7)]
    sheet.append(["Persona", "Reparto", *days, "Totale"])
    for _name, department, hours in PEOPLE:
        values = [hours, hours, hours, hours, hours, 0, 0]
        sheet.append([f"{department} {hours}", department, *values, sum(values)])
    return _bytes(book)


def staff_title_department(month: int = 11) -> bytes:
    """The department is written only in the title: "TURNI HOUSEKEEPING - SETTIMANA 43"."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Foglio1"
    sheet["A1"] = "TURNI HOUSEKEEPING - SETTIMANA 43"
    sheet.append([])
    sheet.append(["Data", "Nome", "Ore previste"])
    for offset in range(3):
        day = datetime(2026, month, 1 + offset)
        for index, (_name, _department, hours) in enumerate(PEOPLE[2:4]):
            sheet.append([day, f"Persona {index + 3}", hours])
    return _bytes(book)


def staff_csv(columns: dict[str, str], *, month: int = 11, rows: int = 12) -> bytes:
    """An ordinary staff table as CSV, in the house's own words (`columns`: header -> kind of its
    values, see `source_learning_support.KINDS`). Whole hours only: no decimal mark to decide."""
    kinds = list(columns.values())
    table: list[list[Any]] = [list(columns)]
    for i in range(rows):
        line: list[Any] = []
        for kind in kinds:
            value = KINDS[kind](i, month)
            if isinstance(value, datetime):
                value = value.strftime("%d/%m/%Y")
            elif isinstance(value, float):
                value = round(value)
            line.append(value)
        table.append(line)
    return _csv(table)

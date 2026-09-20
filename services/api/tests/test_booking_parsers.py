"""CSV and XLSX readers (no database)."""

import datetime as dt
from typing import Any

import pytest

from app.modules.bookings import parsers
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions
from app.modules.bookings.parsers import open_table
from tests.booking_support import csv_bytes, xlsx_bytes

HEADER = ["Booking ID", "Check-in", "Room Revenue", "Note"]
ROWS = [["A1", "2026-07-10", "120.50", "ok"], ["A2", "2026-07-11", "99.00", "vip"]]


def cells(table: parsers.SourceTable) -> list[tuple[int, list[Any]]]:
    return [(row.number, row.cells) for row in table.rows()]


def refused(
    content: bytes, filename: str, options: FormatOptions | None = None
) -> BookingErrorCode:
    with pytest.raises(BookingImportError) as info:
        table = open_table(content, filename, options)
        list(table.rows())
    return info.value.error_code


# --- CSV (tests 23-26, 29, 30) ---------------------------------------------------------------


def test_csv_with_commas() -> None:
    table = open_table(csv_bytes([HEADER, *ROWS]), "bookings.csv")

    assert table.headers == HEADER
    assert cells(table) == [(2, ROWS[0]), (3, ROWS[1])]


def test_csv_with_semicolons() -> None:
    table = open_table(csv_bytes([HEADER, *ROWS], delimiter=";"), "bookings.csv")

    assert table.headers == HEADER
    assert cells(table)[0] == (2, ROWS[0])


def test_csv_with_tabs() -> None:
    table = open_table(csv_bytes([HEADER, *ROWS], delimiter="\t"), "bookings.csv")

    assert table.headers == HEADER
    assert cells(table)[1] == (3, ROWS[1])


def test_the_delimiter_is_not_fooled_by_decimal_commas_in_the_data() -> None:
    content = b"Booking ID;Room Revenue\nA1;1.234,56\nA2;99,00\n"

    table = open_table(content, "b.csv")

    assert table.headers == ["Booking ID", "Room Revenue"]
    assert cells(table) == [(2, ["A1", "1.234,56"]), (3, ["A2", "99,00"])]


def test_utf8_bom_is_removed_from_the_first_header() -> None:
    table = open_table(csv_bytes([HEADER, *ROWS], bom=True), "bookings.csv")

    assert table.headers[0] == "Booking ID"  # not "﻿Booking ID"


def test_windows_1252_is_read_when_the_file_is_not_utf8() -> None:
    content = csv_bytes(
        [["ID", "Città", "Tipologia"], ["1", "Perugia", "Camera Doppia à"]],
        delimiter=";",
        encoding="cp1252",
    )

    table = open_table(content, "bookings.csv")

    assert table.headers == ["ID", "Città", "Tipologia"]
    assert cells(table)[0][1][2] == "Camera Doppia à"


def test_the_profile_can_force_the_encoding() -> None:
    content = "ID;Nota\n1;caffè\n".encode("cp1252")

    table = open_table(content, "b.csv", FormatOptions(encoding="cp1252"))

    assert cells(table)[0][1] == ["1", "caffè"]


def test_a_utf16_file_is_reported_as_unreadable_not_misread() -> None:
    content = "ID;Nota\n1;x\n".encode("utf-16")

    assert refused(content, "b.csv") == BookingErrorCode.UNREADABLE_FILE


def test_excel_sep_hint_line_is_honoured_and_not_treated_as_data() -> None:
    content = b"sep=;\nBooking ID;Check-in\nA1;2026-07-10\n"

    table = open_table(content, "b.csv")

    assert table.headers == ["Booking ID", "Check-in"]
    assert [row.cells for row in table.rows()] == [["A1", "2026-07-10"]]


def test_fully_empty_rows_are_ignored_but_row_numbers_stay_true() -> None:
    content = b"ID,Amount\nA1,10\n\n,\n   ,  \nA2,20\n"

    table = open_table(content, "b.csv")

    assert cells(table) == [(2, ["A1", "10"]), (6, ["A2", "20"])]


def test_leading_blank_lines_before_the_header_are_skipped() -> None:
    table = open_table(b"\n\nID,Amount\nA1,10\n", "b.csv")

    assert table.headers == ["ID", "Amount"]
    assert cells(table) == [(4, ["A1", "10"])]


def test_short_rows_are_padded_and_extra_cells_ignored() -> None:
    table = open_table(b"A,B,C\n1,2\n1,2,3,4,5\n", "b.csv")

    assert cells(table) == [(2, ["1", "2", None]), (3, ["1", "2", "3"])]


def test_quoted_delimiters_and_multiline_fields_are_kept_intact() -> None:
    content = b'ID,Note,Amount\n1,"a, b",10\n2,"line1\nline2",20\n3,x,30\n'

    table = open_table(content, "b.csv")

    # Row numbers count records (as a spreadsheet does), not physical lines.
    assert [(n, c[0], c[2]) for n, c in cells(table)] == [
        (2, "1", "10"),
        (3, "2", "20"),
        (4, "3", "30"),
    ]


def test_cells_are_trimmed_and_empty_cells_are_none() -> None:
    table = open_table(b"A,B\n  x  ,\n", "b.csv")

    assert cells(table) == [(2, ["x", None])]


def test_trailing_delimiters_do_not_create_phantom_columns() -> None:
    table = open_table(b"A;B;\n1;2;\n", "b.csv")

    assert table.headers == ["A", "B"]


@pytest.mark.parametrize(
    "headers", [["ID", "Note", "Note"], ["ID", "Email", "email"], ["Check-in", "Check in", "X"]]
)
def test_duplicate_headers_are_rejected(headers: list[str]) -> None:
    assert (
        refused(csv_bytes([headers, ["1"] * len(headers)]), "b.csv")
        == BookingErrorCode.DUPLICATE_HEADER
    )


def test_blank_header_cells_are_not_duplicates() -> None:
    table = open_table(b"A,,B,,\n1,2,3,4,5\n", "b.csv")

    assert table.headers == ["A", "", "B"]


def test_a_headers_only_csv_has_no_data_rows() -> None:
    table = open_table(b"ID,Amount\n", "b.csv")

    assert cells(table) == []


def test_an_empty_file_is_reported() -> None:
    assert refused(b"", "b.csv") == BookingErrorCode.EMPTY_FILE
    assert refused(b"\n\n   \n", "b.csv") == BookingErrorCode.EMPTY_FILE


# --- file types and limits -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["b.xls", "b.xlsm", "b.ods", "b.txt", "b.pdf", "bookings", "b.csv.exe"]
)
def test_only_csv_and_xlsx_are_supported(name: str) -> None:
    assert refused(b"a,b\n1,2\n", name) == BookingErrorCode.UNSUPPORTED_FILE_TYPE


def test_extensions_are_case_insensitive() -> None:
    assert open_table(b"a,b\n1,2\n", "B.CSV").headers == ["a", "b"]
    assert open_table(xlsx_bytes({"S": [["a", "b"], [1, 2]]}), "B.XLSX").headers == ["a", "b"]


def test_a_workbook_renamed_to_csv_is_rejected() -> None:
    content = xlsx_bytes({"S": [["a"], [1]]})

    assert refused(content, "b.csv") == BookingErrorCode.UNSUPPORTED_FILE_TYPE


def test_a_non_workbook_named_xlsx_is_unreadable() -> None:
    assert refused(b"a,b\n1,2\n", "b.xlsx") == BookingErrorCode.UNREADABLE_FILE
    assert refused(b"PK\x03\x04 definitely not a zip", "b.xlsx") == BookingErrorCode.UNREADABLE_FILE


def test_files_over_the_size_limit_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsers, "MAX_FILE_BYTES", 10)

    assert refused(b"a,b\n1,2\n3,4\n", "b.csv") == BookingErrorCode.FILE_LIMIT_EXCEEDED


def test_files_over_the_row_limit_are_refused_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parsers, "MAX_ROWS", 2)

    assert refused(b"a\n1\n2\n3\n", "b.csv") == BookingErrorCode.FILE_LIMIT_EXCEEDED
    assert len(cells(open_table(b"a\n1\n2\n", "b.csv"))) == 2


def test_files_over_the_column_limit_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsers, "MAX_COLUMNS", 3)

    assert refused(b"a,b,c,d\n1,2,3,4\n", "b.csv") == BookingErrorCode.FILE_LIMIT_EXCEEDED


# --- XLSX (tests 27, 28, 29, 30) -------------------------------------------------------------


def test_xlsx_single_sheet_is_selected_automatically() -> None:
    content = xlsx_bytes({"Prenotazioni": [HEADER, *ROWS]})

    table = open_table(content, "bookings.xlsx")

    assert table.file_type == "xlsx"
    assert table.sheet_name == "Prenotazioni"
    assert table.headers == HEADER
    assert cells(table) == [(2, ROWS[0]), (3, ROWS[1])]


def test_xlsx_keeps_native_types_for_dates_and_numbers() -> None:
    content = xlsx_bytes(
        {
            "S": [
                ["ID", "Arrival", "Amount", "Rooms"],
                ["A1", dt.datetime(2026, 7, 10, 14, 30), 120.5, 2],
            ]
        }
    )

    row = cells(open_table(content, "b.xlsx"))[0][1]

    assert row == ["A1", dt.datetime(2026, 7, 10, 14, 30), 120.5, 2]


def test_xlsx_with_several_data_sheets_asks_for_a_choice() -> None:
    content = xlsx_bytes({"Prenotazioni": [HEADER, *ROWS], "Legenda": [["k", "v"], ["a", "b"]]})

    with pytest.raises(BookingImportError) as info:
        open_table(content, "b.xlsx")

    assert info.value.error_code == BookingErrorCode.MAPPING_REQUIRED
    assert info.value.details == {
        "reason": "sheet_selection_required",
        "sheet_names": ["Prenotazioni", "Legenda"],
    }


def test_the_profile_resolves_the_sheet_choice() -> None:
    content = xlsx_bytes({"Prenotazioni": [HEADER, *ROWS], "Legenda": [["k", "v"], ["a", "b"]]})

    table = open_table(content, "b.xlsx", FormatOptions(sheet_name="Legenda"))

    assert table.headers == ["k", "v"]


def test_a_configured_sheet_that_disappeared_means_the_schema_changed() -> None:
    content = xlsx_bytes({"Export": [HEADER, *ROWS]})

    with pytest.raises(BookingImportError) as info:
        open_table(content, "b.xlsx", FormatOptions(sheet_name="Prenotazioni"))

    assert info.value.error_code == BookingErrorCode.SOURCE_SCHEMA_CHANGED
    assert info.value.details is not None and info.value.details["reason"] == "sheet_not_found"


def test_hidden_and_empty_sheets_are_not_candidates() -> None:
    content = xlsx_bytes(
        {"Dati": [HEADER, *ROWS], "Tabelle": [["x"], [1]], "Vuoto": []}, hidden=["Tabelle"]
    )

    assert open_table(content, "b.xlsx").sheet_name == "Dati"


def test_xlsx_empty_rows_are_ignored_and_numbering_matches_excel() -> None:
    content = xlsx_bytes({"S": [[], [], ["ID", "Amount"], ["A1", 10], [], ["A2", 20]]})

    table = open_table(content, "b.xlsx")

    assert table.headers == ["ID", "Amount"]
    assert cells(table) == [(4, ["A1", 10]), (6, ["A2", 20])]


def test_xlsx_duplicate_headers_are_rejected() -> None:
    content = xlsx_bytes({"S": [["ID", "Note", "note"], ["1", "a", "b"]]})

    assert refused(content, "b.xlsx") == BookingErrorCode.DUPLICATE_HEADER


def test_xlsx_without_data_is_reported() -> None:
    assert refused(xlsx_bytes({"S": []}), "b.xlsx") == BookingErrorCode.EMPTY_FILE


def test_a_corrupt_workbook_is_unreadable() -> None:
    content = xlsx_bytes({"S": [["a"], [1]]})

    assert refused(content[: len(content) // 2], "b.xlsx") == BookingErrorCode.UNREADABLE_FILE

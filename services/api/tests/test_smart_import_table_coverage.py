"""A file is never read automatically while real data is left out of it.

Found by the AI readiness benchmark (PB-1): a workbook with one sheet per department, three of them
readable and the fourth with a header no rule could read, was offered as READY with 27 records of
36 - the fourth sheet silently dropped. The ranking of the tables picks the BEST one; it cannot
prove that the others are irrelevant. So when another table is real data of the kind chosen - it
sits on a sheet that holds data, has records enough to matter and fits the kind of data at least
half as well - the person is asked which table the file is (the TABLE question), however clear the
winner.

A summary, a dashboard, a legend, a hidden draft, an example of two rows, a decoy block, an empty
sheet or a table of another kind never counts: those files stay automatic, as before.

No database, no model, no network: real workbooks through the real understanding service.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.understanding_types import Question
from tests.hardening_support import LABOR, PEOPLE, level_of, question_kinds, understand

MONDAY = datetime(2026, 10, 19)
DEPARTMENTS = ("Reception", "Housekeeping", "Ristorante", "Manutenzione")
HEADER = ["Data", "Dipendente", "Ore previste", "Ore effettive"]
UNREADABLE = ["Colonna 9", "Dipendente", "Ore previste", "Ore effettive"]
RECORDS = 9


def _records(count: int = RECORDS) -> list[list[Any]]:
    return [[MONDAY + timedelta(days=i % 3), PEOPLE[i % len(PEOPLE)], 8, 7.5] for i in range(count)]


def _department_sheets(
    unreadable: Sequence[str] = (), names: Sequence[str] = DEPARTMENTS
) -> dict[str, list[list[Any]]]:
    return {name: [UNREADABLE if name in unreadable else HEADER, *_records()] for name in names}


def _workbook(sheets: Mapping[str, Sequence[Sequence[Any]]], hidden: Sequence[str] = ()) -> bytes:
    book = Workbook()
    first = book.active
    assert first is not None
    book.remove(first)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
        if name in hidden:
            sheet.sheet_state = "hidden"
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _table_question(inspection: FileInspection) -> Question | None:
    assert inspection.understanding is not None
    return next((q for q in inspection.understanding.questions if q.kind.value == "TABLE"), None)


def _records_read(inspection: FileInspection) -> int:
    assert inspection.understanding is not None
    table = inspection.understanding.document.table
    assert table is not None
    return table.data_rows


# --- PB-1: the sheet that was silently dropped ---


def test_the_control_four_readable_sheets_are_one_table_of_36_records_and_ready() -> None:
    inspection = understand(LABOR, _workbook(_department_sheets()))

    assert level_of(inspection) == "READY" and _table_question(inspection) is None
    assert _records_read(inspection) == 36


def test_three_readable_sheets_and_a_fourth_the_rules_cannot_read_are_not_ready() -> None:
    content = _workbook(_department_sheets(unreadable=["Reception"]))

    inspection = understand(LABOR, content)

    question = _table_question(inspection)
    assert question is not None, "27 of 36 records were read and nobody was asked"
    assert level_of(inspection) == "ASK"
    # what the file would be read as (27) against what is really in it (27 + 9 = 36)
    assert _records_read(inspection) == 27
    offered = {choice.count for choice in question.choices}
    assert offered == {27, 9} and sum(n for n in offered if n is not None) == 36
    sheets = sorted(sorted(choice.sheets) for choice in question.choices)
    assert sheets == [["Housekeeping", "Manutenzione", "Ristorante"], ["Reception"]]


@pytest.mark.parametrize("readable", [2, 3, 5])
def test_however_clear_the_winner_a_table_it_leaves_out_is_asked_about(readable: int) -> None:
    # 2 against 1 is already a "clear winner" (more than 1.6 times the value): the ranking is
    # not what decides whether the rest of the file is irrelevant
    names = [f"Reparto {i}" for i in range(readable)] + ["Reception"]
    content = _workbook(_department_sheets(unreadable=["Reception"], names=names))

    inspection = understand(LABOR, content)

    assert _table_question(inspection) is not None and level_of(inspection) == "ASK"


def test_the_person_choosing_the_winning_tables_is_a_decision_not_a_silent_loss() -> None:
    content = _workbook(_department_sheets(unreadable=["Reception"]))
    question = _table_question(understand(LABOR, content))
    assert question is not None
    winner = next(c for c in question.choices if len(c.sheets) == 3)

    decided = understand(LABOR, content, table_key=winner.value)

    assert _table_question(decided) is None and level_of(decided) == "READY"
    assert _records_read(decided) == 27  # the person saw 27 against 9 and said so


def test_the_person_can_choose_the_sheet_that_was_left_out() -> None:
    content = _workbook(_department_sheets(unreadable=["Reception"]))
    question = _table_question(understand(LABOR, content))
    assert question is not None
    left_out = next(c for c in question.choices if c.sheets == ("Reception",))

    decided = understand(LABOR, content, table_key=left_out.value)

    assert _table_question(decided) is None
    assert _records_read(decided) == 9


def test_two_comparable_sheets_one_of_them_unreadable_are_still_asked_about() -> None:
    # the cases the old rule already protected (the winner is not clear): they keep asking
    content = _workbook(_department_sheets(unreadable=["Ottobre"], names=["Ottobre", "Novembre"]))

    inspection = understand(LABOR, content)

    question = _table_question(inspection)
    assert question is not None and level_of(inspection) == "ASK"
    assert {c.count for c in question.choices} == {9}


# --- the legitimate leftovers stay automatic ---


def _same_as_without(
    extra: Mapping[str, Sequence[Sequence[Any]]], hidden: Sequence[str] = ()
) -> None:
    plain = understand(LABOR, _workbook(_department_sheets()))
    with_extra = understand(LABOR, _workbook({**_department_sheets(), **extra}, hidden))

    assert _table_question(with_extra) is None, "a legitimate leftover started a question"
    assert level_of(with_extra) == level_of(plain) == "READY"
    assert question_kinds(with_extra) == question_kinds(plain)
    assert _records_read(with_extra) == _records_read(plain) == 36


def test_a_summary_sheet_beside_the_detail_stays_automatic() -> None:
    _same_as_without(
        {
            "Riepilogo": [
                ["Reparto", "Ore totali"],
                *[[d, 80 + i] for i, d in enumerate(DEPARTMENTS)],
            ]
        }
    )


def test_a_dashboard_sheet_beside_the_data_stays_automatic() -> None:
    _same_as_without(
        {
            "Dashboard": [
                ["Indicatore", "Valore"],
                ["Ore previste totali", 288],
                ["Ore effettive totali", 270],
                ["Persone", 6],
                ["Reparti", 4],
                ["Settimana", 43],
            ]
        }
    )


def test_a_legend_sheet_beside_the_table_stays_automatic() -> None:
    _same_as_without(
        {
            "Legenda": [
                ["Sigla", "Significato"],
                ["M", "Mattina"],
                ["P", "Pomeriggio"],
                ["N", "Notte"],
                ["R", "Riposo"],
                ["F", "Ferie"],
            ]
        }
    )


def test_a_hidden_draft_of_the_data_stays_automatic() -> None:
    _same_as_without({"Bozza": [HEADER, *_records()]}, hidden=["Bozza"])


def test_an_empty_sheet_beside_the_data_stays_automatic() -> None:
    _same_as_without({"Vuoto": []})


def test_a_summary_named_sheet_with_a_table_as_long_as_the_data_stays_automatic() -> None:
    _same_as_without(
        {"Totale": [["Data", "Ore"], *[[MONDAY + timedelta(days=i), 8] for i in range(9)]]}
    )


DEPARTMENT_HEADER = ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"]


def _with_department(count: int) -> list[list[Any]]:
    return [
        [MONDAY + timedelta(days=i % 3), PEOPLE[i % len(PEOPLE)], DEPARTMENTS[i % 4], 8, 7.5]
        for i in range(count)
    ]


def _sheet_with_blocks(*blocks: Sequence[Sequence[Any]]) -> bytes:
    rows: list[list[Any]] = []
    for block in blocks:
        rows.extend(list(r) for r in block)
        rows.append([])
    return _workbook({"Turni": rows})


def test_an_example_table_above_the_real_one_stays_automatic() -> None:
    example = [["Esempio di compilazione"], DEPARTMENT_HEADER, *_with_department(2)]
    real = [["Turni della settimana"], DEPARTMENT_HEADER, *_with_department(15)]

    inspection = understand(LABOR, _sheet_with_blocks(example, real))

    assert _table_question(inspection) is None and level_of(inspection) == "READY"


def test_a_decoy_block_of_another_kind_above_the_real_table_stays_automatic() -> None:
    legend = [
        ["Legenda"],
        ["Sigla", "Significato"],
        ["M", "Mattina"],
        ["P", "Pomeriggio"],
        ["N", "Notte"],
    ]
    real = [["Turni della settimana"], DEPARTMENT_HEADER, *_with_department(15)]

    inspection = understand(LABOR, _sheet_with_blocks(legend, real))

    assert _table_question(inspection) is None and level_of(inspection) == "READY"


def test_a_table_of_another_kind_in_the_same_workbook_stays_automatic() -> None:
    # a second dataset in the workbook, as long as the first but not staff at all: not "left out
    # staff", just something else
    suppliers = [
        ["Fornitore", "Categoria", "Telefono"],
        *[[f"Fornitore {i}", "Alimentari", f"06 1234{i:03d}"] for i in range(9)],
    ]

    _same_as_without({"Fornitori": suppliers})

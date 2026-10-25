"""The gate every answer about a file passes before it leaves the server (Smart Import V3).

Personal data is first recognised column by column. This is the second line, and it is server-side:
whatever text an answer would show - an example value, a department word, a title, the name of a
sheet - is read once more and a personal value found in it is replaced, whatever put it there.
These tests check the gate by itself; `test_smart_import_hardening.py` checks it on whole files.
"""

import json

import pytest

from app.modules.data_sources.mapping_types import ColumnInfo, FileInspection
from app.modules.data_sources.understanding_redaction import redact_inspection
from app.modules.data_sources.understanding_types import (
    Choice,
    Detection,
    DocumentSummary,
    LabelCount,
    Origin,
    OriginKind,
    Question,
    QuestionKind,
    Recognized,
    SheetSummary,
    TableSummary,
    UnderstandingInfo,
    UnderstandingLevel,
)
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.redaction import MARK, PersonalDataGuard
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.value_text import split_weekday, strip_currency, weekday_agrees


@pytest.mark.parametrize(
    "text",
    [
        "scrivere a giulia.ferretti@example.org grazie",
        "Tel. +39 333 0001234",
        "0039 06 12345678",
        "chiamare 333 0001234 dopo le 18",
        "333-000-1234",
        "FRRGLI90Z41H501X",
        "frrgli90z41h501x",
        "IT60X0542811101000000123456",
        "IT60 X054 2811 1010 0000 0123 456",
        "DE89370400440532013000",
    ],
)
def test_the_things_that_are_personal_by_their_shape_are_replaced_wherever_they_are(
    text: str,
) -> None:
    cleaned = PersonalDataGuard().clean(text)

    assert MARK in cleaned
    for secret in ("example.org", "0001234", "12345678", "FRRGLI", "frrgli", "0542811", "0532013"):
        assert secret not in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "Fornitura energia elettrica - 09/2026",  # a month and a year are not a telephone number
        "2026-10-25",
        "25/10/2026",
        "1.234.567,89",
        "FT20260101234567",  # an invoice number is not an IBAN: its length is not any country's
        "FT/2026/0101",
        "Booking.com",
        "Reception",
        "BK-10001",
        "6 h",
    ],
)
def test_ordinary_text_of_a_hotel_is_left_alone(text: str) -> None:
    assert PersonalDataGuard().clean(text) == text


def test_the_names_of_the_columns_found_to_carry_people_are_removed_in_both_orders() -> None:
    guard = PersonalDataGuard.for_columns(
        [(PiiKind.PERSON_NAME, ["Giulia Ferretti", "Marco Rinaldi", "Giulia Ferretti"])]
    )

    assert guard.clean("Turni di Giulia Ferretti") == f"Turni di {MARK}"
    assert guard.clean("RINALDI MARCO e Giulia  Ferretti") == f"{MARK} e {MARK}"
    assert guard.clean("Giuliana Ferrettini") == "Giuliana Ferrettini"  # only whole words


def test_a_department_word_in_a_column_called_operatore_does_not_disappear() -> None:
    guard = PersonalDataGuard.for_columns(
        [(PiiKind.PERSON_NAME, ["Reception", "Cucina", "Giulia Ferretti"])]
    )

    assert guard.clean("Reception") == "Reception"
    assert guard.clean("Cucina e Giulia Ferretti") == f"Cucina e {MARK}"


def test_the_other_kinds_of_column_are_removed_as_written() -> None:
    guard = PersonalDataGuard.for_columns(
        [
            (PiiKind.EMAIL, ["g.f@example.org"]),
            (PiiKind.IBAN, ["IT00A0000000000000000000000"]),
        ]
    )

    assert guard.clean("g.f@example.org") == MARK
    assert guard.clean("IT00A0000000000000000000000") == MARK


def _inspection() -> FileInspection:
    info = UnderstandingInfo(
        level=UnderstandingLevel.ASK,
        detection=Detection("LABOR", "HIGH", (), "LABOR"),
        document=DocumentSummary(
            file_type="XLSX",
            sheets=(SheetSummary("Turni di Giulia Ferretti", "DATA", 20),),
            table=TableSummary(
                sheets=("Turni di Giulia Ferretti",),
                header_rows=(1,),
                first_row=2,
                last_row=20,
                data_rows=19,
                partition=False,
            ),
            title="Turni di Giulia Ferretti - tel +39 333 0001234",
        ),
        recognized=(
            Recognized(
                "role", Origin(OriginKind.COLUMN, "Reparto"), "HIGH", "mail g.f@example.org"
            ),
        ),
        questions=(
            Question(
                id="LABELS:role_mapping",
                kind=QuestionKind.VALUE_LABELS,
                document="role_mapping",
                labels=(LabelCount("Marco Rinaldi", 3), LabelCount("HK", 5)),
                choices=(
                    Choice("TABLE-KEY", title="Elenco di Marco Rinaldi", sheets=("Marco Rinaldi",)),
                ),
            ),
        ),
    )
    return FileInspection(
        DataSourceDomain.LABOR,
        file_type="XLSX",
        sheet_name="Turni di Giulia Ferretti",
        sheet_names=("Turni di Giulia Ferretti",),
        columns=(ColumnInfo(0, "Marco Rinaldi", ("Marco Rinaldi", "IT60X0542811101000000123456")),),
        understanding=info,
    )


def test_every_text_an_answer_shows_passes_the_gate_and_the_headers_do_not() -> None:
    guard = PersonalDataGuard.for_columns(
        [(PiiKind.PERSON_NAME, ["Giulia Ferretti", "Marco Rinaldi"])]
    )

    answer = redact_inspection(_inspection(), guard)

    shown = json.dumps(
        [
            answer.sheet_name,
            answer.sheet_names,
            answer.columns[0].examples,
            answer.understanding.document.title,  # type: ignore[union-attr]
            answer.understanding.document.sheets[0].name,  # type: ignore[union-attr]
            answer.understanding.document.table.sheets,  # type: ignore[union-attr]
            answer.understanding.recognized[0].example,  # type: ignore[union-attr]
            [label.label for label in answer.understanding.questions[0].labels],  # type: ignore[union-attr]
            answer.understanding.questions[0].choices[0].title,  # type: ignore[union-attr]
            answer.understanding.questions[0].choices[0].sheets,  # type: ignore[union-attr]
        ]
    )
    for secret in ("Ferretti", "Rinaldi", "0001234", "example.org", "0542811"):
        assert secret not in shown
    assert answer.understanding.questions[0].labels[1].label == "HK"  # type: ignore[union-attr]
    # what the import matches the file by is exactly as it was
    assert answer.columns[0].header == "Marco Rinaldi"
    assert answer.understanding.questions[0].id == "LABELS:role_mapping"  # type: ignore[union-attr]
    assert answer.understanding.questions[0].choices[0].value == "TABLE-KEY"  # type: ignore[union-attr]


# --- the two small readings of a cell's text the importers and the understanding share -----------


@pytest.mark.parametrize(
    ("text", "rest", "weekday"),
    [
        ("Lun 26/10/2026", "26/10/2026", 0),
        ("lun. 26/10/2026", "26/10/2026", 0),
        ("Martedì 27/10/2026", "27/10/2026", 1),
        ("martedi, 27/10/2026", "27/10/2026", 1),
        ("Fri 23/10/2026", "23/10/2026", 4),
        ("Sunday 25/10/2026 10:30", "25/10/2026 10:30", 6),
        ("26/10/2026", "26/10/2026", None),
        ("Mar Rosso 12/10", "Mar Rosso 12/10", None),  # not a weekday followed by a date
        ("Rosso 12/10/2026", "Rosso 12/10/2026", None),
    ],
)
def test_a_weekday_in_front_of_a_date_is_taken_away_and_remembered(
    text: str, rest: str, weekday: int | None
) -> None:
    assert split_weekday(text) == (rest, weekday)


def test_a_weekday_that_is_not_the_dates_weekday_is_not_accepted() -> None:
    from datetime import date

    thursday = date(2026, 10, 29)
    assert weekday_agrees(thursday, 3) and weekday_agrees(thursday, None)
    assert not weekday_agrees(thursday, 0)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("1.250,00 EUR", "1.250,00"),
        ("850 EUR", "850"),
        ("850 euro", "850"),
        ("850 €", "850"),
        ("€ 850", "850"),
        ("EUR 1.250,00", "1.250,00"),
        ("-€ 850", "-850"),
        ("1250.00", "1250.00"),
        ("850 USD", "850 USD"),  # another currency is NOT taken for euros
        ("$ 850", "$ 850"),
        ("12 europei", "12 europei"),
    ],
)
def test_the_hotels_currency_is_taken_away_from_an_amount_and_no_other(
    text: str, amount: str
) -> None:
    assert strip_currency(text) == amount

"""A header cell that IS a personal value must never reach the browser (ADV09).

A column is identified, all the way to the import, by its header. When a cell used as a header is an
e-mail address, a telephone number, a tax code or an IBAN, the page used to be sent that value twice
(the column and the decision). The fix is where the table's labels are made: such a header becomes
"Colonna X" there, so the answer, the decision the browser sends back and the import's own
reading of the file are the same safe word - with the model off and with it on - and nothing about
the column's position, its values or what the import finds in it is lost.
"""

import json
from io import BytesIO
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.ai.import_understanding.types import AiMode
from app.modules.bookings.parsers import open_table
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.observe import make_service, run
from tests.benchmarks.smart_import_v3.openai_intelligence import _truth, adversarial_docs
from tests.semantic_support import Behaviour, SemanticStandIn, semantic_service

PERSONAL = {
    "email": "mario.rossi@example.com",
    "phone": "+39 333 1234567",
    "mobile": "333 123 4567",
    "tax code": "RSSMRA80A01H501U",
    "iban": "IT60X0542811101000000123456",
    "labelled": "Tel. +39 333 1234567",
}
HEADER = [
    "Codice prenotazione",
    "Data prenotazione",
    "Arrivo",
    "Partenza",
    "Condizione",
    "Camere",
    "Ricavo camera",
    "Canale",
]


def workbook(extra_headers: list[str]) -> bytes:
    from datetime import datetime, timedelta

    book = Workbook()
    sheet = book.active
    sheet.title = "Prenotazioni"
    sheet.append([*HEADER, *extra_headers])
    for i in range(10):
        arrival = datetime(2026, 11, 2 + i)
        sheet.append(
            [
                f"RES-{2000 + i}",
                datetime(2026, 10, 1 + i),
                arrival,
                arrival + timedelta(days=2),
                "Confermata",
                1,
                120.0 + i,
                ("Booking.com", "Expedia", "Diretto", "Airbnb")[i % 4],
                *["x"] * len(extra_headers),
            ]
        )
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def answer(content: bytes, *, mode: AiMode | None = None) -> tuple[dict[str, Any], str]:
    """The exact JSON the browser would be sent, with the model off or on (a model that reads every
    column right, the kindest one)."""
    if mode is None:
        service = make_service()
    else:
        model = SemanticStandIn(Behaviour.ORACLE, {"Condizione": "status"})
        service = semantic_service(model, mode=mode)
    observed = run(service, "bookings", "file.xlsx", content)
    assert observed.error is None
    return json.loads(observed.payload), observed.payload


@pytest.mark.parametrize("kind", PERSONAL)
@pytest.mark.parametrize("mode", [None, AiMode.ASSIST])
def test_a_personal_value_used_as_a_header_never_reaches_the_browser(
    kind: str, mode: AiMode | None
) -> None:
    value = PERSONAL[kind]

    payload, text = answer(workbook([value]), mode=mode)

    assert value not in text
    assert "".join(value.split()) not in "".join(text.split())
    headers = [c["header"] for c in payload["columns"]]
    assert headers[-1] == "Colonna I"
    # the decision the browser sends back names the column by the same word
    assert [c["header"] for c in payload["proposal"]["columns"]][-1] == "Colonna I"


def test_adv09_of_the_adversarial_corpus_shows_no_personal_value_with_the_model_off_or_on(
    rules_engine: str,
) -> None:
    doc = next(d for d in adversarial_docs() if d.id.startswith("ADV09"))
    forbidden = doc.golden.pii_values

    off = run(make_service(), doc.card, doc.filename, doc.content)
    model = SemanticStandIn(Behaviour.ORACLE, _truth(doc), None, forbidden)
    on = run(semantic_service(model, mode=AiMode.ASSIST), doc.card, doc.filename, doc.content)

    for observed in (off, on):
        assert observed.error is None
        assert not any(value in observed.payload for value in forbidden)
    if rules_engine == "v3":
        assert model.calls >= 1  # V3 leaves a gap the model is asked about
    # V4 reads the file itself and may not ask the model at all: either way nothing personal went
    assert model.violations == []


def test_the_column_keeps_its_place_its_values_and_its_reading_in_the_import() -> None:
    content = workbook([PERSONAL["email"], PERSONAL["phone"]])
    service = make_service()
    inspection = service.understand(
        DataSourceDomain.BOOKINGS,
        "file.xlsx",
        content,
        UnderstandAnswers(),
        False,
        None,
        False,
        currency="EUR",
    )
    assert isinstance(inspection, FileInspection) and inspection.proposal is not None

    table = SmartImportService.read_table(content, "file.xlsx", None, inspection.proposal.layout)

    headers = [c.header for c in inspection.proposal.columns]
    assert headers[-2:] == ["Colonna I", "Colonna J"]  # unique, in their own places
    assert table.headers == headers  # what the import reads is what the decision names
    first = next(iter(table.rows()))
    assert first.cells[-1] == "x" and len(first.cells) == len(headers)


def test_the_plain_reader_gives_the_same_safe_word() -> None:
    csv = b"Codice,Telefono,Mail\nA1,x,y\n".replace(b"Mail", PERSONAL["email"].encode())

    table = open_table(csv, "file.csv")

    assert table.headers == ["Codice", "Telefono", "Colonna C"]
    assert next(iter(table.rows())).cells == ["A1", "x", "y"]


@pytest.mark.parametrize(
    "header",
    [
        "Data 09/2026",
        "Lun 02/11",
        "Check-in",
        "Ricavo (EUR)",
        "ID-12345",
        "Telefono ospite",
        "Email",
        "Notti",
        "Camere vendute",
    ],
)
def test_an_ordinary_header_is_not_touched(header: str) -> None:
    payload, _ = answer(workbook([header]))

    assert [c["header"] for c in payload["columns"]][-1] == header

"""A reading that changes nothing is neither applied nor asked about (V1.1, any model).

With the real model, 8 challenge files whose "rooms" column the rules could not name became a
question for the person - and the column held "1" in every row, which is exactly what the import
assumes when the column is absent. Asking cost a person a click and protected nothing. The rule
knows no model: ignoring a reading is safe when (a) the field is descriptive - stored, read by
no measure - or (b) the field has an assumed value and the column says exactly that, in every row.
One row that says something else, and the question is back.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.ai.import_understanding.types import AiMode, AiTrace
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.proposal import ColumnProposal
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.understanding_ai import is_immaterial
from app.modules.document_understanding.stats import column_stats
from app.modules.ingestion.models import DataSourceDomain
from tests.semantic_support import Behaviour, SemanticStandIn, outline, understand_semantic

DEFAULTS = {"rooms": 1}


def column(values: list[Any]) -> ColumnProposal:
    @dataclass
    class Stub:  # only what `is_immaterial` reads
        stats: Any

    return Stub(column_stats(values))  # type: ignore[return-value]


def test_a_descriptive_field_is_always_immaterial() -> None:
    for field in ("guests", "room_type", "rate_plan"):
        assert is_immaterial(column(["a", "b", "c"]), field, BOOKINGS, DEFAULTS)


def test_the_assumed_value_is_immaterial_only_when_every_row_says_it() -> None:
    assert is_immaterial(column([1, 1, 1, 1]), "rooms", BOOKINGS, DEFAULTS)
    assert is_immaterial(column(["1", "1", "1"]), "rooms", BOOKINGS, DEFAULTS)
    assert not is_immaterial(column([1, 1, 1, 2]), "rooms", BOOKINGS, DEFAULTS)
    assert not is_immaterial(column([2, 2, 2]), "rooms", BOOKINGS, DEFAULTS)
    assert not is_immaterial(column([1, 1]), "rooms", BOOKINGS, DEFAULTS)  # too few to say
    assert not is_immaterial(column([1, 1, "x"]), "rooms", BOOKINGS, DEFAULTS)


@pytest.mark.parametrize(
    "field",
    [
        # required, money, a pair, proved by a vocabulary, read by an analysis: never immaterial
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "status",
        "channel",
        "room_revenue",
        "total_revenue",
        "commission_amount",
        "cancelled_at",
    ],
)
def test_nothing_that_matters_is_ever_immaterial(field: str) -> None:
    assert not is_immaterial(column([1, 1, 1, 1]), field, BOOKINGS, DEFAULTS)
    assert field not in BOOKINGS.descriptive


def test_the_other_kinds_of_data_declare_no_descriptive_field() -> None:
    assert COSTS.descriptive == frozenset()


# --- through the real service --------------------------------------------------------------------
# The status column is called "Condizione", a word NINFA's rules do not know: the file is not READY,
# so the model IS asked - and it reads the rooms column (and more) as well.

HEADER = [
    "Codice prenotazione",
    "Data prenotazione",
    "Arrivo",
    "Partenza",
    "Condizione",
    "Num. unita",
    "Ricavo camera",
    "Canale",
]
STATUS = {"Condizione": "status"}


def bookings(
    rooms: list[Any], extra: tuple[str, list[Any]] | None = None, *, known_status: bool = False
) -> bytes:
    header = ["Stato" if known_status and h == "Condizione" else h for h in HEADER]
    book = Workbook()
    sheet = book.active
    sheet.title = "Prenotazioni"
    sheet.append([*header, *([extra[0]] if extra else [])])
    for i, count in enumerate(rooms):
        arrival = datetime(2026, 11, 2 + i)
        sheet.append(
            [
                f"RES-{2000 + i}",
                datetime(2026, 10, 1 + i),
                arrival,
                arrival + timedelta(days=2),
                "Confermata",
                count,
                120.0 + i,
                ("Booking.com", "Expedia", "Diretto", "Airbnb")[i % 4],
                *([extra[1][i]] if extra else []),
            ]
        )
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def read(
    content: bytes, truth: dict[str, str], *, mode: AiMode = AiMode.ASSIST
) -> tuple[FileInspection, SemanticStandIn, list[AiTrace]]:
    traces: list[AiTrace] = []
    model = SemanticStandIn(Behaviour.ORACLE, truth)
    inspection = understand_semantic(
        model,
        DataSourceDomain.BOOKINGS,
        content,
        mode=mode,
        vocabulary_certainty=False,  # production
        observer=traces.append,
    )
    return inspection, model, traces


def asked(inspection: Any) -> list[str]:
    assert inspection.understanding is not None
    return sorted(q.id for q in inspection.understanding.questions)


@pytest.mark.usefixtures("rules_engine")
@pytest.mark.rules_v3_only
def test_a_rooms_column_that_says_what_the_import_assumes_asks_nothing() -> None:
    inspection, model, traces = read(bookings([1] * 10), {**STATUS, "Num. unita": "rooms"})

    assert model.calls == 1  # the model was asked (nobody knows "Condizione") and answered
    # the status is a question; the rooms are not: "1" in every row is what the import assumes
    assert asked(inspection) == ["CONFIRM:Condizione"]
    assert traces[0].ignored == 1 and traces[0].suggested == 1
    assert all(field != "rooms" for _h, field, _l in outline(inspection)["columns"])


@pytest.mark.usefixtures("rules_engine")
@pytest.mark.rules_v3_only
def test_one_booking_of_two_rooms_brings_the_question_back() -> None:
    inspection, _model, traces = read(
        bookings([1, 1, 1, 2, 1, 1, 1, 1]), {**STATUS, "Num. unita": "rooms"}
    )

    assert asked(inspection) == ["CONFIRM:Condizione", "CONFIRM:Num. unita"]
    assert traces[0].ignored == 0 and traces[0].suggested == 2


@pytest.mark.usefixtures("rules_engine")
@pytest.mark.rules_v3_only
def test_a_descriptive_column_named_by_a_model_is_set_aside_quietly() -> None:
    content = bookings([1] * 10, extra=("Sistemazione", ["Doppia", "Singola"] * 5))
    truth = {**STATUS, "Num. unita": "rooms", "Sistemazione": "room_type"}

    inspection, model, traces = read(content, truth)

    assert model.calls == 1
    assert asked(inspection) == ["CONFIRM:Condizione"]
    assert traces[0].ignored == 2  # the rooms of one, the room type of the other
    assert all(field != "room_type" for _h, field, _l in outline(inspection)["columns"])


def test_the_rule_is_the_same_in_shadow_where_nothing_is_applied_anyway() -> None:
    inspection, _model, traces = read(
        bookings([1] * 10), {**STATUS, "Num. unita": "rooms"}, mode=AiMode.SHADOW
    )

    rules_only = understand_semantic(None, DataSourceDomain.BOOKINGS, bookings([1] * 10))
    assert outline(inspection) == outline(rules_only)  # SHADOW: the answer is the rules' own
    assert traces[0].ignored == 1


# --- the other half of the same economy: no question for a model that cannot change the answer --


def test_a_file_the_rules_already_read_as_ready_is_not_asked_about() -> None:
    content = bookings([1] * 10, known_status=True)
    # (rooms in a header the rules do not know, everything else known: the rules read it as READY
    # because the import assumes one room per row)
    rules_only = understand_semantic(None, DataSourceDomain.BOOKINGS, content)
    traces: list[AiTrace] = []
    model = SemanticStandIn(Behaviour.ORACLE, {"Num. unita": "rooms"})

    inspection = understand_semantic(
        model,
        DataSourceDomain.BOOKINGS,
        content,
        mode=AiMode.ASSIST,
        vocabulary_certainty=False,
        observer=traces.append,
    )

    assert outline(rules_only)["level"] == "READY"
    assert model.calls == 0 and traces == []
    assert outline(inspection) == outline(rules_only)


def test_a_file_that_cannot_be_imported_for_a_reason_no_name_lifts_is_not_asked_about() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Prenotazioni"
    sheet.append(HEADER)  # a header and not one row of data
    out = BytesIO()
    book.save(out)
    model = SemanticStandIn(Behaviour.ORACLE, {})

    inspection = understand_semantic(
        model, DataSourceDomain.BOOKINGS, out.getvalue(), mode=AiMode.ASSIST
    )

    assert inspection.understanding is not None
    assert inspection.understanding.level.value == "BLOCKED"
    assert model.calls == 0

"""What `assisted_fields` is, and what it can never be.

When a model helps to read a column and NINFA's own vocabulary proves it, the decision records the
name (`{"Condizione": "status"}`) in the answers it was made with, so the server can read the file
the same way WITHOUT any model. Six guarantees, each one tested here:

1. it records only what was already validated: no suggestion, no doubt, no failure ever lands in it;
2. it is not an authority above what a person confirmed (an answer, Source Learning);
3. the server can re-verify it with no model, and gets the very same decision;
4. a mapping that is no longer true of the file cannot be replayed;
5. it holds no personal data, and a forged one cannot place a personal-data column;
6. it has nothing to do with FULL / PARTIAL / DELTA or with what the memory learns.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.ai.import_understanding.types import AiMode
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.source_learning import Via
from app.modules.data_sources.understanding import UnderstandAnswers, confirmation_from
from app.modules.ingestion.models import DataSourceDomain
from tests.semantic_support import Behaviour, SemanticStandIn, outline, understand_semantic
from tests.test_smart_import_ai_pipeline import (
    BOOKINGS,
    GUESTS,
    TRUTH_STATUS,
    bookings,
    header_of,
    rows_of,
    table,
)

STATUS_UNKNOWN = bookings(status="Condizione")
_APP = Path(__file__).resolve().parents[1] / "app"


def assisted_run(
    behaviour: Behaviour = Behaviour.ORACLE,
    content: bytes = STATUS_UNKNOWN,
    truth: dict[str, str] | None = None,
    # this file IS the mechanism ADR 0052 withdrew: on, and explicitly
    vocabulary_certainty: bool = True,
    **kwargs: Any,
) -> FileInspection:
    provider = SemanticStandIn(behaviour, truth if truth is not None else TRUTH_STATUS)
    return understand_semantic(
        provider, BOOKINGS, content, vocabulary_certainty=vocabulary_certainty, **kwargs
    )


def mapping(result: dict[str, Any]) -> dict[str, Any]:
    """What was read, without the reference that echoes the answers it was made with."""
    shown = dict(result)
    shown["proposal"] = {k: v for k, v in (result["proposal"] or {}).items() if k != "smart_import"}
    return shown


def recorded(inspection: FileInspection) -> dict[str, str]:
    assert inspection.proposal is not None
    reference = inspection.proposal.smart_import
    return {} if reference is None else dict(reference.answers.get("assisted_fields", {}))


# --- 1. only what was already validated ---


def test_a_certain_column_is_recorded_and_nothing_else_is() -> None:
    inspection = assisted_run()

    assert recorded(inspection) == {"Condizione": "status"}
    assert inspection.proposal is not None and inspection.proposal.smart_import is not None
    # the rest of what the decision says it was made with is what the person said, as ever
    assert set(inspection.proposal.smart_import.answers) == {"assisted_fields"}


@pytest.mark.parametrize(
    "behaviour",
    [
        Behaviour.WRONG,
        Behaviour.LOW,
        Behaviour.UNKNOWN,
        Behaviour.AMBIGUOUS,
        Behaviour.ASKS_PERSON,
        Behaviour.HEADER_SUSPECT,
        Behaviour.FLAGS_INJECTION,
        Behaviour.OBEYS_INJECTION,
        Behaviour.ANOTHER_KIND,
        Behaviour.INVENTS_FIELD,
        Behaviour.GARBAGE,
        Behaviour.TIMEOUT,
        Behaviour.REFUSES,
    ],
)
def test_no_suggestion_no_doubt_and_no_failure_is_ever_recorded(behaviour: Behaviour) -> None:
    assert recorded(assisted_run(behaviour)) == {}


def test_a_reading_that_is_only_a_suggestion_is_not_recorded() -> None:
    assert recorded(assisted_run(corroborate=False)) == {}


def test_in_shadow_nothing_is_recorded_because_nothing_is_applied() -> None:
    assert recorded(assisted_run(mode=AiMode.SHADOW)) == {}


def test_a_column_the_values_do_not_prove_is_not_recorded() -> None:
    body = rows_of(status=("Alfa", "Beta", "Gamma", "Delta"))
    content = table(header_of(status="Condizione"), body)

    assert recorded(assisted_run(content=content)) == {}


# --- 2. not an authority above a person ---


def test_a_recorded_name_never_overrides_what_the_person_confirmed() -> None:
    # the person says the column is the channel; a (forged or old) record says it is the status
    result = outline(
        understand_semantic(
            None,
            BOOKINGS,
            STATUS_UNKNOWN,
            column_fields={"Condizione": "channel"},
            assisted_fields={"Condizione": "status"},
        )
    )

    fields = {header: field for header, field, _ in result["columns"]}
    assert fields["Condizione"] == "channel"


def test_a_recorded_name_does_not_take_a_field_another_column_already_has() -> None:
    result = outline(
        understand_semantic(
            None, BOOKINGS, STATUS_UNKNOWN, assisted_fields={"Condizione": "channel"}
        )
    )

    fields = [field for _, field, _ in result["columns"]]
    assert fields.count("channel") == 1  # the column the rules read, never doubled


# --- 3. re-verified with no model, to the very same decision ---


def test_the_server_reads_it_again_without_a_model_and_gets_the_same_decision() -> None:
    first = assisted_run()
    assert first.proposal is not None and first.proposal.smart_import is not None
    answers = dict(first.proposal.smart_import.answers)

    again = understand_semantic(None, BOOKINGS, STATUS_UNKNOWN, **answers)

    assert again.understanding is not None and first.understanding is not None
    assert again.understanding.level.value == first.understanding.level.value == "READY"
    assert again.understanding.questions == () and again.understanding.blockers == ()
    assert again.proposal is not None
    assert again.proposal.model_dump(exclude={"smart_import"}) == first.proposal.model_dump(
        exclude={"smart_import"}
    )


def test_the_record_is_checked_against_the_file_every_time() -> None:
    answers: dict[str, Any] = {"assisted_fields": {"Condizione": "status"}}

    result = outline(understand_semantic(None, BOOKINGS, STATUS_UNKNOWN, **answers))

    # nothing the client says is believed beyond the name: the values prove it, here they do
    assert result["level"] == "READY"
    unproved = table(header_of(status="Condizione"), rows_of(status=("Alfa", "Beta", "Gamma")))
    assert outline(understand_semantic(None, BOOKINGS, unproved, **answers))["level"] != "READY"


# --- 4. no replay of a mapping that is no longer true ---


def test_a_record_cannot_be_replayed_on_a_file_whose_column_changed() -> None:
    answers: dict[str, Any] = {"assisted_fields": {"Condizione": "status"}}
    numbers = rows_of()
    for index, row in enumerate(numbers):
        row[4] = 100 + index  # the "status" column now holds numbers
    channels = rows_of(status=("Booking.com", "Expedia", "Diretto", "Airbnb"))  # ...or channels

    for body in (numbers, channels):
        content = table(header_of(status="Condizione"), body)

        result = outline(understand_semantic(None, BOOKINGS, content, **answers))

        assert result["level"] != "READY"
        assert ("Condizione", "status", "RECOGNIZED") not in result["columns"]


def test_a_record_for_a_column_that_is_gone_places_nothing() -> None:
    answers: dict[str, Any] = {"assisted_fields": {"Condizione": "status"}}
    renamed = bookings(status="Altra cosa")

    result = outline(understand_semantic(None, BOOKINGS, renamed, **answers))

    assert mapping(result) == mapping(outline(understand_semantic(None, BOOKINGS, renamed)))


# --- 5. nothing personal, and a forged record places nothing it should not ---


def test_a_forged_record_cannot_place_money_a_date_a_count_or_an_identifier() -> None:
    forgeries: list[tuple[bytes, dict[str, str]]] = [
        (bookings(revenue="Corrispettivo"), {"Corrispettivo": "room_revenue"}),
        (bookings(**{"in": "Colonna 3", "out": "Colonna 4"}), {"Colonna 3": "check_in"}),
        (bookings(rooms="Unita", status="Condizione"), {"Unita": "rooms"}),
        (bookings(code="Chiave 9", status="Condizione"), {"Chiave 9": "source_record_id"}),
    ]
    for content, forged in forgeries:
        honest = outline(understand_semantic(None, BOOKINGS, content))

        result = outline(understand_semantic(None, BOOKINGS, content, assisted_fields=forged))

        assert mapping(result) == mapping(honest), forged


def test_a_forged_record_cannot_place_a_column_of_personal_data() -> None:
    header = [*header_of(status="Condizione"), "Ospite", "Email ospite"]
    body = [[*row, *GUESTS[i % len(GUESTS)][:2]] for i, row in enumerate(rows_of(9))]
    content = table(header, body)

    result = outline(
        understand_semantic(
            None, BOOKINGS, content, assisted_fields={"Ospite": "status", "Email ospite": "channel"}
        )
    )

    fields = {header: field for header, field, _ in result["columns"]}
    assert fields["Ospite"] is None and fields["Email ospite"] is None


def test_what_is_recorded_holds_no_value_of_a_personal_column() -> None:
    header = [*header_of(status="Condizione"), "Ospite", "Email ospite", "Telefono ospite"]
    body = [[*row, *GUESTS[i % len(GUESTS)][:3]] for i, row in enumerate(rows_of(9))]
    inspection = assisted_run(content=table(header, body))

    assert recorded(inspection) == {"Condizione": "status"}
    assert inspection.proposal is not None and inspection.proposal.smart_import is not None
    text = json.dumps(inspection.proposal.smart_import.model_dump(mode="json"))
    for guest in GUESTS:
        for value in guest[:3]:
            assert value not in text


# --- 6. nothing to do with scope or with what the memory learns ---


def test_a_record_never_says_anything_about_what_the_file_is() -> None:
    inspection = assisted_run()

    assert inspection.proposal is not None
    assert inspection.proposal.file_scope is None
    assert inspection.proposal.expected_removals == 0
    assert inspection.proposal.remembered_file_scope is None


def test_a_record_confirms_nothing_to_the_memory() -> None:
    answers = UnderstandAnswers(assisted_fields={"Condizione": "status"})

    confirmation = confirmation_from(answers, None)

    assert confirmation.origin == Via.ENGINE  # it cannot teach: only a person's word does
    assert not confirmation.classified


def test_the_record_is_read_by_nothing_that_decides_scope_or_teaches() -> None:
    allowed = {"understanding.py", "understanding_ai.py"}
    readers = sorted(
        str(path.relative_to(_APP))
        for path in _APP.rglob("*.py")
        if "assisted_fields" in path.read_text(encoding="utf-8") and path.name not in allowed
    )

    assert readers == []


def test_the_domain_is_still_the_one_the_person_chose() -> None:
    # a record is about a column, never about the kind of data
    inspection = assisted_run()

    assert inspection.domain == DataSourceDomain.BOOKINGS

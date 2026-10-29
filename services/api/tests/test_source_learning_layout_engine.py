"""Source Learning, how a family is READ: the layout hints that belong to ONE family.

Pure functions, no database. Which sheets to read, the hours of a day grid and where the department
comes from describe how to read THAT structure - not the property, not the kind of data, and not
whichever family happened to be imported last. They are remembered with the family and given back
only once a file has been recognised as it.
"""

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.modules.data_sources.source_learning import (
    PERSONAL,
    Learning,
    Memory,
    Trust,
    Via,
    fingerprint_of,
    layout_hints,
    parse_learning,
    parse_memory,
    remember,
    remember_in,
    safe_layout,
    stored_learning,
    within_shape,
)
from app.modules.document_understanding.layout import LayoutSpec

DOMAIN = "BOOKINGS"
SHAPE = [("codice", "TEXT"), ("dal", "DATE"), ("al", "DATE")]
MAPPED = {"source_record_id": "codice", "check_in": "dal", "check_out": "al"}
GRID = {"grid": {"hours_field": "planned_hours"}}
SHEET = {"sheets": ["Prenotazioni"]}


def memory(layout: dict[str, Any] | None = None, *, family_id: str = "1") -> Memory:
    return Memory(
        trust=Trust.PERSON,
        origin=Via.ANSWERS,
        domain=DOMAIN,
        shape=SHAPE,
        mapped=MAPPED,
        person=dict(MAPPED),
        fingerprint=fingerprint_of(DOMAIN, SHAPE, MAPPED),
        id=family_id,
        touched=1,
        layout=layout,
    )


def learn(
    learning: Learning | None,
    shape: Sequence[tuple[str, str]],
    mapped: dict[str, str],
    layout: dict[str, Any] | None,
    *,
    family_id: str | None = None,
    origin: Via = Via.ANSWERS,
) -> Learning:
    result = remember_in(
        learning,
        family=family_id,
        domain=DOMAIN,
        shape=shape,
        mapped=mapped,
        person=dict(mapped),
        answers={},
        origin=origin,
        layout=layout,
    )
    assert result is not None
    return result


# --- what is worth remembering ---


def test_the_layout_of_a_family_keeps_only_how_it_is_read_never_a_date_or_a_table() -> None:
    raw = {
        "sheets": ["Prenotazioni"],
        "table_key": "Prenotazioni#4",  # the row numbers of THAT file
        "period_start": "2026-10-26",  # the week of THAT file
        "department": {"kind": "TITLE"},
        "grid": {"hours_field": "planned_hours"},
    }

    kept = safe_layout(raw)

    assert kept == {
        "sheets": ["Prenotazioni"],
        "department": {"kind": "TITLE"},
        "grid": {"hours_field": "planned_hours"},
    }


def test_a_layout_with_nothing_special_is_remembered_as_such_not_as_unknown() -> None:
    assert safe_layout({}) == {}  # "read it with the layout reader" is something
    assert safe_layout(None) is None  # nothing known


@pytest.mark.parametrize(
    "raw",
    [{"grid": {"hours_field": "nope"}}, {"sheets": "Prenotazioni"}, {"unknown": 1}, "text"],
)
def test_a_layout_that_cannot_be_read_is_not_remembered(raw: Any) -> None:
    assert safe_layout(raw) is None


@pytest.mark.parametrize(
    "name",
    ["Mario Rossi", "Rossi Giulia", "mario.rossi@example.com", "Export 20261030123456"],
)
def test_a_sheet_that_names_a_person_an_address_or_a_number_is_never_remembered(name: str) -> None:
    kept = safe_layout({"sheets": ["Prenotazioni", name], "grid": {"hours_field": "actual_hours"}})

    assert kept == {"grid": {"hours_field": "actual_hours"}}  # no sheet at all: nothing to leak
    assert name.casefold() not in json.dumps(kept).casefold()


@pytest.mark.parametrize(
    "name", ["Prenotazioni", "Export", "Turni Reception", "Foglio1", "Ottobre"]
)
def test_the_sheets_that_say_what_they_are_are_remembered(name: str) -> None:
    assert safe_layout({"sheets": [name]}) == {"sheets": [name]}


# --- what a family gives back ---


def test_a_family_gives_back_its_own_hints() -> None:
    hints = layout_hints(memory({**SHEET, **GRID}), None, LayoutSpec())

    assert hints is not None and hints.sheets == ["Prenotazioni"]
    assert hints.grid is not None and hints.grid.hours_field == "planned_hours"


def test_a_family_without_hints_does_not_inherit_the_layout_of_the_last_import() -> None:
    last_import = LayoutSpec(sheets=["Export"])
    store = Learning(
        seq=2, current="2", families=[memory(None, family_id="1"), memory(None, family_id="2")]
    )

    assert (
        layout_hints(store.families[0], store, last_import) is None
    )  # family 1 is not the last import


def test_a_family_remembered_before_layouts_were_gets_the_profile_layout_only_if_it_wrote_it() -> (
    None
):
    profile_layout = LayoutSpec.model_validate({**SHEET, "period_start": "2026-10-26"})
    store = Learning(
        seq=2, current="2", families=[memory(None, family_id="1"), memory(None, family_id="2")]
    )

    hints = layout_hints(store.families[1], store, profile_layout)

    assert hints is not None and hints.sheets == ["Prenotazioni"]
    assert hints.period_start is None  # a week is never inherited


def test_a_damaged_hint_is_no_hint_and_does_not_harm_the_other_families() -> None:
    broken = memory({"grid": {"hours_field": "nope"}}, family_id="1")
    fine = memory(SHEET, family_id="2")
    store = Learning(seq=2, current="2", families=[broken, fine])

    assert layout_hints(broken, store, None) is None
    hints = layout_hints(fine, store, None)
    assert hints is not None and hints.sheets == ["Prenotazioni"]


def test_no_family_no_hints() -> None:
    assert layout_hints(None, None, LayoutSpec(sheets=["Export"])) is None


def test_a_hint_that_is_not_even_json_makes_the_family_unreadable_not_the_source() -> None:
    raw = stored_learning(
        Learning(
            seq=2, current="1", families=[memory(SHEET, family_id="1"), memory(GRID, family_id="2")]
        )
    )
    raw["families"][0]["layout"] = "garbage"  # not an object

    learning = parse_learning(raw)

    assert learning is not None and [m.id for m in learning.families] == ["2"]
    assert parse_memory(raw["families"][0]) is None


# --- the matching restricted to the file as it is ---


def test_a_column_a_layout_adds_is_not_part_of_the_structure() -> None:
    shape = [(PERSONAL, "TEXT"), ("reparto", "TEXT")]
    mapped = {"role": "reparto", "work_date": "data", "planned_hours": "ore previste"}

    assert within_shape(mapped, shape) == {
        "role": "reparto"
    }  # the date and the hours are the grid's


def test_a_plain_structure_keeps_every_mapped_column() -> None:
    assert within_shape(MAPPED, SHAPE) == MAPPED


def test_a_personal_placeholder_is_never_a_mapped_column() -> None:
    shape = [(PERSONAL, "TEXT"), ("dal", "DATE")]

    assert within_shape({"guest_name": "~", "check_in": "dal"}, shape) == {"check_in": "dal"}


# --- remembering how a family is read ---


def test_the_layout_is_learned_with_the_family() -> None:
    learning = learn(None, SHAPE, MAPPED, SHEET)

    assert learning.families[0].layout == SHEET


def test_the_same_layout_confirmed_again_is_not_a_revision() -> None:
    first = learn(None, SHAPE, MAPPED, SHEET)

    again = learn(first, SHAPE, MAPPED, SHEET, family_id=first.families[0].id)

    assert again.families[0].revision == 1 and again.families[0].history == []


def test_a_changed_layout_is_a_revision_and_the_old_layout_stays_in_the_history() -> None:
    first = learn(None, SHAPE, MAPPED, SHEET)

    after = learn(first, SHAPE, MAPPED, {"sheets": ["Storico"]}, family_id=first.families[0].id)

    family = after.families[0]
    assert family.revision == 2 and family.layout == {"sheets": ["Storico"]}
    assert family.history[0]["layout"] == SHEET  # the old way of reading it is not rewritten
    assert len(after.families) == 1  # a change of layout is not a new family


def test_a_family_remembered_before_layouts_learns_its_layout_without_a_revision() -> None:
    old = memory(None)

    updated = remember(
        old,
        domain=DOMAIN,
        shape=SHAPE,
        mapped=MAPPED,
        person=dict(MAPPED),
        answers={},
        origin=Via.ANSWERS,
        layout=GRID,
    )

    assert updated is not None and updated.layout == GRID and updated.revision == 1


def test_a_decision_with_no_layout_does_not_forget_the_one_the_family_has() -> None:
    old = memory(SHEET)

    updated = remember(
        old,
        domain=DOMAIN,
        shape=SHAPE,
        mapped=MAPPED,
        person=dict(MAPPED),
        answers={},
        origin=Via.ANSWERS,
        layout=None,
    )

    assert updated is not None and updated.layout == SHEET


def test_confirming_a_family_from_a_csv_does_not_forget_the_sheet_chosen_for_its_xlsx() -> None:
    first = learn(None, SHAPE, MAPPED, SHEET)

    after = learn(first, SHAPE, MAPPED, {}, family_id=first.families[0].id)  # a csv: no sheets

    assert after.families[0].layout == SHEET
    assert after.families[0].revision == 1  # nothing changed about how the xlsx is read


def test_a_new_sheet_chosen_for_the_family_replaces_the_old_one() -> None:
    first = learn(None, SHAPE, MAPPED, SHEET)

    after = learn(first, SHAPE, MAPPED, {"sheets": ["Storico"]}, family_id=first.families[0].id)

    assert after.families[0].layout == {"sheets": ["Storico"]}


def test_a_layout_correction_in_one_family_does_not_touch_another() -> None:
    other_shape = [("rif", "TEXT"), ("emessa", "DATE"), ("netto", "NUMBER")]
    other_mapped = {"source_record_id": "rif", "booked_at": "emessa", "room_revenue": "netto"}
    both = learn(learn(None, SHAPE, MAPPED, SHEET), other_shape, other_mapped, GRID)
    first, second = both.families
    assert (first.layout, second.layout) == (SHEET, GRID)

    after = learn(both, SHAPE, MAPPED, {"sheets": ["Storico"]}, family_id=first.id)

    by_id = {m.id: m for m in after.families}
    assert by_id[first.id].layout == {"sheets": ["Storico"]}
    assert by_id[second.id].model_dump() == second.model_dump()  # exactly as it was


def test_a_reused_decision_leaves_the_layout_as_it_is() -> None:
    first = learn(None, SHAPE, MAPPED, SHEET)

    after = remember_in(
        first,
        family=first.families[0].id,
        domain=DOMAIN,
        shape=SHAPE,
        mapped=MAPPED,
        person={},
        answers={},
        origin=Via.REUSE,
        layout={"sheets": ["Other"]},
    )

    assert after is not None and after.families[0].layout == SHEET


def test_the_stored_family_holds_no_file_name_and_no_person() -> None:
    learning = learn(None, SHAPE, MAPPED, safe_layout({"sheets": ["Mario Rossi"], **GRID}))

    blob = json.dumps(stored_learning(learning), ensure_ascii=False).casefold()

    for fragment in ("rossi", "mario", ".xlsx", ".csv"):
        assert fragment not in blob
    assert learning.families[0].layout == GRID

"""Source Learning, the engine: what a remembered source says about the file in front of us.

Pure functions, no database: a memory (what a person confirmed about a source), the columns of a new
file as the engine reads them alone, and the verdict - how much of the source is still there
(`Drift`), what may be reused (`proven`), and why not (`conflicts`). A memory is evidence, never
authority: the current document wins.
"""

from collections.abc import Callable

import pytest

from app.modules.data_sources.source_learning import (
    HISTORY_KEPT,
    PERSONAL,
    ColumnView,
    Drift,
    Memory,
    SourceMatch,
    Structure,
    Trust,
    Via,
    fingerprint_of,
    header_key,
    kept_answers,
    match_source,
    parse_memory,
    remember,
    reusable,
    stored,
)

# A source as a hotel's staff export: a day, the planned and the actual hours, a department.
SHAPE = [("giorno", "DATE"), ("ore a", "NUMBER"), ("ore b", "NUMBER"), ("settore", "TEXT")]
MAPPED = {
    "work_date": "giorno",
    "planned_hours": "ore a",
    "actual_hours": "ore b",
    "role": "settore",
}
# What the PERSON decided (the engine alone could not tell which hours column is which).
PERSON = {"planned_hours": "ore a", "actual_hours": "ore b"}


def memory(
    *,
    trust: Trust = Trust.PERSON,
    shape: list[tuple[str, str]] | None = None,
    mapped: dict[str, str] | None = None,
    person: dict[str, str] | None = None,
    answers: dict[str, str] | None = None,
) -> Memory:
    shape = SHAPE if shape is None else shape
    mapped = MAPPED if mapped is None else mapped
    return Memory(
        trust=trust,
        origin=Via.ANSWERS if trust == Trust.PERSON else Via.ENGINE,
        domain="labor",
        shape=shape,
        mapped=mapped,
        person=PERSON if person is None else person,
        answers=answers or {},
        fingerprint=fingerprint_of("labor", shape, mapped),
    )


def view(
    header: str,
    kind: str = "TEXT",
    *,
    personal: bool = False,
    field: str | None = None,
    level: str | None = None,
    fit: float | None = None,
) -> ColumnView:
    return ColumnView(
        header=header,
        key=header_key(header),
        kind=kind,
        personal=personal,
        field=field,
        level=level,
        fit_for=lambda _field: fit,
    )


def same_source() -> list[ColumnView]:
    return [
        view("Giorno", "DATE", field="work_date", level="HIGH"),
        view("Ore A", "NUMBER"),
        view("Ore B", "NUMBER"),
        view("Settore", field="role", level="HIGH"),
    ]


def match(columns: list[ColumnView], remembered: Memory | None = None) -> SourceMatch:
    return match_source(remembered or memory(), columns)


# --- the same source, harmlessly changed ---


def test_the_same_structure_is_recognised_and_what_the_person_decided_is_proven() -> None:
    result = match(same_source())

    assert (result.structure, result.drift) == (Structure.EXACT, Drift.NONE)
    assert result.proven == {"Ore A": "planned_hours", "Ore B": "actual_hours"}
    assert result.conflicts == () and result.missing == () and result.new_columns == 0
    assert "EXACT_HEADER_SET" in result.evidence and "TYPES_COMPATIBLE" in result.evidence
    assert result.score == 1.0


def test_it_can_say_why_in_a_sentence() -> None:
    result = match(same_source())

    assert result.explain() == (
        "EXACT (NONE): 4/4 columns coincide, 0 new, 0 missing, 0 in conflict; "
        "types compatible; score 1.00"
    )


@pytest.mark.parametrize(
    "headers",
    [
        ["GIORNO", "ORE A", "ore b", "SETTORE"],  # case
        ["  Giorno ", "Ore   A", "Ore B", "Settore"],  # spacing
        ["Giòrno", "Òre A", "Ore B", "Settòre"],  # accents
        ["Gior​no", "Ore A", "Ore B", "Sett­ore"],  # invisible and no-break characters
        ["Giorno.", "Ore A:", "(Ore B)", "Settore*"],  # punctuation
    ],
    ids=["case", "spacing", "accents", "invisible", "punctuation"],
)
def test_case_spaces_accents_invisible_characters_and_punctuation_change_nothing(
    headers: list[str],
) -> None:
    columns = [
        view(headers[0], "DATE", field="work_date", level="HIGH"),
        view(headers[1], "NUMBER"),
        view(headers[2], "NUMBER"),
        view(headers[3], field="role", level="HIGH"),
    ]

    result = match(columns)

    assert (result.structure, result.drift) == (Structure.EXACT, Drift.NONE)
    assert set(result.proven.values()) == {"planned_hours", "actual_hours"}


def test_the_same_columns_in_another_order_are_the_same_source() -> None:
    columns = [same_source()[i] for i in (3, 0, 2, 1)]  # Settore, Giorno, Ore B, Ore A

    result = match(columns)

    assert (result.structure, result.drift) == (Structure.EXACT, Drift.COSMETIC)
    assert result.reordered and "ORDER_CHANGED" in result.evidence
    assert result.proven == {"Ore A": "planned_hours", "Ore B": "actual_hours"}


def test_a_junk_column_added_leaves_every_remembered_column_valid() -> None:
    result = match([*same_source(), view("Note", "TEXT")])

    assert (result.structure, result.drift) == (Structure.COMPATIBLE, Drift.ADDITIVE)
    assert result.new_columns == 1 and result.proven == {
        "Ore A": "planned_hours",
        "Ore B": "actual_hours",
    }
    assert result.conflicts == ()


def test_a_header_renamed_to_what_the_engine_reads_the_same_is_a_cosmetic_alias() -> None:
    columns = same_source()
    columns[1] = view("Ore A (previste)", "NUMBER", field="planned_hours", level="MEDIUM")

    result = match(columns)

    assert (result.structure, result.drift) == (Structure.EXACT, Drift.COSMETIC)
    assert result.renamed == {"Ore A (previste)": "ore a"}
    assert result.proven["Ore A (previste)"] == "planned_hours"
    assert any(e.startswith("KNOWN_ALIAS") for e in result.evidence)


def test_a_renamed_header_the_engine_cannot_read_is_a_missing_column_not_a_guess() -> None:
    columns = same_source()
    columns[1] = view("Boh", "NUMBER")  # the engine says nothing about it

    result = match(columns)

    assert result.drift == Drift.MISSING and result.renamed == {}
    assert result.missing == (("planned_hours", "ore a"),)
    assert result.proven == {"Ore B": "actual_hours"}  # reuse what is still proven, ask the rest


def test_a_column_that_appeared_alongside_a_missing_one_does_not_inherit_its_meaning() -> None:
    columns = same_source()[:-1] + [
        view("Reparto nuovo", field="role", level="HIGH"),
        view("Turno"),
    ]
    del columns[1]  # "Ore A" is gone too

    result = match(columns)

    assert result.drift == Drift.MISSING
    assert result.missing and ("planned_hours", "ore a") in result.missing
    assert "Ore A" not in result.proven


# --- the current document wins over the memory ---


def test_a_column_whose_values_changed_class_is_a_semantic_conflict_and_is_not_reused() -> None:
    columns = same_source()
    columns[1] = view("Ore A", "TEXT")  # it held numbers; now it holds names or words

    result = match(columns)

    assert (result.structure, result.drift) == (Structure.COMPATIBLE, Drift.SEMANTIC_CONFLICT)
    assert [(c.header, c.field, c.reason) for c in result.conflicts] == [
        ("Ore A", "planned_hours", "VALUE_CLASS")
    ]
    assert "Ore A" not in result.proven and result.proven == {"Ore B": "actual_hours"}


def test_a_column_that_became_mixed_is_not_reused() -> None:
    columns = same_source()
    columns[2] = view("Ore B", "MIXED")

    result = match(columns)

    assert result.drift == Drift.SEMANTIC_CONFLICT and "Ore B" not in result.proven


def test_values_that_do_not_fit_the_field_are_a_conflict_even_if_the_class_is_the_same() -> None:
    columns = same_source()
    columns[1] = view("Ore A", "NUMBER", fit=0.1)  # numbers, but not hours

    result = match(columns)

    assert [(c.reason) for c in result.conflicts] == ["VALUES_DONT_FIT"]
    assert "Ore A" not in result.proven


def test_the_engine_reading_this_very_file_clearly_differently_beats_the_memory() -> None:
    columns = same_source()
    columns[1] = view("Ore A", "NUMBER", field="actual_hours", level="HIGH")

    result = match(columns)

    assert [c.reason for c in result.conflicts] == ["ENGINE_DISAGREES"]
    assert "Ore A" not in result.proven


def test_an_unsure_engine_reading_does_not_outrank_what_a_person_confirmed() -> None:
    columns = same_source()
    columns[1] = view("Ore A", "NUMBER", field="actual_hours", level="MEDIUM")

    result = match(columns)

    assert result.conflicts == () and result.proven["Ore A"] == "planned_hours"


def test_a_column_that_is_now_personal_data_is_never_reused() -> None:
    columns = same_source()
    columns[1] = view("Ore A", "TEXT", personal=True)

    result = match(columns)

    assert result.drift in (Drift.MISSING, Drift.SEMANTIC_CONFLICT) and "Ore A" not in result.proven


def test_two_columns_with_the_same_header_are_ambiguous_and_not_reused() -> None:
    columns = [*same_source(), view("Ore A", "NUMBER")]

    result = match(columns)

    assert any(c.reason == "DUPLICATE_HEADER" for c in result.conflicts)
    assert "Ore A" not in result.proven


def test_a_file_that_shares_too_little_is_a_different_source_and_nothing_is_reused() -> None:
    columns = [view("Giorno", "DATE", field="work_date", level="HIGH"), view("Altro"), view("X")]

    result = match(columns)

    assert (result.structure, result.drift) == (Structure.DIFFERENT, Drift.MAJOR_CHANGE)
    assert not reusable(memory(), result)


def test_a_memory_the_engine_made_itself_is_never_reusable() -> None:
    engine = memory(trust=Trust.ENGINE, person={})

    result = match(same_source(), engine)

    assert (result.structure, result.drift) == (Structure.EXACT, Drift.NONE)
    assert not reusable(engine, result) and result.proven == {}
    assert kept_answers(engine, result) == {}


def test_a_persons_scalar_answers_are_kept_only_for_a_file_that_still_looks_the_same() -> None:
    remembered = memory(answers={"date_order": "DMY", "amount_basis": "NET"})

    assert kept_answers(remembered, match(same_source(), remembered)) == {
        "date_order": "DMY",
        "amount_basis": "NET",
    }
    broken = same_source()
    broken[1] = view("Ore A", "TEXT")
    assert kept_answers(remembered, match(broken, remembered)) == {}  # a conflict keeps none
    assert kept_answers(remembered, match(same_source()[:2], remembered)) == {}  # nor a missing one


# --- what is remembered ---


def test_a_personal_data_column_is_a_placeholder_in_the_remembered_structure() -> None:
    from app.modules.data_sources.source_learning import shape_of

    columns = [
        view("Giorno", "DATE"),
        view("Mario Rossi", "TEXT", personal=True),
        view("Ore", "NUMBER"),
    ]

    assert shape_of(columns) == [("giorno", "DATE"), (PERSONAL, "TEXT"), ("ore", "NUMBER")]
    blob = repr(stored(memory(shape=shape_of(columns))))
    assert "mario" not in blob.lower() and "rossi" not in blob.lower()


def test_the_fingerprint_is_the_structure_not_its_order_and_changes_with_the_mapping() -> None:
    one = fingerprint_of("labor", SHAPE, MAPPED)
    reordered = fingerprint_of("labor", list(reversed(SHAPE)), MAPPED)
    other_mapping = fingerprint_of("labor", SHAPE, {**MAPPED, "planned_hours": "ore b"})

    assert one == reordered and one != other_mapping
    assert fingerprint_of("bookings", SHAPE, MAPPED) != one  # a kind of data is part of identity
    assert len(one) == 16


@pytest.mark.parametrize(
    "raw", [None, {}, {"v": 99}, {"trust": "PERSON"}, "nope", {"v": 1, "trust": "?"}]
)
def test_a_missing_damaged_or_newer_memory_is_just_no_memory(raw: object) -> None:
    assert parse_memory(raw) is None  # type: ignore[arg-type]


def test_a_stored_memory_reads_back_as_it_was_written() -> None:
    original = memory(answers={"date_order": "DMY"})

    assert parse_memory(stored(original)) == original


# --- trust, revisions and correction ---


def _learn(
    existing: Memory | None, via: Via, *, mapped: dict[str, str] | None = None, **extra: object
) -> Memory | None:
    return remember(
        existing,
        domain="labor",
        shape=SHAPE,
        mapped=MAPPED if mapped is None else mapped,
        person=extra.pop("person", PERSON) if via in (Via.ANSWERS, Via.MANUAL) else {},  # type: ignore[arg-type]
        answers=extra.pop("answers", {}),  # type: ignore[arg-type]
        origin=via,
    )


def test_a_persons_answer_makes_the_first_revision_trusted() -> None:
    learned = _learn(None, Via.ANSWERS)

    assert learned is not None
    assert (learned.revision, learned.trust, learned.origin) == (1, Trust.PERSON, Via.ANSWERS)
    assert learned.person == PERSON and learned.history == []


def test_a_matching_built_by_hand_is_trusted_too() -> None:
    learned = _learn(None, Via.MANUAL, person=dict(MAPPED))

    assert learned is not None and learned.trust == Trust.PERSON and learned.person == MAPPED


def test_a_file_the_engine_read_alone_leaves_evidence_never_authority() -> None:
    learned = _learn(None, Via.ENGINE)

    assert learned is not None and learned.trust == Trust.ENGINE and learned.person == {}


def test_the_engine_never_replaces_what_a_person_confirmed() -> None:
    trusted = _learn(None, Via.ANSWERS)

    assert _learn(trusted, Via.ENGINE, mapped={**MAPPED, "planned_hours": "ore b"}) is None


def test_a_decision_that_came_from_the_memory_confirms_nothing_new() -> None:
    assert _learn(_learn(None, Via.ANSWERS), Via.REUSE) is None


def test_confirming_the_same_thing_again_keeps_the_revision() -> None:
    first = _learn(None, Via.ANSWERS)

    again = _learn(first, Via.ANSWERS)

    assert again is not None and again.revision == 1 and again.history == []


def test_a_correction_is_a_new_revision_and_the_old_one_stays_in_the_history() -> None:
    first = _learn(None, Via.ANSWERS)
    corrected_person = {"planned_hours": "ore b", "actual_hours": "ore a"}
    corrected_mapped = {**MAPPED, **corrected_person}

    second = _learn(first, Via.MANUAL, mapped=corrected_mapped, person=corrected_person)

    assert second is not None
    assert second.revision == 2 and second.person == corrected_person
    assert [h["revision"] for h in second.history] == [1]
    assert second.history[0]["person"] == PERSON  # the history is not rewritten
    third = _learn(second, Via.ANSWERS)
    assert third is not None and third.revision == 3 and third.person == PERSON  # and back


def test_the_history_is_short() -> None:
    current: Memory | None = None
    for round_ in range(HISTORY_KEPT + 4):
        person = {"planned_hours": f"c{round_}", "actual_hours": "ore b"}
        current = _learn(current, Via.MANUAL, mapped={**MAPPED, **person}, person=person)

    assert current is not None
    assert current.revision == HISTORY_KEPT + 4
    assert len(current.history) == HISTORY_KEPT


def test_what_is_remembered_holds_only_closed_vocabulary_keys_and_numbers() -> None:
    learned = _learn(
        None, Via.ANSWERS, answers={"date_order": "DMY", "secret": "x", "decimal_style": ""}
    )

    assert learned is not None
    assert learned.answers == {"date_order": "DMY"}  # only the answers worth remembering
    blob = stored(learned)
    assert set(blob) <= {
        "v", "revision", "trust", "origin", "domain", "shape", "mapped", "person", "answers",
        "history", "fingerprint", "id", "touched", "layout",
    }  # fmt: skip


@pytest.mark.parametrize(
    "build",
    [
        lambda: match(same_source()),
        lambda: match(list(reversed(same_source()))),
        lambda: match([*same_source(), view("Note")]),
    ],
)
def test_matching_is_deterministic(build: Callable[[], SourceMatch]) -> None:
    assert build() == build()

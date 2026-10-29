"""Source Learning, several recurring families in ONE source (property + kind of data).

Pure functions, no database. A hotel brings back more than one kind of file in the same kind of data
- the PMS export, an OTA export, an internal report - and none of them may replace another. Which
family a file is, is decided by how much of the file each family explains; when two could be it and
none clearly is, nothing is reused (it is never guessed).
"""

import itertools
import json
import time
from collections.abc import Sequence

import pytest

from app.modules.data_sources.source_learning import (
    FAMILIES_KEPT,
    HISTORY_KEPT,
    LEARNING_SCHEMA,
    MIN_RESIDUAL_GAP,
    ColumnView,
    Drift,
    FamilyChoice,
    Learning,
    Memory,
    Structure,
    Trust,
    Via,
    choose_family,
    fingerprint_of,
    header_key,
    is_revision,
    parse_learning,
    parse_memory,
    remember_in,
    residual,
    reusable,
    stored,
    stored_learning,
)

DOMAIN = "LABOR"


def shape_of_columns(columns: Sequence[str]) -> list[tuple[str, str]]:
    return [(header_key(c), "TEXT" if c in TEXT else "NUMBER") for c in columns]


TEXT = {
    "Area",
    "Costo",
    "Note",
    "Altro",
    "Reparto",
}  # (a family's columns are all numbers but these)


def view(header: str, *, field: str | None = None, level: str | None = None) -> ColumnView:
    return ColumnView(
        header=header,
        key=header_key(header),
        kind="TEXT" if header in TEXT else "NUMBER",
        personal=False,
        field=field,
        level=level,
        fit_for=lambda _field: None,
    )


def file_of(*headers: str) -> list[ColumnView]:
    return [view(h) for h in headers]


def family(
    *headers: str, mapped: dict[str, str] | None = None, trust: Trust = Trust.PERSON
) -> Memory:
    """A family a person confirmed: every header is mapped to a field of its own."""
    keys = [header_key(h) for h in headers]
    mapping = mapped if mapped is not None else {f"field_{k}": k for k in keys}
    shape = shape_of_columns(headers)
    return Memory(
        trust=trust,
        origin=Via.ANSWERS if trust == Trust.PERSON else Via.ENGINE,
        domain=DOMAIN,
        shape=shape,
        mapped=mapping,
        person=dict(mapping) if trust == Trust.PERSON else {},
        fingerprint=fingerprint_of(DOMAIN, shape, mapping),
    )


def source_of(*families: Memory) -> Learning:
    """A source that remembers these families (ids "1", "2", ...)."""
    return Learning(
        seq=len(families),
        current="1",
        families=[
            m.model_copy(update={"id": str(i), "touched": i}) for i, m in enumerate(families, 1)
        ],
    )


def chosen(learning: Learning, headers: Sequence[str]) -> FamilyChoice:
    return choose_family(learning, file_of(*headers))


def id_of(choice: FamilyChoice) -> str | None:
    return None if choice.memory is None else choice.memory.id


# A hotel's staff exports: three unrelated families and a "twin" that differs from the first by ONE
# column (the department is called something else).
A = ("Data", "Prev.", "Eff.", "Area")
B = ("Giorno", "Ore base", "Ore extra")
C = ("Codice", "Turno", "Ore")
A_TWIN = ("Data", "Prev.", "Eff.", "Costo")


# --- the section stored in the profile ---


def test_the_families_of_a_source_are_stored_side_by_side_and_come_back_the_same() -> None:
    learning = source_of(family(*A), family(*B), family(*C))

    again = parse_learning(stored_learning(learning))

    assert again == learning
    assert stored_learning(learning)["v"] == LEARNING_SCHEMA
    assert [m.id for m in again.families] == ["1", "2", "3"]


def test_the_section_written_before_there_were_families_is_one_family() -> None:
    legacy = stored(family(*A))  # a flat memory: what Gate 1 stored

    learning = parse_learning(legacy)

    assert learning is not None and len(learning.families) == 1
    assert learning.current == learning.families[0].id  # its matching is the one in the profile
    assert learning.families[0].mapped == family(*A).mapped


def test_a_damaged_family_is_left_out_and_the_others_survive() -> None:
    raw = stored_learning(source_of(family(*A), family(*B), family(*C)))
    raw["families"][1] = {"id": "2", "shape": "broken"}  # no structure, no matching

    learning = parse_learning(raw)

    assert learning is not None and [m.id for m in learning.families] == ["1", "3"]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"v": 1, "families": []},  # another version
        {"v": LEARNING_SCHEMA, "families": "nope"},
        {"v": 99, "families": []},
        "garbage",
    ],
)
def test_nothing_readable_is_no_memory_never_an_error(raw: object) -> None:
    assert parse_learning(raw) is None  # type: ignore[arg-type]


def test_a_family_with_the_same_identity_twice_is_kept_once() -> None:
    raw = stored_learning(source_of(family(*A), family(*B)))
    raw["families"][1]["id"] = raw["families"][0]["id"]

    learning = parse_learning(raw)

    assert learning is not None and len(learning.families) == 1


def test_a_current_family_that_does_not_exist_points_nowhere() -> None:
    raw = stored_learning(source_of(family(*A)))
    raw["current"] = "ghost"

    learning = parse_learning(raw)

    assert learning is not None and learning.current == ""


def test_only_the_families_of_this_kind_of_data_are_applied() -> None:
    other = family(*B).model_copy(update={"domain": "BOOKINGS"})
    learning = source_of(family(*A), other)

    assert [m.domain for m in learning.of_domain(DOMAIN).families] == [DOMAIN]


# --- which family is this file ---


def test_a_source_with_no_family_chooses_nothing() -> None:
    assert choose_family(None, file_of(*A)) == FamilyChoice()
    assert choose_family(Learning(), file_of(*A)) == FamilyChoice()


@pytest.mark.parametrize(
    ("headers", "wanted"),
    [(A, "1"), (B, "2"), (C, "3")],
    ids=["first", "second", "third"],
)
def test_each_family_of_the_source_is_recognised_whichever_came_first(
    headers: Sequence[str], wanted: str
) -> None:
    learning = source_of(family(*A), family(*B), family(*C))

    choice = chosen(learning, headers)

    assert id_of(choice) == wanted
    assert choice.match is not None and (choice.match.structure, choice.match.drift) == (
        Structure.EXACT,
        Drift.NONE,
    )
    assert choice.revision and choice.family == wanted and not choice.ambiguous
    assert choice.known == 3


def test_the_order_in_which_families_were_learned_never_decides_anything() -> None:
    families = [family(*A), family(*B), family(*C), family(*A_TWIN)]
    files = [A, B, C, A_TWIN, (*A, "Note"), tuple(reversed(A)), ("Data", "Prev.", "Eff.", "Altro")]

    for file in files:
        results = set()
        for order in itertools.permutations(families):
            learning = Learning(
                seq=9,
                families=[m.model_copy(update={"id": m.fingerprint, "touched": 1}) for m in order],
            )
            choice = chosen(learning, file)
            results.add((choice.memory.fingerprint if choice.memory else None, choice.ambiguous))
        assert len(results) == 1, f"the order changed the answer for {file}"


def test_a_returning_family_is_not_confused_with_the_ones_learned_after_it() -> None:
    learning = source_of(family(*A), family(*B), family(*C), family(*A_TWIN))

    for headers, wanted in ((A, "1"), (B, "2"), (C, "3"), (A_TWIN, "4")):
        assert id_of(chosen(learning, headers)) == wanted


def test_a_family_that_drifted_is_still_that_family_and_not_a_neighbour() -> None:
    learning = source_of(family(*A), family(*B), family(*C), family(*A_TWIN))
    drifted = {
        "reordered": ("Area", "Data", "Eff.", "Prev."),
        "junk column": (*A, "Colonna extra"),
        "junk and reordered": ("Colonna extra", "Eff.", "Area", "Data", "Prev."),
        "two new columns": (*A, "Note", "Colonna extra"),
    }

    for what, headers in drifted.items():
        choice = chosen(learning, headers)
        assert id_of(choice) == "1", what
        assert choice.revision, what  # nothing remembered is lost: the family itself, evolving

    # a column gone: still THIS family's file (what is left is reused), though not a revision of it
    gone = chosen(learning, ("Data", "Prev.", "Area"))
    assert id_of(gone) == "1" and not gone.ambiguous and not gone.revision


def test_family_a_after_family_b_is_compatible_with_a_not_b() -> None:
    learning = source_of(family(*A), family(*B))

    choice = chosen(learning, ("Eff.", "Data", "Prev.", "Area", "Extra"))

    assert id_of(choice) == "1"
    assert choice.match is not None and choice.match.structure == Structure.COMPATIBLE
    assert choice.match.drift == Drift.ADDITIVE


# --- collision safety ---


def test_two_families_one_column_apart_are_told_apart_when_the_file_is_complete() -> None:
    learning = source_of(family(*A), family(*A_TWIN))

    assert id_of(chosen(learning, A)) == "1"
    assert id_of(chosen(learning, A_TWIN)) == "2"
    assert id_of(chosen(learning, (*A, "Colonna extra"))) == "1"
    assert id_of(chosen(learning, (*A_TWIN, "Colonna extra"))) == "2"


@pytest.mark.parametrize(
    "headers",
    [
        ("Data", "Prev.", "Eff."),  # the column that tells them apart is not in the file
        ("Data", "Prev.", "Eff.", "Altro"),  # a column neither family has
        ("Prev.", "Eff.", "Altro", "Data"),
        (*A, "Costo"),  # both columns at once: it is both families and neither
    ],
    ids=["no distinguishing column", "a third column", "reordered third", "both columns"],
)
def test_when_two_families_could_be_the_file_and_none_clearly_is_nothing_is_chosen(
    headers: Sequence[str],
) -> None:
    learning = source_of(family(*A), family(*A_TWIN))

    choice = chosen(learning, headers)

    assert choice.ambiguous and choice.memory is None and choice.match is None
    assert choice.family is None  # a confirmation of this file would start a family of its own
    assert choice.eligible == 2 and choice.rival is not None


def test_an_ambiguous_file_reuses_nothing() -> None:
    learning = source_of(family(*A), family(*A_TWIN))
    choice = chosen(learning, ("Data", "Prev.", "Eff."))

    # nothing to be reused: the caller has no memory and no match to apply
    assert choice.memory is None and choice.match is None


def test_a_weak_coincidence_with_a_third_family_does_not_decide() -> None:
    # (a family nobody could mistake for the file is not a rival)
    learning = source_of(family(*A), family(*A_TWIN), family(*C))

    assert chosen(learning, ("Data", "Prev.", "Eff.")).ambiguous
    assert id_of(chosen(learning, C)) == "3"


def test_a_family_nested_in_another_is_not_guessed() -> None:
    small = ("ID", "Arrivo", "Partenza")
    large = ("ID", "Arrivo", "Partenza", "Canale", "Totale")
    learning = source_of(family(*small), family(*large))

    assert id_of(chosen(learning, small)) == "1"
    assert id_of(chosen(learning, large)) == "2"
    # small + one column: it could be the first family grown, or the second one with a column less
    assert chosen(learning, (*small, "Canale")).ambiguous


def test_the_winner_explains_it_all_or_leaves_the_minimum_gap_fewer_columns_unexplained() -> None:
    # a complete explanation beats a rival that leaves even ONE column unexplained...
    learning = source_of(family(*A), family("Data", "Prev.", "Eff.", "Area", "Note"))
    complete = chosen(learning, A)
    assert id_of(complete) == "1" and residual(complete.match) == 0  # type: ignore[arg-type]
    assert complete.rival is not None and residual(complete.rival) == 1
    # ...but between two imperfect explanations the gap has to be real
    assert MIN_RESIDUAL_GAP == 2
    tied = chosen(learning, ("Data", "Prev.", "Eff.", "Area", "Altro"))
    assert tied.ambiguous


def test_a_header_that_is_there_beats_one_the_engine_only_reads_the_same() -> None:
    # two families that differ by a column the engine reads as the SAME field: the file that holds
    # the header itself is the first one, not "either, if you count the synonym"
    base = {"work_date": "data", "planned_hours": "prev", "actual_hours": "eff"}
    exact = family("Data", "Prev.", "Eff.", "Area", mapped={**base, "role": "area"})
    synonym = family("Data", "Prev.", "Eff.", "Reparto", mapped={**base, "role": "reparto"})
    learning = source_of(exact, synonym)
    columns = [
        view("Data"),
        view("Prev."),
        view("Eff."),
        view("Area", field="role", level="HIGH"),
    ]

    choice = choose_family(learning, columns)

    assert id_of(choice) == "1" and not choice.ambiguous
    assert choice.rival is not None and len(choice.rival.renamed) == 1  # (held under another name)
    assert residual(choice.match) == 0 and residual(choice.rival) == 1  # type: ignore[arg-type]


def test_a_single_family_that_could_be_the_file_is_chosen_as_before_with_no_rival() -> None:
    learning = source_of(family(*A), family(*B), family(*C))

    choice = chosen(learning, (*A, "Colonna extra"))

    assert id_of(choice) == "1" and choice.eligible == 1 and choice.rival is None


def test_when_no_family_could_be_the_file_the_closest_is_reported_and_nothing_is_reused() -> None:
    learning = source_of(family(*A), family(*B), family(*C))

    choice = chosen(learning, ("Altro", "Note", "Costo"))

    assert choice.eligible == 0 and not choice.ambiguous and not choice.revision
    assert choice.match is not None and choice.match.structure == Structure.DIFFERENT
    assert choice.family is None
    assert not reusable(choice.memory, choice.match)  # type: ignore[arg-type]


def test_a_family_only_the_engine_read_wins_the_file_it_is_but_reuses_nothing() -> None:
    engine = family(*B, trust=Trust.ENGINE)
    learning = source_of(family(*A), engine)

    choice = chosen(learning, B)

    assert id_of(choice) == "2"
    assert choice.memory is not None and choice.match is not None
    assert not reusable(choice.memory, choice.match)  # the engine cannot teach itself


def test_an_engine_family_is_not_taken_for_a_person_s_family_that_resembles_it() -> None:
    # the file is the engine's family exactly; the person's is only a weaker neighbour
    person = family(*A)
    engine = family("Data", "Prev.", "Eff.", "Area", "Note", trust=Trust.ENGINE)
    learning = source_of(person, engine)

    choice = chosen(learning, ("Data", "Prev.", "Eff.", "Area", "Note"))

    assert id_of(choice) == "2" and choice.match is not None
    assert not reusable(choice.memory, choice.match)  # type: ignore[arg-type]


def test_matching_every_family_of_a_full_source_stays_fast() -> None:
    families = [
        family(*(f"Col{n}_{k}" for k in range(12)), mapped=None) for n in range(FAMILIES_KEPT)
    ]
    learning = source_of(*families)
    columns = file_of(*(f"Col{FAMILIES_KEPT - 1}_{k}" for k in range(12)))

    started = time.perf_counter()
    for _ in range(20):
        choice = choose_family(learning, columns)
    per_file_ms = (time.perf_counter() - started) * 1000 / 20

    assert id_of(choice) == str(FAMILIES_KEPT)
    assert per_file_ms < 50  # macroscopic regressions only


# --- family or revision ---


def test_a_file_that_loses_nothing_remembered_is_a_revision_however_much_is_added() -> None:
    learning = source_of(family(*A))

    for extra in range(1, 8):
        choice = chosen(learning, (*A, *(f"Extra{n}" for n in range(extra))))
        assert choice.match is not None and choice.match.drift == Drift.ADDITIVE
        assert choice.revision, f"{extra} new columns"


def test_a_file_that_still_holds_everything_remembered_is_a_revision_even_if_meaning_changed() -> (
    None
):
    learning = source_of(family(*A))
    retyped = [
        view("Data"),
        view("Prev."),
        view("Eff."),
        ColumnView("Area", header_key("Area"), "NUMBER", False, None, None, lambda _f: None),
    ]  # the same headers; "Area" now holds numbers

    choice = choose_family(learning, retyped)

    assert choice.match is not None and choice.match.drift == Drift.SEMANTIC_CONFLICT
    assert choice.revision  # the person's correction is the next revision of THIS family


def test_a_file_that_lacks_a_remembered_column_is_another_family_not_a_revision() -> None:
    learning = source_of(family("Data", "Prev.", "Eff.", "Area", "Note"))

    # one of five is gone: the memory still helps (as before: the rest is reused), but a
    # confirmation of this file starts a family of its own and leaves this one as it is
    gone = chosen(learning, ("Data", "Prev.", "Eff.", "Area"))

    assert id_of(gone) == "1" and gone.match is not None
    assert gone.match.drift == Drift.MISSING and gone.match.score >= 0.6
    assert not gone.revision and gone.family is None
    assert not is_revision(gone.match)


def test_a_column_called_something_else_is_a_sibling_not_the_same_family_renamed() -> None:
    learning = source_of(family(*A))

    choice = chosen(learning, A_TWIN)  # Area -> Costo: one gone, one new

    assert id_of(choice) == "1" and choice.match is not None
    assert (choice.match.structure, choice.match.drift) == (Structure.COMPATIBLE, Drift.MISSING)
    assert not choice.revision and choice.family is None


def test_a_file_that_shares_little_of_it_is_another_family_not_a_revision() -> None:
    learning = source_of(family(*A))

    # two of the four are in common: the memory still helps, a confirmation starts a family
    overlap = chosen(learning, ("Data", "Prev.", "Altro", "Note"))

    assert id_of(overlap) == "1" and overlap.match is not None
    assert overlap.match.structure == Structure.COMPATIBLE
    assert not overlap.revision and overlap.family is None
    assert not is_revision(overlap.match)


def test_nothing_in_common_is_never_a_revision() -> None:
    learning = source_of(family(*A))
    choice = chosen(learning, C)

    assert choice.match is not None and not is_revision(choice.match)


# --- remembering: only the family the file is changes ---


def learn(
    learning: Learning | None,
    headers: Sequence[str],
    *,
    family_id: str | None,
    origin: Via = Via.ANSWERS,
    mapped: dict[str, str] | None = None,
    person: dict[str, str] | None = None,
) -> Learning | None:
    keys = [header_key(h) for h in headers]
    mapping = mapped if mapped is not None else {f"field_{k}": k for k in keys}
    return remember_in(
        learning,
        family=family_id,
        domain=DOMAIN,
        shape=shape_of_columns(headers),
        mapped=mapping,
        person=(dict(mapping) if person is None else person) if origin != Via.ENGINE else {},
        answers={},
        origin=origin,
    )


def teach(learning: Learning | None, headers: Sequence[str]) -> Learning:
    """A person confirms a file the way the server would: as the family it is, or as a new one."""
    choice = choose_family(learning, file_of(*headers))
    updated = learn(learning, headers, family_id=choice.family)
    assert updated is not None
    return updated


def memory_of(learning: Learning, family_id: str) -> Memory:
    found = learning.family(family_id)
    assert found is not None
    return found


def test_the_first_confirmation_creates_the_first_family() -> None:
    learning = learn(None, A, family_id=None)

    assert learning is not None and len(learning.families) == 1
    first = learning.families[0]
    assert first.revision == 1 and first.trust == Trust.PERSON and first.history == []
    assert learning.current == first.id and learning.seq == 1


def test_another_structure_confirmed_is_a_new_family_and_the_first_is_untouched() -> None:
    first = teach(None, A)
    before = memory_of(first, first.current)

    both = teach(first, B)

    assert len(both.families) == 2
    after = memory_of(both, before.id)
    assert after.model_dump() == before.model_dump()  # not even `touched` moved
    assert both.current != before.id and memory_of(both, both.current).shape == shape_of_columns(B)


def test_learning_a_b_and_c_keeps_all_three_and_they_are_all_recognised_after() -> None:
    learning = teach(teach(teach(None, A), B), C)

    assert len(learning.families) == 3
    ids = {headers: id_of(choose_family(learning, file_of(*headers))) for headers in (A, B, C)}
    assert len(set(ids.values())) == 3 and None not in ids.values()


def test_a_correction_in_one_family_does_not_touch_another() -> None:
    learning = teach(teach(None, A), B)
    a_id = id_of(chosen(learning, A))
    b_id = id_of(chosen(learning, B))
    assert a_id and b_id
    b_before = memory_of(learning, b_id).model_dump()
    corrected = {
        "field_data": "data",
        "field_prev.": "eff.",
        "field_eff.": "prev.",
        "field_area": "area",
    }

    after = learn(learning, A, family_id=a_id, mapped=corrected, origin=Via.MANUAL)

    assert after is not None
    assert memory_of(after, a_id).revision == 2 and memory_of(after, a_id).mapped == corrected
    assert [h["revision"] for h in memory_of(after, a_id).history] == [1]
    assert memory_of(after, b_id).model_dump() == b_before  # the other family is exactly as it was
    assert len(after.families) == 2


def test_the_same_structure_and_matching_confirmed_again_is_the_same_family() -> None:
    learning = teach(None, A)

    again = learn(learning, A, family_id=None)  # (the caller found no family: still the same one)

    assert again is not None and len(again.families) == 1
    assert again.families[0].revision == 1 and again.families[0].id == learning.families[0].id


def test_a_revision_keeps_the_identity_of_its_family() -> None:
    learning = teach(teach(None, A), B)
    a_id = id_of(chosen(learning, A))
    grown = (*A, "Note")

    after = learn(learning, grown, family_id=chosen(learning, grown).family)

    assert after is not None and len(after.families) == 2
    assert memory_of(after, a_id or "").revision == 2
    assert memory_of(after, a_id or "").shape == shape_of_columns(grown)


def test_a_decision_that_came_from_the_memory_only_marks_which_family_is_in_use() -> None:
    learning = teach(teach(None, A), B)
    a_id = id_of(chosen(learning, A)) or ""
    before = {m.id: m.model_dump(exclude={"touched"}) for m in learning.families}

    after = learn(learning, A, family_id=a_id, origin=Via.REUSE)

    assert after is not None and after.current == a_id
    assert {m.id: m.model_dump(exclude={"touched"}) for m in after.families} == before
    assert memory_of(after, a_id).touched > memory_of(learning, a_id).touched


def test_a_reuse_with_no_family_leaves_the_profile_belonging_to_nobody() -> None:
    learning = teach(teach(None, A), B)

    after = learn(learning, A, family_id=None, origin=Via.REUSE)

    assert after is not None and after.current == ""
    assert after.families == learning.families
    assert learn(None, A, family_id=None, origin=Via.REUSE) is None


def test_the_engine_alone_never_writes_once_a_person_confirmed_something() -> None:
    learning = teach(None, A)

    assert learn(learning, B, family_id=None, origin=Via.ENGINE) is None
    assert learn(learning, A, family_id=learning.current, origin=Via.ENGINE) is None


def test_the_engine_alone_leaves_evidence_when_nobody_confirmed_anything() -> None:
    learning = learn(None, A, family_id=None, origin=Via.ENGINE)

    assert learning is not None and learning.families[0].trust == Trust.ENGINE
    assert learning.families[0].person == {}


def test_a_person_confirming_a_family_the_engine_read_makes_it_theirs() -> None:
    engine = learn(None, A, family_id=None, origin=Via.ENGINE)
    assert engine is not None
    a_id = engine.families[0].id

    person = learn(engine, A, family_id=a_id, origin=Via.ANSWERS)

    assert person is not None and len(person.families) == 1
    assert person.families[0].trust == Trust.PERSON and person.families[0].revision == 2


# --- the limits ---


def test_families_and_revisions_do_not_share_a_limit_and_neither_is_tiny() -> None:
    assert FAMILIES_KEPT != HISTORY_KEPT
    assert FAMILIES_KEPT >= 20  # a hotel's recurring files in a kind of data, with room to spare
    assert HISTORY_KEPT >= 1


def distinct_files(count: int) -> list[tuple[str, ...]]:
    return [(f"Alfa{n}", f"Beta{n}", f"Gamma{n}", f"Delta{n}") for n in range(count)]


def test_past_the_limit_the_least_recently_used_family_goes_and_the_newest_stays() -> None:
    files = distinct_files(FAMILIES_KEPT + 3)
    learning: Learning | None = None
    for headers in files:
        learning = teach(learning, headers)

    assert learning is not None and len(learning.families) == FAMILIES_KEPT
    survivors = {tuple(k for k, _ in m.shape) for m in learning.families}
    assert tuple(header_key(h) for h in files[-1]) in survivors  # the one just written
    assert tuple(header_key(h) for h in files[0]) not in survivors  # the oldest, unused
    assert tuple(header_key(h) for h in files[2]) not in survivors
    assert tuple(header_key(h) for h in files[3]) in survivors


def test_a_family_in_use_outlives_older_ones_that_were_not() -> None:
    files = distinct_files(FAMILIES_KEPT)
    learning: Learning | None = None
    for headers in files:
        learning = teach(learning, headers)
    assert learning is not None
    oldest = id_of(choose_family(learning, file_of(*files[0]))) or ""
    # the hotel brings the oldest family back (an import that reused it)...
    learning = learn(learning, files[0], family_id=oldest, origin=Via.REUSE)
    assert learning is not None
    # ...and then another new family arrives: the second oldest goes, not the one in use
    learning = teach(learning, ("Omega1", "Omega2", "Omega3", "Omega4"))

    keys = {tuple(k for k, _ in m.shape) for m in learning.families}
    assert tuple(header_key(h) for h in files[0]) in keys
    assert tuple(header_key(h) for h in files[1]) not in keys
    assert len(learning.families) == FAMILIES_KEPT


def test_what_only_the_engine_read_goes_before_what_a_person_confirmed() -> None:
    learning: Learning | None = None
    person_files = distinct_files(FAMILIES_KEPT - 1)
    for headers in person_files:
        learning = teach(learning, headers)
    # the engine leaves evidence only in a source nobody confirmed anything in: build it directly
    assert learning is not None
    engine = family("Zeta1", "Zeta2", "Zeta3", "Zeta4", trust=Trust.ENGINE).model_copy(
        update={"id": "e1", "touched": 0}
    )
    learning = learning.model_copy(update={"families": [engine, *learning.families]})
    assert len(learning.families) == FAMILIES_KEPT
    learning = teach(learning, ("Omega1", "Omega2", "Omega3", "Omega4"))

    assert len(learning.families) == FAMILIES_KEPT
    assert "e1" not in {m.id for m in learning.families}  # the engine's went, a person's did not
    assert all(m.trust == Trust.PERSON for m in learning.families)


def test_the_history_of_a_family_is_capped_on_its_own_while_families_stay_many() -> None:
    learning: Learning | None = None
    for headers in distinct_files(6):
        learning = teach(learning, headers)
    assert learning is not None
    target = learning.families[0]
    headers = tuple(k for k, _ in target.shape)
    for n in range(HISTORY_KEPT + 4):
        mapping = {"field_a": headers[0], "field_b": headers[1], f"field_{n}": headers[2]}
        learning = learn(learning, headers, family_id=target.id, mapped=mapping, origin=Via.MANUAL)
        assert learning is not None

    revised = memory_of(learning, target.id)
    assert len(revised.history) == HISTORY_KEPT
    assert len(learning.families) == 6  # the other families lose nothing to a long history


def test_family_identities_are_unique_and_never_reused_after_one_is_dropped() -> None:
    learning: Learning | None = None
    seen: set[str] = set()
    for headers in distinct_files(FAMILIES_KEPT + 6):
        learning = teach(learning, headers)
        assert learning.current not in seen
        seen.add(learning.current)
    assert learning is not None
    assert len({m.id for m in learning.families}) == len(learning.families)


# --- what is kept ---


ALLOWED_FAMILY_KEYS = {
    "v", "revision", "trust", "origin", "domain", "shape", "mapped", "person", "answers",
    "history", "fingerprint", "id", "touched", "layout",
}  # fmt: skip


def test_the_stored_section_holds_only_closed_keys_headers_and_numbers() -> None:
    learning = teach(teach(None, A), B)

    blob = stored_learning(learning)

    assert set(blob) <= {"v", "seq", "current", "families"}
    for entry in blob["families"]:
        assert set(entry) <= ALLOWED_FAMILY_KEYS
        parse_memory(entry)  # and each one is a readable family
    text = json.dumps(blob, ensure_ascii=False).casefold()
    for forbidden in ("xlsx", ".csv", "rossi", "@", "iban", "turni"):
        assert forbidden not in text


def test_a_family_is_identified_by_a_number_never_by_a_file_name() -> None:
    learning = teach(None, ("Pratica", "Dal", "Al", "Valore"))

    assert learning.current.isalnum() and "pratica" not in learning.current.casefold()

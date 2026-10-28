"""Source Learning with SEVERAL recurring families in one source, end to end.

One property can bring back more than one kind of file in the same kind of data - the staff export
of the reception, another from the restaurant, a third for the seasonal workers - and none of them
is the same structure. Each is taught once (a question answered, or a matching built by hand); each
is then recognised whenever it comes back, whichever of the others came in between, with nothing
asked again.

Real files through the real API and the real database (rolled back). No model, no embedding, no
external service: `IMPORT_UNDERSTANDING_MODE` is off for the whole suite.
"""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingMappingProfile
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.service import DataSourcesService
from app.modules.data_sources.source_learning import Learning, Memory, Via, parse_learning
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from app.modules.labor.models import LaborMappingProfile
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import by_hand, decision, import_mapped, profiles_of, understand
from tests.source_learning_support import PEOPLE, same_columns_with, xlsx_of
from tests.support import BookingFactory

LABOR = "LABOR"
BOOKINGS = "BOOKINGS"

# Four staff exports in the house's own words: the engine cannot tell which hours column is which.
RECEPTION = {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"}
RECEPTION_SAYS = {"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}}
RESTAURANT = {"Data": "day", "Ore 1": "planned", "Ore 2": "actual", "Area": "dept"}
RESTAURANT_SAYS = {"column_fields": {"Ore 1": "planned_hours", "Ore 2": "actual_hours"}}
SEASONAL = {"Giorno": "day", "Ore base": "planned", "Ore extra": "actual", "Squadra": "dept"}
SEASONAL_SAYS = {"column_fields": {"Ore base": "planned_hours", "Ore extra": "actual_hours"}}
# The reception export's twin: one column apart (the second hours column has another name).
NIGHT = {"Giorno": "day", "Ore A": "planned", "Ore C": "actual", "Settore": "dept"}
NIGHT_SAYS = {"column_fields": {"Ore A": "planned_hours", "Ore C": "actual_hours"}}
# A matching built by hand, for a structure nobody could read.
BY_HAND = {"Dt": "day", "H1": "planned", "H2": "actual", "Rep": "dept"}
BY_HAND_DECISION = decision(
    {"Dt": "work_date", "H1": "planned_hours", "H2": "actual_hours", "Rep": "role"}
)
# A bookings export with the SAME headers as a staff one would be nonsense: use the same words.
MONTH = {"reception": 10, "restaurant": 9, "seasonal": 8, "night": 7, "by hand": 6}


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _teach(
    api_client: TestClient,
    env: SourcesEnv,
    columns: dict[str, str],
    answers: dict[str, Any],
    month: int,
    name: str = "turni.xlsx",
    *,
    asks: bool = True,
    confirmed: bool = False,
) -> None:
    """The first time a family arrives: it asks, the person answers, the import remembers."""
    content = xlsx_of(columns, month=month)
    asked = understand(api_client, env, LABOR, name, content, confirmed=confirmed)
    if asks:
        assert asked["understanding"]["level"] == "ASK", "the file must ask to have a question"
    answered = understand(api_client, env, LABOR, name, content, answers, confirmed=confirmed)
    assert answered["understanding"]["level"] == "READY"
    done = import_mapped(
        api_client, env, LABOR, name, content, answered["proposal"], snapshot=f"2026-{month:02d}-28"
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    assert done.json()["configuration_saved"] is True


def _teach_by_hand(
    api_client: TestClient, env: SourcesEnv, columns: dict[str, str], month: int
) -> None:
    content = xlsx_of(columns, month=month)
    done = import_mapped(
        api_client,
        env,
        LABOR,
        "turni.xlsx",
        content,
        by_hand(BY_HAND_DECISION),
        snapshot=f"2026-{month:02d}-28",
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    assert done.json()["configuration_saved"] is True


def _store(db_session: Session, env: SourcesEnv, model: Any = LaborMappingProfile) -> Learning:
    (profile,) = profiles_of(db_session, env, model)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    return store


def _family(store: Learning, family_id: str | None) -> Memory:
    found = store.family(family_id)
    assert found is not None, f"no family {family_id} among {[m.id for m in store.families]}"
    return found


def _inspect(
    db_session: Session,
    env: SourcesEnv,
    content: bytes,
    domain: DataSourceDomain = DataSourceDomain.LABOR,
) -> FileInspection:
    service = DataSourcesService(db_session, TenantContext(env.workspace.id))
    return service.understand_file(
        env.property.id,
        domain,
        filename="file.xlsx",
        content=content,
        answers=UnderstandAnswers(),
    )


def _which(db_session: Session, env: SourcesEnv, columns: dict[str, str], month: int = 11) -> Any:
    """The family Smart Import finds a file to be (None: none, or it could not be told)."""
    info = _inspect(db_session, env, xlsx_of(columns, month=month)).learning
    assert info is not None
    return info


def _nothing_asked(api_client: TestClient, env: SourcesEnv, columns: dict[str, str]) -> None:
    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", xlsx_of(columns, month=11))
    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == [], (
        f"{list(columns)}: {u['level']} {[q['id'] for q in u['questions']]}"
    )


# --- learn A, learn B in the same property and kind of data ---


def test_a_second_structure_taught_in_the_same_source_is_a_family_of_its_own(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    first = _store(db_session, env)
    a = first.families[0]

    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    store = _store(db_session, env)
    assert len(store.families) == 2
    assert _family(store, a.id).model_dump(exclude={"touched"}) == a.model_dump(exclude={"touched"})
    b = next(m for m in store.families if m.id != a.id)
    assert b.mapped["work_date"] == "data" and b.person == {
        "planned_hours": "ore 1",
        "actual_hours": "ore 2",
    }
    assert store.current == b.id  # the saved matching of the profile is the last import's


def test_the_first_family_is_still_recognised_after_the_second_one_was_taught(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _nothing_asked(api_client, env, RECEPTION)
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    # A -> B -> A: the one taught first comes back, with its own meaning of the hours
    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=11))

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []
    fields = {r["origin"]["detail"]: r["field"] for r in u["recognized"]}
    assert (fields["Ore A"], fields["Ore B"]) == ("planned_hours", "actual_hours")
    info = _which(db_session, env, RECEPTION)
    store = _store(db_session, env)
    assert info.match is not None and info.match.explain().startswith("EXACT (NONE): 4/4")
    assert info.family == info.memory.id and info.memory is not None
    assert info.memory.mapped["planned_hours"] == "ore a" and store.current != info.memory.id


def test_the_second_family_is_recognised_too_and_its_own_meaning_is_kept(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RESTAURANT, month=11))

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == []
    fields = {r["origin"]["detail"]: r["field"] for r in u["recognized"]}
    assert (fields["Ore 1"], fields["Ore 2"]) == ("planned_hours", "actual_hours")


# --- learn C; alternate A, B, C ---


def test_a_third_family_does_not_displace_the_first_two(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    _teach(api_client, env, SEASONAL, SEASONAL_SAYS, MONTH["seasonal"])

    store = _store(db_session, env)

    assert len(store.families) == 3 and len({m.id for m in store.families}) == 3
    for columns in (RECEPTION, RESTAURANT, SEASONAL):
        _nothing_asked(api_client, env, columns)


def test_the_three_families_alternate_in_any_order_and_nothing_is_ever_asked_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    _teach(api_client, env, SEASONAL, SEASONAL_SAYS, MONTH["seasonal"])

    # A -> B -> C -> A -> C -> B, and then the other way round
    order = (RECEPTION, RESTAURANT, SEASONAL, RECEPTION, SEASONAL, RESTAURANT)
    for columns in (*order, *reversed(order)):
        _nothing_asked(api_client, env, columns)
    seen = {_which(db_session, env, c).memory.id for c in (RECEPTION, RESTAURANT, SEASONAL)}
    assert len(seen) == 3


# --- the lookalike: two families one column apart ---


def test_two_families_one_column_apart_are_told_apart(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, NIGHT, NIGHT_SAYS, MONTH["night"])

    reception = _which(db_session, env, RECEPTION)
    night = _which(db_session, env, NIGHT)

    assert reception.memory is not None and night.memory is not None
    assert reception.memory.id != night.memory.id and not reception.ambiguous
    assert reception.memory.mapped["actual_hours"] == "ore b"
    assert night.memory.mapped["actual_hours"] == "ore c"
    _nothing_asked(api_client, env, RECEPTION)
    _nothing_asked(api_client, env, NIGHT)
    _nothing_asked(api_client, env, same_columns_with(RECEPTION, add={"Note": "note"}))
    _nothing_asked(api_client, env, same_columns_with(NIGHT, move=("Settore", 0)))


@pytest.mark.parametrize(
    "columns",
    [
        {"Giorno": "day", "Ore A": "planned", "Settore": "dept"},  # neither tells them apart
        {"Settore": "dept", "Ore A": "planned", "Giorno": "day"},
        {
            "Giorno": "day",
            "Ore A": "planned",
            "Settore": "dept",
            "Ore B": "actual",
            "Ore C": "junk",
        },
    ],
    ids=["no second hours column", "reordered", "both second columns"],
)
def test_a_file_that_could_be_either_family_reuses_nothing_and_asks(
    api_client: TestClient, db_session: Session, env: SourcesEnv, columns: dict[str, str]
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, NIGHT, NIGHT_SAYS, MONTH["night"])

    info = _which(db_session, env, columns)
    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(columns, month=11))

    assert info.ambiguous and info.memory is None and info.match is None and info.reused == ()
    assert info.family is None and info.known == 2 and info.eligible == 2
    u = body["understanding"]
    automatic = u["level"] == "READY" and not u["questions"] and not u["blockers"]
    assert not automatic  # never settled by a guess: the person is asked as for any new source


def test_confirming_a_file_that_could_be_either_starts_a_third_family_and_changes_neither(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, NIGHT, NIGHT_SAYS, MONTH["night"])
    before = {m.id: m.model_dump(exclude={"touched"}) for m in _store(db_session, env).families}
    neither = {"Giorno": "day", "Ore A": "planned", "Settore": "dept"}

    _teach(api_client, env, neither, {"column_fields": {"Ore A": "planned_hours"}}, 5)

    store = _store(db_session, env)
    assert len(store.families) == 3
    for family_id, dumped in before.items():
        assert _family(store, family_id).model_dump(exclude={"touched"}) == dumped
    # and now that file is a family of its own: it is recognised, and so are the other two
    for columns in (neither, RECEPTION, NIGHT):
        _nothing_asked(api_client, env, columns)


# --- drift in one family, the others unchanged ---


def test_a_drifted_file_of_the_first_family_is_that_family_not_a_neighbour(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    a = _which(db_session, env, RECEPTION).memory
    assert a is not None

    drifted = same_columns_with(
        same_columns_with(RECEPTION, move=("Settore", 0)), add={"Colonna extra": "junk"}
    )  # reordered + a junk column
    info = _which(db_session, env, drifted)

    assert info.memory is not None and info.memory.id == a.id
    assert info.match is not None and info.match.structure.value == "COMPATIBLE"
    _nothing_asked(api_client, env, drifted)


def test_the_second_family_is_unchanged_while_the_first_drifts(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    before = {m.id: m.model_dump(exclude={"touched"}) for m in _store(db_session, env).families}
    drifted = same_columns_with(RECEPTION, add={"Annotazioni": "note"})

    _nothing_asked(api_client, env, drifted)
    info = _which(db_session, env, RESTAURANT)

    assert info.match is not None and info.match.drift.value == "NONE"
    store = _store(db_session, env)
    assert {m.id: m.model_dump(exclude={"touched"}) for m in store.families} == before


def test_a_family_that_grew_stays_the_same_family(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    a_id = _which(db_session, env, RECEPTION).memory.id
    grown = same_columns_with(RECEPTION, add={"Pausa": "junk"})

    # (memory already reads it: the person only confirms what they said before)
    _teach(api_client, env, grown, RECEPTION_SAYS, 5, asks=False)

    store = _store(db_session, env)
    assert len(store.families) == 2  # not a third: the first one, one column richer
    first = _family(store, a_id)
    assert "pausa" in first.header_keys()  # its structure grew...
    assert (
        first.revision == 1 and first.mapped["planned_hours"] == "ore a"
    )  # ...its meaning did not
    _nothing_asked(api_client, env, RECEPTION)  # and the old shape still reads the same way
    _nothing_asked(api_client, env, grown)


def test_a_file_that_lacks_a_remembered_column_is_a_family_of_its_own_not_a_rewrite(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    a = _store(db_session, env).families[0]
    smaller = same_columns_with(RECEPTION, drop="Ore B")  # the actual hours are not in this export

    # (memory already reads what is left of it: the person confirms it, and that is a new family)
    _teach(api_client, env, smaller, {"column_fields": {"Ore A": "planned_hours"}}, 5, asks=False)

    store = _store(db_session, env)
    assert len(store.families) == 2  # not a rewrite of the first: a second structure beside it
    assert _family(store, a.id).model_dump(exclude={"touched"}) == a.model_dump(exclude={"touched"})
    _nothing_asked(api_client, env, RECEPTION)  # the full export is still recognised, as taught
    _nothing_asked(api_client, env, smaller)


# --- correction is local to the family ---


def test_a_correction_in_one_family_does_not_touch_another(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    store = _store(db_session, env)
    a_id = _which(db_session, env, RECEPTION).memory.id
    b_id = _which(db_session, env, RESTAURANT).memory.id
    b_before = _family(store, b_id).model_dump(exclude={"touched"})
    swapped = {"column_fields": {"Ore A": "actual_hours", "Ore B": "planned_hours"}}
    november = xlsx_of(RECEPTION, month=11)

    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", november, swapped)
    done = import_mapped(
        api_client,
        env,
        LABOR,
        "turni-novembre.xlsx",
        november,
        body["proposal"],
        snapshot="2026-11-30",
    )

    assert done.json()["succeeded"] is True
    after = _store(db_session, env)
    corrected = _family(after, a_id)
    assert corrected.revision == 2 and corrected.person["actual_hours"] == "ore a"
    assert [h["person"] for h in corrected.history] == [
        {"planned_hours": "ore a", "actual_hours": "ore b"}
    ]
    assert len(after.families) == 2
    assert _family(after, b_id).model_dump(exclude={"touched"}) == b_before  # exactly as it was
    _nothing_asked(api_client, env, RESTAURANT)
    december = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=12))
    fields = {r["origin"]["detail"]: r["field"] for r in december["understanding"]["recognized"]}
    assert (fields["Ore A"], fields["Ore B"]) == ("actual_hours", "planned_hours")


def test_an_import_from_memory_marks_the_family_in_use_and_changes_nothing_else(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    a_id = _which(db_session, env, RECEPTION).memory.id
    before = {m.id: m.model_dump(exclude={"touched"}) for m in _store(db_session, env).families}
    november = xlsx_of(RECEPTION, month=11, rows=20)
    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", november)

    done = import_mapped(
        api_client, env, LABOR, "turni-novembre.xlsx", november, body["proposal"],
        snapshot="2026-11-30",
    )  # fmt: skip

    assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is True
    store = _store(db_session, env)
    assert store.current == a_id  # the profile now holds this family's matching
    assert {m.id: m.model_dump(exclude={"touched"}) for m in store.families} == before
    assert _family(store, a_id).origin == Via.ANSWERS and _family(store, a_id).revision == 1


def test_the_saved_matching_of_another_family_is_not_applied_to_a_file_holding_all_its_columns(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    """The profile keeps the matching of the LAST import. A smaller family, read the other way round
    (the hours swapped), is all inside the bigger one's file: its saved matching "fits" it - and
    would read the hours of the bigger family wrong."""
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    smaller = same_columns_with(RECEPTION, drop="Settore")  # (no department: all front office)
    swapped = {
        "column_fields": {"Ore A": "actual_hours", "Ore B": "planned_hours"},
        "department_value": "FRONT_OFFICE",
    }
    _teach(api_client, env, smaller, swapped, MONTH["restaurant"], asks=False, confirmed=True)
    store = _store(db_session, env)
    small_id = _which(db_session, env, smaller).memory.id
    assert len(store.families) == 2 and store.current == small_id

    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=11))

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == []
    fields = {r["origin"]["detail"]: r["field"] for r in u["recognized"]}
    assert (fields["Ore A"], fields["Ore B"]) == (
        "planned_hours",
        "actual_hours",
    )  # as taught for it
    assert fields["Settore"] == "role"
    # ...and the smaller family still reads its own way
    small = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(smaller, month=11), None)
    fields = {r["origin"]["detail"]: r["field"] for r in small["understanding"]["recognized"]}
    assert (fields["Ore A"], fields["Ore B"]) == ("actual_hours", "planned_hours")


def test_the_matching_saved_for_one_family_is_never_applied_to_another(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    store = _store(db_session, env)
    b_id = _which(db_session, env, RESTAURANT).memory.id
    assert store.current == b_id  # the saved matching of the profile is the restaurant's

    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=11))

    # ...and still the reception file is read as the reception's family, column by column
    fields = {r["origin"]["detail"]: r["field"] for r in body["understanding"]["recognized"]}
    assert fields["Ore A"] == "planned_hours" and fields["Ore B"] == "actual_hours"
    assert "Ore 1" not in fields and "Ore 2" not in fields
    assert body["understanding"]["level"] == "READY"


# --- Manual V2 ---


def test_a_matching_built_by_hand_for_a_new_structure_is_a_family_beside_the_others(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    a = _store(db_session, env).families[0]

    _teach_by_hand(api_client, env, BY_HAND, MONTH["by hand"])

    store = _store(db_session, env)
    assert len(store.families) == 2
    assert _family(store, a.id).model_dump(exclude={"touched"}) == a.model_dump(exclude={"touched"})
    by_hand_family = _family(store, store.current)
    assert by_hand_family.origin == Via.MANUAL and by_hand_family.person == by_hand_family.mapped
    assert by_hand_family.mapped["planned_hours"] == "h1"
    _nothing_asked(api_client, env, BY_HAND)
    _nothing_asked(api_client, env, RECEPTION)


def test_a_manual_matching_of_the_same_structure_corrects_its_family_and_no_other(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach_by_hand(api_client, env, BY_HAND, MONTH["by hand"])
    store = _store(db_session, env)
    hand_id = store.current
    a_before = _family(store, _which(db_session, env, RECEPTION).memory.id).model_dump(
        exclude={"touched"}
    )
    november = xlsx_of(BY_HAND, month=11)
    swapped = decision(
        {"Dt": "work_date", "H1": "actual_hours", "H2": "planned_hours", "Rep": "role"}
    )

    done = import_mapped(
        api_client, env, LABOR, "turni.xlsx", november, by_hand(swapped), snapshot="2026-11-28"
    )

    assert done.json()["succeeded"] is True
    after = _store(db_session, env)
    assert len(after.families) == 2 and _family(after, hand_id).revision == 2
    assert _family(after, hand_id).mapped["actual_hours"] == "h1"
    reception = _which(db_session, env, RECEPTION).memory
    assert reception is not None
    assert reception.model_dump(exclude={"touched"}) == a_before


# --- isolation ---


def test_the_families_of_one_property_never_reach_another_even_with_the_same_headers(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    env: SourcesEnv,
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    sister = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)

    for columns in (RECEPTION, RESTAURANT):
        body = understand(api_client, sister, LABOR, "turni.xlsx", xlsx_of(columns, month=11))
        assert body["understanding"]["level"] == "ASK"  # asked all over again
        assert [q["kind"] for q in body["understanding"]["questions"]] == ["COLUMN_MEANING"] * 2
    info = (
        DataSourcesService(db_session, TenantContext(env.workspace.id))
        .understand_file(
            sister.property.id,
            DataSourceDomain.LABOR,
            filename="turni.xlsx",
            content=xlsx_of(RECEPTION, month=11),
            answers=UnderstandAnswers(),
        )
        .learning
    )
    assert info is not None and info.memory is None and info.known == 0 and info.reused == ()


def test_each_property_has_its_own_families(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    sister = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, sister, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    _nothing_asked(api_client, env, RECEPTION)
    _nothing_asked(api_client, sister, RESTAURANT)
    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RESTAURANT, month=11))
    assert body["understanding"]["level"] == "ASK"  # the restaurant is the sister's, not this one's
    body = understand(api_client, sister, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=11))
    assert body["understanding"]["level"] == "ASK"
    assert len(_store(db_session, env).families) == 1


def test_what_was_learned_for_staff_is_never_applied_to_another_kind_of_data(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    for columns in (RECEPTION, RESTAURANT):
        info = _inspect(
            db_session, env, xlsx_of(columns, month=11), DataSourceDomain.BOOKINGS
        ).learning
        assert info is not None and info.memory is None and info.known == 0 and info.reused == ()


def test_a_family_that_says_it_belongs_to_another_kind_of_data_is_ignored_the_others_are_not(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learning = json.loads(json.dumps(profile.format_options["learning"]))
    a_id = _which(db_session, env, RECEPTION).memory.id
    for family in learning["families"]:
        if family["id"] == a_id:
            family["domain"] = "BOOKINGS"
    profile.format_options = {**profile.format_options, "learning": learning}
    db_session.flush()

    info = _which(db_session, env, RECEPTION)
    assert info.reused == () and info.family is None  # nothing reused, and not as that family
    assert info.memory is None or info.memory.id != a_id
    _nothing_asked(api_client, env, RESTAURANT)


# --- what is kept ---


def test_nothing_personal_is_kept_in_any_family(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    with_names = {
        "Giorno": "day",
        "Nome dipendente": "people",
        "Ore A": "planned",
        "Ore B": "actual",
        "Settore": "dept",
    }
    roster = {
        "Data": "day",
        "Mario Rossi": "junk",
        "Giulia Bianchi": "junk",
        "Ore 1": "planned",
        "Ore 2": "actual",
        "Area": "dept",
    }
    _teach(
        api_client, env, with_names, RECEPTION_SAYS, MONTH["reception"], "Turni-Mario-Rossi.xlsx"
    )
    _teach(
        api_client, env, roster, RESTAURANT_SAYS, MONTH["restaurant"], "Turni-Giulia-Bianchi.xlsx"
    )

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    blob = json.dumps(
        {
            "column_mapping": profile.column_mapping,
            "role_mapping": profile.role_mapping,
            "format_options": profile.format_options,
        },
        ensure_ascii=False,
    ).casefold()
    for name in PEOPLE:
        assert name.casefold() not in blob
    for fragment in (
        "rossi", "mario", "giulia", "bianchi", "turni-mario", "turni-giulia", ".xlsx",
        "nome dipendente",
    ):  # fmt: skip
        assert fragment not in blob
    store = _store(db_session, env)
    assert len(store.families) == 2
    for family in store.families:
        assert [key for key, _ in family.shape].count("~") >= 1 or len(family.shape) == 5
        assert family.id.isalnum()  # a number, never a file name
    # and both are still recognised next month
    _nothing_asked(api_client, env, with_names)
    _nothing_asked(api_client, env, roster)


# --- compatibility, damage ---


def test_the_section_written_before_there_were_families_is_read_as_a_source_with_one(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    only = profile.format_options["learning"]["families"][0]
    profile.format_options = {**profile.format_options, "learning": only}  # the flat memory
    db_session.flush()

    _nothing_asked(api_client, env, RECEPTION)
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])

    store = _store(db_session, env)
    assert len(store.families) == 2  # the old memory became the first family of the source
    _nothing_asked(api_client, env, RECEPTION)
    _nothing_asked(api_client, env, RESTAURANT)


def test_a_damaged_family_is_read_again_and_the_others_still_work(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    _teach(api_client, env, RESTAURANT, RESTAURANT_SAYS, MONTH["restaurant"])
    a_id = _which(db_session, env, RECEPTION).memory.id
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learning = json.loads(json.dumps(profile.format_options["learning"]))
    for family in learning["families"]:
        if family["id"] == a_id:
            family["shape"] = "damaged"
    profile.format_options = {**profile.format_options, "learning": learning}
    db_session.flush()

    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION, month=11))

    assert body["understanding"]["level"] == "ASK"  # asked again, like any source nobody taught
    _nothing_asked(api_client, env, RESTAURANT)


def test_a_source_with_families_saves_nothing_when_the_person_leaves_remember_off(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, RECEPTION, RECEPTION_SAYS, MONTH["reception"])
    before = _store(db_session, env)
    content = xlsx_of(RESTAURANT, month=MONTH["restaurant"])
    answered = understand(api_client, env, LABOR, "turni.xlsx", content, RESTAURANT_SAYS)

    done = import_mapped(
        api_client, env, LABOR, "turni.xlsx", content, answered["proposal"],
        save=False, snapshot="2026-09-28",
    )  # fmt: skip

    assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is False
    assert _store(db_session, env) == before  # not even a second family


def test_the_bookings_profile_keeps_families_too(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    pms = {
        "Pratica": "ref", "Creata": "booked", "Dal": "checkin", "Al": "checkout",
        "Esito": "status", "Unita": "rooms", "Valore": "revenue", "Fonte": "channel",
    }  # fmt: skip
    report = {
        "Cod": "ref", "Emissione": "booked", "Arrivo": "checkin", "Partenza": "checkout",
        "Stato": "status", "Cam": "rooms", "Importo": "revenue", "Origine": "channel",
    }  # fmt: skip
    pms_says = decision(
        {
            "Pratica": "source_record_id", "Creata": "booked_at", "Dal": "check_in",
            "Al": "check_out", "Esito": "status", "Unita": "rooms", "Valore": "room_revenue",
            "Fonte": "channel",
        }
    )  # fmt: skip
    report_says = decision(
        {
            "Cod": "source_record_id", "Emissione": "booked_at", "Arrivo": "check_in",
            "Partenza": "check_out", "Stato": "status", "Cam": "rooms", "Importo": "room_revenue",
            "Origine": "channel",
        }
    )  # fmt: skip
    for columns, says in ((pms, pms_says), (report, report_says)):
        done = import_mapped(
            api_client, env, BOOKINGS, "pren.xlsx", xlsx_of(columns, month=10), by_hand(says)
        )
        assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is True

    store = _store(db_session, env, BookingMappingProfile)
    assert len(store.families) == 2
    for columns in (pms, report, pms):
        body = understand(api_client, env, BOOKINGS, "pren.xlsx", xlsx_of(columns, month=11))
        u = body["understanding"]
        assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []

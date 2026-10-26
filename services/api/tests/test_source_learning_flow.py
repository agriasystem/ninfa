"""Source Learning, end to end: ask once, remember the confirmation, ask less the next time.

Real files through the real API and the real database (rolled back). The first time a source arrives
Smart Import asks; the person answers (or builds the matching by hand); the server recomputes READY;
the explicit import writes and remembers what the person confirmed. The next file of the same source
is recognised and the question that was answered is not asked again - unless THIS file contradicts
the memory, in which case the current document wins.

No model, no embedding, no external service: `IMPORT_UNDERSTANDING_MODE` is off for the whole suite.
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
from app.modules.data_sources.source_learning import Drift, Structure, Trust, Via, parse_memory
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from app.modules.labor.models import LaborMappingProfile
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import by_hand, decision, import_mapped, profiles_of, understand
from tests.source_learning_support import PEOPLE, same_columns_with, xlsx_of
from tests.support import BookingFactory

LABOR = "LABOR"
BOOKINGS = "BOOKINGS"
# A staff export with house-specific hour headers: the engine cannot tell which is which.
STAFF = {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"}
ANSWERS = {"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}}
# A bookings export in the house's own words: the engine cannot read it, a person matches it.
RESERVATIONS = {
    "Pratica": "ref",
    "Creata": "booked",
    "Dal": "checkin",
    "Al": "checkout",
    "Esito": "status",
    "Unita": "rooms",
    "Valore": "revenue",
    "Fonte": "channel",
}
RESERVATIONS_DECISION = decision(
    {
        "Pratica": "source_record_id",
        "Creata": "booked_at",
        "Dal": "check_in",
        "Al": "check_out",
        "Esito": "status",
        "Unita": "rooms",
        "Valore": "room_revenue",
        "Fonte": "channel",
    },
    date_order="DMY",
)


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _origin_of(body: dict[str, Any], field: str) -> str:
    return str(
        next(
            r["origin"]["kind"] for r in body["understanding"]["recognized"] if r["field"] == field
        )
    )


def _inspect(
    db_session: Session,
    env: SourcesEnv,
    domain: DataSourceDomain,
    content: bytes,
    answers: dict[str, Any] | None = None,
) -> FileInspection:
    """What Smart Import understands of a file, seen from inside (with what Source Learning did)."""
    service = DataSourcesService(db_session, TenantContext(env.workspace.id))
    return service.understand_file(
        env.property.id,
        domain,
        filename="file.xlsx",
        content=content,
        answers=UnderstandAnswers.model_validate(answers or {}),
    )


def _memory(db_session: Session, env: SourcesEnv, model: Any = LaborMappingProfile) -> Any:
    (profile,) = profiles_of(db_session, env, model)
    return parse_memory(profile.format_options.get("learning"))


def _teach_staff(
    api_client: TestClient,
    env: SourcesEnv,
    *,
    columns: dict[str, str] = STAFF,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """The first time: the file asks, the person answers, the explicit import remembers."""
    content = xlsx_of(columns, month=10)
    asked = understand(api_client, env, LABOR, "turni-ottobre.xlsx", content)
    assert asked["understanding"]["level"] == "ASK", "the file must ask for there to be a question"
    answered = understand(api_client, env, LABOR, "turni-ottobre.xlsx", content, ANSWERS)
    assert answered["understanding"]["level"] == "READY"
    done = import_mapped(
        api_client,
        env,
        LABOR,
        "turni-ottobre.xlsx",
        content,
        answered["proposal"],
        snapshot=snapshot,
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    assert done.json()["configuration_saved"] is True
    return asked


# --- the main test: ask once ---


def test_the_first_time_asks_the_person_answers_and_the_import_remembers_it(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    asked = _teach_staff(api_client, env)

    assert _kinds(asked) == ["COLUMN_MEANING", "COLUMN_MEANING"]
    learned = _memory(db_session, env)
    assert learned is not None
    assert (learned.trust, learned.origin, learned.revision) == (Trust.PERSON, Via.ANSWERS, 1)
    assert learned.person == {"planned_hours": "ore a", "actual_hours": "ore b"}
    assert learned.mapped["work_date"] == "giorno" and learned.mapped["role"] == "settore"
    assert learned.domain == "LABOR" and len(learned.fingerprint) == 16


def test_the_second_time_the_same_source_is_recognised_and_asks_nothing_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    november = xlsx_of(STAFF, month=11, rows=20)

    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", november)

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == []  # zero repeated mapping questions
    assert (_origin_of(body, "planned_hours"), _origin_of(body, "actual_hours")) == (
        "PROFILE",
        "PROFILE",
    )
    info = _inspect(db_session, env, DataSourceDomain.LABOR, november).learning
    assert info is not None and info.match is not None
    assert (info.match.structure, info.match.drift) == (Structure.EXACT, Drift.NONE)
    assert sorted(info.reused) == ["Ore A", "Ore B"]
    assert info.match.explain().startswith("EXACT (NONE): 4/4 columns coincide")


def test_the_reused_decision_imports_and_confirms_nothing_new(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env, snapshot="2026-10-30")
    november = xlsx_of(STAFF, month=11, rows=20)
    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", november)

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
    learned = _memory(db_session, env)
    assert learned is not None and (learned.revision, learned.trust) == (1, Trust.PERSON)


def test_what_the_person_said_once_about_the_whole_file_is_kept_and_verified_by_the_server(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    columns = {"Giorno": "day", "Gruppo di lavoro": "dept", "Ore previste": "planned"}
    october = xlsx_of(columns, month=10)
    asked = understand(api_client, env, LABOR, "turni-ottobre.xlsx", october)
    assert _kinds(asked) == ["DEPARTMENT_ROWS"]
    answered = understand(
        api_client, env, LABOR, "turni-ottobre.xlsx", october, {"department_value": "FRONT_OFFICE"}
    )
    done = import_mapped(
        api_client, env, LABOR, "turni-ottobre.xlsx", october, answered["proposal"],
        snapshot="2026-10-30",
    )  # fmt: skip
    assert done.json()["succeeded"] is True
    learned = _memory(db_session, env)
    assert learned is not None and learned.answers == {"department_value": "FRONT_OFFICE"}

    november = xlsx_of(columns, month=11, rows=20)
    body = understand(api_client, env, LABOR, "turni-novembre.xlsx", november)

    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []
    assert body["proposal"]["constants"]["labor_category"] == "FRONT_OFFICE"
    # the decision carries the server's own reference: it is verified and imported like any other
    again = import_mapped(
        api_client, env, LABOR, "turni-novembre.xlsx", november, body["proposal"],
        snapshot="2026-11-30",
    )  # fmt: skip
    assert again.json()["succeeded"] is True
    reused = _memory(db_session, env)
    assert reused is not None and reused.revision == 1  # nothing new was confirmed


# --- harmless changes ---


@pytest.mark.parametrize(
    ("change", "drift"),
    [
        ({"move": ("Settore", 0)}, Drift.COSMETIC),  # another order
        ({"move": ("Ore B", 1)}, Drift.COSMETIC),
        ({"add": {"Note": "note"}}, Drift.ADDITIVE),  # a junk column
        ({"add": {"Codice": "junk", "Note": "note"}}, Drift.ADDITIVE),
    ],
    ids=["settore first", "ore b second", "junk", "two junk"],
)
def test_reordered_columns_and_extra_junk_are_still_the_same_source_and_ask_nothing(
    api_client: TestClient,
    db_session: Session,
    env: SourcesEnv,
    change: dict[str, Any],
    drift: Drift,
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(same_columns_with(STAFF, **change), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    assert match is not None and match.drift == drift


@pytest.mark.parametrize("sheet", ["Novembre", "Turni 11-2026", "Foglio1"])
def test_the_sheet_name_of_another_month_does_not_make_it_another_source(
    api_client: TestClient, env: SourcesEnv, sheet: str
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(STAFF, month=11, sheet=sheet)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []


def test_a_cosmetic_header_change_is_followed_when_the_engine_reads_it_the_same(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(same_columns_with(STAFF, rename=("Settore", "Reparto")), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    assert match is not None and match.structure == Structure.EXACT
    assert match.drift in (Drift.COSMETIC, Drift.NONE)


# --- reuse what is still proven, ask what changed ---


def test_a_new_column_asks_nothing_and_the_known_ones_are_still_reused(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(same_columns_with(STAFF, add={"Turno": "note"}), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []
    assert _origin_of(body, "planned_hours") == "PROFILE"
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    assert match is not None and (match.drift, match.new_columns) == (Drift.ADDITIVE, 1)


def test_a_known_column_that_disappears_is_asked_about_and_the_rest_is_reused(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(same_columns_with(STAFF, drop="Ore B"), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    # "Ore A" is still proven by the person's earlier answer; nothing is guessed for "Ore B"
    assert _origin_of(body, "planned_hours") == "PROFILE"
    assert "actual_hours" not in {r["field"] for r in body["understanding"]["recognized"]}
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    assert match is not None and match.drift == Drift.MISSING
    assert match.missing == (("actual_hours", "ore b"),)
    assert match.proven == {"Ore A": "planned_hours"}


# --- the current document wins ---


def test_a_column_that_now_holds_something_else_is_asked_about_not_reused(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    # "Ore A" used to hold hours; this month it holds words
    later = xlsx_of(same_columns_with(STAFF, retype=("Ore A", "note")), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    u = body["understanding"]
    assert u["level"] == "ASK"  # a contradiction is a question, never an automatic reading
    assert [q["id"] for q in u["questions"]] == ["CONFIRM:Ore A"]
    # "is «Ore A» still the planned hours?" - the person answers yes, or looks at the columns
    assert (u["questions"][0]["kind"], u["questions"][0]["candidate"]) == (
        "COLUMN_MEANING",
        "planned_hours",
    )
    reused = {r["field"] for r in u["recognized"] if r["origin"]["kind"] == "PROFILE"}
    assert reused == {"actual_hours"}  # "Ore B" is still proven; "Ore A" is not
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    assert match is not None and match.drift == Drift.SEMANTIC_CONFLICT
    assert [(c.header, c.reason) for c in match.conflicts] == [("Ore A", "VALUE_CLASS")]
    assert "Ore A" not in match.proven


def test_a_column_that_became_personal_data_is_never_used(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    # "Ore A" used to hold hours; this month it holds the names of the staff (the value wins)
    later = xlsx_of(same_columns_with(STAFF, retype=("Ore A", "people")), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    u = body["understanding"]
    assert "Ore A" not in {r["origin"]["detail"] for r in u["recognized"]}
    assert not any(q["id"] == "CONFIRM:Ore A" for q in u["questions"])  # nothing to confirm there
    match = _inspect(db_session, env, DataSourceDomain.LABOR, later).learning.match  # type: ignore[union-attr]
    # a column that is personal data is out of the comparison altogether: it is as if it were gone
    assert match is not None and match.drift == Drift.MISSING
    assert match.missing == (("planned_hours", "ore a"),) and match.conflicts == ()
    assert "Ore A" not in match.proven


@pytest.mark.parametrize("retype", ["note", "day", "dept"])
def test_a_conflicting_memory_can_never_make_a_file_ready_by_itself(
    api_client: TestClient, env: SourcesEnv, retype: str
) -> None:
    _teach_staff(api_client, env)
    later = xlsx_of(same_columns_with(STAFF, retype=("Ore A", retype)), month=11)

    body = understand(api_client, env, LABOR, "turni.xlsx", later)

    u = body["understanding"]
    automatic = u["level"] == "READY" and not u["questions"] and not u["blockers"]
    assert not automatic


def test_the_person_can_still_confirm_a_column_the_memory_doubted(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env, snapshot="2026-10-30")
    later = xlsx_of(same_columns_with(STAFF, retype=("Ore A", "junk")), month=11)  # still numbers
    asked = understand(api_client, env, LABOR, "turni.xlsx", later)
    # numbers, but not hours (the fit says so): the memory is not applied until the person says
    assert asked["understanding"]["level"] in ("ASK", "READY")

    answered = understand(
        api_client, env, LABOR, "turni.xlsx", later, {"column_fields": {"Ore A": "planned_hours"}}
    )

    assert answered["understanding"]["level"] == "READY"
    assert _origin_of(answered, "planned_hours") == "USER"  # now it is the person's word


def test_a_file_that_is_mostly_something_else_reuses_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    other = xlsx_of({"Giorno": "day", "Valore": "junk", "Altro": "note"}, month=11)

    info = _inspect(db_session, env, DataSourceDomain.LABOR, other).learning

    assert info is not None and info.match is not None
    assert (info.match.structure, info.match.drift) == (Structure.DIFFERENT, Drift.MAJOR_CHANGE)
    assert info.reused == ()


# --- correction ---


def test_a_correction_by_answering_again_prevails_over_the_old_confirmation(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env, snapshot="2026-10-30")
    november = xlsx_of(STAFF, month=11)
    swapped = {"column_fields": {"Ore A": "actual_hours", "Ore B": "planned_hours"}}

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
    learned = _memory(db_session, env)
    assert learned is not None and learned.revision == 2
    assert learned.person == {"actual_hours": "ore a", "planned_hours": "ore b"}
    assert [h["person"] for h in learned.history] == [
        {"planned_hours": "ore a", "actual_hours": "ore b"}
    ]  # the old confirmation is history, not overwritten
    december = understand(api_client, env, LABOR, "turni-dicembre.xlsx", xlsx_of(STAFF, month=12))
    fields = {r["origin"]["detail"]: r["field"] for r in december["understanding"]["recognized"]}
    assert (fields["Ore A"], fields["Ore B"]) == ("actual_hours", "planned_hours")


def test_a_correction_by_hand_prevails_too(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env, snapshot="2026-10-30")
    november = xlsx_of(STAFF, month=11)
    proposal = understand(api_client, env, LABOR, "turni-novembre.xlsx", november)["proposal"]
    columns = {c["header"]: c["field"] for c in proposal["columns"]}
    columns.update({"Ore A": "actual_hours", "Ore B": "planned_hours"})

    done = import_mapped(
        api_client,
        env,
        LABOR,
        "turni-novembre.xlsx",
        november,
        by_hand(decision(columns)),
        snapshot="2026-11-30",
    )

    assert done.json()["succeeded"] is True
    learned = _memory(db_session, env)
    assert learned is not None and (learned.revision, learned.origin) == (2, Via.MANUAL)
    assert learned.mapped["actual_hours"] == "ore a" and learned.mapped["planned_hours"] == "ore b"


# --- Manual V2 learning ---


def test_a_matching_built_by_hand_is_remembered_for_the_next_file(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    first = xlsx_of(RESERVATIONS, month=10)
    asked = understand(api_client, env, BOOKINGS, "pren-ottobre.xlsx", first)
    assert asked["understanding"]["level"] in ("MANUAL", "BLOCKED")  # the engine cannot read it

    done = import_mapped(
        api_client, env, BOOKINGS, "pren-ottobre.xlsx", first, by_hand(RESERVATIONS_DECISION)
    )
    assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is True

    learned = _memory(db_session, env, BookingMappingProfile)
    assert learned is not None and (learned.trust, learned.origin) == (Trust.PERSON, Via.MANUAL)
    assert learned.mapped["check_in"] == "dal" and learned.person == learned.mapped
    november = xlsx_of(RESERVATIONS, month=11, rows=20)
    body = understand(api_client, env, BOOKINGS, "pren-novembre.xlsx", november)
    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []
    assert _origin_of(body, "source_record_id") == "PROFILE"


def test_a_manual_memory_is_for_that_source_only_not_global(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    first = xlsx_of(RESERVATIONS, month=10)
    import_mapped(api_client, env, BOOKINGS, "p.xlsx", first, by_hand(RESERVATIONS_DECISION))
    sister = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)

    body = understand(api_client, sister, BOOKINGS, "p.xlsx", xlsx_of(RESERVATIONS, month=11))

    assert body["understanding"]["level"] != "READY"  # another property knows nothing of it


# --- isolation ---


def test_what_one_property_learned_does_not_reach_another_even_with_the_same_headers(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    other = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)
    november = xlsx_of(STAFF, month=11)

    body = understand(api_client, other, LABOR, "turni.xlsx", november)
    info = (
        DataSourcesService(db_session, TenantContext(env.workspace.id))
        .understand_file(
            other.property.id,
            DataSourceDomain.LABOR,
            filename="turni.xlsx",
            content=november,
            answers=UnderstandAnswers(),
        )
        .learning
    )

    assert body["understanding"]["level"] == "ASK"  # asked all over again
    assert _kinds(body) == ["COLUMN_MEANING", "COLUMN_MEANING"]
    assert info is not None and info.memory is None and info.match is None and info.reused == ()


def test_what_another_workspace_learned_does_not_reach_this_one(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
    env: SourcesEnv,
) -> None:
    _teach_staff(api_client, env)
    stranger = sources_env(factory, authenticated_as)  # another workspace, another property

    body = understand(api_client, stranger, LABOR, "turni.xlsx", xlsx_of(STAFF, month=11))

    assert body["understanding"]["level"] == "ASK"
    assert _kinds(body) == ["COLUMN_MEANING", "COLUMN_MEANING"]


def test_what_was_learned_for_staff_is_never_applied_to_another_kind_of_data(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    # the same headers, uploaded as bookings: the bookings source has no memory at all
    info = _inspect(db_session, env, DataSourceDomain.BOOKINGS, xlsx_of(STAFF, month=11)).learning

    assert info is not None and info.memory is None and info.match is None and info.reused == ()


def test_a_memory_that_claims_another_domain_is_ignored(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    profile.format_options = {
        **profile.format_options,
        "learning": {**profile.format_options["learning"], "domain": "bookings"},
    }
    db_session.flush()

    info = _inspect(db_session, env, DataSourceDomain.LABOR, xlsx_of(STAFF, month=11)).learning

    assert info is not None and info.memory is None and info.reused == ()


# --- trust ---


def test_a_file_the_engine_reads_alone_never_makes_a_trusted_memory(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    clear = {
        "Giorno": "day",
        "Ore previste": "planned",
        "Ore effettive": "actual",
        "Reparto": "dept",
    }
    content = xlsx_of(clear, month=10)
    body = understand(api_client, env, LABOR, "turni.xlsx", content)
    assert body["understanding"]["level"] == "READY" and body["understanding"]["questions"] == []

    done = import_mapped(api_client, env, LABOR, "turni.xlsx", content, body["proposal"])

    assert done.json()["configuration_saved"] is True
    learned = _memory(db_session, env)
    assert learned is not None and (learned.trust, learned.origin) == (Trust.ENGINE, Via.ENGINE)
    assert learned.person == {}  # nobody decided anything, so nothing is a person's decision
    info = _inspect(db_session, env, DataSourceDomain.LABOR, xlsx_of(clear, month=11)).learning
    assert info is not None and info.match is not None and info.reused == ()


def test_the_engine_never_replaces_what_a_person_confirmed(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env, snapshot="2026-10-30")
    before = _memory(db_session, env)
    clear = {
        "Giorno": "day",
        "Ore previste": "planned",
        "Ore effettive": "actual",
        "Reparto": "dept",
    }
    content = xlsx_of(clear, month=11)
    body = understand(api_client, env, LABOR, "turni-altri.xlsx", content)
    assert body["understanding"]["level"] == "READY"

    done = import_mapped(
        api_client, env, LABOR, "turni-altri.xlsx", content, body["proposal"], snapshot="2026-11-30"
    )

    assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is False
    assert _memory(db_session, env) == before  # what the person confirmed is untouched


def test_a_profile_saved_before_source_learning_is_not_trusted(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_staff(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    legacy = dict(profile.format_options)
    del legacy["learning"]
    profile.format_options = legacy
    db_session.flush()

    body = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=11))

    assert body["understanding"]["level"] == "ASK"  # nobody can tell who confirmed that profile
    assert _kinds(body) == ["COLUMN_MEANING", "COLUMN_MEANING"]


def test_not_saving_means_not_learning(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = xlsx_of(STAFF, month=10)
    answered = understand(api_client, env, LABOR, "turni.xlsx", content, ANSWERS)

    done = import_mapped(
        api_client, env, LABOR, "turni.xlsx", content, answered["proposal"], save=False
    )

    assert done.json()["succeeded"] is True and done.json()["configuration_saved"] is False
    assert profiles_of(db_session, env, LaborMappingProfile) == []


def test_an_answer_that_only_repeats_what_the_engine_read_clearly_trusts_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    clear = {
        "Giorno": "day",
        "Ore previste": "planned",
        "Ore effettive": "actual",
        "Reparto": "dept",
    }
    content = xlsx_of(clear, month=10)
    body = understand(api_client, env, LABOR, "turni.xlsx", content)
    forged = json.loads(json.dumps(body["proposal"]))
    # "I answered it": no question was ever asked about this column
    forged["smart_import"]["answers"] = {"column_fields": {"Ore previste": "planned_hours"}}

    done = import_mapped(api_client, env, LABOR, "turni.xlsx", content, forged)

    assert done.status_code == 200 and done.json()["succeeded"] is True
    learned = _memory(db_session, env)
    assert learned is not None and (learned.trust, learned.person) == (Trust.ENGINE, {})


# --- privacy ---


def test_nothing_personal_is_remembered_about_a_source(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    columns = {
        "Giorno": "day",
        "Nome dipendente": "people",
        "Ore A": "planned",
        "Ore B": "actual",
        "Settore": "dept",
    }
    content = xlsx_of(columns, month=10)
    answered = understand(
        api_client, env, LABOR, "Turni-Mario-Rossi-ottobre.xlsx", content, ANSWERS
    )
    done = import_mapped(
        api_client, env, LABOR, "Turni-Mario-Rossi-ottobre.xlsx", content, answered["proposal"]
    )
    assert done.json()["succeeded"] is True

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learned = parse_memory(profile.format_options["learning"])
    assert learned is not None
    stored = json.dumps(
        {
            "column_mapping": profile.column_mapping,
            "role_mapping": profile.role_mapping,
            "format_options": profile.format_options,
        },
        ensure_ascii=False,
    ).casefold()
    for name in PEOPLE:
        assert name.casefold() not in stored
    for fragment in ("rossi", "mario", "turni-mario", "ottobre.xlsx", "nome dipendente"):
        assert fragment not in stored
    assert ("~", "TEXT") in [tuple(item) for item in learned.shape]  # the placeholder, nothing else
    assert all("rossi" not in key for key, _ in learned.shape)


def test_a_personal_data_column_never_becomes_a_remembered_mapping(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    columns = {
        "Giorno": "day",
        "Nome dipendente": "people",
        "Ore A": "planned",
        "Ore B": "actual",
        "Settore": "dept",
    }
    content = xlsx_of(columns, month=10)
    answered = understand(api_client, env, LABOR, "t.xlsx", content, ANSWERS)
    import_mapped(api_client, env, LABOR, "t.xlsx", content, answered["proposal"])
    learned = _memory(db_session, env)
    assert learned is not None and "nome dipendente" not in learned.mapped.values()

    # next month the same names column is still personal data: untouched, never "reused"
    later = understand(api_client, env, LABOR, "t2.xlsx", xlsx_of(columns, month=11))

    assert "Nome dipendente" not in {
        r["origin"]["detail"] for r in later["understanding"]["recognized"]
    }

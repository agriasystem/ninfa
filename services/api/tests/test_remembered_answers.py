"""A wrong answer NINFA remembered can be corrected by the person who gave it, with no help.

    answered -> the next file does not ask -> corrected or forgotten -> the next file uses the new
    answer, or asks again -> nothing already imported is read again

Real files through the real API and database (rolled back). `Modificata` is the case that started
this, and nothing here knows it by name in production code: any word behaves the same.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingMappingProfile, BookingStatus
from app.modules.data_sources.remembered_answers import (
    STATUS_CHOICES,
    RememberedAnswersService,
    _word_id,
)
from app.modules.data_sources.source_learning import parse_learning
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.labor.models import LaborMappingProfile
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, profiles_of, understand
from tests.source_learning_support import xlsx_of
from tests.support import BookingFactory

BOOKINGS = "BOOKINGS"
LABOR = "LABOR"
HEADERS = [
    "Codice prenotazione",
    "Data prenotazione",
    "Check-in",
    "Check-out",
    "Camere",
    "Ricavo camere",
    "Canale",
    "Stato",
]
FIRST = date(2027, 3, 1)
MODIFICATA = {"labels": {"status_mapping": {"Modificata": "NO_SHOW"}}}


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def row(number: int, status: str = "Confermata") -> list[Any]:
    check_in = datetime.combine(FIRST + timedelta(days=number), datetime.min.time())
    return [
        f"P-{number:03d}",
        check_in - timedelta(days=30),
        check_in,
        check_in + timedelta(days=1),
        1,
        150,
        "Booking.com",
        status,
    ]


def bookings_file(*statuses: str, without: int | None = None) -> bytes:
    rows = [row(index, status) for index, status in enumerate(statuses) if index != without]
    return xlsx_bytes({"Prenotazioni": [HEADERS, *rows]})


WITH_MODIFICATA = bookings_file(
    "Confermata", "Confermata", "Confermata", "Modificata", "Modificata", "Confermata"
)


def _understand(
    client: TestClient, env: SourcesEnv, content: bytes, answers: dict[str, Any] | None = None
) -> dict[str, Any]:
    return understand(client, env, BOOKINGS, "pren.xlsx", content, answers)


def _questions(body: dict[str, Any]) -> list[str]:
    return [q["id"] for q in body["understanding"]["questions"]]


def _import(
    client: TestClient, env: SourcesEnv, content: bytes, answers: dict[str, Any] | None = None
) -> dict[str, Any]:
    understood = _understand(client, env, content, answers)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(client, env, BOOKINGS, "pren.xlsx", content, understood["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    body: dict[str, Any] = done.json()
    return body


def _source_id(session: Session, env: SourcesEnv) -> UUID:
    source = session.scalar(select(DataSource).where(DataSource.property_id == env.property.id))
    assert source is not None
    return source.id


def _url(env: SourcesEnv, source_id: UUID, answer: str | None = None) -> str:
    base = f"{env.base}/{source_id}/remembered-answers"
    return base if answer is None else f"{base}/{answer}"


def _remembered(client: TestClient, env: SourcesEnv, source_id: UUID) -> dict[str, Any]:
    response = client.get(_url(env, source_id))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body: dict[str, Any] = response.json()
    return body


def _word(body: dict[str, Any], label: str) -> dict[str, Any]:
    [found] = [word for word in body["words"] if word["label"] == label]
    word: dict[str, Any] = found
    return word


def _statuses(session: Session, env: SourcesEnv) -> dict[str, BookingStatus]:
    session.expire_all()
    rows = session.scalars(select(Booking).where(Booking.workspace_id == env.workspace.id)).all()
    return {booking.source_record_id: booking.status for booking in rows}


@pytest.fixture
def taught(api_client: TestClient, env: SourcesEnv, db_session: Session) -> UUID:
    """A file whose word NINFA did not know, answered once and imported."""
    assert _questions(_understand(api_client, env, WITH_MODIFICATA)) == ["LABELS:status_mapping"]
    _import(api_client, env, WITH_MODIFICATA, MODIFICATA)
    return _source_id(db_session, env)


# --- 1, 2: learned, and not asked again ----------------------------------------------------------


def test_an_answer_is_remembered_and_the_next_file_does_not_ask(
    api_client: TestClient, env: SourcesEnv, taught: UUID
) -> None:
    assert _questions(_understand(api_client, env, WITH_MODIFICATA)) == []

    word = _word(_remembered(api_client, env, taught), "modificata")
    assert word["field"] == "status"
    assert word["document"] == "status_mapping"
    assert word["value"] == "NO_SHOW"
    assert word["choices"] == list(STATUS_CHOICES)


def test_the_list_a_word_can_be_corrected_to_is_the_questions_own(
    api_client: TestClient, env: SourcesEnv
) -> None:
    question = _understand(api_client, env, WITH_MODIFICATA)["understanding"]["questions"][0]

    assert [choice["value"] for choice in question["choices"]] == list(STATUS_CHOICES)


def test_a_source_with_nothing_taught_remembers_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, bookings_file(*["Confermata"] * 6))

    body = _remembered(api_client, env, _source_id(db_session, env))

    assert body == {"words": [], "files": []}


# --- 3, 4: forgotten, and asked again ------------------------------------------------------------


def test_a_forgotten_answer_is_asked_again_by_the_next_file(
    api_client: TestClient, env: SourcesEnv, taught: UUID
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")

    response = api_client.delete(_url(env, taught, word["id"]))

    assert response.status_code == 200, response.text
    assert response.json()["words"] == []
    understood = _understand(api_client, env, WITH_MODIFICATA)
    assert understood["understanding"]["level"] != "READY"
    assert _questions(understood) == ["LABELS:status_mapping"]


def test_a_forgotten_answer_can_be_answered_differently_and_is_then_remembered(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")
    api_client.delete(_url(env, taught, word["id"]))

    _import(
        api_client,
        env,
        WITH_MODIFICATA,
        {"labels": {"status_mapping": {"Modificata": "CONFIRMED"}}},
    )

    assert _word(_remembered(api_client, env, taught), "modificata")["value"] == "CONFIRMED"
    assert _statuses(db_session, env)["P-003"] is BookingStatus.CONFIRMED


def test_a_corrected_answer_is_used_by_the_next_file_with_no_question(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")

    response = api_client.put(_url(env, taught, word["id"]), json={"value": "CONFIRMED"})

    assert response.status_code == 200, response.text
    assert _word(response.json(), "modificata")["value"] == "CONFIRMED"
    assert _questions(_understand(api_client, env, WITH_MODIFICATA)) == []
    _import(api_client, env, WITH_MODIFICATA)
    assert _statuses(db_session, env)["P-003"] is BookingStatus.CONFIRMED


def test_a_word_cannot_be_corrected_to_what_its_question_does_not_offer(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")

    response = api_client.put(_url(env, taught, word["id"]), json={"value": "PAID"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REMEMBERED_ANSWER"
    assert _word(_remembered(api_client, env, taught), "modificata")["value"] == "NO_SHOW"


def test_correcting_to_the_same_meaning_changes_nothing(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")

    assert (
        api_client.put(_url(env, taught, word["id"]), json={"value": "NO_SHOW"}).status_code == 200
    )

    assert _trail(db_session, env) == []


def test_an_answer_already_forgotten_is_the_usual_404(
    api_client: TestClient, env: SourcesEnv, taught: UUID
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")
    api_client.delete(_url(env, taught, word["id"]))

    response = api_client.delete(_url(env, taught, word["id"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REMEMBERED_ANSWER_NOT_FOUND"


# --- 5: nothing else changes ---------------------------------------------------------------------


def test_forgetting_a_word_leaves_the_other_words_and_the_saved_matching(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = bookings_file(
        "Confermata", "Confermata", "Modificata", "Modificata", "Sospesa", "Sospesa"
    )
    _import(
        api_client,
        env,
        content,
        {"labels": {"status_mapping": {"Modificata": "NO_SHOW", "Sospesa": "CONFIRMED"}}},
    )
    source_id = _source_id(db_session, env)
    before = db_session.scalar(
        select(BookingMappingProfile).where(BookingMappingProfile.data_source_id == source_id)
    )
    assert before is not None
    columns, signature = dict(before.column_mapping), before.header_signature

    word = _word(_remembered(api_client, env, source_id), "modificata")
    api_client.delete(_url(env, source_id, word["id"]))

    remaining = _remembered(api_client, env, source_id)["words"]
    assert [(item["label"], item["value"]) for item in remaining] == [("sospesa", "CONFIRMED")]
    db_session.expire_all()
    after = db_session.scalar(
        select(BookingMappingProfile).where(BookingMappingProfile.data_source_id == source_id)
    )
    assert after is not None
    assert after.column_mapping == columns and after.header_signature == signature


# Two staff exports of one source, each taught by a person: the engine cannot tell the hours apart.
RECEPTION = {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"}
RECEPTION_SAYS = {"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}}
RESTAURANT = {"Data": "day", "Ore 1": "planned", "Ore 2": "actual", "Area": "dept"}
RESTAURANT_SAYS = {"column_fields": {"Ore 1": "planned_hours", "Ore 2": "actual_hours"}}


def _teach_labor(
    client: TestClient, env: SourcesEnv, columns: dict[str, str], says: dict[str, Any]
) -> None:
    content = xlsx_of(columns)
    understood = understand(client, env, LABOR, "turni.xlsx", content, says)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(
        client,
        env,
        LABOR,
        "turni.xlsx",
        content,
        understood["proposal"],
        snapshot="2026-10-23",
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text


def _labor_source(session: Session, env: SourcesEnv) -> UUID:
    source = session.scalar(
        select(DataSource).where(
            DataSource.property_id == env.property.id,
            DataSource.domain == DataSourceDomain.LABOR,
        )
    )
    assert source is not None
    return source.id


def test_forgetting_one_kind_of_file_leaves_the_other_and_asks_again_only_for_it(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _teach_labor(api_client, env, RECEPTION, RECEPTION_SAYS)
    _teach_labor(api_client, env, RESTAURANT, RESTAURANT_SAYS)
    source_id = _labor_source(db_session, env)
    files = _remembered(api_client, env, source_id)["files"]
    assert len(files) == 2
    reception = next(item for item in files if "ore a" in item["columns"])
    assert reception["column_decisions"] == 2

    response = api_client.delete(_url(env, source_id, reception["id"]))

    assert response.status_code == 200, response.text
    assert ["ore 1" in item["columns"] for item in response.json()["files"]] == [True]
    # The one forgotten is a file nobody taught; the other is still recognised, asking nothing.
    forgotten = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RECEPTION))
    assert forgotten["understanding"]["questions"]
    kept = understand(api_client, env, LABOR, "turni.xlsx", xlsx_of(RESTAURANT))
    assert kept["understanding"]["questions"] == []


def test_a_file_only_the_engine_read_is_not_shown_it_has_decided_nothing(
    api_client: TestClient, env: SourcesEnv, taught: UUID
) -> None:
    assert _remembered(api_client, env, taught)["files"] == []


def test_what_a_person_said_a_file_holds_is_shown_and_can_be_forgotten(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    six = ["Confermata"] * 6
    _import(api_client, env, bookings_file(*six))
    answers = {"file_scope": "PARTIAL", "remember_scope": True}
    _import(api_client, env, bookings_file(*six, without=2), answers)
    source_id = _source_id(db_session, env)
    # Remembered: another file of this structure lacking something in its period is not asked about.
    another = bookings_file(*six, without=3)
    assert "FILE_SCOPE" not in [
        q["kind"] for q in _understand(api_client, env, another)["understanding"]["questions"]
    ]

    [remembered] = _remembered(api_client, env, source_id)["files"]
    assert remembered["file_scope"] == "PARTIAL"

    api_client.delete(_url(env, source_id, remembered["id"]))

    assert _remembered(api_client, env, source_id)["files"] == []
    understood = _understand(api_client, env, another)
    assert "FILE_SCOPE" in [q["kind"] for q in understood["understanding"]["questions"]]


def test_several_answers_of_a_family_stay_together_with_it(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _teach_labor(api_client, env, RECEPTION, RECEPTION_SAYS)
    source_id = _labor_source(db_session, env)
    profile = db_session.scalar(
        select(LaborMappingProfile).where(LaborMappingProfile.data_source_id == source_id)
    )
    assert profile is not None
    learning = parse_learning(profile.format_options.get("learning"))
    assert learning is not None
    family = learning.families[0]
    assert family.trust.value == "PERSON"

    [item] = _remembered(api_client, env, source_id)["files"]

    assert item["id"] == f"f-{family.id}"
    assert set(item["columns"]) == set(family.header_keys())


# --- 6: nothing already imported is read again
# -----------------------------------------------------


@pytest.mark.parametrize("how", ["forget", "correct"])
def test_what_was_imported_stays_as_it_was_read(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session, how: str
) -> None:
    before = _statuses(db_session, env)
    assert before["P-003"] is BookingStatus.NO_SHOW
    word = _word(_remembered(api_client, env, taught), "modificata")

    if how == "forget":
        api_client.delete(_url(env, taught, word["id"]))
    else:
        api_client.put(_url(env, taught, word["id"]), json={"value": "CONFIRMED"})

    assert _statuses(db_session, env) == before


def test_a_correction_asks_for_no_analysis(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    count = "SELECT count(*) FROM procrastinate_jobs WHERE args ->> 'property_id' = :p"
    before = db_session.scalar(text(count), {"p": str(env.property.id)})
    word = _word(_remembered(api_client, env, taught), "modificata")

    api_client.delete(_url(env, taught, word["id"]))

    assert db_session.scalar(text(count), {"p": str(env.property.id)}) == before


# --- 7: tenancy -----------------------------------------------------------------------------------


def test_a_source_of_another_workspace_is_the_usual_404(
    api_client: TestClient,
    env: SourcesEnv,
    taught: UUID,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")
    stranger = sources_env(factory, authenticated_as)

    for response in (
        api_client.get(_url(env, taught)),
        api_client.delete(_url(env, taught, word["id"])),
        api_client.put(_url(env, taught, word["id"]), json={"value": "CONFIRMED"}),
        api_client.get(_url(stranger, taught)),
        api_client.delete(_url(stranger, taught, word["id"])),
    ):
        assert response.status_code == 404


def test_a_source_of_another_property_of_the_same_workspace_is_the_same_404(
    api_client: TestClient, env: SourcesEnv, taught: UUID, factory: BookingFactory
) -> None:
    sibling = factory.property(env.workspace)
    other = SourcesEnv(env.workspace, sibling, env.user)

    assert api_client.get(_url(other, taught)).status_code == 404


# --- audit ---------------------------------------------------------------------------------------


def _trail(session: Session, env: SourcesEnv) -> list[dict[str, Any]]:
    session.expire_all()
    [profile] = profiles_of(session, env, BookingMappingProfile)
    learning = parse_learning(profile.format_options.get("learning"))
    return [] if learning is None else list(learning.corrections)


def test_a_correction_leaves_a_line_saying_what_when_and_who(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")

    api_client.put(_url(env, taught, word["id"]), json={"value": "CONFIRMED"})
    api_client.delete(_url(env, taught, word["id"]))

    first, second = _trail(db_session, env)
    assert first["action"] == "CORRECTED" and second["action"] == "FORGOTTEN"
    assert first["document"] == "status_mapping" and first["label"] == "modificata"
    assert (first["before"], first["after"]) == ("NO_SHOW", "CONFIRMED")
    assert (second["before"], second["after"]) == ("CONFIRMED", None)
    assert first["by"] == str(env.user.id)
    assert datetime.fromisoformat(first["at"]).tzinfo is not None


def test_the_line_survives_the_next_import(
    api_client: TestClient, env: SourcesEnv, taught: UUID, db_session: Session
) -> None:
    word = _word(_remembered(api_client, env, taught), "modificata")
    api_client.delete(_url(env, taught, word["id"]))

    _import(
        api_client,
        env,
        WITH_MODIFICATA,
        {"labels": {"status_mapping": {"Modificata": "CONFIRMED"}}},
    )

    assert [entry["action"] for entry in _trail(db_session, env)] == ["FORGOTTEN"]


def test_the_word_does_not_travel_in_the_address() -> None:
    answer_id = _word_id("status_mapping", "modificata")

    assert "modificata" not in answer_id and answer_id.startswith("w-")


def test_a_word_of_personal_data_is_not_shown(db_session: Session, factory: BookingFactory) -> None:
    """A department word is a free word a person typed: it passes the gate every answer about a file
    passes, and its handle still reaches it."""
    tenant = factory.tenant()
    source = factory.data_source(tenant.property, domain=DataSourceDomain.LABOR)
    profile = LaborMappingProfile(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=source.id,
        column_mapping={},
        role_mapping={"mario.rossi@example.com": "HOUSEKEEPING", "hk": "HOUSEKEEPING"},
        format_options={},
        header_signature="0" * 64,
    )
    db_session.add(profile)
    db_session.flush()

    answers = RememberedAnswersService(db_session, TenantContext(tenant.workspace.id)).read(source)

    assert len(answers.words) == 2
    assert all("@" not in word.label for word in answers.words)

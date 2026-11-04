"""What the absence of a booking means: real files through the real API and database (rolled back).

A file that holds everything of its period takes away what it no longer holds; one that holds a
part of it, or only what is new, takes away nothing. NINFA never decides which from the file: it
asks once, only when the answer changes what counts, and remembers it for files of that structure.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingMappingProfile, BookingStatus
from app.modules.bookings.repository import BookingRepository
from app.modules.bookings.service import BookingImportService
from app.modules.data_sources.source_learning import Trust, parse_learning
from app.modules.ingestion.models import FileScope, ImportJob
from app.modules.intelligence.distribution.repository import DistributionRepository
from app.modules.snapshots.repository import BookingStayRepository
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import by_hand, import_mapped, profiles_of, understand
from tests.support import BookingFactory

BOOKINGS = "BOOKINGS"
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


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def row(number: int, *, revenue: int = 150, status: str = "Confermata") -> list[Any]:
    check_in = datetime.combine(FIRST + timedelta(days=number), datetime.min.time())
    return [
        f"P-{number:03d}",
        check_in - timedelta(days=30),
        check_in,
        check_in + timedelta(days=1),
        1,
        revenue,
        "Booking.com",
        status,
    ]


def row_without_rooms(number: int) -> list[Any]:
    return [cell for at, cell in enumerate(row(number)) if at != 4]


def _always(index: int) -> list[Any]:
    """A booking every file of these tests holds, arriving on the first day: enough rows for the
    columns to be understood, and the period of each file starts here."""
    return [f"S-{index}", *row(0)[1:]]


ALWAYS = tuple(_always(index) for index in range(4))


def file_of(*rows: list[Any], extra: dict[str, Any] | None = None) -> bytes:
    headers = [*HEADERS, *(extra or {})]
    body = [[*one, *(extra or {}).values()] for one in (*ALWAYS, *rows)]
    return xlsx_bytes({"Prenotazioni": [headers, *body]})


def _questions(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _import(
    api_client: TestClient,
    env: SourcesEnv,
    content: bytes,
    answers: dict[str, Any] | None = None,
    name: str = "pren.xlsx",
) -> dict[str, Any]:
    """Understand, then import what NINFA proposes: the way the page does it."""
    understood = understand(api_client, env, BOOKINGS, name, content, answers)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(api_client, env, BOOKINGS, name, content, understood["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    body: dict[str, Any] = done.json()
    return body


def _all(session: Session, env: SourcesEnv) -> dict[str, Booking]:
    session.expire_all()
    rows = session.scalars(select(Booking).where(Booking.workspace_id == env.workspace.id)).all()
    return {b.source_record_id: b for b in rows if not b.source_record_id.startswith("S-")}


def _current(session: Session, env: SourcesEnv) -> set[str]:
    return {
        booking.source_record_id
        for booking in BookingRepository(session, env.tenant).list_for_property(env.property.id)
        if not booking.source_record_id.startswith("S-")
    }


ONE_TWO_THREE = (row(1), row(2), row(3))


# --- a complete file ------------------------------------------------------------------------------


def test_a_first_file_has_no_absence_to_explain_and_asks_nothing(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(api_client, env, BOOKINGS, "a.xlsx", file_of(*ONE_TWO_THREE))

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []
    assert body["proposal"]["file_scope"] is None


def test_records_missing_from_a_later_file_ask_once_what_the_file_is(
    api_client: TestClient, env: SourcesEnv
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))

    body = understand(api_client, env, BOOKINGS, "b.xlsx", file_of(row(1), row(3)))

    assert body["understanding"]["level"] == "ASK"
    [question] = body["understanding"]["questions"]
    assert question["kind"] == "FILE_SCOPE"
    assert question["absent_records"] == 1
    assert [choice["value"] for choice in question["choices"]] == ["FULL", "PARTIAL", "DELTA"]


def test_a_complete_file_takes_away_what_it_no_longer_holds_and_deletes_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3))
    understood = understand(api_client, env, BOOKINGS, "b.xlsx", content, {"file_scope": "FULL"})
    assert understood["understanding"]["level"] == "READY"
    assert understood["understanding"]["removes"] == 1  # said before anyone presses anything

    done = import_mapped(api_client, env, BOOKINGS, "b.xlsx", content, understood["proposal"])

    assert done.json()["removed"] == 1
    assert done.json()["changed_data"] is True
    assert _current(db_session, env) == {"P-001", "P-003"}
    stored = _all(db_session, env)
    assert set(stored) == {"P-001", "P-002", "P-003"}  # nothing is deleted
    assert stored["P-002"].removed_at is not None


def test_what_was_taken_away_says_where_it_went_and_where_it_was_last_seen(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    # a second import that holds P-002 unchanged writes nothing on it
    _import(api_client, env, file_of(*ONE_TWO_THREE), name="a-di-nuovo.xlsx")
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")

    jobs = db_session.scalars(
        select(ImportJob)
        .where(ImportJob.workspace_id == env.workspace.id)
        .order_by(ImportJob.started_at)
    ).all()
    first, again, complete = jobs
    gone = _all(db_session, env)["P-002"]
    assert gone.removed_by_import_job_id == complete.id
    assert gone.last_seen_import_job_id == again.id  # not the first: the last that held it
    assert gone.last_import_job_id == first.id  # the last that changed it, untouched
    assert complete.file_scope is FileScope.FULL
    assert complete.changed_data is True


def test_what_was_taken_away_stops_counting_everywhere_bookings_are_read(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")
    source = _all(db_session, env)["P-001"].data_source_id
    first_night, last_night = FIRST, FIRST + timedelta(days=9)

    stays = BookingStayRepository(db_session, env.tenant).list_stays(
        env.property.id, source, first_night, last_night
    )
    with_channel = DistributionRepository(db_session, env.tenant).list_stays_with_channel(
        env.property.id, source, first_night, last_night
    )

    assert len(stays) == len(ALWAYS) + 2
    assert len(with_channel) == len(ALWAYS) + 2


def test_a_booking_that_comes_back_is_current_again_and_that_is_a_change(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")

    back = _import(api_client, env, file_of(*ONE_TWO_THREE), name="c.xlsx")

    assert back["updated"] == 1
    assert back["changed_data"] is True
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}
    restored = _all(db_session, env)["P-002"]
    assert restored.removed_at is None
    assert restored.removed_by_import_job_id is None
    assert restored.last_seen_import_job_id is None


def test_the_same_complete_file_again_moves_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3))
    _import(api_client, env, content, {"file_scope": "FULL"}, name="b.xlsx")

    again = understand(api_client, env, BOOKINGS, "b.xlsx", content)
    assert again["understanding"]["removes"] == 0
    done = _import(api_client, env, content, name="b.xlsx")

    assert (done["created"], done["updated"], done["removed"]) == (0, 0, 0)
    assert done["changed_data"] is False


def test_a_period_the_file_does_not_cover_is_not_its_business(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(row(1), row(2), row(20), row(21)))
    content = file_of(row(1), row(2))  # 2-3 March: 21-22 March is not in it

    body = understand(api_client, env, BOOKINGS, "b.xlsx", content)
    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []

    _import(api_client, env, content, {"file_scope": "FULL"}, name="b.xlsx")

    assert _current(db_session, env) == {"P-001", "P-002", "P-020", "P-021"}


def test_a_stored_cancellation_a_file_leaves_out_has_nothing_to_lose(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(row(1), row(2, status="Cancellata"), row(3)))

    body = understand(api_client, env, BOOKINGS, "b.xlsx", file_of(row(1), row(3)))

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []


def test_a_cancellation_the_file_states_is_a_status_and_not_a_removal(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(2, status="Cancellata", revenue=0), row(3))

    body = understand(api_client, env, BOOKINGS, "b.xlsx", content)
    assert body["understanding"]["level"] == "READY"

    done = _import(api_client, env, content, name="b.xlsx")

    assert (done["updated"], done["removed"]) == (1, 0)
    cancelled = _all(db_session, env)["P-002"]
    assert cancelled.status == BookingStatus.CANCELLED
    assert cancelled.removed_at is None


# --- a part of it, or only what is new ---------------------------------------------------------


@pytest.mark.parametrize("scope", ["PARTIAL", "DELTA"])
def test_a_file_that_is_not_complete_takes_away_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session, scope: str
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1, revenue=175), row(3))

    understood = understand(api_client, env, BOOKINGS, "b.xlsx", content, {"file_scope": scope})
    assert understood["understanding"]["level"] == "READY"
    assert understood["understanding"]["removes"] == 0
    done = import_mapped(api_client, env, BOOKINGS, "b.xlsx", content, understood["proposal"])

    assert (done.json()["updated"], done.json()["removed"]) == (1, 0)
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}
    assert _all(db_session, env)["P-001"].room_revenue == 175


def test_only_what_is_new_adds_to_what_is_there(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """Its dates span the older bookings: that alone says nothing about them."""
    _import(api_client, env, file_of(*ONE_TWO_THREE))

    body = _import(api_client, env, file_of(row(4)), {"file_scope": "DELTA"}, name="nuove.xlsx")

    assert (body["created"], body["removed"]) == (1, 0)
    assert _current(db_session, env) == {"P-001", "P-002", "P-003", "P-004"}


def test_nobody_saying_anything_takes_away_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """An import that does not go through the question (the pilot's CLI, a canonical file)."""
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    source = _all(db_session, env)["P-001"].data_source_id

    result = BookingImportService(db_session, TenantContext(env.workspace.id)).import_file(
        source, filename="b.xlsx", content=file_of(row(1), row(3)), property_id=env.property.id
    )

    assert result.succeeded and result.bookings_removed == 0
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}


# --- never a claim of the client ---------------------------------------------------------------


def test_a_matching_built_by_hand_cannot_say_a_file_is_complete(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3))
    understood = understand(api_client, env, BOOKINGS, "b.xlsx", content, {"file_scope": "FULL"})
    claimed = {**by_hand(understood["proposal"]), "file_scope": "FULL"}

    done = import_mapped(api_client, env, BOOKINGS, "b.xlsx", content, claimed)

    assert done.status_code == 200 and done.json()["succeeded"] is True
    assert done.json()["removed"] == 0
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}


def test_a_decision_cannot_be_turned_complete_by_posting_it_so(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3))
    asked = understand(api_client, env, BOOKINGS, "b.xlsx", content, {"file_scope": "PARTIAL"})
    forged = {**asked["proposal"], "file_scope": "FULL"}

    done = import_mapped(api_client, env, BOOKINGS, "b.xlsx", content, forged)

    assert done.status_code == 409
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}


def test_a_file_that_asks_cannot_be_imported_without_the_answer(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3))
    asked = understand(api_client, env, BOOKINGS, "b.xlsx", content)

    done = import_mapped(api_client, env, BOOKINGS, "b.xlsx", content, asked["proposal"])

    assert done.status_code == 409
    assert done.json()["error"]["code"] == "UNRESOLVED_IMPORT_QUESTIONS"


# --- Source Learning -----------------------------------------------------------------------------


def _family_scope(session: Session, env: SourcesEnv) -> list[Any]:
    (profile,) = profiles_of(session, env, BookingMappingProfile)
    session.refresh(profile)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    return [(family.file_scope, family.trust) for family in store.families]


def test_the_answer_is_remembered_and_the_next_file_of_that_structure_asks_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")
    assert _family_scope(db_session, env) == [(FileScope.FULL, Trust.ENGINE)]

    # a later export, another name: P-001 is gone too
    content = file_of(row(3))
    body = understand(api_client, env, BOOKINGS, "export-del-giorno-dopo.xlsx", content)

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []
    assert body["proposal"]["file_scope"] == "FULL"
    assert body["understanding"]["removes"] == 1


def test_answering_about_the_file_confirms_nothing_about_its_columns(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """A word about the file is not a word about its columns: the family keeps the trust it had."""
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "DELTA"}, name="b.xlsx")

    (profile,) = profiles_of(db_session, env, BookingMappingProfile)
    db_session.refresh(profile)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    [family] = store.families
    assert family.trust == Trust.ENGINE
    assert family.person == {}
    assert family.file_scope is FileScope.DELTA


def test_a_remembered_partial_answer_keeps_a_later_file_from_taking_anything_away(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "PARTIAL"}, name="b.xlsx")

    done = _import(api_client, env, file_of(row(3)), name="c.xlsx")

    assert done["removed"] == 0
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}


def test_another_structure_does_not_inherit_the_answer(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")
    # the same bookings from another export: a column it remembers is gone, so it is another family
    without_rooms = [[cell for at, cell in enumerate(one) if at != 4] for one in ALWAYS]
    headers = [header for header in HEADERS if header != "Camere"]
    other = xlsx_bytes({"Altro": [headers, *without_rooms, row_without_rooms(3)]})

    body = understand(api_client, env, BOOKINGS, "altro.xlsx", other)

    assert body["proposal"]["file_scope"] is None
    assert _questions(body) == ["FILE_SCOPE"]


def test_a_header_renamed_to_what_reads_the_same_is_still_that_structure(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "PARTIAL"}, name="b.xlsx")
    renamed = xlsx_bytes({"Altro": [["Numero prenotazione", *HEADERS[1:]], *ALWAYS, row(3)]})

    body = understand(api_client, env, BOOKINGS, "c.xlsx", renamed)

    assert _questions(body) == []
    assert body["proposal"]["file_scope"] == "PARTIAL"


def test_a_column_more_is_the_same_structure_and_keeps_the_answer(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    _import(api_client, env, file_of(row(1), row(3)), {"file_scope": "FULL"}, name="b.xlsx")

    body = understand(
        api_client, env, BOOKINGS, "c.xlsx", file_of(row(3), extra={"Trattamento": "BB"})
    )

    assert _questions(body) == []
    assert body["proposal"]["file_scope"] == "FULL"
    assert body["understanding"]["removes"] == 1


def test_the_question_comes_last_after_what_the_file_itself_needs_answered(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    """`Modificata` stays what it was: asked once, about the word. The file comes after it."""
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    content = file_of(row(1), row(3, status="Modificata"))

    first = understand(api_client, env, BOOKINGS, "b.xlsx", content)
    assert _questions(first) == ["VALUE_LABELS"]

    taught = {"labels": {"status_mapping": {"Modificata": "CONFIRMED"}}}
    second = understand(api_client, env, BOOKINGS, "b.xlsx", content, taught)
    assert _questions(second) == ["FILE_SCOPE"]

    third = understand(
        api_client, env, BOOKINGS, "b.xlsx", content, {**taught, "file_scope": "FULL"}
    )
    assert third["understanding"]["level"] == "READY"


# --- isolation, and kinds of data where absence means nothing ----------------------------------


def test_what_another_hotel_holds_is_never_absent_from_this_file(
    api_client: TestClient,
    env: SourcesEnv,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    _import(api_client, env, file_of(*ONE_TWO_THREE))
    other = sources_env(factory, authenticated_as)

    body = understand(api_client, other, BOOKINGS, "b.xlsx", file_of(row(1)))

    assert body["understanding"]["level"] == "READY"
    assert _current(db_session, env) == {"P-001", "P-002", "P-003"}


def test_a_cost_register_never_asks_and_never_takes_anything_away(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    headers = [
        "Numero documento",
        "Data documento",
        "Fornitore",
        "Descrizione",
        "Imponibile",
        "IVA",
        "Totale",
    ]
    rows = [
        [f"FT-{n}", datetime(2026, 9, n + 1), "Alfa Srl", "Servizio", 100 + n, 22, 122 + n]
        for n in range(12)
    ]
    first = xlsx_bytes({"Costi": [headers, *rows]})
    second = xlsx_bytes({"Costi": [headers, *rows[:6], *rows[7:]]})
    understood = understand(api_client, env, "COSTS", "a.xlsx", first)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(api_client, env, "COSTS", "a.xlsx", first, understood["proposal"])
    assert done.json()["succeeded"] is True

    body = understand(api_client, env, "COSTS", "b.xlsx", second)

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []
    assert body["understanding"]["removes"] == 0
    assert body["proposal"]["file_scope"] is None

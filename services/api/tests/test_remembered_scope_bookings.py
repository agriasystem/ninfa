"""A memory never takes bookings away by itself: real files through the real API (rolled back).

The same source can export a part of its period with the very same columns. So remembering that
files of a structure are complete saves a question only while nothing would stop counting: as soon
as something would, a person says it again, for this import. The memory moves only if they ask.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.errors import BookingErrorCode
from app.modules.bookings.models import Booking, BookingMappingProfile
from app.modules.bookings.repository import BookingRepository
from app.modules.bookings.service import BookingImportService
from app.modules.data_sources.source_learning import parse_learning
from app.modules.ingestion.models import FileScope, ImportJob
from app.modules.ingestion.scope import ScopePlan
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, profiles_of, understand
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
COMPLETE = {"file_scope": "FULL"}
A_PART = {"file_scope": "PARTIAL"}
COMPLETE_FROM_NOW_ON = {"file_scope": "FULL", "remember_scope": True}
A_PART_FROM_NOW_ON = {"file_scope": "PARTIAL", "remember_scope": True}


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


# Bookings every file holds, on the first day: rows to read, and each file's period starts here.
ALWAYS = tuple([f"S-{index}", *row(0)[1:]] for index in range(4))


def file_of(*rows: list[Any]) -> bytes:
    return xlsx_bytes({"Prenotazioni": [HEADERS, *ALWAYS, *rows]})


def _kinds(body: dict[str, Any]) -> list[str]:
    return [question["kind"] for question in body["understanding"]["questions"]]


def _import(
    api_client: TestClient,
    env: SourcesEnv,
    content: bytes,
    answers: dict[str, Any] | None = None,
    name: str = "pren.xlsx",
) -> dict[str, Any]:
    understood = understand(api_client, env, BOOKINGS, name, content, answers)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(api_client, env, BOOKINGS, name, content, understood["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    body: dict[str, Any] = done.json()
    return body


def _current(session: Session, env: SourcesEnv) -> set[str]:
    session.expire_all()
    return {
        booking.source_record_id
        for booking in BookingRepository(session, env.tenant).list_for_property(env.property.id)
        if not booking.source_record_id.startswith("S-")
    }


def _remembered(session: Session, env: SourcesEnv) -> list[FileScope | None]:
    (profile,) = profiles_of(session, env, BookingMappingProfile)
    session.refresh(profile)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    return [family.file_scope for family in store.families]


def _jobs(session: Session, env: SourcesEnv) -> list[ImportJob]:
    session.expire_all()
    return list(
        session.scalars(
            select(ImportJob)
            .where(ImportJob.workspace_id == env.workspace.id)
            .order_by(ImportJob.started_at)
        ).all()
    )


@pytest.fixture
def complete_source(api_client: TestClient, env: SourcesEnv, db_session: Session) -> SourcesEnv:
    """Files of this structure are remembered as complete; 1, 2, 3, 4 are on the books."""
    _import(api_client, env, file_of(row(1), row(2), row(3), row(4)))
    _import(
        api_client, env, file_of(row(1), row(2), row(3), row(4)), COMPLETE_FROM_NOW_ON, "b.xlsx"
    )
    assert _remembered(db_session, env) == [FileScope.FULL]
    return env


LEAVES_OUT_TWO = (row(1), row(4))  # P-002 and P-003 would stop counting


# --- the safety rule ----------------------------------------------------------------------------


def test_a_remembered_complete_with_nothing_to_lose_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(
        api_client,
        complete_source,
        BOOKINGS,
        "c.xlsx",
        file_of(row(1), row(2), row(3), row(4)),
    )

    understanding = body["understanding"]
    assert understanding["level"] == "READY"
    assert understanding["questions"] == []
    assert understanding["scope"] == {
        "effective_scope": "FULL",
        "remembered_scope": "FULL",
        "removal_count": 0,
        "requires_scope_confirmation": False,
    }


def test_a_remembered_complete_that_would_take_something_away_asks_first(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(api_client, complete_source, BOOKINGS, "c.xlsx", file_of(*LEAVES_OUT_TWO))

    understanding = body["understanding"]
    assert understanding["level"] == "ASK"
    [question] = understanding["questions"]
    assert question["kind"] == "FILE_SCOPE_CONFIRM"
    assert question["absent_records"] == 2
    assert [choice["value"] for choice in question["choices"]] == ["FULL", "PARTIAL"]
    assert understanding["scope"] == {
        "effective_scope": None,  # nothing is applied on the memory's word
        "remembered_scope": "FULL",
        "removal_count": 2,
        "requires_scope_confirmation": True,
    }
    assert understanding["removes"] == 0
    assert body["proposal"]["file_scope"] is None


def test_it_cannot_be_imported_without_the_answer(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    asked = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content)

    done = import_mapped(
        api_client, complete_source, BOOKINGS, "c.xlsx", content, asked["proposal"]
    )

    assert done.status_code == 409
    assert done.json()["error"]["code"] == "UNRESOLVED_IMPORT_QUESTIONS"
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}


def test_a_memory_cannot_be_posted_as_a_decision_to_skip_the_question(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    asked = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content)
    forged = {**asked["proposal"], "file_scope": "FULL", "expected_removals": 2}

    done = import_mapped(api_client, complete_source, BOOKINGS, "c.xlsx", content, forged)

    assert done.status_code == 409
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}


def test_yes_it_is_complete_takes_them_away(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    understood = understand(
        api_client, complete_source, BOOKINGS, "c.xlsx", file_of(*LEAVES_OUT_TWO), COMPLETE
    )
    assert understood["understanding"]["removes"] == 2
    assert understood["understanding"]["scope"]["requires_scope_confirmation"] is False

    done = _import(api_client, complete_source, file_of(*LEAVES_OUT_TWO), COMPLETE, "c.xlsx")

    assert done["removed"] == 2
    assert _current(db_session, complete_source) == {"P-001", "P-004"}
    job = _jobs(db_session, complete_source)[-1]
    assert (job.file_scope, job.remembered_file_scope) == (FileScope.FULL, FileScope.FULL)


def test_no_it_is_a_part_takes_nothing_away(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    done = _import(api_client, complete_source, file_of(*LEAVES_OUT_TWO), A_PART, "c.xlsx")

    assert done["removed"] == 0
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}
    job = _jobs(db_session, complete_source)[-1]
    assert (job.file_scope, job.remembered_file_scope) == (FileScope.PARTIAL, FileScope.FULL)


def test_a_part_is_a_word_about_this_import_and_the_memory_stays(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, complete_source, file_of(*LEAVES_OUT_TWO), A_PART, "c.xlsx")

    assert _remembered(db_session, complete_source) == [FileScope.FULL]
    # the next complete file of this source: nothing to lose, nothing to ask
    full = understand(
        api_client,
        complete_source,
        BOOKINGS,
        "d.xlsx",
        file_of(row(1), row(2), row(3), row(4)),
    )
    assert _kinds(full) == []
    assert full["proposal"]["file_scope"] == "FULL"
    # and one that would take something away asks again: one export says nothing about the next
    leaves_out_another = understand(
        api_client, complete_source, BOOKINGS, "e.xlsx", file_of(row(2), row(3), row(4))
    )
    assert _kinds(leaves_out_another) == ["FILE_SCOPE_CONFIRM"]


def test_saying_so_explicitly_changes_the_memory(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, complete_source, file_of(*LEAVES_OUT_TWO), A_PART_FROM_NOW_ON, "c.xlsx")

    assert _remembered(db_session, complete_source) == [FileScope.PARTIAL]
    body = understand(api_client, complete_source, BOOKINGS, "d.xlsx", file_of(row(2), row(4)))
    assert _kinds(body) == []
    assert body["understanding"]["scope"]["effective_scope"] == "PARTIAL"
    assert body["understanding"]["removes"] == 0


def test_yes_this_time_does_not_touch_a_memory_of_a_part(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(row(1), row(2), row(3), row(4)))
    _import(api_client, env, file_of(row(1), row(4)), A_PART_FROM_NOW_ON, "b.xlsx")

    done = _import(api_client, env, file_of(row(2), row(4)), COMPLETE, "c.xlsx")

    assert done["removed"] == 2  # P-001 and P-003
    assert _remembered(db_session, env) == [FileScope.PARTIAL]


def test_correcting_a_memory_of_a_part_with_the_explicit_word(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, file_of(row(1), row(2), row(3), row(4)))
    _import(api_client, env, file_of(row(1), row(4)), A_PART_FROM_NOW_ON, "b.xlsx")

    _import(api_client, env, file_of(row(1), row(4)), COMPLETE_FROM_NOW_ON, "c.xlsx")

    assert _remembered(db_session, env) == [FileScope.FULL]
    assert _current(db_session, env) == {"P-001", "P-004"}


# --- no friction where nothing is at stake -------------------------------------------------


@pytest.mark.parametrize("scope", ["PARTIAL", "DELTA"])
def test_a_remembered_part_never_asks_and_says_what_it_would_have_meant(
    api_client: TestClient, env: SourcesEnv, db_session: Session, scope: str
) -> None:
    _import(api_client, env, file_of(row(1), row(2), row(3), row(4)))
    answers = {"file_scope": scope, "remember_scope": True}
    _import(api_client, env, file_of(row(1), row(4)), answers, "b.xlsx")

    body = understand(api_client, env, BOOKINGS, "c.xlsx", file_of(row(2), row(4)))

    understanding = body["understanding"]
    assert understanding["level"] == "READY"
    assert understanding["questions"] == []
    assert understanding["removes"] == 0
    assert understanding["scope"]["removal_count"] == 2  # for the secondary way of correcting it


def test_a_file_that_only_adds_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(
        api_client,
        complete_source,
        BOOKINGS,
        "c.xlsx",
        file_of(row(1), row(2), row(3), row(4), row(5)),
    )

    assert _kinds(body) == []


def test_a_file_that_only_changes_what_is_there_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(
        api_client,
        complete_source,
        BOOKINGS,
        "c.xlsx",
        file_of(row(1, revenue=210), row(2), row(3), row(4)),
    )

    assert _kinds(body) == []


def test_the_same_file_again_asks_nothing_and_moves_nothing(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    _import(api_client, complete_source, content, COMPLETE, "c.xlsx")

    done = _import(api_client, complete_source, content, name="c.xlsx")

    assert (done["created"], done["updated"], done["removed"]) == (0, 0, 0)
    assert done["changed_data"] is False


def test_the_same_part_again_is_not_asked_about_twice(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    _import(api_client, complete_source, content, A_PART, "c.xlsx")

    again = understand(api_client, complete_source, BOOKINGS, "c-di-nuovo.xlsx", content)
    assert _kinds(again) == []
    assert again["understanding"]["scope"]["effective_scope"] == "PARTIAL"

    done = _import(api_client, complete_source, content, name="c-di-nuovo.xlsx")

    assert done["removed"] == 0
    assert done["changed_data"] is False
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}


def test_a_file_once_complete_is_asked_about_again_if_it_would_take_something_away(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    _import(api_client, complete_source, content, COMPLETE, "c.xlsx")
    _import(api_client, complete_source, file_of(row(1), row(2), row(3), row(4)), name="d.xlsx")
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}

    again = understand(api_client, complete_source, BOOKINGS, "c-di-nuovo.xlsx", content)

    assert _kinds(again) == ["FILE_SCOPE_CONFIRM"]


def test_modificata_stays_what_it_was_and_comes_first(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    content = file_of(row(1), row(4, status="Modificata"))

    first = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content)
    assert _kinds(first) == ["VALUE_LABELS"]

    taught = {"labels": {"status_mapping": {"Modificata": "CONFIRMED"}}}
    second = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content, taught)
    assert _kinds(second) == ["FILE_SCOPE_CONFIRM"]


def test_another_structure_inherits_nothing_and_gets_the_first_question(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    keep = [index for index, header in enumerate(HEADERS) if header != "Camere"]
    headers = [HEADERS[index] for index in keep]
    rows = [[one[index] for index in keep] for one in (*ALWAYS, row(1), row(4))]

    body = understand(
        api_client,
        complete_source,
        BOOKINGS,
        "altro.xlsx",
        xlsx_bytes({"Altro": [headers, *rows]}),
    )

    assert _kinds(body) == ["FILE_SCOPE"]
    assert body["understanding"]["scope"]["remembered_scope"] is None


# --- what the server verifies at the commit ------------------------------------------------


def _add_on_the_side(api_client: TestClient, env: SourcesEnv, *rows: list[Any]) -> None:
    """Another file arrives between the reading and the commit (a part: it takes nothing away)."""
    _import(api_client, env, file_of(*rows), A_PART, "nel-frattempo.xlsx")


def test_something_new_after_a_reading_with_nothing_to_lose_is_refused(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(row(1), row(2), row(3), row(4))
    read = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content)
    assert read["understanding"]["removes"] == 0

    _add_on_the_side(api_client, complete_source, row(2), row(3), row(4), row(1), row(0))

    done = import_mapped(api_client, complete_source, BOOKINGS, "c.xlsx", content, read["proposal"])

    assert done.status_code == 409
    assert "P-000" in _current(db_session, complete_source)


def test_a_figure_that_moved_after_the_answer_is_refused(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    read = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content, COMPLETE)
    assert read["understanding"]["removes"] == 2

    _add_on_the_side(api_client, complete_source, row(1), row(4), row(0))

    done = import_mapped(api_client, complete_source, BOOKINGS, "c.xlsx", content, read["proposal"])

    assert done.status_code == 409
    assert done.json()["error"]["code"] == "IMPORT_DECISION_CHANGED"
    assert _current(db_session, complete_source) == {"P-000", "P-001", "P-002", "P-003", "P-004"}


def test_the_figure_of_the_browser_is_never_believed(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = file_of(*LEAVES_OUT_TWO)
    read = understand(api_client, complete_source, BOOKINGS, "c.xlsx", content, COMPLETE)
    forged = {**read["proposal"], "expected_removals": 0}

    done = import_mapped(api_client, complete_source, BOOKINGS, "c.xlsx", content, forged)

    assert done.status_code == 409
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}


def test_under_the_lock_a_plan_that_no_longer_holds_imports_nothing(
    complete_source: SourcesEnv, db_session: Session, api_client: TestClient
) -> None:
    """What the two checks above cannot see: a file that lands after them, before the commit."""
    stored = db_session.scalars(
        select(Booking).where(Booking.workspace_id == complete_source.workspace.id).limit(1)
    ).first()
    assert stored is not None
    source = stored.data_source_id

    result = BookingImportService(db_session, complete_source.tenant).import_file(
        source,
        filename="c.xlsx",
        content=file_of(row(1), row(4), row(5)),
        property_id=complete_source.property.id,
        scope=ScopePlan(FileScope.FULL, FileScope.FULL, expected_removals=0),  # it read none
    )

    assert not result.succeeded
    assert result.error_code == BookingErrorCode.IMPORT_PLAN_CHANGED
    assert _current(db_session, complete_source) == {"P-001", "P-002", "P-003", "P-004"}


def test_a_plan_that_holds_is_applied_and_counted_again_under_the_lock(
    complete_source: SourcesEnv, db_session: Session
) -> None:
    stored = db_session.scalars(
        select(Booking).where(Booking.workspace_id == complete_source.workspace.id).limit(1)
    ).first()
    assert stored is not None

    result = BookingImportService(db_session, complete_source.tenant).import_file(
        stored.data_source_id,
        filename="c.xlsx",
        content=file_of(*LEAVES_OUT_TWO),
        property_id=complete_source.property.id,
        scope=ScopePlan(FileScope.FULL, FileScope.FULL, expected_removals=2),
    )

    assert result.succeeded
    assert result.bookings_removed == 2

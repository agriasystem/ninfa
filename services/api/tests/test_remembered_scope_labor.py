"""A memory never takes a department out of the plan by itself: real files through the real API.

The same rule as for bookings, on what a staff file can leave out: a whole department, or one
department on one day.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.data_sources.source_learning import parse_learning
from app.modules.ingestion.models import DataSource, DataSourceDomain, FileScope, ImportJob
from app.modules.ingestion.scope import ScopePlan
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.labor.errors import LaborErrorCode
from app.modules.labor.models import LaborMappingProfile
from app.modules.labor.roles import LaborCategory
from app.modules.labor.service import LaborImportService
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, profiles_of, understand
from tests.support import BookingFactory

LABOR = "LABOR"
HEADERS = ["Giorno", "Reparto", "Ore previste", "Costo previsto"]
WEEK = date(2027, 3, 1)
NEXT_WEEK = date(2027, 3, 8)
BOTH = ("Reception", "Housekeeping")
COMPLETE = {"file_scope": "FULL"}
A_PART = {"file_scope": "PARTIAL"}
COMPLETE_FROM_NOW_ON = {"file_scope": "FULL", "remember_scope": True}
A_PART_FROM_NOW_ON = {"file_scope": "PARTIAL", "remember_scope": True}


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def staff(
    departments: tuple[str, ...] = BOTH,
    *,
    first: date = WEEK,
    hours: int = 8,
    without: tuple[int, str] | None = None,
    skip_day: int | None = None,
) -> bytes:
    """A week of shifts; `without` leaves one department out of one day (its offset, its name),
    `skip_day` a whole day inside the week."""
    rows = [
        [datetime.combine(first + timedelta(days=offset), datetime.min.time()), name, hours, 100]
        for offset in range(7)
        for name in departments
        if (offset, name) != without and offset != skip_day
    ]
    return xlsx_bytes({"Turni": [HEADERS, *rows]})


def _kinds(body: dict[str, Any]) -> list[str]:
    return [question["kind"] for question in body["understanding"]["questions"]]


def _import(
    api_client: TestClient,
    env: SourcesEnv,
    content: bytes,
    answers: dict[str, Any] | None = None,
    name: str = "turni.xlsx",
) -> dict[str, Any]:
    understood = understand(api_client, env, LABOR, name, content, answers)
    assert understood["understanding"]["level"] == "READY", understood["understanding"]
    done = import_mapped(api_client, env, LABOR, name, content, understood["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    body: dict[str, Any] = done.json()
    return body


def _source(session: Session, env: SourcesEnv) -> UUID:
    source = session.scalar(
        select(DataSource).where(
            DataSource.workspace_id == env.workspace.id,
            DataSource.domain == DataSourceDomain.LABOR,
        )
    )
    assert source is not None
    return source.id


def _plan(session: Session, env: SourcesEnv, day: date) -> dict[LaborCategory, int]:
    session.expire_all()
    found = LaborEvaluationRepository(session, env.tenant).current_plan(
        _source(session, env), date(2030, 1, 1), [day]
    )
    if day not in found:
        return {}
    totals: dict[LaborCategory, int] = {}
    for entry in found[day][1]:
        totals[entry.labor_category] = totals.get(entry.labor_category, 0) + (
            entry.planned_minutes or 0
        )
    return {category: minutes // 60 for category, minutes in totals.items()}


def _remembered(session: Session, env: SourcesEnv) -> list[FileScope | None]:
    (profile,) = profiles_of(session, env, LaborMappingProfile)
    session.refresh(profile)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    return [family.file_scope for family in store.families]


def _last_job(session: Session, env: SourcesEnv) -> ImportJob:
    session.expire_all()
    job = session.scalars(
        select(ImportJob)
        .where(ImportJob.workspace_id == env.workspace.id)
        .order_by(ImportJob.started_at.desc())
        .limit(1)
    ).first()
    assert job is not None
    return job


RECEPTION = LaborCategory.FRONT_OFFICE
HOUSEKEEPING = LaborCategory.HOUSEKEEPING


@pytest.fixture
def complete_source(api_client: TestClient, env: SourcesEnv, db_session: Session) -> SourcesEnv:
    """Files of this structure are remembered as complete; two departments for a week count."""
    _import(api_client, env, staff((*BOTH, "Cucina")))
    _import(api_client, env, staff(), COMPLETE_FROM_NOW_ON, "b.xlsx")
    assert _remembered(db_session, env) == [FileScope.FULL]
    assert _plan(db_session, env, WEEK) == {RECEPTION: 8, HOUSEKEEPING: 8}
    return env


def test_a_remembered_complete_with_nothing_to_lose_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(api_client, complete_source, LABOR, "c.xlsx", staff(first=NEXT_WEEK))

    assert _kinds(body) == []
    assert body["understanding"]["scope"] == {
        "effective_scope": "FULL",
        "remembered_scope": "FULL",
        "removal_count": 0,
        "requires_scope_confirmation": False,
    }


def test_a_department_gone_asks_first_and_it_is_not_imported_without_the_answer(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = staff(("Reception",))
    asked = understand(api_client, complete_source, LABOR, "c.xlsx", content)

    assert _kinds(asked) == ["FILE_SCOPE_CONFIRM"]
    assert asked["understanding"]["questions"][0]["absent_records"] == 7
    assert asked["understanding"]["scope"]["requires_scope_confirmation"] is True
    done = import_mapped(api_client, complete_source, LABOR, "c.xlsx", content, asked["proposal"])
    assert done.status_code == 409
    assert _plan(db_session, complete_source, WEEK) == {RECEPTION: 8, HOUSEKEEPING: 8}


def test_a_day_gone_asks_first_too_and_a_yes_takes_its_departments_away(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = staff(skip_day=3)

    asked = understand(api_client, complete_source, LABOR, "c.xlsx", content)
    assert _kinds(asked) == ["FILE_SCOPE_CONFIRM"]
    assert asked["understanding"]["questions"][0]["absent_records"] == 2

    done = _import(api_client, complete_source, content, COMPLETE, "c.xlsx")

    assert done["removed"] == 2
    assert _plan(db_session, complete_source, WEEK + timedelta(days=3)) == {}
    assert _plan(db_session, complete_source, WEEK) == {RECEPTION: 8, HOUSEKEEPING: 8}


def test_a_day_gone_stays_if_the_file_is_a_part(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    done = _import(api_client, complete_source, staff(skip_day=3), A_PART, "c.xlsx")

    assert done["removed"] == 0
    both = {RECEPTION: 8, HOUSEKEEPING: 8}
    assert _plan(db_session, complete_source, WEEK + timedelta(days=3)) == both


def test_a_department_missing_on_a_day_the_file_names_is_replaced_as_it_always_was(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    """Not what a memory decides: the rule of V1.2. A file speaks for the days and the departments
    it names, so this cell is replaced whatever the file is said to be, and nothing is asked. Pinned
    because it is the one way a shift stops counting without the question."""
    content = staff(without=(3, "Housekeeping"))

    body = understand(api_client, complete_source, LABOR, "c.xlsx", content)
    assert _kinds(body) == []
    assert body["understanding"]["scope"]["removal_count"] == 0

    _import(api_client, complete_source, content, A_PART, "c.xlsx")

    assert _plan(db_session, complete_source, WEEK + timedelta(days=3)) == {RECEPTION: 8}


def test_yes_it_is_the_whole_plan_stops_counting_the_department(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    done = _import(api_client, complete_source, staff(("Reception",)), COMPLETE, "c.xlsx")

    assert done["removed"] == 7
    assert _plan(db_session, complete_source, WEEK) == {RECEPTION: 8}
    job = _last_job(db_session, complete_source)
    assert (job.file_scope, job.remembered_file_scope) == (FileScope.FULL, FileScope.FULL)


def test_no_it_is_a_part_stays_for_this_import_and_the_memory_stays(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    done = _import(api_client, complete_source, staff(("Reception",), hours=6), A_PART, "c.xlsx")

    assert done["removed"] == 0
    assert _plan(db_session, complete_source, WEEK) == {RECEPTION: 6, HOUSEKEEPING: 8}
    assert _remembered(db_session, complete_source) == [FileScope.FULL]
    job = _last_job(db_session, complete_source)
    assert (job.file_scope, job.remembered_file_scope) == (FileScope.PARTIAL, FileScope.FULL)
    # one export says nothing about the next
    next_one = understand(api_client, complete_source, LABOR, "d.xlsx", staff(("Housekeeping",)))
    assert _kinds(next_one) == ["FILE_SCOPE_CONFIRM"]


def test_saying_so_explicitly_changes_the_memory(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, complete_source, staff(("Reception",)), A_PART_FROM_NOW_ON, "c.xlsx")

    assert _remembered(db_session, complete_source) == [FileScope.PARTIAL]
    next_one = understand(api_client, complete_source, LABOR, "d.xlsx", staff(("Housekeeping",)))
    assert _kinds(next_one) == []
    assert next_one["understanding"]["removes"] == 0
    assert next_one["understanding"]["scope"]["removal_count"] == 7


def test_the_same_plan_again_moves_nothing_and_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = staff(("Reception",))
    _import(api_client, complete_source, content, COMPLETE, "c.xlsx")

    done = _import(api_client, complete_source, content, name="c-di-nuovo.xlsx")

    assert done["removed"] == 0
    assert done["changed_data"] is False


def test_the_same_part_again_is_not_asked_about_twice(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = staff(("Reception",))
    _import(api_client, complete_source, content, A_PART, "c.xlsx")

    again = understand(api_client, complete_source, LABOR, "c-di-nuovo.xlsx", content)

    assert _kinds(again) == []
    assert again["understanding"]["scope"]["effective_scope"] == "PARTIAL"


def test_a_changed_plan_that_leaves_nothing_out_asks_nothing(
    api_client: TestClient, complete_source: SourcesEnv
) -> None:
    body = understand(api_client, complete_source, LABOR, "c.xlsx", staff(hours=6))

    assert _kinds(body) == []


def test_a_figure_that_moved_after_the_answer_is_refused(
    api_client: TestClient, complete_source: SourcesEnv, db_session: Session
) -> None:
    content = staff(("Reception",))
    read = understand(api_client, complete_source, LABOR, "c.xlsx", content, COMPLETE)
    assert read["understanding"]["removes"] == 7

    # another file: a department more, as a part, between the reading and the commit
    _import(api_client, complete_source, staff(("Cucina",)), A_PART, "nel-frattempo.xlsx")

    done = import_mapped(api_client, complete_source, LABOR, "c.xlsx", content, read["proposal"])

    assert done.status_code == 409
    assert done.json()["error"]["code"] == "IMPORT_DECISION_CHANGED"
    assert HOUSEKEEPING in _plan(db_session, complete_source, WEEK)


def test_under_the_lock_a_plan_that_no_longer_holds_imports_nothing(
    complete_source: SourcesEnv, db_session: Session
) -> None:
    result = LaborImportService(db_session, complete_source.tenant).import_file(
        _source(db_session, complete_source),
        filename="c.xlsx",
        content=staff(("Reception",), hours=6),
        snapshot_local_date=date(2026, 11, 4),
        property_id=complete_source.property.id,
        scope=ScopePlan(FileScope.FULL, FileScope.FULL, expected_removals=0),  # it read none
    )

    assert not result.succeeded
    assert result.error_code == LaborErrorCode.IMPORT_PLAN_CHANGED
    assert _plan(db_session, complete_source, WEEK) == {RECEPTION: 8, HOUSEKEEPING: 8}

"""What a missing (day, department) means: nothing in a part or a list of changes, a removal only in
a whole plan a person said is complete.

The case that must never happen: a file that has Monday, and has Housekeeping on Tuesday, is not a
file that removes Housekeeping on Monday. The days of a file times its departments are never what it
speaks for. REAL commits, read back through what the page and the detector read.
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.cli.imports import run_import_labor
from app.modules.data_overview.labor import LaborOverviewReader
from app.modules.ingestion.canonical_csv import (
    identity_column_mapping,
    labor_format_options,
    read_headers,
)
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    FileScope,
    ImportJob,
    ImportJobStatus,
)
from app.modules.ingestion.scope import ScopePlan
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.labor.mapping import LaborField
from app.modules.labor.models import LaborSnapshot
from app.modules.labor.roles import LaborCategory
from app.modules.labor.service import LaborImportResult, LaborImportService
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.refresh_support import Hotel, local_today, make_hotel, purge
from tests.smart_import_support import import_mapped, understand
from tests.support import BookingFactory

RECEPTION = LaborCategory.FRONT_OFFICE
HOUSEKEEPING = LaborCategory.HOUSEKEEPING
MON, TUE = 0, 1
Line = tuple[date, str, str, str]


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


def day(offset: int) -> date:
    return local_today() + timedelta(days=offset)


def current() -> list[Line]:
    """What counts before: Reception and Housekeeping, Monday and Tuesday."""
    return [
        (day(MON), "FRONT_OFFICE", "8", "120.00"),
        (day(MON), "HOUSEKEEPING", "5", "60.00"),
        (day(TUE), "FRONT_OFFICE", "8", "120.00"),
        (day(TUE), "HOUSEKEEPING", "5", "60.00"),
    ]


def diagonal() -> list[Line]:
    """Reception on Monday and Housekeeping on Tuesday, both changed: both days and both departments
    are in the file, Housekeeping on Monday and Reception on Tuesday are not."""
    return [
        (day(MON), "FRONT_OFFICE", "6", "90.00"),
        (day(TUE), "HOUSEKEEPING", "3", "36.00"),
    ]


def import_file(hotel: Hotel, name: str, rows: list[Line], scope: FileScope | None) -> Any:
    """The two steps of the page's import on the service, with what it says it took away."""
    source_id = hotel.source(DataSourceDomain.LABOR)
    path = hotel.tmp_dir / name
    lines = ["work_date,labor_category,planned_hours,planned_cost,currency"]
    lines += [f"{d.isoformat()},{cat},{hours},{cost},EUR" for d, cat, hours, cost in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    content = path.read_bytes()
    headers = read_headers(content)
    with hotel.session() as session:
        labor = LaborImportService(session, hotel.tenant)
        labor.save_mapping(
            source_id,
            headers=headers,
            column_mapping=identity_column_mapping(headers, LaborField),
            format_options=labor_format_options(),
            property_id=hotel.property_id,
        )
        result: LaborImportResult = labor.import_file(
            source_id,
            filename=name,
            content=content,
            snapshot_local_date=local_today(),
            property_id=hotel.property_id,
            scope=ScopePlan(scope),
        )
    assert result.succeeded, result
    return result


def import_worked(hotel: Hotel, name: str, rows: list[Line]) -> None:
    """A file of hours worked only: no planned column at all."""
    path = hotel.tmp_dir / name
    lines = ["work_date,labor_category,actual_hours,actual_cost,currency"]
    lines += [f"{d.isoformat()},{cat},{hours},{cost},EUR" for d, cat, hours, cost in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with hotel.session() as session:
        code = run_import_labor(
            session,
            workspace_slug=hotel.slug,
            property_slug=hotel.slug,
            data_source_id=hotel.source(DataSourceDomain.LABOR),
            file=path,
            snapshot_local_date=local_today(),
        )
    assert code == 0


def plan(hotel: Hotel, offset: int) -> dict[LaborCategory, int]:
    with hotel.session() as session:
        found = LaborEvaluationRepository(session, hotel.tenant).current_plan(
            hotel.source(DataSourceDomain.LABOR), local_today(), [day(offset)]
        )
    if day(offset) not in found:
        return {}
    totals: dict[LaborCategory, int] = {}
    for entry in found[day(offset)][1]:
        totals[entry.labor_category] = totals.get(entry.labor_category, 0) + (
            entry.planned_minutes or 0
        )
    return {category: minutes // 60 for category, minutes in totals.items()}


def worked(hotel: Hotel, offset: int) -> dict[LaborCategory, int]:
    with hotel.session() as session:
        found = LaborEvaluationRepository(session, hotel.tenant).current_labor(
            hotel.source(DataSourceDomain.LABOR), local_today(), [day(offset)]
        )[1]
    rows = found[day(offset)][1] if day(offset) in found else []
    return {
        row.labor_category: row.actual_minutes // 60
        for row in rows
        if row.actual_minutes is not None
    }


def personale(hotel: Hotel) -> Any:
    with hotel.session() as session:
        return LaborOverviewReader(session, hotel.tenant).read(
            as_of=local_today(),
            currency="EUR",
            source_id=hotel.source(DataSourceDomain.LABOR),
            source_reason=None,
            labor_decision=None,
        )


def revisions(hotel: Hotel) -> list[int]:
    with hotel.session() as session:
        return list(
            session.scalars(
                select(LaborSnapshot.revision)
                .where(LaborSnapshot.workspace_id == hotel.tenant.workspace_id)
                .order_by(LaborSnapshot.snapshot_local_date, LaborSnapshot.revision)
            ).all()
        )


def latest_job(hotel: Hotel) -> ImportJob:
    with hotel.session() as session:
        job = session.scalar(
            select(ImportJob)
            .where(
                ImportJob.workspace_id == hotel.tenant.workspace_id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
            )
            .order_by(ImportJob.finished_at.desc())
            .limit(1)
        )
    assert job is not None
    return job


# --- a part, a list of changes, a file nobody said anything about ---------------------------------


@pytest.mark.parametrize("scope", [FileScope.PARTIAL, FileScope.DELTA, None])
def test_a_part_updates_the_cells_it_holds_and_removes_none(
    hotel: Hotel, scope: FileScope | None
) -> None:
    import_file(hotel, "a.csv", current(), None)

    result = import_file(hotel, "b.csv", diagonal(), scope)

    assert result.cells_cleared == 0
    assert plan(hotel, MON) == {RECEPTION: 6, HOUSEKEEPING: 5}  # Housekeeping Monday stays
    assert plan(hotel, TUE) == {RECEPTION: 8, HOUSEKEEPING: 3}  # Reception Tuesday stays


@pytest.mark.parametrize("scope", [FileScope.PARTIAL, FileScope.DELTA])
def test_what_a_part_leaves_out_still_counts_on_the_page(hotel: Hotel, scope: FileScope) -> None:
    import_file(hotel, "a.csv", current(), None)

    import_file(hotel, "b.csv", diagonal(), scope)

    figures = personale(hotel).economics
    assert figures.planned_hours == Decimal("22.00")  # 6 + 5 on Monday, 8 + 3 on Tuesday
    assert figures.planned_cost == Decimal("306.00")  # 90 + 60 + 120 + 36


# --- the same file, said complete -----------------------------------------------------------------


def test_the_same_file_said_complete_takes_the_two_missing_cells_away(hotel: Hotel) -> None:
    import_file(hotel, "a.csv", current(), None)

    result = import_file(hotel, "b.csv", diagonal(), FileScope.FULL)

    assert result.cells_cleared == 2
    assert plan(hotel, MON) == {RECEPTION: 6}
    assert plan(hotel, TUE) == {HOUSEKEEPING: 3}
    assert revisions(hotel) == [1, 2]  # the older plan stays in the history, the same day
    assert personale(hotel).economics.planned_hours == Decimal("9.00")


# --- the same data again --------------------------------------------------------------------------


@pytest.mark.parametrize("scope", [FileScope.PARTIAL, FileScope.DELTA, None])
def test_a_part_that_repeats_what_counts_moves_nothing(
    hotel: Hotel, scope: FileScope | None
) -> None:
    import_file(hotel, "a.csv", current(), None)
    reception_monday, _, _, housekeeping_tuesday = current()

    import_file(hotel, "b.csv", [reception_monday, housekeeping_tuesday], scope)

    assert latest_job(hotel).changed_data is False
    assert revisions(hotel) == [1]


def test_the_same_cells_said_complete_are_news_because_of_what_they_leave_out(
    hotel: Hotel,
) -> None:
    import_file(hotel, "a.csv", current(), None)
    reception_monday, _, _, housekeeping_tuesday = current()

    import_file(hotel, "b.csv", [reception_monday, housekeeping_tuesday], FileScope.FULL)

    assert latest_job(hotel).changed_data is True
    assert revisions(hotel) == [1, 2]


def test_the_same_part_twice_is_a_no_op_the_second_time(hotel: Hotel) -> None:
    import_file(hotel, "a.csv", current(), None)
    import_file(hotel, "b.csv", diagonal(), FileScope.PARTIAL)

    import_file(hotel, "b-di-nuovo.csv", diagonal(), FileScope.PARTIAL)

    assert latest_job(hotel).changed_data is False
    assert revisions(hotel) == [1, 2]


# --- planned and worked hours stay apart ----------------------------------------------------------


@pytest.mark.parametrize("scope", [FileScope.PARTIAL, FileScope.DELTA, FileScope.FULL])
def test_no_part_or_whole_plan_touches_the_hours_worked(hotel: Hotel, scope: FileScope) -> None:
    import_file(hotel, "a.csv", current(), None)
    import_worked(
        hotel,
        "consuntivo.csv",
        [(day(MON), "HOUSEKEEPING", "4", "48.00"), (day(TUE), "FRONT_OFFICE", "7", "105.00")],
    )

    import_file(hotel, "b.csv", diagonal(), scope)

    assert worked(hotel, MON) == {HOUSEKEEPING: 4}
    assert worked(hotel, TUE) == {RECEPTION: 7}
    expected_monday = {RECEPTION: 6} if scope is FileScope.FULL else {RECEPTION: 6, HOUSEKEEPING: 5}
    assert plan(hotel, MON) == expected_monday  # the hours worked never stand in for the plan


# --- a zero is a plan of zero hours, not a removal ------------------------------------------------


def test_a_zero_in_a_part_is_a_plan_of_zero_hours_not_a_removal(hotel: Hotel) -> None:
    """Zero hours replaces the cell with a zero, which the analysis reads as a department scheduled
    for nothing. Taking the cell away is a whole plan's job (FULL)."""
    import_file(hotel, "a.csv", current(), None)

    import_file(hotel, "b.csv", [(day(MON), "HOUSEKEEPING", "0", "0.00")], FileScope.PARTIAL)

    assert plan(hotel, MON) == {RECEPTION: 8, HOUSEKEEPING: 0}
    assert plan(hotel, TUE) == {RECEPTION: 8, HOUSEKEEPING: 5}


# --- through the page, with no memory yet ---------------------------------------------------------


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


LABOR = "LABOR"
HEADERS = ["Giorno", "Reparto", "Ore previste", "Costo previsto"]
WEEK = date(2027, 3, 1)


def staff(*, without: frozenset[tuple[int, str]] = frozenset(), hours: int = 8) -> bytes:
    rows = [
        [datetime.combine(WEEK + timedelta(days=offset), datetime.min.time()), name, hours, 100]
        for offset in range(7)
        for name in ("Reception", "Housekeeping")
        if (offset, name) not in without
    ]
    return xlsx_bytes({"Turni": [HEADERS, *rows]})


DIAGONAL = frozenset({(0, "Housekeeping"), (1, "Reception")})


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


def _plan(session: Session, env: SourcesEnv, offset: int) -> dict[LaborCategory, int]:
    session.expire_all()
    source = session.scalar(
        select(DataSource).where(
            DataSource.workspace_id == env.workspace.id,
            DataSource.domain == DataSourceDomain.LABOR,
        )
    )
    assert source is not None
    wanted = WEEK + timedelta(days=offset)
    found = LaborEvaluationRepository(session, env.tenant).current_plan(
        source.id, date(2030, 1, 1), [wanted]
    )
    totals: dict[LaborCategory, int] = {}
    for entry in found[wanted][1] if wanted in found else []:
        totals[entry.labor_category] = totals.get(entry.labor_category, 0) + (
            entry.planned_minutes or 0
        )
    return {category: minutes // 60 for category, minutes in totals.items()}


def test_through_the_page_the_missing_cells_are_asked_about_and_never_taken_silently(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, staff())
    content = staff(without=DIAGONAL, hours=6)

    asked = understand(api_client, env, LABOR, "b.xlsx", content)

    assert [question["kind"] for question in asked["understanding"]["questions"]] == ["FILE_SCOPE"]
    assert asked["understanding"]["questions"][0]["absent_records"] == 2
    assert asked["understanding"]["removes"] == 0  # nobody said anything yet
    assert _plan(db_session, env, 0) == {RECEPTION: 8, HOUSEKEEPING: 8}


@pytest.mark.parametrize("scope", ["PARTIAL", "DELTA"])
def test_through_the_page_a_part_removes_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session, scope: str
) -> None:
    _import(api_client, env, staff())

    done = _import(
        api_client, env, staff(without=DIAGONAL, hours=6), {"file_scope": scope}, "b.xlsx"
    )

    assert done["removed"] == 0
    assert _plan(db_session, env, 0) == {RECEPTION: 6, HOUSEKEEPING: 8}
    assert _plan(db_session, env, 1) == {RECEPTION: 8, HOUSEKEEPING: 6}
    assert _plan(db_session, env, 2) == {RECEPTION: 6, HOUSEKEEPING: 6}


def test_through_the_page_the_whole_plan_takes_the_two_cells_away(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    _import(api_client, env, staff())

    done = _import(
        api_client, env, staff(without=DIAGONAL, hours=6), {"file_scope": "FULL"}, "b.xlsx"
    )

    assert done["removed"] == 2
    assert _plan(db_session, env, 0) == {RECEPTION: 6}
    assert _plan(db_session, env, 1) == {HOUSEKEEPING: 6}
    assert _plan(db_session, env, 2) == {RECEPTION: 6, HOUSEKEEPING: 6}

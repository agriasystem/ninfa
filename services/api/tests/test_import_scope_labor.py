"""What the absence of a department means, and why hours worked are not a plan.

REAL commits, read back through what the page and the detector read. The rule itself, as a table of
cases, is in `test_labor_current_plan.py`.
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.modules.data_overview.labor import LaborOverviewReader
from app.modules.ingestion.models import DataSourceDomain, FileScope, ImportJob, ImportJobStatus
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.labor.models import LaborEntry, LaborSnapshot
from app.modules.labor.roles import LaborCategory
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import SourcesEnv, sources_env
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel, purge
from tests.smart_import_support import import_mapped, understand
from tests.support import BookingFactory

RECEPTION = LaborCategory.FRONT_OFFICE
HOUSEKEEPING = LaborCategory.HOUSEKEEPING


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


def day(offset: int) -> date:
    return local_today() + timedelta(days=offset)


def shifts(category: str, offsets: range, *, hours: str = "8", cost: str = "120.00") -> list[Any]:
    return [(day(offset), category, hours, cost) for offset in offsets]


WEEK = range(0, 7)


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


def personale(hotel: Hotel) -> Any:
    with hotel.session() as session:
        return LaborOverviewReader(session, hotel.tenant).read(
            as_of=local_today(),
            currency="EUR",
            source_id=hotel.source(DataSourceDomain.LABOR),
            source_reason=None,
            labor_decision=None,
        )


def snapshots(hotel: Hotel) -> int:
    with hotel.session() as session:
        return len(
            session.scalars(
                select(LaborSnapshot.id).where(
                    LaborSnapshot.workspace_id == hotel.tenant.workspace_id
                )
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


BOTH = [*shifts("FRONT_OFFICE", WEEK), *shifts("HOUSEKEEPING", WEEK, hours="5", cost="60.00")]


# --- a complete file ------------------------------------------------------------------------------


def test_a_complete_plan_takes_away_a_department_it_no_longer_holds(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)

    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)

    assert plan(hotel, 3) == {RECEPTION: 8}
    figures = personale(hotel).economics
    assert figures.planned_hours == Decimal("56.00")  # 7 x 8: housekeeping no longer counts
    assert figures.planned_cost == Decimal("840.00")
    assert latest_job(hotel).file_scope is FileScope.FULL


def test_the_older_plan_stays_in_the_history(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)
    entries_before = _entries(hotel)

    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)

    assert snapshots(hotel) == 2
    assert _entries(hotel) == entries_before + 7  # nothing deleted, the new file's rows added


def _entries(hotel: Hotel) -> int:
    with hotel.session() as session:
        return len(
            session.scalars(
                select(LaborEntry.id).where(LaborEntry.workspace_id == hotel.tenant.workspace_id)
            ).all()
        )


def test_a_complete_plan_clears_a_day_of_its_period_it_holds_nothing_for(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)
    holes = [row for row in shifts("FRONT_OFFICE", WEEK) if row[0] != day(3)]

    hotel.import_shifts("b.csv", holes, file_scope=FileScope.FULL)

    assert plan(hotel, 3) == {}
    assert plan(hotel, 2) == {RECEPTION: 8}


def test_a_complete_plan_is_silent_outside_its_own_period(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)

    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", range(0, 3)), file_scope=FileScope.FULL)

    assert plan(hotel, 2) == {RECEPTION: 8}
    assert plan(hotel, 5) == {RECEPTION: 8, HOUSEKEEPING: 5}


def test_the_same_complete_plan_again_moves_nothing(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)
    only = shifts("FRONT_OFFICE", WEEK)
    hotel.import_shifts("b.csv", only, file_scope=FileScope.FULL)
    before = snapshots(hotel)

    hotel.import_shifts("b-di-nuovo.csv", only, file_scope=FileScope.FULL)

    assert snapshots(hotel) == before
    assert latest_job(hotel).changed_data is False


def test_the_same_hours_are_not_a_no_op_if_the_file_also_takes_something_away(hotel: Hotel) -> None:
    """Reception says what already counts; the file is still news, because of what it leaves out."""
    hotel.import_shifts("a.csv", BOTH)

    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)

    assert latest_job(hotel).changed_data is True
    assert snapshots(hotel) == 2


def test_a_later_department_file_comes_back_over_a_complete_plan(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)
    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)

    hotel.import_shifts(
        "c.csv", shifts("HOUSEKEEPING", WEEK, hours="4"), file_scope=FileScope.PARTIAL
    )

    assert plan(hotel, 3) == {RECEPTION: 8, HOUSEKEEPING: 4}


# --- a part of it --------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", [None, FileScope.PARTIAL, FileScope.DELTA])
def test_a_file_of_one_department_leaves_the_others_alone(
    hotel: Hotel, scope: FileScope | None
) -> None:
    hotel.import_shifts("a.csv", BOTH)

    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK, hours="6"), file_scope=scope)

    assert plan(hotel, 3) == {RECEPTION: 6, HOUSEKEEPING: 5}


def test_a_new_version_of_the_plan_still_replaces_it(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)

    hotel.import_shifts(
        "b.csv",
        [*shifts("FRONT_OFFICE", WEEK, hours="6"), *shifts("HOUSEKEEPING", WEEK, hours="3")],
        file_scope=FileScope.FULL,
    )

    assert plan(hotel, 3) == {RECEPTION: 6, HOUSEKEEPING: 3}
    assert personale(hotel).economics.planned_hours == Decimal("63.00")  # never a sum


# --- hours worked are not a plan ---------------------------------------------------------------


def _import_worked(hotel: Hotel, name: str, rows: list[tuple[date, str, str, str]]) -> None:
    """A file of hours worked only: no planned column at all."""
    source = hotel.source(DataSourceDomain.LABOR)
    path = hotel.tmp_dir / name
    lines = ["work_date,labor_category,actual_hours,actual_cost,currency"]
    lines += [f"{d.isoformat()},{cat},{hours},{cost},EUR" for d, cat, hours, cost in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from app.cli.imports import run_import_labor

    with hotel.session() as session:
        code = run_import_labor(
            session,
            workspace_slug=hotel.slug,
            property_slug=hotel.slug,
            data_source_id=source,
            file=path,
            snapshot_local_date=local_today(),
        )
    assert code == 0


def _worked(hotel: Hotel, offset: int) -> list[Any]:
    with hotel.session() as session:
        found = LaborEvaluationRepository(session, hotel.tenant).current_labor(
            hotel.source(DataSourceDomain.LABOR), local_today(), [day(offset)]
        )[1]
    return found[day(offset)][1] if day(offset) in found else []


def test_a_file_of_hours_worked_does_not_take_the_place_of_the_plan(hotel: Hotel) -> None:
    hotel.import_shifts("plan.csv", shifts("FRONT_OFFICE", WEEK))
    figures = personale(hotel).economics

    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    assert plan(hotel, 3) == {RECEPTION: 8}
    after = personale(hotel).economics
    assert (after.planned_hours, after.planned_cost) == (
        figures.planned_hours,
        figures.planned_cost,
    )
    assert latest_job(hotel).changed_data is True  # it is new: it is simply not the plan


def test_a_comparison_with_the_past_reads_the_hours_worked_of_that_file(hotel: Hotel) -> None:
    hotel.import_shifts("plan.csv", shifts("FRONT_OFFICE", WEEK))
    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    [row] = _worked(hotel, 3)

    assert row.actual_minutes == 180
    assert row.planned_minutes is None  # the two never mix inside a category


def test_a_new_plan_does_not_take_the_place_of_the_hours_worked(hotel: Hotel) -> None:
    hotel.import_shifts("plan.csv", shifts("FRONT_OFFICE", WEEK))
    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    hotel.import_shifts("plan-2.csv", shifts("FRONT_OFFICE", WEEK, hours="9"))

    assert plan(hotel, 3) == {RECEPTION: 9}
    [row] = _worked(hotel, 3)
    assert row.actual_minutes == 180


def test_a_complete_plan_says_nothing_about_the_hours_worked(hotel: Hotel) -> None:
    hotel.import_shifts("plan.csv", BOTH)
    _import_worked(hotel, "consuntivo.csv", shifts("HOUSEKEEPING", WEEK, hours="3"))

    hotel.import_shifts("plan-2.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)

    assert plan(hotel, 3) == {RECEPTION: 8}
    worked = {row.labor_category: row.actual_minutes for row in _worked(hotel, 3)}
    assert worked[HOUSEKEEPING] == 180


def test_the_same_hours_worked_again_move_nothing(hotel: Hotel) -> None:
    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))
    before = snapshots(hotel)

    _import_worked(hotel, "consuntivo-2.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    assert snapshots(hotel) == before
    assert latest_job(hotel).changed_data is False


def test_with_only_hours_worked_the_plan_says_it_does_not_know(hotel: Hotel) -> None:
    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    view = personale(hotel)

    assert view.economics.planned_hours is None  # never the hours worked, passed off as a plan


def test_the_analysis_stays_coherent_after_hours_worked_arrive(hotel: Hotel) -> None:
    hotel.import_bookings("p.csv", [booking_row("A", 1)])
    hotel.import_shifts("plan.csv", shifts("FRONT_OFFICE", WEEK))
    first = hotel.refresh().result
    _import_worked(hotel, "consuntivo.csv", shifts("FRONT_OFFICE", WEEK, hours="3"))

    second = hotel.refresh().result

    assert second.labor_target_count == first.labor_target_count


# --- same-day ------------------------------------------------------------------------------------


def test_complete_partial_and_new_files_all_arrive_the_same_day(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", BOTH)
    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)
    hotel.import_shifts(
        "c.csv", shifts("HOUSEKEEPING", WEEK, hours="2"), file_scope=FileScope.PARTIAL
    )
    hotel.import_shifts("d.csv", shifts("KITCHEN", range(7, 10)), file_scope=FileScope.DELTA)

    assert snapshots(hotel) == 4
    assert plan(hotel, 3) == {RECEPTION: 8, HOUSEKEEPING: 2}
    assert plan(hotel, 8) == {LaborCategory.KITCHEN: 8}


def test_the_run_says_which_files_it_read_after_a_complete_one(hotel: Hotel) -> None:
    from app.modules.decisions.models import DecisionRun
    from app.modules.decisions.provenance import RunInputProvenance

    hotel.import_bookings("p.csv", [booking_row("A", 1)])
    hotel.import_shifts("a.csv", BOTH)
    hotel.refresh()
    hotel.import_shifts("b.csv", shifts("FRONT_OFFICE", WEEK), file_scope=FileScope.FULL)
    complete = latest_job(hotel).id

    hotel.refresh()

    with hotel.session() as session:
        runs = session.scalars(
            select(DecisionRun)
            .where(DecisionRun.workspace_id == hotel.tenant.workspace_id)
            .order_by(DecisionRun.run_sequence)
        ).all()
    latest = runs[-1].input_provenance
    assert latest is not None
    labor = RunInputProvenance.from_json(latest).labor
    assert labor is not None and labor.import_job_id == complete


# --- the question, through the real API --------------------------------------------------------


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


LABOR = "LABOR"
STAFF_HEADERS = ["Giorno", "Reparto", "Ore previste", "Costo previsto"]


def staff_file(
    departments: tuple[str, ...], first: date = date(2027, 3, 1), days: int = 7
) -> bytes:
    rows = [
        [datetime.combine(first + timedelta(days=offset), datetime.min.time()), name, 8, 100]
        for offset in range(days)
        for name in departments
    ]
    return xlsx_bytes({"Turni": [STAFF_HEADERS, *rows]})


def _questions(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


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


BOTH_NAMES = ("Reception", "Housekeeping")


def test_a_second_week_asks_nothing(api_client: TestClient, env: SourcesEnv) -> None:
    _import(api_client, env, staff_file(BOTH_NAMES))

    body = understand(api_client, env, LABOR, "b.xlsx", staff_file(BOTH_NAMES, date(2027, 3, 8)))

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []


def test_a_file_with_fewer_departments_asks_once_what_it_is(
    api_client: TestClient, env: SourcesEnv
) -> None:
    _import(api_client, env, staff_file(BOTH_NAMES))

    body = understand(api_client, env, LABOR, "b.xlsx", staff_file(("Reception",)))

    assert _questions(body) == ["FILE_SCOPE"]
    assert (
        body["understanding"]["questions"][0]["absent_records"] == 7
    )  # seven days of housekeeping


def test_the_answer_is_remembered_for_that_structure(
    api_client: TestClient, env: SourcesEnv
) -> None:
    _import(api_client, env, staff_file(BOTH_NAMES))
    _import(api_client, env, staff_file(("Reception",)), {"file_scope": "PARTIAL"}, name="b.xlsx")

    body = understand(api_client, env, LABOR, "c.xlsx", staff_file(("Housekeeping",)))

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []
    assert body["proposal"]["file_scope"] == "PARTIAL"


def test_another_structure_does_not_inherit_the_answer(
    api_client: TestClient, env: SourcesEnv
) -> None:
    _import(api_client, env, staff_file(BOTH_NAMES))
    _import(api_client, env, staff_file(("Reception",)), {"file_scope": "FULL"}, name="b.xlsx")
    other_headers = ["Data", "Settore", "Ore pianificate", "Spesa prevista"]
    rows = [[datetime(2027, 3, 1 + offset), "Reception", 8, 100] for offset in range(7)]
    other = xlsx_bytes({"Altro": [other_headers, *rows]})

    body = understand(api_client, env, LABOR, "altro.xlsx", other)

    assert body["proposal"]["file_scope"] is None


def test_hours_that_do_not_say_which_are_asked_about_once_and_remembered(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """The planned/actual question was already there: it keeps a plan from being replaced."""
    headers = ["Giorno", "Reparto", "Ore"]
    rows = [[datetime(2027, 3, 1 + offset), name, 8] for offset in range(7) for name in BOTH_NAMES]
    first = xlsx_bytes({"Turni": [headers, *rows]})
    asked = understand(api_client, env, LABOR, "a.xlsx", first)
    assert "COLUMN_MEANING" in _questions(asked)

    answers = {"column_fields": {"Ore": "actual_hours"}}
    _import(api_client, env, first, answers)

    later = [[datetime(2027, 3, 8 + offset), name, 7] for offset in range(7) for name in BOTH_NAMES]
    body = understand(api_client, env, LABOR, "b.xlsx", xlsx_bytes({"Turni": [headers, *later]}))

    assert body["understanding"]["level"] == "READY"
    assert _questions(body) == []

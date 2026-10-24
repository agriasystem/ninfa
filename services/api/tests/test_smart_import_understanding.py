"""Smart Import V3: NINFA reads the DOCUMENT, then asks only what is really ambiguous.

The flows of a staff file, end to end through the real API:

    file -> `import-understanding` (what it is, what each column means, what is still unclear)
         -> `import-validation` with the proposed decision (the same dry run as V2)
         -> `imports/mapped` (all or nothing) -> the way of reading is remembered
         -> the next file of the same layout is recognised, with no question at all

The acceptance criterion of this gate is pinned first: a column called "Reparto o mansione" is a
column of departments, read row by row - NINFA never asks "which department are all the rows?".
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.labor.models import LaborEntry, LaborMappingProfile
from app.modules.labor.roles import LaborCategory
from tests import understanding_support as corpus
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import (
    by_header,
    import_mapped,
    profiles_of,
    understand,
    validation,
)
from tests.support import BookingFactory

LABOR = "LABOR"


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _question_kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _recognized(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["field"]: item for item in body["understanding"]["recognized"]}


def _imported(
    client: TestClient, env: SourcesEnv, name: str, content: bytes, mapping: Any
) -> dict[str, Any]:
    response = import_mapped(client, env, LABOR, name, content, mapping)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- the bug that started it: "Reparto o mansione" -----------------------------------------------


def test_a_column_called_reparto_o_mansione_is_read_row_by_row_and_never_asked_about(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content, expected = corpus.staff_simple_xlsx()

    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    # recognised ...
    by = by_header(body)
    assert by["Reparto o mansione"]["field"] == "role"
    role = _recognized(body)["role"]
    assert role["level"] == "HIGH"
    assert role["origin"] == {"kind": "COLUMN", "detail": "Reparto o mansione"}
    # ... used row by row: the decision maps the COLUMN, there is no single value for all the rows
    proposal = body["proposal"]
    assert {c["header"]: c["field"] for c in proposal["columns"]}["Reparto o mansione"] == "role"
    assert "labor_category" not in proposal["constants"]
    # ... and NINFA does not ask "which department are all the rows?"
    assert "DEPARTMENT_ROWS" not in _question_kinds(body)
    assert "DEPARTMENT_CONFIRM" not in _question_kinds(body)
    assert body["understanding"]["level"] == "READY"

    tried = validation(api_client, env, LABOR, content, proposal, name="turni.xlsx")
    assert tried["can_import"] is True and tried["rows_total"] == expected.rows
    _imported(api_client, env, "turni.xlsx", content, proposal)
    categories = {
        e.labor_category
        for e in db_session.scalars(
            select(LaborEntry).where(LaborEntry.workspace_id == env.workspace.id)
        )
    }
    # each row got ITS department: Reception, Housekeeping, Cucina ... not one value for all
    assert {
        LaborCategory.FRONT_OFFICE,
        LaborCategory.HOUSEKEEPING,
        LaborCategory.KITCHEN,
    } <= categories


@pytest.mark.parametrize(
    "header",
    [
        "Reparto o mansione",
        "Reparto/Mansione",
        "Area / reparto",
        "Reparto - mansione",
        "REPARTO O MANSIONE",
        "Mansione",
        "Dipartimento",
        "Department",
        "Team",
    ],
)
def test_the_many_ways_of_writing_the_department_column_are_all_recognised(
    api_client: TestClient, env: SourcesEnv, header: str
) -> None:
    rows: list[list[object]] = [
        ["Data", "Nome", header, "Ore previste"],
        ["26/10/2026", "Marta Conti", "Reception", 8],
        ["26/10/2026", "Anna Bianchi", "Housekeeping", 6],
        ["26/10/2026", "Paolo Neri", "Cucina", 8],
        ["27/10/2026", "Marta Conti", "Reception", 8],
        ["27/10/2026", "Anna Bianchi", "Housekeeping", 6],
    ]
    content = corpus.csv_of(rows)

    body = understand(api_client, env, LABOR, "turni.csv", content)

    assert by_header(body)[header]["field"] == "role"
    assert "DEPARTMENT_ROWS" not in _question_kinds(body)


# --- a realistic file: title, summary, header on row 8, a total row ------------------------------


def test_a_realistic_staff_file_is_understood_with_no_question_and_nothing_stored_about_people(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content, expected = corpus.staff_title_summary_xlsx()

    body = understand(api_client, env, LABOR, "turni-ottobre.xlsx", content)

    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == []
    assert u["detection"]["domain"] == LABOR and u["detection"]["level"] == "HIGH"
    assert u["people"] == expected.people  # counted in memory ...
    table = u["document"]["table"]
    assert table["first_row"] > 1 and table["data_rows"] == expected.rows
    assert u["document"]["skipped"]["totals"] >= 1  # the TOTALE row is not a shift
    # ... and never sent back: no name of a person is anywhere in the answer
    text = repr(body)
    assert not any(name in text for name, *_ in corpus.PEOPLE)
    # the column of names is recognised as personal data and left out
    person = by_header(body)["Nome e cognome"]
    assert person["field"] is None and person["not_used_reason"] is not None
    assert person["examples"] == []


def test_the_dry_run_of_the_proposal_gives_the_summary_that_comes_from_the_file(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content, expected = corpus.staff_title_summary_xlsx()
    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    tried = validation(api_client, env, LABOR, content, body["proposal"], name="turni.xlsx")

    assert tried["can_import"] is True and tried["rows_invalid"] == 0
    assert tried["rows_total"] == expected.rows
    summary = tried["summary"]
    assert len(summary["departments"]) == expected.departments
    assert Decimal(summary["planned_hours"]) == expected.planned_hours
    assert Decimal(summary["actual_hours"]) == expected.actual_hours
    assert Decimal(summary["planned_cost"]) == expected.planned_cost
    assert summary["currency"] == "EUR"
    assert summary["date_from"] == "2026-10-26"


def test_the_import_keeps_no_identity_and_the_way_of_reading_is_remembered(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content, expected = corpus.staff_title_summary_xlsx()
    proposal = understand(api_client, env, LABOR, "turni.xlsx", content)["proposal"]

    done = _imported(api_client, env, "turni.xlsx", content, proposal)

    assert done["succeeded"] is True and done["created"] == expected.rows
    entries = list(
        db_session.scalars(select(LaborEntry).where(LaborEntry.workspace_id == env.workspace.id))
    )
    assert len(entries) == expected.rows
    stored = repr([vars(e) for e in entries])
    assert not any(name in stored for name, *_ in corpus.PEOPLE)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    saved = repr((profile.column_mapping, profile.role_mapping, profile.format_options))
    assert not any(name in saved for name, *_ in corpus.PEOPLE)
    assert "Hotel Aurora" not in saved  # the title of the file is not part of the way of reading
    # the layout is there even when it holds nothing else: it is what makes the next file be read
    # the same way (title, summary and total skipped, the header found by what the rows are)
    assert "layout" in profile.format_options
    # the file has costs and no currency: the hotel's own currency is remembered as a fixed value
    assert profile.column_mapping["currency"] == {"constant": "EUR"}


def test_the_next_file_of_the_same_layout_is_recognised_and_asks_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    first, _ = corpus.staff_title_summary_xlsx(days=3)
    proposal = understand(api_client, env, LABOR, "turni-43.xlsx", first)["proposal"]
    _imported(api_client, env, "turni-43.xlsx", first, proposal)

    second, expected = corpus.staff_title_summary_xlsx(days=4)
    body = understand(api_client, env, LABOR, "settimana-successiva.xlsx", second)

    assert body["profile"]["status"] == "RECOGNIZED"
    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == []
    assert u["people"] == expected.people
    again = validation(api_client, env, LABOR, second, None, name="settimana-successiva.xlsx")
    assert again["status"] == "READY" and again["rows_total"] == expected.rows


def test_no_name_of_a_person_is_ever_a_value_of_any_response(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content, _ = corpus.staff_title_summary_xlsx()
    asked = understand(api_client, env, LABOR, "turni.xlsx", content)
    tried = validation(api_client, env, LABOR, content, asked["proposal"], name="turni.xlsx")

    for body in (asked, tried):
        assert not any(name in repr(body) for name, *_ in corpus.PEOPLE)

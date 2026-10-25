"""Smart Import V3: what NINFA does with the SHAPES hotels give their staff files.

A department that is a sheet, a line or the title; a grid of people x days; a weekly summary; a
two-level header; two tables; totals that do or do not add up; words only this hotel uses; cells
that try to give orders. Each is read from the real bytes, through the real API - and each ends in
one of four honest outcomes: nothing to ask, ONE question, the matching screen, or a plain "this
cannot be imported as it is, and here is why".
"""

from collections.abc import Callable
from datetime import date
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
    writes,
)
from tests.support import BookingFactory

LABOR = "LABOR"


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _level(body: dict[str, Any]) -> str:
    return str(body["understanding"]["level"])


def _kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _blockers(body: dict[str, Any]) -> list[str]:
    return [b["code"] for b in body["understanding"]["blockers"]]


def _origin(body: dict[str, Any], field: str) -> dict[str, Any]:
    item = next(r for r in body["understanding"]["recognized"] if r["field"] == field)
    origin: dict[str, Any] = item["origin"]
    return origin


def _entries(db_session: Session, env: SourcesEnv) -> list[LaborEntry]:
    return list(
        db_session.scalars(select(LaborEntry).where(LaborEntry.workspace_id == env.workspace.id))
    )


def _tried(
    client: TestClient, env: SourcesEnv, content: bytes, body: dict[str, Any], name: str = "t.xlsx"
) -> dict[str, Any]:
    result: dict[str, Any] = validation(client, env, LABOR, content, body["proposal"], name=name)
    return result


def _import(
    client: TestClient, env: SourcesEnv, content: bytes, body: dict[str, Any], name: str = "t.xlsx"
) -> dict[str, Any]:
    response = import_mapped(client, env, LABOR, name, content, body["proposal"])
    assert response.status_code == 200, response.text
    done: dict[str, Any] = response.json()
    return done


# --- where the department comes from -------------------------------------------------------------


def test_a_sheet_per_department_labels_its_rows_and_the_summary_sheet_is_not_data(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_sheet_per_department_xlsx()

    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(body) == "READY" and body["understanding"]["questions"] == []
    assert _origin(body, "role")["kind"] == "SHEET"
    table = body["understanding"]["document"]["table"]
    assert table["partition"] is True
    assert table["sheets"] == ["Reception", "Housekeeping", "Cucina"]  # not "Riepilogo"
    summary_sheet = next(
        s for s in body["understanding"]["document"]["sheets"] if s["name"] == "Riepilogo"
    )
    assert summary_sheet["role"] == "SUMMARY"

    tried = _tried(api_client, env, content, body)
    assert tried["can_import"] is True and tried["rows_total"] == table["data_rows"]
    _import(api_client, env, content, body)
    assert {e.labor_category for e in _entries(db_session, env)} == {
        LaborCategory.FRONT_OFFICE,
        LaborCategory.HOUSEKEEPING,
        LaborCategory.KITCHEN,
    }


def test_a_department_written_on_a_line_of_its_own_labels_the_rows_under_it(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_sections_xlsx()

    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(body) == "READY"
    assert _origin(body, "role")["kind"] == "SECTION"
    assert body["understanding"]["document"]["skipped"]["sections"] == 2
    # "RECEPTION" is a department, never a date, a person or a row of data
    assert body["understanding"]["document"]["table"]["data_rows"] == 5
    assert _tried(api_client, env, content, body)["rows_invalid"] == 0
    _import(api_client, env, content, body)
    assert {e.labor_category for e in _entries(db_session, env)} == {
        LaborCategory.FRONT_OFFICE,
        LaborCategory.HOUSEKEEPING,
    }


def test_a_department_only_in_the_title_is_proposed_and_the_person_confirms_it(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_title_department_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["DEPARTMENT_CONFIRM"]
    question = asked["understanding"]["questions"][0]
    assert (
        question["candidate"] == "HOUSEKEEPING"
    )  # the least certain source: confirmed, not assumed

    confirmed = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"department_from": "TITLE"}
    )

    assert _level(confirmed) == "READY"
    assert _origin(confirmed, "role") == {"kind": "TITLE", "detail": "HOUSEKEEPING"}
    _import(api_client, env, content, confirmed)
    assert {e.labor_category for e in _entries(db_session, env)} == {LaborCategory.HOUSEKEEPING}


def test_when_nothing_says_the_department_one_question_is_asked_and_the_answer_is_a_fixed_value(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_no_department_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["DEPARTMENT_ROWS"]
    assert "labor_category" not in asked["proposal"]["constants"]  # never guessed

    answered = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"department_value": "FRONT_OFFICE"}
    )

    assert _level(answered) == "READY"
    assert answered["proposal"]["constants"]["labor_category"] == "FRONT_OFFICE"
    assert _origin(answered, "labor_category")["kind"] == "USER"
    _import(api_client, env, content, answered)
    assert {e.labor_category for e in _entries(db_session, env)} == {LaborCategory.FRONT_OFFICE}


# --- words only this hotel uses ------------------------------------------------------------------


def test_unknown_department_words_are_asked_once_with_how_often_they_appear(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(api_client, env, LABOR, "turni.xlsx", corpus.staff_unknown_labels_xlsx())

    assert _level(body) == "ASK" and _kinds(body) == ["VALUE_LABELS"]
    question = body["understanding"]["questions"][0]
    # one question, not one per row: the words and how often each appears - nothing else
    assert {(item["label"], item["count"]) for item in question["labels"]} == {
        ("HK", 3),
        ("Turno A", 3),
    }
    assert question["document"] == "role_mapping"


def test_a_taught_word_is_remembered_for_this_source_and_asks_nothing_next_time(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_unknown_labels_xlsx()
    taught = {"labels": {"role_mapping": {"HK": "HOUSEKEEPING", "Turno A": "FRONT_OFFICE"}}}
    body = understand(api_client, env, LABOR, "turni.xlsx", content, taught)
    assert _level(body) == "READY"

    _import(api_client, env, content, body)

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    assert profile.role_mapping == {"hk": "HOUSEKEEPING", "turno a": "FRONT_OFFICE"}
    assert {e.labor_category for e in _entries(db_session, env)} >= {
        LaborCategory.HOUSEKEEPING,
        LaborCategory.FRONT_OFFICE,
    }
    again = understand(api_client, env, LABOR, "settimana-dopo.xlsx", content)
    assert again["profile"]["status"] == "RECOGNIZED"
    assert _level(again) == "READY" and again["understanding"]["questions"] == []


def test_what_one_hotel_taught_is_not_known_by_another(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    content = corpus.staff_unknown_labels_xlsx()
    taught = {"labels": {"role_mapping": {"HK": "HOUSEKEEPING", "Turno A": "FRONT_OFFICE"}}}
    _import(api_client, env, content, understand(api_client, env, LABOR, "t.xlsx", content, taught))
    sister_env = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)

    other = understand(api_client, sister_env, LABOR, "turni.xlsx", content)

    assert other["profile"]["status"] == "NONE"
    assert _kinds(other) == ["VALUE_LABELS"]  # the sister hotel is asked again


def test_a_department_that_ninfa_cannot_use_is_never_silently_imported(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_unknown_labels_xlsx()
    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    tried = _tried(api_client, env, content, body)

    # the dry run of the UNTAUGHT proposal says what is left, instead of importing "OTHER"
    assert tried["rows_unclassified"] > 0 or tried["questions"]


# --- a column of hours that does not say which ---------------------------------------------------


def test_a_bare_hours_column_is_asked_about_and_never_guessed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.staff_bare_hours_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["COLUMN_MEANING"]
    question = asked["understanding"]["questions"][0]
    assert question["column"] == "Ore"
    assert {c["value"] for c in question["choices"]} == {"planned_hours", "actual_hours"}
    assert by_header(asked)["Ore"]["field"] is None

    answered = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"column_fields": {"Ore": "planned_hours"}}
    )

    assert _level(answered) == "READY" and _origin(answered, "planned_hours")["kind"] == "USER"


def test_two_columns_with_the_same_header_are_renamed_not_refused_and_asked_about(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.staff_duplicate_headers_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert asked["problem"] is None and _blockers(asked) == []  # no DUPLICATE_HEADER failure
    assert asked["understanding"]["document"]["table"]["renamed_headers"] == 1
    assert sorted(q["column"] for q in asked["understanding"]["questions"]) == ["Ore", "Ore (2)"]

    answered = understand(
        api_client,
        env,
        LABOR,
        "turni.xlsx",
        content,
        {"column_fields": {"Ore": "planned_hours", "Ore (2)": "actual_hours"}},
    )

    assert _level(answered) == "READY"
    assert _tried(api_client, env, content, answered)["can_import"] is True


# --- a grid of people x days ---------------------------------------------------------------------


def test_a_grid_with_the_period_in_its_title_needs_only_to_know_which_hours_they_are(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_grid_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["GRID_HOURS"]
    document = asked["understanding"]["document"]
    assert document["day_grid"] is True and document["period_start"] == "2026-10-26"
    assert document["skipped"]["totals"] == 1 and document["totals"] == "MATCH"

    answered = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"grid_hours": "planned_hours"}
    )

    assert _level(answered) == "READY"
    tried = _tried(api_client, env, content, answered)
    assert tried["can_import"] is True and tried["rows_invalid"] == 0
    assert tried["summary"]["date_from"] == "2026-10-26"
    # the week is 26/10-01/11; the weekend cells are empty, and an empty cell is not a shift
    assert tried["summary"]["date_to"] == "2026-10-30"
    _import(api_client, env, content, answered)
    days = {e.work_date for e in _entries(db_session, env)}
    assert min(days) == date(2026, 10, 26) and max(days) <= date(2026, 11, 1)


def test_a_grid_whose_days_are_names_and_whose_week_is_not_written_asks_for_the_week(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.staff_grid_xlsx(period_in_title=False)

    asked = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"grid_hours": "planned_hours"}
    )

    assert _level(asked) == "ASK" and _kinds(asked) == ["PERIOD"]  # a date is never invented

    answered = understand(
        api_client,
        env,
        LABOR,
        "turni.xlsx",
        content,
        {"grid_hours": "planned_hours", "period_start": "2026-10-26"},
    )

    assert _level(answered) == "READY"
    assert _tried(api_client, env, content, answered)["summary"]["date_from"] == "2026-10-26"


def test_the_week_of_a_grid_is_never_remembered_for_the_next_file(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_grid_xlsx(period_in_title=False)
    answers = {"grid_hours": "planned_hours", "period_start": "2026-10-26"}
    body = understand(api_client, env, LABOR, "turni.xlsx", content, answers)
    _import(api_client, env, content, body)

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    assert "period_start" not in repr(profile.format_options)
    assert profile.format_options["layout"]["grid"] == {"hours_field": "planned_hours"}

    next_week = understand(api_client, env, LABOR, "settimana-dopo.xlsx", content)

    assert next_week["profile"]["status"] == "RECOGNIZED"
    assert _kinds(next_week) == ["PERIOD"]  # the way of reading is kept, the week is asked again


def test_a_weekly_summary_with_no_days_is_refused_with_the_reason_and_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_weekly_summary_xlsx()
    before = writes(db_session, env)

    body = understand(api_client, env, LABOR, "riepilogo.xlsx", content)

    assert _level(body) == "BLOCKED" and _blockers(body) == ["PERIOD_SUMMARY_ONLY"]
    # hours are NEVER spread over the days of the week: there is nothing to import
    tried = _tried(api_client, env, content, body, "riepilogo.xlsx")
    assert tried["can_import"] is False
    done = import_mapped(api_client, env, LABOR, "riepilogo.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is False
    assert writes(db_session, env) == before
    assert _entries(db_session, env) == []


# --- structure: header, two levels, totals, two tables -------------------------------------------


def test_a_two_level_header_is_one_header_and_imports(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.staff_two_level_header_xlsx()

    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(body) == "READY"
    table = body["understanding"]["document"]["table"]
    assert table["header_rows"] == [1, 2] and table["first_row"] == 3
    assert {c["header"] for c in body["columns"]} >= {"Personale - Reparto", "Costi - Previsto"}
    assert _tried(api_client, env, content, body)["can_import"] is True


def test_a_total_row_that_adds_up_is_left_out_and_one_that_does_not_is_a_warning(
    api_client: TestClient, env: SourcesEnv
) -> None:
    good = understand(api_client, env, LABOR, "t.xlsx", corpus.staff_title_summary_xlsx()[0])[
        "understanding"
    ]["document"]
    bad_content = corpus.staff_totals_wrong_xlsx()
    bad = understand(api_client, env, LABOR, "t.xlsx", bad_content)

    assert good["totals"] == "MATCH" and good["skipped"]["totals"] == 1
    document = bad["understanding"]["document"]
    assert document["totals"] == "MISMATCH" and document["skipped"]["totals"] == 1
    # the wrong total is reported, and is never imported as a shift
    assert _tried(api_client, env, bad_content, bad)["rows_total"] == document["table"]["data_rows"]


def test_two_tables_of_the_kind_being_imported_are_asked_about_and_the_answer_is_kept(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.staff_two_tables_xlsx()

    asked = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["TABLE"]
    choices = asked["understanding"]["questions"][0]["choices"]
    assert len(choices) == 2 and all(c["count"] == 5 for c in choices)

    answered = understand(
        api_client, env, LABOR, "turni.xlsx", content, {"table_key": choices[1]["value"]}
    )

    assert _kinds(answered) == [] and _level(answered) == "READY"
    assert _tried(api_client, env, content, answered)["rows_total"] == 5


def test_a_sheet_with_a_staff_table_and_a_bookings_table_gives_each_import_its_own(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.two_tables_xlsx()

    staff = understand(api_client, env, LABOR, "t.xlsx", content)
    bookings = understand(api_client, env, "BOOKINGS", "t.xlsx", content)

    assert "TABLE" not in _kinds(staff) and "TABLE" not in _kinds(bookings)
    assert {c["header"] for c in staff["columns"]} == {"Data", "Reparto", "Ore previste"}
    assert "Codice prenotazione" in {c["header"] for c in bookings["columns"]}


# --- adversarial files ---------------------------------------------------------------------------


def test_cells_that_give_orders_are_data_and_change_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.hostile_xlsx()

    body = understand(api_client, env, LABOR, "turni.xlsx", content)

    assert _level(body) == "READY"
    assert by_header(body)["Note"]["field"] is None  # the instructions are in an ignored column
    proposal = body["proposal"]
    assert proposal["labels"] == {} and proposal["constants"] == {}
    assert {c["field"] for c in proposal["columns"]} == {
        "work_date",
        "role",
        "planned_hours",
        None,
    }
    assert not any(word in repr(body["understanding"]) for word in ("admin mode", "evil.example"))
    _import(api_client, env, content, body)
    assert {e.labor_category for e in _entries(db_session, env)} == {
        LaborCategory.FRONT_OFFICE,
        LaborCategory.KITCHEN,
        LaborCategory.FOOD_BEVERAGE,
        LaborCategory.HOUSEKEEPING,
    }


def test_an_empty_workbook_says_there_is_no_table_and_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    before = writes(db_session, env)

    body = understand(api_client, env, LABOR, "vuoto.xlsx", corpus.empty_xlsx())

    assert _level(body) == "BLOCKED" and _blockers(body) == ["NO_TABLE"]
    assert writes(db_session, env) == before


def test_a_file_that_is_not_a_spreadsheet_is_refused_with_a_reason(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(api_client, env, LABOR, "turni.xlsx", b"this is not a workbook at all")

    assert body["problem"] is not None and body["understanding"] is None


def test_understanding_a_file_writes_nothing_at_all(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    before = writes(db_session, env)

    for content in (
        corpus.staff_title_summary_xlsx()[0],
        corpus.staff_grid_xlsx(),
        corpus.staff_two_tables_xlsx(),
    ):
        understand(api_client, env, LABOR, "t.xlsx", content)

    assert writes(db_session, env) == before


# --- which kind of data it is --------------------------------------------------------------------


def test_a_staff_file_chosen_as_bookings_is_asked_about_and_the_answer_is_not_asked_twice(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content, _ = corpus.staff_simple_xlsx()

    body = understand(api_client, env, "BOOKINGS", "turni.xlsx", content)

    assert "DOMAIN" in _kinds(body)
    question = next(q for q in body["understanding"]["questions"] if q["kind"] == "DOMAIN")
    assert question["candidate"] == LABOR
    assert body["understanding"]["detection"]["domain"] == LABOR

    confirmed = understand(api_client, env, "BOOKINGS", "turni.xlsx", content, confirmed=True)

    assert "DOMAIN" not in _kinds(confirmed)


def test_a_file_that_looks_like_nothing_known_is_not_asked_what_it_is_and_is_not_imported(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [
        ["Colore", "Forma", "Peso"],
        *[["rosso", "tondo", 3 + i] for i in range(6)],
    ]

    body = understand(api_client, env, LABOR, "altro.csv", corpus.csv_of(rows))

    assert body["understanding"]["detection"]["level"] == "LOW"
    # the card the person chose is a weak prior: nothing contradicts it, so there is no question
    # ("what is this?" would change nothing) - but nothing proves it either, so it is not imported
    assert "DOMAIN" not in _kinds(body)
    assert body["understanding"]["level"] == "MANUAL"
    assert [b["code"] for b in body["understanding"]["blockers"]] == ["MISSING_REQUIRED"]


def test_a_staff_file_chosen_as_staff_is_never_asked_what_kind_of_file_it_is(
    api_client: TestClient, env: SourcesEnv
) -> None:
    for content in (
        corpus.staff_title_summary_xlsx()[0],
        corpus.staff_no_department_xlsx(),
        corpus.staff_bare_hours_xlsx(),
    ):
        body = understand(api_client, env, LABOR, "t.xlsx", content)
        assert "DOMAIN" not in _kinds(body)


# --- how the file writes its dates -------------------------------------------------------------


def test_dates_that_can_be_read_two_ways_are_asked_about_never_guessed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [["Data", "Reparto", "Ore previste"]]
    rows += [[f"0{i + 1}/10/2026", "Reception", 8] for i in range(6)]  # 3 October or 10 March?
    content = corpus.csv_of(rows)

    asked = understand(api_client, env, LABOR, "turni.csv", content)

    assert _level(asked) == "ASK" and _kinds(asked) == ["DATE_ORDER"]
    assert {c["value"] for c in asked["understanding"]["questions"][0]["choices"]} == {"DMY", "MDY"}

    answered = understand(api_client, env, LABOR, "turni.csv", content, {"date_order": "DMY"})

    assert _level(answered) == "READY"
    tried = _tried(api_client, env, content, answered, "turni.csv")
    assert tried["can_import"] is True and tried["summary"]["date_from"] == "2026-10-01"


def test_dates_that_the_numbers_themselves_prove_are_not_asked_about(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [["Data", "Reparto", "Ore previste"]]
    rows += [[f"{20 + i}/10/2026", "Reception", 8] for i in range(6)]  # there is no month 20

    body = understand(api_client, env, LABOR, "turni.csv", corpus.csv_of(rows))

    assert "DATE_ORDER" not in _kinds(body) and _level(body) == "READY"


def test_a_column_that_writes_its_dates_two_ways_is_refused_with_the_reason(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [["Data", "Reparto", "Ore previste"]]
    rows += [["25/10/2026", "Reception", 8], ["10/25/2026", "Cucina", 8]]
    rows += [[f"0{i}/10/2026", "Sala e bar", 8] for i in range(1, 5)]

    body = understand(api_client, env, LABOR, "turni.csv", corpus.csv_of(rows))

    assert _level(body) == "BLOCKED" and _blockers(body) == ["MIXED_FORMATS"]


def test_any_day_of_the_week_names_the_week_of_a_grid(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.staff_grid_xlsx(period_in_title=False)

    # Wednesday 28 October 2026, not the Monday: the week is the one that contains it
    answered = understand(
        api_client,
        env,
        LABOR,
        "turni.xlsx",
        content,
        {"grid_hours": "planned_hours", "period_start": "2026-10-28"},
    )

    assert _level(answered) == "READY"
    tried = _tried(api_client, env, content, answered)
    assert tried["summary"]["date_from"] == "2026-10-26"  # the Monday of that week


def test_two_tables_with_the_same_columns_are_told_apart_by_the_line_above_them(
    api_client: TestClient, env: SourcesEnv
) -> None:
    asked = understand(api_client, env, LABOR, "turni.xlsx", corpus.staff_two_tables_xlsx())

    choices = asked["understanding"]["questions"][0]["choices"]
    assert [c["title"] for c in choices] == ["Turni mattina", "Turni sera"]
    assert [c["first_row"] for c in choices] == [3, 11]


def test_what_was_recognised_shows_a_value_seen_in_the_file_but_never_a_person(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(api_client, env, LABOR, "t.xlsx", corpus.staff_title_summary_xlsx()[0])

    examples = {r["field"]: r["example"] for r in body["understanding"]["recognized"]}
    assert examples["role"] == "Reception" and examples["planned_hours"] == "8"
    assert examples["work_date"] == "2026-10-26"
    assert not any(name in repr(body) for name, *_ in corpus.PEOPLE)

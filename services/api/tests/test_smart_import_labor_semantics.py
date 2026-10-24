"""Smart Import V2: what a staff file's department column really means to NINFA.

The audit of the canonical staff model found two different things, and this file pins both:

* `labor_category` is the department / operational area (Reception, Housekeeping, Kitchen, ...).
  It is the ONLY label the Decision Engine reads, and "Altro" is never actionable.
* `role_raw` / `role_normalized` are the free text the file used for the shift ("Reception",
  "Cuoco", "Turno A"), kept as written and used for ONE thing: working the department out. Nothing
  downstream reads them. They are not a professional role, and a person's name never goes in them.

So a hotel's "Reparto" column is imported as that free label and NINFA derives the department;
what it cannot derive stays "Altro" and is COUNTED, so the person hears about it before importing.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.labor.models import LaborEntry
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import (
    BOOKINGS_IT_DECISION,
    bookings_it_file,
    csv_bytes,
    decision,
    import_mapped,
    validation,
)
from tests.support import BookingFactory

APP = Path(__file__).resolve().parents[1] / "app"

TEAM_MAPPING = decision(
    {"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"}, date_order="DMY"
)


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _staff_file(teams: list[str]) -> bytes:
    rows = [["Giorno", "Ore turno", "Reparto"]]
    for index, team in enumerate(teams):
        rows.append([f"{index % 28 + 1:02d}/11/2026", "8", team])
    return csv_bytes(rows, delimiter=";", bom=True)


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- the label and the department ---------------------------------------------------------------


def test_a_department_or_a_job_in_the_file_is_a_label_and_the_department_is_worked_out_from_it(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = _staff_file(["Reception", "Cuoco", "Turno A"])

    body = validation(api_client, env, "LABOR", content, TEAM_MAPPING)

    assert body["status"] == "READY" and body["can_import"] is True
    assert body["sample_fields"] == ["work_date", "labor_category", "planned_hours"]
    # "Reception" (a department) and "Cuoco" (a job) both land in a department; "Turno A" says
    # nothing, so it is not guessed.
    assert [row[1] for row in body["sample_rows"]] == ["FRONT_OFFICE", "KITCHEN", "OTHER"]
    assert body["rows_unclassified"] == 1


def test_the_label_is_kept_as_the_file_wrote_it_and_says_how_the_department_was_found(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = _staff_file(["Reception", "Cuoco", "Turno A"])

    assert _ok(import_mapped(api_client, env, "LABOR", "turni.csv", content, TEAM_MAPPING))[
        "succeeded"
    ]

    entries = db_session.scalars(
        select(LaborEntry).where(LaborEntry.workspace_id == env.workspace.id)
    ).all()
    found = {
        e.role_raw: (e.role_normalized, e.labor_category, e.classification_method) for e in entries
    }
    rule = LaborClassificationMethod.DETERMINISTIC_RULE
    assert found == {
        "Reception": ("reception", LaborCategory.FRONT_OFFICE, rule),
        "Cuoco": ("cuoco", LaborCategory.KITCHEN, rule),
        # Not guessed: it stays "Altro", flagged as unclassified, with no confidence at all.
        "Turno A": ("turno a", LaborCategory.OTHER, LaborClassificationMethod.UNCLASSIFIED),
    }
    confidence = {e.role_raw: e.classification_confidence for e in entries}
    assert confidence["Turno A"] == 0 and confidence["Cuoco"] > 0


def test_unrecognised_departments_are_counted_over_the_whole_file_not_only_the_samples(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = _staff_file(["Reception"] * 6 + ["Turno A"] * 4)

    body = validation(api_client, env, "LABOR", content, TEAM_MAPPING)

    assert (body["rows_total"], body["rows_valid"]) == (10, 10)
    assert len(body["sample_rows"]) == 5  # the samples are all recognised...
    assert {row[1] for row in body["sample_rows"]} == {"FRONT_OFFICE"}
    assert body["rows_unclassified"] == 4  # ...and the four that are not still get counted


def test_a_department_that_was_stated_is_never_counted_as_unrecognised(
    api_client: TestClient, env: SourcesEnv
) -> None:
    fixed = decision(
        {"Giorno": "work_date", "Ore turno": "planned_hours"},
        constants={"labor_category": "KITCHEN"},
        date_order="DMY",
    )
    stated = decision(
        {"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "labor_category"},
        date_order="DMY",
    )

    for mapping, content in (
        (fixed, _staff_file(["x", "y"])),
        (stated, _staff_file(["KITCHEN", "HOUSEKEEPING"])),
    ):
        body = validation(api_client, env, "LABOR", content, mapping)
        assert body["status"] == "READY", body
        assert body["rows_unclassified"] == 0


def test_bookings_have_no_departments_so_they_never_report_unrecognised_rows(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = validation(api_client, env, "BOOKINGS", bookings_it_file(), BOOKINGS_IT_DECISION)

    assert body["status"] == "READY"
    assert body["rows_unclassified"] == 0


# --- who reads what -----------------------------------------------------------------------------


def test_the_decision_engine_reads_the_department_and_never_the_free_label() -> None:
    engine = sorted((APP / "modules" / "intelligence" / "labor").glob("*.py"))
    readers = [
        *engine,
        APP / "modules" / "data_overview" / "labor.py",
        *sorted((APP / "modules" / "decisions").glob("*.py")),
    ]
    assert len(engine) >= 5  # the scan would pass for nothing if the folder moved

    for source in readers:
        text = source.read_text(encoding="utf-8")
        assert "role_raw" not in text, source.name
        assert "role_normalized" not in text, source.name

    repository = (APP / "modules" / "intelligence" / "labor" / "repository.py").read_text(
        encoding="utf-8"
    )
    assert "LaborEntry.labor_category" in repository

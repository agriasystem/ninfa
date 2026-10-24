"""Smart Import V2: from the first file to the next one that is recognised.

    first file  ->  matched by the person  ->  imported  ->  the matching is remembered
    next file (another name, another week)  ->  recognised by its COLUMNS  ->  imported

What is pinned here: a source and a saved configuration exist only after an import SUCCEEDED (Fonti
dati V1's rule holds for the new way in); a failed import never saves a configuration and never
spoils a good one; the second file of the same layout is recognised whatever it is called; a
configuration made for another version of NINFA's rules, or for columns the file no longer has, is
never applied silently; forgetting a configuration keeps every imported row; and one hotel can
neither see nor use another hotel's configuration.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking, BookingMappingProfile
from app.modules.ingestion.models import DataSourceDomain, ImportFile, ImportJob, ImportJobStatus
from app.modules.labor.models import LaborEntry, LaborMappingProfile
from app.modules.labor.roles import LaborCategory
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import (
    SourcesEnv,
    booking_bytes,
    card,
    jobs_of,
    raw,
    sources_env,
    sources_of,
)
from tests.smart_import_support import (
    BOOKINGS_IT_DECISION,
    LABOR_IT_DECISION,
    b64,
    bookings_it_file,
    by_header,
    csv_bytes,
    decision,
    forget_url,
    import_mapped,
    inspection,
    labor_it_file,
    post_json,
    profiles_of,
    validation,
    writes,
)
from tests.support import BookingFactory


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _first_staff_import(client: TestClient, env: SourcesEnv, **kwargs: Any) -> dict[str, Any]:
    return _ok(
        import_mapped(
            client, env, "LABOR", "turni-43.csv", labor_it_file(), LABOR_IT_DECISION, **kwargs
        )
    )


def _staff_source(db_session: Session, env: SourcesEnv) -> Any:
    (source,) = [s for s in sources_of(db_session, env, DataSourceDomain.LABOR) if s.is_active]
    return source


# --- the first import ---------------------------------------------------------------------------


def test_the_first_matched_import_creates_the_source_and_remembers_the_matching(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    body = _first_staff_import(api_client, env)

    assert body["succeeded"] is True and body["problem"] is None
    assert (body["rows_total"], body["rows_invalid"], body["created"]) == (3, 0, 3)
    assert body["configuration_saved"] is True
    source = _staff_source(db_session, env)
    assert source.domain == DataSourceDomain.LABOR and source.is_active
    assert card(api_client, env, "STAFF")["state"] == "CONFIGURED_FILE"
    assert card(api_client, env, "STAFF")["last_update_at"] is not None
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    assert profile.data_source_id == source.id
    assert profile.column_mapping == {
        "work_date": {"column": "Giorno"},
        "planned_hours": {"column": "Ore turno"},
        "role": {"column": "Reparto"},
    }


def test_the_rows_are_imported_in_ninfas_own_form_with_the_team_read_into_a_category(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)

    entries = db_session.scalars(
        select(LaborEntry).where(LaborEntry.workspace_id == env.workspace.id)
    ).all()

    assert sorted((e.work_date.isoformat(), e.labor_category) for e in entries) == [
        ("2026-10-26", LaborCategory.FRONT_OFFICE),  # "Reception"
        ("2026-10-27", LaborCategory.HOUSEKEEPING),
        ("2026-10-28", LaborCategory.KITCHEN),  # "Cucina"
    ]
    assert {e.planned_minutes for e in entries} == {480}
    # Neither the person's name nor the hourly rate ever reached NINFA.
    assert not any(
        "Persona" in str(value) for e in entries for value in vars(e).values() if value is not None
    )


def test_the_saved_configuration_holds_only_the_matching_never_the_values_of_the_file(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    stored = repr((profile.column_mapping, profile.role_mapping, profile.format_options))

    assert "Persona" not in stored and "14,50" not in stored and "Reception" not in stored
    assert "Nome dipendente" not in stored  # an ignored column is not even remembered by name
    assert profile.format_options["schema_version"] == 1
    assert profile.format_options["date_formats"] == {"work_date": "%d/%m/%Y"}


def test_a_fixed_value_is_remembered_with_the_matching(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = labor_it_file(header=["Giorno", "Nome dipendente", "Ore turno", "Costo orario"])
    mapping = decision(
        {
            "Giorno": "work_date",
            "Nome dipendente": None,
            "Ore turno": "planned_hours",
            "Costo orario": None,
        },
        constants={"labor_category": "FRONT_OFFICE"},
        date_order="DMY",
    )

    body = _ok(import_mapped(api_client, env, "LABOR", "turni.csv", content, mapping))

    assert body["succeeded"] is True and body["configuration_saved"] is True
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    assert profile.column_mapping["labor_category"] == {"constant": "FRONT_OFFICE"}
    categories = db_session.scalars(select(LaborEntry.labor_category)).all()
    assert set(categories) == {LaborCategory.FRONT_OFFICE}


def test_asking_not_to_remember_the_matching_remembers_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    body = _first_staff_import(api_client, env, save=False)

    assert body["succeeded"] is True and body["configuration_saved"] is False
    assert profiles_of(db_session, env, LaborMappingProfile) == []
    assert card(api_client, env, "STAFF")["state"] == "CONFIGURED_FILE"  # the import still counts
    again = inspection(api_client, env, "LABOR", "turni-44.csv", labor_it_file())
    assert again["profile"]["status"] == "NONE"


def test_a_bookings_export_is_imported_and_its_channels_become_the_derived_cards(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    body = _ok(
        import_mapped(
            api_client, env, "BOOKINGS", "p.csv", bookings_it_file(), BOOKINGS_IT_DECISION
        )
    )

    assert body["succeeded"] is True and body["created"] == 2
    bookings = db_session.scalars(
        select(Booking).where(Booking.workspace_id == env.workspace.id)
    ).all()
    assert sorted((b.source_record_id, b.check_in.isoformat()) for b in bookings) == [
        ("IT-0001", "2026-11-12"),
        ("IT-0002", "2026-11-20"),
    ]
    assert {str(b.room_revenue) for b in bookings} == {"150.00"}
    assert card(api_client, env, "PMS")["state"] == "CONFIGURED_FILE"
    assert card(api_client, env, "OTA")["state"] == "DERIVED"  # received through the bookings


def test_an_excel_bookings_export_with_real_dates_is_imported(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = xlsx_bytes(
        {
            "Prenotazioni": [
                [
                    "Codice",
                    "Creata il",
                    "Arrivo",
                    "Partenza",
                    "Stato",
                    "Camere",
                    "Totale camera",
                    "Provenienza",
                ],
                [
                    "X-1",
                    datetime(2026, 10, 1, 9, 30),
                    datetime(2026, 11, 12),
                    datetime(2026, 11, 14),
                    "Confermata",
                    1,
                    150.5,
                    "Expedia",
                ],
                [
                    "X-2",
                    datetime(2026, 10, 2, 10, 0),
                    datetime(2026, 11, 20),
                    datetime(2026, 11, 22),
                    "Annullata",
                    1,
                    99,
                    "Diretto",
                ],
            ]
        }
    )
    mapping = decision(
        {
            "Codice": "source_record_id",
            "Creata il": "booked_at",
            "Arrivo": "check_in",
            "Partenza": "check_out",
            "Stato": "status",
            "Camere": "rooms",
            "Totale camera": "room_revenue",
            "Provenienza": "channel",
        },
        sheet_name="Prenotazioni",
    )

    body = _ok(import_mapped(api_client, env, "BOOKINGS", "export.xlsx", content, mapping))

    assert body["succeeded"] is True and body["created"] == 2
    revenues = {
        b.source_record_id: str(b.room_revenue) for b in db_session.scalars(select(Booking))
    }
    assert revenues == {"X-1": "150.50", "X-2": "99.00"}
    (profile,) = profiles_of(db_session, env, BookingMappingProfile)
    assert (
        profile.format_options["sheet_name"] == "Prenotazioni"
    )  # an Excel layout is its sheet too


def test_an_excel_staff_file_with_real_dates_and_numbers_is_imported(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = xlsx_bytes(
        {
            "Turni": [
                ["Data", "Dipendente", "Ore previste", "Reparto"],
                [datetime(2026, 10, 26), "Persona 1", 8, "Reception"],
                [datetime(2026, 10, 27), "Persona 2", 7.5, "Cucina"],
            ]
        }
    )
    mapping = decision(
        {
            "Data": "work_date",
            "Dipendente": None,
            "Ore previste": "planned_hours",
            "Reparto": "role",
        },
        sheet_name="Turni",
    )

    seen = inspection(api_client, env, "LABOR", "turni.xlsx", content)
    body = _ok(import_mapped(api_client, env, "LABOR", "turni.xlsx", content, mapping))

    assert by_header(seen)["Dipendente"]["not_used_reason"] == "PERSON"
    assert body["succeeded"] is True and body["created"] == 2  # no date format was asked for
    entries = db_session.scalars(select(LaborEntry).order_by(LaborEntry.work_date)).all()
    assert [(e.work_date.isoformat(), e.planned_minutes) for e in entries] == [
        ("2026-10-26", 480),
        ("2026-10-27", 450),
    ]


def test_an_excel_formula_is_never_calculated_by_ninfa(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    """A workbook is read for the VALUES it carries: a formula nobody has calculated has no value,
    and NINFA never evaluates one (that would be running somebody else's expression)."""
    content = xlsx_bytes(
        {"Turni": [["Data", "Ore", "Reparto"], [datetime(2026, 10, 26), "=1+1", "Cucina"]]}
    )
    mapping = decision(
        {"Data": "work_date", "Ore": "planned_hours", "Reparto": "role"}, sheet_name="Turni"
    )

    tried = validation(api_client, env, "LABOR", content, mapping, name="turni.xlsx")

    assert tried["status"] == "READY" and tried["can_import"] is False
    assert tried["rows_invalid"] == 1
    assert writes(db_session, env) == (0, 0, 0, 0)


# --- nothing is kept unless the import succeeded ------------------------------------------------


def test_a_failed_first_import_leaves_no_source_and_no_saved_matching(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = labor_it_file(hours="otto")

    body = _ok(import_mapped(api_client, env, "LABOR", "turni.csv", content, LABOR_IT_DECISION))

    assert body["succeeded"] is False and body["problem"] == "INVALID_ROWS"
    assert body["configuration_saved"] is False
    assert [s for s in sources_of(db_session, env, DataSourceDomain.LABOR) if s.is_active] == []
    assert profiles_of(db_session, env, LaborMappingProfile) == []
    assert card(api_client, env, "STAFF")["state"] == "NOT_CONFIGURED"
    assert [j.status for j in jobs_of(db_session, env)] == [ImportJobStatus.FAILED]  # a record only


def test_a_matching_that_is_not_enough_is_refused_before_anything_is_created(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    body = _ok(
        import_mapped(
            api_client, env, "LABOR", "t.csv", labor_it_file(), decision({"Giorno": "work_date"})
        )
    )

    assert body["succeeded"] is False and body["problem"] == "MAPPING_INCOMPLETE"
    assert writes(db_session, env) == (0, 0, 0, 0)  # not even an inactive source was created
    assert card(api_client, env, "STAFF")["state"] == "NOT_CONFIGURED"


def test_dates_that_must_be_chosen_stop_the_import_instead_of_being_guessed(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = labor_it_file(days=("01/11/2026", "02/11/2026", "03/11/2026"))
    mapping = decision({"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"})

    body = _ok(import_mapped(api_client, env, "LABOR", "t.csv", content, mapping))

    assert body["succeeded"] is False and body["problem"] == "FORMAT_UNCLEAR"
    assert card(api_client, env, "STAFF")["state"] == "NOT_CONFIGURED"
    assert writes(db_session, env) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("name", "content", "problem"),
    [
        ("vuoto.csv", b"", "EMPTY_FILE"),
        ("turni.pdf", b"%PDF-1.4", "UNSUPPORTED_FILE"),
        ("binario.csv", b"Giorno;Ore\n26/10/2026;\x00\x01\n", "UNREADABLE_FILE"),
    ],
)
def test_a_file_that_cannot_be_read_is_refused_before_anything_is_created(
    api_client: TestClient,
    db_session: Session,
    env: SourcesEnv,
    name: str,
    content: bytes,
    problem: str,
) -> None:
    body = _ok(import_mapped(api_client, env, "LABOR", name, content, LABOR_IT_DECISION))

    assert body["succeeded"] is False and body["problem"] == problem
    assert writes(db_session, env) == (0, 0, 0, 0)


def test_a_labor_file_still_needs_the_day_it_is_dated_as_of(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    response = post_json(
        api_client,
        f"{env.base}/imports/mapped",
        {
            "domain": "LABOR",
            "filename": "t.csv",
            "file_base64": b64(labor_it_file()),
            "mapping": LABOR_IT_DECISION,
        },
    )

    assert (
        response.status_code == 400 and response.json()["error"]["code"] == "INVALID_SNAPSHOT_DATE"
    )
    assert writes(db_session, env) == (0, 0, 0, 0)


def test_a_failed_import_never_spoils_the_configuration_that_was_working(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    (before,) = profiles_of(db_session, env, LaborMappingProfile)
    saved = (dict(before.column_mapping), dict(before.format_options), before.header_signature)

    other = decision(
        {
            "Giorno": "work_date",
            "Nome dipendente": None,
            "Ore turno": "actual_hours",
            "Costo orario": None,
            "Reparto": "role",
        },
        date_order="DMY",
    )
    bad_file = labor_it_file(hours="molte", days=("29/10/2026",))
    body = _ok(import_mapped(api_client, env, "LABOR", "altro.csv", bad_file, other))

    assert body["succeeded"] is False and body["configuration_saved"] is False
    (after,) = profiles_of(db_session, env, LaborMappingProfile)
    assert (dict(after.column_mapping), dict(after.format_options), after.header_signature) == saved
    assert card(api_client, env, "STAFF")["state"] == "CONFIGURED_FILE"  # and the source stays on


def test_costs_have_no_columns_to_match(api_client: TestClient, env: SourcesEnv) -> None:
    response = post_json(
        api_client,
        f"{env.base}/imports/mapped",
        {
            "domain": "COSTS",
            "filename": "f.csv",
            "file_base64": b64(b"a;b\n1;2\n"),
            "mapping": None,
        },
    )

    assert response.status_code == 404 and response.json()["error"]["code"] == "UNSUPPORTED_DOMAIN"
    assert card(api_client, env, "ACCOUNTING")["state"] == "NOT_CONFIGURED"


# --- the next file is recognised ----------------------------------------------------------------


def test_the_next_weeks_file_is_recognised_by_its_columns_whatever_it_is_called(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    next_week = labor_it_file(days=("02/11/2026", "03/11/2026", "04/11/2026"))

    body = inspection(api_client, env, "LABOR", "turni-settimana-44.csv", next_week)

    assert body["profile"]["status"] == "RECOGNIZED" and body["profile"]["reason"] is None
    assert body["profile"]["last_used_at"] is not None
    mapping = body["profile"]["mapping"]
    assert {c["header"]: c["field"] for c in mapping["columns"]} == {
        "Giorno": "work_date",
        "Nome dipendente": None,
        "Ore turno": "planned_hours",
        "Costo orario": None,
        "Reparto": "role",
    }
    assert mapping["date_order"] == "DMY"


def test_the_recognised_layout_is_tried_and_imported_with_no_matching_sent_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    next_week = labor_it_file(days=("02/11/2026", "03/11/2026", "04/11/2026"))

    tried = validation(api_client, env, "LABOR", next_week, None, name="turni-settimana-44.csv")
    body = _ok(
        import_mapped(
            api_client,
            env,
            "LABOR",
            "turni-settimana-44.csv",
            next_week,
            None,
            snapshot="2026-10-30",
        )
    )

    assert tried["status"] == "READY" and tried["can_import"] is True and tried["rows_total"] == 3
    assert body["succeeded"] is True and body["created"] == 3
    assert body["configuration_saved"] is False  # nothing new to remember
    assert _staff_source(db_session, env).id == source.id  # the SAME source, not a second one
    assert len([s for s in sources_of(db_session, env, DataSourceDomain.LABOR)]) == 1
    assert len(jobs_of(db_session, env)) == 2
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 6


def test_the_same_file_twice_changes_nothing_the_second_time(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)

    again = _ok(import_mapped(api_client, env, "LABOR", "ancora.csv", labor_it_file(), None))

    assert again["succeeded"] is True and again["already_imported"] is True
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 3


def test_a_file_with_extra_columns_is_still_recognised_and_a_missing_one_is_not(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)

    with_extra = labor_it_file(
        header=["Giorno", "Nome dipendente", "Ore turno", "Costo orario", "Reparto", "Note"]
    )
    without_hours = csv_bytes([["Giorno", "Reparto"], ["26/10/2026", "Cucina"]], delimiter=";")

    extra = inspection(api_client, env, "LABOR", "a.csv", with_extra)["profile"]
    changed = inspection(api_client, env, "LABOR", "b.csv", without_hours)["profile"]

    assert extra["status"] == "RECOGNIZED"
    assert changed["status"] == "NEEDS_REVIEW" and changed["reason"] == "COLUMNS_CHANGED"
    assert changed["missing_columns"] == ["Ore turno"]
    # the saved matching is offered as the starting point, for the columns that are still there
    assert {c["header"]: c["field"] for c in changed["mapping"]["columns"]} == {
        "Giorno": "work_date",
        "Reparto": "role",
    }


def test_a_file_that_no_longer_has_the_saved_columns_is_not_imported_silently(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    without_hours = csv_bytes([["Giorno", "Reparto"], ["30/10/2026", "Cucina"]], delimiter=";")
    before = writes(db_session, env)

    tried = validation(api_client, env, "LABOR", without_hours, None)
    body = _ok(import_mapped(api_client, env, "LABOR", "b.csv", without_hours, None))

    assert tried["status"] == "BLOCKED" and tried["problem"] == "PROFILE_NOT_USABLE"
    assert body["succeeded"] is False and body["problem"] == "PROFILE_NOT_USABLE"
    assert writes(db_session, env) == before  # no second source, no job, nothing at all
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 3


def test_a_configuration_made_for_another_version_of_the_rules_is_never_applied_silently(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    profile.format_options = {**profile.format_options, "schema_version": 99}
    db_session.flush()
    next_week = labor_it_file(days=("02/11/2026", "03/11/2026", "04/11/2026"))

    body = inspection(api_client, env, "LABOR", "t44.csv", next_week)
    tried = validation(api_client, env, "LABOR", next_week, None)
    imported = _ok(import_mapped(api_client, env, "LABOR", "t44.csv", next_week, None))

    assert body["profile"]["status"] == "NEEDS_REVIEW"
    assert body["profile"]["reason"] == "VERSION_CHANGED"
    assert body["profile"]["mapping"] is not None  # still a starting point for the person
    assert tried["problem"] == "PROFILE_NOT_USABLE" and imported["problem"] == "PROFILE_NOT_USABLE"
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 3


def test_a_configuration_that_cannot_be_read_any_more_asks_for_a_new_matching(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    profile.column_mapping = {"campo_che_non_esiste_piu": {"column": "Giorno"}}
    db_session.flush()

    body = inspection(api_client, env, "LABOR", "t.csv", labor_it_file())

    assert body["profile"]["status"] == "NEEDS_REVIEW" and body["profile"]["reason"] == "INVALID"


def test_a_matching_made_again_replaces_the_saved_one_and_keeps_what_was_taught_about_values(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    profile.role_mapping = {"cucina": "KITCHEN", "sala colazioni": "FOOD_BEVERAGE"}
    db_session.flush()
    new_layout = csv_bytes(
        [["Data", "Ore effettive", "Reparto"], ["29/10/2026", "6", "Sala colazioni"]], delimiter=";"
    )
    mapping = decision(
        {"Data": "work_date", "Ore effettive": "actual_hours", "Reparto": "role"}, date_order="DMY"
    )

    body = _ok(
        import_mapped(
            api_client, env, "LABOR", "nuovo.csv", new_layout, mapping, snapshot="2026-10-30"
        )
    )

    assert body["succeeded"] is True and body["configuration_saved"] is True
    (after,) = profiles_of(db_session, env, LaborMappingProfile)
    assert after.column_mapping["actual_hours"] == {"column": "Ore effettive"}
    assert "planned_hours" not in after.column_mapping
    assert after.role_mapping == {"cucina": "KITCHEN", "sala colazioni": "FOOD_BEVERAGE"}
    last = db_session.scalars(
        select(LaborEntry).where(LaborEntry.work_date == datetime(2026, 10, 29).date())
    ).one()
    assert last.labor_category == LaborCategory.FOOD_BEVERAGE  # the taught label was used


def test_a_file_imported_the_first_way_is_still_recognised_by_the_new_way(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    """The canonical import (no matching) saves its own identity matching, without a version: that
    counts as version 1, so such a source is recognised, not asked again."""
    first = raw(api_client, env.imports_url("BOOKINGS", "prenotazioni.csv"), booking_bytes())
    assert first.json()["succeeded"] is True
    (profile,) = profiles_of(db_session, env, BookingMappingProfile)
    assert "schema_version" not in profile.format_options

    body = inspection(api_client, env, "BOOKINGS", "ottobre.csv", booking_bytes())

    assert body["profile"]["status"] == "RECOGNIZED"


# --- looking after the saved configuration ------------------------------------------------------


def test_the_saved_configuration_can_be_read_and_says_what_each_column_means(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)

    response = api_client.get(forget_url(env, source.id))
    body = _ok(response)

    assert body["domain"] == "LABOR" and body["schema_current"] is True
    assert {item["field"]: item["column"] for item in body["columns"]} == {
        "work_date": "Giorno",
        "planned_hours": "Ore turno",
        "role": "Reparto",
    }
    assert body["last_used_at"] is not None


def test_forgetting_the_configuration_keeps_the_source_and_every_imported_row(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)

    deleted = api_client.delete(forget_url(env, source.id))
    again = api_client.delete(forget_url(env, source.id))

    assert deleted.status_code == 204 and again.status_code == 204  # forgetting twice is harmless
    assert api_client.get(forget_url(env, source.id)).status_code == 404
    assert profiles_of(db_session, env, LaborMappingProfile) == []
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 3
    assert card(api_client, env, "STAFF")["state"] == "CONFIGURED_FILE"
    assert (
        inspection(api_client, env, "LABOR", "t.csv", labor_it_file())["profile"]["status"]
        == "NONE"
    )


def test_after_forgetting_the_next_import_asks_for_a_matching_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    api_client.delete(forget_url(env, source.id))

    body = _ok(
        import_mapped(api_client, env, "LABOR", "t.csv", labor_it_file(days=("30/10/2026",)), None)
    )

    assert body["succeeded"] is False and body["problem"] == "PROFILE_NOT_USABLE"


def test_a_removed_source_keeps_its_configuration_for_when_it_is_linked_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    assert api_client.delete(f"{env.base}/{source.id}").status_code == 204
    next_week = labor_it_file(days=("02/11/2026", "03/11/2026", "04/11/2026"))

    recognised = inspection(api_client, env, "LABOR", "t44.csv", next_week)["profile"]
    body = _ok(
        import_mapped(api_client, env, "LABOR", "t44.csv", next_week, None, snapshot="2026-10-30")
    )

    assert recognised["status"] == "RECOGNIZED"
    assert body["succeeded"] is True
    assert _staff_source(db_session, env).id == source.id  # reactivated, history attached
    assert api_client.get(forget_url(env, source.id)).status_code == 200


def test_the_configuration_of_a_removed_source_is_not_shown_in_manage(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    api_client.delete(f"{env.base}/{source.id}")

    assert api_client.get(forget_url(env, source.id)).status_code == 404


# --- one hotel never sees or uses another hotel's configuration ---------------------------------


def test_another_property_of_the_same_workspace_neither_sees_nor_uses_the_configuration(
    api_client: TestClient, db_session: Session, factory: BookingFactory, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    sister = factory.property(env.workspace)
    sister_env = SourcesEnv(env.workspace, sister, env.user)

    body = inspection(api_client, sister_env, "LABOR", "t.csv", labor_it_file())
    tried = validation(api_client, sister_env, "LABOR", labor_it_file(), None)
    imported = _ok(import_mapped(api_client, sister_env, "LABOR", "t.csv", labor_it_file(), None))
    reached = api_client.get(forget_url(sister_env, source.id))
    forgotten = api_client.delete(forget_url(sister_env, source.id))

    assert body["profile"]["status"] == "NONE" and body["already_imported"] is False
    assert tried["problem"] == "PROFILE_NOT_USABLE" and imported["problem"] == "PROFILE_NOT_USABLE"
    assert reached.status_code == 404 and reached.json()["error"]["code"] == "DATA_SOURCE_NOT_FOUND"
    assert forgotten.status_code == 404  # the same answer as for a source that does not exist
    assert len(profiles_of(db_session, env, LaborMappingProfile)) == 1  # nothing was forgotten


def test_a_member_of_another_workspace_cannot_read_or_forget_my_configuration(
    api_client: TestClient,
    db_session: Session,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    env: SourcesEnv,
) -> None:
    from app.modules.tenancy.models import MembershipRole

    _first_staff_import(api_client, env)
    source = _staff_source(db_session, env)
    outsider_workspace = factory.workspace()
    outsider_property = factory.property(outsider_workspace)
    outsider = factory.user()
    factory.membership(outsider_workspace, outsider, MembershipRole.MEMBER)
    authenticated_as(outsider.id)
    # They name MY property: it is the same 404 as a property that does not exist.
    mine = f"/api/v1/properties/{env.property.id}/data-sources/{source.id}/import-configuration"
    theirs = (
        f"/api/v1/properties/{outsider_property.id}/data-sources/{source.id}/import-configuration"
    )

    assert api_client.get(mine).json()["error"]["code"] == "PROPERTY_NOT_FOUND"
    assert api_client.delete(mine).status_code == 404
    # They name THEIR property with MY source id: the source is simply not theirs.
    assert api_client.get(theirs).json()["error"]["code"] == "DATA_SOURCE_NOT_FOUND"
    assert len(profiles_of(db_session, env, LaborMappingProfile)) == 1


def test_the_other_kind_of_data_of_the_same_property_has_its_own_configuration(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    _ok(
        import_mapped(
            api_client, env, "BOOKINGS", "p.csv", bookings_it_file(), BOOKINGS_IT_DECISION
        )
    )

    staff = inspection(api_client, env, "LABOR", "t.csv", labor_it_file())["profile"]
    bookings = inspection(api_client, env, "BOOKINGS", "p.csv", bookings_it_file())["profile"]
    cross = inspection(api_client, env, "BOOKINGS", "t.csv", labor_it_file())["profile"]

    assert staff["status"] == "RECOGNIZED" and bookings["status"] == "RECOGNIZED"
    assert cross["status"] == "NEEDS_REVIEW"  # staff columns are not the bookings' columns
    assert len(profiles_of(db_session, env, LaborMappingProfile)) == 1
    assert len(profiles_of(db_session, env, BookingMappingProfile)) == 1


# --- what a file can carry ----------------------------------------------------------------------


def test_a_file_name_is_only_a_label_and_never_a_path(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    body = _ok(
        import_mapped(
            api_client,
            env,
            "LABOR",
            "../../etc/passwd\\turni.csv",
            labor_it_file(),
            LABOR_IT_DECISION,
        )
    )

    assert body["succeeded"] is True
    names = db_session.scalars(select(ImportFile.original_filename)).all()
    assert names == ["turni.csv"]


def test_a_cell_that_looks_like_a_formula_is_only_text(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = csv_bytes(
        [
            ["Giorno", "Ore turno", "Reparto"],
            ["26/10/2026", "8", '=HYPERLINK("http://example.invalid")'],
            ["27/10/2026", "8", "+CMD|' /C calc'!A0"],
        ],
        delimiter=";",
    )
    mapping = decision(
        {"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"}, date_order="DMY"
    )

    seen = inspection(api_client, env, "LABOR", "t.csv", content)
    body = _ok(import_mapped(api_client, env, "LABOR", "t.csv", content, mapping))

    assert by_header(seen)["Reparto"]["examples"][0] == '=HYPERLINK("http://example.invalid")'
    assert body["succeeded"] is True  # stored as a role label, classified OTHER, never evaluated
    categories = db_session.scalars(select(LaborEntry.labor_category)).all()
    assert set(categories) == {LaborCategory.OTHER}


def test_two_matched_imports_of_one_kind_cannot_leave_two_configurations(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _first_staff_import(api_client, env)
    second = decision(
        {
            "Giorno": "work_date",
            "Nome dipendente": None,
            "Ore turno": "actual_hours",
            "Costo orario": None,
            "Reparto": "role",
        },
        date_order="DMY",
    )

    body = _ok(
        import_mapped(
            api_client,
            env,
            "LABOR",
            "altro.csv",
            labor_it_file(days=("30/10/2026",)),
            second,
            snapshot="2026-10-31",
        )
    )

    assert body["succeeded"] is True
    assert len(profiles_of(db_session, env, LaborMappingProfile)) == 1  # one per source, replaced
    assert db_session.scalar(select(func.count()).select_from(ImportJob)) == 2

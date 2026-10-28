"""Source Learning: how a family is READ belongs to the family, end to end.

One source (property + kind of data) can bring back an xlsx whose table sits under a title on one
sheet, another xlsx on another sheet, a csv, a day grid, a document whose department is in its
title. How each is read - which sheet, which hours a grid holds, where the department comes from -
is what a person decided about THAT structure. It is remembered with the family and handed back
only once a file has been recognised as it: never inherited from whichever family was imported last.

Real files through the real API and the real database (rolled back). No model, no embedding, no
external service: `IMPORT_UNDERSTANDING_MODE` is off for the whole suite.
"""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import BookingMappingProfile
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.service import DataSourcesService
from app.modules.data_sources.source_learning import Learning, Memory, parse_learning
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from app.modules.labor.models import LaborMappingProfile
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import import_mapped, profiles_of, understand
from tests.source_learning_layout_support import (
    reservations_csv,
    reservations_export,
    reservations_pms,
    staff_csv,
    staff_grid,
    staff_title_department,
)
from tests.source_learning_support import xlsx_of
from tests.support import BookingFactory

BOOKINGS = "BOOKINGS"
LABOR = "LABOR"
PMS_SAYS = {"sheet_name": "Prenotazioni"}
EXPORT_SAYS = {"sheet_name": "Export"}
CSV_SAYS = {"date_order": "DMY"}
GRID_SAYS = {"grid_hours": "planned_hours"}
TITLE_SAYS = {"department_from": "TITLE"}
STAFF = {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"}
STAFF_SAYS = {"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}}
STAFF_CSV = {"Data": "day", "Ore 1": "planned", "Ore 2": "actual", "Area": "dept"}
STAFF_CSV_SAYS = {
    "column_fields": {"Ore 1": "planned_hours", "Ore 2": "actual_hours"},
    "date_order": "DMY",
}


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


# --- helpers ---


def _teach(
    api_client: TestClient,
    env: SourcesEnv,
    domain: str,
    name: str,
    content: bytes,
    answers: dict[str, Any],
    month: int = 10,
) -> None:
    """The first time a family arrives: the person answers, the import remembers."""
    body = understand(api_client, env, domain, name, content, answers)
    assert body["understanding"]["level"] == "READY", (
        name,
        body["understanding"]["level"],
        [q["id"] for q in body["understanding"]["questions"]],
        [b["code"] for b in body["understanding"]["blockers"]],
    )
    done = import_mapped(
        api_client, env, domain, name, content, body["proposal"], snapshot=f"2026-{month:02d}-28"
    )
    assert done.status_code == 200 and done.json()["succeeded"] is True, done.text
    assert done.json()["configuration_saved"] is True


def _nothing_asked(
    api_client: TestClient, env: SourcesEnv, domain: str, name: str, content: bytes
) -> dict[str, Any]:
    body = understand(api_client, env, domain, name, content)
    u = body["understanding"]
    assert u["level"] == "READY" and u["questions"] == [] and u["blockers"] == [], (
        name,
        u["level"],
        [q["id"] for q in u["questions"]],
        [b["code"] for b in u["blockers"]],
    )
    return body


def _look(
    db_session: Session,
    env: SourcesEnv,
    domain: DataSourceDomain,
    name: str,
    content: bytes,
    answers: dict[str, Any] | None = None,
) -> FileInspection:
    service = DataSourcesService(db_session, TenantContext(env.workspace.id))
    return service.understand_file(
        env.property.id,
        domain,
        filename=name,
        content=content,
        answers=UnderstandAnswers.model_validate(answers or {}),
    )


def _store(db_session: Session, env: SourcesEnv, model: Any = BookingMappingProfile) -> Learning:
    (profile,) = profiles_of(db_session, env, model)
    store = parse_learning(profile.format_options.get("learning"))
    assert store is not None
    return store


def _family(store: Learning, family_id: str | None) -> Memory:
    found = store.family(family_id)
    assert found is not None
    return found


def _read_as(inspection: FileInspection) -> dict[str, Any]:
    """How the document is read: the layout of the decision the server proposes."""
    assert inspection.proposal is not None and inspection.proposal.layout is not None
    return inspection.proposal.layout.model_dump(
        mode="json", exclude_none=True, exclude_defaults=True
    )


def _id(inspection: FileInspection) -> str | None:
    info = inspection.learning
    return None if info is None or info.memory is None else info.memory.id


def _teach_three_formats(api_client: TestClient, env: SourcesEnv) -> None:
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "export.xlsx", reservations_export(9), EXPORT_SAYS, 9)
    _teach(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(8), CSV_SAYS, 8)


# --- the defect: the layout of the last import decided how the others were read ---


def test_two_xlsx_families_on_different_sheets_are_each_read_through_their_own_sheet(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "export.xlsx", reservations_export(9), EXPORT_SAYS, 9)

    # A -> B -> A -> B: whoever came in between, each one is itself
    for _ in range(2):
        pms = _look(db_session, env, DataSourceDomain.BOOKINGS, "pms.xlsx", reservations_pms(11))
        export = _look(
            db_session, env, DataSourceDomain.BOOKINGS, "export.xlsx", reservations_export(11)
        )
        assert _read_as(pms) == {"sheets": ["Prenotazioni"]}
        assert _read_as(export) == {"sheets": ["Export"]}
        assert _id(pms) is not None and _id(pms) != _id(export)
        _nothing_asked(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(11))
        _nothing_asked(api_client, env, BOOKINGS, "export.xlsx", reservations_export(11))


def test_each_family_keeps_its_own_hints_in_the_store(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_three_formats(api_client, env)

    store = _store(db_session, env)

    assert len(store.families) == 3
    layouts = sorted(json.dumps(m.layout, sort_keys=True) for m in store.families)
    assert layouts == sorted(['{"sheets": ["Prenotazioni"]}', '{"sheets": ["Export"]}', "{}"])
    assert store.current == store.families[-1].id  # the profile holds the last import's layout...


def test_a_csv_is_readable_after_an_xlsx_family_with_a_chosen_sheet(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    # (a sheet chosen for the xlsx used to make every other file "have no table")
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)

    csv = understand(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(9), CSV_SAYS)

    assert csv["understanding"]["level"] == "READY"
    assert csv["understanding"]["blockers"] == []
    assert csv["understanding"]["document"]["file_type"] == "CSV"


def test_xlsx_then_csv_then_xlsx_then_csv_nothing_is_asked_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(9), CSV_SAYS, 9)

    for month in (11, 12):  # A -> C -> A -> C
        _nothing_asked(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(month))
        _nothing_asked(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(month))
    csv = _look(db_session, env, DataSourceDomain.BOOKINGS, "g.csv", reservations_csv(11))
    assert _read_as(csv) == {}  # a csv has no sheet: it is not read through the xlsx's


def test_a_csv_taught_first_is_still_readable_after_an_xlsx_with_a_chosen_sheet(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(9), CSV_SAYS, 9)
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)

    _nothing_asked(api_client, env, BOOKINGS, "gestionale.csv", reservations_csv(11))
    _nothing_asked(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(11))


def test_three_formats_in_any_order_each_read_by_its_own_structure(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach_three_formats(api_client, env)
    files = {
        "pms": ("pms.xlsx", reservations_pms),
        "export": ("export.xlsx", reservations_export),
        "csv": ("gestionale.csv", reservations_csv),
    }
    expected = {"pms": {"sheets": ["Prenotazioni"]}, "export": {"sheets": ["Export"]}, "csv": {}}

    # A -> B -> C -> A -> B, then the other way round
    for key in ("pms", "export", "csv", "pms", "export", "csv", "export", "pms"):
        name, build = files[key]
        _nothing_asked(api_client, env, BOOKINGS, name, build(11))
        inspection = _look(db_session, env, DataSourceDomain.BOOKINGS, name, build(12))
        assert _read_as(inspection) == expected[key], key
    ids = {
        key: _id(
            _look(db_session, env, DataSourceDomain.BOOKINGS, *files[key][:1], files[key][1](12))
        )
        for key in files
    }
    assert len(set(ids.values())) == 3 and None not in ids.values()


def test_a_table_lower_in_the_sheet_under_a_blank_column_is_read_as_taught(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "export.xlsx", reservations_export(9), EXPORT_SAYS, 9)

    body = _nothing_asked(api_client, env, BOOKINGS, "export.xlsx", reservations_export(11))

    document = body["understanding"]["document"]
    assert (
        document["table"]["data_rows"] == 7
    )  # the seven bookings, not the title or the blank column
    assert {r["field"] for r in body["understanding"]["recognized"]} >= {"check_in", "check_out"}


# --- special layouts ---


def _staff_normal(api_client: TestClient, env: SourcesEnv, month: int = 9) -> None:
    _teach(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=month), STAFF_SAYS, month)


def test_a_grid_comes_back_as_a_grid_after_an_ordinary_table(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _staff_normal(api_client, env)

    for month in (11, 12):  # SPECIAL -> NORMAL -> SPECIAL
        _nothing_asked(api_client, env, LABOR, "griglia.xlsx", staff_grid(month))
        _nothing_asked(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=month))
    grid = _look(db_session, env, DataSourceDomain.LABOR, "griglia.xlsx", staff_grid(12))
    ordinary = _look(
        db_session, env, DataSourceDomain.LABOR, "turni.xlsx", xlsx_of(STAFF, month=12)
    )
    assert _read_as(grid) == {"grid": {"hours_field": "planned_hours"}}
    assert _read_as(ordinary) == {}  # not read as a grid: the grid is another family's


def test_an_ordinary_table_taught_first_is_not_read_as_the_grid_that_came_after(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _staff_normal(api_client, env)
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)

    # NORMAL -> SPECIAL -> NORMAL: the layout saved last is the grid's, and the table is not a grid
    ordinary = _look(
        db_session, env, DataSourceDomain.LABOR, "turni.xlsx", xlsx_of(STAFF, month=12)
    )

    assert _read_as(ordinary) == {}
    assert ordinary.proposal is not None
    assert all(c.header != "Data" or c.field is None for c in ordinary.proposal.columns)
    _nothing_asked(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=12))
    _nothing_asked(api_client, env, LABOR, "griglia.xlsx", staff_grid(12))


def test_a_grid_whose_days_are_dates_is_the_same_family_week_after_week(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(
        api_client, env, LABOR, "griglia.xlsx", staff_grid(10, weekday_names=False), GRID_SAYS, 10
    )
    _staff_normal(api_client, env)

    for month in (11, 12):  # the headers are other dates every week
        _nothing_asked(
            api_client, env, LABOR, "griglia.xlsx", staff_grid(month, weekday_names=False)
        )


def test_a_department_confirmed_from_the_title_is_not_asked_again(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "titolo.xlsx", staff_title_department(10), TITLE_SAYS, 10)
    _staff_normal(api_client, env)

    for month in (11, 12):  # SPECIAL -> NORMAL -> SPECIAL
        _nothing_asked(api_client, env, LABOR, "titolo.xlsx", staff_title_department(month))
        _nothing_asked(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=month))
    ordinary = _look(
        db_session, env, DataSourceDomain.LABOR, "turni.xlsx", xlsx_of(STAFF, month=12)
    )
    assert (
        _read_as(ordinary) == {}
    )  # no synthetic department column added to a table that has its own


def test_a_special_layout_and_an_ordinary_csv_in_the_same_source(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _teach(api_client, env, LABOR, "turni.csv", staff_csv(STAFF_CSV, month=9), STAFF_CSV_SAYS, 9)

    for month in (11, 12):
        _nothing_asked(api_client, env, LABOR, "griglia.xlsx", staff_grid(month))
        _nothing_asked(api_client, env, LABOR, "turni.csv", staff_csv(STAFF_CSV, month=month))


# --- ambiguity: two families that need different layouts ---


def test_two_families_that_could_be_the_file_and_need_other_layouts_reuse_neither(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    # two exports one optional column apart, each read through a sheet of its own
    guests = reservations_pms(10, sheet_name="Prenotazioni", guests=True)
    plan = reservations_pms(9, sheet_name="Elenco", rate_plan=True)
    _teach(api_client, env, BOOKINGS, "pms-ospiti.xlsx", guests, PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "pms-tariffe.xlsx", plan, {"sheet_name": "Elenco"}, 9)
    store = _store(db_session, env)
    assert {json.dumps(m.layout) for m in store.families} == {
        '{"sheets": ["Prenotazioni"]}',
        '{"sheets": ["Elenco"]}',
    }
    _nothing_asked(api_client, env, BOOKINGS, "pms-ospiti.xlsx", reservations_pms(11, guests=True))
    _nothing_asked(
        api_client,
        env,
        BOOKINGS,
        "pms-tariffe.xlsx",
        reservations_pms(11, sheet_name="Elenco", rate_plan=True),
    )

    # the same export without either column, on a sheet neither family names: it could be either
    for sheet in ("Altro", "Foglio1"):
        inspection = _look(
            db_session,
            env,
            DataSourceDomain.BOOKINGS,
            "pms.xlsx",
            reservations_pms(11, sheet_name=sheet),
        )

        info = inspection.learning
        assert info is not None and info.ambiguous and info.family is None
        assert info.layout is None and info.memory is None  # neither family's sheet was applied
        assert _read_as(inspection) == {}  # and the file is read on its own terms, not blocked
        assert inspection.understanding is not None
        assert inspection.understanding.blockers == ()


# --- local ---


def test_a_layout_correction_in_one_family_changes_nothing_in_another(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _staff_normal(api_client, env)
    store = _store(db_session, env, LaborMappingProfile)
    normal = next(m for m in store.families if m.layout == {})
    grid = next(m for m in store.families if m.layout and "grid" in m.layout)
    before = normal.model_dump(exclude={"touched"})

    corrected = {"grid_hours": "actual_hours"}
    content = staff_grid(11)
    body = understand(api_client, env, LABOR, "griglia.xlsx", content, corrected)
    done = import_mapped(
        api_client, env, LABOR, "griglia.xlsx", content, body["proposal"], snapshot="2026-11-28"
    )

    assert done.json()["succeeded"] is True
    after = _store(db_session, env, LaborMappingProfile)
    assert len(after.families) == 2  # the same family, corrected: not a third
    assert _family(after, grid.id).layout == {"grid": {"hours_field": "actual_hours"}}
    assert _family(after, grid.id).revision == 2
    assert _family(after, grid.id).history[0]["layout"] == {
        "grid": {"hours_field": "planned_hours"}
    }
    assert _family(after, normal.id).model_dump(exclude={"touched"}) == before
    # and the next grid is read the corrected way, the table as ever
    inspection = _look(db_session, env, DataSourceDomain.LABOR, "griglia.xlsx", staff_grid(12))
    assert _read_as(inspection) == {"grid": {"hours_field": "actual_hours"}}
    _nothing_asked(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=12))


def test_the_sheet_a_family_is_read_through_can_be_corrected_without_touching_another(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, BOOKINGS, "pms.xlsx", reservations_pms(10), PMS_SAYS, 10)
    _teach(api_client, env, BOOKINGS, "export.xlsx", reservations_export(9), EXPORT_SAYS, 9)
    store = _store(db_session, env)
    export = next(m for m in store.families if m.layout == {"sheets": ["Export"]})
    pms = next(m for m in store.families if m.layout == {"sheets": ["Prenotazioni"]})
    before = export.model_dump(exclude={"touched"})

    # the PMS export now arrives with the sheet renamed: the person says which it is
    renamed = reservations_pms(11)
    body = understand(api_client, env, BOOKINGS, "pms.xlsx", renamed, PMS_SAYS)
    assert body["understanding"]["level"] == "READY"

    # without the answer the family is still recognised - nothing is guessed about the sheet
    plain = _look(db_session, env, DataSourceDomain.BOOKINGS, "pms.xlsx", renamed)
    assert _id(plain) == pms.id
    after = _store(db_session, env)
    assert len(after.families) == 2
    assert _family(after, export.id).model_dump(exclude={"touched"}) == before


def test_a_layout_change_is_a_revision_of_the_family_not_a_new_family_every_time(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    before = _store(db_session, env, LaborMappingProfile)

    for month, hours in ((11, "actual_hours"), (12, "planned_hours")):
        content = staff_grid(month)
        body = understand(api_client, env, LABOR, "g.xlsx", content, {"grid_hours": hours})
        import_mapped(
            api_client, env, LABOR, "g.xlsx", content, body["proposal"], snapshot=f"2026-{month}-28"
        )

    after = _store(db_session, env, LaborMappingProfile)
    assert len(after.families) == len(before.families) == 1
    assert after.families[0].revision == 3 and len(after.families[0].history) == 2


# --- a hint that cannot be used, an old store, nothing personal ---


def test_a_damaged_layout_costs_that_family_its_hints_and_no_other_anything(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _staff_normal(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learning = json.loads(json.dumps(profile.format_options["learning"]))
    for family in learning["families"]:
        if family["layout"] and "grid" in family["layout"]:
            family["layout"] = {"grid": {"hours_field": "nope"}}
    profile.format_options = {**profile.format_options, "learning": learning}
    db_session.flush()

    grid = understand(api_client, env, LABOR, "griglia.xlsx", staff_grid(11))

    # the grid family reads without its hours (it asks, like any grid nobody taught)...
    assert [q["id"] for q in grid["understanding"]["questions"]] == ["GRID_HOURS"]
    # ...and the other family is not affected at all
    _nothing_asked(api_client, env, LABOR, "turni.xlsx", xlsx_of(STAFF, month=11))


def test_a_store_written_before_layouts_were_per_family_still_reads(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learning = json.loads(json.dumps(profile.format_options["learning"]))
    for family in learning["families"]:
        del family["layout"]  # as Source Learning 1.1 stored it
    profile.format_options = {**profile.format_options, "learning": learning}
    db_session.flush()

    # the profile's layout is the layout of the import that wrote the profile: this family's
    _nothing_asked(api_client, env, LABOR, "griglia.xlsx", staff_grid(11))


def test_the_flat_memory_of_the_first_gate_reads_with_the_layout_of_the_profile_it_sits_in(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    flat = json.loads(json.dumps(profile.format_options["learning"]["families"][0]))
    del flat["layout"]
    profile.format_options = {**profile.format_options, "learning": flat}
    db_session.flush()

    _nothing_asked(api_client, env, LABOR, "griglia.xlsx", staff_grid(11))


def test_the_layout_of_the_last_import_is_not_given_to_a_family_that_did_not_write_it(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _staff_normal(api_client, env)
    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learning = json.loads(json.dumps(profile.format_options["learning"]))
    for family in learning["families"]:
        del family["layout"]  # no family says how it is read
    profile.format_options = {**profile.format_options, "learning": learning}
    db_session.flush()
    store = _store(db_session, env, LaborMappingProfile)

    # the profile holds the ordinary table's layout (the last import); the grid family did not
    # write it, so it is NOT lent to the grid: the grid asks its hours again, honestly
    grid = understand(api_client, env, LABOR, "griglia.xlsx", staff_grid(11))
    assert store.current != _id(
        _look(db_session, env, DataSourceDomain.LABOR, "g.xlsx", staff_grid(11))
    )
    assert [q["id"] for q in grid["understanding"]["questions"]] == ["GRID_HOURS"]


def test_a_sheet_that_names_a_person_is_never_kept_in_a_family(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import io

    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(reservations_pms(10)))
    book["Prenotazioni"].title = "Mario Rossi"
    buffer = io.BytesIO()
    book.save(buffer)

    _teach(
        api_client, env, BOOKINGS, "pms.xlsx", buffer.getvalue(), {"sheet_name": "Mario Rossi"}, 10
    )

    (profile,) = profiles_of(db_session, env, BookingMappingProfile)
    learned = json.dumps(profile.format_options["learning"], ensure_ascii=False).casefold()
    for fragment in ("rossi", "mario", "pms.xlsx", ".xlsx"):
        assert fragment not in learned
    assert _family(_store(db_session, env), _store(db_session, env).current).layout == {}


def test_nothing_personal_or_dated_is_kept_in_the_hints(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)
    _teach(api_client, env, LABOR, "titolo.xlsx", staff_title_department(9), TITLE_SAYS, 9)

    (profile,) = profiles_of(db_session, env, LaborMappingProfile)
    learned = json.dumps(profile.format_options["learning"], ensure_ascii=False).casefold()

    for fragment in ("period_start", "table_key", "2026", "persona", "turni", ".xlsx"):
        assert fragment not in learned, fragment


# --- isolation ---


def test_the_hints_of_one_property_never_reach_another(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    _teach_three_formats(api_client, env)
    sister = SourcesEnv(env.workspace, factory.property(env.workspace), env.user)

    other = _look(db_session, sister, DataSourceDomain.BOOKINGS, "pms.xlsx", reservations_pms(11))

    assert other.learning is not None and other.learning.layout is None
    assert _read_as(other) == {}  # read on its own terms, as any source nobody taught


def test_the_hints_of_one_kind_of_data_never_reach_another(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    _teach(api_client, env, LABOR, "griglia.xlsx", staff_grid(10), GRID_SAYS, 10)

    other = _look(db_session, env, DataSourceDomain.BOOKINGS, "pms.xlsx", reservations_pms(11))

    assert other.learning is not None and other.learning.layout is None
    assert _read_as(other) == {}

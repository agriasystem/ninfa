"""Data-source API V1 (Struttura > Fonti dati): GET `.../data-sources`, DELETE `.../{id}`,
POST `.../import-preview?domain=`, POST `.../imports?domain=`, GET `.../templates/{domain}`.

What is pinned here: authentication and tenant/property isolation (the safe 404); a state that is
always TRUE (no integration is ever reported connected; a card is only configured once a real
import has delivered; the last update is a real import's own timestamp); a source that comes to
exist ONLY when an import succeeds (opening a dialog, choosing a file, an import that fails or an
abandoned flow never leave a "configured" source); the import going through the real import
services; removing a source keeping every imported row; no technical error text reaching the page.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli import imports as cli
from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.repository import BookingRepository
from app.modules.data_sources.service import DataSourcesService, ImportOutcome
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportJob, ImportJobStatus
from tests.data_sources_support import (
    LABOR_DAY,
    SourcesEnv,
    booking_bytes,
    card,
    import_ok,
    jobs_of,
    labor_bytes,
    malformed_booking_bytes,
    raw,
    sources_env,
    sources_of,
)
from tests.decision_api_support import assert_error
from tests.invoice_support import fattura_xml
from tests.support import BookingFactory

CARDS = ["PMS", "CHANNEL_MANAGER", "OTA", "ACCOUNTING", "STAFF"]
DOMAINS = ("BOOKINGS", "COSTS", "LABOR")
CARD_OF = {"BOOKINGS": "PMS", "COSTS": "ACCOUNTING", "LABOR": "STAFF"}
HEADER_ONLY = b"source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel\n"


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _job_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(ImportJob)) or 0)


def _source_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(DataSource)) or 0)


def _jobs_on(session: Session, data_source_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.data_source_id == data_source_id)
        )
        or 0
    )


def _upload(
    client: TestClient, env: SourcesEnv, domain: str, content: bytes, name: str
) -> dict[str, Any]:
    """Import `content` into `domain` the way the page does (labor carries the local day)."""
    snapshot = LABOR_DAY if domain == "LABOR" else None
    response = raw(client, env.imports_url(domain, name, snapshot=snapshot), content)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _assert_no_active_source(session: Session, env: SourcesEnv) -> None:
    for domain in DataSourceDomain:
        assert [s for s in sources_of(session, env, domain) if s.is_active] == []


# --- authentication / authorization --------------------------------------------------------------


def test_every_route_answers_401_without_a_session(
    api_client: TestClient, factory: BookingFactory
) -> None:
    ws = factory.workspace()
    prop = factory.property(ws)
    base = f"/api/v1/properties/{prop.id}/data-sources"

    assert api_client.get(base).status_code == 401
    assert api_client.delete(f"{base}/{uuid4()}").status_code == 401
    assert raw(api_client, f"{base}/import-preview?domain=BOOKINGS", b"x").status_code == 401
    assert (
        raw(api_client, f"{base}/imports?domain=BOOKINGS&filename=a.csv", b"x").status_code == 401
    )
    assert api_client.get(f"{base}/templates/BOOKINGS").status_code == 401


def test_a_property_of_another_workspace_is_the_same_404_as_a_missing_one(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    env: SourcesEnv,
) -> None:
    foreign_prop = factory.property(factory.workspace())
    foreign_base = f"/api/v1/properties/{foreign_prop.id}/data-sources"
    missing_base = f"/api/v1/properties/{uuid4()}/data-sources"
    sources_before = _source_count(db_session)

    for base in (foreign_base, missing_base):
        assert_error(api_client.get(base), status_code=404, code="PROPERTY_NOT_FOUND")
        assert_error(
            raw(api_client, f"{base}/import-preview?domain=BOOKINGS", booking_bytes()),
            status_code=404,
            code="PROPERTY_NOT_FOUND",
        )
        assert_error(
            raw(api_client, f"{base}/imports?domain=BOOKINGS&filename=a.csv", booking_bytes()),
            status_code=404,
            code="PROPERTY_NOT_FOUND",
        )
        assert_error(
            api_client.get(f"{base}/templates/BOOKINGS"), status_code=404, code="PROPERTY_NOT_FOUND"
        )
    # a refused request configures nothing, in the foreign property or anywhere else
    assert _source_count(db_session) == sources_before


def test_a_source_of_another_property_is_unreachable_through_mine(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    # Same workspace, another property; and another workspace altogether.
    other_prop = factory.property(env.workspace)
    same_ws_source = factory.data_source(other_prop, DataSourceDomain.BOOKINGS)
    foreign = factory.tenant()
    sources = (same_ws_source.id, foreign.data_source.id)
    jobs_before = _job_count(db_session)

    for source_id in sources:
        assert_error(
            api_client.delete(f"{env.base}/{source_id}"),
            status_code=404,
            code="DATA_SOURCE_NOT_FOUND",
        )
    for source_id in sources:
        untouched = db_session.get(DataSource, source_id)
        assert untouched is not None and untouched.is_active is True
    assert _job_count(db_session) == jobs_before


def test_an_import_into_my_property_never_touches_another_propertys_source(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    other_prop = factory.property(env.workspace)
    same_ws_source = factory.data_source(other_prop, DataSourceDomain.BOOKINGS)
    foreign = factory.tenant()
    others = (same_ws_source.id, foreign.data_source.id)
    others_before = {source_id: _jobs_on(db_session, source_id) for source_id in others}

    import_ok(api_client, env, "BOOKINGS")

    (mine,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    assert mine.id not in others  # a source of my own was made, theirs were not borrowed
    assert {source_id: _jobs_on(db_session, source_id) for source_id in others} == others_before
    for source_id in others:
        untouched = db_session.get(DataSource, source_id)
        assert untouched is not None and untouched.is_active is True


def test_the_overview_never_shows_another_propertys_sources(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    other_prop = factory.property(env.workspace)
    factory.data_source(other_prop, DataSourceDomain.LABOR)
    factory.data_source(factory.property(factory.workspace()), DataSourceDomain.COSTS)

    for name in CARDS:
        assert card(api_client, env, name)["state"] == "NOT_CONFIGURED"


# --- the truth of the state ----------------------------------------------------------------------


def test_a_property_with_no_source_reads_not_configured_everywhere(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = api_client.get(env.base)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["property_id"] == str(env.property.id)
    assert [c["card"] for c in body["cards"]] == CARDS
    for item in body["cards"]:
        assert item["state"] == "NOT_CONFIGURED", item
        assert item["data_source_id"] is None
        assert item["last_update_at"] is None
        assert item["channels"] == []
    assert response.headers["cache-control"] == "no-store"


def test_nothing_is_ever_reported_as_an_automatic_connection(
    api_client: TestClient, env: SourcesEnv
) -> None:
    for domain in DOMAINS:
        import_ok(api_client, env, domain)
    body = api_client.get(env.base).json()

    assert body["automatic_integrations"] == []
    assert all(item["state"] != "CONNECTED" for item in body["cards"])
    # the only ways to provide data are the real file formats
    assert {c["domain"]: c["methods"] for c in body["capabilities"]} == {
        "BOOKINGS": ["CSV"],
        "COSTS": ["XML"],
        "LABOR": ["CSV"],
    }


def test_the_response_names_no_vendor(api_client: TestClient, env: SourcesEnv) -> None:
    import_ok(api_client, env, "BOOKINGS")
    text = api_client.get(env.base).text

    for vendor in ("Mews", "SiteMinder", "Cloudbeds", "TeamSystem"):
        assert vendor not in text


def test_several_active_sources_of_a_domain_are_reported_not_picked(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    factory.data_source(env.property, DataSourceDomain.BOOKINGS)
    factory.data_source(env.property, DataSourceDomain.BOOKINGS)

    pms = card(api_client, env, "PMS")

    assert pms["several_sources"] is True
    assert pms["data_source_id"] is None
    assert pms["last_update_at"] is None


def test_an_import_is_refused_rather_than_guessing_between_several_active_sources(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    factory.data_source(env.property, DataSourceDomain.BOOKINGS)
    factory.data_source(env.property, DataSourceDomain.BOOKINGS)
    sources_before = _source_count(db_session)
    jobs_before = _job_count(db_session)

    response = raw(api_client, env.imports_url("BOOKINGS"), booking_bytes())

    assert_error(response, status_code=409, code="SEVERAL_SOURCES")
    assert _source_count(db_session) == sources_before
    assert _job_count(db_session) == jobs_before
    assert BookingRepository(db_session, env.tenant).list_for_property(env.property.id) == []


# --- a source exists only after a SUCCESSFUL import ----------------------------------------------


def test_there_is_no_route_that_creates_a_source_on_its_own(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    for domain in DOMAINS:
        assert api_client.post(env.base, json={"domain": domain}).status_code == 405
    assert _source_count(db_session) == 0


def test_opening_the_dialog_creates_no_source(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    """Opening a dialog only READS: the overview, and the column template the dialog offers."""
    for _ in range(2):
        assert api_client.get(env.base).status_code == 200
    assert api_client.get(f"{env.base}/templates/BOOKINGS").status_code == 200
    assert api_client.get(f"{env.base}/templates/LABOR").status_code == 200

    assert _source_count(db_session) == 0
    assert jobs_of(db_session, env) == []
    for name in CARDS:
        assert card(api_client, env, name)["state"] == "NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("domain", "content"),
    [
        ("BOOKINGS", booking_bytes()),
        ("LABOR", labor_bytes()),
        ("COSTS", fattura_xml()),
        ("BOOKINGS", malformed_booking_bytes()),
        ("BOOKINGS", b"nome,cognome\nMario,Rossi\n"),
    ],
)
def test_choosing_a_file_without_confirming_the_import_configures_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv, domain: str, content: bytes
) -> None:
    """The dialog previews the chosen file: that is a pure read, so a flow that stops there (the
    user closes the dialog, or never presses "Importa") leaves the card exactly as it was."""
    response = raw(api_client, env.preview_url(domain), content)

    assert response.status_code == 200, response.text
    assert _source_count(db_session) == 0
    assert jobs_of(db_session, env) == []
    assert card(api_client, env, CARD_OF[domain])["state"] == "NOT_CONFIGURED"
    assert card(api_client, env, "OTA")["state"] == "NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("domain", "content", "problem"),
    [
        ("BOOKINGS", malformed_booking_bytes(), "INVALID_ROWS"),
        ("BOOKINGS", b"nome,cognome\nMario,Rossi\n", "MISSING_COLUMNS"),
        ("BOOKINGS", b"\xff\xfe\x00bad", "UNREADABLE_FILE"),
        ("COSTS", b"fornitore,importo\nRossi,10\n", "UNSUPPORTED_FILE"),
        ("LABOR", b"work_date,currency\n2026-10-01,EUR\n", "MISSING_COLUMNS"),
    ],
)
def test_a_failed_first_import_leaves_no_configured_source(
    api_client: TestClient,
    db_session: Session,
    env: SourcesEnv,
    domain: str,
    content: bytes,
    problem: str,
) -> None:
    body = _upload(api_client, env, domain, content, "guasto.csv")

    assert body["succeeded"] is False
    assert body["problem"] == problem
    # nothing is configured: not the card, not the derived cards, not an active source row
    _assert_no_active_source(db_session, env)
    for name in CARDS:
        item = card(api_client, env, name)
        assert item["state"] == "NOT_CONFIGURED", item
        assert item["data_source_id"] is None
        assert item["last_update_at"] is None
    assert all(job.status != ImportJobStatus.SUCCEEDED for job in jobs_of(db_session, env))
    assert BookingRepository(db_session, env.tenant).list_for_property(env.property.id) == []


def test_a_failed_import_answers_with_a_reason_never_with_technical_text(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = raw(api_client, env.imports_url("BOOKINGS", "guasto.csv"), malformed_booking_bytes())

    text = response.text.lower()
    for technical in ("traceback", "validation", "booking_", "error_code", "exception", "sql"):
        assert technical not in text
    assert set(response.json()) == {
        "succeeded",
        "problem",
        "rows_total",
        "rows_invalid",
        "created",
        "updated",
        "unchanged",
        "already_imported",
    }


def test_a_failed_import_after_a_failed_one_still_leaves_nothing_configured(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    for _ in range(2):
        body = _upload(api_client, env, "BOOKINGS", malformed_booking_bytes(), "guasto.csv")
        assert body["succeeded"] is False

    _assert_no_active_source(db_session, env)
    assert card(api_client, env, "PMS")["state"] == "NOT_CONFIGURED"
    # the attempts do not pile up sources: the (switched off) one is reused
    assert len(sources_of(db_session, env, DataSourceDomain.BOOKINGS)) == 1


def test_an_unexpected_failure_during_an_import_leaves_no_configured_source(
    db_session: Session, env: SourcesEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self: DataSourcesService, *args: object, **kwargs: object) -> ImportOutcome:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(DataSourcesService, "_import_bookings", explode)

    with pytest.raises(RuntimeError):
        DataSourcesService(db_session, env.tenant).import_file(
            env.property.id,
            DataSourceDomain.BOOKINGS,
            filename="prenotazioni.csv",
            content=booking_bytes(),
        )

    _assert_no_active_source(db_session, env)
    overview = DataSourcesService(db_session, env.tenant).overview(env.property.id)
    assert all(item.state.value == "NOT_CONFIGURED" for item in overview.cards)


def test_a_successful_first_import_creates_the_source_and_configures_the_card(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    assert sources_of(db_session, env, DataSourceDomain.BOOKINGS) == []

    response = raw(api_client, env.imports_url("BOOKINGS", "prenotazioni.csv"), booking_bytes())

    assert response.status_code == 200, response.text
    assert response.json() == {
        "succeeded": True,
        "problem": None,
        "rows_total": 2,
        "rows_invalid": 0,
        "created": 2,
        "updated": 0,
        "unchanged": 0,
        "already_imported": False,
    }
    (source,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    assert source.is_active is True
    assert len(BookingRepository(db_session, env.tenant).list_for_property(env.property.id)) == 2
    pms = card(api_client, env, "PMS")
    assert pms["state"] == "CONFIGURED_FILE"
    assert pms["method"] == "CSV"
    assert pms["data_source_id"] == str(source.id)
    # the card's last update is the import's own finished_at - never a clock of the page
    job = db_session.scalar(select(ImportJob).where(ImportJob.data_source_id == source.id))
    assert job is not None and job.status == ImportJobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert pms["last_update_at"] is not None


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_domain_is_configured_by_its_own_successful_import(
    api_client: TestClient, db_session: Session, env: SourcesEnv, domain: str
) -> None:
    import_ok(api_client, env, domain)

    item = card(api_client, env, CARD_OF[domain])
    assert item["state"] == "CONFIGURED_FILE"
    assert item["last_update_at"] is not None
    (source,) = sources_of(db_session, env, DataSourceDomain(domain))
    assert source.is_active is True
    # the other kinds of data are untouched
    for other in DOMAINS:
        if other != domain:
            assert sources_of(db_session, env, DataSourceDomain(other)) == []


def test_a_second_import_reuses_the_same_source_and_moves_the_last_update(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    (first,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    first_update = card(api_client, env, "PMS")["last_update_at"]

    second = _upload(
        api_client,
        env,
        "BOOKINGS",
        booking_bytes(channels=("Booking.com", "Direct", "Expedia")),
        "prenotazioni-2.csv",
    )

    assert second["succeeded"] is True
    assert second["created"] == 1 and second["unchanged"] == 2
    (only,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    assert only.id == first.id  # the SAME source: no second, empty one
    succeeded = [j for j in jobs_of(db_session, env) if j.status == ImportJobStatus.SUCCEEDED]
    assert len(succeeded) == 2
    pms = card(api_client, env, "PMS")
    assert pms["data_source_id"] == str(first.id)
    assert pms["last_update_at"] >= first_update
    assert len(BookingRepository(db_session, env.tenant).list_for_property(env.property.id)) == 3


def test_the_same_file_twice_is_idempotent_and_says_so(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")

    again = _upload(api_client, env, "BOOKINGS", booking_bytes(), "prenotazioni.csv")

    assert again["succeeded"] is True
    assert again["already_imported"] is True
    assert again["created"] == 0
    assert again["unchanged"] == 2
    assert len(sources_of(db_session, env, DataSourceDomain.BOOKINGS)) == 1
    assert len(BookingRepository(db_session, env.tenant).list_for_property(env.property.id)) == 2


def test_a_failed_import_never_unconfigures_a_source_that_already_delivered(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    before = card(api_client, env, "PMS")

    body = _upload(api_client, env, "BOOKINGS", malformed_booking_bytes(), "guasto.csv")

    assert body["succeeded"] is False
    after = card(api_client, env, "PMS")
    assert after["state"] == "CONFIGURED_FILE"
    assert after["data_source_id"] == before["data_source_id"]
    assert after["last_update_at"] == before["last_update_at"]  # a failure is not an update
    assert len(BookingRepository(db_session, env.tenant).list_for_property(env.property.id)) == 2


def test_a_source_that_never_delivered_reads_not_configured_and_is_reused_by_the_first_import(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    dormant = factory.data_source(env.property, DataSourceDomain.BOOKINGS)  # active, never fed

    pms = card(api_client, env, "PMS")
    assert pms["state"] == "NOT_CONFIGURED"
    assert pms["data_source_id"] is None
    assert pms["last_update_at"] is None

    import_ok(api_client, env, "BOOKINGS")

    (only,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    assert only.id == dormant.id  # reused, not duplicated
    assert card(api_client, env, "PMS")["state"] == "CONFIGURED_FILE"


def test_a_failed_import_into_a_source_that_never_delivered_does_not_switch_it_off(
    api_client: TestClient, factory: BookingFactory, db_session: Session, env: SourcesEnv
) -> None:
    """Only what THIS import switched on is switched off again: an active source somebody else
    set up is not this call's to undo."""
    dormant = factory.data_source(env.property, DataSourceDomain.BOOKINGS)

    body = _upload(api_client, env, "BOOKINGS", malformed_booking_bytes(), "guasto.csv")

    assert body["succeeded"] is False
    reloaded = db_session.get(DataSource, dormant.id)
    assert reloaded is not None and reloaded.is_active is True
    assert card(api_client, env, "PMS")["state"] == "NOT_CONFIGURED"


def test_after_a_bookings_import_the_channel_manager_and_ota_are_received_not_to_be_linked_again(
    api_client: TestClient, env: SourcesEnv
) -> None:
    assert card(api_client, env, "CHANNEL_MANAGER")["state"] == "NOT_CONFIGURED"
    assert card(api_client, env, "OTA")["state"] == "NOT_CONFIGURED"

    import_ok(api_client, env, "BOOKINGS")
    channel_manager = card(api_client, env, "CHANNEL_MANAGER")
    ota = card(api_client, env, "OTA")

    assert channel_manager["state"] == "DERIVED"
    assert channel_manager["derived_from"] == "BOOKINGS_FILE"
    assert channel_manager["data_source_id"] is None
    assert ota["state"] == "DERIVED"
    assert ota["derived_from"] == "BOOKINGS_FILE"
    # the REAL channel names found in the imported bookings; "Direct" is not an OTA
    assert ota["channels"] == ["Booking.com"]
    # nothing else is dragged along
    assert card(api_client, env, "ACCOUNTING")["state"] == "NOT_CONFIGURED"
    assert card(api_client, env, "STAFF")["state"] == "NOT_CONFIGURED"


# --- importing: the real services ----------------------------------------------------------------


def test_a_labor_file_needs_the_property_local_day_and_never_guesses_it(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    url = env.imports_url("LABOR", "personale.csv")
    jobs_before = _job_count(db_session)

    assert_error(raw(api_client, url, labor_bytes()), status_code=400, code="INVALID_SNAPSHOT_DATE")
    assert_error(
        raw(api_client, f"{url}&snapshot_local_date=ieri", labor_bytes()),
        status_code=400,
        code="INVALID_SNAPSHOT_DATE",
    )
    # a request that cannot be imported does not even switch a source on
    assert _job_count(db_session) == jobs_before
    assert sources_of(db_session, env, DataSourceDomain.LABOR) == []

    body = import_ok(api_client, env, "LABOR")
    assert body["created"] == 1
    assert card(api_client, env, "STAFF")["last_update_at"] is not None


def test_a_different_labor_file_for_the_same_day_is_a_conflict_not_an_overwrite(
    api_client: TestClient, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "LABOR")
    other = (
        b"work_date,labor_category,planned_hours,planned_cost,currency\n"
        b"2026-11-02,HOUSEKEEPING,5,80.00,EUR\n"
    )

    body = _upload(api_client, env, "LABOR", other, "personale-2.csv")

    assert body["succeeded"] is False
    assert body["problem"] == "SAME_DAY_CONFLICT"
    assert card(api_client, env, "STAFF")["state"] == "CONFIGURED_FILE"  # the first one stands


def test_an_invoice_xml_is_imported_into_the_costs_source(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = import_ok(api_client, env, "COSTS")

    assert body["created"] == 1
    accounting = card(api_client, env, "ACCOUNTING")
    assert accounting["state"] == "CONFIGURED_FILE"
    assert accounting["method"] == "XML"
    assert accounting["last_update_at"] is not None


# --- the preview ---------------------------------------------------------------------------------


def test_the_preview_works_before_any_source_exists_and_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    response = raw(api_client, env.preview_url("BOOKINGS"), booking_bytes(extra="note_interne"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_import"] is True
    assert body["problem"] is None
    assert body["method"] == "CSV"
    assert body["rows_total"] == 2
    assert set(body["recognized_columns"]) >= {"source_record_id", "check_in", "channel"}
    assert body["missing_columns"] == []
    assert body["unrecognized_columns"] == ["note_interne"]
    assert body["sample_columns"][0] == "source_record_id"
    assert len(body["sample_rows"]) == 2
    assert body["already_imported"] is False
    assert _source_count(db_session) == 0
    assert jobs_of(db_session, env) == []
    assert BookingRepository(db_session, env.tenant).list_for_property(env.property.id) == []


def test_the_preview_names_the_missing_columns_and_blocks_the_import(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = raw(
        api_client, env.preview_url("BOOKINGS"), b"source_record_id,check_in\nA1,2026-10-01\n"
    ).json()

    assert body["can_import"] is False
    assert body["problem"] == "MISSING_COLUMNS"
    required_missing = {group[0] for group in body["missing_columns"]}
    assert required_missing == {
        CanonicalField.BOOKED_AT.value,
        CanonicalField.CHECK_OUT.value,
        CanonicalField.STATUS.value,
        CanonicalField.ROOMS.value,
        CanonicalField.ROOM_REVENUE.value,
        CanonicalField.CHANNEL.value,
    }


def test_the_preview_of_labor_names_alternatives_as_one_group(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = raw(api_client, env.preview_url("LABOR"), b"work_date,currency\n2026-10-01,EUR\n").json()

    assert body["problem"] == "MISSING_COLUMNS"
    assert ["actual_hours", "planned_hours"] in body["missing_columns"]
    assert ["labor_category", "role"] in body["missing_columns"]


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"", "EMPTY_FILE"),
        (b"   \n", "EMPTY_FILE"),
        (b"\xff\xfe\x00bad", "UNREADABLE_FILE"),
        (HEADER_ONLY, "NO_ROWS"),
        (b"a,a\n1,2\n", "DUPLICATE_COLUMNS"),
    ],
)
def test_the_preview_reports_a_file_that_cannot_be_used(
    api_client: TestClient, env: SourcesEnv, content: bytes, problem: str
) -> None:
    body = raw(api_client, env.preview_url("BOOKINGS"), content).json()

    assert body["can_import"] is False
    assert body["problem"] == problem


def test_the_preview_says_when_the_same_file_was_already_imported(
    api_client: TestClient, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")

    body = raw(api_client, env.preview_url("BOOKINGS"), booking_bytes()).json()

    assert body["already_imported"] is True


def test_the_preview_still_knows_a_file_imported_through_a_source_that_was_removed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    api_client.delete(f"{env.base}/{card(api_client, env, 'PMS')['data_source_id']}")

    body = raw(api_client, env.preview_url("BOOKINGS"), booking_bytes()).json()

    assert body["already_imported"] is True


def test_the_preview_of_an_invoice_counts_the_documents(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = raw(api_client, env.preview_url("COSTS"), fattura_xml()).json()

    assert body["method"] == "XML"
    assert body["can_import"] is True
    assert body["rows_total"] == 1
    assert body["documents_with_issues"] == 0


def test_the_preview_of_something_that_is_not_an_invoice_blocks_the_import(
    api_client: TestClient, env: SourcesEnv
) -> None:
    for content in (b"fornitore,importo\nRossi,10\n", b"<altro/>"):
        body = raw(api_client, env.preview_url("COSTS"), content).json()
        assert body["can_import"] is False
        assert body["problem"] in {"UNREADABLE_FILE", "UNSUPPORTED_FORMAT"}


def test_the_kind_of_data_is_required_and_must_be_a_known_one(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    for domain in ("DISTRIBUTION", "PMS", ""):
        assert raw(api_client, env.preview_url(domain), b"x").status_code == 422
        assert raw(api_client, env.imports_url(domain), b"x").status_code == 422
    assert raw(api_client, f"{env.base}/import-preview", b"x").status_code == 422
    assert raw(api_client, f"{env.base}/imports?filename=a.csv", b"x").status_code == 422
    assert _source_count(db_session) == 0


# --- size ----------------------------------------------------------------------------------------


def test_a_file_over_the_maximum_is_refused_with_413_and_configures_nothing(
    api_client: TestClient,
    db_session: Session,
    env: SourcesEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.v1.sources.router.MAX_FILE_BYTES", 64)
    monkeypatch.setattr("app.modules.data_sources.service.MAX_FILE_BYTES", 64)

    for url in (env.preview_url("BOOKINGS"), env.imports_url("BOOKINGS")):
        assert_error(raw(api_client, url, b"x" * 65), status_code=413, code="FILE_TOO_LARGE")

    assert _source_count(db_session) == 0


# --- removing a source ---------------------------------------------------------------------------


def test_removing_a_source_switches_it_off_and_keeps_every_imported_row(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    source_id = UUID(card(api_client, env, "PMS")["data_source_id"])
    bookings = BookingRepository(db_session, env.tenant)
    assert len(bookings.list_for_property(env.property.id)) == 2

    response = api_client.delete(f"{env.base}/{source_id}")

    assert response.status_code == 204
    # the row is still there, only switched off; the imported bookings are untouched
    source = db_session.get(DataSource, source_id)
    assert source is not None and source.is_active is False
    assert len(bookings.list_for_property(env.property.id)) == 2
    # the cards no longer claim anything
    assert card(api_client, env, "PMS")["state"] == "NOT_CONFIGURED"
    assert card(api_client, env, "OTA")["state"] == "NOT_CONFIGURED"
    # a removed source cannot be removed again
    assert_error(
        api_client.delete(f"{env.base}/{source_id}"), status_code=404, code="DATA_SOURCE_NOT_FOUND"
    )


def test_importing_again_after_a_removal_reuses_the_same_source_and_its_history(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    (original,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    api_client.delete(f"{env.base}/{original.id}")
    assert card(api_client, env, "PMS")["state"] == "NOT_CONFIGURED"

    body = _upload(
        api_client,
        env,
        "BOOKINGS",
        booking_bytes(channels=("Booking.com", "Direct", "Expedia")),
        "prenotazioni-2.csv",
    )

    assert body["succeeded"] is True
    (only,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    assert only.id == original.id  # no second, empty source
    assert only.is_active is True
    pms = card(api_client, env, "PMS")
    assert pms["state"] == "CONFIGURED_FILE"
    assert pms["data_source_id"] == str(original.id)
    succeeded = [j for j in jobs_of(db_session, env) if j.status == ImportJobStatus.SUCCEEDED]
    assert len(succeeded) == 2  # the earlier import is still part of this source's history


def test_a_failed_import_after_a_removal_leaves_the_source_removed(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    (original,) = sources_of(db_session, env, DataSourceDomain.BOOKINGS)
    api_client.delete(f"{env.base}/{original.id}")

    body = _upload(api_client, env, "BOOKINGS", malformed_booking_bytes(), "guasto.csv")

    assert body["succeeded"] is False
    reloaded = db_session.get(DataSource, original.id)
    assert reloaded is not None and reloaded.is_active is False
    assert card(api_client, env, "PMS")["state"] == "NOT_CONFIGURED"
    assert card(api_client, env, "OTA")["state"] == "NOT_CONFIGURED"
    # the data that arrived earlier are still there
    assert len(BookingRepository(db_session, env.tenant).list_for_property(env.property.id)) == 2


# --- templates -----------------------------------------------------------------------------------


def test_the_templates_are_only_the_canonical_column_row(
    api_client: TestClient, env: SourcesEnv
) -> None:
    bookings = api_client.get(f"{env.base}/templates/BOOKINGS")
    labor = api_client.get(f"{env.base}/templates/LABOR")

    assert bookings.status_code == labor.status_code == 200
    assert bookings.headers["content-type"].startswith("text/csv")
    assert "attachment" in bookings.headers["content-disposition"]
    assert bookings.content.decode("utf-8-sig").strip().split(",") == [
        f.value for f in CanonicalField
    ]
    assert labor.content.decode("utf-8-sig").strip() == (
        "work_date,role,labor_category,planned_hours,actual_hours,planned_cost,actual_cost,currency"
    )
    # a single header row: no example data that could be imported by mistake
    assert len(bookings.content.decode("utf-8-sig").strip().splitlines()) == 1


def test_there_is_no_csv_template_for_costs(api_client: TestClient, env: SourcesEnv) -> None:
    assert_error(
        api_client.get(f"{env.base}/templates/COSTS"), status_code=404, code="UNSUPPORTED_DOMAIN"
    )


def test_the_template_is_recognised_by_the_preview_so_it_can_never_drift_from_the_importer(
    api_client: TestClient, env: SourcesEnv
) -> None:
    for domain in ("BOOKINGS", "LABOR"):
        template = api_client.get(f"{env.base}/templates/{domain}").content

        body = raw(api_client, env.preview_url(domain), template).json()

        assert body["missing_columns"] == []
        assert body["unrecognized_columns"] == []
        assert body["problem"] == "NO_ROWS"  # a column row alone holds no data


def test_the_cli_and_the_api_share_one_canonical_convention() -> None:
    """A file the API's template describes is exactly the one `app.cli.imports` already accepted:
    the CLI no longer carries a copy of the convention, it imports it."""
    cli_source = (Path(cli.__file__)).read_text(encoding="utf-8")

    assert "from app.modules.ingestion.canonical_csv import" in cli_source
    assert "def _identity_column_mapping" not in cli_source
    assert "def _read_headers" not in cli_source

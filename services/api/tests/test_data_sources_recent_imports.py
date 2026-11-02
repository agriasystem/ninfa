"""GET `.../data-sources/imports`: the "Importazioni recenti" of the Importa file page.

What is pinned here: authentication and tenant/property isolation (the safe 404); a list built only
from real import attempts, newest first and bounded; a failed attempt that says it failed and
nothing else (no stored error text); a file name that passes the personal-data gate; a read that
writes nothing.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import (
    DataSource,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.ingestion.repository import ImportFileRepository, ImportJobRepository
from app.modules.ingestion.schemas import ImportFileCreate, ImportJobCreate
from tests.data_sources_support import (
    SourcesEnv,
    import_ok,
    malformed_booking_bytes,
    raw,
    sources_env,
)
from tests.decision_api_support import assert_error
from tests.support import BookingFactory


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _recent(client: TestClient, env: SourcesEnv) -> list[dict[str, object]]:
    response = client.get(f"{env.base}/imports")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    imports: list[dict[str, object]] = response.json()["imports"]
    return imports


def test_answers_401_without_a_session(api_client: TestClient, factory: BookingFactory) -> None:
    prop = factory.property(factory.workspace())

    response = api_client.get(f"/api/v1/properties/{prop.id}/data-sources/imports")

    assert response.status_code == 401


def test_a_property_of_another_workspace_is_the_same_404_as_a_missing_one(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    foreign = factory.tenant()
    for property_id in (foreign.property.id, uuid4()):
        response = api_client.get(f"/api/v1/properties/{property_id}/data-sources/imports")
        assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_nothing_imported_is_an_empty_list(api_client: TestClient, env: SourcesEnv) -> None:
    assert _recent(api_client, env) == []


def test_lists_what_really_arrived_newest_first_with_the_kind_of_data(
    api_client: TestClient, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    import_ok(api_client, env, "LABOR")

    recent = _recent(api_client, env)

    assert [item["file_name"] for item in recent] == ["personale.csv", "prenotazioni.csv"]
    assert [item["domain"] for item in recent] == ["LABOR", "BOOKINGS"]
    assert {item["status"] for item in recent} == {"SUCCEEDED"}
    assert all(set(item) == {"file_name", "domain", "status", "at"} for item in recent)


def test_a_failed_attempt_says_it_failed_and_nothing_else(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    raw(api_client, env.imports_url("BOOKINGS", "rotto.csv"), malformed_booking_bytes())
    stored = db_session.scalars(select(ImportJob)).all()
    assert [job.status for job in stored] == [ImportJobStatus.FAILED]
    assert stored[0].error_code is not None  # there IS a stored reason: it just never travels

    response = api_client.get(f"{env.base}/imports")

    assert response.json()["imports"] == [
        {
            "file_name": "rotto.csv",
            "domain": "BOOKINGS",
            "status": "FAILED",
            "at": response.json()["imports"][0]["at"],
        }
    ]
    assert stored[0].error_code not in response.text
    assert "error" not in response.text


def test_a_personal_value_in_the_name_of_a_file_never_travels(
    api_client: TestClient, env: SourcesEnv
) -> None:
    address = "marta.conti@example.com"
    tax_code = "RSSMRA85T10A562S"
    raw(api_client, env.imports_url("BOOKINGS", f"{address}.csv"), malformed_booking_bytes())
    raw(api_client, env.imports_url("BOOKINGS", f"{tax_code}.csv"), malformed_booking_bytes())

    response = api_client.get(f"{env.base}/imports")

    assert len(response.json()["imports"]) == 2
    assert address not in response.text
    assert tax_code not in response.text


def test_never_shows_another_propertys_imports(
    api_client: TestClient, db_session: Session, factory: BookingFactory, env: SourcesEnv
) -> None:
    same_workspace = factory.data_source(factory.property(env.workspace))
    foreign = factory.tenant()
    for tenant, source in (
        (env.tenant, same_workspace),
        (TenantContext(foreign.workspace.id), foreign.data_source),
    ):
        job = ImportJobRepository(db_session, tenant).add(ImportJobCreate(data_source_id=source.id))
        ImportFileRepository(db_session, tenant).add(
            job.id, ImportFileCreate(original_filename="di-un-altro.csv")
        )
    db_session.commit()
    import_ok(api_client, env, "BOOKINGS")

    recent = _recent(api_client, env)

    assert [item["file_name"] for item in recent] == ["prenotazioni.csv"]


def test_an_attempt_with_no_file_recorded_has_no_name_and_a_running_one_its_start(
    api_client: TestClient, db_session: Session, factory: BookingFactory, env: SourcesEnv
) -> None:
    source = factory.data_source(env.property)
    jobs = ImportJobRepository(db_session, env.tenant)
    job = jobs.add(ImportJobCreate(data_source_id=source.id))
    db_session.commit()

    recent = _recent(api_client, env)

    assert recent[0]["file_name"] is None
    assert recent[0]["status"] == "PENDING"
    assert datetime.fromisoformat(str(recent[0]["at"])) == job.created_at


def test_is_bounded_and_ordered_by_when_each_attempt_ended(
    api_client: TestClient, db_session: Session, factory: BookingFactory, env: SourcesEnv
) -> None:
    source = factory.data_source(env.property)
    jobs = ImportJobRepository(db_session, env.tenant)
    files = ImportFileRepository(db_session, env.tenant)
    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for day in range(12):
        job = jobs.add(ImportJobCreate(data_source_id=source.id))
        files.add(job.id, ImportFileCreate(original_filename=f"giorno-{day}.csv"))
        job.status = ImportJobStatus.SUCCEEDED
        job.started_at = start + timedelta(days=day)
        job.finished_at = start + timedelta(days=day, minutes=5)
    db_session.commit()

    recent = _recent(api_client, env)

    assert [item["file_name"] for item in recent] == [
        f"giorno-{day}.csv" for day in range(11, 1, -1)
    ]


def test_reading_the_list_writes_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "BOOKINGS")

    def counts() -> list[int | None]:
        return [
            db_session.scalar(select(func.count()).select_from(model))
            for model in (DataSource, ImportJob, ImportFile)
        ]

    before = counts()

    _recent(api_client, env)

    db_session.expire_all()
    assert counts() == before

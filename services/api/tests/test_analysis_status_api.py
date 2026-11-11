"""The analysis status over the API, and the post-import dispatch as the page triggers it.

`resolve_property_scope` keeps a foreign property the same 404; a successful import reaches the
queue by itself and a failed one does not; a dispatch that cannot be queued never turns a good
import into a failure; the limits a page shows are the backend's own.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.analysis.queue import ANALYSIS_REFRESH_TASK
from app.modules.bookings.parsers import MAX_COLUMNS, MAX_ROWS
from app.modules.data_sources.files import MAX_FILE_BYTES
from tests.data_sources_support import (
    LABOR_DAY,
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


def _status_url(env: SourcesEnv) -> str:
    return f"/api/v1/properties/{env.property.id}/analysis/status"


def _refresh_url(env: SourcesEnv) -> str:
    return f"/api/v1/properties/{env.property.id}/analysis/refresh"


def _status(client: TestClient, env: SourcesEnv) -> dict[str, Any]:
    response = client.get(_status_url(env))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body: dict[str, Any] = response.json()
    return body


def _jobs(db_session: Session, env: SourcesEnv) -> list[Any]:
    return list(
        db_session.execute(
            text(
                "SELECT status::text, args FROM procrastinate_jobs "
                "WHERE task_name = :t AND args ->> 'property_id' = :p ORDER BY id"
            ),
            {"t": ANALYSIS_REFRESH_TASK, "p": str(env.property.id)},
        ).all()
    )


def test_both_routes_answer_401_without_a_session(
    api_client: TestClient, factory: BookingFactory
) -> None:
    prop = factory.property(factory.workspace())

    assert api_client.get(f"/api/v1/properties/{prop.id}/analysis/status").status_code == 401
    assert api_client.post(f"/api/v1/properties/{prop.id}/analysis/refresh").status_code == 401


def test_a_property_of_another_workspace_is_the_same_404_as_a_missing_one(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    foreign = factory.tenant()
    for property_id in (foreign.property.id, uuid4()):
        for response in (
            api_client.get(f"/api/v1/properties/{property_id}/analysis/status"),
            api_client.post(f"/api/v1/properties/{property_id}/analysis/refresh"),
        ):
            assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_a_property_with_nothing_imported_says_so(api_client: TestClient, env: SourcesEnv) -> None:
    assert _status(api_client, env) == {
        "state": "NO_DATA",
        "imported_domains": [],
        "latest_import_at": None,
        "last_analysis_at": None,
        "next_attempt_at": None,
        "can_retry": False,
    }


def test_a_successful_import_asks_the_worker_by_itself(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    import_ok(api_client, env, "BOOKINGS")

    jobs = _jobs(db_session, env)
    assert [job[0] for job in jobs] == ["todo"]
    assert jobs[0][1] == {
        "workspace_id": str(env.workspace.id),
        "property_id": str(env.property.id),
    }
    status = _status(api_client, env)
    assert status["state"] == "IN_PROGRESS"
    assert status["imported_domains"] == ["BOOKINGS"]
    assert status["latest_import_at"] is not None


def test_a_second_import_while_one_waits_adds_no_second_job(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    import_ok(api_client, env, "LABOR")

    assert [job[0] for job in _jobs(db_session, env)] == ["todo"]


def test_the_same_file_again_asks_the_worker_nothing_and_says_it_changed_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    first = import_ok(api_client, env, "BOOKINGS")
    assert first["changed_data"] is True
    db_session.execute(
        text("UPDATE procrastinate_jobs SET status = 'succeeded' WHERE task_name = :t"),
        {"t": ANALYSIS_REFRESH_TASK},
    )
    db_session.flush()

    second = import_ok(api_client, env, "BOOKINGS")

    assert second["changed_data"] is False
    assert second["already_imported"] is True
    assert (second["created"], second["updated"]) == (0, 0)
    assert [job[0] for job in _jobs(db_session, env)] == ["succeeded"]  # no second job


def test_a_file_that_changes_something_asks_the_worker_again(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    first = import_ok(api_client, env, "LABOR")
    assert first["changed_data"] is True
    db_session.execute(
        text("UPDATE procrastinate_jobs SET status = 'succeeded' WHERE task_name = :t"),
        {"t": ANALYSIS_REFRESH_TASK},
    )
    db_session.flush()
    other = (
        b"work_date,labor_category,planned_hours,planned_cost,currency\n"
        b"2026-11-03,HOUSEKEEPING,5,80.00,EUR\n"
    )

    response = raw(
        api_client, env.imports_url("LABOR", "personale-2.csv", snapshot=LABOR_DAY), other
    ).json()

    assert response["succeeded"] is True
    assert response["changed_data"] is True
    assert [job[0] for job in _jobs(db_session, env)] == ["succeeded", "todo"]


def test_a_failed_import_asks_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    response = raw(api_client, env.imports_url("BOOKINGS", "p.csv"), malformed_booking_bytes())

    assert response.json()["succeeded"] is False
    assert _jobs(db_session, env) == []
    assert _status(api_client, env)["state"] == "NO_DATA"


def test_labor_alone_is_data_and_the_analysis_says_what_it_lacks(
    api_client: TestClient, env: SourcesEnv
) -> None:
    import_ok(api_client, env, "LABOR")

    status = _status(api_client, env)

    assert status["state"] == "NEEDS_BOOKINGS"
    assert status["imported_domains"] == ["LABOR"]


def test_an_import_stands_even_if_the_refresh_cannot_be_queued(
    api_client: TestClient, env: SourcesEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise SQLAlchemyError("the queue is not reachable")

    monkeypatch.setattr("app.modules.data_sources.service.enqueue_refresh", fail)

    body = import_ok(api_client, env, "BOOKINGS")

    assert body["succeeded"] is True
    status = _status(api_client, env)
    assert status["state"] == "NEW_DATA"  # never "updated", and it can be asked again
    assert status["can_retry"] is True


def test_the_recovery_queues_a_refresh_and_says_so(
    api_client: TestClient, env: SourcesEnv, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise SQLAlchemyError("the queue is not reachable")

        patch.setattr("app.modules.data_sources.service.enqueue_refresh", fail)
        import_ok(api_client, env, "BOOKINGS")
    assert _jobs(db_session, env) == []

    response = api_client.post(_refresh_url(env))

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "IN_PROGRESS"
    assert [job[0] for job in _jobs(db_session, env)] == ["todo"]


def test_the_recovery_changes_nothing_when_there_is_nothing_to_recover(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    response = api_client.post(_refresh_url(env))

    assert response.json()["state"] == "NO_DATA"
    assert _jobs(db_session, env) == []


def test_the_limits_are_the_backends_own(api_client: TestClient, env: SourcesEnv) -> None:
    response = api_client.get(f"{env.base}/import-limits")

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "max_file_bytes": MAX_FILE_BYTES,
        "max_rows": MAX_ROWS,
        "max_columns": MAX_COLUMNS,
        "file_extensions": [".csv", ".xlsx"],
    }


def test_the_limits_are_scoped_like_every_route_of_the_family(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    foreign = factory.tenant()

    response = api_client.get(
        f"/api/v1/properties/{foreign.property.id}/data-sources/import-limits"
    )

    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")

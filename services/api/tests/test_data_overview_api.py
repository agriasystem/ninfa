"""Dati overview API V1: GET /api/v1/properties/{property_id}/data/overview.

Authentication, tenant isolation, the safe 404, input validation, the response contract (Decimals
are strings, nothing internal leaks), read-only behaviour - and proof that the endpoint never
touches the language-model provider: Dati is deterministic and does not call Mia.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.decisions.deps import get_language_model_provider
from tests.ask_home_support import five_triggered_evaluations
from tests.data_overview_support import (
    AS_OF,
    full_coverage,
    overview_url,
    seed_run,
    uniform_nights,
)
from tests.decision_api_support import assert_error, authed_tenant, decision_table_counts
from tests.support import BookingFactory

AS_OF_TEXT = AS_OF.isoformat()


def _get(client: TestClient, property_id: UUID, as_of: str = AS_OF_TEXT, period: Any = None) -> Any:
    return client.get(overview_url(property_id, as_of, period))


def _floats_in(value: object, path: str = "$") -> list[str]:
    """Paths of every JSON float in `value` (there must be none: a Decimal is a string)."""
    found: list[str] = []
    if isinstance(value, float):
        found.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_floats_in(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_floats_in(item, f"{path}[{index}]"))
    return found


# --- authentication / authorization ---------------------------------------------------------------


def test_an_unauthenticated_caller_gets_401(
    api_client: TestClient, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    response = _get(api_client, tenant.property.id)

    assert response.status_code == 401


def test_a_member_reads_the_overview_of_their_property(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(db_session, auth.tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40))

    response = _get(api_client, auth.tenant.property.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["property_id"] == str(auth.tenant.property.id)
    assert body["as_of_local_date"] == AS_OF_TEXT
    assert body["period_days"] == 30
    assert body["overview_version"] == "data-overview-v1"
    assert body["currency"] == "EUR"


def test_a_foreign_property_is_the_same_404_as_one_that_does_not_exist(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    authed_tenant(factory, authenticated_as)  # the caller is a member of ANOTHER workspace
    foreign = factory.tenant()
    seed_run(db_session, foreign, nights=uniform_nights(AS_OF, rooms=20, capacity=40))

    foreign_response = _get(api_client, foreign.property.id)
    missing_response = _get(api_client, uuid4())

    assert_error(foreign_response, status_code=404, code="PROPERTY_NOT_FOUND")
    assert_error(missing_response, status_code=404, code="PROPERTY_NOT_FOUND")
    # identical apart from the request id: a caller cannot tell which ids exist
    assert (
        foreign_response.json()["error"]["message"] == missing_response.json()["error"]["message"]
    )


def test_a_foreign_properties_figures_never_appear_in_any_response(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    mine = authed_tenant(factory, authenticated_as)
    seed_run(db_session, mine.tenant, nights=uniform_nights(AS_OF, rooms=11, capacity=40))
    foreign = factory.tenant()
    seed_run(db_session, foreign, nights=uniform_nights(AS_OF, rooms=37, capacity=40))

    body = _get(api_client, mine.tenant.property.id).json()

    assert body["occupancy"]["today"]["room_nights"] == 11
    assert str(foreign.property.id) not in json.dumps(body)


def test_an_archived_property_is_a_404(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    auth.tenant.property.archived_at = datetime.now(UTC)
    auth.tenant.property.is_active = False
    db_session.flush()

    assert_error(
        _get(api_client, auth.tenant.property.id), status_code=404, code="PROPERTY_NOT_FOUND"
    )


# --- query validation -----------------------------------------------------------------------------


def test_an_invalid_as_of_is_a_400(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    auth = authed_tenant(factory, authenticated_as)

    for bad in ("2026-13-40", "yesterday", "2026-08", ""):
        assert_error(
            _get(api_client, auth.tenant.property.id, bad),
            status_code=400,
            code="INVALID_AS_OF_DATE",
        )


def test_a_missing_as_of_is_refused_never_defaulted_to_a_server_clock(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    auth = authed_tenant(factory, authenticated_as)

    response = api_client.get(f"/api/v1/properties/{auth.tenant.property.id}/data/overview")

    assert response.status_code == 422


def test_only_seven_and_thirty_day_periods_are_offered(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    auth = authed_tenant(factory, authenticated_as)

    for bad in (0, 1, 14, 31, -7):
        assert_error(
            _get(api_client, auth.tenant.property.id, period=bad),
            status_code=400,
            code="INVALID_PERIOD",
        )
    assert _get(api_client, auth.tenant.property.id, period="abc").status_code == 422


def test_the_period_selects_the_night_rows(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(db_session, auth.tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40))

    seven = _get(api_client, auth.tenant.property.id, period=7).json()["occupancy"]
    thirty = _get(api_client, auth.tenant.property.id, period=30).json()["occupancy"]
    default = _get(api_client, auth.tenant.property.id).json()["occupancy"]

    assert len(seven["nights"]) == 7 and seven["selected"]["nights_requested"] == 7
    assert len(thirty["nights"]) == 30 and thirty["selected"]["nights_requested"] == 30
    assert default == thirty  # 30 is the default


# --- the contract ---------------------------------------------------------------------------------


def test_the_full_overview_has_every_block_and_no_float(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(
        db_session,
        auth.tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, auth.tenant),
        coverage=full_coverage(),
    )

    body = _get(api_client, auth.tenant.property.id).json()

    assert set(body) == {
        "property_id",
        "as_of_local_date",
        "period_days",
        "currency",
        "analysis",
        "freshness",
        "occupancy",
        "distribution",
        "costs",
        "labor",
        "decisions",
        "overview_version",
    }
    assert _floats_in(body) == []  # every Decimal is a string
    today = body["occupancy"]["today"]
    assert today["occupancy_pct"] == "50.00"  # 20 of 40 rooms, a plain fixed-point string
    assert today["room_revenue"] == "2000.00"
    assert body["analysis"]["feed_state"] == "ACTION_REQUIRED"
    assert [item["domain"] for item in body["analysis"]["domain_states"]] == [
        "REVENUE",
        "DISTRIBUTION",
        "COSTS",
        "LABOR",
    ]
    assert len(body["decisions"]) == 5
    assert body["distribution"]["outcome"] == "DECISION"
    assert body["distribution"]["ota_share_pct"] == "75.00"
    freshness = body["freshness"]["bookings"]
    assert freshness["status"] == "KNOWN"
    assert freshness["last_successful_import_finished_at"].startswith("2026-08-01T07:15:00")


def test_a_night_row_exposes_the_stay_date_figures_and_its_status(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(
        db_session,
        auth.tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, auth.tenant),
        coverage=full_coverage(),
    )

    nights = _get(api_client, auth.tenant.property.id).json()["occupancy"]["nights"]

    first = nights[0]
    assert set(first) == {
        "stay_date",
        "has_data",
        "bookings",
        "rooms_on_books",
        "rooms_available",
        "occupancy_pct",
        "room_revenue",
        "adr",
        "rooms_on_books_7d_ago",
        "rooms_delta_7d",
        "status",
        "decision_id",
    }
    assert first["status"] == "REGULAR"
    flagged = [night for night in nights if night["status"] == "ATTENTION"]
    assert len(flagged) == 2 and all(night["decision_id"] for night in flagged)


def test_not_processed_is_a_designed_response_with_reasons_not_an_error(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    auth = authed_tenant(factory, authenticated_as)

    response = _get(api_client, auth.tenant.property.id)

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["feed_state"] == "NOT_PROCESSED"
    assert body["occupancy"] == {
        "state": "NOT_AVAILABLE",
        "reason": "NO_ANALYSIS",
        "today": None,
        "days_7": None,
        "days_30": None,
        "selected": None,
        "nights": [],
    }
    assert body["distribution"]["reason"] == "NO_ANALYSIS"
    assert {item["state"] for item in body["analysis"]["domain_states"]} == {"UNKNOWN"}


def test_nothing_internal_leaks_into_the_response(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(
        db_session,
        auth.tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, auth.tenant),
        coverage=full_coverage(),
    )

    text = _get(api_client, auth.tenant.property.id).text

    internal_ids = (
        auth.tenant.workspace.id,
        auth.tenant.data_source.id,  # the booking data source
        auth.tenant.import_job.id,
        auth.user.id,
    )
    for internal in internal_ids:
        assert str(internal) not in text
    for forbidden in ("fingerprint", "identity_payload", "source_target_key", "memory_version"):
        assert forbidden not in text


def test_the_endpoint_writes_nothing(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(
        db_session,
        auth.tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, auth.tenant),
        coverage=full_coverage(),
    )
    before = decision_table_counts(db_session)

    _get(api_client, auth.tenant.property.id)
    _get(api_client, auth.tenant.property.id, period=7)

    assert decision_table_counts(db_session) == before


def test_the_endpoint_never_touches_the_language_model_provider(
    app: FastAPI,
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    """Dati is deterministic: a provider that raises on any use must not matter."""

    def exploding_provider() -> None:
        raise AssertionError("Dati must never resolve the language-model provider")

    app.dependency_overrides[get_language_model_provider] = exploding_provider
    auth = authed_tenant(factory, authenticated_as)
    seed_run(db_session, auth.tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40))

    response = _get(api_client, auth.tenant.property.id)

    assert response.status_code == 200

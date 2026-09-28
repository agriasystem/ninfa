"""Gate 18 review items 52-63: the real `POST /ask` endpoint, over HTTP, with a
`DeterministicFakeLanguageModelProvider` wired in via `app.dependency_overrides` (the same seam
`authenticated_as` already uses for `get_current_principal`).
"""

from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.intelligence.priority.types import PriorityContext
from tests.ask_ninfa_support import (
    DeterministicFakeLanguageModelProvider,
    ask_url,
    with_fake_provider,
)
from tests.decision_api_support import assert_error, authed_tenant, decision_table_counts
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _seed_open_decision(db_session: Session, tenant: Tenant) -> UUID:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    db_session.flush()
    return decision_id


def _answered_provider() -> DeterministicFakeLanguageModelProvider:
    return DeterministicFakeLanguageModelProvider(
        answer=LanguageModelAnswer(
            status=ModelAnswerStatus.ANSWERED,
            answer="Il pickup è sotto le attese rispetto a quanto normalmente osservato.",
            grounding_refs=("LATEST_FACTS",),
            limitations=(),
        )
    )


# --- 52: authenticated ask --------------------------------------------------------------------


def test_52_authenticated_ask_returns_an_answered_response(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(_answered_provider())

    response = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché me lo mostri?"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ANSWERED"


# --- 53: unauthenticated -> 401 ----------------------------------------------------------------


def test_53_unauthenticated_ask_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.post(ask_url(tenant.property.id, uuid4()), json={"question": "Perché?"})
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


# --- 54: foreign property -> 404 (never 403) ----------------------------------------------------


def test_54_foreign_property_is_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    foreign_tenant = factory.tenant()  # never a member here
    authed_tenant(factory, authenticated_as)

    response = api_client.post(
        ask_url(foreign_tenant.property.id, uuid4()), json={"question": "Perché?"}
    )
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


# --- 55: foreign/unknown decision -> 404 (never 403) ----------------------------------------------


def test_55_foreign_decision_is_404(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.post(
        ask_url(at.tenant.property.id, uuid4()), json={"question": "Perché?"}
    )
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


def test_55_a_refused_question_still_answers_404_for_an_unknown_decision(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    """Decision-not-found is checked BEFORE the question is even classified - an inaccessible
    decision answers identically (404) regardless of what was asked about it."""
    at = authed_tenant(factory, authenticated_as)
    response = api_client.post(
        ask_url(at.tenant.property.id, uuid4()), json={"question": "Esegui questa azione"}
    )
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


# --- 56: response schema --------------------------------------------------------------------------


def test_56_response_schema_has_exactly_the_expected_fields(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(_answered_provider())

    body = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    ).json()

    assert set(body.keys()) == {"status", "answer", "grounding_refs", "limitations"}
    assert "chat_id" not in body and "thread_id" not in body and "conversation_id" not in body


# --- 57: no raw provider error ever leaks -----------------------------------------------------


def test_57_provider_exception_message_never_leaks_into_the_response(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    secret = "SECRET_PROVIDER_API_KEY_OR_STACK_DETAIL_ABC123"
    with_fake_provider(app)(DeterministicFakeLanguageModelProvider(error=RuntimeError(secret)))

    response = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    )

    assert response.status_code == 200  # UNAVAILABLE is a normal, controlled 200 response
    body = response.json()
    assert body["status"] == "UNAVAILABLE"
    assert secret not in response.text


# --- 58: Cache-Control: no-store --------------------------------------------------------------


def test_58_response_carries_cache_control_no_store(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(_answered_provider())

    response = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    )

    assert response.headers["cache-control"] == "no-store"


# --- 59-63: zero business writes, zero persistence of any kind -----------------------------------


def test_59_60_61_ask_creates_no_decision_observation_or_run(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(_answered_provider())
    before = decision_table_counts(db_session)

    for _ in range(3):
        api_client.post(ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"})

    after = decision_table_counts(db_session)
    assert after == before  # 59: no new Decision row; 60: no new Observation; 61: no new Run


def test_62_recommendation_stays_unpersisted(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """There is no recommendation table to write to at all (Gate 16: zero persistence) - asking
    repeatedly cannot create one, proven the same way `test_recommendation_readonly.py` proves it:
    the Decision Layer's own three tables are the ONLY ones a `sync()` could ever touch, and this
    endpoint never calls `sync()`."""
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(_answered_provider())
    before = decision_table_counts(db_session)

    api_client.post(ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"})

    assert decision_table_counts(db_session) == before


def test_63_no_conversation_or_message_table_exists_to_write_to(db_session: Session) -> None:
    from sqlalchemy import inspect as sa_inspect

    table_names = set(sa_inspect(db_session.get_bind()).get_table_names())
    forbidden_substrings = ("conversation", "message", "chat", "ask_")
    for table_name in table_names:
        lowered = table_name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, table_name


# --- Gate 19.1 (ADR 0026): UTF-8 is a client-display finding, never a product bug --------------


def test_utf8_accented_italian_characters_survive_the_real_http_json_roundtrip(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """The PowerShell live smoke test showed `perchÃ©`/`prioritÃ `/`Ã¨` - this proves that is a
    LOCAL CLIENT/terminal display artefact, never a backend or JSON encoding bug: `TestClient`
    decodes the real HTTP response body exactly like any other real HTTP client would, and the
    accented characters below come back byte-for-byte identical to what the fake provider sent."""
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    accented_answer = (
        "Perché la priorità è alta: l'affidabilità della stima è confermata, è opportuno "
        "verificarla più a fondo."
    )
    with_fake_provider(app)(
        DeterministicFakeLanguageModelProvider(
            answer=LanguageModelAnswer(
                status=ModelAnswerStatus.ANSWERED,
                answer=accented_answer,
                grounding_refs=("LATEST_FACTS",),
                limitations=(),
            )
        )
    )

    response = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché me lo mostri?"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["answer"] == accented_answer

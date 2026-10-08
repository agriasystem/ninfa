"""Mia Home (Home UI V1, ADR 0028): the real `POST /properties/{id}/ask` over HTTP, with a
`DeterministicFakeLanguageModelProvider` wired in through `app.dependency_overrides` - the same seam
the Decision Ask's own tests use. The Decision Ask (`.../decisions/{id}/ask`) is exercised at the
bottom to prove it is untouched.
"""

import json
from collections.abc import Callable
from datetime import date
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.home_instructions import ASK_MIA_HOME_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.home_types import HomeGroundingRef
from app.modules.ai.ask_ninfa.instructions import ASK_NINFA_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.types import MAX_ANSWER_CHARS
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityContext
from tests.ask_home_support import (
    D1,
    STAY,
    answered_provider,
    ask_home_url,
    booking_only_coverage,
    five_triggered_evaluations,
    known_provenance,
    sync_feed,
    utc,
)
from tests.ask_ninfa_support import (
    DeterministicFakeLanguageModelProvider,
    ask_url,
    with_fake_provider,
)
from tests.decision_api_support import assert_error, authed_tenant, decision_table_counts
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory

QUESTION = "Ci sono altri problemi oltre a questo?"


def _body(question: str = QUESTION, as_of: str = "2026-08-01") -> dict[str, str]:
    return {"question": question, "as_of_local_date": as_of}


# --- auth, tenant, explicit parameters ----------------------------------------------------------


def test_unauthenticated_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.post(ask_home_url(tenant.property.id), json=_body())
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


def test_foreign_property_is_404_never_403(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    foreign = factory.tenant()  # the caller is never a member here
    authed_tenant(factory, authenticated_as)
    response = api_client.post(ask_home_url(foreign.property.id), json=_body())
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_unknown_property_is_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    authed_tenant(factory, authenticated_as)
    response = api_client.post(ask_home_url(uuid4()), json=_body())
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_as_of_local_date_is_mandatory(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.post(ask_home_url(at.tenant.property.id), json={"question": QUESTION})
    assert response.status_code == 422


def test_an_invalid_as_of_local_date_is_a_semantic_400(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.post(ask_home_url(at.tenant.property.id), json=_body(as_of="01/08/2026"))
    assert_error(response, status_code=400, code="INVALID_AS_OF_DATE")


def test_a_blank_or_oversized_question_is_a_semantic_400(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    url = ask_home_url(at.tenant.property.id)
    assert_error(
        api_client.post(url, json=_body(question="   ")),
        status_code=400,
        code="INVALID_ASK_QUESTION",
    )
    assert_error(
        api_client.post(url, json=_body(question="x" * 1001)),
        status_code=400,
        code="INVALID_ASK_QUESTION",
    )


# --- statuses -------------------------------------------------------------------------------------


def test_answered_is_200_no_store_with_exactly_the_four_response_fields(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(db_session, at.tenant, five_triggered_evaluations(factory, at.tenant))
    with_fake_provider(app)(answered_provider())

    response = api_client.post(ask_home_url(at.tenant.property.id), json=_body())

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"status", "answer", "grounding_refs", "limitations"}
    assert body["status"] == "ANSWERED"
    assert body["grounding_refs"] == ["DECISIONS"]


def test_insufficient_context_is_passed_through_with_its_answer(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    with_fake_provider(app)(
        answered_provider(
            "L'analisi di oggi non è ancora disponibile.",
            status=ModelAnswerStatus.INSUFFICIENT_CONTEXT,
            limitations=("Nessuna analisi completata per oggi.",),
        )
    )
    response = api_client.post(ask_home_url(at.tenant.property.id), json=_body())
    body = response.json()
    assert body["status"] == "INSUFFICIENT_CONTEXT"
    assert body["limitations"] == ["Nessuna analisi completata per oggi."]


def test_grounding_refs_are_narrowed_to_the_home_vocabulary(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    with_fake_provider(app)(
        answered_provider(refs=("DECISIONS", "LATEST_FACTS", "COVERAGE", "bogus", "COVERAGE"))
    )
    body = api_client.post(ask_home_url(at.tenant.property.id), json=_body()).json()
    # `LATEST_FACTS` is the Decision Ask's vocabulary, never Mia Home's; duplicates collapse.
    assert body["grounding_refs"] == ["DECISIONS", "COVERAGE"]


def test_an_unconfigured_provider_answers_unavailable(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)  # no provider override: the real default
    body = api_client.post(ask_home_url(at.tenant.property.id), json=_body()).json()
    assert body == {
        "status": "UNAVAILABLE",
        "answer": None,
        "grounding_refs": [],
        "limitations": [],
    }


def test_a_provider_error_of_any_kind_fails_closed_to_unavailable(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    url = ask_home_url(at.tenant.property.id)
    for error in (LanguageModelUnavailableError("timeout"), RuntimeError("boom")):
        with_fake_provider(app)(DeterministicFakeLanguageModelProvider(error=error))
        response = api_client.post(url, json=_body())
        assert response.status_code == 200
        assert response.json()["status"] == "UNAVAILABLE"
        assert "boom" not in response.text and "timeout" not in response.text


def test_a_refused_question_never_reaches_the_provider_or_the_feed(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    provider = answered_provider()
    with_fake_provider(app)(provider)

    with patch.object(DecisionMemoryService, "get_feed", side_effect=AssertionError("feed read")):
        response = api_client.post(
            ask_home_url(at.tenant.property.id), json=_body(question="Abbassa il prezzo di tutto")
        )

    body = response.json()
    assert body["status"] == "REFUSED"
    assert body["answer"] is None
    assert body["limitations"] and body["limitations"][0].startswith("Mia ")
    assert provider.requests == []


def test_technical_codes_in_an_answer_fail_closed(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    url = ask_home_url(at.tenant.property.id)
    for leaky in (
        "La decisione REV_PICKUP_LOW è la prima.",
        "Il dato current_rooms_on_books è basso.",
        "Lo stato è ACTION_REQUIRED oggi.",
    ):
        with_fake_provider(app)(answered_provider(leaky))
        assert api_client.post(url, json=_body()).json()["status"] == "UNAVAILABLE", leaky


def test_an_overlong_or_empty_answer_fails_closed_never_truncated(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)
    url = ask_home_url(at.tenant.property.id)
    for bad in ("a" * (MAX_ANSWER_CHARS + 1), "   "):
        with_fake_provider(app)(answered_provider(bad))
        assert api_client.post(url, json=_body()).json()["status"] == "UNAVAILABLE"


# --- what the provider is actually sent ----------------------------------------


def test_the_provider_gets_three_separate_fields_and_the_home_vocabulary(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        five_triggered_evaluations(factory, at.tenant),
        coverage=booking_only_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),
    )
    provider = answered_provider()
    with_fake_provider(app)(provider)

    api_client.post(
        ask_home_url(at.tenant.property.id), json=_body("  Quali dati ha usato NINFA oggi?  ")
    )

    [request] = provider.requests
    assert request.system_instructions == ASK_MIA_HOME_SYSTEM_INSTRUCTIONS
    assert request.question == "Quali dati ha usato NINFA oggi?"  # trimmed, nothing else
    assert request.max_answer_chars == MAX_ANSWER_CHARS
    assert request.grounding_ref_values == tuple(ref.value for ref in HomeGroundingRef)
    context = json.loads(request.context)
    assert context["data di riferimento"] == "2026-08-01"
    assert context["numero di decisioni che richiedono attenzione"] == 5
    # the property-level context never contains the question, the instructions or any id
    assert request.question not in request.context
    assert str(at.tenant.property.id) not in request.context
    assert "istruzioni" not in request.context.lower()


# --- tenant isolation + explicit as_of ------------------------------------------------------------


def test_the_context_only_ever_contains_the_callers_own_property_feed(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    foreign = factory.tenant()
    sync_feed(db_session, foreign, five_triggered_evaluations(factory, foreign))  # a busy feed
    provider = answered_provider()
    with_fake_provider(app)(provider)

    api_client.post(ask_home_url(at.tenant.property.id), json=_body())

    context = json.loads(provider.last_request.context)
    assert context["numero di decisioni che richiedono attenzione"] == 0
    assert context["decisioni in ordine di priorità"] == []


def test_the_explicit_as_of_selects_the_feed_exactly_like_the_decision_feed(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(db_session, at.tenant, five_triggered_evaluations(factory, at.tenant), as_of=D1)
    provider = answered_provider()
    with_fake_provider(app)(provider)
    url = ask_home_url(at.tenant.property.id)

    api_client.post(url, json=_body(as_of="2026-08-01"))
    api_client.post(url, json=_body(as_of="2026-08-02"))  # no run for this day

    with_run, without_run = (json.loads(r.context) for r in provider.requests)
    assert with_run["numero di decisioni che richiedono attenzione"] == 5
    assert without_run["numero di decisioni che richiedono attenzione"] == 0
    assert without_run["stato dell'analisi"] == "L'analisi di oggi non è ancora disponibile"
    assert without_run["copertura dell'analisi"] is None
    assert without_run["dati usati dall'analisi"] is None
    assert without_run["data dell'ultima analisi completata"] == "2026-08-01"


def test_the_property_timezone_drives_the_import_time(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    at.tenant.property.timezone = "America/New_York"  # UTC-4 in August
    db_session.flush()
    sync_feed(
        db_session,
        at.tenant,
        five_triggered_evaluations(factory, at.tenant)[:1],
        provenance=known_provenance(utc(2026, 8, 1, 13, 31)),
    )
    provider = answered_provider()
    with_fake_provider(app)(provider)

    api_client.post(ask_home_url(at.tenant.property.id), json=_body())

    imported = json.loads(provider.last_request.context)["dati usati dall'analisi"]
    assert imported["ultimo import prenotazioni"]["ora locale della struttura"] == "09:31"


# --- read-only ------------------------------------------------------------------------------------


def test_asking_writes_nothing(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(db_session, at.tenant, five_triggered_evaluations(factory, at.tenant))
    with_fake_provider(app)(answered_provider())
    before = decision_table_counts(db_session)

    api_client.post(ask_home_url(at.tenant.property.id), json=_body())

    assert decision_table_counts(db_session) == before


# --- the Decision Ask is untouched ----------------------------------------------------------------


def test_the_decision_ask_still_uses_its_own_instructions_and_vocabulary(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    evaluation = revenue_evaluation(
        workspace_id=at.tenant.workspace.id,
        property_id=at.tenant.property.id,
        data_source_id=at.tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(at.tenant.workspace.id, at.tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(at.tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    db_session.flush()
    provider = DeterministicFakeLanguageModelProvider(
        answer=LanguageModelAnswer(
            status=ModelAnswerStatus.ANSWERED,
            answer="Il pickup è sotto le attese.",
            grounding_refs=("LATEST_FACTS", "DECISIONS"),
            limitations=(),
        )
    )
    with_fake_provider(app)(provider)

    response = api_client.post(
        ask_url(at.tenant.property.id, decision_id), json={"question": "Perché me lo mostri?"}
    )

    assert response.status_code == 200
    assert response.json()["grounding_refs"] == ["LATEST_FACTS"]  # `DECISIONS` is Home-only
    assert provider.last_request.system_instructions == ASK_NINFA_SYSTEM_INSTRUCTIONS
    assert provider.last_request.grounding_ref_values is None
    assert date(2026, 8, 1).isoformat() in provider.last_request.context

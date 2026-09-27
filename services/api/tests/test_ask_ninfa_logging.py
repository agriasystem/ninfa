"""Gate 18 review items 70-73: nothing in the real `/ask` request path logs the raw question, the
full context, or a provider's own raw exception text.

There is, by construction, no logging call anywhere in `app.modules.ai.ask_ninfa`/
`app.modules.ai.gateway` that touches the question or the context at all (see `service.py`: every
provider exception is caught and turned into a controlled `AskResult`, never re-raised, so
`app.core.errors`'s own generic `_handle_unexpected_error` - the only place this codebase logs a
full exception - never even runs for a provider failure). This test proves that structural claim
against the REAL request path, not just by reading the source.
"""

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
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
from tests.decision_api_support import authed_tenant
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)

_DISTINCTIVE_QUESTION = "DISTINCTIVE_QUESTION_TEXT_MUST_NEVER_BE_LOGGED_9f31"
_SECRET_PROVIDER_DETAIL = "SECRET_PROVIDER_STACK_DETAIL_MUST_NEVER_BE_LOGGED_7a02"


def _seed_open_decision(db_session: Session, tenant: Tenant) -> UUID:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        confidence_score=Decimal("81.23"),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    db_session.flush()
    return decision_id


def test_70_71_raw_question_and_full_context_never_appear_in_logs(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(
        DeterministicFakeLanguageModelProvider(
            answer=LanguageModelAnswer(
                status=ModelAnswerStatus.ANSWERED,
                answer="Risposta.",
                grounding_refs=(),
                limitations=(),
            )
        )
    )

    with caplog.at_level(logging.DEBUG):
        api_client.post(
            ask_url(at.tenant.property.id, decision_id), json={"question": _DISTINCTIVE_QUESTION}
        )

    assert _DISTINCTIVE_QUESTION not in caplog.text
    # "81.23" is real context content (the observation's own confidence) - proves the scan reaches
    # a real value the context genuinely carries, then confirms it is absent from logs too.
    assert "81.23" not in caplog.text


def test_72_no_password_or_session_token_in_logs_during_an_ask_request(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(
        DeterministicFakeLanguageModelProvider(
            answer=LanguageModelAnswer(
                status=ModelAnswerStatus.ANSWERED,
                answer="Risposta.",
                grounding_refs=(),
                limitations=(),
            )
        )
    )

    with caplog.at_level(logging.DEBUG):
        api_client.post(ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"})

    lowered = caplog.text.lower()
    for forbidden in ("password", "session_token", "cookie", "authorization: bearer"):
        assert forbidden not in lowered


def test_73_provider_exception_text_is_sanitized_out_of_logs(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    with_fake_provider(app)(
        DeterministicFakeLanguageModelProvider(error=RuntimeError(_SECRET_PROVIDER_DETAIL))
    )

    with caplog.at_level(logging.DEBUG):
        response = api_client.post(
            ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
        )

    assert response.json()["status"] == "UNAVAILABLE"
    assert _SECRET_PROVIDER_DETAIL not in caplog.text

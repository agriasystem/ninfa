"""Gate 18 review items 74-77: bounded, non-linear query count and exactly one provider call.

Reuses `test_decision_api_performance.py`/`test_recommendation_performance.py`'s own
`statements_of()`/`_select_count()` technique unmodified.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
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


@contextmanager
def statements_of(session: Session) -> Iterator[list[str]]:
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[str] = []

    def record(*args: Any) -> None:
        captured.append(str(args[2]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _select_count(statements: list[str]) -> int:
    return sum(1 for sql in statements if sql.strip().upper().startswith("SELECT"))


def _seed_decision_with_history(db_session: Session, tenant: Tenant, days: int) -> UUID:
    decision_id: UUID | None = None
    for offset in range(days):
        evaluation = revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY,
            snapshot_local_date=D1 + timedelta(days=offset),
            confidence_score=Decimal(f"{50 + offset}.00"),
        )
        as_of = D1 + timedelta(days=offset)
        context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
        outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
        [decision_id] = outcome.result.touched_decision_ids
    assert decision_id is not None
    db_session.flush()
    return decision_id


def _answered_provider() -> DeterministicFakeLanguageModelProvider:
    return DeterministicFakeLanguageModelProvider(
        answer=LanguageModelAnswer(
            status=ModelAnswerStatus.ANSWERED, answer="Risposta.", grounding_refs=(), limitations=()
        )
    )


# --- 74, 76: bounded, non-linear query count --------------------------------------------------


def test_74_76_query_count_is_bounded_and_not_linear_in_observation_count(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    small_decision_id = _seed_decision_with_history(db_session, at.tenant, days=2)
    with_fake_provider(app)(_answered_provider())

    with statements_of(db_session) as small_statements:
        api_client.post(
            ask_url(at.tenant.property.id, small_decision_id), json={"question": "Perché?"}
        )
    small_selects = _select_count(small_statements)

    at2 = authed_tenant(factory, authenticated_as)
    large_decision_id = _seed_decision_with_history(db_session, at2.tenant, days=15)
    with_fake_provider(app)(_answered_provider())

    with statements_of(db_session) as large_statements:
        api_client.post(
            ask_url(at2.tenant.property.id, large_decision_id), json={"question": "Perché?"}
        )
    large_selects = _select_count(large_statements)

    assert small_selects <= 5
    assert large_selects <= 5
    # 15 real observations, but `history` is bounded (max 10) via ONE keyset query - never one
    # SELECT per observation.
    assert large_selects <= small_selects + 1


# --- 75: history is genuinely bounded to MAX_HISTORY_OBSERVATIONS ---------------------------------


def test_75_history_sent_to_the_provider_is_bounded_to_ten(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_decision_with_history(db_session, at.tenant, days=15)
    provider = _answered_provider()
    with_fake_provider(app)(provider)

    api_client.post(ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"})

    sent_context = json.loads(provider.last_request.context)
    assert len(sent_context["history"]) == 10


# --- 77: exactly one provider call per ask --------------------------------------------------------


def test_77_exactly_one_provider_call_per_ask(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_decision_with_history(db_session, at.tenant, days=1)
    provider = _answered_provider()
    with_fake_provider(app)(provider)

    api_client.post(ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"})

    assert len(provider.requests) == 1

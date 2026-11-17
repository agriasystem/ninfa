"""Mia's conversation store: NINFA-owned, isolated by construction, bounded in size and in time.

The id of a conversation is a handle, not a credential: it is matched together with the workspace,
the property AND the user the route resolved, so another person's conversation, another property's
and another workspace's are all the same as a missing one. What the model is given of a long
conversation is the recent messages plus a deterministic summary of the rest - built from what was
asked and which tools were used, never from an answer or a figure."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.mia.conversation import (
    MAX_CONVERSATIONS,
    MAX_MODEL_HISTORY_CHARS,
    MAX_MODEL_HISTORY_MESSAGES,
    MAX_STORED_MESSAGES,
    RETENTION,
    MiaConversationService,
    parse_messages,
    summary_of,
)
from app.modules.ai.mia.models import TITLE_MAX_LENGTH, MiaConversation
from app.modules.ai.mia.types import MiaTurnResult, ToolTrace
from app.modules.tenancy.models import MembershipRole
from tests.support import BookingFactory, Tenant

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _result(
    answer: str | None = "Risposta.",
    *,
    status: AskStatus = AskStatus.ANSWERED,
    tools: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
) -> MiaTurnResult:
    trace = tuple(ToolTrace(name, {"window": 7}, (f"dati:{name}",)) for name in tools) + tuple(
        ToolTrace(name, {}, (), failed=True) for name in failed
    )
    return MiaTurnResult(status, answer, (), ("Un limite.",), trace=trace)


def _service(db_session: Session, tenant: Tenant, clock: Clock | None = None) -> Any:
    return MiaConversationService(
        db_session, TenantContext(tenant.workspace.id), clock=clock or Clock()
    )


def _member(factory: BookingFactory, tenant: Tenant) -> Any:
    user = factory.user()
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    return user


def _owner_of(factory: BookingFactory, tenant: Tenant) -> Any:
    return _member(factory, tenant)


# --- isolation --------------------------------------------------------------------------------


def test_a_conversation_belongs_to_workspace_property_and_user_at_once(
    factory: BookingFactory, db_session: Session
) -> None:
    mine, other = factory.tenant(), factory.tenant()
    me = _owner_of(factory, mine)
    colleague = _member(factory, mine)  # same workspace, same property, another person
    stranger = _member(factory, other)
    sibling = factory.property(mine.workspace)  # same workspace, another property
    service = _service(db_session, mine)
    conversation = service.create(mine.property.id, me.id, "Com'è venerdì?")

    assert service.get_owned(conversation.id, mine.property.id, me.id) is not None
    # another person of the same workspace and property
    assert service.get_owned(conversation.id, mine.property.id, colleague.id) is None
    # another property of the same workspace
    assert service.get_owned(conversation.id, sibling.id, me.id) is None
    # another workspace, asking with everything of its own
    foreign = _service(db_session, other)
    assert foreign.get_owned(conversation.id, other.property.id, stranger.id) is None
    assert foreign.get_owned(conversation.id, mine.property.id, me.id) is None
    # an id nobody has
    assert service.get_owned(uuid4(), mine.property.id, me.id) is None


def test_the_list_shows_only_my_conversations_about_this_property(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me, colleague = _member(factory, tenant), _member(factory, tenant)
    sibling = factory.property(tenant.workspace)
    service = _service(db_session, tenant)
    mine = service.create(tenant.property.id, me.id, "mia")
    service.create(tenant.property.id, colleague.id, "del collega")
    service.create(sibling.id, me.id, "altra struttura")

    listed = service.list_recent(tenant.property.id, me.id)

    assert [row.id for row in listed] == [mine.id]


def test_revoking_a_membership_deletes_the_persons_conversations(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me, colleague = _member(factory, tenant), _member(factory, tenant)
    service = _service(db_session, tenant)
    service.create(tenant.property.id, me.id, "mia")
    kept = service.create(tenant.property.id, colleague.id, "del collega")

    db_session.execute(
        text("DELETE FROM workspace_memberships WHERE workspace_id = :w AND user_id = :u"),
        {"w": tenant.workspace.id, "u": me.id},
    )
    db_session.expire_all()

    rows = db_session.scalars(
        select(MiaConversation).where(MiaConversation.workspace_id == tenant.workspace.id)
    ).all()
    assert [row.id for row in rows] == [kept.id]


# --- recording --------------------------------------------------------------------------------


def test_an_exchange_is_stored_with_the_trace_of_the_tools_that_really_ran(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "Com'è venerdì?")

    service.record_exchange(
        conversation,
        question="Com'è venerdì?",
        result=_result(tools=("get_occupancy_revenue",), failed=("execute_sql",)),
    )

    messages = service.messages_of(conversation)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "Com'è venerdì?"
    assert messages[1].status == "ANSWERED" and messages[1].limitations == ("Un limite.",)
    assert [dict(t)["strumento"] for t in messages[1].tools] == ["get_occupancy_revenue"]
    assert dict(messages[1].tools[0])["argomenti"] == {"window": 7}


@pytest.mark.parametrize(
    "result",
    [
        _result(None, status=AskStatus.UNAVAILABLE),
        _result(None, status=AskStatus.REFUSED),
    ],
)
def test_a_turn_that_was_not_answered_leaves_no_trace(
    factory: BookingFactory, db_session: Session, result: MiaTurnResult
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "domanda")

    service.record_exchange(conversation, question="domanda", result=result)

    assert service.messages_of(conversation) == []


def test_an_insufficient_context_turn_is_a_complete_exchange(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "RevPAR?")

    service.record_exchange(
        conversation,
        question="RevPAR?",
        result=_result("NINFA non lo calcola.", status=AskStatus.INSUFFICIENT_CONTEXT),
    )

    assert len(service.messages_of(conversation)) == 2


def test_a_title_is_one_short_line(factory: BookingFactory, db_session: Session) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)

    row = _service(db_session, tenant).create(
        tenant.property.id, me.id, "riga uno\n   riga due " + "x" * 300
    )

    assert "\n" not in row.title and len(row.title) <= TITLE_MAX_LENGTH
    assert row.title.startswith("riga uno riga due")


def test_a_corrupt_stored_array_yields_what_is_valid_and_nothing_else() -> None:
    raw = [
        "not a dict",
        {"role": "system", "content": "x", "at": NOW.isoformat()},
        {"role": "assistant", "content": "starts with an answer", "at": NOW.isoformat()},
        {"role": "user", "content": "valid", "at": NOW.isoformat()},
        {"role": "user", "content": "", "at": NOW.isoformat()},
        {"role": "user", "content": "bad date", "at": "yesterday-ish"},
        {"role": "assistant", "content": "reply", "at": NOW.isoformat(), "tools": ["x", {"a": 1}]},
    ]

    parsed = parse_messages(raw)

    assert [m.content for m in parsed] == ["valid", "reply"]
    assert parse_messages({"not": "a list"}) == []
    assert parse_messages(None) == []


# --- what the model sees ----------------------------------------------------------------------


def _filled(service: Any, conversation: MiaConversation, pairs: int, *, tool: str = "t") -> None:
    for index in range(pairs):
        service.record_exchange(
            conversation,
            question=f"domanda numero {index}",
            result=_result(f"risposta numero {index} con 99{index} camere.", tools=(tool,)),
        )


def test_a_short_conversation_is_sent_whole_with_no_summary(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "x")
    _filled(service, conversation, 3)

    context = service.model_context(conversation)

    assert context.summary == ""
    assert [turn.role for turn in context.history] == ["user", "assistant"] * 3


def test_a_missing_conversation_is_no_context(factory: BookingFactory, db_session: Session) -> None:
    tenant = factory.tenant()

    context = _service(db_session, tenant).model_context(None)

    assert context.summary == "" and context.history == ()


def test_a_long_conversation_sends_the_recent_messages_and_summarises_the_rest(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "x")
    _filled(service, conversation, 12, tool="get_occupancy_revenue")

    context = service.model_context(conversation)

    assert len(context.history) <= MAX_MODEL_HISTORY_MESSAGES
    assert context.history[0].role == "user"  # always starts at a person's message
    assert context.history[-1].content.startswith("risposta numero 11")
    # the old part is a summary of QUESTIONS and the tools used, never an answer or a figure
    assert "domanda numero 0" in context.summary
    assert "get_occupancy_revenue" in context.summary
    assert "NON sono fatti sui dati" in context.summary
    assert "risposta numero" not in context.summary and "990" not in context.summary
    assert "domanda numero 11" not in context.summary  # that one is verbatim in the history


def test_the_recent_window_is_bounded_in_characters_too(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "x")
    for index in range(6):
        service.record_exchange(
            conversation,
            question=f"domanda {index}",
            result=_result("lunga " * 400),  # 2400 characters each
        )

    context = service.model_context(conversation)

    assert sum(len(turn.content) for turn in context.history) <= MAX_MODEL_HISTORY_CHARS + 2400
    assert context.history[0].role == "user"
    assert "domanda 0" in context.summary


def test_storage_is_bounded_and_the_oldest_exchange_ages_into_the_digest(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "x")

    # two exchanges age out: the digest holds them and the summary still fits its 14 lines
    _filled(service, conversation, MAX_STORED_MESSAGES // 2 + 2, tool="get_cost_metrics")

    stored = service.messages_of(conversation)
    assert len(stored) <= MAX_STORED_MESSAGES
    assert stored[0].role == "user"
    assert "domanda numero 0" not in [m.content for m in stored]
    assert "domanda numero 0" in conversation.digest
    assert "get_cost_metrics" in conversation.digest
    assert "risposta numero" not in conversation.digest
    # the summary keeps the most recent earlier questions (bounded), the digest what left storage
    summary = service.model_context(conversation).summary
    assert "domanda numero 26" in summary and "domanda numero 0" not in summary


def test_the_summary_is_bounded_whatever_the_conversation(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    conversation = service.create(tenant.property.id, me.id, "x")

    _filled(service, conversation, 80)

    summary = service.model_context(conversation).summary
    assert len(summary) <= 2400
    assert summary.count("\n- ") <= 14


def test_a_summary_of_nothing_is_empty() -> None:
    assert summary_of("", []) == ""


# --- bounds in number and in time -------------------------------------------------------------


def test_the_least_recent_conversation_goes_when_a_new_one_starts_past_the_limit(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me, colleague = _member(factory, tenant), _member(factory, tenant)
    clock = Clock()
    service = _service(db_session, tenant, clock)
    first = service.create(tenant.property.id, me.id, "la più vecchia")
    for index in range(MAX_CONVERSATIONS - 1):
        clock.advance(timedelta(minutes=1))
        service.create(tenant.property.id, me.id, f"c{index}")
    colleagues = service.create(tenant.property.id, colleague.id, "del collega")
    assert service.get_owned(first.id, tenant.property.id, me.id) is not None

    clock.advance(timedelta(minutes=1))
    service.create(tenant.property.id, me.id, "una in più")

    assert service.get_owned(first.id, tenant.property.id, me.id) is None
    assert len(service.list_recent(tenant.property.id, me.id, limit=100)) <= 10
    # housekeeping touches its owner only
    assert service.get_owned(colleagues.id, tenant.property.id, colleague.id) is not None


def test_a_conversation_past_its_retention_is_invisible_and_is_purged_for_its_owner(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    clock = Clock()
    service = _service(db_session, tenant, clock)
    old = service.create(tenant.property.id, me.id, "vecchia")

    clock.advance(RETENTION + timedelta(days=1))

    assert service.get_owned(old.id, tenant.property.id, me.id) is None
    assert service.list_recent(tenant.property.id, me.id) == []
    service.create(tenant.property.id, me.id, "nuova")
    db_session.expire_all()
    assert db_session.get(MiaConversation, old.id) is None


def test_activity_keeps_a_conversation_alive(factory: BookingFactory, db_session: Session) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    clock = Clock()
    service = _service(db_session, tenant, clock)
    conversation = service.create(tenant.property.id, me.id, "viva")

    clock.advance(RETENTION - timedelta(days=1))
    service.record_exchange(conversation, question="ancora", result=_result())
    clock.advance(RETENTION - timedelta(days=1))

    assert service.get_owned(conversation.id, tenant.property.id, me.id) is not None


def test_delete_removes_only_that_conversation(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    me = _member(factory, tenant)
    service = _service(db_session, tenant)
    gone = service.create(tenant.property.id, me.id, "da cancellare")
    kept = service.create(tenant.property.id, me.id, "da tenere")

    service.delete(gone)

    assert service.get_owned(gone.id, tenant.property.id, me.id) is None
    assert service.get_owned(kept.id, tenant.property.id, me.id) is not None


def test_the_database_refuses_a_conversation_of_a_user_who_is_not_a_member(
    factory: BookingFactory, db_session: Session, rejects: Any
) -> None:
    tenant = factory.tenant()
    outsider = factory.user()  # no membership on this workspace

    with rejects(
        psycopg.errors.ForeignKeyViolation,
        "fk_mia_conversations_workspace_id_workspace_memberships",
    ):
        db_session.add(
            MiaConversation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                user_id=outsider.id,
                title="x",
                digest="",
                messages=[],
                last_message_at=NOW,
            )
        )
        db_session.flush()

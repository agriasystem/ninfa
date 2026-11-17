"""The conversation store of Mia: NINFA-owned, bounded, bound to ONE user and ONE property.

    MiaConversationService(session, tenant).create / get_owned / list_recent / delete
    MiaConversationService(session, tenant).model_context(conversation)   -> what the model may see
    MiaConversationService(session, tenant).record_exchange(conversation, question, result)

What it keeps (see `models.MiaConversation` for why it exists): the text of the conversation - each
user message and each answer Mia gave - plus, for every answer, the server-written TRACE of which
tools it used with which RESOLVED arguments. The trace is what lets "e sabato?" mean "the same thing
about the Saturday we were discussing" without the model re-deriving it from prose. What it never
keeps: an observation, a booking row, a prompt, anything a tool read, a chain of thought.

CONTEXT WINDOW (never "send the whole history for ever"):

* the model sees the RECENT messages verbatim (`MAX_MODEL_HISTORY_MESSAGES` messages, at most
  `MAX_MODEL_HISTORY_CHARS` characters, newest first, always starting at a person's message);
* everything older - the stored messages that fell out of that window AND the ones that aged out of
  storage - reaches the model only as a compact, DETERMINISTIC summary: one short line per earlier
  question with the NAMES of the tools it used (`summary_of`). It is built from what the person
  asked and which areas were consulted, never from an answer or a figure, and it is headed by a
  sentence saying it is not a fact about the data. A model-written summary could "remember"
  something the system never verified; this one cannot.

The bounds, all enforced here (and the message count also by a database CHECK):

* `MAX_STORED_MESSAGES` messages per conversation (the oldest pair ages out first, into the digest);
* `MAX_CONVERSATIONS` conversations per person and property (the least recent is deleted when a new
  one starts) and `RETENTION` of inactivity before a conversation is deleted;
* `Cache-Control: no-store` at the route: a conversation is never cached or replayed.

Isolation by construction: every query carries the workspace of the `TenantContext` AND the property
and user the route resolved from the authenticated request. The conversation id is a handle, not a
credential: `get_owned` matches ALL FOUR, so another person's conversation, another property's and
another workspace's are indistinguishable from a missing one.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import Clock, utcnow
from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.tool_protocol import ToolHistoryTurn
from app.modules.ai.mia.models import TITLE_MAX_LENGTH, MiaConversation
from app.modules.ai.mia.types import MiaTurnResult, ToolTrace

logger = logging.getLogger(__name__)

MAX_STORED_MESSAGES = 60
MAX_MODEL_HISTORY_MESSAGES = 10
MAX_MODEL_HISTORY_CHARS = 8000
MAX_CONVERSATIONS = 20
RETENTION = timedelta(days=60)
MAX_TRACES_PER_MESSAGE = 8
MAX_REFS_PER_TRACE = 8
MAX_SUMMARY_LINES = 14
MAX_SUMMARY_CHARS = 2400
SUMMARY_QUESTION_CHARS = 120
LIST_LIMIT = 10

_RECORDABLE = frozenset({AskStatus.ANSWERED, AskStatus.INSUFFICIENT_CONTEXT})
_SUMMARY_HEADER = (
    "Domande già fatte in questa conversazione (NON sono fatti sui dati: servono solo a capire i "
    "riferimenti; i dati si rileggono sempre con gli strumenti):"
)


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """One message as the UI shows it back after a refresh. `status`/`limitations` exist on an
    assistant message only (the UI renders a restored answer exactly like a fresh one)."""

    role: str
    content: str
    at: datetime
    status: str | None = None
    limitations: tuple[str, ...] = ()
    tools: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ModelContext:
    """What the model may know of the conversation so far: the summary of the old part and the
    recent messages verbatim."""

    summary: str
    history: tuple[ToolHistoryTurn, ...]


def traces_to_json(trace: Sequence[ToolTrace]) -> list[dict[str, Any]]:
    """The trace of an answer as stored: only tools that really ran (a refused or failed call is not
    a topic of the conversation), bounded, with the RESOLVED arguments the server validated."""
    entries: list[dict[str, Any]] = []
    for item in trace:
        if item.failed:
            continue
        entries.append(
            {
                "strumento": item.tool,
                "argomenti": dict(item.arguments),
                "riferimenti": list(item.refs)[:MAX_REFS_PER_TRACE],
            }
        )
        if len(entries) >= MAX_TRACES_PER_MESSAGE:
            break
    return entries


def parse_messages(raw: object) -> list[StoredMessage]:
    """Defensive: a stored array that is not what this service wrote (a manual edit, an older
    shape) yields what is valid and nothing else - never an exception, never a guess."""
    if not isinstance(raw, list):
        return []
    parsed: list[StoredMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role, content, at = item.get("role"), item.get("content"), item.get("at")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content:
            continue
        try:
            when = datetime.fromisoformat(str(at))
        except ValueError:
            continue
        limitations = item.get("limitations")
        tools = item.get("tools")
        parsed.append(
            StoredMessage(
                role=role,
                content=content,
                at=when,
                status=item.get("status") if isinstance(item.get("status"), str) else None,
                limitations=tuple(x for x in limitations if isinstance(x, str))
                if isinstance(limitations, list)
                else (),
                tools=tuple(t for t in tools if isinstance(t, dict))
                if isinstance(tools, list)
                else (),
            )
        )
    while parsed and parsed[0].role != "user":
        parsed.pop(0)
    return parsed


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _summary_line(question: StoredMessage, answer: StoredMessage | None) -> str:
    names: list[str] = []
    for tool in () if answer is None else answer.tools:
        name = tool.get("strumento")
        if isinstance(name, str) and name not in names:
            names.append(name)
    consulted = f" [strumenti: {', '.join(names)}]" if names else ""
    return f"- «{_one_line(question.content, SUMMARY_QUESTION_CHARS)}»{consulted}"


def summary_of(digest: str, older: Sequence[StoredMessage]) -> str:
    """The deterministic summary of the part of the conversation the model no longer sees verbatim:
    the digest of what aged out of storage, then one line per earlier question still stored."""
    lines = [line for line in digest.splitlines() if line.strip()]
    index = 0
    while index < len(older):
        message = older[index]
        if message.role == "user":
            following = older[index + 1] if index + 1 < len(older) else None
            reply = following if following is not None and following.role == "assistant" else None
            lines.append(_summary_line(message, reply))
        index += 1
    if not lines:
        return ""
    lines = lines[-MAX_SUMMARY_LINES:]
    text = "\n".join([_SUMMARY_HEADER, *lines])
    return text[-MAX_SUMMARY_CHARS:] if len(text) > MAX_SUMMARY_CHARS else text


def _title_of(question: str) -> str:
    return _one_line(question, TITLE_MAX_LENGTH)


class MiaConversationService:
    def __init__(self, session: Session, tenant: TenantContext, *, clock: Clock = utcnow) -> None:
        self._session = session
        self._tenant = tenant
        self._clock = clock

    # --- reading --------------------------------------------------------------------------------

    def get_owned(
        self, conversation_id: UUID, property_id: UUID, user_id: UUID
    ) -> MiaConversation | None:
        """The conversation, ONLY if it is this workspace's, this property's and this user's - and
        not past its retention. Anything else is `None`, the same as a missing one."""
        row = self._session.scalar(
            select(MiaConversation).where(
                MiaConversation.id == conversation_id,
                MiaConversation.workspace_id == self._tenant.workspace_id,
                MiaConversation.property_id == property_id,
                MiaConversation.user_id == user_id,
            )
        )
        if row is None or self._clock() - row.last_message_at > RETENTION:
            return None
        return row

    def list_recent(
        self, property_id: UUID, user_id: UUID, *, limit: int = LIST_LIMIT
    ) -> list[MiaConversation]:
        cutoff = self._clock() - RETENTION
        return list(
            self._session.scalars(
                select(MiaConversation)
                .where(
                    MiaConversation.workspace_id == self._tenant.workspace_id,
                    MiaConversation.property_id == property_id,
                    MiaConversation.user_id == user_id,
                    MiaConversation.last_message_at >= cutoff,
                )
                .order_by(MiaConversation.last_message_at.desc(), MiaConversation.id)
                .limit(min(limit, LIST_LIMIT))
            )
        )

    def messages_of(self, conversation: MiaConversation) -> list[StoredMessage]:
        return parse_messages(conversation.messages)

    def model_context(self, conversation: MiaConversation | None) -> ModelContext:
        """The summary of the old part and the recent messages, bounded in count and characters,
        starting at a person's message."""
        if conversation is None:
            return ModelContext("", ())
        stored = parse_messages(conversation.messages)
        recent: list[StoredMessage] = []
        used = 0
        for message in reversed(stored):
            if len(recent) >= MAX_MODEL_HISTORY_MESSAGES:
                break
            if used + len(message.content) > MAX_MODEL_HISTORY_CHARS and recent:
                break
            recent.append(message)
            used += len(message.content)
        recent.reverse()
        while recent and recent[0].role != "user":
            recent.pop(0)
        older = stored[: len(stored) - len(recent)]
        history = tuple(
            ToolHistoryTurn(role=m.role, content=m.content, tools_used=m.tools) for m in recent
        )
        return ModelContext(summary_of(conversation.digest, older), history)

    # --- writing --------------------------------------------------------------------------------

    def create(self, property_id: UUID, user_id: UUID, first_question: str) -> MiaConversation:
        """A new, empty conversation. Housekeeping happens here, for its owner only: whatever is
        past the retention, and the least recent beyond `MAX_CONVERSATIONS`, is deleted."""
        self._purge(property_id, user_id)
        now = self._clock()
        row = MiaConversation(
            workspace_id=self._tenant.workspace_id,
            property_id=property_id,
            user_id=user_id,
            title=_title_of(first_question),
            digest="",
            messages=[],
            last_message_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def record_exchange(
        self, conversation: MiaConversation, *, question: str, result: MiaTurnResult
    ) -> None:
        """Appends one complete exchange (only an answered or insufficient-context turn is
        recordable: a refused, unavailable or failed turn leaves no trace)."""
        if result.status not in _RECORDABLE or result.answer is None:
            return
        now = self._clock()
        stored = list(conversation.messages) if isinstance(conversation.messages, list) else []
        stored.append({"role": "user", "content": question, "at": now.isoformat()})
        stored.append(
            {
                "role": "assistant",
                "content": result.answer,
                "at": now.isoformat(),
                "status": result.status.value,
                "limitations": list(result.limitations),
                "tools": traces_to_json(result.trace),
            }
        )
        digest = conversation.digest
        while len(stored) > MAX_STORED_MESSAGES:
            aged = parse_messages(stored[:2])
            if aged:
                digest = _digest_with(digest, aged)
            del stored[:2]
        # `messages` is reassigned (not mutated) so the ORM sees the JSONB change
        conversation.messages = stored
        conversation.digest = digest
        conversation.last_message_at = now
        self._session.flush()

    def delete(self, conversation: MiaConversation) -> None:
        self._session.delete(conversation)
        self._session.flush()

    def _purge(self, property_id: UUID, user_id: UUID) -> None:
        owner = (
            MiaConversation.workspace_id == self._tenant.workspace_id,
            MiaConversation.property_id == property_id,
            MiaConversation.user_id == user_id,
        )
        self._session.execute(
            delete(MiaConversation).where(
                *owner, MiaConversation.last_message_at < self._clock() - RETENTION
            )
        )
        keep = list(
            self._session.scalars(
                select(MiaConversation.id)
                .where(*owner)
                .order_by(MiaConversation.last_message_at.desc(), MiaConversation.id)
                .limit(MAX_CONVERSATIONS - 1)
            )
        )
        self._session.execute(
            delete(MiaConversation).where(*owner, MiaConversation.id.not_in(keep))
        )


def _digest_with(digest: str, aged: Sequence[StoredMessage]) -> str:
    question = next((m for m in aged if m.role == "user"), None)
    if question is None:
        return digest
    reply = next((m for m in aged if m.role == "assistant"), None)
    lines = [line for line in digest.splitlines() if line.strip()]
    lines.append(_summary_line(question, reply))
    return "\n".join(lines[-MAX_SUMMARY_LINES:])


__all__ = [
    "LIST_LIMIT",
    "MAX_CONVERSATIONS",
    "MAX_MODEL_HISTORY_CHARS",
    "MAX_MODEL_HISTORY_MESSAGES",
    "MAX_STORED_MESSAGES",
    "RETENTION",
    "MiaConversationService",
    "ModelContext",
    "StoredMessage",
    "parse_messages",
    "summary_of",
    "traces_to_json",
]

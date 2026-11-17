"""The wire contract of Mia V1. The browser sends a message, the date it is looking at, optionally
the id of the conversation it continues and a small validated hint about the screen; it never sends
a history, a tool, a property id in the body or a workspace. The answer carries the conversation id
the
server owns."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.ask_ninfa.types import MAX_QUESTION_LENGTH
from app.modules.ai.mia.ui_context import UiContext


class MiaMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    # The business date the person is looking at, in the property's own time zone: never a server
    # clock (the same rule as every other read of this API).
    as_of_local_date: str = Field(min_length=10, max_length=10)
    # Absent = a NEW conversation. Present = continue one that belongs to this user and property
    # (anything else is a 404, the same as a missing one).
    conversation_id: UUID | None = None
    ui_context: UiContext | None = None


class MiaAnswerResponse(BaseModel):
    status: Literal["ANSWERED", "INSUFFICIENT_CONTEXT", "UNAVAILABLE", "REFUSED"]
    answer: str | None
    limitations: list[str]
    grounding_refs: list[str]
    # The conversation the exchange was recorded in; `None` when nothing was recorded (a refused or
    # unavailable turn leaves no trace).
    conversation_id: UUID | None


class MiaStoredMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    status: str | None = None
    limitations: list[str] = Field(default_factory=list)


class MiaConversationSummary(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    message_count: int


class MiaConversationListResponse(BaseModel):
    conversations: list[MiaConversationSummary]


class MiaConversationResponse(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    messages: list[MiaStoredMessage]


__all__ = [
    "MiaAnswerResponse",
    "MiaConversationListResponse",
    "MiaConversationResponse",
    "MiaConversationSummary",
    "MiaMessageRequest",
    "MiaStoredMessage",
]

"""The ONE table of Mia: a person's conversation with Mia about ONE property.

Why NINFA owns the conversation (ADR 0055): "e sabato?", "perché?", "intendo il 20 novembre" only
work if Mia knows what came before, the conversation should survive a navigation or a refresh, and
it must be tamper-proof - an assistant message can only be one Mia really wrote, never one a client
forged to plant a fact. Keeping it in NINFA's own database (instead of leaning on a vendor's stored
threads, which the requests do not use: `store=False`) also makes isolation, retention and deletion
NINFA's decisions.

Deliberately small and bounded, not a memory:

* MANY conversations per (workspace, property, user), each with its own id. The id is a handle,
never
  a credential: every read and every write names the workspace, the property AND the user the route
  resolved from the authenticated request, so a guessed or leaked id of another person's
  conversation is a missing one (404), and the database ties each row to the user's membership.
* Bound to the user's MEMBERSHIP by a composite foreign key: revoking the membership (or removing
the
  user or the workspace, which remove the membership) deletes the conversation with it (`ON DELETE
  CASCADE`) - because otherwise a conversation would make a revoked user's membership impossible to
  delete. The link to the property stays RESTRICT like every other operational table (properties are
  archived, never deleted).
* Bounded in size (the service keeps at most `conversation.MAX_STORED_MESSAGES`; the database
refuses
  an array of more than 200) and in time (a conversation idle for `conversation.RETENTION` is
  deleted by the service, lazily, when its owner next starts one).
* It stores only what the person typed and what Mia answered (text, status, limitations), the
  server-written trace of which tools an answer used, a title and a short deterministic digest of
  what was already asked - never an observation, a booking row, a credential, a model prompt or a
  chain of thought. Long-term AI memory of the business is NOT part of this table.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# The database's own backstop; the service's working limit (`conversation.MAX_STORED_MESSAGES`) is
# lower.
MAX_ROWS_MESSAGES = 200
TITLE_MAX_LENGTH = 120


class MiaConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mia_conversations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    # What was already asked in messages that aged out of `messages`: one short line each, written
    # by the service from the person's own questions and the NAMES of the tools used, never from
    # an answer or a figure. It is context for understanding a follow-up, never a source of facts.
    digest: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # A JSON array of {"role", "content", "at", ...}: see `conversation.py` for the shape.
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_mia_conversations_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        # The user must be a MEMBER of the workspace: revoking the membership deletes this row.
        ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            name="fk_mia_conversations_workspace_id_workspace_memberships",
            ondelete="CASCADE",
        ),
        CheckConstraint("jsonb_typeof(messages) = 'array'", name="messages_is_array"),
        # CASE: a non-array must fail `messages_is_array`, not blow up the length function first.
        CheckConstraint(
            "CASE WHEN jsonb_typeof(messages) = 'array'"
            f" THEN jsonb_array_length(messages) <= {MAX_ROWS_MESSAGES} ELSE true END",
            name="messages_bounded",
        ),
        # "the recent conversations of this person about this property" (the list, the purge).
        Index(
            "ix_mia_conversations_owner_recent",
            "workspace_id",
            "property_id",
            "user_id",
            "last_message_at",
        ),
    )


__all__ = ["MAX_ROWS_MESSAGES", "TITLE_MAX_LENGTH", "MiaConversation"]

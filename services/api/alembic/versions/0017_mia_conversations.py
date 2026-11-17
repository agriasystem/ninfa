"""Mia: the bounded, NINFA-owned conversations of a user with Mia about one property.

Adds ONE new table, `mia_conversations` (many rows per workspace, property and user, each with its own
id): the title, the text of the conversation (a JSON array of at most 200 entries; the service keeps
fewer), a short digest of what aged out of it, and the time of its last message. Additive: no existing
table or constraint is touched, no row is inserted, nothing is backfilled - every user starts with no
conversation.

Tenant, property and user integrity is enforced by the database with composite foreign keys that
reuse the existing `properties (workspace_id, id)` and `workspace_memberships (workspace_id,
user_id)` unique constraints. The link to the property is RESTRICT like every other operational table;
the link to the MEMBERSHIP is `ON DELETE CASCADE` on purpose: a conversation is ephemeral text, and
revoking a user's membership must delete what that user said and was told with it (and must not be
blocked by it).

Written by hand; the model tests keep the ORM metadata in sync with it. Migrations 0001-0016 are
untouched (the head before this one was `0016_remembered_scope`). An earlier, unmerged branch of Mia
(Mia V3) also created `mia_conversations` under the revision number `0014`; that revision never
reached `main`, so this is the only creator of the table.

Revision ID: 0017_mia_conversations
Revises: 0016_remembered_scope
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_mia_conversations"
down_revision: str | None = "0016_remembered_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mia_conversations",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mia_conversations")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_mia_conversations_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            name=op.f("fk_mia_conversations_workspace_id_workspace_memberships"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(messages) = 'array'",
            name=op.f("ck_mia_conversations_messages_is_array"),
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(messages) = 'array'"
            " THEN jsonb_array_length(messages) <= 200 ELSE true END",
            name=op.f("ck_mia_conversations_messages_bounded"),
        ),
    )
    op.create_index(
        "ix_mia_conversations_owner_recent",
        "mia_conversations",
        ["workspace_id", "property_id", "user_id", "last_message_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mia_conversations_owner_recent", table_name="mia_conversations")
    op.drop_table("mia_conversations")

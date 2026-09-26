"""Gate 13: Authentication & Session V1.

Adds two tables, both keyed off `users` (a global identity, never tenant-owned):

    user_credentials    ONE password authenticator per User (unique `user_id`); the raw password
                          is never stored - only an Argon2id PHC hash string.
    auth_sessions         ONE server-side session per successful login; the browser holds a random
                          opaque token, this table holds only its SHA-256 lookup hash.

Neither table is immutable (unlike Gate 11's own evidence tables): `user_credentials` rows are
updated in place on every login attempt (failure counters/lock) and password change;
`auth_sessions.revoked_at` is set in place on logout or password rotation. No trigger, no
append-only enforcement - there is no history to protect here, only current state.

Written by hand; `tests/test_data_model_migration.py` keeps the ORM metadata in sync with it.
Migrations 0001-0009 are untouched (Gate 12 added no schema; the head before this gate was
`0009_decision_layer`).

Revision ID: 0010_auth_session
Revises: 0009_decision_layer
Create Date: 2026-09-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0010_auth_session"
down_revision: str | None = "0009_decision_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    # --- user_credentials ------------------------------------------------------------------
    op.create_table(
        "user_credentials",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_credentials")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_user_credentials_user_id")),
        sa.CheckConstraint(
            "failed_login_count >= 0",
            name=op.f("ck_user_credentials_failed_login_count_non_negative"),
        ),
        sa.CheckConstraint(
            "btrim(password_hash) <> ''", name=op.f("ck_user_credentials_password_hash_not_blank")
        ),
    )

    # --- auth_sessions -----------------------------------------------------------------------
    op.create_table(
        "auth_sessions",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_sessions_token_hash_format")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_sessions_expires_at_after_created_at")
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_auth_sessions_revoked_at_not_before_created"),
        ),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"])
    op.create_index(op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"])


def downgrade() -> None:
    # Children first. Gate 0-12 objects are untouched.
    op.drop_table("auth_sessions")
    op.drop_table("user_credentials")

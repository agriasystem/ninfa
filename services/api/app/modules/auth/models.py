"""ORM models of Authentication & Session V1 (migration `0010_auth_session`).

Two tables, both keyed off `User` (a GLOBAL identity, never tenant-owned - see
`app.modules.identity.repository.UserRepository`'s own docstring), neither carrying a
`workspace_id`: authentication happens before any tenant is resolved.

    user_credentials    ONE password authenticator per User (V1: exactly one, enforced by a
                         unique `user_id`). The raw password is NEVER stored - only an Argon2id
                         PHC hash string (see `app.modules.auth.passwords`).
    auth_sessions        ONE server-side session per successful login. The BROWSER holds a random
                         opaque token; this table holds only its SHA-256 lookup hash - the raw
                         token itself never reaches the database (see `app.modules.auth.tokens`).

Both are mutable (unlike Gate 11's own append-only evidence tables): a credential's failure
counters/lock/hash change in place, and a session's `revoked_at` is set in place on logout or
password rotation - there is no history to preserve here, only current state.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The password authenticator of ONE User. V1: at most one per User (`user_id` is unique) -
    there is no concept of multiple credentials/factors yet.

    `failed_login_count`/`locked_until` implement the V1 brute-force policy (5 failures ->
    15-minute lock, see `app.modules.auth.service`); both reset to `0`/`NULL` on a successful
    login. `password_changed_at` is bumped by every real password change (provisioning CLI or a
    future rehash-on-login) - never by a failed attempt.
    """

    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Argon2id PHC string (e.g. "$argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>") - never the raw
    # password, never a weaker digest. Length is generous headroom over real Argon2 output.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_credentials_user_id_users",
            ondelete="CASCADE",
        ),
        UniqueConstraint("user_id", name="uq_user_credentials_user_id"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_non_negative"),
        CheckConstraint("btrim(password_hash) <> ''", name="password_hash_not_blank"),
    )


class AuthSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """ONE server-side session created by a successful login.

    `token_hash` is `SHA-256(raw_token)`, lowercase hex - the RAW token (high-entropy,
    `secrets.token_urlsafe(32)`) lives only in the browser's `HttpOnly` cookie and is never
    persisted; a hash lookup is exactly as safe as storing the raw value here would be unsafe,
    because the raw token's own entropy already makes it unguessable (see ADR 0019). No
    `last_seen`/sliding expiry: an ordinary authenticated GET never writes to this table - only
    login (INSERT) and logout/password-rotation (`revoked_at` UPDATE) do.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"
        ),
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_format"),
        CheckConstraint("expires_at > created_at", name="expires_at_after_created_at"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="revoked_at_not_before_created"
        ),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )


__all__ = ["AuthSession", "UserCredential"]

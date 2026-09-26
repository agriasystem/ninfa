"""`AuthRepository`: the ONLY place that reads or writes `user_credentials`/`auth_sessions`.

Neither table is tenant-scoped (a `User` is a global identity - see
`app.modules.identity.repository.UserRepository`'s own docstring), so - like `UserRepository` -
nothing here takes a `TenantContext`.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession, UserCredential


class AuthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- user_credentials ------------------------------------------------------------------

    def get_credential(self, user_id: UUID) -> UserCredential | None:
        return self._session.scalar(select(UserCredential).where(UserCredential.user_id == user_id))

    def get_credential_for_update(self, user_id: UUID) -> UserCredential | None:
        """Locks the row (`SELECT ... FOR UPDATE`) for the duration of the caller's transaction:
        two concurrent login attempts for the SAME user serialize on their failure-counter/lock
        update instead of racing (see `test_auth_lockout.py`'s own concurrency test)."""
        stmt = select(UserCredential).where(UserCredential.user_id == user_id).with_for_update()
        return self._session.scalar(stmt)

    def create_credential(self, user_id: UUID, password_hash: str, now: datetime) -> UserCredential:
        credential = UserCredential(
            user_id=user_id, password_hash=password_hash, password_changed_at=now
        )
        self._session.add(credential)
        self._session.flush()
        return credential

    # --- auth_sessions -----------------------------------------------------------------------

    def create_session(
        self, user_id: UUID, token_hash: str, created_at: datetime, expires_at: datetime
    ) -> AuthSession:
        session = AuthSession(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at, created_at=created_at
        )
        self._session.add(session)
        self._session.flush()
        return session

    def get_session_by_token_hash(self, token_hash: str) -> AuthSession | None:
        return self._session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))

    def revoke_session(self, session: AuthSession, now: datetime) -> None:
        if session.revoked_at is None:
            session.revoked_at = now
            self._session.flush()

    def revoke_all_sessions_for_user(self, user_id: UUID, now: datetime) -> None:
        stmt = select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
        for session in self._session.scalars(stmt):
            session.revoked_at = now
        self._session.flush()


__all__ = ["AuthRepository"]

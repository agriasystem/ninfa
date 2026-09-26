"""AuthService: login, logout, principal/session resolution and credential provisioning.

    email + password -> AuthService.login() -> AuthenticatedSession (raw token + AuthSession + User)
    raw cookie token  -> AuthService.resolve_principal() -> AuthenticatedPrincipal | None

Every method that changes state (`login`, `logout_by_raw_token`, `set_password`) owns its own
transaction: it commits on success and leaves the session ready for the next call. Verification
methods (`resolve_principal`, `resolve_session`) never write - not even a "last seen" touch (see
`app.modules.auth.models.AuthSession`'s own docstring for why).
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedPrincipal
from app.core.clock import Clock, utcnow
from app.modules.auth.errors import InvalidCredentialsError
from app.modules.auth.models import AuthSession
from app.modules.auth.passwords import dummy_verify, hash_password, needs_rehash, verify_password
from app.modules.auth.repository import AuthRepository
from app.modules.auth.tokens import generate_session_token, hash_session_token
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository

SESSION_ABSOLUTE_LIFETIME_SECONDS = 7 * 24 * 60 * 60  # 7 days, absolute, never sliding
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION_SECONDS = 15 * 60  # 15 minutes

SESSION_ABSOLUTE_LIFETIME = timedelta(seconds=SESSION_ABSOLUTE_LIFETIME_SECONDS)
LOCK_DURATION = timedelta(seconds=LOCK_DURATION_SECONDS)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """The result of a successful login: the RAW token (to become the cookie value - never
    persisted) plus the real, committed `AuthSession`/`User` rows."""

    raw_token: str
    session: AuthSession
    user: User


class AuthService:
    def __init__(self, session: Session, clock: Clock = utcnow) -> None:
        self._session = session
        self._clock = clock
        self._repo = AuthRepository(session)
        self._users = UserRepository(session)

    # --- login / logout ------------------------------------------------------------------

    def login(self, email: str, password: str) -> AuthenticatedSession:
        """ALWAYS raises `InvalidCredentialsError` for: unknown email, inactive user, no
        credential, wrong password, or a currently locked account - the public outcome is
        identical in every case (see ADR 0019, "why one generic error"). An unknown email never
        touches `user_credentials`/`auth_sessions`: only a real Argon2 verification against a
        fixed dummy hash runs, so the wall-clock cost is close to a real attempt's without ever
        writing a row for an email that may not even be a real account (see
        `app.modules.auth.passwords.dummy_verify`).
        """
        user = self._users.get_by_email(email)
        if user is None or not user.is_active:
            dummy_verify(password)
            raise InvalidCredentialsError()

        credential = self._repo.get_credential_for_update(user.id)
        if credential is None:
            dummy_verify(password)
            raise InvalidCredentialsError()

        now = self._clock()
        is_locked = credential.locked_until is not None and credential.locked_until > now
        # Always run the real verification, even while locked: a correct password during an
        # active lock must still fail (never reveal that the password itself was right), and
        # running it unconditionally keeps the locked/unlocked code paths timing-similar.
        verified = verify_password(credential.password_hash, password)

        if is_locked or not verified:
            if not is_locked:  # a lock already in force is not extended by further attempts
                credential.failed_login_count += 1
                if credential.failed_login_count >= MAX_FAILED_ATTEMPTS:
                    credential.locked_until = now + LOCK_DURATION
            self._session.commit()
            raise InvalidCredentialsError()

        credential.failed_login_count = 0
        credential.locked_until = None
        if needs_rehash(credential.password_hash):
            # The just-verified plaintext is only ever available inside THIS successful login -
            # re-hashing it now, in the same transaction, is the only place this can happen
            # without asking the user to log in again (see ADR 0019, "why rehash-on-login").
            credential.password_hash = hash_password(password)

        raw_token = generate_session_token()
        auth_session = self._repo.create_session(
            user.id,
            hash_session_token(raw_token),
            created_at=now,
            expires_at=now + SESSION_ABSOLUTE_LIFETIME,
        )
        self._session.commit()
        return AuthenticatedSession(raw_token=raw_token, session=auth_session, user=user)

    def logout_by_raw_token(self, raw_token: str) -> None:
        """Idempotent and safe on ANY input: a missing, malformed, already-revoked or expired
        token all no-op silently - logout never leaks whether a token was ever valid."""
        session_row = self._repo.get_session_by_token_hash(hash_session_token(raw_token))
        if session_row is not None:
            self._repo.revoke_session(session_row, self._clock())
        self._session.commit()

    # --- principal / session resolution (read-only, no last-seen write) ------------------

    def _resolve_valid_session(self, raw_token: str) -> tuple[AuthSession, User] | None:
        session_row = self._repo.get_session_by_token_hash(hash_session_token(raw_token))
        if session_row is None or session_row.revoked_at is not None:
            return None
        if session_row.expires_at <= self._clock():
            return None
        user = self._users.get(session_row.user_id)
        if user is None or not user.is_active:
            return None
        return session_row, user

    def resolve_principal(self, raw_token: str) -> AuthenticatedPrincipal | None:
        resolved = self._resolve_valid_session(raw_token)
        return None if resolved is None else AuthenticatedPrincipal(user_id=resolved[1].id)

    def resolve_session(self, raw_token: str) -> AuthSession | None:
        """Like `resolve_principal`, but the full `AuthSession` row - used only by the
        `/auth/session` endpoint, which needs `expires_at`. `AuthenticatedPrincipal` stays
        deliberately minimal (see `app.core.auth`'s own docstring)."""
        resolved = self._resolve_valid_session(raw_token)
        return None if resolved is None else resolved[0]

    # --- credential provisioning (CLI only - see app.cli.auth) ---------------------------

    def set_password(self, user_id: UUID, new_password: str) -> None:
        """Sets/replaces the User's ONE credential and revokes every one of their existing
        sessions (see ADR 0019, "why password rotation revokes sessions"). Commits on return."""
        now = self._clock()
        new_hash = hash_password(new_password)
        credential = self._repo.get_credential(user_id)
        if credential is None:
            self._repo.create_credential(user_id, new_hash, now)
        else:
            credential.password_hash = new_hash
            credential.password_changed_at = now
            credential.failed_login_count = 0
            credential.locked_until = None
        self._repo.revoke_all_sessions_for_user(user_id, now)
        self._session.commit()


__all__ = [
    "LOCK_DURATION_SECONDS",
    "MAX_FAILED_ATTEMPTS",
    "SESSION_ABSOLUTE_LIFETIME_SECONDS",
    "AuthService",
    "AuthenticatedSession",
]

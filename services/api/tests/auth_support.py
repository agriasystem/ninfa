"""Shared helpers for the Gate 13 (Authentication & Session V1) tests."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.modules.auth.service import AuthService
from app.modules.identity.models import User
from tests.support import BookingFactory

DEFAULT_PASSWORD = "a-real-passphrase-1234"  # 23 chars: well within [14, 128]
LOGIN_PATH = "/api/v1/auth/login"
LOGOUT_PATH = "/api/v1/auth/logout"
SESSION_PATH = "/api/v1/auth/session"


@dataclass
class MutableClock:
    """An injectable clock a test can advance directly (`clock.now += timedelta(...)`) - used for
    the lockout-expiry and session-expiry scenarios, never by monkeypatching `datetime.now`."""

    now: datetime

    def __call__(self) -> datetime:
        return self.now

    @classmethod
    def starting_now(cls) -> "MutableClock":
        return cls(utcnow())


def provision_user_with_password(
    factory: BookingFactory,
    session: Session,
    password: str = DEFAULT_PASSWORD,
    clock: MutableClock | None = None,
) -> User:
    """A fresh `User` (via `factory.user()`, Gate 1's own builder) with a real Argon2id credential
    - the ONLY way to give a user a password, mirroring `app.cli.auth`'s own `AuthService.
    set_password`, never a hand-built `UserCredential` row."""
    user = factory.user()
    AuthService(session, clock=clock or utcnow).set_password(user.id, password)
    return user


def login_json(email: str, password: str) -> dict[str, str]:
    return {"email": email, "password": password}


__all__ = [
    "DEFAULT_PASSWORD",
    "LOGIN_PATH",
    "LOGOUT_PATH",
    "SESSION_PATH",
    "MutableClock",
    "login_json",
    "provision_user_with_password",
]

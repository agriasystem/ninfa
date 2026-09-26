"""Authentication & Session V1: brute-force protection (review items 31-38)."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.modules.auth.errors import InvalidCredentialsError
from app.modules.auth.models import AuthSession, UserCredential
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import LOCK_DURATION, MAX_FAILED_ATTEMPTS, AuthService
from app.modules.identity.models import User
from tests.auth_support import DEFAULT_PASSWORD, MutableClock, provision_user_with_password
from tests.support import BookingFactory

WRONG_PASSWORD = "definitely-the-wrong-one"


def _fail_login(service: AuthService, email: str) -> None:
    with pytest.raises(InvalidCredentialsError):
        service.login(email, WRONG_PASSWORD)


# --- 31-32: failure counting and the fifth-failure lock --------------------------------------


def test_failure_count_increments_on_each_wrong_password(
    db_session: Session, factory: BookingFactory
) -> None:
    user = provision_user_with_password(factory, db_session)
    service = AuthService(db_session)
    repo = AuthRepository(db_session)

    for expected in range(1, MAX_FAILED_ATTEMPTS):
        _fail_login(service, user.email)
        credential = repo.get_credential(user.id)
        assert credential is not None
        assert credential.failed_login_count == expected
        assert credential.locked_until is None  # not yet locked


def test_fifth_failure_locks_the_account(db_session: Session, factory: BookingFactory) -> None:
    user = provision_user_with_password(factory, db_session)
    service = AuthService(db_session)
    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail_login(service, user.email)

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.failed_login_count == MAX_FAILED_ATTEMPTS
    assert credential.locked_until is not None


# --- 33-34: locked account rejects even the CORRECT password, publicly unchanged -------------


def test_locked_account_rejects_correct_password_with_the_same_public_error(
    db_session: Session, factory: BookingFactory
) -> None:
    user = provision_user_with_password(factory, db_session)
    service = AuthService(db_session)
    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail_login(service, user.email)

    with pytest.raises(InvalidCredentialsError) as info:
        service.login(user.email, DEFAULT_PASSWORD)  # the REAL, correct password
    assert info.value.code == "INVALID_CREDENTIALS"
    assert info.value.status_code == 401


# --- 35-36: lock expiry, counters reset on success --------------------------------------------


def test_after_lock_duration_correct_login_succeeds_and_resets_counters(
    db_session: Session, factory: BookingFactory
) -> None:
    clock = MutableClock.starting_now()
    user = provision_user_with_password(factory, db_session, clock=clock)
    service = AuthService(db_session, clock=clock)
    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail_login(service, user.email)

    clock.now += LOCK_DURATION + timedelta(seconds=1)
    result = service.login(user.email, DEFAULT_PASSWORD)
    assert result.user.id == user.id

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.failed_login_count == 0
    assert credential.locked_until is None


def test_correct_login_before_threshold_resets_counters(
    db_session: Session, factory: BookingFactory
) -> None:
    user = provision_user_with_password(factory, db_session)
    service = AuthService(db_session)
    _fail_login(service, user.email)
    _fail_login(service, user.email)
    service.login(user.email, DEFAULT_PASSWORD)

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.failed_login_count == 0
    assert credential.locked_until is None


# --- 37: unknown emails never create a row -----------------------------------------------------


def test_unknown_email_creates_no_credential_row(db_session: Session) -> None:
    service = AuthService(db_session)
    with pytest.raises(InvalidCredentialsError):
        service.login("truly-unknown@example.com", "any-password-value")
    # No User exists for this email either, so there is nothing a credential could even
    # reference - the assertion is really "no exception beyond InvalidCredentialsError, no crash".


# --- 38: concurrent failed attempts do not lose an update --------------------------------------


@dataclass(frozen=True, slots=True)
class CommittedUser:
    id: UUID
    email: str


@pytest.fixture
def committed_user(db_engine: Engine) -> Iterator[CommittedUser]:
    """A real, COMMITTED `User` + credential (Gate 11's own `test_decision_real_commits.py`
    pattern): concurrency across separate sessions needs real commits, which the standard
    rolled-back `db_session` fixture cannot provide. Purged afterwards. Plain values, not the ORM
    object itself: the session that created it closes before the test body runs, so the object
    would otherwise be detached (expired attributes with no session to reload them from)."""
    with Session(db_engine) as session:
        user = User(email=f"lockout-concurrency-{threading.get_ident()}@example.com")
        session.add(user)
        session.flush()
        AuthService(session).set_password(user.id, DEFAULT_PASSWORD)
        user_id, email = user.id, user.email
        session.commit()
    try:
        yield CommittedUser(id=user_id, email=email)
    finally:
        with Session(db_engine) as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
            session.execute(delete(UserCredential).where(UserCredential.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def test_concurrent_failed_logins_do_not_lose_updates(
    db_engine: Engine, committed_user: CommittedUser
) -> None:
    user_id, email = committed_user.id, committed_user.email
    barrier = threading.Barrier(3)

    def attempt() -> None:
        barrier.wait(timeout=10)
        with Session(db_engine) as session, pytest.raises(InvalidCredentialsError):
            AuthService(session).login(email, WRONG_PASSWORD)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(attempt) for _ in range(3)]
        for future in futures:
            future.result(timeout=30)

    with Session(db_engine) as session:
        credential = AuthRepository(session).get_credential(user_id)
        assert credential is not None
        assert credential.failed_login_count == 3  # every attempt counted, none lost

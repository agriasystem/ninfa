"""Authentication & Session V1: password hashing and provisioning policy (review items 1-12)."""

from collections.abc import Callable
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from app.cli.auth import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordInputError,
    run_set_password,
)
from app.core.clock import utcnow
from app.modules.auth.models import UserCredential
from app.modules.auth.passwords import dummy_verify, hash_password, needs_rehash, verify_password
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from tests.auth_support import provision_user_with_password
from tests.support import BookingFactory

WEAK_PASSWORD = "correct horse battery"  # 22 chars, no digits/symbols - no composition rule


def _password_reader(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)

    def read(_prompt: str) -> str:
        return next(iterator)

    return read


# --- 1-4: hashing/verification fundamentals -------------------------------------------------


def test_raw_password_is_never_persisted(db_session: Session, factory: BookingFactory) -> None:
    user = provision_user_with_password(factory, db_session, password="a-real-passphrase-1234")
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert "a-real-passphrase-1234" not in credential.password_hash


def test_argon2_hash_is_stored(db_session: Session, factory: BookingFactory) -> None:
    user = provision_user_with_password(factory, db_session)
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")


def test_correct_password_verifies() -> None:
    password = "a-real-passphrase-1234"
    assert verify_password(hash_password(password), password) is True


def test_wrong_password_fails() -> None:
    hashed = hash_password("a-real-passphrase-1234")
    assert verify_password(hashed, "something-else-entirely") is False


# --- 5: unknown user executes the dummy verification path -----------------------------------


def test_unknown_email_runs_dummy_verify_never_touches_credentials(
    db_session: Session, factory: BookingFactory
) -> None:
    with patch("app.modules.auth.service.dummy_verify") as mock_dummy:
        from app.modules.auth.errors import InvalidCredentialsError

        with pytest.raises(InvalidCredentialsError):
            AuthService(db_session).login("nobody@example.com", "whatever-password")
    mock_dummy.assert_called_once_with("whatever-password")


def test_dummy_verify_runs_a_real_argon2_verification_and_always_mismatches() -> None:
    # Not an exception, not a silent no-op: a real Argon2 verify against the fixed dummy hash.
    dummy_verify("anything")  # must not raise


# --- 6-9: provisioning length policy (CLI only) ----------------------------------------------


def test_password_min_boundary_accepted(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    password = "x" * MIN_PASSWORD_LENGTH
    run_set_password(db_session, user.email, read=_password_reader([password, password]))
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None


def test_below_min_length_rejected(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    password = "x" * (MIN_PASSWORD_LENGTH - 1)
    with pytest.raises(PasswordInputError):
        run_set_password(db_session, user.email, read=_password_reader([password, password]))


def test_password_max_boundary_accepted(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    password = "x" * MAX_PASSWORD_LENGTH
    run_set_password(db_session, user.email, read=_password_reader([password, password]))
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None


def test_above_max_length_rejected(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    password = "x" * (MAX_PASSWORD_LENGTH + 1)
    with pytest.raises(PasswordInputError):
        run_set_password(db_session, user.email, read=_password_reader([password, password]))


# --- 10-11: no composition requirement, whitespace preserved --------------------------------


def test_password_whitespace_is_preserved_byte_for_byte() -> None:
    password = "  leading and trailing spaces preserved  "
    assert len(password) >= MIN_PASSWORD_LENGTH
    hashed = hash_password(password)
    assert verify_password(hashed, password) is True
    assert verify_password(hashed, password.strip()) is False  # NOT the same password


def test_no_composition_requirement_lowercase_only_passphrase_accepted(
    db_session: Session, factory: BookingFactory
) -> None:
    user = factory.user()
    run_set_password(db_session, user.email, read=_password_reader([WEAK_PASSWORD, WEAK_PASSWORD]))
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert verify_password(credential.password_hash, WEAK_PASSWORD) is True


# --- 12: needs_rehash is handled on a successful login ---------------------------------------


def test_needs_rehash_true_for_a_weaker_hash() -> None:
    weak_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    weak_hash = weak_hasher.hash("a-real-passphrase-1234")
    assert needs_rehash(weak_hash) is True


def test_login_rehashes_a_weak_hash_in_place(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    password = "a-real-passphrase-1234"
    weak_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    weak_hash = weak_hasher.hash(password)
    db_session.add(
        UserCredential(user_id=user.id, password_hash=weak_hash, password_changed_at=utcnow())
    )
    db_session.flush()

    AuthService(db_session).login(user.email, password)

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.password_hash != weak_hash
    assert needs_rehash(credential.password_hash) is False
    assert verify_password(credential.password_hash, password) is True

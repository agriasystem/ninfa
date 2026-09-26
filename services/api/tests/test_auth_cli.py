"""Authentication & Session V1: the credential provisioning CLI (review items 74-82)."""

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.cli.auth import PasswordInputError, run_set_password
from app.modules.auth.errors import InvalidCredentialsError
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.identity.models import User
from tests.auth_support import DEFAULT_PASSWORD, provision_user_with_password
from tests.support import BookingFactory

NEW_PASSWORD = "a-brand-new-passphrase-99"


def _reader(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)
    return lambda _prompt: next(iterator)


# --- 74-75: existing user set, non-existing user rejected ---------------------------------------


def test_existing_user_password_is_set(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    run_set_password(db_session, user.email, read=_reader([NEW_PASSWORD, NEW_PASSWORD]))
    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None


def test_nonexistent_user_is_rejected(db_session: Session) -> None:
    with pytest.raises(PasswordInputError, match="No user"):
        run_set_password(
            db_session, "nobody-at-all@example.com", read=_reader([NEW_PASSWORD, NEW_PASSWORD])
        )


# --- 76: password is never a CLI argument --------------------------------------------------------


def test_password_is_not_an_argparse_option() -> None:
    from app.cli.auth import main

    with pytest.raises(SystemExit):
        main(["set-password", "--email", "x@example.com", "--password", "leaked-on-argv"])


# --- 77: confirmation mismatch rejected -----------------------------------------------------------


def test_confirmation_mismatch_is_rejected(db_session: Session, factory: BookingFactory) -> None:
    user = factory.user()
    with pytest.raises(PasswordInputError, match="do not match"):
        run_set_password(
            db_session, user.email, read=_reader([NEW_PASSWORD, "a-different-passphrase-00"])
        )


# --- 78, 81: credential created/updated, hash changes --------------------------------------------


def test_credential_is_created_and_hash_changes_on_update(
    db_session: Session, factory: BookingFactory
) -> None:
    user = provision_user_with_password(factory, db_session, password=DEFAULT_PASSWORD)
    before = AuthRepository(db_session).get_credential(user.id)
    assert before is not None
    before_hash = before.password_hash

    run_set_password(db_session, user.email, read=_reader([NEW_PASSWORD, NEW_PASSWORD]))

    after = AuthRepository(db_session).get_credential(user.id)
    assert after is not None
    assert after.password_hash != before_hash
    assert AuthService(db_session).login(user.email, NEW_PASSWORD).user.id == user.id
    with pytest.raises(InvalidCredentialsError):
        AuthService(db_session).login(user.email, DEFAULT_PASSWORD)  # the OLD password is dead


# --- 79-80: password change revokes all sessions and resets failure state ------------------------


def test_password_change_revokes_all_existing_sessions(
    db_session: Session, factory: BookingFactory
) -> None:
    user = provision_user_with_password(factory, db_session, password=DEFAULT_PASSWORD)
    service = AuthService(db_session)
    first = service.login(user.email, DEFAULT_PASSWORD)
    second = service.login(user.email, DEFAULT_PASSWORD)

    run_set_password(db_session, user.email, read=_reader([NEW_PASSWORD, NEW_PASSWORD]))

    db_session.expire_all()
    rows = db_session.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    assert first.session.id != second.session.id


def test_password_change_resets_failure_state(db_session: Session, factory: BookingFactory) -> None:
    user = provision_user_with_password(factory, db_session, password=DEFAULT_PASSWORD)
    service = AuthService(db_session)
    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            service.login(user.email, "wrong-password-value")

    run_set_password(db_session, user.email, read=_reader([NEW_PASSWORD, NEW_PASSWORD]))

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.failed_login_count == 0
    assert credential.locked_until is None


# --- 82: the raw password never appears in stdout/stderr (real subprocess) -----------------------


@pytest.fixture
def committed_user_email(db_engine: Engine) -> Iterator[str]:
    """A real, COMMITTED `User` email with no credential: the CLI subprocess below runs in its
    OWN process, with its OWN database connection - it cannot see anything the rolled-back
    `db_session` fixture holds only in an uncommitted transaction. Yields a plain `str`, never the
    ORM object (which would be detached the moment this `with` block ends)."""
    email = "cli-provisioning-test@example.com"
    with Session(db_engine) as session:
        session.add(User(email=email))
        session.commit()
    try:
        yield email
    finally:
        with Session(db_engine) as session:
            from app.modules.auth.models import AuthSession, UserCredential

            user_id = session.scalar(select(User.id).where(User.email == email))
            session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
            session.execute(delete(UserCredential).where(UserCredential.user_id == user_id))
            session.execute(delete(User).where(User.email == email))
            session.commit()


def test_raw_password_absent_from_cli_stdout_and_stderr(
    committed_user_email: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercises the REAL entry point (`app.cli.auth.main`: argparse -> `run_set_password` ->
    the final `print`) end to end, via `main`'s own injectable `read` PARAMETER - not a real OS
    subprocess: on Windows, `getpass.getpass()` reads directly from the console (`msvcrt`),
    bypassing a redirected/piped stdin entirely, so a real `subprocess.run(..., input=...)` hangs
    forever waiting for a keystroke that never comes - a platform quirk of `getpass`, not of this
    CLI's own code. This still proves the raw password is not among anything printed by the real
    code path.
    """
    from app.cli.auth import main

    exit_code = main(
        ["set-password", "--email", committed_user_email],
        read=_reader([NEW_PASSWORD, NEW_PASSWORD]),
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert NEW_PASSWORD not in captured.out
    assert NEW_PASSWORD not in captured.err

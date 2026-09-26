"""Credential provisioning CLI (Gate 13): the ONLY way to give a User a password in V1 - there is
no `/signup`, `/change-password` or `/reset-password` endpoint (see
docs/architecture/auth-session-v1.md).

    python -m app.cli.auth set-password --email user@example.com

The password is read with `getpass.getpass` (never a CLI argument, never an environment
variable, never echoed) and confirmed once. `run_set_password`/`_read_new_password` take their
I/O and clock as parameters specifically so tests can exercise the REAL logic with a fake reader
and a fake clock - never a reimplementation of it - without a real terminal.
"""

import argparse
import sys
from collections.abc import Callable
from getpass import getpass

from sqlalchemy.orm import Session

from app.core.clock import Clock, utcnow
from app.db.session import get_sessionmaker
from app.modules.auth.service import AuthService
from app.modules.identity.repository import UserRepository

MIN_PASSWORD_LENGTH = 14
MAX_PASSWORD_LENGTH = 128

PasswordReader = Callable[[str], str]


class PasswordInputError(Exception):
    """A provisioning-time password rejection (too short/long, confirmation mismatch) - CLI-only,
    never surfaced by any HTTP endpoint (login accepts any length - see `LoginRequest`'s own
    docstring)."""


def _read_new_password(read: PasswordReader = getpass) -> str:
    password = read("New password: ")
    confirmation = read("Confirm password: ")
    if password != confirmation:
        raise PasswordInputError("Passwords do not match.")
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise PasswordInputError(
            f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} "
            "characters long."
        )
    return password


def run_set_password(
    session: Session,
    email: str,
    *,
    read: PasswordReader = getpass,
    clock: Clock = utcnow,
) -> None:
    """Fails (raises) if `email` names no existing `User` - this command NEVER creates a User,
    a Workspace or a WorkspaceMembership; it only ever provisions/rotates a credential for one
    that already exists."""
    user = UserRepository(session).get_by_email(email)
    if user is None:
        raise PasswordInputError(f"No user with email {email!r} exists.")
    password = _read_new_password(read)
    AuthService(session, clock=clock).set_password(user.id, password)


def main(argv: list[str] | None = None, *, read: PasswordReader = getpass) -> int:
    """`read` defaults to the real `getpass.getpass` for actual CLI use; tests pass their own
    fake reader here directly - a default PARAMETER, not a monkeypatched module attribute, which
    a function's already-bound default (evaluated once, at definition time) could never see."""
    parser = argparse.ArgumentParser(prog="python -m app.cli.auth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_password_parser = subparsers.add_parser(
        "set-password", help="Provision or rotate one User's password."
    )
    set_password_parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    with get_sessionmaker()() as session:
        try:
            run_set_password(session, args.email, read=read)
        except PasswordInputError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        session.commit()
    print(f"Password set for {args.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PasswordInputError",
    "main",
    "run_set_password",
]

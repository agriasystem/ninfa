"""Argon2id password hashing (`auth-session-v1`). The ONLY module allowed to hash or verify a
password - no manual/DIY hashing (SHA-256, bcrypt-by-hand, PBKDF2-by-hand) anywhere else.

`argon2-cffi`'s `PasswordHasher` defaults are the library's own tuned Argon2id parameters - this
module does not second-guess them with custom time/memory costs, which would need its own security
review. The password is passed through EXACTLY as received: never stripped, never truncated, never
required to contain a class of character - length is the only policy (enforced by the credential
PROVISIONING path, `app.cli.auth`, never here: verification must accept whatever was once hashed).
"""

from contextlib import suppress

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# A real Argon2id hash of an arbitrary, fixed string - computed once at import time - so an
# unknown-email login can still spend a REAL Argon2 verification's wall-clock time (see
# `dummy_verify`) instead of returning instantly, which would otherwise be a trivial timing
# side-channel for user enumeration (see ADR 0019, "why dummy verification").
_DUMMY_HASH = _hasher.hash("ninfa-dummy-password-for-constant-time-unknown-user-verification")


def hash_password(password: str) -> str:
    """The full Argon2id PHC string (algorithm, version, params, salt and hash together) - this
    is the ONLY thing ever persisted; the raw `password` argument never is."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """`True` only on an exact Argon2id match. Any other outcome (mismatch, or a hash string this
    version of the library cannot even parse) is a plain `False` - never an exception a caller
    might forget to catch."""
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """`True` when the hash was produced with parameters older than this process's current
    `PasswordHasher` defaults - the caller may then re-hash the just-verified password onto the
    SAME successful login, never as a separate step (see ADR 0019, "why rehash-on-login")."""
    return _hasher.check_needs_rehash(password_hash)


def dummy_verify(password: str) -> None:
    """Run a REAL Argon2id verification against a fixed dummy hash and discard the (always
    mismatching) result. Called for an email that has no User/no credential, so that its own
    wall-clock cost is close to a real verification's - never skip straight to failure."""
    with suppress(VerifyMismatchError, InvalidHashError):
        _hasher.verify(_DUMMY_HASH, password)


__all__ = ["dummy_verify", "hash_password", "needs_rehash", "verify_password"]

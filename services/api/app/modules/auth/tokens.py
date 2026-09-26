"""Opaque session tokens (`auth-session-v1`): stdlib only, no JWT, no claims.

A session token is a bare random secret - never a container for `user_id`/`workspace_id`/
`expiry`/anything else. The browser cookie holds the RAW token; `auth_sessions.token_hash` holds
only `SHA-256(raw_token)`. A hash is safe to use as a DB lookup key here (unlike a password hash,
which needs Argon2's deliberate slowness) precisely BECAUSE the raw token already has 32 bytes of
`secrets`-grade entropy: nothing meaningfully "brute-forces" a value that large, so a fast general-
purpose hash is exactly the right tool for the actual threat (a stolen DB dump must not itself be
usable as a session token) without punishing every authenticated request with Argon2's cost.
"""

import hashlib
import secrets

SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    """A fresh, unguessable opaque token - `secrets.token_urlsafe`'s own default alphabet, no
    structure a caller could ever parse."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(raw_token: str) -> str:
    """The 64-char lowercase hex SHA-256 of a raw token - the ONLY form ever persisted."""
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


__all__ = ["SESSION_TOKEN_BYTES", "generate_session_token", "hash_session_token"]

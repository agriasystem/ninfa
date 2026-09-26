"""Stable, machine-readable error codes of Authentication & Session V1.

`InvalidCredentialsError` is deliberately the ONE public outcome of every login failure - unknown
email, wrong password, missing credential, or a locked account all raise exactly this, with the
exact same message and status: see `app.modules.auth.service`, "why one generic error" and
ADR 0019.
"""

from app.core.exceptions import AppError


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_CREDENTIALS", "Invalid email or password", status_code=401)


__all__ = ["InvalidCredentialsError"]

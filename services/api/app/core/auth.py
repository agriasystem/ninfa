"""Authentication boundary (`decision-api-v1` seam, filled in for real by Gate 13's
`auth-session-v1`; see ADR 0018 and ADR 0019).

`AuthenticatedPrincipal` is the typed shape every authenticated route depends on;
`get_current_principal` is the PRODUCTION resolver of that dependency. Its body:

    HttpOnly session cookie -> raw opaque token -> SHA-256 -> AuthSession lookup
    -> expiry/revocation check -> User lookup -> AuthenticatedPrincipal(user_id)

No header, cookie name other than the one below, or query parameter is ever trusted as identity -
an `X-User-Id`-style header is exactly the spoofable shortcut this boundary exists to refuse.

Tests still provide a real principal via FastAPI's own
`app.dependency_overrides[get_current_principal]` - never a spoofable header - exactly as before
Gate 13; the real, cookie-based path is exercised end to end by
`tests/test_auth_real_cookie_e2e.py`, which uses NO override at all.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.session import get_session

SESSION_COOKIE_NAME = "ninfa_session"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The authenticated caller of a request. Deliberately minimal: authorization (which
    workspaces/properties this user may reach) is resolved separately, per request, from real
    membership rows - this type carries identity only, never a workspace, a role or session-level
    detail like an expiry (the `/auth/session` endpoint reads that separately, from the real
    `AuthSession` row - see `app.modules.auth.service.AuthService.resolve_session`)."""

    user_id: UUID


class AuthenticationRequiredError(AppError):
    """No authenticated principal could be resolved for this request."""

    def __init__(self) -> None:
        super().__init__("AUTHENTICATION_REQUIRED", "Authentication is required", status_code=401)


def get_current_principal(
    request: Request,
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> AuthenticatedPrincipal:
    """FastAPI dependency: the ONLY function in this codebase allowed to produce an
    `AuthenticatedPrincipal`. Deferred import (function-local, not module-level) breaks the
    otherwise circular `core.auth` <-> `modules.auth.service` dependency: `AuthService` itself
    needs `AuthenticatedPrincipal`'s TYPE, this function needs `AuthService`'s BEHAVIOUR."""
    from app.modules.auth.service import AuthService

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        raise AuthenticationRequiredError()
    principal = AuthService(session, clock=clock).resolve_principal(raw_token)
    if principal is None:
        raise AuthenticationRequiredError()
    return principal


def set_session_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    """Sets the ONE cookie this whole auth boundary reads (`get_current_principal` above): the
    RAW opaque token, `HttpOnly`, `SameSite=Lax`, host-only (no `Domain`), `Secure` by
    configuration (see `Settings.session_cookie_secure` - defaults to `True`, i.e. HTTPS-only,
    everywhere; a local HTTP dev override must be explicit, see ADR 0019). `max_age` matches the
    session's own 7-day absolute lifetime, so the cookie does not outlive what the server will
    actually still accept. `settings` is REQUIRED (never a silent `get_settings()` fallback):
    callers get it from `app.core.config.get_request_settings`, the THIS-APP instance - a stray
    fallback here previously meant a test-overridden `Settings` was silently ignored.
    """
    from app.modules.auth.service import SESSION_ABSOLUTE_LIFETIME_SECONDS

    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=SESSION_ABSOLUTE_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


__all__ = [
    "SESSION_COOKIE_NAME",
    "AuthenticatedPrincipal",
    "AuthenticationRequiredError",
    "clear_session_cookie",
    "get_current_principal",
    "set_session_cookie",
]

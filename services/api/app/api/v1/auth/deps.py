"""`GET /auth/session`'s own dependency: the full `AuthSession` row (for `expires_at`), resolved
by the SAME cookie/hash/expiry/revocation path as `app.core.auth.get_current_principal` - kept
separate so the generic `AuthenticatedPrincipal` (used by every OTHER authenticated route,
including all four Decision API ones) stays deliberately minimal.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import SESSION_COOKIE_NAME, AuthenticationRequiredError
from app.core.clock import Clock, get_clock
from app.db.session import get_session
from app.modules.auth.models import AuthSession


def get_current_auth_session(
    request: Request,
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> AuthSession:
    from app.modules.auth.service import AuthService

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        raise AuthenticationRequiredError()
    auth_session = AuthService(session, clock=clock).resolve_session(raw_token)
    if auth_session is None:
        raise AuthenticationRequiredError()
    return auth_session


__all__ = ["get_current_auth_session"]

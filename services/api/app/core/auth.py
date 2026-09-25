"""Gate 12 fail-closed authentication boundary (`decision-api-v1`, see ADR 0018).

No real authentication provider exists yet in this repository: `app.modules.identity.models.User`
stores no credential of any kind (its own docstring says so - "see auth gate"), and there is no
session, token or SSO integration anywhere in the codebase. `AuthenticatedPrincipal` is the typed
shape every authenticated route depends on; `get_current_principal` is the PRODUCTION resolver of
that dependency, and it always fails closed with 401 - there is no header, cookie or query
parameter this module will ever trust as identity (an `X-User-Id`-style header is exactly the
spoofable shortcut this boundary exists to refuse). A future gate wires a real provider (session
cookie, JWT, OAuth/OIDC - not decided here) by replacing ONLY this function's body; every route
that already depends on `get_current_principal` needs no change.

Tests provide a real principal via FastAPI's own `app.dependency_overrides[get_current_principal]`
- never a spoofable header - exactly as this module's docstring promises callers.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import AppError


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The authenticated caller of a request. Deliberately minimal: authorization (which
    workspaces/properties this user may reach) is resolved separately, per request, from real
    membership rows - this type carries identity only, never a workspace or a role."""

    user_id: UUID


class AuthenticationRequiredError(AppError):
    """No authenticated principal could be resolved for this request."""

    def __init__(self) -> None:
        super().__init__("AUTHENTICATION_REQUIRED", "Authentication is required", status_code=401)


def get_current_principal() -> AuthenticatedPrincipal:
    """FastAPI dependency: the ONLY function in this codebase allowed to produce an
    `AuthenticatedPrincipal`. The production body is unconditional: fail closed until a real
    transport-level authentication mechanism is chosen and wired in here."""
    raise AuthenticationRequiredError()


__all__ = ["AuthenticatedPrincipal", "AuthenticationRequiredError", "get_current_principal"]

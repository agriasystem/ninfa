"""Builds the one `SessionContextResponse` shape shared by a successful `POST /auth/login` and
`GET /auth/session` (see `schemas.py`'s own docstring for why they are the same DTO).
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v1.auth.schemas import (
    PropertyAccess,
    SessionContextResponse,
    SessionInfo,
    SessionUser,
    WorkspaceAccess,
)
from app.core.tenant import TenantContext
from app.modules.identity.models import User
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import MembershipRepository, WorkspaceRepository


def build_session_context(
    session: Session, user: User, expires_at: datetime
) -> SessionContextResponse:
    """Workspace/property access via the SAME policy the Decision API already uses (Gate 12): an
    active `WorkspaceMembership` grants every property of that workspace - no `PropertyAccess`
    invented here either."""
    workspaces = []
    for workspace in WorkspaceRepository(session).list_for_user(user.id):
        tenant = TenantContext(workspace.id)
        membership = MembershipRepository(session, tenant).get_for_user(user.id)
        if membership is None:  # pragma: no cover - list_for_user only returns joined workspaces
            continue
        properties = PropertyRepository(session, tenant).list_all()
        workspaces.append(
            WorkspaceAccess(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
                properties=[
                    PropertyAccess(
                        id=prop.id, name=prop.name, slug=prop.slug, timezone=prop.timezone
                    )
                    for prop in properties
                ],
            )
        )
    return SessionContextResponse(
        user=SessionUser(id=user.id, email=user.email, display_name=user.display_name),
        session=SessionInfo(expires_at=expires_at),
        workspaces=workspaces,
    )


__all__ = ["build_session_context"]

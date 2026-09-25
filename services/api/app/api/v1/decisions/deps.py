"""Server-side tenant derivation for Decision API V1 (see ADR 0018, "why tenant derives server-
side"). The client sends a `property_id` path parameter and nothing else; every other step -
which workspace that property belongs to, whether the caller is a member of it - is resolved here,
from real rows, never from a client-supplied workspace id or header.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.decisions.errors import PropertyNotFoundError
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.tenant import TenantContext
from app.db.session import get_session
from app.modules.properties.models import Property
from app.modules.tenancy.models import WorkspaceMembership


@dataclass(frozen=True, slots=True)
class PropertyScope:
    """The one thing every Decision API route needs: a Property the caller is really allowed to
    read, plus the `TenantContext` derived from it - never from anything the client sent."""

    tenant: TenantContext
    property_id: UUID


def resolve_property_scope(
    property_id: UUID = Path(...),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> PropertyScope:
    """PROPERTY_ID (path) -> Property -> its Workspace -> membership check -> TenantContext.

    A missing property, an archived property, and a real property the caller has no membership
    on are all answered with the SAME `PropertyNotFoundError` (404): distinguishing them would let
    an authenticated-but-unauthorized caller enumerate which property ids exist for a foreign
    workspace, which is exactly what a 403 (instead of a 404) would leak.
    """
    prop = session.get(Property, property_id)
    if prop is None or prop.archived_at is not None:
        raise PropertyNotFoundError()

    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == prop.workspace_id,
            WorkspaceMembership.user_id == principal.user_id,
        )
    )
    if membership is None:
        raise PropertyNotFoundError()

    return PropertyScope(tenant=TenantContext(prop.workspace_id), property_id=prop.id)


__all__ = ["PropertyScope", "resolve_property_scope"]

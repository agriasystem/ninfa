"""Server-side scope of a Mia request: WHO is asking, about WHICH property, with which access.

`resolve_property_scope` (the Decision API's own dependency) already turns the path's property id
into a tenant the authenticated user really belongs to - and answers 404 identically for a missing,
archived or foreign property. Mia adds the one thing the Decision API never needed: the asking
user's ROLE and first name, read from the same membership row, because Mia may know who is asking
(and the access policy needs the role). Nothing here comes from the client except the property id
in the path.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.api.v1.decisions.errors import PropertyNotFoundError
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.tenant import TenantContext
from app.db.session import get_session
from app.modules.ai.gateway.tool_protocol import ToolCallingProvider
from app.modules.ai.mia.access import DomainAccessPolicy, MembershipAccessPolicy, UserContext
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry, default_registry
from app.modules.ai.mia.tools.base import ToolCatalog
from app.modules.ai.mia.tools.catalog import default_tool_catalog
from app.modules.identity.models import User
from app.modules.tenancy.models import WorkspaceMembership


@dataclass(frozen=True, slots=True)
class MiaScope:
    tenant: TenantContext
    property_id: UUID
    user: UserContext


def resolve_mia_scope(
    scope: PropertyScope = Depends(resolve_property_scope),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> MiaScope:
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == scope.tenant.workspace_id,
            WorkspaceMembership.user_id == principal.user_id,
        )
    )
    if membership is None:  # `resolve_property_scope` just checked it: defensive, same answer
        raise PropertyNotFoundError()
    user = session.get(User, principal.user_id)
    return MiaScope(
        tenant=scope.tenant,
        property_id=scope.property_id,
        user=UserContext(
            user_id=principal.user_id,
            role=membership.role,
            display_name=None if user is None else user.display_name,
        ),
    )


def get_mia_provider(request: Request) -> ToolCallingProvider:
    """The ONE provider `create_app()` built for THIS app instance (`app.state.mia_provider`):
    OpenAI's adapter when Mia is explicitly configured, an "unavailable" one otherwise. Overridable
    per test with a scripted provider."""
    provider: ToolCallingProvider = request.app.state.mia_provider
    return provider


def get_tool_catalog() -> ToolCatalog:
    """The closed catalog, built once: it holds no per-request state."""
    return default_tool_catalog()


def get_registry() -> KnowledgeRegistry:
    return default_registry()


def get_access_policy() -> DomainAccessPolicy:
    return MembershipAccessPolicy()


__all__ = [
    "MiaScope",
    "get_access_policy",
    "get_mia_provider",
    "get_registry",
    "get_tool_catalog",
    "resolve_mia_scope",
]

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.validation import Name, Slug
from app.modules.tenancy.models import MembershipRole


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Slug


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MembershipCreate(BaseModel):
    # No workspace_id: the workspace always comes from the TenantContext, never from the payload.
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: MembershipRole


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    role: MembershipRole
    created_at: datetime
    updated_at: datetime

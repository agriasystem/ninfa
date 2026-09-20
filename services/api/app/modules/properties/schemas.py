from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.validation import CurrencyCode, Name, Slug, Timezone
from app.modules.properties.models import DEFAULT_CURRENCY, DEFAULT_TIMEZONE


class PropertyCreate(BaseModel):
    # No workspace_id: it always comes from the TenantContext, never from the payload.
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Slug
    timezone: Timezone = DEFAULT_TIMEZONE
    currency: CurrencyCode = DEFAULT_CURRENCY


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    timezone: str
    currency: str
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

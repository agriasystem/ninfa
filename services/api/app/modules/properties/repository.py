from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.properties.models import Property
from app.modules.properties.schemas import PropertyCreate


class PropertyRepository:
    """Properties of ONE workspace. Every query carries the workspace_id of the TenantContext."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add(self, data: PropertyCreate) -> Property:
        prop = Property(
            workspace_id=self._tenant.workspace_id,
            name=data.name,
            slug=data.slug,
            timezone=data.timezone,
            currency=data.currency,
        )
        self._session.add(prop)
        self._session.flush()
        return prop

    def get(self, property_id: UUID) -> Property | None:
        return self._session.scalar(
            select(Property).where(
                Property.workspace_id == self._tenant.workspace_id, Property.id == property_id
            )
        )

    def get_by_slug(self, slug: str) -> Property | None:
        return self._session.scalar(
            select(Property).where(
                Property.workspace_id == self._tenant.workspace_id, Property.slug == slug
            )
        )

    def list_all(self, *, include_archived: bool = False) -> Sequence[Property]:
        query = select(Property).where(Property.workspace_id == self._tenant.workspace_id)
        if not include_archived:
            query = query.where(Property.archived_at.is_(None))
        return self._session.scalars(query.order_by(Property.slug)).all()

    def archive(self, property_id: UUID) -> Property:
        """Archive (never delete) a property. Idempotent."""
        prop = self.get(property_id)
        if prop is None:
            raise NotFoundError("Property")
        if prop.archived_at is None:
            prop.is_active = False
            prop.archived_at = datetime.now(UTC)
            self._session.flush()
        return prop

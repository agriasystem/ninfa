import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.ingestion.models import DataSource
    from app.modules.tenancy.models import Workspace

DEFAULT_TIMEZONE = "Europe/Rome"
DEFAULT_CURRENCY = "EUR"


class Property(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A hospitality structure. Deliberately only its identity: the Property Profile
    (rooms, beds, opening model, ...) belongs to the Data Contract gate.
    """

    __tablename__ = "properties"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default=DEFAULT_TIMEZONE, server_default=DEFAULT_TIMEZONE
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_CURRENCY, server_default=DEFAULT_CURRENCY
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped["Workspace"] = relationship("Workspace", viewonly=True)
    data_sources: Mapped[list["DataSource"]] = relationship("DataSource", viewonly=True)

    __table_args__ = (
        # RESTRICT: a workspace that still owns properties can never be deleted (archive it).
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_properties_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        # The same slug may exist in different workspaces, never twice in one.
        UniqueConstraint("workspace_id", "slug", name="uq_properties_workspace_id_slug"),
        # Redundant with the primary key on purpose: it is the target of the composite foreign
        # keys that pin child rows (data sources, ...) to this property's workspace.
        UniqueConstraint("workspace_id", "id", name="uq_properties_workspace_id_id"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 2 AND 63",
            name="slug_format",
        ),
        CheckConstraint("btrim(timezone) <> ''", name="timezone_not_blank"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("archived_at IS NULL OR NOT is_active", name="archived_implies_inactive"),
    )

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check

if TYPE_CHECKING:
    from app.modules.identity.models import User
    from app.modules.properties.models import Property


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The tenant boundary. Archived (never physically deleted) when no longer in use.

    `is_active` is the operational switch; `archived_at` records when the workspace was
    archived. Archived implies inactive (enforced by a CHECK).
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    properties: Mapped[list["Property"]] = relationship("Property", viewonly=True)
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", viewonly=True
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint(
            r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 2 AND 63",
            name="slug_format",
        ),
        CheckConstraint("archived_at IS NULL OR NOT is_active", name="archived_implies_inactive"),
    )


class WorkspaceMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User <-> Workspace. The only entity that is deleted for real when access is revoked.

    Both foreign keys CASCADE: a membership has no meaning without its user or workspace, so
    it must never block (or outlive) their removal.
    """

    __tablename__ = "workspace_memberships"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole, 16), nullable=False)

    workspace: Mapped["Workspace"] = relationship("Workspace", viewonly=True)
    user: Mapped["User"] = relationship("User", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_memberships_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_workspace_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        # Also serves "members of a workspace" (leading column workspace_id).
        UniqueConstraint(
            "workspace_id", "user_id", name="uq_workspace_memberships_workspace_id_user_id"
        ),
        CheckConstraint(values_check("role", MembershipRole), name="role_valid"),
        # "Which workspaces does this user belong to?" is the entry point of access resolution.
        Index("ix_workspace_memberships_user_id", "user_id"),
    )

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.tenancy.models import WorkspaceMembership


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Internal application identity. No credentials of any kind live here (see auth gate).

    `email` is stored already normalised (trimmed, lower-case). PostgreSQL enforces that with
    a CHECK, so a plain UNIQUE constraint is a case-insensitive uniqueness guarantee without
    the citext extension or a functional index.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )

    # Read-only navigation: memberships are written through their repository, by explicit ids.
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", viewonly=True
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
        CheckConstraint(r"email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'", name="email_format"),
        CheckConstraint(
            "display_name IS NULL OR btrim(display_name) <> ''", name="display_name_not_blank"
        ),
    )

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.tenancy.models import MembershipRole, Workspace, WorkspaceMembership
from app.modules.tenancy.schemas import MembershipCreate, WorkspaceCreate


class WorkspaceRepository:
    """Workspaces ARE the tenant boundary, so this repository is not tenant-scoped.

    Access to it must only ever come from platform-level code (workspace provisioning, and the
    future authentication layer resolving which workspaces a user may enter).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, data: WorkspaceCreate) -> Workspace:
        workspace = Workspace(name=data.name, slug=data.slug)
        self._session.add(workspace)
        self._session.flush()
        return workspace

    def get(self, workspace_id: UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)

    def get_by_slug(self, slug: str) -> Workspace | None:
        return self._session.scalar(select(Workspace).where(Workspace.slug == slug))

    def list_for_user(
        self, user_id: UUID, *, include_archived: bool = False
    ) -> Sequence[Workspace]:
        """Workspaces a user belongs to: the first hop of USER -> MEMBERSHIP -> WORKSPACE."""
        query = (
            select(Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(Workspace.slug)
        )
        if not include_archived:
            query = query.where(Workspace.archived_at.is_(None))
        return self._session.scalars(query).all()

    def archive(self, workspace_id: UUID) -> Workspace:
        """Archive (never delete) a workspace. Idempotent."""
        workspace = self.get(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace")
        if workspace.archived_at is None:
            workspace.is_active = False
            workspace.archived_at = datetime.now(UTC)
            self._session.flush()
        return workspace


class MembershipRepository:
    """Memberships of ONE workspace, fixed by the TenantContext at construction."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add(self, data: MembershipCreate) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            workspace_id=self._tenant.workspace_id, user_id=data.user_id, role=data.role
        )
        self._session.add(membership)
        self._session.flush()
        return membership

    def get_for_user(self, user_id: UUID) -> WorkspaceMembership | None:
        return self._session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == self._tenant.workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    def list_all(self, *, role: MembershipRole | None = None) -> Sequence[WorkspaceMembership]:
        query = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == self._tenant.workspace_id
        )
        if role is not None:
            query = query.where(WorkspaceMembership.role == role)
        return self._session.scalars(query.order_by(WorkspaceMembership.created_at)).all()

    def remove(self, user_id: UUID) -> None:
        """Revoke access: the membership row is really deleted."""
        membership = self.get_for_user(user_id)
        if membership is None:
            raise NotFoundError("Membership")
        self._session.delete(membership)
        self._session.flush()

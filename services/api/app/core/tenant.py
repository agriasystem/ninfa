"""Tenant context: the explicit workspace scope every tenant-owned data access must carry."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantContext:
    """The workspace a piece of work runs for.

    Deliberately minimal and *not* an authentication mechanism: it says nothing about who the
    caller is or whether they may act on this workspace. Resolving that (USER -> WORKSPACE
    MEMBERSHIP -> PROPERTY ACCESS) belongs to the authentication/authorization gate, which will
    be the only place that builds a TenantContext for a request.

    There is no default and no "no tenant" value: a tenant-scoped repository cannot be
    constructed without one.
    """

    workspace_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("TenantContext.workspace_id must be a UUID")

"""Who is asking, and which data domains they may reach through Mia.

AUTHORIZATION HAPPENS BEFORE DATA REACHES THE MODEL. Every tool belongs to exactly one
`AccessDomain`; `ToolExecutor` asks the `DomainAccessPolicy` before it runs the tool, and a tool
that lists several areas (the decisions, the analysis status) filters out the areas the user may not
see BEFORE anything is counted or serialized - a hidden area leaves no trace in a total either. A
denied call returns a plain "not allowed" outcome and the underlying service is never invoked.

What exists today (audited, not invented): the Decision API authorizes by WORKSPACE MEMBERSHIP only
- any member of the property's workspace (OWNER, ADMIN or MEMBER) reads every area through the
Decision Feed. NINFA has no per-domain or per-role permission model yet, so the default policy
mirrors exactly that: Mia never grants more than the product already does, and never less. The
`DomainAccessPolicy` seam is where a future per-domain permission (for example: costs only for
OWNER/ADMIN) is plugged in, with no change to any tool.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.modules.decisions.coverage import AnalysisDomain
from app.modules.tenancy.models import MembershipRole


class AccessDomain(StrEnum):
    """The data areas a tool can belong to. The four analysis areas deliberately share the names of
    `AnalysisDomain` (the areas the product already presents); `COMPANY` is what NINFA knows about
    the business itself (profile, capacity, connected data, configuration)."""

    REVENUE = "REVENUE"
    DISTRIBUTION = "DISTRIBUTION"
    COSTS = "COSTS"
    LABOR = "LABOR"
    COMPANY = "COMPANY"
    # What NINFA itself IS (sections, features, terms): knowledge of the product, never of a
    # property - so it needs no data area, only a member of the workspace.
    PRODUCT = "PRODUCT"


def access_domain_of(domain: AnalysisDomain) -> AccessDomain:
    return AccessDomain(domain.value)


@dataclass(frozen=True, slots=True)
class UserContext:
    """The asking user as Mia may know them: id (for binding), role and the name to address them
    with. Never the email or any credential."""

    user_id: UUID
    role: MembershipRole
    display_name: str | None = None


class DomainAccessPolicy(Protocol):
    def allows(self, user: UserContext, domain: AccessDomain) -> bool: ...


class MembershipAccessPolicy:
    """The product's current rule: a member of the workspace reads every area (see the module
    docstring). Property scoping is not decided here - the route resolves the property through the
    user's membership before a `UserContext` even exists."""

    def allows(self, user: UserContext, domain: AccessDomain) -> bool:
        return user.role in MembershipRole


__all__ = [
    "AccessDomain",
    "DomainAccessPolicy",
    "MembershipAccessPolicy",
    "UserContext",
    "access_domain_of",
]

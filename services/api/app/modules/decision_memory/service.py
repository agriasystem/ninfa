"""DecisionMemoryService: the internal READ SIDE of the Decision Layer.

No public business API, no UI, no recommendation: this is a plain, framework-free class a future
gate's authenticated endpoint (or worker, or another service) can call, exactly like every other
read path in this codebase. It never writes: `DecisionService.sync()` is the only write path.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.repository import DecisionRepository
from app.modules.intelligence.priority.types import PriorityDecisionType


class DecisionMemoryService:
    """Read-only. Pass any session: this service never commits or rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Decision Memory service needs a TenantContext")
        self._repo = DecisionRepository(session, tenant)

    def list_open_decisions(self, property_id: UUID) -> list[Decision]:
        """Every OPEN Decision of a property (a reopened one included; a resolved one excluded),
        loaded with ONE query."""
        return list(self._repo.list_open_decisions(property_id))

    def get_decision(self, decision_id: UUID) -> Decision | None:
        """A Decision's current row, tenant-scoped: one of another workspace does not exist here
        (a missing id and a foreign id are indistinguishable, the same convention as every other
        repository in this codebase)."""
        return self._repo.get_decision(decision_id)

    def get_history(self, decision_id: UUID) -> list[DecisionObservation]:
        """Every Observation of one Decision, chronological (`as_of_local_date`, then the run that
        produced it, then the observation id as a final tie-break) - the whole memory of what
        NINFA knew about this problem, one row per day/run it was actually evaluated. Empty for an
        unknown or foreign decision id, never an error: the caller can tell the two apart, if it
        needs to, from `get_decision()`."""
        return list(self._repo.history(decision_id))

    def find_by_identity(
        self, property_id: UUID, decision_type: PriorityDecisionType, identity_key: str
    ) -> Decision | None:
        """The Decision of one exact identity, if any - useful for tests and for auditing a
        specific cross-day identity end to end without walking `list_open_decisions()`."""
        return self._repo.find_by_identity(property_id, decision_type, identity_key)


__all__ = ["DecisionMemoryService"]

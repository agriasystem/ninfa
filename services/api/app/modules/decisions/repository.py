"""`DecisionRepository`: the ONLY place that reads or writes `decision_runs`/`decisions`/
`decision_observations`.

Every method takes the `TenantContext`'s workspace scope and (where relevant) an explicit
`property_id`: nothing here has a method that accepts a workspace argument, and nothing here ever
loads a Decision one identity at a time (`existing_by_identities` is the ONE set-based query a
whole sync uses, whatever the number of source evaluations - see `test_decision_performance.py`).
`insert_observations` is a single bulk `INSERT` through Core, never a loop of ORM adds.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, tuple_
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.identity import DecisionIdentity
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.types import DecisionStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

IdentityKey = tuple[PriorityDecisionType, str]


class DecisionRepository:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("DecisionRepository needs a TenantContext")
        self._session = session
        self._tenant = tenant

    # --- decision_runs ---------------------------------------------------------------------

    def find_run(
        self, property_id: UUID, as_of_local_date: date, input_fingerprint: str
    ) -> DecisionRun | None:
        """The existing run of this exact (workspace, property, as-of, input), if any: what makes
        an exact replay idempotent."""
        stmt = select(DecisionRun).where(
            DecisionRun.workspace_id == self._tenant.workspace_id,
            DecisionRun.property_id == property_id,
            DecisionRun.as_of_local_date == as_of_local_date,
            DecisionRun.input_fingerprint == input_fingerprint,
        )
        return self._session.scalars(stmt).one_or_none()

    def insert_run(self, values: dict[str, Any]) -> DecisionRun:
        run = DecisionRun(workspace_id=self._tenant.workspace_id, **values)
        self._session.add(run)
        self._session.flush()
        return run

    # --- decisions ---------------------------------------------------------------------------

    def existing_by_identities(
        self, property_id: UUID, identities: Iterable[DecisionIdentity]
    ) -> dict[IdentityKey, Decision]:
        """Every Decision already matching one of `identities`, loaded in ONE query (never a
        SELECT per identity): keyed by (decision_type, identity_key)."""
        pairs = {(identity.decision_type, identity.identity_key) for identity in identities}
        if not pairs:
            return {}
        stmt = select(Decision).where(
            Decision.workspace_id == self._tenant.workspace_id,
            Decision.property_id == property_id,
            tuple_(Decision.decision_type, Decision.identity_key).in_(pairs),
        )
        return {(d.decision_type, d.identity_key): d for d in self._session.scalars(stmt)}

    def insert_decision(self, values: dict[str, Any]) -> Decision:
        decision = Decision(workspace_id=self._tenant.workspace_id, **values)
        self._session.add(decision)
        self._session.flush()
        return decision

    def find_by_identity(
        self, property_id: UUID, decision_type: PriorityDecisionType, identity_key: str
    ) -> Decision | None:
        stmt = select(Decision).where(
            Decision.workspace_id == self._tenant.workspace_id,
            Decision.property_id == property_id,
            Decision.decision_type == decision_type,
            Decision.identity_key == identity_key,
        )
        return self._session.scalars(stmt).one_or_none()

    def get_decision(self, decision_id: UUID) -> Decision | None:
        """Tenant-scoped: a Decision of another workspace does not exist for this call."""
        stmt = select(Decision).where(
            Decision.workspace_id == self._tenant.workspace_id, Decision.id == decision_id
        )
        return self._session.scalars(stmt).one_or_none()

    def list_open_decisions(self, property_id: UUID) -> Sequence[Decision]:
        """Every OPEN Decision of a property (includes a reopened one), most recently evaluated
        first, id as the final deterministic tie-break."""
        stmt = (
            select(Decision)
            .where(
                Decision.workspace_id == self._tenant.workspace_id,
                Decision.property_id == property_id,
                Decision.status == DecisionStatus.OPEN,
            )
            .order_by(Decision.last_evaluated_local_date.desc(), Decision.id)
        )
        return self._session.scalars(stmt).all()

    # --- decision_observations -------------------------------------------------------------

    def insert_observations(self, rows: list[dict[str, Any]]) -> None:
        """ONE bulk INSERT for the whole run's observations (never a loop of ORM adds)."""
        if not rows:
            return
        self._session.execute(
            insert(DecisionObservation),
            [{"workspace_id": self._tenant.workspace_id, **row} for row in rows],
        )

    def history(self, decision_id: UUID) -> Sequence[DecisionObservation]:
        """Every Observation of one Decision, in DETERMINISTIC memory order: as-of date, then the
        run that produced it (`DecisionRun.run_sequence`, an explicit, DB-generated, strictly
        increasing run order - `created_at` alone cannot break a tie between two runs of the same
        transaction, since PostgreSQL's `now()` is fixed for the whole transaction), then the
        observation id only as a final tie-break. ONE query, never one per observation."""
        stmt = (
            select(DecisionObservation)
            .join(DecisionRun, DecisionObservation.decision_run_id == DecisionRun.id)
            .where(
                DecisionObservation.workspace_id == self._tenant.workspace_id,
                DecisionObservation.decision_id == decision_id,
            )
            .order_by(
                DecisionObservation.as_of_local_date,
                DecisionRun.run_sequence,
                DecisionObservation.id,
            )
        )
        return self._session.scalars(stmt).all()


__all__ = ["DecisionRepository", "IdentityKey"]

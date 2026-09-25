"""`DecisionRepository`: the ONLY place that reads or writes `decision_runs`/`decisions`/
`decision_observations`.

Every method takes the `TenantContext`'s workspace scope and (where relevant) an explicit
`property_id`: nothing here has a method that accepts a workspace argument, and nothing here ever
loads a Decision one identity at a time (`existing_by_identities` is the ONE set-based query a
whole sync uses, whatever the number of source evaluations - see `test_decision_performance.py`).
`insert_observations` is a single bulk `INSERT` through Core, never a loop of ORM adds.

Gate 12 (Decision API V1) added the READ-ONLY, set-based query methods below the `# --- Gate 12`
marker: the latest run of an as-of, its feed rows, a keyset-paginated Decision page with its
latest observations loaded set-based, and a keyset-paginated, newest-first Observation history.
None of them write; none of them recomputes Priority or a detector's own status - every one reads
exactly what Gate 11 already persisted.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import and_, insert, or_, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.core.tenant import TenantContext
from app.modules.decisions.identity import DecisionIdentity
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.types import DecisionStatus, SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

IdentityKey = tuple[PriorityDecisionType, str]


def _seek_predicate(fields: list[tuple[Any, Any, bool]]) -> ColumnElement[bool]:
    """The standard keyset "seek" predicate for a compound ORDER BY where each column may have
    its own direction: `fields` is `(column, cursor_value, is_descending)` in ORDER BY order.
    Strictly continues past the cursor row in that exact order - the general form of a keyset
    `WHERE` clause when not every column sorts the same way (a plain tuple `<`/`>` comparison only
    works when every column shares one direction)."""
    clauses = []
    for index in range(len(fields)):
        equalities = [col == val for col, val, _ in fields[:index]]
        col, val, descending = fields[index]
        comparison = col < val if descending else col > val
        clauses.append(and_(*equalities, comparison) if equalities else comparison)
    return or_(*clauses)


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

    # --- Gate 12: Decision API V1 read-only queries -----------------------------------------

    def latest_run(self, property_id: UUID, as_of_local_date: date) -> DecisionRun | None:
        """The `DecisionRun` with the HIGHEST `run_sequence` of this exact (workspace, property,
        as-of): several runs can share one as-of date (see the golden "multiple same-day runs"
        scenario), and `run_sequence` - not `created_at` - is the DB-generated, strictly
        increasing order that breaks that tie (see `models.py`'s own `DecisionRun.run_sequence`
        docstring)."""
        stmt = (
            select(DecisionRun)
            .where(
                DecisionRun.workspace_id == self._tenant.workspace_id,
                DecisionRun.property_id == property_id,
                DecisionRun.as_of_local_date == as_of_local_date,
            )
            .order_by(DecisionRun.run_sequence.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def feed_rows(self, run_id: UUID) -> Sequence[tuple[DecisionObservation, Decision]]:
        """The TRIGGERED observations of ONE run, each paired with its Decision's current
        lifecycle row, ordered `priority_rank ASC` - ONE query, never one per item."""
        stmt = (
            select(DecisionObservation, Decision)
            .join(Decision, DecisionObservation.decision_id == Decision.id)
            .where(
                DecisionObservation.workspace_id == self._tenant.workspace_id,
                DecisionObservation.decision_run_id == run_id,
                DecisionObservation.source_status == SourceStatus.TRIGGERED,
            )
            .order_by(DecisionObservation.priority_rank.asc())
        )
        return [(row.DecisionObservation, row.Decision) for row in self._session.execute(stmt)]

    def list_decisions_page(
        self,
        property_id: UUID,
        *,
        status: DecisionStatus | None,
        decision_type: PriorityDecisionType | None,
        limit: int,
        after: tuple[date, date, PriorityDecisionType, UUID] | None,
    ) -> tuple[Sequence[Decision], bool]:
        """A keyset-paginated page of Decisions (Memory/lifecycle - every status, not only what a
        single run touched), ordered `last_evaluated_local_date DESC, last_seen_local_date DESC,
        decision_type, decision_id` (never by priority: that belongs to an Observation, not to a
        Decision's own lifecycle row - see `docs/architecture/decision-api-v1.md`). `after` is the
        exact 4-tuple of the previous page's last row. Fetches `limit + 1` to report `has_more`
        without a second COUNT query."""
        stmt = select(Decision).where(
            Decision.workspace_id == self._tenant.workspace_id,
            Decision.property_id == property_id,
        )
        if status is not None:
            stmt = stmt.where(Decision.status == status)
        if decision_type is not None:
            stmt = stmt.where(Decision.decision_type == decision_type)
        if after is not None:
            last_evaluated, last_seen, after_type, after_id = after
            stmt = stmt.where(
                _seek_predicate(
                    [
                        (Decision.last_evaluated_local_date, last_evaluated, True),
                        (Decision.last_seen_local_date, last_seen, True),
                        (Decision.decision_type, after_type, False),
                        (Decision.id, after_id, False),
                    ]
                )
            )
        stmt = stmt.order_by(
            Decision.last_evaluated_local_date.desc(),
            Decision.last_seen_local_date.desc(),
            Decision.decision_type,
            Decision.id,
        ).limit(limit + 1)
        rows = list(self._session.scalars(stmt))
        has_more = len(rows) > limit
        return rows[:limit], has_more

    def latest_observations_of(
        self, decision_ids: Iterable[UUID]
    ) -> dict[UUID, DecisionObservation]:
        """The single most recent Observation of each of `decision_ids`, loaded in ONE query
        (never a SELECT per Decision): `DISTINCT ON` the decision, ordered by the same memory
        order `history()` uses (`as_of_local_date`, then `DecisionRun.run_sequence`, then the
        observation id as a final tie-break), each DESC to keep the first row of every group."""
        ids = list(decision_ids)
        if not ids:
            return {}
        stmt = (
            select(DecisionObservation)
            .join(DecisionRun, DecisionObservation.decision_run_id == DecisionRun.id)
            .where(
                DecisionObservation.workspace_id == self._tenant.workspace_id,
                DecisionObservation.decision_id.in_(ids),
            )
            .distinct(DecisionObservation.decision_id)
            .order_by(
                DecisionObservation.decision_id,
                DecisionObservation.as_of_local_date.desc(),
                DecisionRun.run_sequence.desc(),
                DecisionObservation.id.desc(),
            )
        )
        return {obs.decision_id: obs for obs in self._session.scalars(stmt)}

    def history_page_desc(
        self,
        decision_id: UUID,
        *,
        limit: int,
        after: tuple[date, int, UUID] | None,
    ) -> tuple[Sequence[tuple[DecisionObservation, int]], bool]:
        """A keyset-paginated, NEWEST-FIRST page of one Decision's Observations: `as_of_local_date
        DESC, run_sequence DESC, observation id` (the API's own contract - the DESC mirror of
        `history()`'s internal ASC memory order, which Gate 11 callers keep relying on unchanged).
        Each row is paired with its run's `run_sequence` so the caller can build the next cursor
        without a further query."""
        stmt = (
            select(DecisionObservation, DecisionRun.run_sequence)
            .join(DecisionRun, DecisionObservation.decision_run_id == DecisionRun.id)
            .where(
                DecisionObservation.workspace_id == self._tenant.workspace_id,
                DecisionObservation.decision_id == decision_id,
            )
        )
        if after is not None:
            after_as_of, after_sequence, after_id = after
            stmt = stmt.where(
                _seek_predicate(
                    [
                        (DecisionObservation.as_of_local_date, after_as_of, True),
                        (DecisionRun.run_sequence, after_sequence, True),
                        (DecisionObservation.id, after_id, True),
                    ]
                )
            )
        stmt = stmt.order_by(
            DecisionObservation.as_of_local_date.desc(),
            DecisionRun.run_sequence.desc(),
            DecisionObservation.id.desc(),
        ).limit(limit + 1)
        rows = [(row[0], row[1]) for row in self._session.execute(stmt)]
        has_more = len(rows) > limit
        return rows[:limit], has_more


__all__ = ["DecisionRepository", "IdentityKey"]

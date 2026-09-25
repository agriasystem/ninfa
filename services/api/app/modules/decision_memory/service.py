"""DecisionMemoryService: the internal READ SIDE of the Decision Layer.

No public business API, no UI, no recommendation: this is a plain, framework-free class a future
gate's authenticated endpoint (or worker, or another service) can call, exactly like every other
read path in this codebase. It never writes: `DecisionService.sync()` is the only write path.

Gate 12 (Decision API V1) added the three methods below the `# --- Gate 12` marker: the typed feed
of a property/as-of, a keyset-paginated Decision list page (with its latest Observations loaded
set-based) and a keyset-paginated, newest-first Observation history page. All three are read-only,
call no detector and call `PriorityService` nowhere - they read exactly what Gate 11 persisted.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.types import (
    DecisionListPage,
    FeedItem,
    FeedResult,
    FeedState,
    HistoryObservation,
    HistoryPage,
)
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.repository import DecisionRepository
from app.modules.decisions.types import DecisionStatus
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

    # --- Gate 12: Decision API V1 -------------------------------------------------------------

    def get_feed(self, property_id: UUID, as_of_local_date: date) -> FeedResult:
        """The typed feed state of one property/as-of, built ONLY from the counts and rows the
        LATEST `DecisionRun` of that exact as-of already persisted - never a fresh Priority run,
        never a detector call. See `FeedState`'s own docstring for the exact state rules."""
        run = self._repo.latest_run(property_id, as_of_local_date)
        if run is None:
            return FeedResult(property_id, as_of_local_date, FeedState.NOT_PROCESSED, None)

        if run.triggered_count > 0:
            state = FeedState.ACTION_REQUIRED
        elif run.insufficient_count > 0 or run.suppressed_count > 0:
            state = FeedState.DATA_QUALITY_LIMITED
        else:
            state = FeedState.NO_ACTION_REQUIRED

        items: tuple[FeedItem, ...] = ()
        if state is FeedState.ACTION_REQUIRED:
            items = tuple(
                FeedItem(observation=observation, decision=decision)
                for observation, decision in self._repo.feed_rows(run.id)
            )
        return FeedResult(property_id, as_of_local_date, state, run, items)

    def list_decisions_page(
        self,
        property_id: UUID,
        *,
        status: DecisionStatus | None,
        decision_type: PriorityDecisionType | None,
        limit: int,
        after: tuple[date, date, PriorityDecisionType, UUID] | None,
    ) -> DecisionListPage:
        """Memory/lifecycle, not only today's run: every Decision of `property_id` (optionally
        filtered), stable-ordered `last_evaluated_local_date DESC, last_seen_local_date DESC,
        decision_type, decision_id` - deliberately NEVER by priority (that belongs to an
        Observation, which an OPEN Decision may not even have in the latest run - see
        `docs/architecture/decision-api-v1.md`, "Decision list order"). The latest Observation of
        every Decision in the page is loaded in one further set-based query."""
        decisions, has_more = self._repo.list_decisions_page(
            property_id, status=status, decision_type=decision_type, limit=limit, after=after
        )
        latest = self._repo.latest_observations_of(decision.id for decision in decisions)
        return DecisionListPage(tuple(decisions), latest, has_more)

    def get_latest_observation(self, decision_id: UUID) -> DecisionObservation | None:
        """The single most recent Observation of ONE Decision - the one-id case of
        `latest_observations_of`, still the same set-based `DISTINCT ON` query, never a second
        query shape to reason about."""
        return self._repo.latest_observations_of([decision_id]).get(decision_id)

    def get_history_page_desc(
        self, decision_id: UUID, *, limit: int, after: tuple[date, int, UUID] | None
    ) -> HistoryPage:
        """The API's own NEWEST-FIRST, keyset-paginated history contract - distinct from
        `get_history()` above, whose ASC, non-paginated order stays exactly as Gate 11 left it for
        its own callers/tests."""
        rows, has_more = self._repo.history_page_desc(decision_id, limit=limit, after=after)
        items = tuple(
            HistoryObservation(observation=observation, run_sequence=run_sequence)
            for observation, run_sequence in rows
        )
        return HistoryPage(items, has_more)


__all__ = ["DecisionMemoryService"]

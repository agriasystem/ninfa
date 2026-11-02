"""Where a property's analysis stands against its data: a descriptor BESIDE the feed, never in it.

`FeedState` says what TODAY's run concluded, coverage what it looked at, freshness when its data
were imported. None of them can say "new data has arrived and the analysis is being updated", and
none is stretched to: this says it, from three facts already stored - the imports (`import_jobs`),
the runs (`decision_runs`) and the refresh jobs (`queue.py`). Nothing is recorded for it, so nothing
can disagree with them.

Read-only; the clock is passed in.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.queue import (
    QueuedJobStatus,
    QueuedRefresh,
    enqueue_refresh,
    latest_refresh,
)
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository

# A refresh still waiting or running after this long is said to be taking longer than usual (the
# worker may be stopped): it is not "in progress" for ever, and it is not called a failure either.
DELAYED_AFTER = timedelta(minutes=5)


class AnalysisUpdateState(StrEnum):
    NO_DATA = "NO_DATA"  # nothing imported yet
    NEEDS_BOOKINGS = "NEEDS_BOOKINGS"  # data, but no bookings: the engines have nothing to run on
    SEVERAL_SOURCES = "SEVERAL_SOURCES"  # several booking sources: NINFA does not choose one
    NEW_DATA = "NEW_DATA"  # imports newer than the analysis, and no refresh under way
    IN_PROGRESS = "IN_PROGRESS"  # a refresh is waiting for the worker or running
    DELAYED = "DELAYED"  # the same, for longer than usual
    DEFERRED = "DEFERRED"  # today keeps its first observation: due again at `next_attempt_at`
    FAILED = "FAILED"  # the refresh failed: the imported data are fine, the analysis is older
    UP_TO_DATE = "UP_TO_DATE"  # the analysis has seen every import


# What the person can ask for again: nothing else is waiting, or could run.
_REFRESHABLE = frozenset({AnalysisUpdateState.NEW_DATA, AnalysisUpdateState.FAILED})


@dataclass(frozen=True, slots=True)
class AnalysisStatus:
    state: AnalysisUpdateState
    # The kinds of data the property holds, whatever was analysed: a partial property is not empty.
    imported_domains: tuple[DataSourceDomain, ...]
    latest_import_at: datetime | None
    last_analysis_at: datetime | None
    next_attempt_at: datetime | None

    @property
    def can_retry(self) -> bool:
        return self.state in _REFRESHABLE


def _state_of_job(
    job: QueuedRefresh, latest_import_at: datetime, now: datetime
) -> AnalysisUpdateState | None:
    """What the latest job says, or None when it says nothing about the latest import."""
    if job.status in (QueuedJobStatus.TODO, QueuedJobStatus.DOING):
        if job.status is QueuedJobStatus.TODO and (
            job.scheduled_at is not None and job.scheduled_at > now
        ):
            return AnalysisUpdateState.DEFERRED
        since = job.last_event_at
        if since is not None and now - since > DELAYED_AFTER:
            return AnalysisUpdateState.DELAYED
        return AnalysisUpdateState.IN_PROGRESS
    # A job queued before the latest import finished did not necessarily see it (the request for
    # that import may not have reached the queue): only the runs can tell, below.
    if job.queued_at is None or job.queued_at < latest_import_at:
        return None
    if job.status is QueuedJobStatus.SUCCEEDED:
        return AnalysisUpdateState.UP_TO_DATE
    if job.status is QueuedJobStatus.FAILED:
        return AnalysisUpdateState.FAILED
    return None  # cancelled or aborted: nothing was concluded


class AnalysisStatusService:
    """Tenant-scoped. `status` only reads; `retry` queues a refresh and owns its transaction."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._imports = ImportJobRepository(session, tenant)
        self._sources = DataSourceRepository(session, tenant)

    def _last_analysis_at(self, property_id: UUID) -> datetime | None:
        return self._session.scalar(
            select(func.max(DecisionRun.created_at)).where(
                DecisionRun.workspace_id == self._tenant.workspace_id,
                DecisionRun.property_id == property_id,
            )
        )

    def _booking_sources(self, property_id: UUID) -> list[DataSource]:
        return [
            source
            for source in self._sources.list_all(property_id=property_id)
            if source.domain == DataSourceDomain.BOOKINGS
        ]

    def status(self, property_id: UUID, now: datetime | None = None) -> AnalysisStatus:
        now = datetime.now(UTC) if now is None else now
        imports = self._imports.latest_succeeded_by_domain(property_id)
        domains = tuple(domain for domain in DataSourceDomain if domain in imports)
        latest_import_at = max(imports.values(), default=None)
        last_analysis_at = self._last_analysis_at(property_id)

        def answer(
            state: AnalysisUpdateState, next_attempt_at: datetime | None = None
        ) -> AnalysisStatus:
            return AnalysisStatus(
                state, domains, latest_import_at, last_analysis_at, next_attempt_at
            )

        if latest_import_at is None:
            return answer(AnalysisUpdateState.NO_DATA)
        if DataSourceDomain.BOOKINGS not in imports:
            return answer(AnalysisUpdateState.NEEDS_BOOKINGS)
        if len(self._booking_sources(property_id)) > 1:
            return answer(AnalysisUpdateState.SEVERAL_SOURCES)

        job = latest_refresh(self._session, self._tenant, property_id)
        state = None if job is None else _state_of_job(job, latest_import_at, now)
        if state is not None:
            assert job is not None
            deferred = state is AnalysisUpdateState.DEFERRED
            return answer(state, job.scheduled_at if deferred else None)
        # No job says anything about the latest import (imported before refreshes existed, or the
        # request never reached the queue): the runs do.
        if last_analysis_at is not None and last_analysis_at >= latest_import_at:
            return answer(AnalysisUpdateState.UP_TO_DATE)
        return answer(AnalysisUpdateState.NEW_DATA)

    def retry(self, property_id: UUID, now: datetime | None = None) -> AnalysisStatus:
        """The recovery the page offers when nothing else will happen by itself: asking for a
        refresh in any other state changes nothing (there is one waiting, or nothing to run on)."""
        current = self.status(property_id, now)
        if not current.can_retry:
            return current
        try:
            enqueue_refresh(self._session, self._tenant, property_id)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return self.status(property_id, now)


__all__ = ["DELAYED_AFTER", "AnalysisStatus", "AnalysisStatusService", "AnalysisUpdateState"]

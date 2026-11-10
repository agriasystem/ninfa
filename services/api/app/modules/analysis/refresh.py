"""The refresh after an import: what to analyse now that new data has arrived, decided at run time.

    import succeeded -> a job on the queue (`queue.py`) -> the worker -> `run_refresh` -> the shared
    orchestration (`service.run_property_analysis`)

ORCHESTRATION ONLY, like the module it calls: no detector, no threshold. Only the CHOICES an
operator would make by hand are made here, and only from what is really stored:

* bookings: the property's ONE active booking source with a successful import, over the same 30
  stay nights from the property-local today as the automatic analysis. Every engine needs it
  (their targets and denominators are its snapshots): with none, nothing runs, and the status
  says so;
* labor: the ONE active labor source, on the work dates of that window it really has entries for -
  a date it says nothing about is not evaluated, and so is not reported as "not enough data";
* costs: the concluded months the invoices really touch, however many a file spans - never the
  month in progress (invoices arrive after the fact) and never a month assumed from the calendar.
  The days of those months that have no snapshot yet are rebuilt from the bookings, where the room
  inventory says how many rooms there were (`history.py`): a refresh asked for by an inventory saved
  from an earlier date is what lets a past month's cost per occupied room be calculated.

The history rebuilt is READABLE, never a sample: it is what the bookings say today about days that
are over, kept for the figures that want how a day ended. Expected, the pickup and the curves read
only what NINFA observed (`observation.py`), so adding a past night changes no stored baseline and
no comparable, and the order of the history and of the day's analysis does not matter for them.

A failure propagates and fails the job (fail loud: nothing is synced, the imported data stay as they
are, the status says so). Bookings changed since today's observation are simply observed again: the
day's next revision, analysed now. What is left of `DEFERRED` is a stored row NINFA cannot observe
over on today's key, a reconstruction (the property's time zone was changed, so today is a day that
already ended elsewhere): that clears by itself on the next local day, so it is not a failure.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.history import HistoryBackfill, backfill_lead_zero_history
from app.modules.analysis.policy import check_configuration
from app.modules.analysis.scope import MAX_COST_MONTHS, active_sources, analysis_request
from app.modules.analysis.service import (
    AnalysisRunRequest,
    AnalysisRunResult,
    run_property_analysis,
)
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import ImportJobRepository
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.localtime import local_date_of, local_day_start

# A deferred refresh runs just after local midnight.
_NEXT_DAY_MARGIN = timedelta(minutes=5)


class RefreshOutcomeKind(StrEnum):
    RAN = "RAN"
    SKIPPED = "SKIPPED"  # nothing to run on: `skip_reason` says why, and nothing was written
    DEFERRED = "DEFERRED"  # today's key cannot be observed yet: due again at `retry_at`


class RefreshSkipReason(StrEnum):
    NO_BOOKING_SOURCE = "NO_BOOKING_SOURCE"
    SEVERAL_BOOKING_SOURCES = "SEVERAL_BOOKING_SOURCES"
    NO_BOOKING_IMPORT = "NO_BOOKING_IMPORT"
    NOT_USABLE = "NOT_USABLE"  # the workspace, the property or its time zone cannot be analysed


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    request: AnalysisRunRequest
    local_today: date
    retry_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    kind: RefreshOutcomeKind
    skip_reason: RefreshSkipReason | None = None
    retry_at: datetime | None = None
    result: AnalysisRunResult | None = None
    # Days of past months stored from the bookings before this analysis (see `history.py`).
    history_days_rebuilt: int = 0


def plan_refresh(
    session: Session, tenant: TenantContext, property_id: UUID, now: datetime
) -> RefreshPlan | RefreshSkipReason:
    """What a refresh would analyse right now, or why there is nothing to run on. Reads only."""
    sources = active_sources(session, tenant, property_id, DataSourceDomain.BOOKINGS)
    if not sources:
        return RefreshSkipReason.NO_BOOKING_SOURCE
    if len(sources) > 1:
        return RefreshSkipReason.SEVERAL_BOOKING_SOURCES
    source = sources[0]
    check = check_configuration(session, tenant.workspace_id, property_id, source.id)
    if check.blocker is not None or check.timezone is None:
        return RefreshSkipReason.NOT_USABLE
    if ImportJobRepository(session, tenant).latest_succeeded_for_data_source(source.id) is None:
        return RefreshSkipReason.NO_BOOKING_IMPORT

    local_today = local_date_of(now, check.timezone)
    return RefreshPlan(
        request=analysis_request(session, tenant, property_id, source.id, local_today),
        local_today=local_today,
        retry_at=local_day_start(local_today + timedelta(days=1), check.timezone)
        + _NEXT_DAY_MARGIN,
    )


def run_refresh(
    session: Session, workspace_id: UUID, property_id: UUID, now: datetime | None = None
) -> RefreshOutcome:
    """One refresh of one property. Anything but a key that cannot be observed yet propagates."""
    now = datetime.now(UTC) if now is None else now
    tenant = TenantContext(workspace_id=workspace_id)
    plan = plan_refresh(session, tenant, property_id, now)
    if isinstance(plan, RefreshSkipReason):
        return RefreshOutcome(RefreshOutcomeKind.SKIPPED, skip_reason=plan)
    history = _rebuild_history(session, tenant, property_id, plan, now)
    try:
        result = run_property_analysis(session, plan.request)
    except SnapshotError as error:
        if error.code != SnapshotErrorCode.CONFLICT:
            raise
        session.rollback()
        return RefreshOutcome(
            RefreshOutcomeKind.DEFERRED,
            retry_at=plan.retry_at,
            history_days_rebuilt=history.rebuilt,
        )
    return RefreshOutcome(
        RefreshOutcomeKind.RAN, result=result, history_days_rebuilt=history.rebuilt
    )


def _rebuild_history(
    session: Session,
    tenant: TenantContext,
    property_id: UUID,
    plan: RefreshPlan,
    now: datetime,
) -> HistoryBackfill:
    return backfill_lead_zero_history(
        session,
        tenant,
        property_id=property_id,
        data_source_id=plan.request.booking_data_source_id,
        cost_months=plan.request.cost_months,
        local_today=plan.local_today,
        now=now,
    )


__all__ = [
    "MAX_COST_MONTHS",
    "RefreshOutcome",
    "RefreshOutcomeKind",
    "RefreshPlan",
    "RefreshSkipReason",
    "plan_refresh",
    "run_refresh",
]

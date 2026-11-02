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

A failure propagates and fails the job (fail loud: nothing is synced, the imported data stay as they
are, the status says so). The one expected refusal is the bookings having changed since today's
observation: a day keeps its first observation, on purpose (booking-snapshots-v1.md). That is not a
failure and is not forced: the refresh is simply due again on the next local day.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.automatic import automatic_stay_window
from app.modules.analysis.policy import check_configuration
from app.modules.analysis.service import (
    AnalysisRunRequest,
    AnalysisRunResult,
    run_property_analysis,
)
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.intelligence.labor.aggregation import latest_snapshot_rows_by_work_date
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.snapshots.calculation import date_range
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.localtime import local_date_of, local_day_start

# How many concluded months of invoices one refresh evaluates at most, newest first: an upper bound
# for a file that spans years, not a business rule.
MAX_COST_MONTHS = 12
# A deferred refresh runs just after local midnight: the new day's first observation.
_NEXT_DAY_MARGIN = timedelta(minutes=5)


class RefreshOutcomeKind(StrEnum):
    RAN = "RAN"
    SKIPPED = "SKIPPED"  # nothing to run on: `skip_reason` says why, and nothing was written
    DEFERRED = "DEFERRED"  # the day keeps its first observation: due again at `retry_at`


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


def _active_sources(
    session: Session, tenant: TenantContext, property_id: UUID, domain: DataSourceDomain
) -> list[DataSource]:
    return [
        source
        for source in DataSourceRepository(session, tenant).list_all(property_id=property_id)
        if source.domain == domain
    ]


def _labor_scope(
    session: Session,
    tenant: TenantContext,
    property_id: UUID,
    local_today: date,
    days: list[date],
) -> tuple[UUID | None, frozenset[date] | None]:
    """The labor source to evaluate and the dates it really covers. With no usable source, or one
    with nothing in the window, labor stays out of this run (`SKIPPED` in its coverage)."""
    sources = _active_sources(session, tenant, property_id, DataSourceDomain.LABOR)
    if len(sources) != 1:
        return None, None
    entries = LaborEvaluationRepository(session, tenant).entries_as_of(
        sources[0].id, local_today, days
    )
    dates = frozenset(latest_snapshot_rows_by_work_date(entries))
    return (sources[0].id, dates) if dates else (None, None)


def _cost_months(
    session: Session, tenant: TenantContext, property_id: UUID, local_today: date
) -> tuple[tuple[int, int], ...]:
    """The concluded months the property's invoices touch, oldest first (the order of a history)."""
    months = CostLineRepository(session, tenant).months_with_lines(
        property_id,
        before=CalendarMonth.of(local_today).start,
        limit=MAX_COST_MONTHS,
    )
    return tuple((month.year, month.month) for month in sorted(months))


def plan_refresh(
    session: Session, tenant: TenantContext, property_id: UUID, now: datetime
) -> RefreshPlan | RefreshSkipReason:
    """What a refresh would analyse right now, or why there is nothing to run on. Reads only."""
    sources = _active_sources(session, tenant, property_id, DataSourceDomain.BOOKINGS)
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
    start, end = automatic_stay_window(local_today)
    labor_source_id, labor_dates = _labor_scope(
        session, tenant, property_id, local_today, list(date_range(start, end))
    )
    return RefreshPlan(
        request=AnalysisRunRequest(
            workspace_id=tenant.workspace_id,
            property_id=property_id,
            booking_data_source_id=source.id,
            stay_date_start=start,
            stay_date_end=end,
            labor_data_source_id=labor_source_id,
            labor_work_dates=labor_dates,
            cost_periods=_cost_months(session, tenant, property_id, local_today),
        ),
        local_today=local_today,
        retry_at=local_day_start(local_today + timedelta(days=1), check.timezone)
        + _NEXT_DAY_MARGIN,
    )


def run_refresh(
    session: Session, workspace_id: UUID, property_id: UUID, now: datetime | None = None
) -> RefreshOutcome:
    """One refresh of one property. Anything but the day's own observation rule propagates."""
    now = datetime.now(UTC) if now is None else now
    tenant = TenantContext(workspace_id=workspace_id)
    plan = plan_refresh(session, tenant, property_id, now)
    if isinstance(plan, RefreshSkipReason):
        return RefreshOutcome(RefreshOutcomeKind.SKIPPED, skip_reason=plan)
    try:
        result = run_property_analysis(session, plan.request)
    except SnapshotError as error:
        if error.code != SnapshotErrorCode.CONFLICT:
            raise
        session.rollback()
        return RefreshOutcome(RefreshOutcomeKind.DEFERRED, retry_at=plan.retry_at)
    return RefreshOutcome(RefreshOutcomeKind.RAN, result=result)


__all__ = [
    "MAX_COST_MONTHS",
    "RefreshOutcome",
    "RefreshOutcomeKind",
    "RefreshPlan",
    "RefreshSkipReason",
    "plan_refresh",
    "run_refresh",
]

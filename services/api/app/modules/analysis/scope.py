"""What one analysis of a property looks at, chosen from what is really stored.

The refresh after an import and the daily analysis are the same analysis: the booking source, the
same 30 stay nights from the property-local today, the labor source on the dates it really has
entries for, the concluded months the invoices really touch. Only WHICH booking source differs: the
refresh takes the property's one active source, the daily analysis the one its policy names.

ORCHESTRATION ONLY: no detector, no threshold, no clock (the local day is passed in). Reads only.
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.service import AnalysisRunRequest
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.snapshots.calculation import date_range

AUTOMATIC_STAY_WINDOW_DAYS = 30
# How many concluded months of invoices one analysis evaluates at most, newest first: an upper bound
# for a file that spans years, not a business rule.
MAX_COST_MONTHS = 12


def automatic_stay_window(local_today: date) -> tuple[date, date]:
    """`(start, end)` inclusive: exactly `AUTOMATIC_STAY_WINDOW_DAYS` dates from `local_today`."""
    return local_today, local_today + timedelta(days=AUTOMATIC_STAY_WINDOW_DAYS - 1)


def active_sources(
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
    sources = active_sources(session, tenant, property_id, DataSourceDomain.LABOR)
    if len(sources) != 1:
        return None, None
    dates = frozenset(
        LaborEvaluationRepository(session, tenant).current_plan(sources[0].id, local_today, days)
    )
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


def analysis_request(
    session: Session,
    tenant: TenantContext,
    property_id: UUID,
    booking_data_source_id: UUID,
    local_today: date,
) -> AnalysisRunRequest:
    """The analysis of `local_today` on this booking source and on whatever else is really there."""
    start, end = automatic_stay_window(local_today)
    labor_source_id, labor_dates = _labor_scope(
        session, tenant, property_id, local_today, list(date_range(start, end))
    )
    return AnalysisRunRequest(
        workspace_id=tenant.workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        stay_date_start=start,
        stay_date_end=end,
        labor_data_source_id=labor_source_id,
        labor_work_dates=labor_dates,
        cost_periods=_cost_months(session, tenant, property_id, local_today),
    )


__all__ = [
    "AUTOMATIC_STAY_WINDOW_DAYS",
    "MAX_COST_MONTHS",
    "active_sources",
    "analysis_request",
    "automatic_stay_window",
]

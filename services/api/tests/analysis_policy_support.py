"""Free-function helpers for the Gate 26B automatic-analysis policy tests (the repository pattern:
they extend the shared `factory` fixture, never override it)."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis import AnalysisPolicyService, PropertyAnalysisPolicy
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSource, ImportJob, ImportJobStatus
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_support import INSUFFICIENT, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant


def import_at(
    factory: BookingFactory,
    data_source: DataSource,
    finished_at: datetime,
    status: ImportJobStatus = ImportJobStatus.SUCCEEDED,
) -> ImportJob:
    """An import of `data_source` that ended at exactly `finished_at` (UTC)."""
    job = ImportJob(
        workspace_id=data_source.workspace_id,
        property_id=data_source.property_id,
        data_source_id=data_source.id,
        status=status,
        started_at=finished_at,
        finished_at=finished_at,
        error_code="boom" if status is ImportJobStatus.FAILED else None,
        error_message="boom" if status is ImportJobStatus.FAILED else None,
    )
    factory.session.add(job)
    factory.session.flush()
    return job


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def enable(session: Session, tenant: Tenant) -> PropertyAnalysisPolicy:
    """Enable automation for a factory tenant with its own BOOKINGS source."""
    return AnalysisPolicyService(session, tenant.context).enable(
        tenant.property.id, tenant.data_source.id
    )


def decision_run_on(
    session: Session, tenant: Tenant, as_of_local_date: date, data_source_id: UUID | None = None
) -> DecisionRun:
    """A real persisted DecisionRun for the tenant's property on `as_of_local_date`."""
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of_local_date)
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=data_source_id or tenant.data_source.id,
        stay_date=as_of_local_date,
        snapshot_local_date=as_of_local_date,
        status=INSUFFICIENT,
    )
    outcome = sync_run(session, TenantContext(tenant.workspace.id), context, [evaluation])
    run = session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    return run

"""Shared helpers for the Dati overview (Dati UI V1) tests.

Builds on the helpers Mia Home's own data-layer tests already use (`tests.ask_home_support`):
real OBSERVED snapshot rows, a real persisted run through `DecisionService.sync()`, real
provenance - read back through the real `DecisionMemoryService`, exactly like production. Nothing
here hand-builds a feed shape.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.data_overview.distribution import OtaEvaluator
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import DataOverview
from app.modules.decisions.coverage import AnalysisCoverage
from app.modules.ingestion.models import DataSource, ImportJob, ImportJobStatus
from tests.ask_home_support import (
    D1,
    booking_only_coverage,
    full_coverage,
    provenance_for,
    seed_night_snapshots,
    sync_feed,
    utc,
)
from tests.decision_support import Evaluation
from tests.support import BookingFactory, Tenant

AS_OF = D1  # 2026-08-01, a Saturday
IMPORT_FINISHED_AT = utc(2026, 8, 1, 7, 15)


def overview_url(property_id: UUID, as_of: str, period: int | str | None = None) -> str:
    base = f"/api/v1/properties/{property_id}/data/overview?as_of={as_of}"
    return base if period is None else f"{base}&period={period}"


def night_range(as_of: date, days: int = 30) -> list[date]:
    return [as_of + timedelta(days=offset) for offset in range(days)]


def uniform_nights(
    as_of: date, rooms: int, capacity: int | None = 40, days: int = 30
) -> dict[date, tuple[int, int | None]]:
    """`days` nights from `as_of`, all with the same rooms on books and capacity."""
    return {day: (rooms, capacity) for day in night_range(as_of, days)}


def seed_run(
    db_session: Session,
    tenant: Tenant,
    *,
    as_of: date = AS_OF,
    nights: Mapping[date, tuple[int, int | None]] | None = None,
    evaluations: Sequence[Evaluation] = (),
    coverage: AnalysisCoverage | None = None,
    finished_at: datetime | None = IMPORT_FINISHED_AT,
    with_provenance: bool = True,
    unknown_coverage: bool = False,
) -> None:
    """Snapshots of the analysis day (when `nights` is given) and one persisted run for it.

    `coverage` defaults to Revenue + Distribution evaluated, Costs + Labor skipped - the automatic
    analysis policy's own coverage."""
    if nights:
        seed_night_snapshots(db_session, tenant, as_of, nights)
    sync_feed(
        db_session,
        tenant,
        list(evaluations),
        as_of=as_of,
        coverage=(
            None
            if unknown_coverage
            else (coverage if coverage is not None else booking_only_coverage())
        ),
        provenance=(
            provenance_for(tenant, finished_at or IMPORT_FINISHED_AT) if with_provenance else None
        ),
    )


def succeeded_import(
    factory: BookingFactory, source: DataSource, finished_at: datetime
) -> ImportJob:
    """A real SUCCEEDED import job of `source` that finished at `finished_at` (every lifecycle CHECK
    of `import_jobs` satisfied)."""
    job = factory.import_job(source)
    job.status = ImportJobStatus.SUCCEEDED
    job.started_at = finished_at - timedelta(minutes=5)
    job.finished_at = finished_at
    factory.session.flush()
    return job


def overview_of(
    db_session: Session,
    tenant: Tenant,
    *,
    as_of: date = AS_OF,
    period: int = 30,
    ota_evaluator: OtaEvaluator | None = None,
) -> DataOverview:
    return DataOverviewService(db_session, tenant.context, ota_evaluator=ota_evaluator).overview(
        tenant.property.id, as_of, period
    )


__all__ = [
    "AS_OF",
    "IMPORT_FINISHED_AT",
    "booking_only_coverage",
    "full_coverage",
    "night_range",
    "overview_of",
    "overview_url",
    "seed_run",
    "succeeded_import",
    "uniform_nights",
    "utc",
]

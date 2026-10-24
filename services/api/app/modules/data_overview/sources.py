"""Which data source a Dati block reads, and how fresh it is - without ever choosing silently.

Bookings: the source is the run's own (its persisted provenance), never inferred here.

Costs and labor are not recorded on the run (the automatic analysis skips both), so there is no
"source the analysis used". Dati reads such a domain only when the property has EXACTLY ONE active
data source of it: with none there is nothing to read, with several NINFA does not pick one - it
says so. The freshness of a domain is the same fact Gate 23B states for bookings: when the latest
SUCCEEDED import of that exact source finished. Never a property-wide maximum across several
sources, never a CURRENT/STALE judgement, never one timestamp standing for several domains."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.data_overview.types import DomainFreshness, FreshnessReason
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    source_id: UUID | None
    reason: FreshnessReason | None  # NO_SOURCE / SEVERAL_SOURCES when `source_id` is None


def booking_provenance_of(run: DecisionRun | None) -> tuple[UUID | None, datetime | None]:
    """`(booking data source id, last successful import finished_at)` the run itself recorded.
    `(None, None)` for no run, a run predating provenance, or an unreadable one."""
    if run is None or run.input_provenance is None:
        return None, None
    try:
        provenance = RunInputProvenance.from_json(run.input_provenance)
    except (KeyError, ValueError):
        return None, None
    bookings = provenance.bookings
    finished = bookings.last_successful_import_finished_at
    return bookings.data_source_id, None if finished is None else finished.astimezone(UTC)


def booking_freshness_of(run: DecisionRun | None) -> DomainFreshness:
    source_id, finished_at = booking_provenance_of(run)
    if finished_at is None:
        reason = FreshnessReason.NO_SOURCE if source_id is None else FreshnessReason.NO_IMPORT
        return DomainFreshness(known=False, finished_at=None, reason=reason)
    return DomainFreshness(known=True, finished_at=finished_at, reason=None)


class PropertySources:
    """Read-only. Every read goes through the repositories of the request's `TenantContext`."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._sources = DataSourceRepository(session, tenant)
        self._imports = ImportJobRepository(session, tenant)

    def resolve(self, property_id: UUID, domain: DataSourceDomain) -> ResolvedSource:
        active = [
            source
            for source in self._sources.list_all(property_id=property_id)
            if source.domain == domain
        ]
        if not active:
            return ResolvedSource(None, FreshnessReason.NO_SOURCE)
        if len(active) > 1:
            return ResolvedSource(None, FreshnessReason.SEVERAL_SOURCES)
        return ResolvedSource(active[0].id, None)

    def freshness(self, source: ResolvedSource) -> DomainFreshness:
        if source.source_id is None:
            return DomainFreshness(known=False, finished_at=None, reason=source.reason)
        job = self._imports.latest_succeeded_for_data_source(source.source_id)
        if job is None or job.finished_at is None:
            return DomainFreshness(known=False, finished_at=None, reason=FreshnessReason.NO_IMPORT)
        return DomainFreshness(known=True, finished_at=job.finished_at.astimezone(UTC), reason=None)


__all__ = [
    "PropertySources",
    "ResolvedSource",
    "booking_freshness_of",
    "booking_provenance_of",
]

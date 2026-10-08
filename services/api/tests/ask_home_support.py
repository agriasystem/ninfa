"""Shared helpers for the Mia Home (property-level Ask, Home UI V1) backend tests.

Builds on `tests.decision_support` (real evaluations, real `DecisionService.sync()`) and
`tests.ask_ninfa_support` (the ONE fake `LanguageModelProvider`) - never a second hand-built feed
shape: every context a test inspects here comes from a real persisted run read back through the
real `DecisionMemoryService.get_feed()`, exactly like production.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import RevenueDecisionType
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider
from tests.decision_support import (
    Evaluation,
    RunOutcome,
    cost_evaluation,
    labor_evaluation,
    ota_evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.expected_support import add_snapshots, snapshot_row
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def ask_home_url(property_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/ask"


def sync_feed(
    db_session: Session,
    tenant: Tenant,
    evaluations: list[Evaluation],
    *,
    as_of: date = D1,
    coverage: AnalysisCoverage | None = None,
    provenance: RunInputProvenance | None = None,
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(
        db_session, TenantContext(tenant.workspace.id), context, evaluations, coverage, provenance
    )


def five_triggered_evaluations(
    factory: BookingFactory, tenant: Tenant, *, as_of: date = D1
) -> list[Evaluation]:
    """One TRIGGERED evaluation of every one of the five real decision types."""
    labor_source_id = factory.data_source(tenant.property).id
    return [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY,
            snapshot_local_date=as_of,
        ),
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=date(2026, 8, 20),
            snapshot_local_date=as_of,
            decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
        ),
        ota_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=as_of,
        ),
        cost_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            target_period_start=date(2026, 7, 1),
        ),
        labor_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            labor_data_source_id=labor_source_id,
            target_work_date=as_of,
        ),
    ]


def booking_only_coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, DomainCoverageStatus.EVALUATED),
            DomainCoverage(
                AnalysisDomain.COSTS, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
            DomainCoverage(
                AnalysisDomain.LABOR, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
        )
    )


def full_coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=tuple(
            DomainCoverage(domain, DomainCoverageStatus.EVALUATED) for domain in AnalysisDomain
        )
    )


def known_provenance(finished_at: datetime) -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=uuid4(),
            import_job_id=uuid4(),
            last_successful_import_finished_at=finished_at,
        )
    )


def provenance_for(tenant: Tenant, finished_at: datetime) -> RunInputProvenance:
    """Provenance naming the tenant's REAL booking data source - the one `HomeDataService` reads the
    stored snapshots of (`known_provenance` names a random one, enough for freshness-only tests)."""
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=tenant.data_source.id,
            import_job_id=tenant.import_job.id,  # both-set-or-both-None (Gate 23B)
            last_successful_import_finished_at=finished_at,
        )
    )


def seed_night_snapshots(
    db_session: Session,
    tenant: Tenant,
    as_of: date,
    nights: Mapping[date, tuple[int, int | None]],
    *,
    revenue_per_room: Decimal = Decimal("100.00"),
) -> None:
    """OBSERVED snapshot rows of the analysis day `as_of`: `{stay night: (rooms on books, rooms
    available or None for an unknown capacity)}`. Every CHECK constraint stays satisfied."""
    rows = []
    for stay_date, (rooms, available) in nights.items():
        row = snapshot_row(tenant, as_of, stay_date, rooms=rooms)
        row["booking_count_on_books"] = 0 if rooms == 0 else max(1, rooms // 2)
        row["allocated_room_revenue_on_books"] = revenue_per_room * rooms
        row["adr_on_books"] = revenue_per_room if rooms > 0 else None
        if available is not None and available > 0:
            row["rooms_available"] = available
            row["occupancy_on_books"] = (Decimal(rooms) * 100 / Decimal(available)).quantize(
                Decimal("0.01")
            )
        rows.append(row)
    add_snapshots(db_session, tenant, rows)


def unknown_provenance() -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=uuid4(), import_job_id=None, last_successful_import_finished_at=None
        )
    )


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def answered_provider(
    answer: str = "NINFA ha rilevato una sola decisione oggi, la prima nel suo ordine.",
    *,
    refs: tuple[str, ...] = ("DECISIONS",),
    status: ModelAnswerStatus = ModelAnswerStatus.ANSWERED,
    limitations: tuple[str, ...] = (),
) -> DeterministicFakeLanguageModelProvider:
    return DeterministicFakeLanguageModelProvider(
        answer=LanguageModelAnswer(
            status=status, answer=answer, grounding_refs=refs, limitations=limitations
        )
    )


__all__ = [
    "D1",
    "STAY",
    "answered_provider",
    "ask_home_url",
    "booking_only_coverage",
    "five_triggered_evaluations",
    "full_coverage",
    "known_provenance",
    "provenance_for",
    "seed_night_snapshots",
    "sync_feed",
    "unknown_provenance",
    "utc",
]

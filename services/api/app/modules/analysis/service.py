"""Shared production analysis orchestration (Gate 25B): the ONE function that composes Expected
calculation, all four detectors, priority ranking and decision persistence for one property.

It was extracted, unchanged in behaviour, from `app/cli/analysis.py` (Gate 21B) so the operator
CLI and the background worker task run EXACTLY the same code:

    CLI (argparse, slugs, print, exit codes) --\
                                                 --> run_property_analysis()
    Worker task (own Session, structured log) -/

ORCHESTRATION ONLY: every number is computed by the existing engines
(`ObservedSnapshotService`, `BookingExpectedService`, `RevenueDecisionService`,
`OtaDependencyService`, `CostDecisionService`, `LaborDecisionService`, `PriorityService`,
`DecisionService`). Nothing here recalculates anything or adds a business rule.

BOUNDARIES: this module takes a caller-owned `Session` and already-resolved ids. It never creates a
Session, resolves a slug, prints, knows an exit code, or imports the CLI, the worker or
Procrastinate. It makes no choice for the caller: no source auto-selection, no stay-window default,
no cost month default - an omitted optional domain is recorded as SKIPPED/NOT_REQUESTED.

The snapshot day is ALWAYS the real clock's "today" in the property's own time zone (see
`snapshots/common.py`); the same-day immutability of OBSERVED snapshots is unchanged: a second
run on the same day after the bookings changed raises the existing snapshot CONFLICT.

FAIL LOUD, NEVER A FALSE ALL-CLEAR (Gate 21A): no detector call below is wrapped in a try/except.
If one raises, the exception propagates and `DecisionService.sync()` is never reached.

COVERAGE (Gate 22) and PROVENANCE (Gate 23B) are built here, from the same booleans that decide
the optional steps and from the latest SUCCEEDED import of the EXACT booking data source used.
"""

from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.tenant import TenantContext
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.decisions.service import DecisionService
from app.modules.ingestion.repository import ImportJobRepository
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.priority.service import PriorityService, SourceEvaluation
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.labor.roles import LaborCategory
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.repository import BookingSnapshotRepository


class AnalysisInputError(AppError):
    """The explicit run request is internally inconsistent (never a data or engine failure)."""

    def __init__(self, message: str) -> None:
        super().__init__("analysis_invalid_input", message, status_code=HTTPStatus.BAD_REQUEST)


@dataclass(frozen=True, slots=True)
class AnalysisRunRequest:
    """Every execution choice, explicit and already resolved. `cost_year`/`cost_month` come
    together or not at all (checked here, the one place, so enqueueing a job and running one
    reject the same inconsistent request); `currency` falls back to the property's own currency."""

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    stay_date_start: date
    stay_date_end: date
    labor_data_source_id: UUID | None = None
    cost_year: int | None = None
    cost_month: int | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if (self.cost_year is None) != (self.cost_month is None):
            raise AnalysisInputError("cost_year and cost_month must be given together")


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    """What one run did. `cost_*`/`labor_*` fields are None when that domain was skipped."""

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    as_of_local_date: date

    snapshots_created: int
    snapshots_unchanged: int
    expected_created: int
    expected_unchanged: int
    expected_ready: int
    expected_insufficient: int

    revenue_target_count: int
    ota_status: str
    cost_currency: str | None
    cost_category_count: int | None
    labor_target_count: int | None
    labor_evaluation_count: int | None

    evaluation_count: int
    triggered_count: int
    clear_count: int
    insufficient_count: int
    not_applicable_count: int
    suppressed_count: int

    coverage: AnalysisCoverage
    provenance: RunInputProvenance

    decision_run_id: UUID
    is_idempotent_replay: bool
    decisions_created: int
    decisions_resolved: int
    decisions_reopened: int
    open_decisions_after_sync: int


def run_property_analysis(session: Session, request: AnalysisRunRequest) -> AnalysisRunResult:
    tenant = TenantContext(workspace_id=request.workspace_id)
    prop = PropertyRepository(session, tenant).get(request.property_id)
    if prop is None:
        raise NotFoundError("Property")

    booking_data_source_id = request.booking_data_source_id
    stay_date_start = request.stay_date_start
    stay_date_end = request.stay_date_end
    labor_data_source_id = request.labor_data_source_id
    cost_year = request.cost_year
    cost_month = request.cost_month

    # 1. Materialize today's OBSERVED booking snapshots - the ONLY step below that writes
    # anything before the final sync(). The snapshot day is the real clock's "today" in the
    # property's own time zone: never a caller-supplied date.
    snapshot_result = ObservedSnapshotService(session, tenant).take_snapshot(
        property_id=prop.id,
        data_source_id=booking_data_source_id,
        stay_date_start=stay_date_start,
        stay_date_end=stay_date_end,
    )
    as_of_local_date = snapshot_result.snapshot_date_first

    # 2. Expected baselines for those same targets.
    expected_result = BookingExpectedService(session, tenant).calculate_for_snapshot_date(
        property_id=prop.id,
        data_source_id=booking_data_source_id,
        snapshot_local_date=as_of_local_date,
        stay_date_start=stay_date_start,
        stay_date_end=stay_date_end,
    )

    evaluations: list[SourceEvaluation] = []

    # 3. Revenue: REV_PICKUP_LOW + REV_OCCUPANCY_RISK for every OBSERVED target in the window.
    signals = RevenueDecisionService(session, tenant).evaluate_snapshot_date(
        property_id=prop.id,
        data_source_id=booking_data_source_id,
        snapshot_local_date=as_of_local_date,
        stay_date_start=stay_date_start,
        stay_date_end=stay_date_end,
    )
    for signal in signals:
        evaluations.append(signal.pickup_low)
        evaluations.append(signal.occupancy_risk)

    # 4. OTA: property-wide, one evaluation.
    ota_evaluation = OtaDependencyService(session, tenant).evaluate(
        property_id=prop.id,
        booking_data_source_id=booking_data_source_id,
        as_of_local_date=as_of_local_date,
    )
    evaluations.append(ota_evaluation)

    # 5. Cost: only when the caller gave an explicit target month - never a hidden default.
    cost_currency: str | None = None
    cost_category_count: int | None = None
    if cost_year is not None and cost_month is not None:
        cost_currency = request.currency or prop.currency
        cost_evaluations = CostDecisionService(session, tenant).evaluate_month(
            property_id=prop.id,
            booking_data_source_id=booking_data_source_id,
            year=cost_year,
            month=cost_month,
            currency=cost_currency,
        )
        evaluations.extend(cost_evaluations)
        cost_category_count = len(cost_evaluations)

    # 6. Labor: only when the caller gave an explicit labor data source - one evaluation per
    # OBSERVED target snapshot and labor category, reusing the same targets as step 3.
    labor_target_count: int | None = None
    labor_evaluation_count: int | None = None
    if labor_data_source_id is not None:
        target_snapshots = BookingSnapshotRepository(session, tenant).list_for_snapshot_date(
            booking_data_source_id,
            as_of_local_date,
            stay_date_from=stay_date_start,
            stay_date_to=stay_date_end,
            origin=SnapshotOrigin.OBSERVED,
        )
        labor_service = LaborDecisionService(session, tenant)
        labor_evaluations = [
            labor_service.evaluate_overstaffing(
                target_booking_snapshot_id=target.id,
                labor_data_source_id=labor_data_source_id,
                labor_category=category,
            )
            for target in target_snapshots
            for category in LaborCategory
        ]
        evaluations.extend(labor_evaluations)
        labor_target_count = len(target_snapshots)
        labor_evaluation_count = len(labor_evaluations)

    # 7. Coverage (Gate 22): built from the SAME booleans that decided steps 5-6 above, never
    # reconstructed from the evaluations list afterward - see app.modules.decisions.coverage.
    # Revenue and OTA are unconditional, so REVENUE and DISTRIBUTION are always EVALUATED.
    coverage = AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, DomainCoverageStatus.EVALUATED)
            if cost_year is not None and cost_month is not None
            else DomainCoverage(
                AnalysisDomain.COSTS, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
            DomainCoverage(AnalysisDomain.LABOR, DomainCoverageStatus.EVALUATED)
            if labor_data_source_id is not None
            else DomainCoverage(
                AnalysisDomain.LABOR, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
        )
    )

    # 8. Provenance (Gate 23B): the latest SUCCEEDED import known, right now, for the EXACT
    # booking data source this run used. No successful import yet is a legitimate, non-fatal
    # outcome: freshness stays UNKNOWN, never fabricated.
    latest_booking_import = ImportJobRepository(session, tenant).latest_succeeded_for_data_source(
        booking_data_source_id
    )
    if latest_booking_import is None:
        provenance = RunInputProvenance(
            bookings=BookingProvenance(
                data_source_id=booking_data_source_id,
                import_job_id=None,
                last_successful_import_finished_at=None,
            )
        )
    else:
        assert latest_booking_import.finished_at is not None  # SUCCEEDED implies finished_at
        provenance = RunInputProvenance(
            bookings=BookingProvenance(
                data_source_id=booking_data_source_id,
                import_job_id=latest_booking_import.id,
                last_successful_import_finished_at=latest_booking_import.finished_at,
            )
        )

    # 9. Rank, then persist. Every evaluation gathered above reaches BOTH calls, or an exception
    # already propagated above and neither call happens.
    context = PriorityContext(
        workspace_id=tenant.workspace_id, property_id=prop.id, as_of_local_date=as_of_local_date
    )
    ranking_result = PriorityService().rank(context, evaluations)
    sync_result = DecisionService(session, tenant).sync(
        context, ranking_result, evaluations, coverage, provenance
    )

    return AnalysisRunResult(
        workspace_id=tenant.workspace_id,
        property_id=prop.id,
        booking_data_source_id=booking_data_source_id,
        as_of_local_date=as_of_local_date,
        snapshots_created=snapshot_result.created,
        snapshots_unchanged=snapshot_result.unchanged,
        expected_created=expected_result.created,
        expected_unchanged=expected_result.unchanged,
        expected_ready=expected_result.ready,
        expected_insufficient=expected_result.insufficient,
        revenue_target_count=len(signals),
        ota_status=ota_evaluation.status.value,
        cost_currency=cost_currency,
        cost_category_count=cost_category_count,
        labor_target_count=labor_target_count,
        labor_evaluation_count=labor_evaluation_count,
        evaluation_count=len(evaluations),
        triggered_count=ranking_result.candidate_count,
        clear_count=ranking_result.excluded_clear_count,
        insufficient_count=ranking_result.excluded_insufficient_count,
        not_applicable_count=ranking_result.excluded_not_applicable_count,
        suppressed_count=ranking_result.excluded_suppressed_count,
        coverage=coverage,
        provenance=provenance,
        decision_run_id=sync_result.decision_run_id,
        is_idempotent_replay=sync_result.is_idempotent_replay,
        decisions_created=sync_result.created_decision_count,
        decisions_resolved=sync_result.resolved_count,
        decisions_reopened=sync_result.reopened_count,
        open_decisions_after_sync=sync_result.open_decision_count_after_sync,
    )

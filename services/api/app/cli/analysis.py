"""Pilot analysis orchestration CLI (Gate 21B): the ONE production entrypoint that composes
Expected calculation, all four detectors, priority ranking and decision persistence for one
property - closing the Gate 21A P0 finding that this composition existed nowhere outside tests.

    python -m app.cli.analysis run --workspace-slug h --property-slug h \
        --booking-data-source-id <uuid> --stay-date-start 2026-09-29 --stay-date-end 2026-10-29 \
        [--labor-data-source-id <uuid>] [--cost-year 2026 --cost-month 8] [--currency EUR]

ORCHESTRATION ONLY: every number here is computed by the existing engines
(`ObservedSnapshotService`, `BookingExpectedService`, `RevenueDecisionService`,
`OtaDependencyService`, `CostDecisionService`, `LaborDecisionService`, `PriorityService`,
`DecisionService`) exactly as the test suite already exercises them - this module recalculates
nothing and adds no business rule of its own.

The snapshot day is ALWAYS the real clock's "today" in the property's own time zone
(`ObservedSnapshotService.take_snapshot` reads the injected real clock, never an operator-passed
date - see `snapshots/common.py`): there is no way to fabricate a past business date through this
CLI, on purpose.

FAIL LOUD, NEVER A FALSE ALL-CLEAR (the Gate 21A finding this closes): every detector evaluation
below runs OUTSIDE any try/except that could swallow it. If a detector call raises, this command
lets the exception propagate, prints nothing further and exits non-zero - `DecisionService.sync()`
is NEVER reached. A run either evaluates everything it attempted, or it persists nothing at all.

COVERAGE (Gate 22): this function is also the ONE place that builds the `AnalysisCoverage` a run
persists - which of REVENUE/DISTRIBUTION/COSTS/LABOR were actually attempted this run, from the
SAME booleans that already decide steps 5-6 below, never reconstructed afterward from the
evaluations list (see `app/modules/decisions/coverage.py`). Revenue and OTA are unconditional in
this CLI, so REVENUE and DISTRIBUTION are always EVALUATED.
"""

import argparse
import sys
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.cli._support import resolve_tenant_and_property, run_cli
from app.db.session import get_sessionmaker
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.service import DecisionService
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.priority.service import PriorityService, SourceEvaluation
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.repository import BookingSnapshotRepository


def _skipped_domain_names(coverage: AnalysisCoverage) -> list[str]:
    return [d.domain.value for d in coverage.domains if d.status is DomainCoverageStatus.SKIPPED]


def run_analysis(
    session: Session,
    *,
    workspace_slug: str,
    property_slug: str,
    booking_data_source_id: UUID,
    stay_date_start: date,
    stay_date_end: date,
    labor_data_source_id: UUID | None,
    cost_year: int | None,
    cost_month: int | None,
    currency: str | None,
) -> int:
    if (cost_year is None) != (cost_month is None):
        print("Error: --cost-year and --cost-month must be given together", file=sys.stderr)
        return 1

    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    print(f"Analysis run: workspace={workspace_slug} property={property_slug}")

    # 1. Materialize today's OBSERVED booking snapshots - the ONLY step below that writes
    # anything before the final sync(). The snapshot day is the real clock's "today" in the
    # property's own time zone: never an operator-supplied date (see the module docstring).
    snapshot_result = ObservedSnapshotService(session, tenant).take_snapshot(
        property_id=prop.id,
        data_source_id=booking_data_source_id,
        stay_date_start=stay_date_start,
        stay_date_end=stay_date_end,
    )
    as_of_local_date = snapshot_result.snapshot_date_first
    print(
        f"  [1/6] observed snapshots: snapshot_local_date={as_of_local_date.isoformat()} "
        f"created={snapshot_result.created} unchanged={snapshot_result.unchanged}"
    )

    # 2. Expected baselines for those same targets.
    expected_result = BookingExpectedService(session, tenant).calculate_for_snapshot_date(
        property_id=prop.id,
        data_source_id=booking_data_source_id,
        snapshot_local_date=as_of_local_date,
        stay_date_start=stay_date_start,
        stay_date_end=stay_date_end,
    )
    print(
        f"  [2/6] expected baselines: created={expected_result.created} "
        f"unchanged={expected_result.unchanged} ready={expected_result.ready} "
        f"insufficient={expected_result.insufficient}"
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
    print(f"  [3/6] revenue signals: targets={len(signals)}")

    # 4. OTA: property-wide, one evaluation.
    ota_evaluation = OtaDependencyService(session, tenant).evaluate(
        property_id=prop.id,
        booking_data_source_id=booking_data_source_id,
        as_of_local_date=as_of_local_date,
    )
    evaluations.append(ota_evaluation)
    print(f"  [4/6] ota dependency: status={ota_evaluation.status.value}")

    # 5. Cost: only when the operator gave an explicit target month - never a hidden default.
    if cost_year is not None and cost_month is not None:
        cost_currency = currency or prop.currency
        cost_evaluations = CostDecisionService(session, tenant).evaluate_month(
            property_id=prop.id,
            booking_data_source_id=booking_data_source_id,
            year=cost_year,
            month=cost_month,
            currency=cost_currency,
        )
        evaluations.extend(cost_evaluations)
        print(
            f"  [5/6] cost cpor anomaly: year={cost_year} month={cost_month} "
            f"currency={cost_currency} categories={len(cost_evaluations)}"
        )
    else:
        print("  [5/6] cost cpor anomaly: skipped (no --cost-year/--cost-month given)")

    # 6. Labor: only when the operator gave an explicit labor data source - one evaluation per
    # OBSERVED target snapshot and labor category, reusing the same targets as step 3.
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
        print(
            f"  [6/6] labor overstaffing: targets={len(target_snapshots)} "
            f"categories={len(LaborCategory)} evaluations={len(labor_evaluations)}"
        )
    else:
        print("  [6/6] labor overstaffing: skipped (no --labor-data-source-id given)")

    # 7. Coverage (Gate 22): built from the SAME booleans that decided steps 5-6 above, never
    # reconstructed from the evaluations list afterward - see app.modules.decisions.coverage's
    # own module docstring for why. Revenue and OTA are unconditional in this CLI, so REVENUE and
    # DISTRIBUTION are always EVALUATED; COSTS/LABOR mirror whichever branch actually ran.
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

    # 8. Rank, then persist. Every evaluation gathered above reaches BOTH calls, or the process
    # already crashed above and neither call happens - see the module docstring.
    context = PriorityContext(
        workspace_id=tenant.workspace_id, property_id=prop.id, as_of_local_date=as_of_local_date
    )
    ranking_result = PriorityService().rank(context, evaluations)
    sync_result = DecisionService(session, tenant).sync(
        context, ranking_result, evaluations, coverage
    )

    print(
        f"Analysis complete: as_of_local_date={as_of_local_date.isoformat()} "
        f"evaluations={len(evaluations)} triggered={ranking_result.candidate_count} "
        f"clear={ranking_result.excluded_clear_count} "
        f"insufficient_data={ranking_result.excluded_insufficient_count} "
        f"not_applicable={ranking_result.excluded_not_applicable_count} "
        f"suppressed={ranking_result.excluded_suppressed_count} "
        f"decision_run_id={sync_result.decision_run_id} "
        f"is_idempotent_replay={sync_result.is_idempotent_replay} "
        f"decisions_created={sync_result.created_decision_count} "
        f"decisions_resolved={sync_result.resolved_count} "
        f"decisions_reopened={sync_result.reopened_count} "
        f"open_decisions_after_sync={sync_result.open_decision_count_after_sync} "
        f"coverage={coverage.summary.value} "
        f"skipped_domains={_skipped_domain_names(coverage)}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run", help="Run today's analysis for one property against real production data."
    )
    run.add_argument("--workspace-slug", required=True)
    run.add_argument("--property-slug", required=True)
    run.add_argument("--booking-data-source-id", required=True, type=UUID)
    run.add_argument("--stay-date-start", required=True, type=date.fromisoformat)
    run.add_argument("--stay-date-end", required=True, type=date.fromisoformat)
    run.add_argument("--labor-data-source-id", type=UUID, default=None)
    run.add_argument("--cost-year", type=int, default=None)
    run.add_argument("--cost-month", type=int, default=None)
    run.add_argument("--currency", type=str, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    with get_sessionmaker()() as session:

        def dispatch() -> int:
            return run_analysis(
                session,
                workspace_slug=args.workspace_slug,
                property_slug=args.property_slug,
                booking_data_source_id=args.booking_data_source_id,
                stay_date_start=args.stay_date_start,
                stay_date_end=args.stay_date_end,
                labor_data_source_id=args.labor_data_source_id,
                cost_year=args.cost_year,
                cost_month=args.cost_month,
                currency=args.currency,
            )

        return run_cli(dispatch)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_analysis"]

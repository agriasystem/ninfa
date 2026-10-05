"""Pilot analysis orchestration CLI (Gate 21B): the ONE production entrypoint that composes
Expected calculation, all four detectors, priority ranking and decision persistence for one
property - closing the Gate 21A P0 finding that this composition existed nowhere outside tests.

    python -m app.cli.analysis run --workspace-slug h --property-slug h \
        --booking-data-source-id <uuid> --stay-date-start 2026-09-29 --stay-date-end 2026-10-29 \
        [--labor-data-source-id <uuid>] [--cost-year 2026 --cost-month 8] [--currency EUR]

THIN ADAPTER (Gate 25B): the orchestration itself lives in `app/modules/analysis`
(`run_property_analysis`), shared verbatim with the worker task `analysis.run_property`.
This module only parses arguments, resolves slugs to ids, calls it and prints the result. Engines,
snapshot-day rule (the real clock's "today" in the property's own time zone, never operator-passed),
fail-loud behaviour (a detector exception propagates, nothing is persisted), coverage (Gate 22) and
provenance (Gate 23B) are all documented there. An inconsistent --cost-year/--cost-month pair is
rejected by that shared function and surfaces here as the usual `Error: ...` line and exit 1.
"""

import argparse
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.cli._support import resolve_tenant_and_property, run_cli
from app.db.session import get_sessionmaker
from app.modules.analysis import AnalysisRunRequest, AnalysisRunResult, run_property_analysis
from app.modules.decisions.coverage import AnalysisCoverage, DomainCoverageStatus
from app.modules.labor.roles import LaborCategory


def _skipped_domain_names(coverage: AnalysisCoverage) -> list[str]:
    return [d.domain.value for d in coverage.domains if d.status is DomainCoverageStatus.SKIPPED]


def _print_result(
    result: AnalysisRunResult, *, cost_year: int | None, cost_month: int | None
) -> None:
    """The existing operator output, rendered from the shared typed result."""
    print(
        f"  [1/6] observed snapshots: snapshot_local_date={result.as_of_local_date.isoformat()} "
        f"created={result.snapshots_created} unchanged={result.snapshots_unchanged}"
    )
    print(
        f"  [2/6] expected baselines: created={result.expected_created} "
        f"unchanged={result.expected_unchanged} ready={result.expected_ready} "
        f"insufficient={result.expected_insufficient}"
    )
    print(f"  [3/6] revenue signals: targets={result.revenue_target_count}")
    print(f"  [4/6] ota dependency: status={result.ota_status}")
    if result.cost_category_count is not None:
        print(
            f"  [5/6] cost cpor anomaly: year={cost_year} month={cost_month} "
            f"currency={result.cost_currency} categories={result.cost_category_count}"
        )
    else:
        print("  [5/6] cost cpor anomaly: skipped (no --cost-year/--cost-month given)")
    if result.labor_evaluation_count is not None:
        print(
            f"  [6/6] labor overstaffing: targets={result.labor_target_count} "
            f"categories={len(LaborCategory)} evaluations={result.labor_evaluation_count}"
        )
    else:
        print("  [6/6] labor overstaffing: skipped (no --labor-data-source-id given)")
    print(
        "  [provenance] bookings: "
        f"data_source_id={result.provenance.bookings.data_source_id} "
        f"last_successful_import_finished_at="
        f"{result.provenance.bookings.last_successful_import_finished_at}"
    )
    print(
        f"Analysis complete: as_of_local_date={result.as_of_local_date.isoformat()} "
        f"evaluations={result.evaluation_count} triggered={result.triggered_count} "
        f"clear={result.clear_count} "
        f"insufficient_data={result.insufficient_count} "
        f"not_applicable={result.not_applicable_count} "
        f"suppressed={result.suppressed_count} "
        f"decision_run_id={result.decision_run_id} "
        f"is_idempotent_replay={result.is_idempotent_replay} "
        f"decisions_created={result.decisions_created} "
        f"decisions_resolved={result.decisions_resolved} "
        f"decisions_reopened={result.decisions_reopened} "
        f"open_decisions_after_sync={result.open_decisions_after_sync} "
        f"coverage={result.coverage.summary.value} "
        f"skipped_domains={_skipped_domain_names(result.coverage)}"
    )


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
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    print(f"Analysis run: workspace={workspace_slug} property={property_slug}")

    result = run_property_analysis(
        session,
        AnalysisRunRequest(
            workspace_id=tenant.workspace_id,
            property_id=prop.id,
            booking_data_source_id=booking_data_source_id,
            stay_date_start=stay_date_start,
            stay_date_end=stay_date_end,
            labor_data_source_id=labor_data_source_id,
            cost_year=cost_year,
            cost_month=cost_month,
            currency=currency,
        ),
    )
    _print_result(result, cost_year=cost_year, cost_month=cost_month)
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

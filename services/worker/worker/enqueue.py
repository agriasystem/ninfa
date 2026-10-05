"""Operator command: enqueue ONE explicit `analysis.run_property` job (Gate 25B).

    python -m worker enqueue-analysis --workspace-id <uuid> --property-id <uuid> \
        --booking-data-source-id <uuid> --stay-date-start 2026-10-01 --stay-date-end 2026-10-31 \
        [--labor-data-source-id <uuid>] [--cost-year 2026 --cost-month 9] [--currency EUR]

Every choice is the operator's: no discovery, no default source, no default window, no "all
properties", no schedule. The command touches only the Procrastinate queue - it never opens the
business database, so unknown ids are not detected here: the job runs and fails visibly instead.
"""

import logging

from app.modules.analysis import AnalysisRunRequest
from worker.app import DEFAULT_QUEUE, app
from worker.tasks import (
    ANALYSIS_RUN_PROPERTY_TASK,
    analysis_task_kwargs,
    run_property_analysis_task,
)

logger = logging.getLogger(__name__)


def _describe(request: AnalysisRunRequest) -> list[str]:
    labor = (
        f"included (data_source_id={request.labor_data_source_id})"
        if request.labor_data_source_id is not None
        else "skipped (no --labor-data-source-id given)"
    )
    costs = (
        f"included (year={request.cost_year} month={request.cost_month} "
        f"currency={request.currency or 'property default'})"
        if request.cost_year is not None
        else "skipped (no --cost-year/--cost-month given)"
    )
    return [
        f"  workspace_id={request.workspace_id} property_id={request.property_id}",
        f"  booking_data_source_id={request.booking_data_source_id}",
        f"  stay_date_start={request.stay_date_start.isoformat()} "
        f"stay_date_end={request.stay_date_end.isoformat()}",
        f"  labor: {labor}",
        f"  costs: {costs}",
    ]


async def enqueue_analysis(request: AnalysisRunRequest) -> int:
    """Defer exactly one job; return the process exit code (0 enqueued, 1 refused/failed)."""
    try:
        async with app.open_async():
            job_id = await run_property_analysis_task.defer_async(**analysis_task_kwargs(request))
    except Exception as error:
        logger.exception("Could not enqueue the analysis job")
        print(f"Error: could not enqueue the analysis job ({type(error).__name__})")
        return 1

    print(
        f"Analysis job enqueued: job_id={job_id} task={ANALYSIS_RUN_PROPERTY_TASK} "
        f"queue={DEFAULT_QUEUE}"
    )
    for line in _describe(request):
        print(line)
    return 0

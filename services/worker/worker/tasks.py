"""Registered background tasks.

* `system.heartbeat` (Gate 0): smoke task proving that the worker starts, connects and executes.
* `analysis.run_property` (Gate 25B): runs the shared production analysis for ONE property.

NOTHING enqueues `analysis.run_property` automatically: there is no periodic job, no dispatcher,
no startup hook and no import trigger. It runs only when an operator enqueues it explicitly
(`python -m worker enqueue-analysis ...`), and every execution choice is an explicit argument.
"""

import logging
from datetime import date
from typing import Any
from uuid import UUID

from app.db.session import get_sessionmaker
from app.modules.analysis import AnalysisRunRequest, run_property_analysis
from worker.app import DEFAULT_QUEUE, app

logger = logging.getLogger(__name__)

HEARTBEAT_TASK = "system.heartbeat"
ANALYSIS_RUN_PROPERTY_TASK = "analysis.run_property"


@app.task(name=HEARTBEAT_TASK, queue=DEFAULT_QUEUE)
async def heartbeat() -> None:
    logger.info("Worker heartbeat: job executed")


# A plain `def` on purpose: Procrastinate runs a synchronous task in a thread pool, and the
# analysis uses a synchronous SQLAlchemy Session. No retry is configured (deterministic failures -
# unknown ids, snapshot CONFLICT, out-of-order run - would only loop); a failure is the job state
# `failed` plus the real exception in the worker log.
@app.task(name=ANALYSIS_RUN_PROPERTY_TASK, queue=DEFAULT_QUEUE)
def run_property_analysis_task(
    *,
    workspace_id: str,
    property_id: str,
    booking_data_source_id: str,
    stay_date_start: str,
    stay_date_end: str,
    labor_data_source_id: str | None = None,
    cost_year: int | None = None,
    cost_month: int | None = None,
    currency: str | None = None,
) -> None:
    """Procrastinate arguments are JSON: ids and dates arrive as strings and are parsed here."""
    request = AnalysisRunRequest(
        workspace_id=UUID(workspace_id),
        property_id=UUID(property_id),
        booking_data_source_id=UUID(booking_data_source_id),
        stay_date_start=date.fromisoformat(stay_date_start),
        stay_date_end=date.fromisoformat(stay_date_end),
        labor_data_source_id=UUID(labor_data_source_id) if labor_data_source_id else None,
        cost_year=cost_year,
        cost_month=cost_month,
        currency=currency,
    )
    ids = f"workspace_id={request.workspace_id} property_id={request.property_id}"
    logger.info("Analysis job started: %s", ids)

    # The task's OWN Session: created here, closed in every case, never passed across a
    # thread/task boundary. The services commit or roll back their own transactions; leaving the
    # `with` block closes the Session, which rolls back anything left uncommitted.
    with get_sessionmaker()() as session:
        try:
            result = run_property_analysis(session, request)
        except Exception as error:
            # Log safe identifiers, then let the SAME exception fail the job: nothing is converted
            # into success and no run is faked.
            logger.error(
                "Analysis job failed: %s status=failed error_type=%s", ids, type(error).__name__
            )
            raise

    logger.info(
        "Analysis job completed: %s status=succeeded decision_run_id=%s is_idempotent_replay=%s",
        ids,
        result.decision_run_id,
        result.is_idempotent_replay,
    )


def analysis_task_kwargs(request: AnalysisRunRequest) -> dict[str, Any]:
    """The JSON-safe arguments `analysis.run_property` takes, from an already validated request."""
    return {
        "workspace_id": str(request.workspace_id),
        "property_id": str(request.property_id),
        "booking_data_source_id": str(request.booking_data_source_id),
        "stay_date_start": request.stay_date_start.isoformat(),
        "stay_date_end": request.stay_date_end.isoformat(),
        "labor_data_source_id": (
            str(request.labor_data_source_id) if request.labor_data_source_id else None
        ),
        "cost_year": request.cost_year,
        "cost_month": request.cost_month,
        "currency": request.currency,
    }

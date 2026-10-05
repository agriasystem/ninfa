"""Worker entrypoint.

python -m worker run              start the worker (Ctrl+C to stop)
python -m worker run --once       process the jobs currently queued, then exit
python -m worker heartbeat        enqueue the smoke job
python -m worker enqueue-analysis enqueue ONE explicit analysis.run_property job (see enqueue.py)
"""

import argparse
import logging
import sys
from datetime import date
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.modules.analysis import AnalysisRunRequest
from worker import runtime
from worker.app import DEFAULT_QUEUE, app
from worker.enqueue import enqueue_analysis
from worker.tasks import heartbeat

SERVICE_NAME = "ninfa-worker"

logger = logging.getLogger(__name__)


async def _run_worker(*, once: bool) -> None:
    async with app.open_async():
        logger.info("Worker started (queue=%s, once=%s)", DEFAULT_QUEUE, once)
        # Windows has no loop.add_signal_handler(); there Ctrl+C surfaces as KeyboardInterrupt.
        await app.run_worker_async(
            queues=[DEFAULT_QUEUE],
            wait=not once,
            install_signal_handlers=sys.platform != "win32",
        )
        logger.info("Worker stopped")


async def _enqueue_heartbeat() -> None:
    async with app.open_async():
        job_id = await heartbeat.defer_async()
        logger.info("Heartbeat job enqueued (job_id=%s)", job_id)


def _analysis_request(args: argparse.Namespace) -> AnalysisRunRequest:
    return AnalysisRunRequest(
        workspace_id=args.workspace_id,
        property_id=args.property_id,
        booking_data_source_id=args.booking_data_source_id,
        stay_date_start=args.stay_date_start,
        stay_date_end=args.stay_date_end,
        labor_data_source_id=args.labor_data_source_id,
        cost_year=args.cost_year,
        cost_month=args.cost_month,
        currency=args.currency,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m worker", description="NINFA worker")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="start the worker")
    run_parser.add_argument("--once", action="store_true", help="drain queued jobs, then exit")
    commands.add_parser("heartbeat", help="enqueue the smoke job")
    enqueue = commands.add_parser(
        "enqueue-analysis", help="enqueue ONE explicit analysis.run_property job"
    )
    enqueue.add_argument("--workspace-id", required=True, type=UUID)
    enqueue.add_argument("--property-id", required=True, type=UUID)
    enqueue.add_argument("--booking-data-source-id", required=True, type=UUID)
    enqueue.add_argument("--stay-date-start", required=True, type=date.fromisoformat)
    enqueue.add_argument("--stay-date-end", required=True, type=date.fromisoformat)
    enqueue.add_argument("--labor-data-source-id", type=UUID, default=None)
    enqueue.add_argument("--cost-year", type=int, default=None)
    enqueue.add_argument("--cost-month", type=int, default=None)
    enqueue.add_argument("--currency", type=str, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(
        service=SERVICE_NAME, level=settings.log_level, json_output=settings.is_production
    )

    try:
        if args.command == "run":
            runtime.run(_run_worker(once=args.once))
        elif args.command == "enqueue-analysis":
            try:
                request = _analysis_request(args)
            except AppError as error:
                print(f"Error: {error}", file=sys.stderr)
                return 1
            return runtime.run(enqueue_analysis(request))
        else:
            runtime.run(_enqueue_heartbeat())
    except KeyboardInterrupt:
        logger.info("Worker interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

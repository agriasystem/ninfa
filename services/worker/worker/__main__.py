"""Worker entrypoint.

python -m worker run              start the worker (Ctrl+C to stop)
python -m worker run --once       process the jobs currently queued, then exit
python -m worker heartbeat        enqueue the smoke job
"""

import argparse
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from worker import runtime
from worker.app import DEFAULT_QUEUE, app
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m worker", description="NINFA worker")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="start the worker")
    run_parser.add_argument("--once", action="store_true", help="drain queued jobs, then exit")
    commands.add_parser("heartbeat", help="enqueue the smoke job")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(
        service=SERVICE_NAME, level=settings.log_level, json_output=settings.is_production
    )

    try:
        if args.command == "run":
            runtime.run(_run_worker(once=args.once))
        else:
            runtime.run(_enqueue_heartbeat())
    except KeyboardInterrupt:
        logger.info("Worker interrupted")


if __name__ == "__main__":
    main()

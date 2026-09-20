"""Registered background tasks.

Gate 0 only ships a smoke task proving that the worker starts, connects and executes jobs.
Business jobs (imports, parsing, recalculation, ...) belong to later gates.
"""

import logging

from worker.app import DEFAULT_QUEUE, app

logger = logging.getLogger(__name__)

HEARTBEAT_TASK = "system.heartbeat"


@app.task(name=HEARTBEAT_TASK, queue=DEFAULT_QUEUE)
async def heartbeat() -> None:
    logger.info("Worker heartbeat: job executed")

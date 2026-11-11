"""The day's analysis, without anyone asking: the worker's own tick.

    every few minutes -> recover what a dead worker left behind -> enrol the properties that became
    ready
                      -> one `analysis.run_policy` job per property whose analysis is due now

Every few minutes, because a once-a-day job is exactly what a restart loses (Procrastinate drops a
tick missed for more than ten minutes), while this one loses nothing: whether a property is due is
worked out each time from what is stored (the property's own clock, today's run, today's failures),
never from when the tick last ran. A tick missed, a worker down for hours, a tick repeated: the next
one finds the same truth, and asks only for what is still missing. Nothing depends on a browser, a
login or an operator.

    restart            the queue's table says at most one tick per moment, however many workers
    a job queued twice the job's `queueing_lock`: one waits per property
    a job run twice    the policy task evaluates again when it runs, and a run today means skip
    a worker killed    its job stays `doing`: a later tick puts it back, a bounded number of times

ORCHESTRATION ONLY: no analysis and no detector here.
"""

import asyncio
import logging
from datetime import UTC, datetime

from procrastinate import App, JobContext, exceptions, jobs

from app.db.session import get_sessionmaker
from app.modules.analysis import (
    DAILY_TICK_TASK,
    PolicyEvaluation,
    daily_opportunities,
    enroll_ready_properties,
    prune_finished_ticks,
)
from worker.app import DEFAULT_QUEUE, app
from worker.dispatch import defer_policy_jobs

logger = logging.getLogger(__name__)

DAILY_TICK_CRON = "*/5 * * * *"
DAILY_TICK_PERIODIC_ID = "daily-analysis"
# A worker silent for this long is gone (it sends a heartbeat every 10 seconds, even mid-analysis).
STALLED_AFTER_SECONDS = 60
# A job that killed its worker this many times is not put back again.
MAX_RECOVERIES = 3


async def recover_stalled_jobs(procrastinate_app: App) -> int:
    """Put back on the queue the jobs a dead worker left in `doing`: without this, one stays there
    for ever, and its lock holds back every later analysis of that property. Every job of this queue
    is safe to run again: an analysis of unchanged data is a replay, and the policy task skips a day
    already analysed. Returns how many were put back."""
    manager = procrastinate_app.job_manager
    recovered = 0
    stalled = await manager.get_stalled_jobs(
        queue=DEFAULT_QUEUE, seconds_since_heartbeat=STALLED_AFTER_SECONDS
    )
    for job in stalled:
        if job.attempts >= MAX_RECOVERIES:
            logger.error("Stalled job given up: job_id=%s task=%s", job.id, job.task_name)
            await manager.finish_job(job, jobs.Status.FAILED, delete_job=False)
            continue
        try:
            await manager.retry_job(job)
        except exceptions.ConnectorException:  # the same job is already waiting: this one is done
            await manager.finish_job(job, jobs.Status.FAILED, delete_job=False)
            continue
        logger.warning("Stalled job put back: job_id=%s task=%s", job.id, job.task_name)
        recovered += 1
    return recovered


def _opportunities(now: datetime) -> list[PolicyEvaluation]:
    with get_sessionmaker()() as session:
        enrolled = enroll_ready_properties(session)
        if enrolled:
            logger.info("Daily analysis switched on: properties=%d", len(enrolled))
        return daily_opportunities(session, now)


def _prune(now: datetime) -> None:
    with get_sessionmaker()() as session:
        prune_finished_ticks(session, now)
        session.commit()


async def run_daily_tick(procrastinate_app: App, now: datetime) -> int:
    """One tick at the instant `now`. Returns how many analyses it asked for."""
    await recover_stalled_jobs(procrastinate_app)
    evaluations = await asyncio.to_thread(_opportunities, now)
    records = await defer_policy_jobs(evaluations)
    enqueued = 0
    for record in records:
        if record.enqueued:
            enqueued += 1
            logger.info(
                "Daily analysis queued: workspace_id=%s property_id=%s local_date=%s job_id=%s",
                record.evaluation.workspace_id,
                record.evaluation.property_id,
                record.evaluation.local_date,
                record.job_id,
            )
    await asyncio.to_thread(_prune, now)
    return enqueued


# The timestamp is the moment the tick stands for. It is not used: what is due is decided on the
# clock when the job really runs, so a tick that waited behind a long analysis decides on the truth
# by then.
@app.periodic(cron=DAILY_TICK_CRON, periodic_id=DAILY_TICK_PERIODIC_ID)
@app.task(
    name=DAILY_TICK_TASK,
    queue=DEFAULT_QUEUE,
    queueing_lock=DAILY_TICK_TASK,
    pass_context=True,
)
async def daily_tick_task(context: JobContext, timestamp: int) -> None:
    await run_daily_tick(context.app, datetime.now(UTC))

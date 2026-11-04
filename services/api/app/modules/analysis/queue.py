"""The API's one door to the worker: asking for an analysis refresh, and reading how it went.

The API does not depend on Procrastinate (only the worker does), and it needs very little of it: a
row in `procrastinate_jobs`, whose schema this repository vendors and migrates itself (revision
0002). `procrastinate_defer_jobs_v1` is exactly this INSERT, and its triggers (the NOTIFY the worker
listens to, the events below) fire the same way. `ON CONFLICT` is what the worker's own "already
enqueued" is: one job waiting per property at most.

The job carries only the property's identity: what to analyse is decided when it runs
(`analysis.refresh.run_refresh`), so a job that waited still analyses what is there by then. Its
state stays here, in the queue's own tables, rather than in a second table that could disagree.

A job told to wait for a later moment does not hold back a request for now: it is simply brought
forward, instead of leaving new data waiting behind it.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from json import dumps
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext

ANALYSIS_REFRESH_TASK = "analysis.refresh_property"
ANALYSIS_QUEUE = "default"


class QueuedJobStatus(StrEnum):
    """`procrastinate_job_status`, as the queue itself names it."""

    TODO = "todo"
    DOING = "doing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class QueuedRefresh:
    """The latest refresh job of a property. `scheduled_at` is set only for a job told to wait."""

    job_id: int
    status: QueuedJobStatus
    scheduled_at: datetime | None
    queued_at: datetime | None
    last_event_at: datetime | None


def _lock_of(property_id: UUID) -> str:
    """One refresh of a property runs at a time, and one waits; other properties never wait."""
    return f"{ANALYSIS_REFRESH_TASK}:{property_id}"


def enqueue_refresh(
    session: Session,
    tenant: TenantContext,
    property_id: UUID,
    *,
    scheduled_at: datetime | None = None,
) -> int | None:
    """Queue a refresh in the caller's transaction (the caller commits). Returns the job id, or None
    when one is already waiting to run: it will read whatever is there then, so that is enough."""
    lock = _lock_of(property_id)
    args = {"workspace_id": str(tenant.workspace_id), "property_id": str(property_id)}
    job_id: int | None = session.scalar(
        text(
            """
            INSERT INTO procrastinate_jobs
                (queue_name, task_name, lock, queueing_lock, args, scheduled_at)
            VALUES
                (:queue, :task, :lock, :lock, CAST(:args AS jsonb), :scheduled_at)
            ON CONFLICT (queueing_lock) WHERE status = 'todo' DO UPDATE
                SET scheduled_at = EXCLUDED.scheduled_at
                WHERE procrastinate_jobs.scheduled_at IS NOT NULL
                  AND EXCLUDED.scheduled_at IS NULL
            RETURNING id
            """
        ),
        {
            "queue": ANALYSIS_QUEUE,
            "task": ANALYSIS_REFRESH_TASK,
            "lock": lock,
            "args": dumps(args),
            "scheduled_at": scheduled_at,
        },
    )
    return job_id


def latest_refresh(
    session: Session, tenant: TenantContext, property_id: UUID
) -> QueuedRefresh | None:
    """The newest refresh job of this property. The queue knows no tenant, so the workspace is read
    from the job's own arguments: a property of another workspace has no job here."""
    row = session.execute(
        text(
            """
            SELECT job.id, job.status::text, job.scheduled_at,
                   (SELECT min(event.at) FROM procrastinate_events event
                     WHERE event.job_id = job.id) AS queued_at,
                   (SELECT max(event.at) FROM procrastinate_events event
                     WHERE event.job_id = job.id) AS last_event_at
              FROM procrastinate_jobs job
             WHERE job.task_name = :task
               AND job.lock = :lock
               AND job.args ->> 'workspace_id' = :workspace_id
             ORDER BY job.id DESC
             LIMIT 1
            """
        ),
        {
            "task": ANALYSIS_REFRESH_TASK,
            "lock": _lock_of(property_id),
            "workspace_id": str(tenant.workspace_id),
        },
    ).first()
    if row is None:
        return None
    return QueuedRefresh(row[0], QueuedJobStatus(row[1]), row[2], row[3], row[4])


__all__ = [
    "ANALYSIS_QUEUE",
    "ANALYSIS_REFRESH_TASK",
    "QueuedJobStatus",
    "QueuedRefresh",
    "enqueue_refresh",
    "latest_refresh",
]

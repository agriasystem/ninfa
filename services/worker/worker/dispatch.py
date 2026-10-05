"""Operator commands of the Automatic Analysis Policy V1 (Gate 26B).

    python -m worker dispatch-analysis   evaluate every enabled policy; enqueue ONE
                                         `analysis.run_policy` job per eligible property
    python -m worker analysis-status     read-only: which enabled properties have no run today

`dispatch-analysis` is meant to be invoked ONCE a day at 10:00 property-local time by an EXTERNAL
scheduler (see docs/architecture/automatic-analysis-policy-v1.md), followed by the normal worker
(`python -m worker run --once`). Nothing here registers a periodic job. It performs no analysis and
no detector logic: it evaluates the frozen policy through `app.modules.analysis`, skips visibly
with a typed reason, and defers jobs. A skip is a normal outcome (exit 0); only a failure to
enqueue exits non-zero.

`analysis-status` deliberately does NOT report the latest worker job status: Procrastinate stores a
job's arguments as JSON, so mapping a property to its jobs would couple this command to
Procrastinate's schema. Job state stays one SQL query away (`procrastinate_jobs`).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from procrastinate import exceptions as procrastinate_exceptions

from app.db.session import get_sessionmaker
from app.modules.analysis import (
    AutomaticSkipReason,
    PolicyEvaluation,
    evaluate_enabled_policies,
)
from worker import runtime
from worker.app import app
from worker.tasks import ANALYSIS_RUN_POLICY_TASK, run_policy_analysis_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    evaluation: PolicyEvaluation
    job_id: int | None
    skip_reason: AutomaticSkipReason | None

    @property
    def enqueued(self) -> bool:
        return self.job_id is not None


def _yes_no(value: bool | None) -> str:
    return "UNKNOWN" if value is None else ("YES" if value else "NO")


def _who(evaluation: PolicyEvaluation) -> str:
    return (
        f"workspace={evaluation.workspace_slug or '-'} property={evaluation.property_slug or '-'}"
    )


def _evaluate(now: datetime) -> list[PolicyEvaluation]:
    with get_sessionmaker()() as session:
        return evaluate_enabled_policies(session, now)


async def _enqueue(evaluations: list[PolicyEvaluation]) -> list[DispatchRecord]:
    records: list[DispatchRecord] = []
    async with app.open_async():
        for evaluation in evaluations:
            if not evaluation.eligible:
                records.append(DispatchRecord(evaluation, None, evaluation.skip_reason))
                continue
            try:
                # One pending job per property at most: invoking the dispatcher twice before the
                # worker ran must not queue the same property twice.
                job_id = await run_policy_analysis_task.configure(
                    queueing_lock=f"{ANALYSIS_RUN_POLICY_TASK}:{evaluation.property_id}"
                ).defer_async(
                    workspace_id=str(evaluation.workspace_id),
                    property_id=str(evaluation.property_id),
                )
            except procrastinate_exceptions.AlreadyEnqueued:
                records.append(
                    DispatchRecord(evaluation, None, AutomaticSkipReason.JOB_ALREADY_QUEUED)
                )
            else:
                records.append(DispatchRecord(evaluation, job_id, None))
    return records


def dispatch_analysis(now: datetime | None = None) -> int:
    now = datetime.now(UTC) if now is None else now
    evaluations = _evaluate(now)
    try:
        records = runtime.run(_enqueue(evaluations))
    except Exception as error:
        logger.exception("Could not enqueue the policy analysis jobs")
        print(f"Error: could not enqueue the policy analysis jobs ({type(error).__name__})")
        return 1

    eligible = sum(record.evaluation.eligible for record in records)
    enqueued = sum(record.enqueued for record in records)
    print(
        f"Analysis dispatch: evaluated_at={now.astimezone(UTC).isoformat()} "
        f"policies_total={len(records)} eligible={eligible} enqueued={enqueued} "
        f"skipped={len(records) - enqueued}"
    )
    for record in records:
        evaluation = record.evaluation
        line = f"  {_who(evaluation)} local_date={evaluation.local_date or '-'}"
        if record.enqueued:
            line += f" result=ENQUEUED job_id={record.job_id}"
        else:
            line += f" result=SKIPPED reason={record.skip_reason}"
        print(line)
    return 0


def analysis_status(now: datetime | None = None) -> int:
    now = datetime.now(UTC) if now is None else now
    evaluations = _evaluate(now)
    without_run = sum(evaluation.run_exists_today is not True for evaluation in evaluations)
    print(
        f"Analysis status: evaluated_at={now.astimezone(UTC).isoformat()} "
        f"enabled_policies={len(evaluations)} without_run_today={without_run}"
    )
    for evaluation in evaluations:
        configuration = (
            "VALID" if evaluation.run_exists_today is not None else str(evaluation.skip_reason)
        )
        next_dispatch = "ELIGIBLE" if evaluation.eligible else f"SKIPPED:{evaluation.skip_reason}"
        print(
            f"  {_who(evaluation)} booking_data_source_id={evaluation.booking_data_source_id} "
            f"local_date={evaluation.local_date or '-'} "
            f"run_today={_yes_no(evaluation.run_exists_today)} "
            f"today_import={_yes_no(evaluation.qualifying_import_today)} "
            f"latest_analysis={evaluation.latest_analysis_date or 'NONE'} "
            f"configuration={configuration} next_dispatch={next_dispatch}"
        )
    return 0

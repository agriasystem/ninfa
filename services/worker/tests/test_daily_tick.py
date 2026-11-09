"""The worker's own tick: registered once, safe to repeat, and able to recover a dead worker's job.

Procrastinate's in-memory connector and a fake evaluation: what is due is pinned in
`services/api/tests/test_daily_analysis.py`, on the real database. Here it is the queue's side.
"""

import asyncio
import inspect
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

import pytest
from procrastinate import exceptions, jobs, testing

from app.modules.analysis import (
    DAILY_TICK_TASK,
    AutomaticSkipReason,
    PolicyEvaluation,
    analysis_lock_of,
)
from worker import daily, runtime
from worker.app import DEFAULT_QUEUE, app
from worker.tasks import ANALYSIS_RUN_POLICY_TASK

NOW = datetime(2026, 10, 5, 8, 5, tzinfo=UTC)


def _evaluation(slug: str, reason: AutomaticSkipReason | None = None) -> PolicyEvaluation:
    return PolicyEvaluation(
        policy_id=uuid4(),
        workspace_id=uuid4(),
        property_id=uuid4(),
        booking_data_source_id=uuid4(),
        workspace_slug=f"ws-{slug}",
        property_slug=slug,
        evaluated_at=NOW,
        local_date=date(2026, 10, 5),
        run_exists_today=False,
        qualifying_import_today=False,
        latest_analysis_date=None,
        skip_reason=reason,
        local_time=time(10, 5),
    )


@pytest.fixture
def due(monkeypatch: pytest.MonkeyPatch) -> list[PolicyEvaluation]:
    items: list[PolicyEvaluation] = []
    monkeypatch.setattr(daily, "_opportunities", lambda now: list(items))
    monkeypatch.setattr(daily, "_prune", lambda now: None)
    return items


def _tick(connector: testing.InMemoryConnector, *, times: int = 1) -> list[int]:
    async def scenario() -> list[int]:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                return [await daily.run_daily_tick(test_app, NOW) for _ in range(times)]

    return runtime.run(scenario())


def test_the_tick_is_registered_once_every_few_minutes() -> None:
    [(task_name, periodic_id)] = list(app.periodic_registry.periodic_tasks)
    assert task_name == DAILY_TICK_TASK and periodic_id == daily.DAILY_TICK_PERIODIC_ID
    periodic = app.periodic_registry.periodic_tasks[(task_name, periodic_id)]
    assert periodic.cron == daily.DAILY_TICK_CRON == "*/5 * * * *"
    # One tick waits at most, however long an analysis keeps the worker busy.
    assert daily.daily_tick_task.queueing_lock == DAILY_TICK_TASK
    assert daily.daily_tick_task.queue == DEFAULT_QUEUE
    assert inspect.iscoroutinefunction(daily.daily_tick_task.func)


def test_the_worker_loads_the_tick_by_itself() -> None:
    assert "worker.daily" in app.import_paths


def test_only_what_is_due_is_queued_with_the_identity_alone_and_the_propertys_lock(
    due: list[PolicyEvaluation],
) -> None:
    ready = _evaluation("ready")
    due.extend(
        [
            ready,
            _evaluation("early", AutomaticSkipReason.NOT_DUE_YET),
            _evaluation("done", AutomaticSkipReason.ALREADY_ANALYZED_TODAY),
            _evaluation("spent", AutomaticSkipReason.ATTEMPTS_EXHAUSTED),
        ]
    )
    connector = testing.InMemoryConnector()

    assert _tick(connector) == [1]

    [job] = list(connector.jobs.values())
    assert job["task_name"] == ANALYSIS_RUN_POLICY_TASK
    assert job["args"] == {
        "workspace_id": str(ready.workspace_id),
        "property_id": str(ready.property_id),
    }
    assert job["lock"] == analysis_lock_of(ready.property_id)


def test_a_tick_repeated_before_the_worker_ran_queues_nothing_more(
    due: list[PolicyEvaluation],
) -> None:
    due.append(_evaluation("alpha"))
    connector = testing.InMemoryConnector()

    assert _tick(connector, times=3) == [1, 0, 0]

    assert len(connector.jobs) == 1


def test_several_properties_each_get_their_own_job(due: list[PolicyEvaluation]) -> None:
    due.extend([_evaluation("a"), _evaluation("b"), _evaluation("c")])
    connector = testing.InMemoryConnector()

    assert _tick(connector) == [3]

    assert len({job["args"]["property_id"] for job in connector.jobs.values()}) == 3


def test_the_tick_is_a_job_the_worker_really_runs(
    due: list[PolicyEvaluation], monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = testing.InMemoryConnector()
    calls: list[Any] = []

    async def fake_tick(procrastinate_app: Any, now: datetime) -> int:
        calls.append(now)
        return 0

    monkeypatch.setattr(daily, "run_daily_tick", fake_tick)

    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                tick: Any = daily.daily_tick_task
                await tick.defer_async(timestamp=1_790_000_000)
                await tick.configure(queueing_lock="other").defer_async(timestamp=1_790_000_300)
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())

    assert [str(job["status"]) for job in connector.jobs.values()] == ["succeeded", "succeeded"]
    assert len(calls) == 2


# --- a worker killed mid-job ---------------------------------------------------------------------


class _Manager:
    """The job manager's three calls the recovery makes."""

    def __init__(self, stalled: list[Any], *, retry_fails: bool = False) -> None:
        self.stalled, self.retry_fails = stalled, retry_fails
        self.retried: list[Any] = []
        self.finished: list[Any] = []
        self.heartbeat: float | None = None

    async def get_stalled_jobs(self, *, queue: str, seconds_since_heartbeat: float) -> list[Any]:
        assert queue == DEFAULT_QUEUE
        self.heartbeat = seconds_since_heartbeat
        return self.stalled

    async def retry_job(self, job: Any) -> None:
        if self.retry_fails:
            raise exceptions.ConnectorException()
        self.retried.append(job)

    async def finish_job(self, job: Any, status: Any, delete_job: bool) -> None:
        assert delete_job is False  # kept: it is what can be read about what happened
        self.finished.append((job, status))


class _App:
    def __init__(self, manager: _Manager) -> None:
        self.job_manager = manager


class _Job:
    def __init__(self, attempts: int = 0) -> None:
        self.id, self.task_name, self.attempts = 7, "analysis.run_policy", attempts


def _recover(manager: _Manager) -> int:
    return asyncio.run(daily.recover_stalled_jobs(_App(manager)))  # type: ignore[arg-type]


def test_a_job_a_dead_worker_left_behind_goes_back_on_the_queue() -> None:
    job = _Job()
    manager = _Manager([job])

    assert _recover(manager) == 1

    assert manager.retried == [job] and manager.finished == []
    # Well beyond the worker's own heartbeat: a worker busy on a long analysis is not dead.
    assert manager.heartbeat == daily.STALLED_AFTER_SECONDS >= 30


def test_a_job_that_keeps_killing_its_worker_is_given_up() -> None:
    job = _Job(attempts=daily.MAX_RECOVERIES)
    manager = _Manager([job])

    assert _recover(manager) == 0

    assert manager.retried == []
    assert [status for _, status in manager.finished] == [jobs.Status.FAILED]


def test_a_job_already_waiting_again_closes_the_one_left_behind() -> None:
    job = _Job()
    manager = _Manager([job], retry_fails=True)

    assert _recover(manager) == 0

    assert [status for _, status in manager.finished] == [jobs.Status.FAILED]


def test_nothing_stalled_changes_nothing() -> None:
    manager = _Manager([])

    assert _recover(manager) == 0

    assert manager.retried == [] and manager.finished == []


def test_recovery_on_the_real_connector_contract() -> None:
    """The in-memory queue answers the same call a real one does: a job left `doing` by a worker
    gone silent is found, and put back."""
    connector = testing.InMemoryConnector()

    async def scenario() -> list[str]:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                job_id = await daily.daily_tick_task.configure(queueing_lock=None).defer_async(
                    timestamp=1
                )
                worker_id = (await connector.register_worker_one())["worker_id"]  # type: ignore[no-untyped-call]
                connector.jobs[job_id]["status"] = "doing"
                connector.jobs[job_id]["worker_id"] = worker_id
                connector.workers[worker_id] = connector.workers[worker_id] - timedelta(hours=1)
                assert await daily.recover_stalled_jobs(test_app) == 1
                return [str(job["status"]) for job in connector.jobs.values()]

    assert runtime.run(scenario()) == ["todo"]

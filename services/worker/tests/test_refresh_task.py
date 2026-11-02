"""The `analysis.refresh_property` worker task: its own contract, the analysis replaced by fakes.

Queue behaviour uses Procrastinate's in-memory connector. What is pinned: the name the API enqueues
is the one the worker registered; a real failure fails the job with no retry; a day that keeps its
first observation queues the refresh for the next local day and is not a failure; nothing else is
ever queued by the task.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from procrastinate import testing

from app.modules.analysis import ANALYSIS_QUEUE, ANALYSIS_REFRESH_TASK, RefreshOutcomeKind
from app.modules.analysis.refresh import RefreshOutcome, RefreshSkipReason
from worker import runtime, tasks
from worker.app import DEFAULT_QUEUE, app
from worker.tasks import refresh_property_task

WORKSPACE_ID = uuid4()
PROPERTY_ID = uuid4()
RETRY_AT = datetime(2026, 11, 3, 0, 5, tzinfo=UTC)


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.commits = 0

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True

    def commit(self) -> None:
        self.commits += 1


class _Recorder:
    def __init__(self, outcome: RefreshOutcome | Exception) -> None:
        self.outcome = outcome
        self.sessions: list[_FakeSession] = []
        self.refreshes: list[tuple[Any, Any]] = []
        self.deferred: list[dict[str, Any]] = []

    def sessionmaker(self) -> Any:
        def make() -> _FakeSession:
            session = _FakeSession()
            self.sessions.append(session)
            return session

        return make

    def run_refresh(self, _session: Any, workspace_id: Any, property_id: Any) -> RefreshOutcome:
        self.refreshes.append((workspace_id, property_id))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def enqueue(self, _session: Any, tenant: Any, property_id: Any, **kwargs: Any) -> int:
        self.deferred.append({"tenant": tenant, "property_id": property_id, **kwargs})
        return 1


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def install(outcome: RefreshOutcome | Exception) -> _Recorder:
        recorder = _Recorder(outcome)
        monkeypatch.setattr(tasks, "get_sessionmaker", recorder.sessionmaker)
        monkeypatch.setattr(tasks, "run_refresh", recorder.run_refresh)
        monkeypatch.setattr(tasks, "enqueue_refresh", recorder.enqueue)
        return recorder

    yield install


def _call() -> None:
    refresh_property_task(workspace_id=str(WORKSPACE_ID), property_id=str(PROPERTY_ID))


def test_the_name_the_api_enqueues_is_the_task_the_worker_runs() -> None:
    assert ANALYSIS_REFRESH_TASK == "analysis.refresh_property"
    assert app.tasks[ANALYSIS_REFRESH_TASK].func is refresh_property_task.func
    assert ANALYSIS_QUEUE == DEFAULT_QUEUE


def test_the_arguments_are_only_the_identity_and_each_run_has_its_own_session(use: Any) -> None:
    recorder = use(RefreshOutcome(RefreshOutcomeKind.SKIPPED, RefreshSkipReason.NO_BOOKING_SOURCE))

    _call()

    assert recorder.refreshes == [(WORKSPACE_ID, PROPERTY_ID)]
    assert len(recorder.sessions) == 1
    assert recorder.sessions[0].closed is True
    assert recorder.deferred == []  # nothing to run on: nothing is due again


def test_a_real_failure_propagates_and_nothing_is_queued(use: Any) -> None:
    recorder = use(RuntimeError("detector exploded"))

    with pytest.raises(RuntimeError):
        _call()

    assert recorder.deferred == []
    assert recorder.sessions[0].closed is True


def test_a_day_that_keeps_its_first_observation_is_due_again_on_the_next_local_day(
    use: Any,
) -> None:
    recorder = use(RefreshOutcome(RefreshOutcomeKind.DEFERRED, retry_at=RETRY_AT))

    _call()  # no exception: it is not a failure

    assert len(recorder.deferred) == 1
    assert recorder.deferred[0]["property_id"] == PROPERTY_ID
    assert recorder.deferred[0]["tenant"].workspace_id == WORKSPACE_ID
    assert recorder.deferred[0]["scheduled_at"] == RETRY_AT
    assert recorder.sessions[0].commits == 1


def test_a_failed_job_is_not_retried_by_the_queue(use: Any) -> None:
    use(RuntimeError("detector exploded"))
    connector = testing.InMemoryConnector()

    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await refresh_property_task.defer_async(
                    workspace_id=str(WORKSPACE_ID), property_id=str(PROPERTY_ID)
                )
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())

    assert [str(job["status"]) for job in connector.jobs.values()] == ["failed"]
    assert [job["attempts"] for job in connector.jobs.values()] == [1]

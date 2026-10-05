"""Gate 25B: the `analysis.run_property` worker task and the `enqueue-analysis` operator command.

Queue behaviour uses Procrastinate's in-memory connector (no database); the shared analysis and
the Session factory are replaced by fakes so these tests prove the TASK's own contract: exact
arguments, its own Session per execution, failure semantics, no retry, nothing automatic. The real
database path is covered by `services/api/tests/test_worker_analysis_integration.py`.
"""

import ast
import inspect
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from procrastinate import testing

import worker
from app.modules.analysis import AnalysisInputError, AnalysisRunRequest
from worker import __main__ as worker_main
from worker import runtime, tasks
from worker.app import DEFAULT_QUEUE, app
from worker.enqueue import enqueue_analysis
from worker.tasks import ANALYSIS_RUN_PROPERTY_TASK, HEARTBEAT_TASK, run_property_analysis_task

WORKSPACE_ID = uuid4()
PROPERTY_ID = uuid4()
SOURCE_ID = uuid4()
LABOR_ID = uuid4()
_WORKER_DIR = Path(worker.__file__).parent


def _request(**overrides: Any) -> AnalysisRunRequest:
    values: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "property_id": PROPERTY_ID,
        "booking_data_source_id": SOURCE_ID,
        "stay_date_start": date(2026, 10, 1),
        "stay_date_end": date(2026, 10, 31),
    }
    values.update(overrides)
    return AnalysisRunRequest(**values)


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


class _Recorder:
    """Stands in for `get_sessionmaker` and `run_property_analysis` inside `worker.tasks`."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.sessions: list[_FakeSession] = []
        self.calls: list[tuple[_FakeSession, AnalysisRunRequest]] = []

    def sessionmaker(self) -> Any:
        def make() -> _FakeSession:
            session = _FakeSession()
            self.sessions.append(session)
            return session

        return make

    def analysis(self, session: _FakeSession, request: AnalysisRunRequest) -> Any:
        self.calls.append((session, request))
        if self.error is not None:
            raise self.error

        class _Result:
            decision_run_id = uuid4()
            is_idempotent_replay = False

        return _Result()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(tasks, "get_sessionmaker", rec.sessionmaker)
    monkeypatch.setattr(tasks, "run_property_analysis", rec.analysis)
    return rec


def _run_enqueue_and_worker(
    request: AnalysisRunRequest, *, times: int = 1
) -> tuple[testing.InMemoryConnector, list[int]]:
    connector = testing.InMemoryConnector()

    async def scenario() -> list[int]:
        with app.replace_connector(connector) as test_app:
            codes = [await enqueue_analysis(request) for _ in range(times)]
            async with test_app.open_async():
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)
        return codes

    return connector, runtime.run(scenario())


def _statuses(connector: testing.InMemoryConnector) -> list[str]:
    return [str(job["status"]) for job in connector.jobs.values()]


def test_01_task_is_registered_on_the_default_queue_and_heartbeat_is_unchanged() -> None:
    assert app.tasks[ANALYSIS_RUN_PROPERTY_TASK].queue == DEFAULT_QUEUE
    assert app.tasks[HEARTBEAT_TASK].queue == DEFAULT_QUEUE
    assert ANALYSIS_RUN_PROPERTY_TASK == "analysis.run_property"


def test_02_task_is_a_synchronous_function_not_a_coroutine() -> None:
    assert not inspect.iscoroutinefunction(run_property_analysis_task.func)
    assert inspect.iscoroutinefunction(tasks.heartbeat.func)


def test_03_explicit_enqueue_produces_exactly_one_job_with_the_exact_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _request(labor_data_source_id=LABOR_ID, cost_year=2026, cost_month=9, currency="EUR")
    connector = testing.InMemoryConnector()

    async def scenario() -> int:
        with app.replace_connector(connector):
            return await enqueue_analysis(request)

    assert runtime.run(scenario()) == 0

    assert len(connector.jobs) == 1
    job = next(iter(connector.jobs.values()))
    assert job["task_name"] == ANALYSIS_RUN_PROPERTY_TASK
    assert job["queue_name"] == DEFAULT_QUEUE
    assert job["args"] == {
        "workspace_id": str(WORKSPACE_ID),
        "property_id": str(PROPERTY_ID),
        "booking_data_source_id": str(SOURCE_ID),
        "stay_date_start": "2026-10-01",
        "stay_date_end": "2026-10-31",
        "labor_data_source_id": str(LABOR_ID),
        "cost_year": 2026,
        "cost_month": 9,
        "currency": "EUR",
    }
    out = capsys.readouterr().out
    assert f"Analysis job enqueued: job_id={job['id']} task=analysis.run_property" in out
    assert f"property_id={PROPERTY_ID}" in out
    assert f"booking_data_source_id={SOURCE_ID}" in out
    assert "stay_date_start=2026-10-01 stay_date_end=2026-10-31" in out
    assert f"labor: included (data_source_id={LABOR_ID})" in out
    assert "costs: included (year=2026 month=9 currency=EUR)" in out


def test_04_optional_domains_are_reported_as_skipped_when_not_given(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connector = testing.InMemoryConnector()

    async def scenario() -> int:
        with app.replace_connector(connector):
            return await enqueue_analysis(_request())

    assert runtime.run(scenario()) == 0
    out = capsys.readouterr().out
    assert "labor: skipped (no --labor-data-source-id given)" in out
    assert "costs: skipped (no --cost-year/--cost-month given)" in out


def test_05_the_task_hands_the_exact_ids_and_window_to_the_shared_analysis(
    recorder: _Recorder,
) -> None:
    request = _request(labor_data_source_id=LABOR_ID, cost_year=2026, cost_month=9, currency="EUR")

    connector, codes = _run_enqueue_and_worker(request)

    assert codes == [0]
    assert _statuses(connector) == ["succeeded"]
    assert [call[1] for call in recorder.calls] == [request]


def test_06_the_task_opens_its_own_session_per_execution_and_closes_it(
    recorder: _Recorder,
) -> None:
    connector, _ = _run_enqueue_and_worker(_request(), times=2)

    assert _statuses(connector) == ["succeeded", "succeeded"]
    assert len(recorder.sessions) == 2
    assert recorder.sessions[0] is not recorder.sessions[1]  # never reused between executions
    assert all(session.closed for session in recorder.sessions)
    assert [call[0] for call in recorder.calls] == recorder.sessions  # the analysis got THAT one


def test_07_an_analysis_exception_fails_the_job_closes_the_session_and_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rec = _Recorder(error=AnalysisInputError("boom"))
    monkeypatch.setattr(tasks, "get_sessionmaker", rec.sessionmaker)
    monkeypatch.setattr(tasks, "run_property_analysis", rec.analysis)

    with caplog.at_level("INFO"):
        connector, _ = _run_enqueue_and_worker(_request())

    assert _statuses(connector) == ["failed"]
    assert len(connector.jobs) == 1  # no second job: nothing was retried
    assert len(rec.calls) == 1
    assert rec.sessions[0].closed
    assert run_property_analysis_task.retry_strategy is None
    assert any(
        "status=failed error_type=AnalysisInputError" in message for message in caplog.messages
    )
    assert f"property_id={PROPERTY_ID}" in " ".join(caplog.messages)


def test_08_a_malformed_argument_fails_the_job_before_any_session_is_opened(
    recorder: _Recorder,
) -> None:
    connector = testing.InMemoryConnector()

    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await run_property_analysis_task.defer_async(
                    workspace_id="not-a-uuid",
                    property_id=str(PROPERTY_ID),
                    booking_data_source_id=str(SOURCE_ID),
                    stay_date_start="2026-10-01",
                    stay_date_end="2026-10-31",
                )
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())

    assert _statuses(connector) == ["failed"]
    assert recorder.sessions == []


def test_09_enqueue_command_rejects_an_inconsistent_cost_pair_without_enqueueing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connector = testing.InMemoryConnector()
    argv = [
        "enqueue-analysis",
        "--workspace-id", str(WORKSPACE_ID),
        "--property-id", str(PROPERTY_ID),
        "--booking-data-source-id", str(SOURCE_ID),
        "--stay-date-start", "2026-10-01",
        "--stay-date-end", "2026-10-31",
        "--cost-year", "2026",
    ]  # fmt: skip

    with app.replace_connector(connector):
        code = worker_main.main(argv)

    assert code == 1
    assert connector.jobs == {}
    assert "cost_year and cost_month must be given together" in capsys.readouterr().err


def test_10_enqueue_command_exits_non_zero_when_enqueueing_itself_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broken_defer(**_: Any) -> int:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(run_property_analysis_task, "defer_async", broken_defer)
    connector = testing.InMemoryConnector()

    async def scenario() -> int:
        with app.replace_connector(connector):
            return await enqueue_analysis(_request())

    assert runtime.run(scenario()) == 1
    assert "could not enqueue the analysis job (RuntimeError)" in capsys.readouterr().out


def test_11_enqueue_command_rejects_bad_arguments_with_a_non_zero_exit() -> None:
    with pytest.raises(SystemExit) as exit_info:
        worker_main.main(["enqueue-analysis", "--workspace-id", "nope"])
    assert exit_info.value.code != 0


def _worker_sources() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(_WORKER_DIR.glob("*.py")):
        yield path.name, ast.parse(path.read_text(encoding="utf-8"))


def test_12_nothing_is_scheduled_or_enqueued_automatically() -> None:
    assert app.periodic_registry.periodic_tasks == {}
    for name, tree in _worker_sources():
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "periodic" not in attributes, f"{name} registers a periodic task"
        if name not in {"enqueue.py", "dispatch.py", "__main__.py"}:
            assert not {"defer", "defer_async"} & attributes, f"{name} enqueues a job"
    # Only the explicit operator commands (enqueue, dispatch) defer a job.
    tasks_tree = ast.parse((_WORKER_DIR / "tasks.py").read_text(encoding="utf-8"))
    decorators = [
        ast.unparse(decorator)
        for node in ast.walk(tasks_tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for decorator in node.decorator_list
    ]
    assert all(d.startswith("app.task(") for d in decorators)


def test_13_worker_package_imports_no_test_helper_and_the_app_never_imports_the_worker() -> None:
    for name, tree in _worker_sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "tests", f"{name} imports a test helper"
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "tests" for a in node.names), name

    api_app = Path(inspect.getfile(AnalysisRunRequest)).parents[2]  # .../app
    offenders = []
    for path in api_app.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(m.split(".")[0] in {"worker", "procrastinate"} for m in modules):
                offenders.append(str(path.relative_to(api_app)))
    assert offenders == []


def test_14_shared_analysis_module_imports_no_cli_worker_argparse_or_procrastinate() -> None:
    package = Path(inspect.getfile(AnalysisRunRequest)).parent
    forbidden = {"argparse", "procrastinate", "worker"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"
                assert not module.startswith("app.cli"), f"{path.name} imports {module}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "print", f"{path.name} prints"
                assert node.func.id != "get_sessionmaker", f"{path.name} opens a Session"


def test_15_a_request_validates_its_cost_pair_once_for_enqueue_and_execution() -> None:
    with pytest.raises(AnalysisInputError):
        _request(cost_month=9)
    with pytest.raises(AnalysisInputError):
        _request(cost_year=2026)
    assert _request(cost_year=2026, cost_month=9).cost_month == 9


def test_16_task_kwargs_roundtrip_through_the_task_parser() -> None:
    request = _request(labor_data_source_id=LABOR_ID, cost_year=2026, cost_month=9)
    kwargs = tasks.analysis_task_kwargs(request)
    assert UUID(kwargs["workspace_id"]) == WORKSPACE_ID
    assert date.fromisoformat(kwargs["stay_date_end"]) == request.stay_date_end

"""Gate 26B: the policy task `analysis.run_policy`, the `dispatch-analysis` command and the
`analysis-status` command.

Queue behaviour uses Procrastinate's in-memory connector (no database). The policy evaluation and
the analysis are replaced by fakes, so these tests prove the worker side's own contract: one job per
eligible property, exact arguments, deterministic output, own Session, failure semantics, no retry,
nothing periodic. The real database path is `services/api/tests/test_worker_policy_integration.py`.
"""

import ast
import inspect
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from procrastinate import testing

import worker
from app.modules.analysis import (
    AutomaticAnalysisOutcome,
    AutomaticOutcome,
    AutomaticSkipReason,
    PolicyEvaluation,
)
from worker import dispatch, tasks
from worker.app import DEFAULT_QUEUE, app
from worker.tasks import (
    ANALYSIS_RUN_POLICY_TASK,
    ANALYSIS_RUN_PROPERTY_TASK,
    run_policy_analysis_task,
    run_property_analysis_task,
)

_WORKER_DIR = Path(worker.__file__).parent
NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def _evaluation(
    slug: str, reason: AutomaticSkipReason | None = None, *, source: UUID | None = None
) -> PolicyEvaluation:
    return PolicyEvaluation(
        policy_id=uuid4(),
        workspace_id=uuid4(),
        property_id=uuid4(),
        booking_data_source_id=source or uuid4(),
        workspace_slug=f"ws-{slug}",
        property_slug=slug,
        evaluated_at=NOW,
        local_date=date(2026, 10, 5),
        run_exists_today=reason is AutomaticSkipReason.ALREADY_ANALYZED_TODAY,
        qualifying_import_today=reason is not AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT,
        latest_analysis_date=date(2026, 10, 4),
        skip_reason=reason,
    )


@pytest.fixture
def evaluations(monkeypatch: pytest.MonkeyPatch) -> list[PolicyEvaluation]:
    items: list[PolicyEvaluation] = []
    monkeypatch.setattr(dispatch, "_evaluate", lambda now: list(items))
    return items


def _dispatch(connector: testing.InMemoryConnector, *, times: int = 1) -> list[int]:
    codes: list[int] = []
    with app.replace_connector(connector):
        for _ in range(times):
            codes.append(dispatch.dispatch_analysis(NOW))
    return codes


# --- the policy task ---------------------------------------------------------------------------


def test_01_policy_task_is_registered_sync_and_without_retry_next_to_the_manual_task() -> None:
    assert app.tasks[ANALYSIS_RUN_POLICY_TASK].queue == DEFAULT_QUEUE
    assert ANALYSIS_RUN_POLICY_TASK == "analysis.run_policy"
    assert not inspect.iscoroutinefunction(run_policy_analysis_task.func)
    assert run_policy_analysis_task.retry_strategy is None
    # Gate 25's explicit task is still registered and unchanged.
    assert app.tasks[ANALYSIS_RUN_PROPERTY_TASK].queue == DEFAULT_QUEUE
    assert not inspect.iscoroutinefunction(run_property_analysis_task.func)
    assert list(inspect.signature(run_property_analysis_task.func).parameters) == [
        "workspace_id",
        "property_id",
        "booking_data_source_id",
        "stay_date_start",
        "stay_date_end",
        "labor_data_source_id",
        "cost_year",
        "cost_month",
        "currency",
    ]


def test_02_policy_task_takes_only_the_policy_identity_so_dates_are_computed_at_execution() -> None:
    assert list(inspect.signature(run_policy_analysis_task.func).parameters) == [
        "workspace_id",
        "property_id",
    ]


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


class _Recorder:
    def __init__(self, *, error: Exception | None = None, skip: bool = False) -> None:
        self.error, self.skip = error, skip
        self.sessions: list[_FakeSession] = []
        self.calls: list[tuple[_FakeSession, UUID, UUID]] = []

    def sessionmaker(self) -> Any:
        def make() -> _FakeSession:
            session = _FakeSession()
            self.sessions.append(session)
            return session

        return make

    def run(self, session: _FakeSession, workspace_id: UUID, property_id: UUID) -> Any:
        self.calls.append((session, workspace_id, property_id))
        if self.error is not None:
            raise self.error
        if self.skip:
            return AutomaticAnalysisOutcome(
                AutomaticOutcome.SKIPPED,
                AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT,
                date(2026, 10, 5),
                None,
                None,
                None,
            )

        class _Result:
            decision_run_id = uuid4()
            is_idempotent_replay = False

        return AutomaticAnalysisOutcome(
            AutomaticOutcome.RAN,
            None,
            date(2026, 10, 5),
            date(2026, 10, 5),
            date(2026, 11, 3),
            _Result(),  # type: ignore[arg-type]
        )


def _run_policy_jobs(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch, *, times: int = 1
) -> Any:
    from worker import runtime

    monkeypatch.setattr(tasks, "get_sessionmaker", recorder.sessionmaker)
    monkeypatch.setattr(tasks, "run_automatic_analysis", recorder.run)
    connector = testing.InMemoryConnector()
    workspace_id, property_id = uuid4(), uuid4()

    async def scenario() -> None:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                for _ in range(times):
                    await run_policy_analysis_task.defer_async(
                        workspace_id=str(workspace_id), property_id=str(property_id)
                    )
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)

    runtime.run(scenario())
    return connector, workspace_id, property_id


def _statuses(connector: testing.InMemoryConnector) -> list[str]:
    return [str(job["status"]) for job in connector.jobs.values()]


def test_03_success_runs_with_its_own_session_per_execution_and_the_exact_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()

    connector, workspace_id, property_id = _run_policy_jobs(recorder, monkeypatch, times=2)

    assert _statuses(connector) == ["succeeded", "succeeded"]
    assert len(recorder.sessions) == 2
    assert recorder.sessions[0] is not recorder.sessions[1]
    assert all(session.closed for session in recorder.sessions)
    assert [(c[1], c[2]) for c in recorder.calls] == [(workspace_id, property_id)] * 2


def test_04_a_skipped_opportunity_is_a_successful_job_and_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = _Recorder(skip=True)

    with caplog.at_level("INFO", logger="worker.tasks"):
        connector, _, _ = _run_policy_jobs(recorder, monkeypatch)

    assert _statuses(connector) == ["succeeded"]
    assert any("status=skipped reason=NO_TODAY_BOOKING_IMPORT" in m for m in caplog.messages)


def test_05_a_real_failure_fails_the_job_closes_the_session_and_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = _Recorder(error=RuntimeError("engine exploded"))

    with caplog.at_level("INFO", logger="worker.tasks"):
        connector, _, _ = _run_policy_jobs(recorder, monkeypatch)

    assert _statuses(connector) == ["failed"]
    assert len(connector.jobs) == 1 and len(recorder.calls) == 1  # nothing retried
    assert recorder.sessions[0].closed
    assert any("status=failed error_type=RuntimeError" in m for m in caplog.messages)


# --- the dispatcher ----------------------------------------------------------------------------


def test_06_no_enabled_policies_enqueues_nothing(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    connector = testing.InMemoryConnector()

    assert _dispatch(connector) == [0]

    assert connector.jobs == {}
    assert (
        "Analysis dispatch: evaluated_at=2026-10-05T08:00:00+00:00 policies_total=0 eligible=0 "
        "enqueued=0 skipped=0"
    ) in capsys.readouterr().out


def test_07_exactly_one_job_per_eligible_property_with_the_policy_identity_only(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = _evaluation("alpha"), _evaluation("beta")
    evaluations.extend([first, second])
    connector = testing.InMemoryConnector()

    assert _dispatch(connector) == [0]

    jobs = list(connector.jobs.values())
    assert len(jobs) == 2
    assert {job["task_name"] for job in jobs} == {ANALYSIS_RUN_POLICY_TASK}
    assert [job["args"] for job in jobs] == [
        {"workspace_id": str(e.workspace_id), "property_id": str(e.property_id)}
        for e in (first, second)
    ]
    out = capsys.readouterr().out
    assert "policies_total=2 eligible=2 enqueued=2 skipped=0" in out
    assert "workspace=ws-alpha property=alpha local_date=2026-10-05 result=ENQUEUED job_id=" in out


def test_08_mixed_policies_skip_visibly_with_a_typed_reason_and_enqueue_only_the_eligible(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    evaluations.extend(
        [
            _evaluation("ok"),
            _evaluation("noimport", AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT),
            _evaluation("done", AutomaticSkipReason.ALREADY_ANALYZED_TODAY),
            _evaluation("inactive", AutomaticSkipReason.PROPERTY_INACTIVE),
            _evaluation("ws", AutomaticSkipReason.WORKSPACE_INACTIVE),
            _evaluation("src", AutomaticSkipReason.BOOKING_SOURCE_INACTIVE),
            _evaluation("bad", AutomaticSkipReason.INVALID_BOOKING_SOURCE),
            _evaluation("tz", AutomaticSkipReason.INVALID_TIMEZONE),
        ]
    )
    connector = testing.InMemoryConnector()

    assert _dispatch(connector) == [0]  # skips are normal outcomes

    assert len(connector.jobs) == 1
    out = capsys.readouterr().out
    assert "policies_total=8 eligible=1 enqueued=1 skipped=7" in out
    for slug, reason in [
        ("noimport", "NO_TODAY_BOOKING_IMPORT"),
        ("done", "ALREADY_ANALYZED_TODAY"),
        ("inactive", "PROPERTY_INACTIVE"),
        ("ws", "WORKSPACE_INACTIVE"),
        ("src", "BOOKING_SOURCE_INACTIVE"),
        ("bad", "INVALID_BOOKING_SOURCE"),
        ("tz", "INVALID_TIMEZONE"),
    ]:
        assert f"property={slug} local_date=2026-10-05 result=SKIPPED reason={reason}" in out


def test_09_invoking_the_dispatcher_twice_before_the_worker_runs_queues_each_property_once(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    evaluations.append(_evaluation("alpha"))
    connector = testing.InMemoryConnector()

    assert _dispatch(connector, times=2) == [0, 0]

    assert len(connector.jobs) == 1
    out = capsys.readouterr().out
    assert "result=SKIPPED reason=JOB_ALREADY_QUEUED" in out
    assert "policies_total=1 eligible=1 enqueued=0 skipped=1" in out


def test_10_the_output_is_deterministic_for_the_same_evaluations(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    evaluations.extend([_evaluation("a"), _evaluation("b", AutomaticSkipReason.INVALID_TIMEZONE)])

    def once() -> str:
        _dispatch(testing.InMemoryConnector())
        return capsys.readouterr().out

    assert once() == once()


def test_11_a_failure_to_enqueue_exits_non_zero(
    evaluations: list[PolicyEvaluation],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evaluations.append(_evaluation("alpha"))

    async def broken(self: Any, **_: Any) -> int:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(
        type(run_policy_analysis_task.configure()), "defer_async", broken, raising=False
    )
    connector = testing.InMemoryConnector()

    assert _dispatch(connector) == [1]
    assert "could not enqueue the policy analysis jobs (RuntimeError)" in capsys.readouterr().out


def test_12_status_reports_every_enabled_policy_and_changes_nothing(
    evaluations: list[PolicyEvaluation], capsys: pytest.CaptureFixture[str]
) -> None:
    evaluations.extend(
        [
            _evaluation("ready"),
            _evaluation("done", AutomaticSkipReason.ALREADY_ANALYZED_TODAY),
            _evaluation("noimport", AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT),
        ]
    )
    connector = testing.InMemoryConnector()

    with app.replace_connector(connector):
        assert dispatch.analysis_status(NOW) == 0

    out = capsys.readouterr().out
    assert "enabled_policies=3 without_run_today=2" in out
    assert "property=ready" in out and "run_today=NO today_import=YES" in out
    assert "latest_analysis=2026-10-04" in out
    assert "next_dispatch=SKIPPED:ALREADY_ANALYZED_TODAY" in out
    assert "next_dispatch=ELIGIBLE" in out
    assert connector.jobs == {}  # read-only: it enqueues nothing


# --- boundaries --------------------------------------------------------------------------------


def test_13_the_dispatcher_does_no_detector_work_and_registers_nothing_periodic() -> None:
    tree = ast.parse((_WORKER_DIR / "dispatch.py").read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden = ("app.modules.intelligence", "app.modules.snapshots", "app.modules.decisions")
    assert not [m for m in imported if m.startswith(forbidden)]
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "periodic" not in attributes
    assert app.periodic_registry.periodic_tasks == {}


def test_14_only_the_dispatch_and_enqueue_commands_defer_jobs() -> None:
    for path in sorted(_WORKER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        if path.name not in {"enqueue.py", "dispatch.py", "__main__.py"}:
            assert not {"defer", "defer_async"} & attributes, f"{path.name} enqueues a job"

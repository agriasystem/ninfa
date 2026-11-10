"""A queueing lock already taken is `AlreadyEnqueued` in every language PostgreSQL speaks.

Procrastinate's stock connector reads the lock out of the error's English DETAIL and asserts it
matched: on a server that speaks another language it raised `AssertionError`, the periodic deferrer
did not catch it, and the worker stopped (worker/connector.py). Three layers, none of them reading a
message:

* the rule on simulated errors (English, Italian, German, no detail at all): the same result,
  through the stock error handling, and the stock connector as the control;
* the real connector on the real test database: lock free, lock taken, another database error, and
  the contract `recover_stalled_jobs` relies on;
* a real worker loop, its periodic deferrer colliding with a lock that stays taken, alone and with
  two workers: it stays alive, its heartbeat goes on, nothing is duplicated and a normal job is
  still run.

The test database's own server messages are whatever that server speaks (Italian on the development
machine): what is pinned does not depend on it, and the control that shows the stock bug skips
itself on an English server. Every row a test makes is on queues of its own and is removed.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import procrastinate
import psycopg
import psycopg.errors
import pytest
from procrastinate import exceptions
from psycopg import pq

from app.core.config import get_settings
from worker import runtime
from worker.connector import QUEUEING_LOCK_CONSTRAINT, QueueConnector, queueing_lock_conflict

# --- what PostgreSQL says, in four languages (and with nothing) ---------------------------------

ENGLISH = "Key (queueing_lock)=(analysis.daily_tick) already exists."
ITALIAN = "La chiave (queueing_lock)=(analysis.daily_tick) esiste già."
GERMAN = "Schlüssel »(queueing_lock)=(analysis.daily_tick)« existiert bereits."
DETAILS = [
    pytest.param(ENGLISH, id="english"),
    pytest.param(ITALIAN, id="italian"),
    pytest.param(GERMAN, id="german"),
    pytest.param(None, id="no detail"),
]


def _unique_violation(constraint: str, detail: str | None) -> psycopg.errors.UniqueViolation:
    """What psycopg raises for a violated unique constraint: the class (SQLSTATE 23505), the
    constraint's name and a DETAIL in whatever language the server speaks."""
    info: dict[int, bytes | None] = {
        pq.DiagnosticField.CONSTRAINT_NAME: constraint.encode(),
        pq.DiagnosticField.MESSAGE_DETAIL: None if detail is None else detail.encode(),
    }
    return psycopg.errors.UniqueViolation("duplicate key", info=info)


# --- a connector whose cursor raises what the test says -----------------------------------------


class _Cursor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise self._error


@pytest.fixture
def server_says(monkeypatch: pytest.MonkeyPatch) -> Callable[[Exception], None]:
    """Make every query of a `PsycopgConnector` (stock or not) fail with `error` at the cursor: the
    place the real server's error appears. No database is touched."""

    def install(error: Exception) -> None:
        @contextlib.asynccontextmanager
        async def cursor(self: Any, connection: Any = None) -> AsyncGenerator[_Cursor]:
            yield _Cursor(error)

        monkeypatch.setattr(procrastinate.PsycopgConnector, "_get_cursor", cursor)

    return install


def _run_query(connector: procrastinate.PsycopgConnector) -> None:
    runtime.run(connector.execute_query_one_async("SELECT 1"))


def _stock() -> procrastinate.PsycopgConnector:
    return procrastinate.PsycopgConnector(conninfo="postgresql://unused")


def _ours() -> QueueConnector:
    return QueueConnector(conninfo="postgresql://unused")


# --- the rule, whatever the language ------------------------------------------------------------


@pytest.mark.parametrize("detail", DETAILS)
def test_the_queueing_lock_is_told_by_sqlstate_and_constraint_whatever_the_message_says(
    detail: str | None,
) -> None:
    error = _unique_violation(QUEUEING_LOCK_CONSTRAINT, detail)
    assert error.sqlstate == "23505"

    conflict = queueing_lock_conflict(error)

    assert isinstance(conflict, exceptions.UniqueViolation)
    assert (conflict.constraint_name, conflict.queueing_lock) == (QUEUEING_LOCK_CONSTRAINT, None)


@pytest.mark.parametrize("detail", DETAILS)
def test_any_other_unique_constraint_is_not_the_queueing_lock(detail: str | None) -> None:
    assert queueing_lock_conflict(_unique_violation("some_other_idx", detail)) is None


@pytest.mark.parametrize("detail", DETAILS)
def test_the_connector_raises_the_same_exception_in_every_language(
    detail: str | None, server_says: Callable[[Exception], None]
) -> None:
    error = _unique_violation(QUEUEING_LOCK_CONSTRAINT, detail)
    server_says(error)

    with pytest.raises(exceptions.UniqueViolation) as raised:
        _run_query(_ours())

    assert (raised.value.constraint_name, raised.value.queueing_lock) == (
        QUEUEING_LOCK_CONSTRAINT,
        None,
    )
    assert raised.value.__cause__ is error


def test_the_stock_connector_needs_an_english_message_and_this_module_exists_for_that(
    server_says: Callable[[Exception], None],
) -> None:
    """The control, on a simulated server: English works, anything else is an AssertionError. If
    Procrastinate stops doing this (an upgrade past upstream issue 1531), this fails: then
    `worker/connector.py` is no longer needed and can go."""
    server_says(_unique_violation(QUEUEING_LOCK_CONSTRAINT, ENGLISH))
    with pytest.raises(exceptions.UniqueViolation) as raised:
        _run_query(_stock())
    assert raised.value.queueing_lock == "analysis.daily_tick"

    server_says(_unique_violation(QUEUEING_LOCK_CONSTRAINT, ITALIAN))
    with pytest.raises(AssertionError):
        _run_query(_stock())


# --- nothing else is hidden ---------------------------------------------------------------------


def test_another_unique_violation_is_raised_as_it_always_was(
    server_says: Callable[[Exception], None],
) -> None:
    error = _unique_violation("some_other_idx", ITALIAN)
    server_says(error)

    with pytest.raises(exceptions.UniqueViolation) as raised:
        _run_query(_ours())

    assert raised.value.constraint_name == "some_other_idx"
    assert not isinstance(raised.value, exceptions.AlreadyEnqueued)


def test_the_manager_makes_only_the_queueing_lock_an_already_enqueued(
    server_says: Callable[[Exception], None],
) -> None:
    """`AlreadyEnqueued` for the lock, whatever the language; the same unique violation of any other
    constraint stays what it is and surfaces."""
    probe = _make_probe(_ours())
    job = probe.once.configure().job

    server_says(_unique_violation(QUEUEING_LOCK_CONSTRAINT, ITALIAN))
    with pytest.raises(exceptions.AlreadyEnqueued):
        runtime.run(probe.app.job_manager.defer_job_async(job))

    server_says(_unique_violation("some_other_idx", ITALIAN))
    with pytest.raises(exceptions.UniqueViolation) as raised:
        runtime.run(probe.app.job_manager.defer_job_async(job))
    assert not isinstance(raised.value, exceptions.AlreadyEnqueued)


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.DeadlockDetected("deadlock"),
        psycopg.errors.OperationalError("connection lost"),
        psycopg.errors.NotNullViolation("null"),
    ],
    ids=["deadlock", "operational", "not null"],
)
def test_every_other_database_error_is_still_a_connector_exception(
    error: Exception, server_says: Callable[[Exception], None]
) -> None:
    server_says(error)

    with pytest.raises(exceptions.ConnectorException) as raised:
        _run_query(_ours())

    assert not isinstance(raised.value, exceptions.UniqueViolation)
    assert raised.value.__cause__ is error


# --- a real database ----------------------------------------------------------------------------


@dataclass
class Probe:
    """An app of its own: queues and a lock nobody else uses, a periodic task that wants the lock
    every second on a queue no worker serves (so it stays taken), and a normal task on a queue that
    is served."""

    app: procrastinate.App
    run: str
    served: str
    unserved: str
    lock: str
    executed: list[str]
    once: Any
    normal: Any

    @property
    def periodic_id(self) -> str:
        return f"locale-{self.run}"


def _make_probe(connector: procrastinate.PsycopgConnector, run: str | None = None) -> Probe:
    run = run or uuid4().hex[:10]
    served, unserved, lock = f"locale-served-{run}", f"locale-unserved-{run}", f"locale-lock-{run}"
    executed: list[str] = []
    app = procrastinate.App(connector=connector)

    @app.task(name=f"locale.once.{run}", queue=unserved, queueing_lock=lock)
    async def once() -> None:
        return None

    @app.periodic(cron="* * * * * *", periodic_id=f"locale-{run}")
    @app.task(name=f"locale.tick.{run}", queue=unserved, queueing_lock=f"{lock}-tick")
    async def tick(timestamp: int) -> None:
        return None

    @app.task(name=f"locale.normal.{run}", queue=served)
    async def normal(label: str) -> None:
        executed.append(label)

    return Probe(app, run, served, unserved, lock, executed, once, normal)


@pytest.fixture
def conninfo(test_database_url: str) -> str:
    return get_settings().libpq_conninfo


@pytest.fixture
def probes(conninfo: str) -> Iterator[list[Probe]]:
    made: list[Probe] = []
    yield made
    with psycopg.connect(conninfo, autocommit=True) as connection:
        for probe in made:
            connection.execute(
                "DELETE FROM procrastinate_jobs WHERE queue_name = ANY(%s)",
                ([probe.served, probe.unserved],),
            )
            connection.execute(
                "DELETE FROM procrastinate_periodic_defers WHERE periodic_id = %s",
                (probe.periodic_id,),
            )


def _real_probe(conninfo: str, probes: list[Probe], run: str | None = None) -> Probe:
    probe = _make_probe(QueueConnector(conninfo=conninfo), run)
    probes.append(probe)
    return probe


def _scalar(conninfo: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(sql, params).fetchone()
    return None if row is None else row[0]


def test_a_free_lock_defers_normally(conninfo: str, probes: list[Probe]) -> None:
    probe = _real_probe(conninfo, probes)

    async def scenario() -> int:
        async with probe.app.open_async():
            return int(await probe.once.defer_async())

    job_id = runtime.run(scenario())

    assert job_id > 0
    todo = "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'todo'"
    assert _scalar(conninfo, todo, probe.lock) == 1


def test_a_taken_lock_is_already_enqueued_and_nothing_is_duplicated_on_a_real_server(
    conninfo: str, probes: list[Probe]
) -> None:
    """The real server, in whatever language it speaks (Italian on the development machine)."""
    probe = _real_probe(conninfo, probes)

    async def scenario() -> list[type[BaseException] | None]:
        outcomes: list[type[BaseException] | None] = []
        async with probe.app.open_async():
            for _ in range(4):
                try:
                    await probe.once.defer_async()
                except exceptions.AlreadyEnqueued:
                    outcomes.append(exceptions.AlreadyEnqueued)
                else:
                    outcomes.append(None)
        return outcomes

    assert runtime.run(scenario()) == [None] + [exceptions.AlreadyEnqueued] * 3
    count = "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s"
    assert _scalar(conninfo, count, probe.lock) == 1


def test_a_real_database_error_that_is_not_the_lock_is_not_swallowed(
    conninfo: str, probes: list[Probe]
) -> None:
    probe = _real_probe(conninfo, probes)

    async def scenario() -> None:
        async with probe.app.open_async():
            await probe.app.connector.execute_query_one_async("SELECT 1 / 0")

    with pytest.raises(exceptions.ConnectorException) as raised:
        runtime.run(scenario())

    assert isinstance(raised.value.__cause__, psycopg.errors.DivisionByZero)
    assert not isinstance(raised.value, exceptions.AlreadyEnqueued)


def test_putting_back_a_stalled_job_whose_lock_was_taken_is_a_connector_exception(
    conninfo: str, probes: list[Probe]
) -> None:
    """`worker.daily.recover_stalled_jobs` catches `ConnectorException` for "the same job is already
    waiting". On a non-English server it got an AssertionError instead, and the tick failed."""
    probe = _real_probe(conninfo, probes)

    async def scenario() -> None:
        async with probe.app.open_async():
            stalled_id = await probe.once.defer_async()
            with psycopg.connect(conninfo, autocommit=True) as connection:
                connection.execute(
                    "UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", (stalled_id,)
                )
            await probe.once.defer_async()  # the same lock, waiting now: the stalled one is behind
            [stalled] = await probe.app.job_manager.list_jobs_async(id=stalled_id)
            await probe.app.job_manager.retry_job(stalled)

    with pytest.raises(exceptions.ConnectorException):
        runtime.run(scenario())


def test_a_cancellation_that_meets_the_taken_lock_is_still_a_cancellation(
    conninfo: str, probes: list[Probe]
) -> None:
    """psycopg lets a query that was running when its task was cancelled finish, and raises the
    query's own error instead of `CancelledError`. For the queueing lock that error became
    `AlreadyEnqueued`, which the periodic deferrer takes as "skip this tick": the cancellation was
    lost and the worker could not stop (found as a hang of the worker-loop tests below).

    The race is made exact. Another transaction holds the lock without committing, so the deferral
    waits inside the server; it commits, the waiting insert fails with the unique violation and the
    answer waits in the socket; the task is cancelled before the loop has read it."""
    probe = _real_probe(conninfo, probes)

    async def scenario() -> tuple[str, bool]:
        async with probe.app.open_async():
            with psycopg.connect(conninfo) as holder:  # a transaction that stays open
                holder.execute(
                    "INSERT INTO procrastinate_jobs (queue_name, task_name, queueing_lock) "
                    "VALUES (%s, %s, %s)",
                    (probe.unserved, f"locale.once.{probe.run}", probe.lock),
                )
                task = asyncio.create_task(probe.once.defer_async())
                await asyncio.sleep(0.5)  # it is waiting for the holder's row
                assert not task.done()
                holder.commit()  # the waiting insert fails now ...
                # ... and the server's answer is in the socket, unread: the loop must NOT run
                # meanwhile, so this wait blocks it on purpose
                time.sleep(0.3)  # noqa: ASYNC251
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    return "cancelled", task.cancelled()
                except exceptions.AlreadyEnqueued:
                    return "already enqueued", task.cancelled()
                return "returned", task.cancelled()

    assert runtime.run(scenario()) == ("cancelled", True)


# --- a real worker loop -------------------------------------------------------------------------


def _server_speaks_english(conninfo: str) -> bool:
    value = str(_scalar(conninfo, "SHOW lc_messages"))
    return value in {"C", "POSIX"} or value.lower().startswith(("english", "en_", "en-"))


def _heartbeats(conninfo: str, after_id: int) -> list[datetime]:
    with psycopg.connect(conninfo) as connection:
        rows = connection.execute(
            "SELECT last_heartbeat FROM procrastinate_workers WHERE id > %s ORDER BY id",
            (after_id,),
        ).fetchall()
    return [row[0] for row in rows]


STOP_TIMEOUT = 15.0  # seconds a cancelled worker has to stop (it takes well under one)


async def _run_workers(
    conninfo: str, probes: list[Probe], *, workers: int, seconds: float = 4.0
) -> dict[str, Any]:
    """`workers` real workers on the same task definitions, each with a connector and a pool of its
    own. The periodic deferrer of each collides, every second, with the tick that stays queued.
    Returns what was seen."""
    first = _make_probe(QueueConnector(conninfo=conninfo))
    probes.append(first)
    group = [first] + [
        _make_probe(QueueConnector(conninfo=conninfo), first.run) for _ in range(workers - 1)
    ]
    after_id = int(_scalar(conninfo, "SELECT coalesce(max(id), 0) FROM procrastinate_workers"))

    async with contextlib.AsyncExitStack() as stack:
        for probe in group:
            await stack.enter_async_context(probe.app.open_async())
        running = [
            asyncio.create_task(
                probe.app.run_worker_async(
                    queues=[probe.served],
                    wait=True,
                    install_signal_handlers=False,
                    update_heartbeat_interval=0.2,
                )
            )
            for probe in group
        ]
        await asyncio.sleep(seconds / 2)
        beats_before = _heartbeats(conninfo, after_id)
        labels = [f"job-{index}" for index in range(5)]
        for index, label in enumerate(labels):
            await group[index % workers].normal.defer_async(label=label)
        await asyncio.sleep(seconds / 2)
        beats_after = _heartbeats(conninfo, after_id)
        alive = [not task.done() for task in running]
        for task in running:
            task.cancel()
        # bounded: a worker that cannot be stopped fails the test instead of hanging it
        _, still_running = await asyncio.wait(running, timeout=STOP_TIMEOUT)
        for task in still_running:
            task.cancel()  # so the loop can close; the test fails on `stopped_in_time`
        if still_running:
            await asyncio.wait(still_running, timeout=STOP_TIMEOUT)

    return {
        "alive": alive,
        "stopped_in_time": not still_running,
        "beats_before": beats_before,
        "beats_after": beats_after,
        "stopped_by_cancel": [task.cancelled() for task in running],
        "executed": [label for probe in group for label in probe.executed],
        "labels": labels,
        "probe": first,
    }


def _collisions(caplog: pytest.LogCaptureFixture) -> int:
    return sum(
        getattr(record, "action", None) == "skip_periodic_task_queueing_lock"
        for record in caplog.records
    )


def test_a_worker_survives_its_periodic_deferrer_meeting_a_taken_lock(
    conninfo: str, probes: list[Probe], caplog: pytest.LogCaptureFixture
) -> None:
    """The path that stopped the real worker: the periodic deferrer asks for the tick, the lock is
    taken, and the worker is still there afterwards - heartbeat going, a normal job still run."""
    caplog.set_level(logging.DEBUG, logger="procrastinate.periodic")

    seen = runtime.run(_run_workers(conninfo, probes, workers=1))

    assert seen["stopped_in_time"], "the worker did not stop when it was cancelled"
    assert seen["alive"] == [True]
    assert _collisions(caplog) >= 2  # the deferrer really met the taken lock, more than once
    assert len(seen["beats_before"]) == len(seen["beats_after"]) == 1
    assert seen["beats_after"][0] > seen["beats_before"][0]  # and the heartbeat went on
    assert sorted(seen["executed"]) == sorted(seen["labels"])  # a normal job after the collision
    assert seen["stopped_by_cancel"] == [True]
    probe: Probe = seen["probe"]
    waiting = "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'todo'"
    assert _scalar(conninfo, waiting, f"{probe.lock}-tick") == 1  # one tick waits, never two


def test_two_workers_meeting_the_same_taken_lock_neither_stops_nor_duplicates_nor_loses_a_job(
    conninfo: str, probes: list[Probe], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="procrastinate.periodic")

    seen = runtime.run(_run_workers(conninfo, probes, workers=2, seconds=5.0))

    assert seen["stopped_in_time"], "a worker did not stop when it was cancelled"
    assert seen["alive"] == [True, True]
    assert _collisions(caplog) >= 4  # both deferrers, repeatedly
    assert len(seen["beats_after"]) == 2
    assert all(
        after > before
        for before, after in zip(seen["beats_before"], seen["beats_after"], strict=True)
    )
    # every job ran once: none lost, none twice, whichever worker took it
    assert sorted(seen["executed"]) == sorted(seen["labels"])
    probe: Probe = seen["probe"]
    waiting = "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'todo'"
    assert _scalar(conninfo, waiting, f"{probe.lock}-tick") == 1


def test_the_stock_connector_stops_a_worker_on_a_server_that_does_not_speak_english(
    conninfo: str, probes: list[Probe]
) -> None:
    """The control, on the real server: what happened to the real worker. Skipped on an English
    server, where the stock connector copes."""
    if _server_speaks_english(conninfo):
        pytest.skip("this server speaks English: the stock connector copes with it")
    probe = _make_probe(procrastinate.PsycopgConnector(conninfo=conninfo))
    probes.append(probe)

    async def scenario() -> bool:
        async with probe.app.open_async():
            task = asyncio.create_task(
                probe.app.run_worker_async(
                    queues=[probe.served], wait=True, install_signal_handlers=False
                )
            )
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return False
            return True

    assert runtime.run(scenario()) is True  # it ended by itself: the worker stopped


# --- the real app, and the real schema ----------------------------------------------------------


def test_the_real_worker_app_uses_the_queue_connector() -> None:
    from worker.app import app as ninfa_app

    assert isinstance(ninfa_app.connector, QueueConnector)


def test_the_constraint_is_the_queueing_lock_index_of_the_schema_this_repository_migrates(
    conninfo: str,
) -> None:
    """The name the rule goes by is the migrated table's own, not only Procrastinate's constant."""
    assert QUEUEING_LOCK_CONSTRAINT == "procrastinate_jobs_queueing_lock_idx_v1"
    found = _scalar(
        conninfo,
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'procrastinate_jobs' AND indexname = %s",
        QUEUEING_LOCK_CONSTRAINT,
    )
    assert found is not None and "UNIQUE" in found and "queueing_lock" in found

"""Worker smoke tests using Procrastinate's in-memory connector (no database needed)."""

import asyncio

from procrastinate import testing

from worker import runtime
from worker.app import DEFAULT_QUEUE, app
from worker.tasks import HEARTBEAT_TASK, heartbeat


def test_heartbeat_task_is_registered_on_the_default_queue() -> None:
    task = app.tasks[HEARTBEAT_TASK]

    assert task.queue == DEFAULT_QUEUE


def test_worker_executes_a_deferred_heartbeat_job() -> None:
    connector = testing.InMemoryConnector()

    async def scenario() -> list[str]:
        with app.replace_connector(connector) as test_app:
            async with test_app.open_async():
                await heartbeat.defer_async()
                await test_app.run_worker_async(queues=[DEFAULT_QUEUE], wait=False)
        return [str(job["status"]) for job in connector.jobs.values()]

    assert runtime.run(scenario()) == ["succeeded"]


def test_runtime_uses_a_selector_event_loop() -> None:
    async def loop_type() -> type[asyncio.AbstractEventLoop]:
        return type(asyncio.get_running_loop())

    assert issubclass(runtime.run(loop_type()), asyncio.SelectorEventLoop)

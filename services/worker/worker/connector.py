"""The queue's connector, independent of the language PostgreSQL speaks.

A job deferred while another with the same `queueing_lock` is waiting is not a failure:
Procrastinate calls it `AlreadyEnqueued`, the periodic deferrer skips it, and the worker goes on. It
happens by design: the daily tick holds one lock, and a worker that was down for a few minutes asks
for every tick it missed, the second of which finds the first waiting.

THE BUG, in Procrastinate 3.9.0 and still in 3.10.0 (upstream issue 1531, an unmerged pull request).
The stock connector turns PostgreSQL's unique violation into its own `UniqueViolation` and, for this
one constraint, reads the lock's value out of the error's DETAIL text with an English regular
expression, then `assert`s that it matched. On a server whose messages are not English ("La chiave
(queueing_lock)=(...) esiste già.") the assert fails: an `AssertionError` instead of
`AlreadyEnqueued`, which the periodic deferrer does not catch, so the worker stops.
`recover_stalled_jobs` (`daily.py`) fails the same way: it expects a `ConnectorException`.

THE FIX is to decide from what PostgreSQL says in a form that is the same in every language: the
SQLSTATE (23505, which is the class `psycopg.errors.UniqueViolation`) and the constraint's name
(`diag.constraint_name`), never from a message. It is made where the stock connector hands every
query a cursor, `_get_cursor`, which runs before the connector's own error handling: the one
constraint of the queueing lock is raised there as Procrastinate's `UniqueViolation`, and anything
else is left exactly as it was, so the stock handling (and its `ConnectorException` for every other
database error) is unchanged. No privilege and no PostgreSQL setting is needed: `lc_messages` cannot
be set by an application role, and nothing here asks for it.

A CANCELLATION IS NOT A COLLISION. When a task is cancelled while its query is still running,
psycopg lets the query finish and raises the query's own error instead of `CancelledError`
(`AsyncConnection.wait`, which only passes `QueryCanceled` through). If that error is the taken
lock, turning it into `AlreadyEnqueued` hands the periodic deferrer a "skip this tick" instead of
the cancellation: it carries on, the cancellation is lost, and the worker's shutdown waits for it
for ever. Found as a hang of the worker tests. A cancellation already requested on the task is
therefore raised as `CancelledError` and never as a collision.

THE TRADE-OFF. The lock's value is not in a form that is the same in every language, so the
exception carries `queueing_lock=None`. `Task.defer` and the periodic deferrer already know their
own lock (the manager reads it from the job, not from the exception); only the text of the
`AlreadyEnqueued` raised by `defer_jobs` says "None" instead of the lock.

SCOPE. NINFA defers through Procrastinate's async API only (`worker.dispatch`, `worker.daily`),
which is what this covers. It relies on one private hook of the pinned minor version
(`procrastinate>=3.9,<3.10`), and `tests/test_queueing_lock_locale.py` fails if that hook moves, or
if the stock connector stops needing this (then this module can go).
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator

import procrastinate
import psycopg
import psycopg.errors
import psycopg.rows
from procrastinate import exceptions, manager

QUEUEING_LOCK_CONSTRAINT = manager.QUEUEING_LOCK_CONSTRAINT


def queueing_lock_conflict(
    error: psycopg.errors.UniqueViolation,
) -> exceptions.UniqueViolation | None:
    """Procrastinate's own exception when `error` is the queueing lock being taken, else None.

    A `psycopg.errors.UniqueViolation` is SQLSTATE 23505 by its class (psycopg picks the class from
    the SQLSTATE), and the constraint is told apart by its name, `diag.constraint_name`: neither
    depends on a language. The error's text is never read."""
    if error.diag.constraint_name != QUEUEING_LOCK_CONSTRAINT:
        return None
    return exceptions.UniqueViolation(constraint_name=QUEUEING_LOCK_CONSTRAINT, queueing_lock=None)


class QueueConnector(procrastinate.PsycopgConnector):
    """`PsycopgConnector` that raises a taken queueing lock the same way in every language."""

    @contextlib.asynccontextmanager
    async def _get_cursor(
        self, connection: psycopg.AsyncConnection | None = None
    ) -> AsyncGenerator[psycopg.AsyncCursor[psycopg.rows.DictRow]]:
        try:
            async with super()._get_cursor(connection) as cursor:
                yield cursor
        except psycopg.errors.UniqueViolation as error:
            conflict = queueing_lock_conflict(error)
            if conflict is None:
                raise
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError from error
            raise conflict from error


__all__ = ["QUEUEING_LOCK_CONSTRAINT", "QueueConnector", "queueing_lock_conflict"]

# ADR 0049: A taken queueing lock is the same in every language

Status: accepted (Worker Queueing Lock Locale Safety Fix). Infrastructure only: no migration, no new dependency, no change to any analysis, detector, threshold, Expected value, CPOR,
inventory, Source Learning, Decision Memory, Mia, the scheduler's semantics or the UI. Builds on [ADR 0044](0044-pilot-autonomy.md) (the worker's own tick).

## Context

The daily tick is a periodic task with a `queueing_lock`: one waits at most. Asking for a tick while one waits is not a failure, it is the design: Procrastinate raises
`AlreadyEnqueued`, its periodic deferrer logs a skip and goes on. It happens at every restart after a few minutes of silence, because the deferrer asks for every tick it missed and the
second finds the first waiting.

On the pilot machine the worker died of it, three minutes after it started. Measured, not guessed:

| | |
|---|---|
| Procrastinate | 3.9.0 (pinned `>=3.9,<3.10`); 3.10.0 is the latest stable |
| psycopg / psycopg-pool | 3.3.6 / 3.3.2 |
| PostgreSQL | 18.6, `lc_messages = Italian_Italy.1252`; the application role is not a superuser |
| Error | `psycopg.errors.UniqueViolation`, SQLSTATE `23505`, constraint `procrastinate_jobs_queueing_lock_idx_v1` (a partial unique index, `WHERE status = 'todo'`) |
| DETAIL | `La chiave (queueing_lock)=(analysis.daily_tick) esiste già.` |
| Raised at | `PeriodicDeferrer.defer_jobs` -> `JobManager.defer_periodic_job` -> `PsycopgConnector.execute_query_one_async` |
| Stopped by | `sync_psycopg_connector.wrap_exceptions`, line 36: `assert match` |

`wrap_exceptions` reads the lock's value out of the DETAIL with the English regular expression `Key \((.*?)\)=\((.*?)\)`. It fails on any other language, an `AssertionError` leaves
instead of `AlreadyEnqueued`, the deferrer (which catches only `AlreadyEnqueued`) ends, and the worker's side-task monitor stops the worker: "Side task deferrer failed with exception,
stopping worker". The lock's value is not even needed there (the manager reads it from the job). `recover_stalled_jobs` fails the same way: it expects a `ConnectorException`.

The tests never saw it: the worker tests use Procrastinate's in-memory connector, which raises the exception directly, and the API's own enqueue uses `ON CONFLICT`, which has no
exception at all.

## Upstream

Issue 1531 of Procrastinate describes exactly this (another language, `assert match`). It is open; the pull request linked to it is open and not merged; a user reports it on
3.10.0. No stable release has the fix, so there is nothing to upgrade to, and a pull request that is not merged is not a thing to pin. The dependency stays as it is.

## Decision

`worker/connector.py`: `QueueConnector`, a subclass of `PsycopgConnector` used by `worker/app.py`.

- It decides from what PostgreSQL says the same way in every language: the SQLSTATE (the class `psycopg.errors.UniqueViolation` is `23505`) and `diag.constraint_name`. It never reads a
  message, in any language.
- Only the one constraint of the queueing lock is turned into Procrastinate's `UniqueViolation`. Any other unique violation, and every other database error, goes on to the stock
  handling untouched: another constraint is still a `UniqueViolation`, a deadlock or a lost connection is still a `ConnectorException`, and nothing is swallowed.
- It is made at `_get_cursor`, the one place the stock connector hands every query a cursor, which runs before the stock error handling. That is a private hook of the pinned minor
  version, so the dependency stays `<3.10` and a test fails if the hook moves.
- No privilege, no PostgreSQL setting, nothing in the operating system. (`lc_messages` cannot be set by an application role: tried, no connection opened at all. It is also not a
  requirement the product should have.)

- A cancellation is not a collision. When a task is cancelled while its query is still running, psycopg lets the query finish and raises the query's own error instead of
  `CancelledError` (`AsyncConnection.wait` passes only `QueryCanceled` through). Turned into `AlreadyEnqueued`, that error made the periodic deferrer skip a tick and carry on: the
  cancellation was lost and the worker's shutdown waited for it for ever. It is the mechanism behind a hang of the worker-loop tests (a pytest that stayed stopped for over an hour).
  The conversion therefore does not happen when a cancellation has been requested on the task (`Task.cancelling()`): `CancelledError` is raised, with the unique violation as its cause.
  The mechanism is in psycopg and in Procrastinate's `except AlreadyEnqueued: continue`, so the stock connector on an English server converts the error the same way; on a server that
  is not English the stock connector raised an `AssertionError` there instead, and the worker stopped, which is the bug above. Only the conversion made here is guarded: every other
  error is re-raised as it was.

The cost: the exception carries `queueing_lock=None`, because the value is not available in a form that is the same in every language. The text of an `AlreadyEnqueued` raised by
`defer_jobs` says "None" where it used to say the lock. Nothing reads it: `dispatch.py` only catches the exception, and the periodic path takes the lock from the job.

The synchronous connector is not subclassed: NINFA defers through the async API only. If synchronous deferral is ever added, it needs the same hook.

## What stays the same

The scheduler: the cron, the tick, `recover_stalled_jobs`, the lock, restart-safety, job recovery and idempotency are untouched. A taken lock still means "skip", and now it means it on
every server. One tick still waits at most.

## Consequences

- A worker no longer stops when a tick is asked for while one waits, whatever language the server speaks. The same fix repairs `recover_stalled_jobs` on such a server.
- A new Procrastinate minor needs the hook checked. The control test fails when the stock connector stops needing this module, which is the moment to delete it.
- Procrastinate still ends its worker when its periodic deferrer fails for any *other* reason (a lost database connection, for instance). That is Procrastinate's own behaviour and is
  not changed here.

## Tests

`services/worker/tests/test_queueing_lock_locale.py`: the rule on simulated errors in English, Italian, German and with no detail (same result, through the stock error handling, with the
stock connector as the control that shows the bug); another constraint and other database errors not hidden; the manager making only the lock an `AlreadyEnqueued`; the real connector on
the real test database (lock free, taken, nothing duplicated, a real database error, the contract `recover_stalled_jobs` relies on); and real worker loops whose periodic deferrer meets a
lock that stays taken, alone and with two workers: alive, heartbeat advancing, one tick waiting, normal jobs run once each, and stopping when cancelled within a bound (a worker that does
not stop fails the test instead of hanging it). The cancellation race is pinned exactly, not by chance: another transaction holds the lock uncommitted so the deferral waits in the
server, it commits, the waiting insert fails and its answer waits in the socket, and the task is cancelled before the event loop reads it: the result must be a cancellation (without
the guard it is `AlreadyEnqueued`). It was run against a throw-away PostgreSQL whose messages are
Italian with the real `python -m worker run`, including a conflict at a real cron boundary and two worker processes at once.

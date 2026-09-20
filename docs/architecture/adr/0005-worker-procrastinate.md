# 0005 — Background worker with Procrastinate (PostgreSQL queue)

**Status:** accepted (Gate 0)

## Context
Imports, parsing, normalisation, recalculation and the decision engine will run asynchronously.
Options considered: Celery (heavy, weak Windows support), Arq (maintenance mode), Dramatiq or RQ
(need Redis), Procrastinate (queue stored in PostgreSQL).

## Decision
Procrastinate on the existing PostgreSQL. No Redis in V1. The worker lives in `services/worker`,
imports the API package for settings and logging, and is started with `python -m worker run`.
Only a smoke job (`system.heartbeat`) exists. The queue schema is installed by Alembic revision
`0002` from vendored SQL (Procrastinate 3.9.0), so history stays reproducible; upgrading the library
means adding a revision with that release's migration SQL.

On Windows, psycopg's async API needs a `SelectorEventLoop`; `worker/runtime.py` selects it with
`asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)` instead of the global policy.

## Consequences
- One less piece of infrastructure; jobs can be enqueued in the same transaction as business data.
- Queue throughput is bounded by PostgreSQL; fine for import/recalculation volumes expected.
- Smaller community than Celery. Switching to a Redis-based queue remains possible because task
  code is plain async functions.

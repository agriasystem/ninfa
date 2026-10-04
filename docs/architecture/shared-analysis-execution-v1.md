# Shared analysis execution V1 (Gate 25B)

Gate 25A audited what stands between "an operator runs the analysis CLI" and "NINFA analyses every
day". Gate 25B builds only the part that needs no unresolved product decision: one shared execution
path and a worker task that can run it. **It does not schedule anything.**

```
CLI  (app.cli.analysis: argparse, slugs -> ids, print, exit codes) --\
                                                                      --> run_property_analysis()
Worker (analysis.run_property: own Session, structured log)  --------/    app/modules/analysis
```

## Shared orchestration — `app/modules/analysis`

`run_property_analysis(session, AnalysisRunRequest) -> AnalysisRunResult` is the former body of
`run_analysis`, moved unchanged in behaviour: observed snapshots -> Expected -> revenue detectors
-> OTA -> optional costs -> optional labor -> coverage -> provenance -> priority ranking ->
`DecisionService.sync`. It computes nothing itself.

- Input is explicit and already resolved: workspace id, property id, booking data source id, stay
  window, optional labor source, optional cost year+month, optional currency. No default source, no
  default window, no default cost month: an omitted optional domain is recorded `SKIPPED /
  NOT_REQUESTED`, exactly as before.
- `cost_year`/`cost_month` come together or not at all. This is checked once, in
  `AnalysisRunRequest`, and raises `AnalysisInputError` (an `AppError`), so enqueueing a job and
  running one reject the same request.
- The caller owns the `Session`. The module never creates one, resolves slugs, prints, knows an exit
  code or imports argparse, Procrastinate, the CLI or the worker (enforced by worker tests).
- The result is a frozen dataclass with what the CLI prints: as-of date, snapshot/expected counts,
  evaluation counts, coverage, provenance, and the DecisionRun id / replay flag / lifecycle counts.

## CLI — unchanged for operators

`python -m app.cli.analysis run ...` keeps its arguments, its output lines and its exit codes. It
resolves slugs, builds the request, calls the shared function and prints the result. Two small,
deliberate differences: progress lines are printed after the run instead of while it runs (a run
that fails midway no longer prints its earlier step lines), and the inconsistent cost pair message
is now `Error: cost_year and cost_month must be given together` (it comes from the single shared
check). Exit code is still 1.

## Worker task — `analysis.run_property`

A **synchronous** task on the existing `default` queue (Procrastinate 3.9 runs sync tasks in a
thread pool; there is no `asyncio.to_thread`). Arguments are JSON strings/ints: every id, date and
optional domain is passed explicitly by whoever enqueues it. The task:

1. opens its **own** Session with `get_sessionmaker()()`;
2. calls the shared function (which builds the `TenantContext` from the workspace id);
3. closes the Session in every case; the services commit or roll back their own transactions.

Success logs `workspace_id`, `property_id`, `decision_run_id`, `is_idempotent_replay`. Any exception
is logged (ids and exception type only, no data) and **re-raised**: Procrastinate records the job as
`failed` and the real traceback is in the worker log. No DecisionRun is faked and no failure table
exists. Procrastinate 3.9 stores no task result, so there is none.

**No retry is configured.** The failures that matter (unknown ids, validation, snapshot CONFLICT,
out-of-order run) are deterministic; retrying would only loop. A transient-failure retry policy is a
later decision.

## Operator enqueue command

```
python -m worker enqueue-analysis --workspace-id <uuid> --property-id <uuid> \
    --booking-data-source-id <uuid> --stay-date-start 2026-10-01 --stay-date-end 2026-10-31 \
    [--labor-data-source-id <uuid>] [--cost-year 2026 --cost-month 9] [--currency EUR]
python -m worker run --once        # process the queued job(s), then exit
```

It enqueues exactly one job and prints the job id, property, window, booking source and whether
labor / costs are included or skipped. It only touches the queue (never the business database), so
bad ids are not caught at enqueue time: the job fails visibly instead. Exit is non-zero for invalid
arguments or when enqueueing fails.

## What is NOT solved

- **There is no scheduler.** Nothing enqueues analysis automatically: no periodic task, cron,
  startup hook, import trigger or dispatcher. The task is inert until an operator enqueues it.
- No property discovery, "analysis enabled" flag, primary booking source, stay-window default, run
  time or timezone-aware dispatch. These are product decisions listed in the Gate 25A audit.
- **Same-day changed-data conflict is intentional and unchanged.** OBSERVED snapshots are immutable
  per (source, local day, stay night). Identical data re-run the same day is a safe replay (no new
  DecisionRun); changed bookings analysed a second time the same day raise the existing snapshot
  CONFLICT, the job fails, and nothing is replaced.
- Failure visibility is Procrastinate job state plus worker logs; nothing is surfaced in the UI.
- The manual CLI remains fully supported and shares exactly this code.

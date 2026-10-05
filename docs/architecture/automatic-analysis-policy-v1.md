# Automatic Analysis Policy V1 (Gate 26B)

Gate 25 made the analysis runnable by a worker. Gate 26B adds the **policy** that says what may run
automatically, plus the commands an external scheduler uses. **Nothing inside NINFA schedules
anything**, and automation is **not hands-off** while booking intake is a manual file import.

## The frozen V1 policy

| Rule | V1 |
|---|---|
| Who | **Opt-in per property**, default disabled. Only AGRIA enables it, with an internal CLI. |
| Source | Exactly one explicit primary BOOKINGS data source per property. Never guessed. |
| Window | **30 stay dates** from the property-local today: `end = start + 29 days`, both inclusive (2026-10-05 -> 2026-11-03). Also the window REV_OTA_DEPENDENCY needs. |
| Domains | Revenue + Distribution. Costs and Labor are `SKIPPED / NOT_REQUESTED` (Oggi: "Non analizzati: Costi, Personale."). |
| Opportunity | **10:00 property-local**, invoked by an external scheduler. Not stored per property. |
| Import cut-off | **09:45** property-local: an operator/runbook rule, not stored and not checked as a threshold. |
| Today's import | The exact source has a `SUCCEEDED` import with `local midnight <= finished_at <= now`. One finished before local midnight does **not** count. |
| No import today | **Skip** (`NO_TODAY_BOOKING_IMPORT`): no snapshot, no run. Never a stale automatic run. |
| One run a day | A DecisionRun for the property-local date (manual or automatic) means skip (`ALREADY_ANALYZED_TODAY`). |
| Retry | None. A failed job stays failed. |
| Config changes | Apply to future opportunities only. Enabling, disabling or changing the source never runs anything. |
| Alerting | None. The status command and Oggi are the V1 visibility. |

Why skip instead of running on stale data: OBSERVED snapshots are immutable per (source, local day,
stay night). A run on yesterday's bookings would freeze today's observation, and a corrected import
could not be re-analysed the same day. A skipped day is recoverable with a manual run.

## Persistence

`property_analysis_policies` (migration `0013_property_analysis_policy`, additive, no rows inserted):
`id`, `workspace_id`, `property_id` (unique), `enabled` (default false), `booking_data_source_id`,
timestamps. Composite foreign keys reuse the existing unique constraints, so the source can never
belong to another property or workspace; `enabled` requires a source (CHECK). No JSONB, nothing on
`DataSource`, and no stay window, run time, cost or labor settings: those are fixed V1 code.
Absence of a row, and `enabled = false`, both mean "not automated". Disabling keeps the source as
history.

Code: `app/modules/analysis` - `policy.py` (enablement, the one configuration check),
`automatic.py` (the frozen rules, evaluation and the policy runner), `service.py` (Gate 25's shared
orchestration, unchanged).

## Fail-closed enablement and re-validation

`enable` refuses unless the workspace and property are active and not archived, the property's
timezone is valid, and the source belongs to exactly this workspace/property, is BOOKINGS and is
active. The dispatcher and the policy task re-check all of it on every opportunity and skip with a
typed reason - `WORKSPACE_INACTIVE`, `PROPERTY_INACTIVE`, `INVALID_BOOKING_SOURCE`,
`BOOKING_SOURCE_INACTIVE`, `INVALID_TIMEZONE` - never falling back to another source.

## Commands

```
# AGRIA configuration (internal CLI; no customer UI, no API)
python -m app.cli.analysis_policy enable  --workspace-slug W --property-slug P --booking-data-source-id <uuid>
python -m app.cli.analysis_policy disable --workspace-slug W --property-slug P
python -m app.cli.analysis_policy show    --workspace-slug W --property-slug P

# the automatic opportunity (run by the EXTERNAL scheduler)
python -m worker dispatch-analysis       # one analysis.run_policy job per eligible property
python -m worker run --once              # process the queued jobs, then exit

# read-only operator view
python -m worker analysis-status
```

`dispatch-analysis` evaluates every enabled policy of every workspace at one instant, enqueues one
`analysis.run_policy` job per eligible property (one pending job per property at most:
`JOB_ALREADY_QUEUED` otherwise) and prints `policies_total`, `eligible`, `enqueued`, `skipped` plus a
line per property with its typed reason. A skip is a normal outcome (exit 0). It does no analysis.
The task `analysis.run_policy` takes only the policy identity: it re-validates and computes the
dates **at execution time**, then calls the shared orchestration with Revenue + Distribution only.

`analysis-status` shows, for every enabled property: local date, whether a run exists today,
whether a qualifying import exists, the latest analysed business date, the configuration state and
what the next dispatch would do. It does **not** show the latest worker job status: Procrastinate
stores job arguments as JSON, so the lookup would couple it to Procrastinate's schema. Job state is
one SQL query away (`procrastinate_jobs`).

## External scheduler contract (not configured by this gate)

At 10:00 property-local time AGRIA infrastructure runs `python -m worker dispatch-analysis`, then
processes the queue with `python -m worker run --once` (or an already running worker). For the
Italy-only pilot one run at 10:00 Europe/Rome is enough; the code still reads each property's
timezone. There is no internal Procrastinate periodic job on purpose: a periodic tick missed for
more than ten minutes (for example a worker restart) is silently dropped, which is unsafe for a
once-a-day job. The scheduler host and its configuration are an AGRIA operations decision; the provider-neutral
deployment package, the daily wrapper (`scripts/run-daily-analysis.sh`) and the operator runbooks are in
[docs/operations/](../operations/README.md).

## Manual override

The Gate 25 CLI (`python -m app.cli.analysis`) and `python -m worker enqueue-analysis` stay
available. A manual run today also blocks the automatic one. Re-running the same data is a safe
replay; running again the same day **after the bookings changed** raises the existing snapshot
CONFLICT. This is intentional and unchanged: import before the cut-off, then let the day run once.

## Not solved / deferred

No automatic costs or labor, per-property run time, retries, alerts, import-triggered runs, wider
than 30 dates, long-lead snapshot backfill, customer settings UI, or scheduler host configuration.
While files are imported by hand the human step remains: the automation only removes the "run the
analysis" step.

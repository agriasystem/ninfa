# Automatic Analysis Policy (Gate 26B, Pilot Autonomy Gate)

Every property with bookings gets its analysis once per local day, with nobody asking: no browser, no login, no operator and no
external scheduler. The worker asks by itself ([ADR 0044](adr/0044-pilot-autonomy.md)).

An import made through the web page, and a room inventory saved, ask for their own refresh of the analysis: see
[post-import-analysis-v1.md](post-import-analysis-v1.md). A run they make counts as today's run here too.

## The rules

| Rule | |
|---|---|
| Who | Every property with exactly one active booking source and a successful import: the tick enrols it. Several active booking sources are never chosen between. A policy switched off (`enabled = false`) stays off. |
| Source | The one its policy names. Never another. |
| What | What a refresh looks at (`analysis/scope.py`): **30 stay dates** from the property-local today (`end = start + 29 days`, both inclusive, also the window REV_OTA_DEPENDENCY needs), the labor source on the dates it really has, the concluded months the invoices touch. |
| When | From **10:00 property-local** on (`DAILY_ANALYSIS_LOCAL_TIME`), once per local day. Not stored per property. |
| Today's import | Not needed. The bookings NINFA holds are analysed, and the run's provenance says when they last arrived. |
| Nothing ever imported | **Skip** (`NO_BOOKING_IMPORT`): no snapshot, no run. |
| One run a day | A DecisionRun for the property-local date (a refresh, an operator's, this) means skip (`ALREADY_ANALYZED_TODAY`). |
| A job that fails | Asked again 1 hour later, at most 3 times a day (`RETRY_NOT_DUE_YET`, `ATTEMPTS_EXHAUSTED`). The next local day starts again. |
| A job a dead worker left | Put back by a later tick, at most 3 times. |

Why it runs with no import: Gate 26B skipped because an observation could not be corrected the same day. Same-day revisions lifted
that: a file arriving later is the day's next revision. A day with no new booking data is told apart
([ADR 0045](adr/0045-no-new-booking-data-is-not-zero-pickup.md)): its pickup is not evaluated, and its observation is no sample of history.

## How it is asked for

`worker/daily.py`, a periodic task of the worker, every 5 minutes:

```
recover the jobs a dead worker left -> enrol the properties that became ready -> one analysis.run_policy job per property due now
```

Being due is worked out each time from what is stored (the property's own clock, today's run, today's failures), never from when the
tick last ran. So a tick missed, a tick repeated or a worker down for hours loses nothing: the next tick the same local day asks for
what is still missing. A day with the worker down all day is not recovered, because an observation cannot be dated in the past.

| What could go wrong | Why it does not |
|---|---|
| A restart, or two workers | the queue's own table holds one tick per moment |
| Asked twice before the worker ran | `queueing_lock`: one job waits per property |
| A job run twice | the policy task evaluates again when it runs, and a run today means skip |
| A refresh at the same time | the same `lock`: one analysis of a property runs at a time |
| Another property's failure | every count is per property |

## Persistence

`property_analysis_policies` (migration `0013_property_analysis_policy`): `id`, `workspace_id`, `property_id` (unique), `enabled`,
`booking_data_source_id`, timestamps. Composite foreign keys reuse the existing unique constraints, so the source can never belong to
another property or workspace; `enabled` requires a source (CHECK). Absence of a row, and `enabled = false`, both mean "not automated":
the tick writes the row of a property that has none and is ready. Disabling keeps the source as history.

Code: `app/modules/analysis` - `policy.py` (enablement, the one configuration check), `automatic.py` (the rules, the evaluation, the
enrolment), `scope.py` (what an analysis looks at), `queue.py` (the queue's own rows), `service.py` (Gate 25's shared orchestration).

## Fail-closed configuration

`enable` refuses unless the workspace and property are active and not archived, the property's timezone is valid, and the source belongs
to exactly this workspace/property, is BOOKINGS and is active. Every opportunity checks all of it again and skips with a typed reason
(`WORKSPACE_INACTIVE`, `PROPERTY_INACTIVE`, `INVALID_BOOKING_SOURCE`, `BOOKING_SOURCE_INACTIVE`, `INVALID_TIMEZONE`), never falling back to
another source.

## Commands

Nobody has to run these for the day's analysis to happen.

```
# switching one property off, or naming its source
python -m app.cli.analysis_policy enable  --workspace-slug W --property-slug P --booking-data-source-id <uuid>
python -m app.cli.analysis_policy disable --workspace-slug W --property-slug P
python -m app.cli.analysis_policy show    --workspace-slug W --property-slug P

# an operator's catch-up, at any hour (no enrolment, no daily hour)
python -m worker dispatch-analysis       # one analysis.run_policy job per eligible property
python -m worker run --once              # process the queued jobs, then exit

# read-only view
python -m worker analysis-status
```

`analysis-status` shows, for every enabled property: local date, whether a run exists today, whether a booking import arrived today,
the latest analysed business date, the configuration state and what a dispatch would do. It does **not** show the latest worker job
status: Procrastinate stores job arguments as JSON. Job state is one SQL query away (`procrastinate_jobs`).

## Manual override

The Gate 25 CLI (`python -m app.cli.analysis`) and `python -m worker enqueue-analysis` stay available. A manual run today also counts as
today's. Re-running the same data is a safe replay; running again the same day **after the bookings changed** analyses the day's next
revision ([same-day-revisions-v1.md](same-day-revisions-v1.md)).

## Not solved / deferred

A run time per property, alerts when a day has no run, a notion of how old the bookings are, automatic intake of the files.

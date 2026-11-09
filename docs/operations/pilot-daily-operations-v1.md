# Pilot daily operations V1 (Gate 27B)

The exact daily sequence the **supported** capabilities allow. The analysis needs nobody: the **worker** asks for it by itself, once per
property-local day ([ADR 0044](../architecture/adr/0044-pilot-autonomy.md)). What stays manual is bringing the data: the hotel imports its
files from the web page, or an operator through the CLI below. Nothing here is native PMS automation. `ninfa-py` is defined in the
[deployment document](pilot-deployment-v1.md) ("Operator shell helpers"); the business rules behind
the policy are in [automatic-analysis-policy-v1.md](../architecture/automatic-analysis-policy-v1.md).

## Daily timeline (property-local time, Europe/Rome for the first pilot)

| When | Who | What |
|---|---|---|
| any time | hotel, or an operator | brings a file: the analysis follows by itself |
| from **10:00** | **the worker** | asks for the day's analysis of every property that has no run today, on its own clock |
| about **10:15** | AGRIA operator (supervision, not a step of the day) | `ninfa-py -m worker analysis-status`: **every enabled property should show `run_today=YES`** |
| afterwards | hotel | opens Oggi |

The hour is the property's own: `Europe/Rome` for the first pilot, and each property's own named timezone for any other. No file is needed
that morning: the bookings NINFA holds are analysed, and Oggi says when they last arrived. A day with no new booking data has no pickup
evaluation and is no sample of history ([ADR 0045](../architecture/adr/0045-no-new-booking-data-is-not-zero-pickup.md)). `REV_OCCUPANCY_RISK` and
labor still read the bookings last known: bring the file before reading those decisions as news.

## The catch-up wrapper

Nobody has to run it: the worker does the day's work. It is for an operator who wants the analysis now, at any hour.
`scripts/run-daily-analysis.sh` runs, in order and always all three:

1. `python -m worker dispatch-analysis` — evaluates every enabled property and enqueues one job per
   eligible property (skips visibly with a typed reason otherwise);
2. `python -m worker run --once` — processes **every** queued job, then exits;
3. `python -m worker analysis-status` — prints whether today's run exists for each enabled property.

It needs the production environment loaded **externally** (`DATABASE_URL`, `APP_ENV=production`;
for example systemd `EnvironmentFile=` or `scripts/with-env.sh /etc/ninfa/api.env …`), runs from the
repository root (override with `NINFA_APP_DIR`) and logs timestamped start/end/exit code per step
plus a summary line. It refuses to start (exit 2, nothing run) if `DATABASE_URL` is missing,
`APP_ENV` is not `production` or `TEST_DATABASE_URL` is set. It exits 0 only if all three commands
exited 0, and 1 otherwise.

> **A zero exit does NOT prove the analyses succeeded.** `worker run --once` exits 0 even when a
> queued job failed, and `analysis-status` exits 0 even when an enabled property has no run today.
> The wrapper logs what happened honestly and does not parse human-readable output.

Manual run, as the service account:
`sudo -u ninfa "$NINFA_APP/scripts/with-env.sh" /etc/ninfa/api.env "$NINFA_APP/scripts/run-daily-analysis.sh"`.

## How the day's analysis is asked for

- The worker runs a tick every 5 minutes. No scheduler has to be configured, and no timer is shipped.
- For each property it reads the property's own clock from its **named timezone**, so daylight saving needs no care: 10:00 in `Europe/Rome` stays
  10:00 on the last Sunday of March and of October. A fixed UTC time would be an hour off for half of the year, which is why none is used.
- It asks only for what is missing. A worker that was down asks at its first tick after coming back, the **same local day**. A day with the worker
  down all day is not recovered: an observation cannot be dated in the past. **So the one thing to keep alive is `ninfa-worker`.**
- **Manual catch-up is supported:** running the wrapper at any hour is safe. It skips a property that already has a run today and one that has never
  imported anything (`NO_BOOKING_IMPORT`).

## File intake (the supported first-pilot process)

There is no HTTP upload, no object storage and no customer upload screen. Import is the CLI
reading a file **on the production host**.

1. **Hotel export** → sent to AGRIA through the agreed secure channel.
2. **Normalize** to NINFA's canonical CSV where required (header names, `YYYY-MM-DD` dates, `.`
   decimals, UTF-8), on an AGRIA workstation. Details: [pilot readiness](../architecture/pilot-readiness-v1.md).
3. **Retain the original export** in AGRIA's own secure storage according to AGRIA's retention
   policy. NINFA keeps no copy of the file; this is how a data loss is recovered.
4. **Transfer the canonical file** to `/var/lib/ninfa/incoming/` on the production host with the
   operator's personal SSH identity, then `chmod 660` it. The directory is restricted to the
   service and operator accounts (mode 2770); it is **not world-readable**. Never put files in the
   repository directories.
5. **Import:**
   ```bash
   ninfa-py -m app.cli.imports bookings --workspace-slug <W> --property-slug <P> \
       --data-source-id <BOOKINGS data source id> --file /var/lib/ninfa/incoming/<file>.csv
   ```
6. **Verify:** the line shows `status=SUCCEEDED` and the exit code is 0. Read any
   `WARNING unrecognized_columns=…` line: a header that did not match a canonical field was
   ignored (a typo of an optional column is indistinguishable from an irrelevant column). A failed
   import persists **nothing**: fix the file and re-import (the same file twice is a safe no-op).
7. **Remove the working copy** from the production host (`rm` the file) once the import succeeded.
8. `ninfa-py -m worker analysis-status` should now show `today_import=YES`.

Labor and invoice imports are read by the daily run wherever they exist: it looks at what a refresh looks at.

## The 10:15 supervision and what to do

`ninfa-py -m worker analysis-status` prints, per enabled property:
`run_today=YES|NO today_import=YES|NO latest_analysis=<date> configuration=VALID|<reason>
next_dispatch=ELIGIBLE|SKIPPED:<reason>`.

| What you see | Meaning | Action |
|---|---|---|
| `run_today=YES` | today's analysis exists | nothing |
| `run_today=NO`, `next_dispatch=SKIPPED:NO_BOOKING_IMPORT` | this source has never delivered | nothing to analyse: bring the first file |
| `run_today=NO`, `next_dispatch=ELIGIBLE` | the worker is down, or the job failed, or it is still running | check that `ninfa-worker` is up and read its log (below): a failed job is asked again by itself, 1 hour later, 3 times a day |
| `configuration=` shows a reason (for example `BOOKING_SOURCE_INACTIVE`) | the property's automation configuration is no longer valid | `ninfa-py -m app.cli.analysis_policy show …`, fix the cause, then run the wrapper |

Investigating, without SQL:

```bash
journalctl -u ninfa-daily-analysis --since today      # the wrapper's own log (if started via the unit)
journalctl -u ninfa-worker --since today              # the job logs (Policy analysis job … status=…)
ninfa-py -m procrastinate -a worker.app.app shell     # then: list_jobs status=failed
                                                      #       list_jobs status=doing
                                                      #       list_jobs task=analysis.run_policy details
```

(`list_jobs …` output shows only task names, statuses and identifiers. Do not use the shell's `retry`
or `cancel` commands without a developer.)

- A **failed** day's job stays failed, and the tick asks for a new one 1 hour later, at most 3 times a day. Read its error in the worker log.
- A job stuck in **`doing`** is a **zombie** left by a killed worker. A later tick puts it back, at most 3 times (`Stalled job put back` in the log).
  One still there after that has been marked failed: tell a developer.
- Manual recovery is safe only through the supported commands: re-running the wrapper, or the
  explicit manual commands (`python -m app.cli.analysis run …`, `python -m worker enqueue-analysis
  …`). **Never edit rows or delete snapshots to "fix" a day.**

## Several files on one day

A property can import as many files as it needs, of any kind, on any day (see
`docs/architecture/same-day-revisions-v1.md`):

- bookings changed after today's analysis: the day's next observation, and a new analysis the same day.
  The earlier observation stays as it was, and the earlier run keeps pointing at it;
- a second staff file: new days live beside the others, the (day, department) it holds are replaced, and
  hours and costs never add up. A department it lacks on a day stays, even if the file has that day and
  that department elsewhere: only a file said to be complete takes it away. A row of 0 hours is a plan of
  zero hours, not a removal;
- a corrected row of a cost spreadsheet: the document's next version, and only the newest counts. A
  FatturaPA that comes back different is refused, on purpose: it is corrected by a credit note;
- the same data again: nothing moves, and the page says so;
- a file that leaves out something NINFA holds: the page asks once whether it holds everything of its
  period. If it does, what it no longer holds stops counting and stays in the history, and the summary says how
  much before anything is imported. If it holds a part, or only what is new, nothing goes. The answer is
  remembered for files of that structure, but a remembered "complete" asks again whenever something would stop
  counting, and that answer is about that import unless "Ricorda questa scelta" is ticked
  (`docs/architecture/import-scope-semantics-v1.md`). The CLI imports never ask, and so never take anything away.

A re-run by hand (`python -m app.cli.analysis`) follows the same rules, and with identical data it is a safe
replay. **Never delete snapshots or edit the database to "fix" a day:** a file with the right data is enough.

## Weekly and periodic

- Extend **room inventory** ahead of the rolling 30-date window: nothing extends it automatically
  (without it occupancy and channel-mix decisions report insufficient data).
- Check that backups ran, and review the Ask NINFA spend at the provider (if enabled).
- Review the logs for repeated failures.
- Keep the data source ids of every property in AGRIA's own records: there is no list command.

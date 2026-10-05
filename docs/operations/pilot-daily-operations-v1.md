# Pilot daily operations V1 (Gate 27B)

The exact daily sequence the **supported** capabilities allow. It is **operator-assisted**: booking
intake is a manual file import and nothing here is native PMS automation. Automation removes only
the step "run the analysis". `ninfa-py` is defined in the
[deployment document](pilot-deployment-v1.md) ("Operator shell helpers"); the business rules behind
the policy are in [automatic-analysis-policy-v1.md](../architecture/automatic-analysis-policy-v1.md).

## Daily timeline (property-local time, Europe/Rome for the first pilot)

| When | Who | What |
|---|---|---|
| before **09:45** | AGRIA operator | receive the hotel's export → normalize → transfer → import → check (see "File intake") |
| before 10:00 | operator | `ninfa-py -m worker analysis-status`: the property shows `today_import=YES` and `next_dispatch=ELIGIBLE` |
| **10:00** | **external scheduler** | runs `scripts/run-daily-analysis.sh` |
| about **10:15** | **AGRIA operator (mandatory)** | `ninfa-py -m worker analysis-status`: **every enabled property must show `run_today=YES`** |
| afterwards | hotel | opens Oggi |

The 09:45 cut-off is **operator discipline**, not a stored threshold. The dispatcher uses "a
successful booking import exists by dispatch time", so an import that finishes after 09:45 but
before the dispatch still counts. An import finished **before local midnight** (for example the
previous evening) does **not** count for today.

## The daily wrapper

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
> The wrapper logs what happened honestly and does not parse human-readable output. **The 10:15
> operator check is the control.**

Manual run, as the service account:
`sudo -u ninfa "$NINFA_APP/scripts/with-env.sh" /etc/ninfa/api.env "$NINFA_APP/scripts/run-daily-analysis.sh"`.

## External scheduler contract (not configured by this repository)

- Run the wrapper **once a day at 10:00 in the named timezone `Europe/Rome`**.
- The scheduler **must support a named timezone**, or otherwise handle daylight saving correctly. A
  schedule written as a fixed UTC time is **not** equivalent: it is an hour off for half of the
  year. Check the behaviour around the last Sunday of March and of October.
- It runs as the service account with the production environment, keeps the output (the journal
  when started through `deploy/systemd/ninfa-daily-analysis.service`) and is monitored by the 10:15
  check: a scheduler that silently does not fire is caught there.
- Examples of mechanisms that *may* satisfy this (verify DST behaviour on the actual host): a systemd
  calendar event that carries a timezone, a cron implementation with a timezone setting, a platform
  scheduler with a named-timezone option. No timer is shipped and none is enabled by this package.
- **Manual catch-up is supported:** running the wrapper later the **same local day** is safe and
  normal (a late import, a late scheduler, a failed run). The dispatcher skips a property that
  already has a run today and one that has no import today. Running it **after local midnight** is a
  different day: the earlier day is not recovered.
- Running the wrapper before the import is harmless: the property is skipped
  (`NO_TODAY_BOOKING_IMPORT`) and nothing is persisted.

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

Labor and invoice imports exist but are **not** part of the automatic daily run in V1.

## The 10:15 check and what to do

`ninfa-py -m worker analysis-status` prints, per enabled property:
`run_today=YES|NO today_import=YES|NO latest_analysis=<date> configuration=VALID|<reason>
next_dispatch=ELIGIBLE|SKIPPED:<reason>`.

| What you see | Meaning | Action |
|---|---|---|
| `run_today=YES` | today's analysis exists | nothing |
| `run_today=NO`, `next_dispatch=SKIPPED:NO_TODAY_BOOKING_IMPORT` | no qualifying import today | import now (file-intake steps), then **run the wrapper** (same-day catch-up) |
| `run_today=NO`, `next_dispatch=ELIGIBLE` | the dispatch did not run, or its job failed, or it is still running | check the scheduler output and the worker log (below), then **run the wrapper** |
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

- A **failed** job stays failed; **nothing retries automatically**. Read its error in the worker log.
- A job stuck in **`doing`** is a **zombie** left by a killed worker; nothing recovers it. It does not
  block the next dispatch. Re-run the wrapper if there is no run today, and tell a developer.
- Manual recovery is safe only through the supported commands: re-running the wrapper, or the
  explicit manual commands (`python -m app.cli.analysis run …`, `python -m worker enqueue-analysis
  …`). **Never edit rows or delete snapshots to "fix" a day.**

## Changed bookings after today's analysis (snapshot conflict)

Each day's observation (a property's snapshot per stay night) is **immutable**. If the bookings
**changed after today's analysis** (a corrected re-import, or a manual analysis earlier in the day on
older data followed by a new import), a **changed-data re-run the same day may fail on purpose**
with a snapshot conflict. That is the product working as designed, not a fault:

- the day keeps its first observation; the next day's run proceeds normally;
- re-running with identical data is a safe replay (no new run);
- **do not delete snapshots, edit the database or try to force a re-run.**

To avoid it: finish the import before the dispatch, and do not run a manual analysis before today's
import.

## Weekly and periodic

- Extend **room inventory** ahead of the rolling 30-date window: nothing extends it automatically
  (without it occupancy and channel-mix decisions report insufficient data).
- Check that backups ran, and review the Ask NINFA spend at the provider (if enabled).
- Review the logs for repeated failures.
- Keep the data source ids of every property in AGRIA's own records: there is no list command.

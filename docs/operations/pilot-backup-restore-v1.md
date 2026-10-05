# Backup and restore V1 (Gate 27B)

Everything NINFA knows is in **one PostgreSQL database**: users, credentials and sessions;
workspaces, properties and data sources; imports and staged rows; canonical bookings, labor and
invoices; room inventory; **observed snapshots**; Expected baselines; DecisionRuns, decisions and
observations; automatic-analysis policies; and the Procrastinate job queue. **Observed snapshots are
the daily, immutable history and cannot be rebuilt exactly from a later file**, so the database
backup is the only complete copy of them. NINFA does not store the hotels' source files.

This document is provider-neutral: it names requirements and a checklist, not commands of any
particular service.

## Requirements (first-pilot minimum)

- [ ] **Managed automated backups**, at least **daily**.
- [ ] **Point-in-time recovery (PITR)** enabled on the production database.
- [ ] A **backup (snapshot) immediately before every migration** (deployment step 3), with its
      identifier and time recorded in the release notes.
- [ ] The hotels' **original source exports are retained by AGRIA** under AGRIA's retention policy
      (the way to re-import bookings; the application and the production host do not keep them).
- [ ] Backups are in the **same or an approved region** as the data (EU for the Italian pilot) and
      are encrypted at rest by the provider.
- [ ] **A restore has been tested successfully BEFORE the first customer launch**, and is repeated
      **periodically** (AGRIA chooses the interval; at least after any change of backup
      configuration or database provider).
- [ ] The recovery targets (how much data AGRIA can afford to lose, how long it can be down) are
      written down by AGRIA. This document does not invent them.

## Restore acceptance checklist

The restore test is **never** performed over production. Always restore into a **new, isolated
database**.

1. **Restore into an isolated database** with a different name (and, ideally, a different server)
   from production, using the provider's restore function from a recent backup or a PITR moment.
   Record which backup/time was used.
2. **Connect** to the restored database with the application role, from an environment that cannot
   reach production data (a temporary env file, never `/etc/ninfa/api.env`, with
   `ASK_NINFA_PROVIDER=unconfigured` and no API key).
3. **Alembic current is correct:** `current` shows the revision that matches the backup's release
   (the head of the release that was running, for example `0013_property_analysis_policy`), and
   `alembic check` reports no differences.
4. **Critical tables are readable**, by an AGRIA administrator with a read-only session: row counts
   look right for `users`, `workspaces`, `properties`, `data_sources`, `import_jobs`, `bookings`,
   `booking_snapshots`, `decision_runs`, `decisions`, `property_analysis_policies`.
5. **Oggi and history are readable.** Start an **isolated** API instance (loopback, a port that is
   not production's, the temporary env file; **no worker and no scheduler**) and, through an SSH port
   forward, log in and open Oggi and a Decision's history. If a browser is not practical, at least
   run `worker analysis-status` against the restored database: it must show the expected enabled
   properties and their latest analysis dates.
6. **Nothing wrote to production**, and nothing from the restore (jobs, scheduler, workers) ran
   against production.
7. **Tear down** the restored database and the temporary env file, and record the result: date,
   backup used, who ran it, how long it took, what failed.

## If production data is really lost

Restore into a **new** database first, verify it with the checklist above, and only then repoint
`DATABASE_URL` (a deliberate, recorded change) and restart the services. Do not overwrite the
damaged production database in place, and do not run a schema downgrade. After a restore, re-import
from AGRIA's retained exports whatever happened after the restored moment, and expect that
**observed snapshots for the lost days cannot be recreated**.

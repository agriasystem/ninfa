# Pilot readiness v1 (Gate 21B)

## What this closes

Gate 21A (Pilot Readiness & Data Intake Audit) found the domain services genuinely
production-quality (booking/invoice/labor import, Expected calculation, all four detectors,
priority ranking, decision persistence) but reachable **only from the test suite** - zero HTTP
routes, zero CLI commands, zero orchestration composing them. This gate closes exactly the three
P0 blockers that finding identified, with the smallest possible surface: three new internal CLI
modules under `app/cli/`, reusing every existing model, repository and service unchanged. No
migration, no new dependency, no HTTP endpoint, no scheduler, no UI.

This is an **internal AGRIA-operator workflow**, not customer self-service: an operator with
shell access to the API service runs these commands on the hotel's behalf.

## Prerequisites

- The API service's Python environment, with `DATABASE_URL` pointing at the pilot's database.
- The hotel has exported its booking data (and, optionally, cost/labor data) as files.

## 1. Tenant and property setup

`python -m app.cli.pilot`, one command per step:

```
create-workspace     --name "Hotel Aurora" --slug hotel-aurora
create-property       --workspace-slug hotel-aurora --name "Hotel Aurora" --slug hotel-aurora \
                       --timezone Europe/Rome --currency EUR
create-user            --email operator@example.com --display-name "Operator"
```

Set that user's password the existing way (Gate 13, unchanged):

```
python -m app.cli.auth set-password --email operator@example.com
```

```
grant-access          --workspace-slug hotel-aurora --email operator@example.com --role OWNER
create-data-source     --workspace-slug hotel-aurora --property-slug hotel-aurora \
                       --domain BOOKINGS --name "Bookings"
set-room-inventory     --workspace-slug hotel-aurora --property-slug hotel-aurora \
                       --stay-date-start 2026-10-01 --stay-date-end 2026-12-31 \
                       --rooms-available 24
```

`create-data-source --domain` also accepts `COSTS` and `LABOR`, one data source per domain the
hotel has files for. `set-room-inventory` is optional: `REV_OCCUPANCY_RISK` and
`REV_OTA_DEPENDENCY` legitimately report `INSUFFICIENT_DATA` without it, they never crash.

Every command prints the id it created (`Workspace created: slug=... id=...`, etc.) - copy those
ids into the next commands. Nothing here is guessed or defaulted from a "current" tenant: every
command names its workspace/property explicitly.

## 2. Data intake: the ONE canonical pilot format per domain

There is no mapping-review UI. Instead, each file format is fixed:

- **Bookings / labor (CSV)**: the header row must use the service's own canonical field names
  exactly (case-insensitive) - e.g. `source_record_id,booked_at,check_in,check_out,status,rooms,
  room_revenue,channel` for bookings, `work_date,labor_category,planned_hours,planned_cost,
  currency` for labor. Dates are `YYYY-MM-DD`, decimals use `.`, encoding is UTF-8, delimiter is
  `,`. The CLI derives the column mapping from whichever canonical names are present as headers
  and confirms it automatically before every import - see `CanonicalField`
  (`app/modules/bookings/mapping.py`) and `LaborField` (`app/modules/labor/mapping.py`) for the
  full, required and optional, field lists.
- **Invoices (FatturaPA XML)**: a real Italian e-invoice XML file, parsed directly with no mapping
  step at all (`app/modules/invoices/fatturapa.py` - this already existed before this gate).

A hotel whose export does not match this convention needs a developer to reshape the file before
import; there is deliberately no generic, user-configurable mapping engine in V1 (see
[Gate 21A's recommendation](architecture-v1.md) against building one before a real pilot needs it).

```
python -m app.cli.imports bookings --workspace-slug hotel-aurora --property-slug hotel-aurora \
    --data-source-id <booking-data-source-id> --file bookings.csv
python -m app.cli.imports labor    --workspace-slug hotel-aurora --property-slug hotel-aurora \
    --data-source-id <labor-data-source-id> --file labor.csv --snapshot-local-date 2026-09-29
python -m app.cli.imports invoices --workspace-slug hotel-aurora --property-slug hotel-aurora \
    --data-source-id <cost-data-source-id> --file invoice.xml
```

## 3. Validation

Every import command prints its outcome on one line (`status=SUCCEEDED|FAILED
error_code=... rows_total=... rows_invalid=... created=...`) and exits non-zero on failure. A file
with even one invalid row imports **nothing** (all-or-nothing per file, unchanged from Gate 2/6/8's
own behaviour) - fix the file and re-import; re-running the same file twice is a safe, idempotent
no-op (content-fingerprint deduplication, unchanged).

## 4. Analysis execution

```
python -m app.cli.analysis run --workspace-slug hotel-aurora --property-slug hotel-aurora \
    --booking-data-source-id <id> --stay-date-start 2026-10-01 --stay-date-end 2026-11-30 \
    [--labor-data-source-id <id>] [--cost-year 2026 --cost-month 8] [--currency EUR]
```

This is the ONE production entrypoint composing, in order: observed booking snapshots (Gate 3,
always today's real date - never an operator-supplied one), Expected baselines (Gate 4), the
revenue detectors (Gate 5, every stay date in the window), OTA dependency (Gate 9, property-wide),
cost CPOR anomaly (Gate 7, only if `--cost-year`/`--cost-month` are given), labor overstaffing
(Gate 8, only if `--labor-data-source-id` is given), priority ranking (Gate 10) and decision
persistence (Gate 11). No detector's threshold, formula or business rule is touched by this
command - it only calls the same services the test suite already exercises, in the same order.

**Fail loud, never a false all-clear** (the exact Gate 21A finding this closes): every detector
call above runs outside any `try`/`except` that could swallow it. If one raises, this command
prints nothing further and exits non-zero, and `DecisionService.sync()` is **never called** - so a
half-finished run can never look like a genuine all-clear on Oggi. A run either evaluates
everything it attempted, or it persists nothing at all.

Re-running the same day is a safe idempotent replay (`is_idempotent_replay=true`, zero new
writes) - the analysis's own existing idempotency (input-fingerprint keyed) is unchanged.

## 5. Where to inspect the result

Nothing here is new: the operator (or the hotel, once granted access) logs in through the existing
Gate 13 session login and opens Oggi, exactly as with the demo property. Decision Detail and
Ask NINFA work unchanged. With little or no history yet, every detector legitimately reports
`INSUFFICIENT_DATA` (cold start is preserved end to end, never faked into a trigger) - Oggi will
show `DATA_QUALITY_LIMITED` or `NO_ACTION_REQUIRED` until enough real history accumulates.

## 6. Common failure states

| Symptom | Cause | Fix |
|---|---|---|
| `create-property`/`create-data-source` etc. fail with "not found" | Wrong or not-yet-created workspace/property slug | Re-check the slug from the earlier `create-workspace`/`create-property` output |
| Import `status=FAILED error_code=VALIDATION_FAILED` | One or more rows failed validation | Fix the file; nothing was imported |
| Import `status=FAILED error_code=MAPPING_REQUIRED` | Headers don't match the canonical field names | Rename the file's columns to the canonical names listed above |
| `analysis run` fails with a data-source error | A `--*-data-source-id` is wrong, wrong-domain, or belongs to another property | Re-check the id against `create-data-source`'s own printed output |
| Oggi stays `NOT_PROCESSED` for today | `analysis run` genuinely failed (see its own error) or was never run for that day | Fix the underlying error and re-run; nothing partial was ever written |

## Explicitly out of scope (deferred, not built here)

A scheduler/periodic trigger (this is a manually-run CLI, not a cron job), HTTP endpoints for any
of the above, a generic/user-configurable column mapping engine, a supplier duplicate-review
interface, unmapped-channel logging/alerting, data-freshness/staleness detection, an
impossible-occupancy anomaly flag, customer self-service onboarding, a connector framework, a PMS
marketplace, SFTP/OAuth integrations, a data lake/warehouse, and any new microservice. See Gate
21A's own report for the full P1/P2/out-of-scope classification this gate deliberately left alone.

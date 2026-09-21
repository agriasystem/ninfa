# NINFA — Architecture v1 (Gates 0–7)

Scope: the technical foundation (Gate 0), the canonical multi-tenant data core (Gate 1), the
booking ingestion with the canonical booking model (Gate 2), the room inventory with the daily
booking snapshots (Gate 3), the first Expected baselines (Gate 4), the first two revenue
detectors (Gate 5), the supplier registry with the invoice ingestion (Gate 6) and the first cost
detector, the cost per occupied room (Gate 7). No NINFA product feature is implemented: data goes
in, is stored correctly, is turned into daily "on the books" facts, into a historical "expected
level" and into typed, non-persisted revenue and cost evaluations, and purchase invoices become
canonical suppliers, invoices and lines; no alert, decision, priority or recommendation exists yet.
Data model: [data-model-v1.md](data-model-v1.md). Bookings: [booking-data-v1.md](booking-data-v1.md).
Snapshots: [booking-snapshots-v1.md](booking-snapshots-v1.md). Expected:
[expected-engine-v1.md](expected-engine-v1.md). Revenue decisions:
[revenue-decisions-v1.md](revenue-decisions-v1.md). Costs (suppliers and invoices):
[cost-ingestion-v1.md](cost-ingestion-v1.md). Cost per occupied room:
[cost-cpor-anomaly-v1.md](cost-cpor-anomaly-v1.md).

## Components

```
Browser ──► apps/web (Next.js) ──► services/api (FastAPI) ──► PostgreSQL
                                        ▲                         ▲
                                        └── services/worker ─────┘
                                            (same backend codebase, job queue in PostgreSQL)
```

| Component           | Responsibility today                                                        |
| ------------------- | --------------------------------------------------------------------------- |
| `apps/web`          | Technical shell: shows whether the API is reachable. No product UI.         |
| `services/api`      | HTTP API under `/api/v1/` (health only), config, logging, error model, the tenant-scoped data core, the booking and invoice import services, the snapshot and Expected services. |
| `services/worker`   | Runs background jobs from a PostgreSQL-backed queue. Only a smoke job exists (the booking import is not a job yet: there is no file storage). |
| PostgreSQL          | The single datastore: the multi-tenant core, the bookings, the suppliers and invoices, and the job queue. |
| `packages/contracts`| A few hand-written TypeScript types mirroring the backend (health, errors). |

The worker imports the API package (`app.core.config`, `app.core.logging`): one backend codebase,
one uv workspace, two entrypoints. Both share the same environment file and database.

## Modular monolith

One deployable backend, organised in modules under `services/api/app/modules/`. Rules:

- A module owns its models, schemas and logic; other modules go through its public functions,
  not its tables.
- Layers stay thin: `api/` (HTTP) → `modules/` (business logic) → `db/` (persistence).
- Ten modules exist: `identity` (User), `tenancy` (Workspace, WorkspaceMembership), `properties`
  (Property), `ingestion` (DataSource, ImportJob, ImportFile) since Gate 1, `bookings` since Gate 2,
  `snapshots` (RoomInventoryDaily, BookingSnapshot) since Gate 3, `intelligence/expected`
  (BookingExpectedBaseline, BookingExpectedComparable) since Gate 4 (the first of the Decision
  Engine stages), `intelligence/revenue` since Gate 5 and `intelligence/costs` since Gate 7 (no
  model in either: their detectors and typed evaluations), `suppliers` (Supplier, SupplierIdentifier, SupplierAlias, SupplierResolutionReview)
  and `invoices` (Invoice, InvoiceLine, InvoiceMappingProfile, InvoiceImportRow) since Gate 6.
  Importing `app.models` registers every model.
- Application services (`bookings/service.py`, `snapshots/observed.py`,
  `snapshots/reconstruction.py`, `intelligence/expected/service.py`,
  `intelligence/revenue/service.py`, `invoices/service.py`, `suppliers/resolution.py`) are plain classes: they depend on a `Session` and a
  `TenantContext`, never on FastAPI (a test enforces it), so a future worker or authenticated
  endpoint can call them as they are. Framework-free exceptions live in `app/core/exceptions.py`.
- The directories for the future domains (`labor`, `normalization`,
  `data_quality`, `intelligence/{detection,impact,priority,recommendation}`, `decisions`,
  `decision_memory`, `ai/*`) are empty package markers so the structure is settled before those
  domains land.
- Splitting a module into a service is a possible future step, never a starting point.

## API conventions

- Versioned prefix `/api/v1/`. Health: `GET /api/v1/health` → `{status, service, version}`.
- **No business endpoint is exposed.** Tenant-facing APIs will be published together with the
  authentication/authorization layer; exposing CRUD earlier (or faking the tenant with a header)
  would suggest a security model that does not exist yet.
- One error shape for every non-2xx response:
  `{"error": {"code", "message", "details", "request_id"}}`. Validation errors never echo the
  submitted values. Unhandled exceptions return a generic `internal_error`.
- `X-Request-ID` is accepted (if it is short and safe) or generated, returned on every response
  and attached to every log line.
- The version is defined once, in `services/api/pyproject.toml`, and read at runtime.
- The **OpenAPI schema generated by FastAPI/Pydantic is the authoritative API contract.**
  `packages/contracts` is intentionally minimal; how frontend types are derived from OpenAPI
  (if generated at all) will be decided in a later gate.

## Configuration and security foundations

- Typed settings (`pydantic-settings`) read from environment variables, plus the root `.env`
  (gitignored). `.env.example` is the template. Nothing sensitive is hardcoded or committed.
- `APP_ENV` = `development | test | production`. In production the API refuses to start with
  `DEBUG=true` or a wildcard CORS origin, and interactive docs are disabled.
- CORS is an explicit allow-list (`CORS_ORIGINS`); empty means no cross-origin access.
- The application connects with a dedicated non-superuser role (`ninfa_app`).
- **Authentication and authorization are not implemented.** They arrive in a dedicated gate.

## Multi-tenancy

NINFA is multi-tenant from day one. The workspace is the tenant boundary:

```
USER → WORKSPACE MEMBERSHIP → PROPERTY ACCESS
```

A user may belong to several workspaces; a workspace owns one or more properties. Every future read
or write of business data must be scoped through this chain.

Implemented in Gate 1 (details in [data-model-v1.md](data-model-v1.md) and ADR 0006):

- **Database-level isolation of relationships.** Tenant-owned tables carry an explicit
  `workspace_id`, and composite foreign keys make it impossible for a row of workspace A to reference
  a row of workspace B, even through buggy code or manual SQL.
- **Explicit tenant scope in code.** `TenantContext(workspace_id)` is required to build any
  tenant-owned repository; every query filters on it and no method takes a workspace argument.
  There is no default and no "all tenants" mode.
- **Not yet implemented:** deciding who may act on which workspace. `TenantContext` is *not*
  authentication; the authentication/authorization gate will be the only place that creates it for a
  request. PostgreSQL row-level security is deliberately not enabled yet; the schema is ready for it.

## Booking ingestion (Gate 2)

`BookingImportService` turns a customer's CSV/XLSX export into canonical bookings without the
customer editing the file: a per-data-source **mapping** (confirmed once, remembered) tells which
columns feed which canonical fields; **only mapped columns** are ever read; rows are normalised
(time zones, `Decimal` money, statuses, channels), validated and **staged**; then written in **one
atomic transaction** or not at all; re-imports are **idempotent** (identity = data source +
`source_record_id`, change detection by fingerprint). Nothing is inferred: ambiguous dates and
numbers, unknown statuses and unclear sheets are reported and need a configuration. Details,
guarantees and error codes: [booking-data-v1.md](booking-data-v1.md), ADR 0008.

## Booking snapshots (Gate 3)

Two application services turn canonical bookings and the declared room inventory into daily
**"on the books"** snapshots, one row per data source × property-local day × stay night:
`ObservedSnapshotService` records what the bookings say *now* (`OBSERVED`, immutable evidence,
never overwritten) and `BookingSnapshotReconstructionService` infers what an earlier day probably
looked like (`RECONSTRUCTED_APPROXIMATE`, always approximate, uncertainty counted, never promoted,
never replacing an observation). The distinction is in the data (`origin`), the code (two code
paths) and the tests; the canonical booking table keeps only current state, so a reconstruction is
never historical truth. Revenue is allocated over the stay nights in exact cents; a missing
inventory is `NULL`, never a guess. Runs are one transaction under the same per-data-source
advisory lock as the import (`app/db/locks.py`). No API, worker task or scheduler was added.
Details: [booking-snapshots-v1.md](booking-snapshots-v1.md), ADR 0009.

## Expected Engine (Gate 4)

`BookingExpectedService` turns an OBSERVED snapshot into an immutable **Expected baseline**: the
median rooms on books of the historical comparables (same data source, **same lead time**, same
weekday, +-42 day season, at most 730 days back, strictly before the target: no temporal
leakage), with the historical P25-P75 range, the IQR, the sample provenance and a versioned
**baseline confidence** (0-100, with caps and bands). OBSERVED comparables come first; clean
reconstructions only complete a small observed sample and are penalised; a reconstruction with
uncertainty never enters the numbers. With fewer than 5 comparables the result is
`INSUFFICIENT_DATA` and **no number is produced**. **Expected is not a forecast**: it says how
much was typically on the books, not how a stay will end, and it computes no pickup, alert or
decision. Baselines and the comparables actually used are stored (immutable, fingerprinted,
tenant-checked by composite foreign keys); runs share the per-data-source advisory lock and use
one candidate query per batch. No API, worker task or scheduler was added. Details:
[expected-engine-v1.md](expected-engine-v1.md), ADR 0010.

## Revenue decision detection (Gate 5)

`RevenueDecisionService` evaluates two explicit detectors on an OBSERVED snapshot and its Gate 4
baseline: `REV_PICKUP_LOW` (the last 7 days brought fewer rooms than the same historical stay
dates did over the same 7 days) and `REV_OCCUPANCY_RISK` (rooms on the books plus the usual
remaining net pickup falls short of the usual final level). Both work on **curve pairs** (two
snapshots of the same historical stay date, the anchor being a stored Gate 4 comparable), with
median/P25/P75 statistics, a curve-pattern confidence and a final confidence that is the
**minimum** of the baseline's and the pattern's. The result is an immutable, fingerprinted
**evaluation** with one of five distinct statuses (`TRIGGERED`, `CLEAR`, `INSUFFICIENT_DATA`,
`NOT_APPLICABLE`, `SUPPRESSED_LOW_CONFIDENCE`), stable reason codes and typed facts; a
`revenue_gap_proxy` (rooms x a reference ADR) is a gross exposure proxy, never a loss. Nothing is
persisted (there is no Decision table yet), the service is read-only (no write, no lock, no clock)
and needs seven statements whatever the number of targets. No API, worker task, scheduler,
migration or dependency was added. Details: [revenue-decisions-v1.md](revenue-decisions-v1.md), ADR 0011.

## Cost ingestion (Gate 6)

`InvoiceImportService` turns a customer's purchase invoices into canonical **suppliers, invoices and
lines**: FatturaPA XML 1.2.x (one file may hold several documents; TD04/TD08 are credit notes) and
structured CSV/XLSX (a per-data-source **mapping** confirmed once, only mapped columns read, rows
grouped into invoices). The **Supplier Registry is workspace-wide**; the separate `SupplierResolver`
resolves each supplier by **VAT number, then tax code, then IBAN hash, then exact name**, hashes the
IBAN so **the raw IBAN is never stored**, and **never merges on a fuzzy match**: a similar name only
opens a `PENDING` possible-duplicate review. An invoice is identified by property, supplier, number,
date and kind (**not** by the data source), is **immutable** and carries **signed** amounts (a credit
note is negative); re-imports are idempotent and a changed document is `INVOICE_DOCUMENT_CONFLICT`.
Lines get a cost category by deterministic rules with a provenance confidence. Import is **atomic**:
parse, validate and stage, then one transaction or nothing. **PDF, OCR and signed .p7m are not
supported.** No cost baseline, cost per occupied room, anomaly, decision, API, worker task or
scheduler was added. Details: [cost-ingestion-v1.md](cost-ingestion-v1.md), ADR 0012.

## Cost CPOR anomaly detection (Gate 7)

`CostDecisionService` evaluates ONE explicit detector, `COST_CPOR_ANOMALY` (rules
`cost-cpor-anomaly-v1`): is the **cost per occupied room** of a cost category, in one currency, on a
concluded calendar month, materially above comparable history? CPOR = the signed net category cost of
the month (Gate 6 `line_total`, credit notes negative, attributed by invoice date:
`INVOICE_DATE_ATTRIBUTION`) divided by the month's **occupied room nights**, the sum of
`rooms_on_books` of the **lead-time-0** snapshots (Gate 3). That denominator is an **operating
proxy**, not a certified occupancy: **a missing snapshot is not zero rooms** (the month is
incomplete), an uncertain snapshot invalidates the month and reconstructed clean snapshots are
admitted with a lower provenance. `OTHER` is not actionable and a month whose classified cost is
below 70 % of the total is not judged. The expectation is the **median** of 5 to 12 comparable
months of the same category and **exact currency** (strictly earlier, at most 36 months back, at most
two months apart in the season, observed-first) with P25/P75/IQR by linear interpolation; the anomaly
needs **all four** conditions (above expected, at least 20 % above, at or above `P75 + 1.5 x IQR`,
gross gap of at least 100 currency units); the final confidence is the minimum of the baseline's and
the target month's quality, gate 55. The result is an immutable, fingerprinted evaluation with one of
five statuses and stable reason codes; the `cost_gap_proxy` is a gross proxy, never a loss or a
saving. Nothing is persisted (`CostPeriodMetric` is a value, not a table), no currency is ever
converted, and the service is read-only (no write, no lock, no clock, a fixed handful of statements).
No table, migration, API, worker task, scheduler or dependency was added. Details:
[cost-cpor-anomaly-v1.md](cost-cpor-anomaly-v1.md), ADR 0013.

## Background processing

The worker uses [Procrastinate](https://procrastinate.readthedocs.io/): jobs are rows in
PostgreSQL. No Redis or broker in V1. See ADR 0005. On Windows, psycopg's async API needs a
`SelectorEventLoop`; `worker/runtime.py` selects it explicitly via `asyncio.run(loop_factory=...)`.

## Not implemented yet (belongs to later gates)

Authentication/authorization and any tenant-facing API, file upload and object storage, the
asynchronous ingestion job, labor ingestion, PDF/OCR/signed invoices, supplier merge and review
resolution, the Property Profile, RevPAR, scheduling of snapshot, Expected, revenue and import
runs, other business models (labor, labor baselines), the rest of the Decision Engine (persisted
decisions, other detectors such as supplier price anomalies, priority, recommendation, pricing),
budgeting and accruals, currency conversion, decision memory, AI gateway / narrative / Ask NINFA, product UI,
notifications, payments, analytics, deployment.

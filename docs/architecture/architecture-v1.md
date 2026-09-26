# NINFA — Architecture v1 (Gates 0–13)

Scope: the technical foundation (Gate 0), the canonical multi-tenant data core (Gate 1), the
booking ingestion with the canonical booking model (Gate 2), the room inventory with the daily
booking snapshots (Gate 3), the first Expected baselines (Gate 4), the first two revenue
detectors (Gate 5), the supplier registry with the invoice ingestion (Gate 6), the first cost
detector, the cost per occupied room (Gate 7), the canonical labor model with its first staffing
detector (Gate 8), the fifth and last MVP detector, OTA distribution dependency (Gate 9), the
Priority Engine (Gate 10), which ranks whatever the five detectors already called TRIGGERED — it
decides nothing a detector did not already decide —, Decision Persistence, Lifecycle and Memory
(Gate 11), which turns a ranked, non-persistent signal into a persistent Decision identity with an
OPEN/RESOLVED lifecycle and an immutable observation history, the Decision API (Gate 12), the
first business-facing HTTP surface: four READ-ONLY endpoints over that memory, behind a
fail-closed authorization boundary, and Authentication & Session (Gate 13), which fills that
boundary in for real: first-party email+password login, Argon2id, an opaque server-side session
behind an `HttpOnly` cookie. Still no product feature beyond reading that memory: data goes
in, is stored correctly, is turned into daily "on the books" facts, into a historical "expected
level" and into typed revenue, cost, labor and distribution evaluations, purchase invoices become
canonical suppliers, invoices and lines, TRIGGERED evaluations become typed, ranked priority
candidates, those candidates become persistent Decisions with a lifecycle and a memory, and that
memory can now be read over HTTP by a real, authenticated, authorized workspace member; no
recommendation, write endpoint, signup, password reset, MFA, OAuth/SSO or UI exists yet.
Data model: [data-model-v1.md](data-model-v1.md). Bookings: [booking-data-v1.md](booking-data-v1.md).
Snapshots: [booking-snapshots-v1.md](booking-snapshots-v1.md). Expected:
[expected-engine-v1.md](expected-engine-v1.md). Revenue decisions:
[revenue-decisions-v1.md](revenue-decisions-v1.md). Costs (suppliers and invoices):
[cost-ingestion-v1.md](cost-ingestion-v1.md). Cost per occupied room:
[cost-cpor-anomaly-v1.md](cost-cpor-anomaly-v1.md). Labor ingestion:
[labor-ingestion-v1.md](labor-ingestion-v1.md). Labor overstaffing:
[labor-overstaffing-v1.md](labor-overstaffing-v1.md). OTA dependency:
[ota-dependency-v1.md](ota-dependency-v1.md). Priority Engine:
[priority-engine-v1.md](priority-engine-v1.md). Decision Layer:
[decision-layer-v1.md](decision-layer-v1.md). Decision API:
[decision-api-v1.md](decision-api-v1.md). Authentication & Session:
[auth-session-v1.md](auth-session-v1.md).

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
| `services/api`      | HTTP API under `/api/v1/` (health, and since Gate 12 the read-only Decision API), config, logging, error model, the tenant-scoped data core, the booking and invoice import services, the snapshot and Expected services. |
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
- Fifteen modules exist: `identity` (User), `tenancy` (Workspace, WorkspaceMembership),
  `properties` (Property), `ingestion` (DataSource, ImportJob, ImportFile) since Gate 1, `bookings`
  since Gate 2, `snapshots` (RoomInventoryDaily, BookingSnapshot) since Gate 3,
  `intelligence/expected` (BookingExpectedBaseline, BookingExpectedComparable) since Gate 4 (the
  first of the Decision Engine stages), `intelligence/revenue` since Gate 5, `intelligence/costs`
  since Gate 7 (no model in either: their detectors and typed evaluations), `suppliers` (Supplier,
  SupplierIdentifier, SupplierAlias, SupplierResolutionReview),
  `invoices` (Invoice, InvoiceLine, InvoiceMappingProfile, InvoiceImportRow) since Gate 6,
  `labor` (LaborSnapshot, LaborEntry, LaborMappingProfile, LaborImportRow) with
  `intelligence/labor` and `intelligence/demand` (no model in either: the demand-forecast
  primitive shared with `intelligence/revenue`, and the LABOR_OVERSTAFFING detector) since Gate 8,
  `intelligence/distribution` since Gate 9 (no model: the REV_OTA_DEPENDENCY detector reads
  Gate 2's `BookingChannel`/`Booking` and Gate 3's `BookingSnapshot` directly and writes none of
  them), `intelligence/priority` since Gate 10 (no model: it reads the four detector modules'
  own evaluation types and writes nothing), `decisions` (DecisionRun, Decision,
  DecisionObservation) with `decision_memory` (no model: an internal read side over `decisions`'
  own repository) since Gate 11, and `auth` (UserCredential, AuthSession) since Gate 13 - kept
  separate from `identity` (User): a User's identity and its authenticator(s) are two different
  lifecycles, and `identity` is imported by nearly every other module while `auth` should not
  need to be. Importing `app.models` registers every model.
- Application services (`bookings/service.py`, `snapshots/observed.py`,
  `snapshots/reconstruction.py`, `intelligence/expected/service.py`,
  `intelligence/revenue/service.py`, `invoices/service.py`, `suppliers/resolution.py`,
  `labor/service.py`, `intelligence/demand/service.py`, `intelligence/labor/service.py`,
  `intelligence/distribution/service.py`, `decisions/service.py`, `decision_memory/service.py`,
  `auth/service.py`)
  are plain classes: they depend on a `Session` and a
  `TenantContext`, never on FastAPI (a test enforces it), so a future worker or authenticated
  endpoint can call them as they are. Framework-free exceptions live in `app/core/exceptions.py`.
  `intelligence/priority/service.py` is a step further still: `PriorityService` depends on
  **neither** a `Session` nor a `TenantContext` — it is a pure function of already-computed
  evaluations, so it can be tested with no database at all. `decisions/service.py` is, since Gate
  11, the first WRITE-capable service outside ingestion/canonicalisation: `DecisionService.sync()`
  owns its own transaction (validate, lock, load, apply the lifecycle, insert, commit/rollback as
  one unit), the same posture `LaborImportService`/`InvoiceImportService` already established.
  `auth/service.py`'s `AuthService` is the ONE exception to "depends on a `TenantContext`" - a
  `User`/credential/session is never tenant-scoped (a `User` can belong to several workspaces),
  so it depends only on a `Session` and an injectable clock (`app.core.clock.Clock`).
- The directories for the still-future domains (`normalization`,
  `data_quality`, `intelligence/{detection,impact,recommendation}`, `ai/*`) are empty package
  markers so the structure is settled before those domains land. `intelligence/priority` and
  `decisions`/`decision_memory` are no longer among them: Gate 10 and Gate 11 filled them in.
- Splitting a module into a service is a possible future step, never a starting point.

## API conventions

- Versioned prefix `/api/v1/`. Health: `GET /api/v1/health` → `{status, service, version}`.
- **Since Gate 12, the read-only Decision API** (`/api/v1/properties/{property_id}/decision-feed`,
  `/decisions`, `/decisions/{decision_id}`, `/decisions/{decision_id}/history` - see
  [decision-api-v1.md](decision-api-v1.md)). Every one is `GET`-only, behind the authorization
  boundary below - no CRUD, no faked tenant header. `app/api/v1/decisions/` holds this gate's own
  `router.py`, `deps.py` (tenant resolution), `schemas.py` (response DTOs), `serializers.py` (ORM
  row -> DTO, whitelisted) and `cursor.py` (opaque keyset pagination).
- **Since Gate 13, real authentication:** `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`,
  `GET /api/v1/auth/session` (see [auth-session-v1.md](auth-session-v1.md)). `app/api/v1/auth/`
  mirrors the same `router.py`/`schemas.py`/`deps.py` layering; `app/core/auth.py` holds the
  cookie contract (`SESSION_COOKIE_NAME`, `set_session_cookie`/`clear_session_cookie`) and the
  now-real `get_current_principal` every other authenticated route (Decision API included)
  depends on, unchanged since Gate 12.
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
- **Since Gate 13, `app.core.auth.get_current_principal` is a real, first-party resolver**: an
  `HttpOnly`, `SameSite=Lax` session cookie (`ninfa_session`) -> `SHA-256` -> an `AuthSession` row
  -> a `User`. No JWT, no OAuth/OIDC yet - see [auth-session-v1.md](auth-session-v1.md), ADR 0019.
  `Settings.session_cookie_secure` defaults to `True` (HTTPS-only) and production REFUSES to start
  with it `False`. Authorization (which workspace/property an authenticated caller may reach) is
  unchanged since Gate 12, V1-scoped: active `WorkspaceMembership` → every property of that
  workspace (see [decision-api-v1.md](decision-api-v1.md), "Authorization boundary").

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

## Labor ingestion and overstaffing detection (Gate 8)

`LaborImportService` turns structured CSV/XLSX labor exports (planned/actual minutes by category,
no employee identity anywhere) into an immutable `LaborSnapshot`/`LaborEntry` pair, the Gate 6
pipeline shape and the Gate 6 deterministic-classification pattern, reused rather than duplicated.
Hours are stored as exact integer **minutes**, never a float, and a fractional minute is rejected,
never rounded. `LaborDecisionService` evaluates ONE explicit detector, `LABOR_OVERSTAFFING` (rules
`labor-overstaffing-v1`): for the room demand a target day is actually expected to see, are a
category's **scheduled hours** materially above what comparable demand days historically needed?
The demand forecast is `REV_OCCUPANCY_RISK`'s own formula and pairing (Gate 5), extracted into
`intelligence.demand` and reused unchanged, never rebuilt. A comparable day needs the same
weekday, a seasonal distance of at most 42 days (the Gate 4 algorithm, reused), a clean
lead-time-0 occupancy within tolerance of the target's forecast, and a complete **ACTUAL-FIRST**
labor basis; the expectation is the median of the comparables' TOTAL hours (never a per-room
ratio); the anomaly needs **all four** conditions (above expected, at least 20% above, at least
4 hours above, at or above `P75 + 1.5 x IQR`); the final confidence is the minimum of the
baseline's, the demand forecast's and the target day's quality, gate 55. An optional
`labor_cost_gap_proxy` is a gross exposure figure, never a saving, and never part of the trigger.
The result is an immutable, fingerprinted evaluation with one of five statuses and stable reason
codes, judging an AGGREGATE level of hours, never a person. Nothing beyond the four canonical
labor tables is persisted, no worker task, scheduler, API or dependency was added. Details:
[labor-ingestion-v1.md](labor-ingestion-v1.md), [labor-overstaffing-v1.md](labor-overstaffing-v1.md), ADR 0014.

## OTA dependency detection (Gate 9)

`OtaDependencyService` evaluates the fifth and last MVP detector, `REV_OTA_DEPENDENCY` (rules
`ota-dependency-v1`): of a property's *next 30 days* of room-night business, how much is already
concentrated on OTA channels, and is that concentration structurally high or rising sharply above
comparable history? It classifies every `BookingChannel` of the property in memory (Gate 2's own
`channel_type`/`is_verified` when verified, else a small exact dictionary, else `UNKNOWN`; never a
write, never a fuzzy match), reconstructs the certain channel mix of the target's 30-night window
**as of** the given date by reusing Gate 3's own temporal certainty rule (made public, unmodified),
and reconciles it day by day against the already-stored `BookingSnapshot`. Historical comparable
30-day periods follow the same weekday/season/horizon rule as Gate 4 (reused, not duplicated) and
the same observed-first sampling as Gates 4/5/7/8. The trigger is STRUCTURAL (actual OTA share
>= 70%, independent of history) OR RISING (>= 55%, at least 15 points above the historical median,
at or above the robust upper fence); the final confidence is the minimum of the baseline's and the
target window's own quality, gate 55. An optional gross OTA revenue **exposure** (never a
commission saving) may be exposed when it resolves cleanly. The result is an immutable,
fingerprinted evaluation measuring CONCENTRATION of the distribution mix, never channel
PERFORMANCE (no conversion, CAC, ROAS, cancellation rate or rate-parity anywhere in it). Nothing is
persisted, no table, migration, API, worker task or dependency was added. Details:
[ota-dependency-v1.md](ota-dependency-v1.md), ADR 0015.

## Priority Engine (Gate 10)

`PriorityService.rank(context, evaluations)` turns whatever the five MVP detectors already called
`TRIGGERED` into a deterministically ranked list of `PriorityCandidate`s: it never re-decides
whether a detector is right, never touches a detector's own threshold, confidence or fingerprint,
and never queries a repository, a detector or the database (it takes no `Session` and no
`TenantContext` at all — a pure function of already-computed evaluations). Every other status
(`CLEAR`, `INSUFFICIENT_DATA`, `NOT_APPLICABLE`, `SUPPRESSED_LOW_CONFIDENCE`) is excluded and
counted, never scored. Five explicit adapters (one per detector, no generic rules framework)
normalize each TRIGGERED signal into an Impact Score (0-100 NORMALIZED OPERATIONAL SEVERITY, never
a currency amount), an Urgency Score (detector-aware: forward-dated, OTA's fixed structural/rising
policy, or cost's retrospective bands), the detector's OWN confidence reused exactly, and a fixed
V1 Actionability policy; `priority_score = 0.40 x impact + 0.25 x urgency + 0.20 x confidence +
0.15 x actionability`, computed and ranked on the full-precision `Decimal` value, never the
two-decimal display one. The ranking is deterministic (an 8-key tie-break, unique ranks, input
order irrelevant) and fingerprinted (both per candidate and for the whole result), duplicates are
deduplicated and logically conflicting evaluations are rejected, and economic proxies
(`revenue_gap_proxy`, `cost_gap_proxy_exact`, `labor_cost_gap_proxy_exact`, an optional OTA
revenue exposure) travel through as evidence only, in their own currency, never scored and never
compared across currencies. No table, migration, API endpoint, worker task or dependency was
added by this gate itself (Gate 11 later adds `0009_decision_layer`, unrelated to the ranking
formula). Details: [priority-engine-v1.md](priority-engine-v1.md), ADR 0016.

## Decision Persistence, Lifecycle and Memory (Gate 11)

`DecisionService.sync(context, ranking_result, evaluations)` turns a `PriorityContext`/
`PriorityRankingResult`/source-evaluations triple (Gate 10's own output, unmodified) into
persistent `Decision`s: a cross-day identity (`decision-identity-v1`, deliberately NOT Gate 10's
own `source_target_key`, which carries a snapshot id or a rolling window that changes every
morning), an `OPEN`/`RESOLVED` lifecycle (eight explicit rules; only an explicit `CLEAR` resolves —
never absence, `INSUFFICIENT_DATA`, `SUPPRESSED_LOW_CONFIDENCE` or `NOT_APPLICABLE`; a later
`TRIGGERED` reopens the SAME Decision id), and an immutable `DecisionObservation` history (one row
per Decision per `DecisionRun`, carrying the exact Priority snapshot of that day when TRIGGERED,
explicit per-detector facts/evidence payloads, never a blind serialization of the whole
evaluation). A `DecisionRun` is append-only and makes an exact replay of the same
workspace/property/as-of/logical input idempotent (zero new rows) while allowing the same as-of
date with a genuinely different dataset to become a new run. `DecisionService.sync()` is the first
WRITE-capable service outside ingestion: it owns its transaction (validate, advisory-lock, load
existing Decisions set-based, apply the lifecycle, insert, commit or roll back as one atomic
unit) and protects concurrent syncs of the same workspace/property with the same
`pg_advisory_xact_lock` pattern `lock_data_source`/`lock_supplier_registry` already use.
`DecisionMemoryService` is the internal read side (`list_open_decisions`, `get_decision`,
`get_history`, `find_by_identity`): no business API, no UI. One migration,
`0009_decision_layer` (three tables: `decision_runs`, `decisions`, `decision_observations`); no new
dependency. Details: [decision-layer-v1.md](decision-layer-v1.md), ADR 0017.

## Decision API (Gate 12)

Four `GET` endpoints over Gate 11's own Decision Memory, and NOTHING else: `decision-feed`
(the latest run's TRIGGERED items for one property/as-of, typed `NOT_PROCESSED` /
`ACTION_REQUIRED` / `DATA_QUALITY_LIMITED` / `NO_ACTION_REQUIRED`), `decisions` (cursor-paginated
lifecycle list), `decisions/{id}` (detail) and `decisions/{id}/history` (newest-first). An
`AuthenticatedPrincipal` dependency (`app.core.auth.get_current_principal`, fail-closed in Gate 12,
genuinely resolvable since Gate 13) and a server-side tenant-derivation dependency
(`resolve_property_scope`: `property_id` path → its workspace → `WorkspaceMembership` check →
`TenantContext` - never a client-supplied workspace id or header) guard every route. No write
endpoint, no `DecisionService.sync()` over HTTP, no `PriorityService`/detector call from a
request, no `identity_payload` passthrough (four explicit `target` DTOs instead), every exact
`Decimal` as a canonical string. Zero migration, zero new dependency. Details:
[decision-api-v1.md](decision-api-v1.md), ADR 0018.

## Authentication & Session (Gate 13)

Fills in Gate 12's own fail-closed seam for real: `POST /auth/login` (email + password, Argon2id
via `argon2-cffi`, generic `INVALID_CREDENTIALS` on any failure, 5-failures/15-minute lockout per
credential), `POST /auth/logout` (revokes the session the cookie names, always clears the cookie,
`204`), `GET /auth/session` (the same `SessionContextResponse` a successful login returns: user,
session expiry, every accessible workspace and its properties - Gate 12's own membership policy,
reused). Two new tables, both keyed off the global `User`, neither tenant-scoped:
`user_credentials` (one Argon2id hash per user, a failure counter and lock timestamp) and
`auth_sessions` (append-mostly: a `SHA-256` token hash, an absolute 7-day `expires_at` that never
slides, a `revoked_at` set once by logout or by a password rotation - never the raw token itself).
`app.core.auth.get_current_principal` - the SAME function Gate 12's Decision API already depends
on, unmodified - now resolves a real `HttpOnly`/`SameSite=Lax` cookie through that path instead of
always failing. Credential provisioning is CLI-only (`python -m app.cli.auth set-password`,
`getpass`-read, 14-128 characters, no public signup/reset endpoint). One migration
(`0010_auth_session`), one new dependency (`argon2-cffi`). Details:
[auth-session-v1.md](auth-session-v1.md), ADR 0019.

## Background processing

The worker uses [Procrastinate](https://procrastinate.readthedocs.io/): jobs are rows in
PostgreSQL. No Redis or broker in V1. See ADR 0005. On Windows, psycopg's async API needs a
`SelectorEventLoop`; `worker/runtime.py` selects it explicitly via `asyncio.run(loop_factory=...)`.

## Not implemented yet (belongs to later gates)

Public signup, password reset/forgot-password, email verification, MFA, passkeys, OAuth/SSO, a
service/machine-to-machine token system, per-IP/perimeter rate limiting, a session-cleanup
maintenance job, a CSRF policy (needed before the first business-mutating endpoint, not before), a
`PropertyAccess` primitive finer than workspace membership, file upload and object storage, the
asynchronous ingestion job, PDF/OCR/signed invoices, an HR system, payroll, shift scheduling or a
workforce optimizer, a channel manager, a booking engine, commission accounting, channel
profitability/conversion/CAC/ROAS, rate parity, marketing attribution, supplier merge and review
resolution, the Property Profile, RevPAR, scheduling of snapshot, Expected, revenue, cost, labor,
distribution, priority-ranking and Decision Layer sync runs, persisted labor, cost or distribution
baselines (all are non-persistent values, recomputed on demand), a customer-facing
channel-classification setup workflow (Gate 9's classifier stays entirely in-memory and
read-only), a sixth detector (e.g. supplier price anomalies), a Decision resolution policy beyond
explicit CLEAR, backtesting/replaying historical as-of dates, any Decision WRITE endpoint
(acknowledge/dismiss/snooze/assign/resolve/reopen), a Decision recommendation, pricing or a UI,
budgeting and accruals, currency conversion, AI gateway / narrative / Ask NINFA, notifications,
payments, analytics, deployment.

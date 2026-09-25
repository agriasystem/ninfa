# Local development

Validated on Windows 11 with Node 24, npm 11, uv 0.11, Python 3.13 (managed by uv) and a native
PostgreSQL 18. Commands run from the repository root.

## Prerequisites

| Tool        | Version | Notes                                                             |
| ----------- | ------- | ----------------------------------------------------------------- |
| Node.js     | ≥ 24    | npm workspaces (no pnpm/yarn)                                     |
| uv          | recent  | installs and pins Python 3.13 (`.python-version`)                 |
| PostgreSQL  | 18      | native service **or** Docker (see below)                          |
| `psql`      | 18      | only to run the one-off database bootstrap                        |

Python 3.13 is required by the project (`requires-python = ">=3.13,<3.14"`); uv downloads it if
it is missing. A newer system Python is not used.

## Setup

```bash
npm run setup            # npm install + uv sync --all-packages
cp .env.example .env     # PowerShell: Copy-Item .env.example .env
```

Edit `.env`: set a strong random password in `DATABASE_URL` and `TEST_DATABASE_URL` (same
password for both), e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
`.env` is gitignored and must never be committed.

### PostgreSQL

The application uses a dedicated role, `ninfa_app` (no superuser rights), which owns the
`ninfa_dev` and `ninfa_test` databases.

**Native PostgreSQL** (validated). Once, as a PostgreSQL superuser (`psql` asks for its password):

```powershell
$pw = (Select-String -Path .env -Pattern '^DATABASE_URL=.*//ninfa_app:([^@]+)@').Matches[0].Groups[1].Value
psql -h 127.0.0.1 -U postgres -v app_password=$pw -f scripts/db/bootstrap-local.sql
```

The script is idempotent. Other shells: pass the same password via `-v app_password='...'`.

**Docker** (portable alternative, **not run on the Gate 0 machine** because Docker is not
installed there — treat as untested until first use). Set `POSTGRES_PASSWORD` and
`NINFA_APP_PASSWORD` (equal to the password in `DATABASE_URL`) in `.env`, then:

```bash
docker compose up -d postgres     # listens on host port 5433
```

and point `DATABASE_URL` / `TEST_DATABASE_URL` at port `5433`.

### Migrations

```bash
npm run db:migrate       # alembic upgrade head on DATABASE_URL
npm run db:current       # show the applied revision
```

New revision: `uv run --all-packages alembic -c services/api/alembic.ini revision -m "message"`.
Revisions: `0001` baseline, `0002` Procrastinate job-queue schema (vendored SQL, see ADR 0005),
`0003` canonical data model and tenant core (see [data-model-v1.md](../architecture/data-model-v1.md)),
`0004` booking ingestion (see [booking-data-v1.md](../architecture/booking-data-v1.md)).
Rolling back Gate 2 only: `uv run --all-packages alembic -c services/api/alembic.ini downgrade 0003_canonical_data_model`;
Gates 1 and 2: `... downgrade 0002_procrastinate_schema`.

## Run

| What     | Command              | Default address / notes                       |
| -------- | -------------------- | --------------------------------------------- |
| API      | `npm run dev:api`    | `http://127.0.0.1:8000/api/v1/health`         |
| Worker   | `npm run dev:worker` | Ctrl+C to stop                                |
| Web      | `npm run dev:web`    | `http://127.0.0.1:3100`                       |

Ports and hosts are configurable through `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` (the web
port defaults to 3100 because 3000 is often taken). The web app reaches the API at
`NEXT_PUBLIC_API_BASE_URL`; that origin must be listed in `CORS_ORIGINS`.

Worker smoke test (proves queue, worker and database work together):

```bash
uv run --all-packages python -m worker heartbeat      # enqueue the smoke job
uv run --all-packages python -m worker run --once     # run queued jobs, then exit
```

## Booking import (Gate 2)

There is no public API for it yet (no authentication): the import is a Python service. Try it in a
Python shell (`uv run --all-packages python`) against your development database, with a workspace,
a property and a `BOOKINGS` / `FILE_UPLOAD` data source already created:

```python
from app.core.tenant import TenantContext
from app.db.session import get_sessionmaker
from app.modules.bookings.service import BookingImportService

with get_sessionmaker()() as session:
    service = BookingImportService(session, TenantContext(workspace_id))
    content = open("export.csv", "rb").read()
    suggestion = service.suggest_mapping(data_source_id, filename="export.csv", content=content)
    # show suggestion.suggestions to the customer; they confirm the mapping and the formats
    service.save_mapping(data_source_id, headers=suggestion.headers,
                         column_mapping={"source_record_id": {"column": "ID Prenotazione"}, ...},
                         format_options={"decimal_separator": ",", "thousands_separator": "."})
    result = service.import_file(data_source_id, filename="export.csv", content=content)
    print(result.status, result.error_code, result.bookings_created)
```

Supported files: `.csv` (UTF-8, Windows-1252; comma, semicolon or tab) and `.xlsx`. Synthetic
fixtures for tests live in `tests/fixtures/bookings/` (see its README); `openpyxl` (the only
dependency added by Gate 2) reads the workbooks. The database tests need the test database, as
for every backend test.

## Booking snapshots (Gate 3)

Also a Python service, with no public API, worker task or scheduler yet. With an imported
`BOOKINGS` source (see above), optionally declare the room capacity, then observe:

```python
from datetime import date

from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import BookingSnapshotRepository, RoomInventoryRepository

tenant = TenantContext(workspace_id)
with get_sessionmaker()() as session:
    RoomInventoryRepository(session, tenant).set_for_date(
        property_id, date(2026, 7, 1), rooms_available=12
    )
    session.commit()

with get_sessionmaker()() as session:  # a session with no uncommitted work
    observed = ObservedSnapshotService(session, tenant).take_snapshot(
        property_id=property_id, data_source_id=data_source_id,
        stay_date_start=date(2026, 7, 1), stay_date_end=date(2026, 7, 31))
    print(observed.created, observed.unchanged)  # a different content -> BOOKING_SNAPSHOT_CONFLICT

with get_sessionmaker()() as session:
    curve = BookingSnapshotRepository(session, tenant).list_curve_for_stay_date(
        data_source_id, date(2026, 7, 14))
```

`BookingSnapshotReconstructionService(...).reconstruct(...)` infers **completed earlier days**; its
rows are `RECONSTRUCTED_APPROXIMATE` and never replace an observation (read
[booking-snapshots-v1.md](../architecture/booking-snapshots-v1.md) before using them). Observing is
meant to run once per property-local day; running it again the same day is a no-op unless the
bookings or the inventory changed, which raises `BOOKING_SNAPSHOT_CONFLICT`. Migration `0005` adds
the two tables; `npm run db:migrate` applies it. The golden scenario lives in
`tests/fixtures/snapshots/`; its expected file is regenerated, independently of the application, with
`uv run --all-packages python tests/fixtures/snapshots/generate_masseria_snapshots_expected.py`.
Gate 3 adds no dependency.

## Expected baselines (Gate 4)

Also a Python service, with no public API, worker task or scheduler yet. It needs OBSERVED snapshots
(see above) and, to get more than `INSUFFICIENT_DATA`, history: at least 5 comparable snapshots at the
same lead time, weekday and season (observed, or clean reconstructions).

```python
from datetime import date

from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.expected.service import BookingExpectedService

with get_sessionmaker()() as session:  # a session with no uncommitted work
    service = BookingExpectedService(session, tenant)
    # every OBSERVED snapshot of one snapshot day and stay range, in one transaction
    result = service.calculate_for_snapshot_date(
        property_id=property_id, data_source_id=data_source_id,
        snapshot_local_date=date(2026, 8, 1),
        stay_date_start=date(2026, 8, 1), stay_date_end=date(2026, 9, 30))
    print(result.created, result.unchanged, result.ready, result.insufficient)

with get_sessionmaker()() as session:
    repository = ExpectedRepository(session, tenant)
    for baseline in repository.list_for_snapshot_date(data_source_id, date(2026, 8, 1)):
        print(baseline.target_stay_date, baseline.status, baseline.expected_rooms_on_books,
              baseline.confidence_band)
        comparables = repository.list_comparables(baseline.id)  # why NINFA expected it
```

`calculate_for_target(property_id=, data_source_id=, target_snapshot_id=)` does the same for one
snapshot. Run it right after the day's observation: a baseline is immutable, so re-running a target
whose history changed meanwhile raises `EXPECTED_BASELINE_CONFLICT` (a corrected history needs a new
`calculation_version`). Migration `0006` adds the two tables (and one unique key to
`booking_snapshots`); `npm run db:migrate` applies it. The golden scenario lives in
`tests/fixtures/expected/`; its history file and expected result are regenerated, independently of the
application, with `uv run --all-packages python
tests/fixtures/expected/generate_masseria_expected_expected.py`. Gate 4 adds no dependency.

## Revenue decisions (Gate 5)

A read-only Python service, with no public API, worker task, scheduler, migration or new
dependency. It needs an OBSERVED snapshot **and** its Expected baseline (see above), and history
with the pairs of the same stay dates: without them the answer is `INSUFFICIENT_DATA`, never an
invented number. It writes nothing and stores no decision; call it as often as you like.

```python
from datetime import date

from app.modules.intelligence.revenue.service import RevenueDecisionService

with get_sessionmaker()() as session:  # any session: the service never commits or rolls back
    service = RevenueDecisionService(session, tenant)
    signals = service.evaluate_revenue_signals(target_snapshot_id)  # one OBSERVED target
    print(signals.pickup_low.status, signals.pickup_low.reason_codes)
    print(signals.occupancy_risk.status, signals.occupancy_risk.revenue_gap_proxy)

    # every OBSERVED target of one snapshot day and stay range, seven statements in total
    for signals in service.evaluate_snapshot_date(
        property_id=property_id, data_source_id=data_source_id,
        snapshot_local_date=date(2026, 8, 1),
        stay_date_start=date(2026, 8, 1), stay_date_end=date(2026, 9, 30),
    ):
        evaluation = signals.pickup_low
        print(evaluation.stay_date, evaluation.status.value, evaluation.confidence_score)
```

`evaluate_pickup_low` and `evaluate_occupancy_risk` run one detector. An evaluation has one of five
statuses (`TRIGGERED`, `CLEAR`, `INSUFFICIENT_DATA`, `NOT_APPLICABLE`, `SUPPRESSED_LOW_CONFIDENCE`),
stable `reason_codes` and typed `facts`; `revenue_gap_proxy` is rooms x a reference ADR, a gross
exposure proxy and **not** a loss. Run the Expected service first for the day's targets. The
golden scenario lives in `tests/fixtures/revenue/`; its bookings and expected result are
regenerated, independently of the application, with `uv run --all-packages python
tests/fixtures/revenue/generate_masseria_revenue_expected.py`. Gate 5 adds no dependency.

## Invoice import (Gate 6)

A Python service, with no public API, worker task, scheduler or new dependency: it is called with a
tenant, a COSTS data source and the file bytes. **Supported: FatturaPA XML 1.2.x, structured CSV and
structured XLSX. Not supported: PDF, scans (OCR) and signed `.p7m`** (refused with
`INVOICE_UNSUPPORTED_FILE_TYPE`). Full guide: [cost-ingestion-v1.md](../architecture/cost-ingestion-v1.md).

```python
from app.core.tenant import TenantContext
from app.modules.invoices.service import InvoiceImportService

with get_sessionmaker()() as session:  # the service commits, and rolls back on failure
    service = InvoiceImportService(session, TenantContext(workspace_id))

    # FatturaPA XML: no mapping needed
    result = service.import_file(costs_source_id, filename="fattura.xml", content=xml_bytes)

    # a structured file: describe it, confirm the mapping once, then import
    described = service.describe_file(costs_source_id, filename="costi.csv", content=csv_bytes)
    service.save_mapping(
        costs_source_id,
        headers=described.headers,
        column_mapping={
            "supplier_name": {"column": "Fornitore"},
            "invoice_number": {"column": "Numero"},
            "invoice_date": {"column": "Data"},
            "line_description": {"column": "Descrizione"},
            "line_total": {"column": "Importo"},
        },
        format_options={
            "date_formats": {"invoice_date": "%d/%m/%Y"},
            "decimal_separator": ",",
            "thousands_separator": ".",
        },
    )
    result = service.import_file(costs_source_id, filename="costi.csv", content=csv_bytes)

    print(result.status, result.error_code, result.invoices_created, result.suppliers_created)
```

Branch on `result.error_code` (for example `INVOICE_VALIDATION_FAILED`,
`INVOICE_DOCUMENT_CONFLICT`, `SUPPLIER_IDENTITY_CONFLICT`), never on the message; the staged rows
(`invoice_import_rows`) say which field of which line failed. Any problem creates **nothing** but the
staging and a `FAILED` job; re-running a fixed file is safe and importing the same file twice creates
nothing new. Suppliers are created by the import itself and are workspace-wide; a possible duplicate
appears as a `PENDING` row in `supplier_resolution_reviews` (there is no merge yet).

The golden scenario ("MASSERIA NINFA DEMO — COST DATA V1") and the synthetic fixtures live in
`tests/fixtures/invoices/`; they are (re)written, together with the independently computed expected
result, by `python tests/fixtures/invoices/generate_cost_fixtures.py` (standard library only). Gate 6
adds no dependency (`openpyxl` has been there since Gate 2) and one migration,
`0007_invoice_supplier_ingestion` (`npm run db:migrate`).

## Cost CPOR anomaly (Gate 7)

A read-only Python service, with no public API, worker task, scheduler, migration or new dependency.
It needs the canonical invoices of Gate 6 **and** lead-time-0 booking snapshots of a BOOKINGS data
source (Gate 3): without either the answer is `INSUFFICIENT_DATA` or `NOT_APPLICABLE`, never an
invented number. The booking data source is always passed explicitly, the target month is always
passed in (the service reads no clock), and it writes nothing and stores no decision. Full guide:
[cost-cpor-anomaly-v1.md](../architecture/cost-cpor-anomaly-v1.md).

```python
from app.core.tenant import TenantContext
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.invoices.cost_categories import CostCategory

with get_sessionmaker()() as session:  # any session: the service never commits or rolls back
    service = CostDecisionService(session, TenantContext(workspace_id))

    metric = service.build_period_metric(
        property_id=property_id, booking_data_source_id=bookings_source_id,
        year=2026, month=8, cost_category=CostCategory.LAUNDRY, currency="EUR",
    )
    print(metric.status.value, metric.occupied_room_nights, metric.cpor_display)

    evaluation = service.evaluate_cpor_anomaly(
        property_id=property_id, booking_data_source_id=bookings_source_id,
        year=2026, month=8, cost_category=CostCategory.LAUNDRY, currency="EUR",
    )
    print(evaluation.status.value, evaluation.reason_codes, evaluation.cost_gap_proxy_display)

    # every operating category of one month and currency: the history is read once
    for evaluation in service.evaluate_month(
        property_id=property_id, booking_data_source_id=bookings_source_id,
        year=2026, month=8, currency="EUR",
    ):
        print(evaluation.cost_category.value, evaluation.status.value, evaluation.confidence_score)
```

An evaluation has one of five statuses (`TRIGGERED`, `CLEAR`, `INSUFFICIENT_DATA`,
`NOT_APPLICABLE`, `SUPPRESSED_LOW_CONFIDENCE`), stable `reason_codes` and typed facts; `cost_gap_proxy_exact`
(and its `_display` value) is a gross proxy and **not** a loss or a saving. Ask only for concluded calendar months, one currency
at a time (NINFA never converts currencies). The golden scenario lives in `tests/fixtures/costs/`;
its bookings, invoices and expected result are regenerated, independently of the application, with
`uv run --all-packages python tests/fixtures/costs/generate_masseria_cost_intelligence_expected.py`.
Gate 7 adds no dependency and no migration (the head stays `0007_invoice_supplier_ingestion`).

## Labor ingestion and overstaffing (Gate 8)

Adds no dependency and one migration, `0008_labor_ingestion` (`npm run db:migrate`, now head).
Import a structured labor file (a confirmed mapping profile is required first, via
`save_mapping()`), then evaluate one category on one target booking snapshot; the demand forecast
reuses Gate 5's own machinery, so no booking data source is passed to the detector explicitly — it
is derived from the target. Full guide: [labor-ingestion-v1.md](../architecture/labor-ingestion-v1.md),
[labor-overstaffing-v1.md](../architecture/labor-overstaffing-v1.md).

```python
from datetime import date

from app.core.tenant import TenantContext
from app.modules.labor.roles import LaborCategory
from app.modules.labor.service import LaborImportService
from app.modules.intelligence.labor.service import LaborDecisionService

with get_sessionmaker()() as session:
    import_service = LaborImportService(session, TenantContext(workspace_id))
    import_service.save_mapping(
        labor_data_source_id,
        headers=["work_date", "role", "planned_hours", "actual_hours"],
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
            "actual_hours": {"column": "actual_hours"},
        },
    )
    result = import_service.import_file(
        labor_data_source_id,
        filename="roster-week36.csv",
        content=csv_bytes,
        snapshot_local_date=date(2026, 9, 1),  # always explicit: no date.today()
    )
    print(result.status.value, result.labor_snapshot_id, result.entries_created)

    decision_service = LaborDecisionService(session, TenantContext(workspace_id))
    evaluation = decision_service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot_id,
        labor_data_source_id=labor_data_source_id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    print(evaluation.status.value, evaluation.reason_codes, evaluation.excess_hours_exact)
```

An evaluation has one of five statuses, stable `reason_codes` and typed facts;
`labor_cost_gap_proxy_exact` (optional) is a gross proxy and **never** a saving, and never part of
the trigger. Hours are stored as integer minutes; a fractional minute in the source is rejected,
never rounded. No employee name, id, email, phone, tax code, address or leave reason is ever
persisted (an unmapped column never reaches staging).

## OTA dependency (Gate 9)

Adds no dependency and no migration of its own (Gate 11 later adds `0009_decision_layer`, unrelated
to OTA dependency detection). Evaluate a property's next-30-day OTA dependency directly on its own
booking data: no separate import step, since it
reads the canonical `Booking`/`BookingChannel`/`BookingSnapshot` rows Gate 2/3 already produced.
`as_of_local_date` is always explicit. Full guide:
[ota-dependency-v1.md](../architecture/ota-dependency-v1.md).

```python
from datetime import date

from app.core.tenant import TenantContext
from app.modules.intelligence.distribution.service import OtaDependencyService

with get_sessionmaker()() as session:
    service = OtaDependencyService(session, TenantContext(workspace_id))
    evaluation = service.evaluate(
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        as_of_local_date=date(2026, 9, 5),  # always explicit: no date.today()
    )
    print(evaluation.status.value, evaluation.reason_codes, evaluation.ota_share_display)
```

An evaluation has one of five statuses, stable `reason_codes` and typed facts;
`ota_revenue_share_exact` (optional) is a gross exposure and **never** a saving, and never part of
the trigger. The channel classifier never writes to `BookingChannel`: it classifies every channel
of the property in memory, on every call, from `channel_type`/`is_verified` (when confirmed) or a
small exact dictionary, never a fuzzy match — an unmapped or ambiguous channel name stays
`UNKNOWN` rather than being guessed.

## Priority ranking (Gate 10)

Adds no dependency and no migration of its own (Gate 11 later adds `0009_decision_layer`, unrelated
to priority ranking). Rank whatever the five detectors above already called `TRIGGERED`:
`PriorityService` needs no database session and
no `TenantContext` at all — it is a pure function of the evaluations you already computed. Full
guide: [priority-engine-v1.md](../architecture/priority-engine-v1.md).

```python
from datetime import date

from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext

context = PriorityContext(
    workspace_id=workspace_id,
    property_id=property_id,
    as_of_local_date=date(2026, 9, 5),  # always explicit: no date.today()
)
# evaluations: any mix of RevenueDecisionEvaluation / OtaDependencyEvaluation /
# CostDecisionEvaluation / LaborDecisionEvaluation, of ANY status, already computed above.
result = PriorityService().rank(context, evaluations)
for ranked in result.ranked_candidates:  # every candidate, never truncated to a top N
    candidate = ranked.candidate
    print(ranked.rank, candidate.decision_type.value, candidate.priority_score_display)
print(result.candidate_count, result.excluded_suppressed_count)
```

Only `TRIGGERED` evaluations become a `PriorityCandidate`; every other status (including
`SUPPRESSED_LOW_CONFIDENCE`) is excluded and counted, never scored, never "resuscitated". Impact
is a 0-100 normalized severity, **never** euro or another currency; any economic proxy
(`revenue_gap_proxy`, `cost_gap_proxy_exact`, ...) rides along as evidence only and never affects
`priority_score_exact`. An empty `ranked_candidates` tuple is a legitimate result (nothing was
TRIGGERED), not an error.

## Decision persistence, lifecycle and memory (Gate 11)

Adds no dependency and one migration, `0009_decision_layer` (`npm run db:migrate`, now head).
Turns a `PriorityContext`/`PriorityRankingResult`/source-evaluations triple into persistent
`Decision`s with an OPEN/RESOLVED lifecycle and an immutable `DecisionObservation` history. Full
guide: [decision-layer-v1.md](../architecture/decision-layer-v1.md).

```python
from app.core.tenant import TenantContext
from app.modules.decisions.service import DecisionService
from app.modules.decision_memory.service import DecisionMemoryService

with get_sessionmaker()() as session:
    tenant = TenantContext(workspace_id)
    # context, ranking_result and evaluations: the SAME PriorityContext/PriorityRankingResult and
    # source evaluations you already built for PriorityService.rank() above.
    result = DecisionService(session, tenant).sync(context, ranking_result, evaluations)
    print(result.created_decision_count, result.observed_open_count, result.resolved_count)

    memory = DecisionMemoryService(session, tenant)
    for decision in memory.list_open_decisions(property_id):
        print(decision.decision_type.value, decision.status.value, decision.episode_count)
```

`sync()` never re-derives a detector's own status and never recomputes a Priority score: both are
read once and persisted exactly as they arrived. A Decision's identity is a CROSS-DAY concept
(never the source's own target key, which carries a snapshot id or a rolling window boundary that
changes every morning); only an explicit `CLEAR` resolves it, never absence, `INSUFFICIENT_DATA`,
`SUPPRESSED_LOW_CONFIDENCE` or `NOT_APPLICABLE`; a later `TRIGGERED` reopens the SAME Decision id.
An exact replay (same workspace/property/as-of/logical input) is idempotent: it returns the
existing `DecisionRun` and writes nothing new. There is no business API, UI, recommendation or AI
here: `DecisionMemoryService` is an internal read-side class, not an endpoint.

## Decision API (Gate 12)

Adds no dependency and no migration: a READ-ONLY HTTP layer over Gate 11's own Decision Memory.
Full guide: [decision-api-v1.md](../architecture/decision-api-v1.md), ADR 0018.

```
GET /api/v1/properties/{property_id}/decision-feed?as_of=YYYY-MM-DD
GET /api/v1/properties/{property_id}/decisions[?status=&decision_type=&limit=&cursor=]
GET /api/v1/properties/{property_id}/decisions/{decision_id}
GET /api/v1/properties/{property_id}/decisions/{decision_id}/history[?limit=&cursor=]
```

**There is still no real login system**, so every one of these answers `401
AUTHENTICATION_REQUIRED` when called directly (`curl`, `/docs`) in ANY environment, including
local development - `app.core.auth.get_current_principal`'s production body is unconditional on
purpose (see ADR 0018, "why auth is fail-closed"). This is expected, not a bug to work around
locally: there is nothing to configure that would make a bare `curl` succeed, because no
credential of any kind exists yet for it to present.

To exercise a route with a real, authorized caller - in a test, a one-off script, or a REPL -
override the dependency the same way `tests/conftest.py`'s own `authenticated_as` fixture does,
never with a header:

```python
from uuid import uuid4
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_session
from app.main import create_app

app = create_app()
app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(user_id=uuid4())
app.dependency_overrides[get_session] = lambda: session  # an open Session with a real
                                                          # WorkspaceMembership row for that user
```

`resolve_property_scope` still resolves the tenant from the real `Property`/`WorkspaceMembership`
rows in whatever session you provide - overriding the principal only answers "who is calling", not
"what may they reach". Every score/proxy is an exact-Decimal **string** in the JSON response, never
a float - see [decision-api-v1.md](../architecture/decision-api-v1.md), "Decimal, dates, UUIDs,
enums".

## Quality

| Goal            | Command                                                        |
| --------------- | -------------------------------------------------------------- |
| All tests       | `npm run test` (web: Vitest; backend: pytest)                  |
| Backend tests   | `npm run test:backend` (needs the test database)               |
| Lint            | `npm run lint` (ESLint; ruff)                                  |
| Typecheck       | `npm run typecheck` (tsc; mypy strict)                         |
| Frontend build  | `npm run build`                                                |
| Format (Python) | `uv run --all-packages ruff format services`                   |

Backend tests use `TEST_DATABASE_URL` and never touch the development database. They fail (not
skip) if it is not configured.

## Troubleshooting

- **`password authentication failed for user "ninfa_app"`** — the bootstrap was not run, or the
  password in `.env` differs from the one given to the script.
- **Port already in use** — change `API_PORT` / `WEB_PORT` in `.env`.
- **npm warns about `unrs-resolver` install scripts** — informational; the scripts are not needed
  and are intentionally not approved.
- **Worker on Windows** — no action needed: `worker/runtime.py` runs the loop with
  `SelectorEventLoop`, which psycopg's async API requires.

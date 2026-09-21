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

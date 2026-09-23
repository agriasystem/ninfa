# NINFA

Hospitality Decision Intelligence — B2B SaaS. Monorepo.

> **Status: Gate 9 (OTA Dependency Detection V1: `REV_OTA_DEPENDENCY`, rules
> `ota-dependency-v1`), the fifth and last MVP detector.** No product feature exists yet: the
> technical base, the multi-tenant data core, the import of booking files into canonical bookings,
> the daily snapshots derived from them (observed vs reconstructed), the Expected baselines (a
> historical level with its confidence, not a forecast), two revenue detectors that return typed,
> non-persisted evaluations, since Gate 6 a workspace-wide supplier registry with canonical
> invoices and lines (no PDF/OCR), since Gate 7 one cost detector (cost per occupied room, an
> operating proxy, one currency at a time, no stored decision, alert, priority or recommendation),
> since Gate 8 canonical labor entries (minutes, never an employee identity) with one staffing
> detector reusing Gate 5's own demand forecast, and since Gate 9 a read-only, in-memory channel
> classifier and a fifth detector measuring how concentrated a property's next 30 days of
> room-night business already is on OTA channels (never channel performance, never a commission
> model), on which the next gates are built.

## Layout

| Path                 | What                                                        |
| -------------------- | ----------------------------------------------------------- |
| `apps/web`           | Next.js (App Router, TypeScript strict) — technical shell   |
| `services/api`       | FastAPI modular monolith, SQLAlchemy 2, Alembic             |
| `services/worker`    | Background worker (Procrastinate on PostgreSQL)             |
| `packages/contracts` | Minimal shared TypeScript types (health, error envelope)    |
| `docs/`              | Architecture, ADRs, local development guide                 |

## Quick start

```bash
npm run setup                 # npm install + uv sync
cp .env.example .env          # then fill in real values (never commit .env)
npm run db:migrate            # after the database exists (see the local development guide)
npm run dev:api               # http://127.0.0.1:8000/api/v1/health
npm run dev:worker
npm run dev:web               # http://127.0.0.1:3100
```

Quality gates: `npm run test`, `npm run lint`, `npm run typecheck`, `npm run build`.

## Documentation

- [Local development](docs/development/local-development.md) — prerequisites, setup, all commands
- [Architecture v1](docs/architecture/architecture-v1.md) — responsibilities, principles, what is *not* built yet
- [Data model v1](docs/architecture/data-model-v1.md) — entities, tenant integrity, delete policy, indexes
- [Booking data v1](docs/architecture/booking-data-v1.md) — canonical booking, mapping memory, import pipeline, guarantees
- [Booking snapshots v1](docs/architecture/booking-snapshots-v1.md) — room inventory, observed vs reconstructed snapshots, on-books metrics
- [Expected engine v1](docs/architecture/expected-engine-v1.md) — historical comparable baselines, statistics, confidence, INSUFFICIENT_DATA
- [Revenue decisions v1](docs/architecture/revenue-decisions-v1.md) — REV_PICKUP_LOW and REV_OCCUPANCY_RISK: curve pairs, five statuses, confidence, revenue gap proxy
- [Cost ingestion v1](docs/architecture/cost-ingestion-v1.md) — supplier registry and resolution, FatturaPA XML and CSV/XLSX invoices, credit notes, categories, atomic import
- [Cost CPOR anomaly v1](docs/architecture/cost-cpor-anomaly-v1.md) — COST_CPOR_ANOMALY: cost per occupied room, lead-time-0 denominator, comparable months, median/IQR, confidence, cost gap proxy
- [Labor ingestion v1](docs/architecture/labor-ingestion-v1.md) — canonical labor snapshots/entries in minutes, no employee identity, mapping memory, atomic import
- [Labor overstaffing v1](docs/architecture/labor-overstaffing-v1.md) — LABOR_OVERSTAFFING: demand forecast reuse, ACTUAL-FIRST comparables, median/IQR, confidence, cost gap proxy
- [OTA dependency v1](docs/architecture/ota-dependency-v1.md) — REV_OTA_DEPENDENCY: 30-day forward window, conservative channel classification, temporal reuse, structural vs rising dependency, confidence
- [Architecture decision records](docs/architecture/adr/)

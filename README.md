# NINFA

Hospitality Decision Intelligence — B2B SaaS. Monorepo.

> **Status: Gate 12 (Decision API V1, `decision-api-v1`), a READ-ONLY HTTP surface over the
> Decision Layer, behind a fail-closed authorization boundary.** Still no product feature beyond
> that: the technical base, the multi-tenant data core, the import of booking files into canonical
> bookings, the daily snapshots derived from them (observed vs reconstructed), the Expected
> baselines (a historical level with its confidence, not a forecast), two revenue detectors that
> return typed evaluations, since Gate 6 a workspace-wide supplier registry with canonical invoices
> and lines (no PDF/OCR), since Gate 7 one cost detector (cost per occupied room, an operating
> proxy, one currency at a time), since Gate 8 canonical labor entries (minutes, never an employee
> identity) with one staffing detector reusing Gate 5's own demand forecast, since Gate 9 a
> read-only, in-memory channel classifier and a fifth detector measuring OTA concentration, since
> Gate 10 a pure, database-free engine that ranks every TRIGGERED signal deterministically, since
> Gate 11 a persistence layer that recognises the SAME operational problem across many days of
> observations (never a new Decision just because the as-of date, priority score or rank changed),
> resolves it only on an explicit CLEAR, reopens the same Decision id on a later TRIGGERED, and
> keeps every day's Observation immutable, and since Gate 12 four `GET` endpoints (feed, list,
> detail, history) that read exactly that memory - server-derived tenant scope, no spoofable
> header, cursor pagination, exact Decimal as a string, no priority recalculation, no detector
> execution, and still no recommendation, AI, write endpoint, notification or scheduler.

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
- [Priority Engine v1](docs/architecture/priority-engine-v1.md) — cross-domain ranking of TRIGGERED signals: normalized severity, detector-aware urgency, confidence reuse, fixed actionability, exact-Decimal scoring, deterministic tie-break
- [Decision Layer v1](docs/architecture/decision-layer-v1.md) — persistent Decision identity, cross-day deduplication, OPEN/RESOLVED lifecycle, explicit CLEAR resolution, reopening, immutable observation history, Decision Memory
- [Decision API v1](docs/architecture/decision-api-v1.md) — read-only feed/list/detail/history over the Decision Layer, fail-closed auth, server-derived tenant, cursor pagination, exact Decimal as string
- [Architecture decision records](docs/architecture/adr/)

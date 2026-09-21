# NINFA

Hospitality Decision Intelligence — B2B SaaS. Monorepo.

> **Status: Gate 6 (Invoice Ingestion & Supplier Resolution V1: FatturaPA XML and structured
> CSV/XLSX).** No product feature exists yet: the technical base, the multi-tenant data core, the
> import of booking files into canonical bookings, the daily snapshots derived from them (observed
> vs reconstructed), the Expected baselines (a historical level with its confidence, not a
> forecast), two revenue detectors that return typed, non-persisted evaluations and, since Gate 6,
> a workspace-wide supplier registry with canonical invoices and lines (no PDF/OCR, no cost
> indicator, no stored decision, alert, priority or recommendation), on which the next gates are
> built.

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
- [Architecture decision records](docs/architecture/adr/)

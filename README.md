# NINFA

Hospitality Decision Intelligence — B2B SaaS. Monorepo.

> **Status: Gate 0 (engineering foundations).** No product feature exists yet: only the technical
> base on which the next gates are built.

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
- [Architecture decision records](docs/architecture/adr/)

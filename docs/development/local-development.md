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
`0003` canonical data model and tenant core (see [data-model-v1.md](../architecture/data-model-v1.md)).
Rolling back Gate 1 only: `uv run --all-packages alembic -c services/api/alembic.ini downgrade 0002_procrastinate_schema`.

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

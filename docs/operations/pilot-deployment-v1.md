# Pilot deployment V1 (Gate 27B)

How AGRIA deploys and operates NINFA for the **first real hospitality pilot** (one hotel, a safe path
to a few). Provider-neutral: Linux + systemd + a reverse proxy are the *reference* artifacts, not a
requirement to use any particular cloud. Nothing in this repository deploys anything, provisions
infrastructure, configures a scheduler or holds a real secret.

Related: [smoke checklist](pilot-smoke-checklist-v1.md) ·
[backup and restore](pilot-backup-restore-v1.md) ·
[daily operations](pilot-daily-operations-v1.md) ·
[customer onboarding](pilot-onboarding-v1.md) ·
[pilot expectations](pilot-expectations-v1.md) ·
[deploy/](../../deploy/README.md) (env templates, systemd units, proxy example).

## 1. Topology (frozen)

```
Customer browser ── HTTPS ──►  reverse proxy  (ONE public origin, TLS mandatory)
                                  │  /api/*          ► FastAPI   127.0.0.1:8000 ──► Anthropic API
                                  │  everything else ► Next.js   127.0.0.1:3100
                                  ▼                                (FastAPI only)
                            Managed PostgreSQL  ◄── worker (python -m worker run, no public port)

External timezone-aware scheduler ──► scripts/run-daily-analysis.sh
```

- **One public origin**, for example `https://ninfa.example.com`. The proxy sends `/api/` to the API
  and everything else to the web app. The browser therefore talks to a single origin: no CORS, and
  the Gate 13 session cookie (HttpOnly, SameSite=Lax, host-only, Secure) keeps working unchanged.
  This package does not add a cookie `Domain`, does not rewrite cookies and does not weaken the
  `Secure` flag.
- `NEXT_PUBLIC_API_BASE_URL` = that absolute origin. `CORS_ORIGINS` stays **empty**.
- Customers use the web over HTTPS only. AGRIA operators use the internal CLI over SSH.

## 2. Host layout and accounts

Paths are **placeholders** (replace them consistently in the units and docs if you choose others):

| Path | What | Owner / mode |
|---|---|---|
| `/opt/ninfa/app` | repository checkout, `.venv`, built web app | deploy account, readable by `ninfa`, **not writable by `ninfa`** |
| `/etc/ninfa/api.env` | API / worker / CLI environment (**secrets**) | `ninfa:ninfa`, **0600** |
| `/etc/ninfa/web.env` | web environment (no secrets) | `ninfa:ninfa`, 0640 |
| `/var/lib/ninfa/incoming` | temporary hotel files for import | `ninfa:ninfa-ops`, **2770** (not world-readable) |

Accounts: `ninfa` (service account: no login shell, no password, no root); personal accounts for
each operator and developer, operators in the `ninfa-ops` group; the PostgreSQL owner/admin
credential is separate and held by an AGRIA administrator only. No shared SSH passwords: personal
SSH keys only. The service account must not be able to write the application directory, except
possibly Next.js's own cache directory under `apps/web/.next` if a future check shows it needs one.

Never place hotel files, env files or backups inside the repository checkout.

### Operator shell helpers

Operators run the CLIs **as the service account with the production environment** (never with
their own copy of the secrets). Add to the operator's shell profile:

```bash
export NINFA_APP=/opt/ninfa/app
ninfa-env() { sudo -u ninfa "$NINFA_APP/scripts/with-env.sh" /etc/ninfa/api.env "$@"; }
ninfa-py()  { ninfa-env "$NINFA_APP/.venv/bin/python" "$@"; }
```

All runbooks use `ninfa-py -m <module> …`. `scripts/with-env.sh` reads plain `KEY=VALUE` lines
without executing the file and never prints values.

## 3. Environment files and DEV vs PROD separation

Two **separate** files, from [deploy/env/](../../deploy/env/):

- `api.env` (from `api.env.example`): `APP_ENV=production`, `DEBUG=false`, `LOG_LEVEL`, `API_HOST`,
  `API_PORT`, `CORS_ORIGINS` (empty), `DATABASE_URL`, `ASK_NINFA_PROVIDER` and, only when Ask NINFA
  is enabled, `ANTHROPIC_API_KEY`. Read by the API, the worker, the daily wrapper and the CLIs.
- `web.env` (from `web.env.example`): **only** `NEXT_PUBLIC_API_BASE_URL`, `WEB_HOST`, `WEB_PORT`.
  It never contains `DATABASE_URL`, `ANTHROPIC_API_KEY` or `TEST_DATABASE_URL`.

**The root `.env` hazard.** `apps/web/scripts/run-next.mjs` loads a repository-root `.env` if one
exists, which would carry database credentials and API keys into the web process. Therefore:
**no `.env` file may exist in the checkout on a production host.** The web, API, worker and
daily-analysis units refuse to start if it does (`ExecStartPre=/usr/bin/test ! -e …/.env`), and the
web process receives only `web.env`.

| | DEVELOPMENT | PRODUCTION |
|---|---|---|
| `APP_ENV` | `development` / `test` | **`production`** |
| Database | `ninfa_dev`, `ninfa_test` (demo, acceptance and test tenants) | a **new, empty** database |
| `TEST_DATABASE_URL` | set | **never set** (the test suite runs migrations and downgrades on it) |
| Cookie `Secure` flag | may be disabled locally for plain HTTP | **always on**; never disabled; production refuses to start otherwise |
| Local patches | possible | development authentication-bypass or preview patches **must never be deployed** |
| Tests | run freely | **never run on the production host** |

Deployment checklist items that are always true: **never restore, push or copy the local
development database into production**; never deploy from a dirty working tree or an unreviewed
branch; production data and demo/acceptance data never share a database.

## 4. Database contract

| Requirement | Detail |
|---|---|
| PostgreSQL | **18 is the tested version** (CI and local). Managed PostgreSQL is acceptable; another major version has not been tested by this project. |
| Endpoint | A **direct, session-capable** endpoint. **No transaction-mode connection pooler in front of NINFA.** |
| Why | The application sends `-c timezone=UTC` as a connection startup option (every session runs in UTC) and the worker relies on **`LISTEN/NOTIFY`**; both fail behind transaction-mode poolers. Advisory locks (`pg_advisory_xact_lock`) are required by the import, snapshot and decision services. |
| Role | The application role (`DATABASE_URL`'s user) is a non-superuser that **owns** the NINFA database and therefore runs the migrations, including the Procrastinate queue schema. |
| URL | `postgresql+psycopg://…` (SQLAlchemy URL, psycopg 3). |
| TLS | **Required in production**: keep `?sslmode=require` (or a stricter mode such as `verify-full` with the provider's CA) in `DATABASE_URL`. The worker uses the same URL. |
| Content | A **new and empty** database, brought to the current head by Alembic. Never a copy of `ninfa_dev` or any test/demo data. No migration inserts business data. |
| Connections | Budget roughly 40 connections for API + worker + CLI (SQLAlchemy defaults to 5 + 10 per process, plus the queue connections). |

Example to adapt to the provider's own mechanism (generic PostgreSQL, **do not use
`scripts/db/bootstrap-local.sql`**, which creates the development and test databases):

```sql
CREATE ROLE ninfa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '<generated, kept in the secret store>';
CREATE DATABASE <NEW_PRODUCTION_DB_NAME> OWNER ninfa_app;
```

Check the endpoint from the production host once (provider-neutral; uses the same endpoint
NINFA will use). psql should report an "Asynchronous notification"; if it does not, the endpoint
is not session-capable:

```bash
psql "<direct endpoint connection string>" -c "LISTEN ninfa_check; NOTIFY ninfa_check; SELECT 1;"
```

## 5. First installation (build)

On the host, as the deploy account (Linux with systemd, Git, Python 3.13 through `uv`, Node 24, npm):

```bash
git clone <repository> /opt/ninfa/app && cd /opt/ninfa/app
git checkout <approved release commit>
uv sync --all-packages --locked --no-dev           # Python environment in .venv
npm ci                                              # web dependencies
scripts/with-env.sh /etc/ninfa/web.env npm run build -w @ninfa/web
```

Install the units from `deploy/systemd/` into `/etc/systemd/system/`, adjusting paths, and the
proxy from `deploy/nginx/`. **`NEXT_PUBLIC_API_BASE_URL` is a BUILD-TIME value**: it is compiled
into the web bundle. **Changing the public origin requires rebuilding the web app** with the new
`web.env`, then restarting `ninfa-web`; editing the file alone changes nothing.

## 6. Deployment procedure (first install and every update)

Never deploy while the daily analysis may be running (avoid the window around 10:00 local time).
Brief downtime is acceptable and simpler than a rolling deploy. **Migrations never run at API
startup**: they are this explicit step.

1. **Verify the commit.** `git fetch`, check out the approved release commit, and confirm
   `git rev-parse HEAD` equals the commit recorded for the release. `git status` must be clean:
   no local patches. The checkout contains no `.env`.
2. **Verify the production environment.**
   ```bash
   stat -c '%U:%G %a' /etc/ninfa/api.env           # expect ninfa:ninfa 600
   test ! -e "$NINFA_APP/.env" && echo "no root .env: ok"
   ninfa-env bash -c 'echo "APP_ENV=$APP_ENV"; test -z "${TEST_DATABASE_URL:-}" && echo "TEST_DATABASE_URL absent: ok"'
   ninfa-env bash -c 'printf "%s\n" "$DATABASE_URL" | sed -E "s#.*/([^/?]+)(\?.*)?\$#database=\1#"'
   ```
   `APP_ENV` must be `production`, the database name must be the production one (never a `dev` or
   `test` name), and neither the cookie `Secure` setting nor any development override may appear
   in `api.env`.
3. **Take a database backup or snapshot** with the managed service and record its identifier and
   time. No migration without a fresh backup.
4. **Stop the API and the worker** (and the web app if the frontend changes):
   `sudo systemctl stop ninfa-web ninfa-api ninfa-worker`. Then update the dependencies:
   `uv sync --all-packages --locked --no-dev`.
5. **Verify database connectivity.** `ninfa-py -m procrastinate -a worker.app.app healthchecks`
   must print `DB connection: OK`. (On a brand-new empty database the queue-table line is not
   expected to pass until step 6; the connection line is what matters here.)
6. **Run the migrations.**
   ```bash
   ninfa-py -m alembic -c "$NINFA_APP/services/api/alembic.ini" upgrade head
   ```
7. **Verify the schema.** The current revision must equal the head, and there must be one head:
   ```bash
   ninfa-py -m alembic -c "$NINFA_APP/services/api/alembic.ini" current   # 0013_property_analysis_policy (head)
   ninfa-py -m alembic -c "$NINFA_APP/services/api/alembic.ini" heads     # 0013_property_analysis_policy
   ninfa-py -m alembic -c "$NINFA_APP/services/api/alembic.ini" check     # No new upgrade operations detected.
   ```
   The required head at this release is **`0013_property_analysis_policy`**. If a later release
   adds migrations, this document is updated with it.
8. **Start the API:** `sudo systemctl start ninfa-api`; confirm `GET /api/v1/health` returns 200.
9. **Start the worker:** `sudo systemctl start ninfa-worker`; confirm "Starting worker" in its log.
10. **Deploy and start the frontend.** If the web app changed or the origin changed:
    `npm ci && scripts/with-env.sh /etc/ninfa/web.env npm run build -w @ninfa/web`, then
    `sudo systemctl start ninfa-web`.
11. **Smoke checks:** run the [smoke checklist](pilot-smoke-checklist-v1.md). Do not run the test
    suite on the host and never set `TEST_DATABASE_URL`.

## 7. Rollback

- **Application failure after a deploy:** redeploy the previous known-good application commit
  (steps 1, 4, 8–11, no migration step) and start the services. The migrations so far are additive
  (new tables and nullable columns), so older application code runs against the newer schema.
- **Database:** leave the additive schema in place. **Do not run an Alembic downgrade as a
  rollback**: the recent downgrades drop persisted analysis coverage, input provenance and
  automatic-analysis policy data. Prefer fix-forward with a new release.
- **A migration that fails:** migrations run inside a transaction, so a failed one leaves the schema
  as it was. Restore the step-3 backup **only** if the schema is demonstrably half-applied, and
  restore into a new database first (see [backup and restore](pilot-backup-restore-v1.md)); never
  overwrite production blindly.

## 8. Running the services

| Service | Command (systemd example) | Notes |
|---|---|---|
| `ninfa-api` | `python -m app` | binds `API_HOST:API_PORT` (loopback); `APP_ENV=production`: no debug, no docs/openapi |
| `ninfa-web` | `node apps/web/scripts/run-next.mjs start` | binds `WEB_HOST:WEB_PORT` (loopback) |
| `ninfa-worker` | `python -m worker run` | one process, no public port |

Worker facts: concurrency is **1** (one job at a time); jobs live in PostgreSQL, so **queued jobs
survive a worker restart**; a job **killed while running stays in state `doing`** (a zombie) and is
not recovered automatically; **there is no automatic retry**: a failed job stays failed. A worker
that is stopped by SIGTERM finishes its running job first (systemd's `TimeoutStopSec` bounds it).
Zombie recovery is not part of this gate.

## 9. Logging

- **API:** structured JSON on stdout (production), with a request id on every line and response.
- **Worker and web:** stdout/stderr (the worker logs JSON in production too).
- Under systemd all three go to the **journal**. Minimum host requirement: logs **survive a service
  restart and a reboot** (persistent journal storage) and stay **searchable for several weeks**
  (retention chosen by AGRIA). No external logging service is required for the first pilot.
  Examples: `journalctl -u ninfa-api --since today`, `journalctl -u ninfa-worker -n 200`.
- **Privacy:** the application does not log raw booking rows, the Ask NINFA question or answer, or
  secrets; import logs carry identifiers and counts, Ask logs carry model, status, latency and token
  counts. Do not add debug logging that changes this, and do not paste logs containing
  `DATABASE_URL` or keys into tickets.

## 10. Edge security checklist (infrastructure responsibilities)

The application does not provide these; the proxy or platform in front of it must (the reference
[nginx example](../../deploy/nginx/ninfa.conf.example) shows the structure):

- [ ] **TLS mandatory** on the public origin; HTTP only redirects.
- [ ] **HSTS**, enabled once HTTPS is verified, with a `max-age` AGRIA chooses.
- [ ] Standard **security headers** (`nosniff`, framing, referrer policy; a CSP is a deliberate
      later design).
- [ ] **Request body limit** (a value AGRIA chooses; the application checks the Ask question length
      only after reading the body).
- [ ] **Host filtering**: unknown `Host` values never reach the application.
- [ ] **Per-IP login rate limiting** (the application locks an account after 5 failed attempts for
      15 minutes but does not limit by IP).
- [ ] The API and web listeners are **loopback only**; only the proxy is public.

The application's own security does not depend on proxy headers.

## 11. Ask NINFA production policy

Ask NINFA **will be enabled for the first pilot, but only after all five conditions hold**:

1. A **provider-side hard spending limit** is configured on the Anthropic account.
2. The production `ANTHROPIC_API_KEY` is configured **only** in `api.env` (the API process); it is
   never in the web environment, the repository, a ticket or a log.
3. `ASK_NINFA_PROVIDER=anthropic` in `api.env`.
4. **One real smoke question** succeeds against the production deployment (see the smoke checklist).
5. The API log line for that call shows model, status, `elapsed_ms`, `input_tokens` and
   `output_tokens` (the telemetry exists).

**If any condition is not satisfied, leave `ASK_NINFA_PROVIDER=unconfigured`**: Ask answers
"unavailable" and the rest of Oggi is unaffected. The model, timeout (15 s), no-retry policy and
output cap are fixed in code. There is **no application-level rate limit** yet (a recorded P1): the
provider-side spending limit is therefore mandatory, not optional. Enabling or disabling means
editing `api.env` and restarting `ninfa-api`.

## 12. Access model

| Who | Access |
|---|---|
| Customer | the web app over HTTPS only |
| AGRIA operator | personal SSH key; the service CLIs through `ninfa-py` (as the service account); **no routine raw database access** |
| Developer | deployment and log access; no routine access to customer data |
| Database owner/admin | separate credential, limited to an AGRIA administrator |
| Service processes | the non-root `ninfa` account; no root login, no shared SSH passwords |

Secret-bearing env files are `0600`; deployment directories are not writable by the service
account unnecessarily; incoming hotel files are restricted to the service and operator accounts.
This is deliberately not a hardening framework.

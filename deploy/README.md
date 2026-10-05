# deploy/ — NINFA pilot deployment package V1

Reference, **provider-neutral** artifacts for running NINFA on a Linux host for the first pilot.
Nothing here deploys anything, provisions infrastructure, configures a scheduler or contains a real
secret. Replace every `<PLACEHOLDER>` and the example paths (`/opt/ninfa/app`, `/etc/ninfa`).

The procedures live in [docs/operations/](../docs/operations/README.md); start with
[pilot-deployment-v1.md](../docs/operations/pilot-deployment-v1.md).

## Topology

One public HTTPS origin behind a reverse proxy: `/api/*` → FastAPI (loopback), everything else →
Next.js (loopback); managed PostgreSQL; one worker process; an **external**, timezone-aware
scheduler running `scripts/run-daily-analysis.sh` at 10:00 `Europe/Rome`. The session cookie is not
changed: no `Domain`, never a disabled `Secure` flag.

## Files

| File | Purpose |
|---|---|
| `env/api.env.example` | environment for the API, worker, daily wrapper and operator CLI (**secrets** once filled in) |
| `env/web.env.example` | environment for the web process **only** (public origin, host, port; no secrets) |
| `systemd/ninfa-api.service` | API process (non-root, loopback, restart on failure) |
| `systemd/ninfa-worker.service` | worker process (one, no public port) |
| `systemd/ninfa-web.service` | web process (loopback; receives only `web.env`) |
| `systemd/ninfa-daily-analysis.service` | the unit an external scheduler starts; **no timer is shipped** |
| `nginx/ninfa.conf.example` | reverse-proxy example (TLS mandatory, placeholders for certificates and limits) |
| `../scripts/run-daily-analysis.sh` | the daily wrapper: dispatch → `run --once` → status |
| `../scripts/with-env.sh` | runs a command with an env file loaded safely (no shell execution of the file) |

## Rules that hold everywhere

- **Two separate env files.** The web environment never contains database credentials or API keys.
- **File permissions:** secret-bearing env files are `chmod 600` and owned by the service account;
  `web.env` holds no secrets (0640 is enough); the incoming hotel-file directory is mode 2770 for the
  service and operator accounts only; the application directory is not writable by the service
  account.
- **No `.env` in the production checkout.** The units refuse to start if one exists (the web launcher
  would otherwise load it).
- **`NEXT_PUBLIC_API_BASE_URL` is a build-time value:** changing the public origin means rebuilding
  the web app.
- **Production database:** new and empty, direct (session-capable) endpoint, TLS, owned by the
  application role. Never the development database.
- **Migrations are an explicit deployment step**, never run at startup, and a schema downgrade is
  never the rollback.
- The service account is non-root; humans use personal SSH keys; no shared passwords.

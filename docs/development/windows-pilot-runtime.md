# Windows pilot runtime: NINFA that starts by itself and stays up

For the **Windows PC that runs the pilot**: the API, the web app and the worker start after a reboot,
and are started again if they exit. It is for a machine where NINFA runs as it does in
[local-development.md](local-development.md): loopback only, plain HTTP, the checkout on disk.

It is **not** the Linux production package. That one is [deploy/](../../deploy/README.md) and
[docs/operations/](../operations/README.md) (systemd units, HTTPS, no `.env` in the checkout), and
nothing here changes it.

It changes no business logic, no scheduler and no database setting. It starts the same three commands
that `npm run dev:api`, `npm run dev:worker` and `npm run dev:web` start, and starts them again if they die.

## The problem it solves

A process started by hand dies with the reboot (or with the terminal that started it). The worker is
the one that matters: it asks for the day's analysis by itself from 10:00
([pilot-daily-operations-v1.md](../operations/pilot-daily-operations-v1.md)), and a worker that is down
all day does not recover that day. Found on 2026-11-11, when a Windows restart left no NINFA process
running.

## What was chosen, and why

**One Windows Task Scheduler task, `NINFA Pilot Runtime`, that runs a small supervisor script**
(`scripts/windows/ninfa-runtime.ps1`, PowerShell 5.1, ASCII only). Nothing is installed.

| Alternative | Why not |
|---|---|
| Windows services | `python.exe` and `node.exe` are not service executables: it takes a wrapper (NSSM, WinSW, `sc.exe` + a shim). That is new software on the pilot PC for no gain here |
| NSSM / PM2 | External supervisors; nothing in this problem needs one |
| Three separate tasks | The task's own "restart on failure" has a one-minute minimum, no backoff, and (measured) does **not** restart a process that was killed |
| A Startup-folder shortcut | Starts once; nothing brings a dead process back |

The task runs a supervisor that does what Task Scheduler cannot: it waits for PostgreSQL, restarts each process within
seconds with a growing delay, refuses duplicates, and keeps PIDs and logs where you can find them.

## Commands

Run them from the checkout, in any PowerShell. No administrator is needed except where stated.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 install     # once; also starts it
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 restart api    # api | web | worker
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 restart        # everything
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 stop
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 start
powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 uninstall      # -PurgeLogs deletes the logs too
```

`status` exits 0 only when the supervisor, the three processes and both health URLs are up.

**After you pull new code, restart what changed.** The API runs without auto-reload (`DEBUG=false`), so it keeps
the code it started with: `restart api` (and `restart worker` for worker code). The web app is `next dev` and
reloads by itself.

## What it starts

| Process | Command (working directory: the checkout) | Address |
|---|---|---|
| api | `.venv\Scripts\python.exe -m app` | `http://127.0.0.1:8000/api/v1/health` |
| worker | `.venv\Scripts\python.exe -m worker run` | no port; heartbeat in `procrastinate_workers` |
| web | `node apps\web\scripts\run-next.mjs dev` | `http://127.0.0.1:3100/` |

Ports and hosts come from `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` (environment, then `.env`, as
everywhere else). Order: PostgreSQL first (it waits up to 3 minutes for `DATABASE_URL`'s host and port, then
starts anyway and lets each process retry), then api, worker, web, a few seconds apart.

**Session cookie.** The API is started with `SESSION_COOKIE_SECURE=false` (API only) *unless* that variable is
already set in the environment or in `.env`, or `APP_ENV` is `production`. This is what the manually started stack
did: without it a browser drops the cookie over plain `http://127.0.0.1`
([local-development.md](local-development.md), "Cookie `Secure` flag"). The worker still uses `QueueConnector`.

## Recovery policy

- **A process exits** (any reason, any exit code): it is started again. The delay starts at **5 s** and doubles
  while it keeps failing (5, 10, 20, 40, 80, then **120 s** at most). A run of 2 minutes or more counts as healthy
  and resets it. It never gives up and never goes faster than that: no uncontrolled loop.
- Each process is a launcher plus a server (the venv `python.exe` and `node run-next.mjs` start a child). When the
  launcher exits, whatever its tree left behind is stopped before the restart, so a dead launcher cannot leave a
  second worker running.
- **No duplicates.** One supervisor at a time (a named mutex). A port that already answers, or a worker of this
  checkout that this supervisor did not start (for example one started with `npm run dev:worker`), is **not
  replaced and not killed**: the component is shown as `blocked` with the reason and is checked again every 30 s.
- **The supervisor itself.** Windows tries to start the task every 5 minutes (a second trigger). While it runs that
  is ignored; if it was killed, it comes back, stops whatever the dead one left, and starts everything again.
- **`stop` stays stopped**: it leaves `stopped.flag`, which the supervisor respects, until `start` or the next
  Windows boot (a reboot always brings NINFA back).
- It restarts **exited** processes. A process that is alive but stuck is not detected.

## Where things are

`%LOCALAPPDATA%\NINFA\runtime` (override: `NINFA_RUNTIME_DIR`). Nothing goes to `%TEMP%` or to the repository;
the logs are not committed.

| Path | What |
|---|---|
| `logs\supervisor.log` | every start, exit (code, how long it ran, last log lines), restart delay, `blocked`, install/stop |
| `logs\api.out.log`, `api.err.log`, `worker.*`, `web.*` | one pair per process (uvicorn and the app log to `.err.log`) |
| `logs\archive\` | the previous run's logs, kept per process (the latest 30) and replaced at each start |
| `state.json` | supervisor PID and, per process: launcher PID, restarts, last exit code, state |
| `config.json`, `bin\ninfa-runtime.ps1` | the supervised checkout and the **installed copy** the task runs |

The task runs the **installed copy**, not the file in the checkout, so switching branches (to one without
`scripts/windows`) cannot break the next reboot. `status` says when the installed copy differs from the checkout's;
run `install` again to update it. A long-running process's log is rotated only when it restarts.

## When it starts: logon, or boot (needs an administrator)

| `install` | Trigger | Needs | After a reboot |
|---|---|---|---|
| default | at **user logon** (+ the 5-minute keep-alive) | nothing | NINFA starts when you sign in. The processes end when you sign out |
| `install -Startup` | at **Windows start**, 30 s later, whether anyone is signed in or not | **administrator** (a confirmation prompt) | NINFA starts by itself, before any sign-in |

Windows refuses a boot trigger, and a task that runs while nobody is signed in, to a non-elevated account
(`Accesso negato` when tried). `install -Startup` asks for that confirmation itself. The task runs as **you**,
not as SYSTEM, so the files it creates are yours, with "run whether signed in or not" and no password stored
(S4U). This PC has no auto-login: with the default mode, after a reboot nothing runs until someone signs in.

**Status of `-Startup`:** the logon mode is the one that was exercised end to end (below). `-Startup` registers the
same task with a boot trigger and the S4U principal, but it could not be run on 2026-11-11 (no administrator
rights in that session). The first time: run it, check that `status` shows `triggers=Startup + Time` and `(S4U)`,
then restart Windows once and check `status` before anyone signs in.

## Behaviours worth knowing (measured on Windows 11, 2026-11-11)

- Killing one server process: back in 7 to 13 s (a second failure in a row waits 10 s instead of 5), new PIDs, one
  of each, health 200, and the worker's new heartbeat, `daily-analysis` registration and job counts are unchanged:
  no duplicate job.
- **"End" on the task in Task Scheduler (or `Stop-ScheduledTask`) stops only the supervisor.** The three processes
  keep running, unsupervised, until the next start of the supervisor, which stops them and starts them again. Use
  `ninfa-runtime.ps1 stop` to stop everything.
- The task's own "restart on failure" setting did **not** restart a killed supervisor: the keep-alive trigger does
  (measured: back 25 s after the kill; at most 5 minutes). `0x800710E0` as the task's last result is that trigger
  being ignored because the supervisor is already running: normal.
- The daily analysis is unchanged. A worker that comes back later the same day asks for that day's analysis; a day
  with no worker at all is not recovered or invented. The PC asleep or off means no worker either.

## Remove it

`ninfa-runtime.ps1 uninstall` stops everything and deletes the task, the installed copy and the state; the logs
stay unless `-PurgeLogs`. Nothing else was changed on the machine.

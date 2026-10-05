# Pilot smoke checklist V1 (Gate 27B)

Run after **every deployment** (step 11 of the [deployment procedure](pilot-deployment-v1.md)) and
before the first customer uses NINFA. One page, no test suite: **never run the test suite on the
production host and never set `TEST_DATABASE_URL`.** `ninfa-py` is defined in the deployment
document ("Operator shell helpers"). Replace `<origin>` with the public origin.

Record the date, the release commit and who ran it.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | **API alive** | `curl -fsS https://<origin>/api/v1/health` | HTTP 200, `"status":"ok"` |
| 2 | **Frontend loads over HTTPS** | open `https://<origin>/login` in a browser | the login page loads, valid certificate, no mixed-content warning; `http://<origin>/` redirects to HTTPS |
| 3 | **API docs are off** | on the host: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs` | `404` (production disables interactive docs) |
| 4 | **Database connectivity** | `ninfa-py -m procrastinate -a worker.app.app healthchecks` | `DB connection: OK` and the jobs table found |
| 5 | **Migration state** | `ninfa-py -m alembic -c "$NINFA_APP/services/api/alembic.ini" current` and `… heads` | both `0013_property_analysis_policy` (current marked `(head)`) |
| 6 | **Worker operational** | `ninfa-py -m worker heartbeat`, then `journalctl -u ninfa-worker -n 50` | within seconds the worker logs `Worker heartbeat: job executed`; `list_jobs task=system.heartbeat` in the Procrastinate shell shows `succeeded` |
| 7 | **Policy / status command** | `ninfa-py -m worker analysis-status` | runs and prints `enabled_policies=N …` (0 on a fresh install) |
| 8 | **Login** | a real pilot user logs in through the browser | lands on Oggi; in the browser's developer tools the `ninfa_session` cookie is **HttpOnly, Secure, SameSite=Lax**, with no explicit `Domain` |
| 9 | **Booking import** | the operator flow of [daily operations](pilot-daily-operations-v1.md), with a small or real file | `status=SUCCEEDED`, exit code 0, no unexplained `WARNING unrecognized_columns` line |
| 10 | **Oggi** | open Oggi after the first analysis | an honest state: "Analisi non ancora disponibile" before any run, then the limited-data state after a run, with the line "Non analizzati: Costi, Personale." |
| 11 | **Decision Detail** | open a decision, **if one exists** | the detail page loads (during the cold start there may be no decisions yet) |
| 12 | **Logs** | `journalctl -u ninfa-api --since today` | JSON lines with a request id; the journal is persistent and survives a restart |
| 13 | **Ask NINFA** | **only if enabled** (see the policy below) | one real question on a real decision is answered or honestly refused; the API log line shows `provider=anthropic`, the model, `status`, `elapsed_ms`, `input_tokens` and `output_tokens` |

## Ask NINFA smoke (only if enabled)

Ask NINFA stays `unconfigured` until all five conditions of the production policy hold (see the
[deployment document](pilot-deployment-v1.md), section 11): hard spending limit configured at the
provider, the key only in the API environment, `ASK_NINFA_PROVIDER=anthropic`, one real smoke call
succeeded, and the token/latency log line observed.

**Practical consequence:** the smoke call needs an existing Decision to ask about. In the first
weeks of a new property there may be none (see [pilot expectations](pilot-expectations-v1.md)). Until
a Decision exists in production, condition 4 cannot be met and Ask stays unconfigured. Creating a
separate synthetic internal workspace in production only to smoke-test Ask is a product decision
that has not been taken: do not do it without that decision.

## If a check fails

Stop the rollout, do not use the customer, and follow the rollback rules in the deployment document
(redeploy the previous known-good commit; never an Alembic downgrade).

# Decision API V1 (`decision-api-v1`, Gate 12)

A READ-ONLY HTTP surface over Gate 11's Decision Layer. See ADR 0018 for the "why" behind every
choice below; this document is the "what" and "how".

## Scope

Four `GET` endpoints under `/api/v1/properties/{property_id}/`:

| Endpoint | Purpose |
| --- | --- |
| `GET /decision-feed?as_of=YYYY-MM-DD` | "What needs action today" - the latest run's TRIGGERED items |
| `GET /decisions` | Memory/lifecycle: every Decision, cursor-paginated, filterable |
| `GET /decisions/{decision_id}` | One Decision's current state + its latest Observation |
| `GET /decisions/{decision_id}/history` | Every Observation of one Decision, newest-first |

Nothing here writes. `DecisionService.sync()` (Gate 11's own write path) is never reachable over
HTTP, never called by a route, and no route opens a mutating transaction, calls `PriorityService`,
or calls a detector. See "Read-only guarantees" below.

Explicitly NOT in scope (unchanged since Gate 11, now enforced by `test_decision_api_scope.py`
too): manual Decision creation, acknowledge/dismiss/snooze/resolve/reopen, assignment,
recommendations, generated prose, AI, notifications, a scheduler, a frontend, detector execution,
Priority execution.

## Authorization boundary

**Update (Gate 13):** `app.core.auth.get_current_principal` is no longer fail-closed - Gate 13
(`auth-session-v1`, see [auth-session-v1.md](auth-session-v1.md) and ADR 0019) replaced its body
with a real resolver (`HttpOnly` session cookie -> `SHA-256` -> `AuthSession` -> `User`), and it
was the ONLY change: every route on this page still depends on exactly the same function, imported
from exactly the same place. The paragraphs below describe Gate 12's ORIGINAL fail-closed seam,
kept for history; the shape it left behind is exactly what Gate 13 filled in.

At Gate 12 time, no real authentication provider existed anywhere in this repository
(`app.modules.identity`'s own `User` model stored no credential - see its docstring). Gate 12
therefore shipped a **fail-closed authorization boundary**, not a real login system:

- `app.core.auth.AuthenticatedPrincipal` - a typed `{user_id}` shape every route depends on.
- `app.core.auth.get_current_principal` - the FastAPI dependency every route resolves it from. Its
  Gate-12 PRODUCTION body was unconditional: it always raised `AuthenticationRequiredError` (401).
  There is no header, cookie or query parameter this module ever trusts as identity - `X-User-Id`
  and similar are explicitly the kind of spoofable shortcut this boundary exists to refuse (still
  true of the real Gate 13 resolver).
- Tests supply a real principal via FastAPI's own `app.dependency_overrides[get_current_principal]`
  (see `tests/conftest.py`'s `authenticated_as` fixture) - never a header. Gate 13 additionally
  exercises the REAL cookie path with NO override at all
  (`tests/test_auth_real_cookie_e2e.py`).
- Gate 12 predicted: "a future gate wires a real provider... by replacing only
  `get_current_principal`'s body; no route changes." Gate 13 is that gate, and did exactly that.

### Tenant derivation (server-side only)

The client sends a `property_id` path parameter and nothing else. `app/api/v1/decisions/deps.py`'s
`resolve_property_scope` dependency does the rest, entirely server-side:

    property_id (path) -> Property row -> its workspace_id -> WorkspaceMembership(workspace_id, principal.user_id)
    -> TenantContext(workspace_id)

V1's authorization policy (Gate 1 has no `PropertyAccess` primitive, only `WorkspaceMembership`):
**active workspace member -> access to every property of that workspace.** No `PropertyAccess`
table was invented for this gate.

A missing property, an archived property, and a real property the caller has no membership on all
answer the identical `PROPERTY_NOT_FOUND` (404) - never 403. Distinguishing them would let an
authenticated-but-unauthorized caller enumerate which property ids exist in a foreign workspace.
Unauthenticated: 401. A Decision belonging to another property/workspace than the one resolved in
the path: `DECISION_NOT_FOUND` (404), same reasoning.

## Decision feed

`as_of` is **mandatory** and validated (`INVALID_AS_OF_DATE`, 400, on a malformed value; omitted
entirely -> FastAPI's own required-query-param 422). Never `date.today()`/`datetime.now()` as a
default (`test_decision_api_feed.py`'s own source-scan test checks this directly).

### Latest run selection

Several `DecisionRun`s can share one as-of date (same-day re-syncs). The feed always uses the run
with the **highest `run_sequence`** of that exact `(workspace, property, as_of)` -
`DecisionRepository.latest_run()` - never `created_at` alone (see Gate 11's own reasoning for why
`run_sequence` exists at all: `created_at` cannot break a tie within one transaction).

### Feed states

A typed `feed_state`, never "empty = all clear":

| State | Condition |
| --- | --- |
| `NOT_PROCESSED` | no `DecisionRun` exists for this property/as-of at all |
| `ACTION_REQUIRED` | the selected run's `triggered_count > 0` |
| `DATA_QUALITY_LIMITED` | `triggered_count == 0` AND (`insufficient_count > 0` OR `suppressed_count > 0`) |
| `NO_ACTION_REQUIRED` | `triggered_count == 0` AND `insufficient_count == 0` AND `suppressed_count == 0` |

A `NOT_APPLICABLE`-only run (or an all-`CLEAR` run) is `NO_ACTION_REQUIRED`, not a data-quality
problem: an inapplicable rule is not evidence NINFA lacks data. `NO_ACTION_REQUIRED` is the only
state a future "Today" UI may read as "nothing to do" - and only together with the run metadata
below, so it can also show *when* that conclusion was reached.

### Feed content

When `ACTION_REQUIRED`, `items` is exactly the selected run's TRIGGERED `DecisionObservation`s,
each paired with its Decision's current lifecycle row, ordered `priority_rank ASC`
(`DecisionRepository.feed_rows()`, one query, joined). Every score is copied from what Gate 11
already persisted - the feed never calls `PriorityService.rank()` or a detector
(`test_decision_api_feed.py::test_feed_never_calls_priority_service_or_a_detector` proves this by
patching both and asserting the endpoint still answers 200).

### Run metadata

`property_id`, `as_of_local_date`, `feed_state`, `decision_run_id` (nullable), `run_sequence`
(nullable), and the five status counts (nullable). **All five counts are `null`, not `0`, when
`NOT_PROCESSED`**: this is what lets a client tell "not processed yet" apart from "processed, zero
of everything" (which cannot actually happen - `evaluation_count` is never zero for a real sync,
but the API still models the field as nullable to make the distinction explicit and future-proof).

## Decision list

Cursor-paginated (never offset), `limit` default 20, min 1, max 100 (`INVALID_LIMIT`, 400, outside
that range for an otherwise well-typed integer; a non-integer `limit` is FastAPI's own 422).
Optional `status` (`OPEN`/`RESOLVED`, `INVALID_DECISION_STATUS` otherwise) and `decision_type` (one
of the five MVP types, `INVALID_DECISION_TYPE` otherwise) filters.

### Order

`last_evaluated_local_date DESC, last_seen_local_date DESC, decision_type, decision_id` -
**deliberately never by priority**: priority belongs to an Observation, and an OPEN Decision may
have no TRIGGERED Observation at all in the latest run (see the golden Day 2 scenario:
`REV_PICKUP_LOW`/`REV_OCCUPANCY_RISK` stay OPEN on `INSUFFICIENT_DATA` while COST alone is
TRIGGERED that day). `latest_observation_summary` on each list item still exposes that
Observation's own `priority_rank`/`priority_score` (nullable) for context, without driving order.

### Cursor

Opaque, versioned (`decision-list-cursor-v1`), base64url of a small canonical JSON object
(`workspace/property`-free: it carries only `last_evaluated_local_date`, `last_seen_local_date`,
`decision_type`, `decision_id` - the exact keyset position of the previous page's last row), stdlib
only (`base64`+`json`, no new dependency). **Not signed**: it carries no authority. Every query is
still filtered by the server-derived `TenantContext`/`property_id` regardless of what the cursor
says, so a cursor built against one property/workspace, replayed against another, can only ever
change *where* an already-authorized query resumes - never *what* tenant/property it reads
(`test_decision_api_list.py`'s own `test_a_cursor_from_another_*` tests prove this: a 200, an
empty or correctly-scoped result, never a leak). A malformed or wrong-version cursor is
`INVALID_CURSOR` (400).

## Decision detail

Identity + current lifecycle (`status`, the three dates, `resolved_local_date`, `episode_count`,
`triggered_observation_count`), the explicit `target` DTO, and the latest Observation's full audit
shape (`ObservationDetail`: facts/evidence/reason codes/priority snapshot/economic proxy/memory
version) - the same shape a history item has (see "Serializers" below for why they are the SAME
DTO). `decision_api_version` (`decision-api-v1`) is included for forward audit. A decision that
does not exist, or exists in a different property/workspace than the one resolved from the path:
`DECISION_NOT_FOUND` (404) either way.

## Decision history

Cursor-paginated (`decision-history-cursor-v1`), default/max limit identical to the list endpoint.
**Newest-first**: `as_of_local_date DESC, run_sequence DESC, observation id` (the deliberate DESC
mirror of Gate 11's own `DecisionMemoryService.get_history()`, whose ASC order is untouched - a
NEW method, `get_history_page_desc()`, serves the API; Gate 11's own callers/tests keep working
unmodified). `run_sequence` (not `created_at`) breaks a same-day, multiple-run tie, exactly like
the feed's own "latest run" selection.

## Serializers: never a raw passthrough

`app/api/v1/decisions/serializers.py`:

- **`target`**: four explicit DTOs (`RevenueDecisionTarget`, `OtaDecisionTarget`,
  `CostDecisionTarget`, `LaborDecisionTarget`), discriminated by a `type` literal, built field by
  field from the real, audited `Decision.identity_payload` keys (never the raw JSON). Every field
  name was checked against Gate 11's own `identity.py` and its tests
  (`test_decision_identity.py::test_*_identity_includes_the_real_gate_7*` and siblings) - nothing
  here was invented.
- **`facts`/`evidence`**: a per-`decision_type` WHITELIST of the exact keys Gate 11's own
  `app/modules/decisions/serialization.py` writes (audited by hand against every `serialize_*`
  function there), applied to the stored `facts_payload`/`evidence_payload` before they ever leave
  this API. `observation.facts_payload`/`.evidence_payload` are never returned as-is - even though
  Gate 11 already minimizes them, this gate keeps its own, independent boundary
  (`test_decision_api_serialization.py`'s own whitelist tests inject an unexpected key and assert
  it is dropped).
- **`priority`**: a `PrioritySnapshot` (rank/impact/urgency/confidence/actionability/priority
  score, candidate fingerprint), present only when the Observation's own `source_status` was
  TRIGGERED (mirroring the DB `CHECK` that already guarantees this).
- **`economic_proxy`**: populated only for `COST_CPOR_ANOMALY` (`currency` = the evaluation's own
  real `currency` field) and `LABOR_OVERSTAFFING` (`currency` = `cost_currency`, when present) -
  **never** for Revenue/OTA, whose gap/exposure proxies carry no currency dimension anywhere in
  Gate 5/9's own evaluation types (confirmed by Gate 11's own reflection test,
  `test_decision_memory_privacy.py::test_no_evaluation_field_is_an_unconstrained_free_text_string`).
  This API never invents one.

## Decimal, dates, UUIDs, enums

Every exact `Decimal` that decided something (a score, a proxy amount) is a canonical **string**
(`app.modules.decisions.precision.canonical_text`), never a float: JavaScript's `Number` cannot
carry Gate 10's own arbitrary-precision priority scores. Dates: ISO `YYYY-MM-DD`. UUIDs: canonical
lowercase string. Enums: the detector/lifecycle's own stable string values, unchanged.

## Privacy

Gate 11 already minimizes what is persisted; Gate 12 adds its OWN, independent boundary on top (the
facts/evidence whitelist above) and a runtime test
(`test_decision_api_privacy.py`) that walks the JSON of all four endpoints for nine PII categories
(guest name/email/phone, employee identity, tax code, address, IBAN, medical data, supplier
free-text name) - none of which has any field to be injected into anywhere in the real pipeline
(Gate 11's own reflection test proves that structurally), and none of which appears.

## Error contract

`{"error": {"code", "message", "details", "request_id"}}` (unchanged shape from the codebase's
existing convention, `app/core/errors.py`). Stable codes this gate adds: `AUTHENTICATION_REQUIRED`
(401), `PROPERTY_NOT_FOUND` / `DECISION_NOT_FOUND` (404), `INVALID_AS_OF_DATE` /
`INVALID_DECISION_STATUS` / `INVALID_DECISION_TYPE` / `INVALID_CURSOR` / `INVALID_LIMIT` (400).
Genuinely malformed types FastAPI/Pydantic cannot even coerce (a non-integer `limit`, a missing
required `as_of`) still answer the codebase's existing generic 422 `validation_error` - this gate
does not reimplement that. 500 never exposes a stack trace, SQL text, a filesystem path or a raw
exception representation (`test_decision_api_errors.py::test_unexpected_error_leaks_no_internals`
forces a genuine unhandled exception and checks the response text directly).

## Read-only guarantees

Every route: no `session.commit()`, no lifecycle mutation, no `DecisionRun`/`DecisionObservation`
insert. `test_decision_api_readonly.py` proves this by snapshotting the three Decision Layer
tables' row counts and a Decision's own `updated_at` before/after a GET (including several GETs in
a row) and asserting nothing moved.

## Performance

Every query path is set-based:

- Feed: one query for the latest run, one join query for its TRIGGERED observations+Decisions.
- List: one keyset-paginated query for the Decision page, one further `DISTINCT ON` query for the
  whole page's latest Observations (`DecisionRepository.latest_observations_of`) - never one
  SELECT per Decision.
- Detail: the same `DISTINCT ON` query, scoped to one id.
- History: one keyset-paginated query, joined with `DecisionRun` for `run_sequence`.

`test_decision_api_performance.py` measures the actual SQL statement count at 1 vs 50 items (feed,
list) and asserts it stays a small, N-independent constant - never linear.

## Limitations (intentional, documented debt)

- **Resolved by Gate 13**: a real authentication provider is now wired (first-party email +
  password, opaque server-side session - see [auth-session-v1.md](auth-session-v1.md)). No route
  on this page changed to get it, exactly as this document originally predicted.
- No caching (no ETag, no Redis) - not needed at V1's scale, and adding it now would be premature.
- No frontend consumes this API yet (Gate 12/13 ship no UI).
- `packages/contracts` still does not derive types from this OpenAPI schema automatically (see
  `architecture-v1.md`'s own "API conventions" - unchanged since before this gate).

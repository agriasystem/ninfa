# 0018 — Decision API V1: read-only HTTP over the Decision Layer, fail-closed authorization

## Context

Gate 11 (ADR 0017) gave NINFA a persistent Decision Layer: `DecisionRun`/`Decision`/
`DecisionObservation`, written only by `DecisionService.sync()`, read only by
`DecisionMemoryService`. Nothing outside the backend process could reach any of it - there was no
HTTP surface beyond `GET /api/v1/health` (ADR 0016 records why: exposing business data before an
authorization model exists would suggest a security posture the codebase does not have).

Gate 12 is the first HTTP business API. It must expose the Decision Layer to a future "Today" UI
without becoming, itself, the place a client can spoof identity, sync a run, or recompute a score.

## Decision

1. **API is read-only, by construction.** Four `GET` endpoints (feed, list, detail, history); no
   `POST`/`PATCH`/`DELETE` on a decision anywhere. `test_decision_api_scope.py` asserts every route
   is `GET`-only from the generated OpenAPI schema itself, not from a hand-maintained list.

2. **`DecisionService.sync()` is never reachable over HTTP.** A sync is a whole-pipeline operation
   (detectors -> Priority -> persistence) that belongs to a scheduled job, not a request/response
   cycle; exposing it would also let any authorized caller manufacture Decision Memory on demand,
   defeating the point of persisting only what a real detector run produced.

3. **Authorization is fail-closed, not stubbed.** No credential store exists yet
   (`app.modules.identity.User` stores none, by its own design). Rather than invent a throwaway
   scheme (an `X-User-Id` header, a hardcoded test user) that would look like real auth and is not,
   `get_current_principal`'s production body unconditionally raises 401. A real provider drops in
   later by replacing that one function; every route already depends on it and needs no change.
   Tests use FastAPI's own `app.dependency_overrides`, the mechanism the framework provides
   specifically for this, never a spoofable header.

4. **Tenant scope is derived server-side, from the path's `property_id` alone.** The client never
   sends (and the server never trusts) a `workspace_id`. `Property -> workspace_id ->
   WorkspaceMembership(workspace_id, principal.user_id) -> TenantContext` is resolved once, in a
   single dependency, before any route body runs - the same posture Gate 11's own
   `DecisionService`/`DecisionRepository` already require (nothing there accepts a bare workspace
   argument either).

5. **An unauthorized property, and a missing one, answer the identical 404.** A 403 would confirm
   the property id exists but is someone else's - resource-id enumeration by status code. The same
   reasoning extends to a Decision resolved outside the path's own property/workspace: `404`, never
   `403`, never a different shape than "truly does not exist".

6. **The feed always uses the LATEST `DecisionRun` (highest `run_sequence`) of an exact
   `(workspace, property, as_of)`.** Several runs can legitimately share one as-of date (a re-sync
   after fixing a data issue); `created_at` cannot break that tie (Gate 11's own reasoning: postgres
   `now()` is fixed for a whole transaction). `run_sequence` already existed for exactly this in
   Gate 11 - this gate is its first real consumer outside Gate 11's own tests.

7. **Absence of a run is its own state, `NOT_PROCESSED` - never folded into `NO_ACTION_REQUIRED`.**
   A future "Today" UI reading `NO_ACTION_REQUIRED` as "all clear" must never be shown that when
   NINFA simply has not run yet for that date.

8. **`DATA_QUALITY_LIMITED` is its own state, distinct from `NO_ACTION_REQUIRED`.** Zero TRIGGERED
   evaluations because the data was insufficient/suppressed is not the same fact as zero TRIGGERED
   evaluations because everything genuinely cleared. Collapsing them would let a data-quality gap
   look identical to "everything is fine".

9. **Priority is never recalculated.** The feed/detail/history all read the exact
   `priority_rank`/`*_score`/`candidate_fingerprint` Gate 11 already persisted from Gate 10's own
   ranking. Recomputing anything here would let the API's own answer drift from the Decision Memory
   it claims to be reporting, and would call a detector/`PriorityService` from a request path -
   exactly what this gate exists to not do (`test_decision_api_feed.py`'s own mock-based test
   proves neither is ever called).

10. **The Decision list orders by lifecycle dates, never by priority.** Priority belongs to an
    Observation, and the latest run may not have TRIGGERED a given OPEN Decision at all (it can be
    OPEN on an old episode, currently `INSUFFICIENT_DATA`) - so "priority order" is not even a
    coherent concept for the list as a whole. `last_evaluated_local_date DESC, last_seen_local_date
    DESC, decision_type, decision_id` is stable and always defined.

11. **Cursor pagination, never offset.** An offset shifts silently as new Decisions are created
    between two page reads (an OPEN Decision's own `last_evaluated_local_date` moves every time it
    is re-observed); a keyset cursor anchored on the previous page's own last row does not. The
    cursor is opaque and versioned (`decision-list-cursor-v1` / `decision-history-cursor-v1`) but
    deliberately UNSIGNED: it carries no authority (every query still filters by the server-derived
    tenant/property regardless of what the cursor says), so there is nothing to protect against
    tampering beyond "does it still decode to a coherent keyset".

12. **Every exact `Decimal` is a JSON string.** JavaScript's `Number` cannot hold Gate 10's own
    50-significant-digit priority scores without silent precision loss. A `"89.00"` string is
    exact; a JSON number `89.00` is not guaranteed to survive a round trip unchanged.

13. **`identity_payload` is never returned raw.** It is Gate 11's own internal audit/collision-
    detection payload, versioned independently (`decision-identity-v1`) from the API's own public
    contract (`decision-api-v1`); coupling the two would mean a Gate 11 identity change breaks
    Gate 12's response shape even when nothing about the PUBLIC target contract needed to change.
    Four explicit `type`-discriminated DTOs (Revenue/OTA/Cost/Labor) are built field by field
    instead.

14. **API-level serializers are explicit and whitelisted, on top of Gate 11's own minimization.**
    `facts`/`evidence` pass through a per-`decision_type` key whitelist before ever reaching a
    response, even though Gate 11's own `serialization.py` already minimizes what gets persisted -
    a second, independent boundary catches a future accidental field addition on either side before
    it becomes a public API leak.

15. **No recommendation, generated prose, or AI anywhere in this gate.** Consistent with Gate 11's
    own boundary (`test_decision_scope.py`) and enforced the same way for the new code
    (`test_decision_api_scope.py` checks the generated OpenAPI paths directly).

16. **Future auth/UI integration is a drop-in, not a rewrite.** Swapping `get_current_principal`'s
    body for a real session/JWT resolver, or building a "Today" UI against this exact contract, are
    both additive: no route signature, DTO or error code here is expected to change for either.

## Alternatives considered

- **A spoofable header (`X-User-Id`/`X-Workspace-Id`) as a stand-in until real auth exists.**
  Rejected outright - the review that opened this gate explicitly forbids it, and it is genuinely
  worse than fail-closed: it would look secure while being trivially bypassable, and every caller
  of this API (including a future frontend) would have to be migrated off it later.
- **403 for an unauthorized-but-existing property.** Rejected: leaks existence, enabling
  enumeration of property ids across workspaces.
- **Offset pagination (`?page=2`).** Rejected: unstable under concurrent writes to the same list
  (a newly-OPENED or newly-re-observed Decision shifts every later page).
- **A new `PropertyAccess` table for per-property authorization.** Rejected for V1: Gate 1 has no
  such primitive, and the review explicitly asked not to invent one. Workspace membership already
  answers "which properties can this user reach" completely at V1's scale (every property belongs
  to exactly one workspace); a per-property grant is a real future feature, not implied by anything
  in this gate.
- **Recomputing Priority/detectors in the API layer "for freshness".** Rejected: it would silently
  turn a read endpoint into a second compute path, able to disagree with what Decision Memory
  actually recorded, and would reintroduce exactly the coupling Gate 10/11 were built to avoid.
- **A single generic `facts: object` with no whitelist ("Gate 11 already minimizes it").**
  Considered and rejected as insufficient on its own: the review explicitly asked for an
  independent API-side boundary, and a second whitelist costs little given Gate 11's serializer
  already documents the exact key set per detector.

## Consequences

- A future gate can wire real authentication by editing exactly one function
  (`get_current_principal`), with zero route changes - and must, before this API is exposed beyond
  trusted testing, since it is otherwise entirely inaccessible in production (fail-closed).
- A future gate can add "assign/acknowledge/dismiss" as genuinely new write endpoints without this
  gate needing to change: the read contract here does not assume or preclude a lifecycle these
  verbs would add.
- Any future OTA/Revenue detector that starts recording a real currency for its own gap/exposure
  proxy can add an `economic_proxy` for that type by extending `economic_proxy_of()` - not by
  inventing a currency today.
- If Gate 1 later grows a genuine per-property access primitive, `resolve_property_scope` is the
  one place that needs to change; every route already depends on it, not on `WorkspaceMembership`
  directly.

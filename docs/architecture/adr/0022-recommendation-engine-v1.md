# 0022 — Recommendation Engine V1: deterministic, explainable, non-autonomous

## Context

Gate 15's own ADR (0021, point 16) named this explicitly as future work: "A Recommendation layer
and Ask NINFA remain explicitly future work, not implied by anything built here... When a
Recommendation layer is built, it is a NEW section, additive to this page, never a rewording of
the evidence/why sections that already exist." Gate 16 is that layer, at the API level only - no
UI consumes it yet. The Decision Detail API (Gate 12) already carries everything a recommendation
needs to be built from: a Decision's identity and lifecycle, and its latest Observation's
whitelisted facts, priority snapshot and confidence - all of it already real, already persisted,
already audited for privacy. Nothing new needed to be computed; something new needed to be
*derived*, deterministically, from data that already exists.

## Decision

1. **Zero AI, zero prose generation, zero embeddings, by construction, not by convention.** The
   engine is closed-enum rules over closed-enum facts: `ActionCode`/`ActionCategory`/`ActionScope`
   are `StrEnum`s, `title_key`/`description_key` are pure functions of `action_code`
   (`f"recommendation.action.{code}.title"`), and no module in `app/modules/recommendations/`
   imports anything resembling an LLM client, embedding model or vector store
   (`test_recommendation_scope.py`'s own AST scan of every identifier in the package proves this,
   not just a naming convention).

2. **The only inputs are a persisted `Decision` and its latest `DecisionObservation`.** Never a
   raw `Booking`/`Invoice`/`LaborEntry`/snapshot row, never a re-invocation of
   `RevenueDecisionService`/`CostDecisionService`/`LaborDecisionService`/`OtaDependencyService`/
   `DemandForecastService`/`PriorityService`/`BookingExpectedService`. Decision Memory (Gate 11)
   is already the durable, already-decided record of "what happened"; re-deriving from raw rows
   would risk disagreeing with it, and re-invoking a detector would risk a different answer on a
   different day for the same historical Decision - Gate 11's own immutability guarantee (enforced
   by a DB trigger, `decisions_forbid_update()` - confirmed empirically while building this gate's
   own tests) would then be a lie one layer up.

3. **`requires_human_review` is `True` unconditionally, on every `Action` and on the top-level
   result, with no field anywhere that could mean the opposite.** No `auto_apply`, `execute`,
   `approved_by_default` or similar field exists on `Action` or `RecommendationResult` - checked
   structurally (`dataclasses.fields()`), not just by the absence of a UI button. NINFA proposes;
   a human decides. This is the single non-negotiable constraint the whole gate exists to satisfy.

4. **A recommendation names a REVIEW ACTION, never the business decision itself.** "Review pricing
   and availability", never "lower the price"; "review demand positioning", never "apply a
   discount"; "review distribution mix", never "close this OTA channel"; "review cost drivers",
   never "change supplier"; "review staffing plan", never "reduce staff". The five primary
   `ActionCode`s are a closed, hand-picked set, and `test_recommendation_action_safety.py` checks
   both that no rule can ever produce anything outside it AND that the rendered template keys
   contain none of the specific forbidden phrases the review demanded.

5. **`source_status != TRIGGERED` -> `NOT_AVAILABLE`, regardless of the Decision's own `status`.**
   An OPEN Decision whose CURRENT observation is `INSUFFICIENT_DATA` (a real, common shape - see
   Gate 11's own Day-2 golden scenario) has nothing actionable right now; showing a recommendation
   anyway, built from a stale prior observation, would silently misrepresent what NINFA currently
   knows. `RESOLVED`/`CLEAR` is the same case from the other direction: nothing to review once the
   problem is gone.

6. **Missing or malformed facts fail closed to `INSUFFICIENT_CONTEXT`, never a guess, a default,
   or a crash.** Every rule reads a fixed, minimal set of named facts through three small helpers
   (`_text`/`_int`/`_bool` in `rules.py`), each of which treats absent, wrong-typed, or
   non-Decimal-parseable exactly like absent. In practice a REAL detector-produced facts payload
   is always well-formed (the whitelist is enforced at evaluation time) - `INSUFFICIENT_CONTEXT`
   exists as a defensive boundary against a partial or hand-built fixture, not a state any real
   TRIGGERED pipeline run is expected to reach. Confirmed the hard way while building this gate:
   Gate 11's own minimal `revenue_evaluation()` test fixture (built for Decision LIFECYCLE testing,
   never for numeric-fact completeness) genuinely reaches this branch through the real HTTP
   endpoint - the correct, intended behaviour, not a bug either in the fixture or the engine.

7. **At most one primary action plus two supporting checks, always in the same, deterministic
   order.** The primary answers "what should a human look at first"; supporting checks are
   optional, additional angles, each gated on one specific optional fact being present in that
   exact order every time (`pickup_rule`'s own `rooms_condition` before `missing_rooms`, and so on
   for every rule) - never re-ordered, never more than two, so the shape is always predictable.

8. **The primary action's `risk_notes` is an empty tuple for `COST_CPOR_ANOMALY`, not a forced
   fit.** None of the three closed `RiskNote`s (pricing/staffing/distribution) honestly describes
   "review cost drivers" - it is a data-verification step, not a pricing, staffing or distribution
   change. An honest empty tuple was chosen over stretching an existing note to cover a case it
   does not fit.

9. **Confidence is copied verbatim, through the SAME `canonical_text()` convention Gate 11 already
   established, never recomputed.** `_confidence_text()` returns `None` only if the persisted
   value is itself `None` (the DB schema forbids this; the check exists so a corrupt/mocked row
   fails closed rather than crashing) - it never runs a second probabilistic model, and the exact
   same value the Decision Detail API's own `priority.confidence_score` already shows is what the
   recommendation carries, byte for byte.

10. **No business value is ever recalculated.** Every delta, expected value, threshold comparison
    and the `economic_proxy` were already decided by a detector; the engine's rules only check
    whether the exact whitelisted fact they need is present, then copy it, as a canonical string,
    into `supporting_facts`. `test_recommendation_engine.py`'s own verbatim-copy tests (mutating
    `priority_rank` between two calls and asserting an identical fingerprint) prove the engine has
    no dependency on Priority Engine math beyond what confidence already carries.

11. **A dedicated SHA-256 fingerprint, built the same way Gate 10's own `priority/fingerprint.py`
    already does** (`json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True)` ->
    `hashlib.sha256(...).hexdigest()`), over exactly the fields that describe WHAT was recommended
    and WHY - the recommendation version, the Decision's own semantic identity
    (`identity_version`/`identity_key`/`decision_type`, never the DB-generated `decision.id`), the
    observation's own semantic `source_evaluation_fingerprint` (never `observation.id`), the
    status, every action code with its canonicalised facts and risk notes, and confidence.
    Explicitly excludes anything DB-generated or wall-clock: no timestamp, no random source, no
    other module's live state influences it, so the same two persisted rows always fingerprint
    identically, forever.

12. **Exposed ADDITIVELY on the existing Decision Detail response - `recommendation`, a new,
    non-nullable field - never a new route.** `RecommendationEngine().evaluate(decision,
    latest_observation)` is called once, inside `decision_detail_of()`, exactly where both objects
    were already in scope. `test_decision_api_scope.py`'s own OpenAPI-level checks (the exact same
    4-path set as Gate 12, no new query parameter, `recommendation` present in
    `DecisionDetailResponse`'s own schema) prove the addition changed nothing else.

13. **The public `RecommendationResponse` deliberately omits the engine's own internal
    bookkeeping** - `generated_from_observation_id`, `generated_from_evaluation_fingerprint`,
    `reason_codes` - fields `RecommendationResult` (the internal dataclass) carries for potential
    future audit use, but that add nothing a consumer of the recommendation itself needs today.
    `recommendation_of()` (the serializer) is the one, explicit place that narrows the internal
    shape down to the public one.

14. **ZERO persistence, ZERO migration, ZERO new dependency.** No table, no column, no Alembic
    revision. The recommendation is computed fresh on every request, from whatever the latest
    persisted Observation says right now - `test_recommendation_readonly.py` proves a real GET,
    repeated, writes nothing and returns byte-identical JSON every time, and a direct
    `information_schema`/`pg_tables` query proves no table matching `%recommendation%` exists at
    all. No package was added to `pyproject.toml`; every helper (`StrEnum`, `dataclasses`,
    `hashlib`, `json`) is Python's own standard library, reusing the exact `canonical_text`
    convention Gate 10/11 already established.

15. **No mutation vocabulary anywhere, structurally, not just absent from the route table.**
    `test_recommendation_scope.py`'s own identifier scan forbids
    acknowledge/dismiss/snooze/assign/autoapply/execute/approvedbydefault as an identifier
    ANYWHERE in the package, on top of `test_decision_api_scope.py`'s existing path-level check
    (extended this gate to also forbid execute/approve/apply/auto in any OpenAPI path) - a future
    contributor cannot even name a private helper after the concept this gate exists to rule out
    without a test failing.

16. **A Recommendation UI and Ask NINFA remain explicitly future work**, exactly as ADR 0021 (point
    16) already said they would be. This gate is the API-level half of that promise; the other
    half - a page that actually renders `recommendation` to a user - is deliberately not started
    here, and when it is, it is additive to Gate 15's own Decision Detail page, never a rewording
    of the evidence/why sections that already exist there.

## Alternatives considered

- **Filling in `app/modules/intelligence/recommendation/`, the empty package Gate 0 reserved for
  it.** Rejected. That placeholder sits under `intelligence/`, alongside the five DETECTOR
  modules; this engine has zero dependency on any of them (point 2 above) and reads only the
  Decision Layer's own already-decided memory - structurally, it belongs beside `decisions`/
  `decision_memory` (Gate 11's own top-level, sibling modules), not inside the detection layer
  whose job is producing the signals this engine deliberately never re-touches. The real module
  lives at `app/modules/recommendations/` instead; Gate 0's placeholder package stays exactly as
  it was, empty, an intentionally unused prediction rather than a followed one.
- **Reading raw `facts_payload`/`evidence_payload` with no whitelist of its own.** Rejected: Gate
  12's own serializer already whitelists what LEAVES the API, but the recommendation engine reads
  the STORED payload directly (it runs inside the API process, before serialization) - without its
  own explicit, named set of facts per rule, a future detector change could silently widen what a
  recommendation is built from. Every rule names its exact facts by hand instead.
- **Re-invoking a detector to get a "fresher" numeric picture for the recommendation specifically.**
  Rejected outright - see point 2. A recommendation about a Decision must describe the SAME
  Decision Memory a human reading the rest of the detail page sees, never a parallel, silently
  more-current calculation.
- **A confidence tier (HIGH/MEDIUM/LOW) instead of the raw percentage string.** Rejected: Gate
  11/12 already expose the raw confidence elsewhere on the same page; inventing a second,
  coarser representation for the recommendation alone would be two sources of truth about the same
  number, for no benefit V1 needs.
- **Persisting each computed recommendation for later audit ("what did NINFA suggest on day X").**
  Rejected for V1: nothing yet consumes a recommendation history, and the fingerprint already
  makes any future persistence trivial to add later (same input -> same fingerprint -> a natural
  primary key) without needing to design that now.

## Consequences

- A sixth decision type added to the five MVP detectors must gain its own rule in `rules.py` and
  its own entry in `_RULE_BY_TYPE` (`engine.py`) - `UnsupportedDecisionTypeError` exists precisely
  to fail loudly, not silently, if one is forgotten.
- The recommendation's own fingerprint changes whenever `RECOMMENDATION_ENGINE_VERSION` changes,
  exactly like Gate 10's own `PRIORITY_RULES_VERSION` convention - a future rule change bumps the
  version string, never reuses an old fingerprint for new logic.
- A future Recommendation UI (ADR 0021's own promise, still outstanding) reads `recommendation`
  additively from the existing Decision Detail response - no new fetch, no new endpoint.
- A future persistence layer for recommendations (if ever needed) can use the fingerprint as its
  natural identity without re-deriving one, since it is already stable and collision-resistant.

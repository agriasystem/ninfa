# Recommendation Engine V1 (`recommendation-engine-v1`, Gate 16)

A deterministic, non-AI derivation layer over Gate 11's Decision Memory, exposed additively on
Gate 12's existing Decision Detail API. See ADR 0022 for the "why" behind every choice below; this
document is the "what" and "how".

## Scope

One pure Python module, `app/modules/recommendations/`, with no database session, no HTTP
dependency, no detector/`PriorityService`/`Expected`-service import, and no AI/ML dependency of any
kind:

    RecommendationEngine().evaluate(decision, latest_observation) -> RecommendationResult

Wired into the existing `GET /api/v1/properties/{property_id}/decisions/{decision_id}` response
(Gate 12) as one new, non-nullable field, `recommendation`. **No new route.** Explicitly NOT in
scope: any write/mutation endpoint, acknowledge/dismiss/snooze/assign/execute/approve/apply of any
kind, generated prose, an LLM/embedding/vector-store call, a Recommendation UI (Ask NINFA remains
future work - see ADR 0021, point 16, and ADR 0022, point 16), persistence of any recommendation,
and a pricing or pacing engine that would decide a business action on its own.

## Input boundary

The ONLY inputs are a persisted `Decision` and its latest `DecisionObservation` - exactly Gate 11's
own already-decided memory, read once, in-process, from wherever the API layer already had both
objects in scope (`decision_detail_of()`). The engine never:

- reads a raw `Booking`/`Invoice`/`LaborEntry`/snapshot row,
- opens or is given a database session,
- calls `RevenueDecisionService`/`CostDecisionService`/`LaborDecisionService`/
  `OtaDependencyService`/`DemandForecastService`/`PriorityService`/`BookingExpectedService`,
- reads `evidence_payload` (only `facts_payload`),
- reads a clock, a random source, or any other module's live state.

`test_recommendation_scope.py` proves all of this by AST-walking every identifier and import in
the package, not by convention.

## Recommendation status

A closed, three-value `RecommendationStatus`:

| Status | When |
| --- | --- |
| `AVAILABLE` | `latest_observation.source_status == TRIGGERED` AND every fact the matching rule needs is present and well-formed |
| `NOT_AVAILABLE` | `latest_observation.source_status != TRIGGERED` (CLEAR / INSUFFICIENT_DATA / SUPPRESSED_LOW_CONFIDENCE / NOT_APPLICABLE) - regardless of the Decision's own `status` |
| `INSUFFICIENT_CONTEXT` | TRIGGERED, but a required fact is missing, wrong-typed, or not Decimal-parseable (or `confidence_score` is itself `None`) |

`NOT_AVAILABLE` is deliberately independent of `Decision.status`: an OPEN Decision whose CURRENT
observation is `INSUFFICIENT_DATA` (Gate 11's own Day-2 golden scenario) has nothing actionable
right now, even though the Decision itself has not resolved.

## Action model

An `Action` is a frozen dataclass: `action_code` (closed `ActionCode` enum), `category`
(`ActionCategory`), `scope` (`ActionScope`), `supporting_facts` (`dict[str, str]` - canonical
Decimal-as-string or `"True"`/`"False"`, never raw JSON), `risk_notes` (a tuple of closed
`RiskNote`s, possibly empty), and `requires_human_review: bool = True`.

A `RecommendationResult` carries at most one `primary_action` plus up to
`MAX_SUPPORTING_CHECKS = 2` `supporting_checks`, in a fixed, deterministic order per rule - never
more, never reordered between two calls on the same input.

### Primary actions, one per decision type

| Decision type | Primary action | Category | Risk notes |
| --- | --- | --- | --- |
| `REV_PICKUP_LOW` | `REVIEW_PRICING_AND_AVAILABILITY` | `REVIEW_PRICING` | pricing may affect revenue |
| `REV_OCCUPANCY_RISK` | `REVIEW_DEMAND_POSITIONING` | `REVIEW_AVAILABILITY` | pricing may affect revenue |
| `REV_OTA_DEPENDENCY` | `REVIEW_DISTRIBUTION_MIX` | `REVIEW_DISTRIBUTION` | distribution change may affect visibility |
| `COST_CPOR_ANOMALY` | `REVIEW_COST_DRIVERS` | `REVIEW_COST_DRIVERS` | none (a data-verification step; no closed risk note fits) |
| `LABOR_OVERSTAFFING` | `REVIEW_STAFFING_PLAN` | `REVIEW_STAFFING` | staffing change may affect service |

Every primary action names a REVIEW action, never the business decision itself: never "lower the
price", "apply a discount", "close this OTA channel", "change supplier" or "reduce staff" -
enforced both structurally (the closed `ActionCode` set a rule can ever produce) and by scanning
the rendered template keys for the specific forbidden phrases (`test_recommendation_action_safety.py`).

### Supporting checks

Each rule reads up to two additional OPTIONAL facts and, only when present, appends a
`VERIFY_DATA`-category supporting check (e.g. pickup's `CHECK_CHANNEL_VISIBILITY` gated on
`rooms_condition`, `CHECK_BOOKING_RESTRICTIONS` gated on `missing_rooms`). Never invented, never
guessed - a missing optional fact simply means one fewer supporting check, not a placeholder.

### `requires_human_review`

`True`, unconditionally, on every `Action` and on the top-level `RecommendationResponse`. No field
named `auto_apply`, `execute` or `approved_by_default` exists anywhere in
`app/modules/recommendations/types.py` - checked structurally via `dataclasses.fields()`, not
just by the absence of a UI control.

## No business recalculation

Every delta, expected value, threshold comparison and the `economic_proxy` were already decided by
a detector and persisted by Gate 11. A rule only checks whether the exact fact it needs is present
and well-typed, then copies it - via `canonical_text()`, the same convention Gate 10/11 already
use - into `supporting_facts`. Confidence is copied the same way, verbatim, from
`observation.confidence_score`; the engine never recomputes it, never reads `priority_rank`/
`priority_score`/`impact_score`/`urgency_score`/`actionability_score` for anything (mutating
`priority_rank` between two calls produces an identical fingerprint and primary action -
`test_recommendation_engine.py::test_priority_is_not_recalculated_the_engine_never_reads_the_score_fields`).

## Missing or malformed context

Every rule in `rules.py` reads facts through three small helpers:

- `_text(facts, key)` - a Decimal-parseable string, or `None` for anything else (missing, wrong
  type, or not a valid `Decimal`).
- `_int(facts, key)` - a real `int` (explicitly never a `bool`, which is an `int` subclass in
  Python), or `None`.
- `_bool(facts, key)` - a real `bool`, or `None`.

If either fact a rule's primary action needs comes back `None`, the whole rule returns `None` and
the engine reports `INSUFFICIENT_CONTEXT` - never a partial, half-built action.

In practice, a REAL detector-produced `facts_payload` is always well-formed for a TRIGGERED
observation (the whitelist in `app/api/v1/decisions/serializers.py`/
`app/modules/decisions/serialization.py` is enforced at evaluation time, and the two are
key-for-key audited to match what each rule reads). `INSUFFICIENT_CONTEXT` exists as a defensive
boundary, exhaustively exercised at the pure-engine level
(`test_recommendation_missing_context.py`) - and, honestly, reachable through the real HTTP
endpoint today only via Gate 11's own MINIMAL `revenue_evaluation()` test fixture (built for
Decision LIFECYCLE testing, not numeric-fact completeness), never through a genuinely
detector-real pipeline run.

## Source status semantics, precisely

`NOT_AVAILABLE` is driven ONLY by `latest_observation.source_status`, never by
`decision.status`. Concretely:

- An OPEN Decision with a TRIGGERED latest observation -> `AVAILABLE` (or `INSUFFICIENT_CONTEXT`).
- An OPEN Decision with an INSUFFICIENT_DATA/SUPPRESSED_LOW_CONFIDENCE/NOT_APPLICABLE latest
  observation -> `NOT_AVAILABLE` (the Decision has not resolved, but there is nothing to act on
  right now).
- A RESOLVED Decision (latest observation CLEAR) -> `NOT_AVAILABLE`.
- A REOPENED Decision (latest observation TRIGGERED again, after a prior CLEAR) -> `AVAILABLE`,
  built from THAT (latest) observation's own facts only - never a stale prior TRIGGERED
  observation's facts, even if they happen to carry the same numbers
  (`test_recommendation_golden.py::test_golden_reopened_recommendation_reflects_latest_observation_only`).

## Fingerprint & versioning

A deterministic SHA-256, built exactly like Gate 10's own `priority/fingerprint.py`:

    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    -> hashlib.sha256(...).hexdigest()

`payload` includes: `recommendation_version` (`RECOMMENDATION_ENGINE_VERSION`, currently
`"recommendation-engine-v1"`), `decision_type`, the Decision's own semantic identity
(`identity_version`/`identity_key` - never `decision.id`, a DB-generated UUID), the observation's
own semantic `source_evaluation_fingerprint` (never `observation.id`), `status`, every action code
in order with its canonicalised `supporting_facts` and `risk_notes`, and `confidence`. Excludes
anything DB-generated or wall-clock - no timestamp, no random source - so the same two persisted
rows always fingerprint identically, and a version bump (a future rule change) always produces a
different one.

## API exposure

Additive only, on the existing Decision Detail response:

```json
{
  "...": "... every existing DecisionDetailResponse field, unchanged ...",
  "recommendation": {
    "status": "AVAILABLE",
    "version": "recommendation-engine-v1",
    "fingerprint": "…64 hex chars…",
    "primary_action": {
      "action_code": "REVIEW_PRICING_AND_AVAILABILITY",
      "title_key": "recommendation.action.REVIEW_PRICING_AND_AVAILABILITY.title",
      "description_key": "recommendation.action.REVIEW_PRICING_AND_AVAILABILITY.description",
      "category": "REVIEW_PRICING",
      "scope": "STAY_DATE",
      "supporting_facts": {"actual_pickup": "3", "expected_pickup": "7.50"},
      "risk_notes": ["PRICING_CHANGE_MAY_AFFECT_REVENUE"],
      "requires_human_review": true
    },
    "supporting_checks": [],
    "confidence": "81.23",
    "requires_human_review": true
  }
}
```

`RecommendationResponse` deliberately omits the internal `RecommendationResult`'s own bookkeeping
fields (`generated_from_observation_id`, `generated_from_evaluation_fingerprint`, `reason_codes`) -
they exist for potential future audit use, not because a consumer of the recommendation needs
them today. No new query parameter exists to request, suppress or control it - it is unconditional,
computed fresh on every request (`test_decision_api_scope.py`'s OpenAPI-level checks confirm the
exact same 4-path set and the same 2-parameter detail route as Gate 12).

## Persistence

**None.** No table, no column, no Alembic revision. `test_recommendation_readonly.py` proves this
three ways: a direct `pg_tables` query finds nothing matching `%recommendation%`; a real GET,
repeated 5 times, leaves every Decision Layer table's row count and every `Decision.updated_at`
unchanged; and the same GET, called twice, returns byte-identical `recommendation` JSON both
times. Recomputed fresh, every request, from whatever the latest persisted Observation says right
now.

## Privacy

The engine reads facts through a fixed, tiny, hand-enumerated set of keys (`rules.py`'s own
`_text`/`_int`/`_bool` call sites) - none of them free-text-capable, none of them a guest, employee
or supplier identity field. `test_recommendation_privacy.py` checks this two ways: an AST scan of
every fact key a rule could ever read against an explicit safe allow-list, and a live HTTP
sentinel-injection test (reusing `test_decision_api_privacy.py`'s own technique) proving no PII
sentinel ever reaches the `recommendation` block of a real response.

## Performance

The engine takes no session and issues zero SQL - proven directly by wrapping a raw call to
`RecommendationEngine().evaluate()` in a SQL-statement listener on a real connection and asserting
zero statements captured, for all five decision types. The Decision Detail endpoint's own overall
query-count bound is unchanged from Gate 12 (`test_recommendation_performance.py` asserts the same
`<= 5` bound `test_decision_api_performance.py` already established, now with the recommendation
attached) - Gate 16 added no query of its own.

## Golden scenarios

`test_recommendation_golden.py` drives the real pipeline end to end (no hand-built `Decision`/
`DecisionObservation`):

- All 5 decision types, real Day-1 TRIGGERED evaluations -> `AVAILABLE`, correct primary action
  code, confidence copied verbatim from the real persisted row.
- A real CLEAR re-evaluation (the dedicated OTA lifecycle source's genuine Day-2 result) ->
  `NOT_AVAILABLE`.
- A real INSUFFICIENT_DATA re-evaluation (a new snapshot with no lead-7 historical curves) on an
  OPEN Decision -> `NOT_AVAILABLE`, even though the Decision itself stays OPEN.
- OPENED (Day 1) -> RESOLVED (Day 2) -> REOPENED (Day 3), the real `LifecycleOtaWorld` -> `AVAILABLE`
  again after Day 3, built from Day 3's own real facts.
- A fingerprint independently recomputed by hand from the ground-truth DB row (stdlib
  `json.dumps`/`hashlib.sha256` only, never calling `recommendation_fingerprint()` itself) matches
  the API's own reported value.

`SUPPRESSED_LOW_CONFIDENCE` and `NOT_APPLICABLE` are deliberately covered only at the pure-engine
level (`test_recommendation_engine.py`) - no golden fixture in this codebase drives a real decision
into either status on demand, and building one purely to re-prove a branch already proven
pure-unit would not add independent evidence.

## Limitations (intentional, documented debt)

- No Recommendation UI yet - `recommendation` is available on the API today, but no frontend page
  renders it (ADR 0021, point 16; ADR 0022, point 16). When it is built, it is a new, additive
  section on Gate 15's own Decision Detail page.
- No recommendation history/audit persistence - the fingerprint already makes this trivial to add
  later (same input -> same fingerprint -> a natural primary key) without needing to design that
  now (ADR 0022, "Alternatives considered").
- A sixth decision type requires a new rule in `rules.py` and a new `_RULE_BY_TYPE` entry in
  `engine.py` - there is no generic fallback a new type could silently fall into
  (`UnsupportedDecisionTypeError` fails loudly if one is forgotten).
- `INSUFFICIENT_CONTEXT` is not reachable through a genuinely detector-real pipeline run today
  (see "Missing or malformed context" above) - it remains defensive, not dead, code.

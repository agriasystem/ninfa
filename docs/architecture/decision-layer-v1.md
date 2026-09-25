# NINFA — Decision Persistence, Lifecycle and Memory v1 (Gate 11)

Scope: turns the Priority Engine's ranked, non-persistent signals into a **persistent Decision
identity** with an **OPEN/RESOLVED lifecycle** and an **immutable observation history**. It answers
one question the previous ten gates deliberately left open: *is this morning's TRIGGERED signal
the SAME operational problem NINFA already knows about, or a new one?*

    ORDERED SIGNALS -> DECISION IDENTITY -> PERSISTENCE -> LIFECYCLE -> MEMORY

Code: `services/api/app/modules/decisions/` (`models`, `types`, `identity`, `fingerprint`,
`serialization`, `lifecycle`, `repository`, `service`, `errors`, `precision`) and
`services/api/app/modules/decision_memory/` (`service`, the internal read side). Migration:
`0009_decision_layer` (three tables: `decision_runs`, `decisions`, `decision_observations`; the
head before this gate was `0008_labor_ingestion` — Gates 5, 7, 9 and 10 added none). Versions:
`decision-layer-v1`, `decision-identity-v1`, `decision-lifecycle-v1`, `decision-memory-v1`.
Decisions: [ADR 0017](adr/0017-decision-persistence-lifecycle-memory-v1.md).

This gate adds **no** recommendation, generated prose, AI/ML, business API, UI, notification or
scheduler, and **no** change to any detector or to the Priority Engine's own formula: it reads
`PriorityContext`, `PriorityRankingResult` and the five detectors' own evaluations, exactly as
Gate 10 produced them, and persists facts about them.

## Signal vs Decision

A detector evaluation (Gate 5/7/8/9's own `RevenueDecisionEvaluation` / `CostDecisionEvaluation` /
`LaborDecisionEvaluation` / `OtaDependencyEvaluation`) is an **observation**: what a detector
concluded, once, from the data it was given at one as-of date. It is not re-decided here and never
recomputed.

A **Decision** is the persistent identity of the *operational problem itself*, recognised across
many observations over time. Re-running the same pipeline tomorrow on the same stay date, the same
OTA source or the same cost category must **not** create a new Decision merely because the as-of
date, the snapshot id, the priority score, the confidence or the rank changed — none of those are
part of what makes two mornings' signals "the same problem". This is the single governing
principle of this gate; every rule below exists to enforce it.

## Decision identity (`decision-identity-v1`)

`app.modules.decisions.identity.build_identity(evaluation)` returns a `DecisionIdentity`: the
`decision_type`, the tenant scope, a `identity_key` (a 64-char lowercase SHA-256) and the
`identity_payload` it was hashed from (kept verbatim, for audit and for a fail-closed collision
check). The payload always includes `identity_version`, `decision_type`, `workspace_id` and
`property_id`, plus detector-specific dimensions below. It is deliberately **not**
`AdaptedSignal.source_target_key` (Gate 10's own key, built for ranking, never for identity): a
target key can carry a snapshot id, an as-of date or a rolling window boundary that changes every
morning the same problem is re-observed — using it as identity would open a new Decision every
day. `raw_target_key` (in the same module) reproduces that key's *shape*, for every status, purely
for audit on an Observation row; it is never identity and never persisted as one.

### Identity per detector

| Decision type | Identity dimensions | Deliberately excluded |
| --- | --- | --- |
| `REV_PICKUP_LOW` | workspace, property, booking data source, `stay_date` | `snapshot_local_date`, `target_snapshot_id`, the evaluation fingerprint |
| `REV_OCCUPANCY_RISK` | workspace, property, booking data source, `stay_date` | same as above — and note: pickup and occupancy on the SAME stay date are two DIFFERENT identities (`decision_type` is part of the hashed payload) |
| `REV_OTA_DEPENDENCY` | workspace, property, booking data source | `as_of_local_date`, `window_start`, `window_end` — the 30-day window shifts every morning while the identity stays fixed; STRUCTURAL and RISING are two possible *reasons*/states of the SAME identity, never two Decisions |
| `COST_CPOR_ANOMALY` | workspace, property, booking data source, `target_period_start` (the month), `cost_category`, `currency` | `target_period_end` (redundant: the month alone determines it) |
| `LABOR_OVERSTAFFING` | workspace, property, booking data source, labor data source, `work_date`, `labor_category` | the labor snapshot date, the target's own as-of date |

Two dimensions deserve their own explanation, because the prompt's own template could have been
followed blindly and would have been wrong:

* **`COST_CPOR_ANOMALY` includes a booking data source.** This is *not* inventing a source
  dimension for cost data — `docs/architecture/cost-cpor-anomaly-v1.md` is explicit that Gate 6/7
  aggregate the canonical invoice lines **cross-source**, by design, and that identity must not
  contradict. But the same document also says, in "The target": *"A target is identified by
  workspace, property, **booking data source**, calendar month, cost category and currency"* — the
  booking source is the occupancy denominator's stated provenance, a real, load-bearing parameter
  of `CostDecisionService.evaluate_cpor_anomaly()` (different booking source, different occupied
  room nights, different CPOR, for the exact same month/category/currency). It genuinely
  distinguishes two different CPOR targets and belongs in the identity for that reason, not
  because "cost has a source" in general.
* **`LABOR_OVERSTAFFING` includes the booking data source.** `docs/architecture/
  labor-overstaffing-v1.md`, "Demand forecast: reused, not rebuilt", shows the target's expected
  room demand comes from the SAME booking data source's own snapshot chain; a different booking
  source changes the forecast the detector compares scheduled hours against, so it is a real
  dimension of the target, not decoration.

### Hash (`identity_hash`, `canonical_identity_json`)

SHA-256 of the payload's canonical JSON (`sort_keys=True`, no whitespace, ASCII): field ordering
never changes the hash, and the same logical dimensions always hash the same. If an existing
Decision's *stored* `identity_payload` ever disagrees with the freshly-built one despite sharing an
`identity_key`, `verify_identity()` fails closed with `DECISION_IDENTITY_HASH_COLLISION` — a hash
is only useful if a collision, however unlikely, is never silently trusted.

## `DecisionRun`: why it exists

One append-only row per Decision Layer sync of one workspace/property/as-of/logical input. It
exists for four reasons: it makes a sync **auditable** (every Observation of a run points back to
it); it is what makes an **exact replay idempotent** (the unique key below); it lets two
*different* datasets evaluated on the *same* as-of date coexist as two runs, without overwriting
history; and it records **run-level counts** (`evaluation_count`, `triggered_count`, ...,
`duplicate_input_count`) even when nothing was TRIGGERED — a run with zero TRIGGERED evaluations is
a perfectly valid, informative row, never translated into a fabricated "all clear" Decision.

`run_input_fingerprint` (SHA-256, `app.modules.decisions.fingerprint`) hashes: the decision layer
version, workspace, property, as-of date, the **sorted, deduplicated set** of kept source-evaluation
fingerprints, the Priority ranking's own fingerprint, the five status counts and
`duplicate_input_count`. The caller's own input order never changes it. Unique key:
`(workspace_id, property_id, as_of_local_date, input_fingerprint)` — an exact replay finds the
existing row and returns it, writing nothing; the same as-of date with a genuinely different
dataset creates a new row.

`run_sequence` is a DB-generated (`GENERATED ALWAYS AS IDENTITY`), strictly increasing integer,
used **only** to order `decision_observations` history deterministically when two runs share an
as-of date (see "Memory order" below) — never business logic, never exposed outside this module.
It exists because `created_at` alone cannot break that tie: PostgreSQL's `now()` is fixed for the
whole transaction block, not per statement, so two runs synced back to back inside one transaction
(exactly what this gate's own test suite does) would otherwise share an identical `created_at`.

## `Decision`: identity plus CURRENT lifecycle state

Deliberately thin: `decision_type`, `identity_version`, `identity_key`, `identity_payload` (never
mutated after creation) plus `status`, `first_seen_local_date`, `last_seen_local_date`,
`last_evaluated_local_date`, `resolved_local_date`, `episode_count`,
`triggered_observation_count` (mutated in place by the lifecycle rules). It never duplicates the
facts of its latest Observation — those live only in `decision_observations`; a Decision Detail
view (a later gate) would join the two, never read facts off `Decision` itself.

`status` is `OPEN | RESOLVED` — V1 has no `SUPPRESSED`, `DISMISSED` or `ARCHIVED` state; those
belong to a future business-facing gate. Unique key:
`(workspace_id, property_id, decision_type, identity_key)`.

## `DecisionObservation`: immutable memory

One row per (Decision, DecisionRun): what NINFA knew about this Decision, in this run. Always
carries `source_status` (the detector's own status, never reinterpreted), `lifecycle_transition`
(what this Observation did, decided by the lifecycle rules — never recomputed from the Decision's
current row), the source evaluation's own fingerprint and a `raw_target_key`-shaped
`source_target_key` (audit only, never identity), `confidence_score` (always populated — every
evaluation carries its own, even an early-exit `0.00`), and two explicit JSONB payloads,
`facts_payload`/`evidence_payload` (see "Serialization" below).

When `source_status = TRIGGERED`, the row **also** carries the exact Priority snapshot for that
day: `priority_candidate_fingerprint`, `priority_rank`, `impact_score`, `urgency_score`,
`actionability_score`, `priority_score` — copied from the ONE `PriorityCandidate` Gate 10 already
produced for this evaluation, **never recomputed**. For any other status every one of those five
fields is `NULL` (a database `CHECK` enforces the correlation both ways). `impact_score` and
`priority_score` are stored as **unconstrained** `NUMERIC` (no fixed precision/scale): they are
computed in Gate 10's own dedicated 50-significant-digit `Decimal` context, and a threshold-
progress ratio is not always terminating at two decimals — a fixed scale would silently truncate
the exact value this table exists to keep.

`observation_fingerprint` (SHA-256) hashes: the memory version, the Decision's `identity_key`, the
run's own `input_fingerprint`, the as-of date, `source_status`, `lifecycle_transition`, the source
evaluation's fingerprint, `source_target_key`, the priority fields (when present), the reason
codes and the two canonical payloads. It never includes a database id, `created_at` or a
display-only figure — the function's own signature has no such parameter at all.

## Lifecycle (`decision-lifecycle-v1`)

`app.modules.decisions.lifecycle.apply_lifecycle()` is a small, pure function of (does a Decision
already exist, its current status, the new source status) → `LifecycleOutcome`. No I/O, no
session, testable as one table:

| Existing | New status | Result | Transition |
| --- | --- | --- | --- |
| none | TRIGGERED | create, OPEN, `episode_count=1`, `triggered_observation_count=1` | `OPENED` |
| none | CLEAR / INSUFFICIENT_DATA / NOT_APPLICABLE / SUPPRESSED_LOW_CONFIDENCE | nothing created, nothing recorded | *(none)* |
| OPEN | TRIGGERED | same id, `last_seen`/`last_evaluated` = as-of, `triggered_observation_count += 1` | `OBSERVED` |
| OPEN | CLEAR | `status = RESOLVED`, `resolved_local_date` = as-of, `last_evaluated` = as-of, **`last_seen` unchanged** | `RESOLVED` |
| OPEN | INSUFFICIENT_DATA / SUPPRESSED_LOW_CONFIDENCE / NOT_APPLICABLE | only `last_evaluated` advances | `NO_STATE_CHANGE` |
| RESOLVED | TRIGGERED | same id, `status = OPEN`, `resolved_local_date = NULL`, `last_seen`/`last_evaluated` = as-of, `episode_count += 1`, `triggered_observation_count += 1` | `REOPENED` |
| RESOLVED | anything else | only `last_evaluated` advances | `NO_STATE_CHANGE` |

`last_seen_local_date` means *the last time this was actually TRIGGERED* — it is why Rule 3
(RESOLVED) deliberately leaves it alone: a Decision resolved today was last **seen** the day it was
last TRIGGERED, not today. `last_evaluated_local_date` means *the last time this identity was
looked at, whatever it said* — it always advances when the Decision is touched at all.

### Only explicit CLEAR resolves

This is the one rule the whole rest of the gate protects: **no other status, and no absence of a
status, ever resolves an OPEN Decision.**

* **Absence is not CLEAR.** If a run's evaluations simply do not mention an OPEN Decision's
  identity, nothing happens to it — no mutation, no Observation, no re-evaluation of any kind. This
  is not a special case in the code: it falls out of the design by construction (the sync loop only
  ever touches identities that are actually present in this run's evaluations), and is tested
  explicitly (`test_missing_evaluation_never_resolves_an_open_decision`, and the golden scenario's
  own Day 2, case D).
* **`INSUFFICIENT_DATA` never resolves.** Not knowing is not the same as knowing it is fine.
* **`SUPPRESSED_LOW_CONFIDENCE` never resolves.** The detector itself said "the numeric condition
  still holds, I am just not confident enough to show it" — the opposite of evidence the problem
  went away.
* **`NOT_APPLICABLE` never resolves.** It means the rule has no meaning in the current context
  (e.g. a cost category is `OTHER`), which is not proof the underlying problem was fixed.

### Reopen semantics

A RESOLVED Decision that TRIGGERS again is **reopened, never recreated**: the same
`identity_key`/`id`, `resolved_local_date` cleared, `status` back to `OPEN`,
`episode_count` incremented. `first_seen_local_date` **never changes** after creation — it always
means the first morning this exact operational problem was ever seen, however many times it has
opened and closed since. `episode_count` counts how many separate OPEN spans the Decision has had;
`triggered_observation_count` counts every TRIGGERED Observation ever recorded for it, across every
episode.

### Out-of-order runs

If a run's as-of date is **strictly before** an existing Decision's own `last_evaluated_local_date`,
the WHOLE sync is rejected: `DECISION_OUT_OF_ORDER_RUN`. History is never rewritten. The SAME as-of
date with a genuinely different input is explicitly allowed (creates a new `DecisionRun`,
Observations follow the real transactional order the runs happened in) — the rule is about the
past being reopened, not about same-day reprocessing. Backtesting a historical period needs a
separate storage/context in a future gate; this one only ever moves forward.

## Priority/source consistency

Before writing anything, `DecisionService.sync()` verifies the `PriorityContext`/
`PriorityRankingResult`/evaluations it was given are the coherent output of ONE real
`PriorityService.rank()` call, never trusting them blindly:

* the ranking's own workspace/property/as-of must match the context exactly;
* every evaluation must belong to the context's workspace/property;
* every TRIGGERED evaluation (after this gate's OWN identity-level dedup) must map to **exactly
  one** `PriorityCandidate` by `source_evaluation_fingerprint`, and every candidate must map back
  to exactly one TRIGGERED evaluation — never a partial match, never chosen arbitrarily;
* the ranking's four exclusion counts must match the CLEAR/INSUFFICIENT_DATA/NOT_APPLICABLE/
  SUPPRESSED_LOW_CONFIDENCE tally of the (deduplicated) evaluations given.

Any mismatch raises `DECISION_PRIORITY_INPUT_MISMATCH` and rolls back the whole sync.

### Duplicates and conflicts (one level above Gate 10's own)

Within one run, evaluations are grouped by **Decision identity** (not `source_target_key`, which is
Priority's own grouping key one level below): the same identity seen twice with the SAME
`calculation_fingerprint` is a duplicate (counted in `duplicate_input_count`, the first copy kept);
the SAME identity with a DIFFERENT fingerprint is `DECISION_CONFLICTING_SOURCE_EVALUATION` — never
resolved arbitrarily, exactly like Gate 10's own duplicate/conflict rule, applied at the identity
level instead of the target-key level.

## Serialization and data minimization (`decision-memory-v1`)

`app.modules.decisions.serialization` has **one explicit function per detector**
(`serialize_revenue`/`serialize_ota`/`serialize_cost`/`serialize_labor`), each returning
`(facts_payload, evidence_payload)`. None of them calls `dataclasses.asdict()`, `__dict__`,
`vars()`, or a detector's own `payload()`/`canonical_payload()`: every field is named by hand. This
is deliberate, for three reasons: **data minimization** (only what a Decision Detail would ever
need to show is kept, forever); **schema stability** (a detector's own evaluation shape can evolve
without silently changing what gets persisted here); and an explicit, auditable, permanent boundary
against PII — guest name/email/phone, employee identity, tax code, address, IBAN, medical notes and
free-text supplier names **never appear** in this module's source, checked by an AST scan of its
own file (`test_decision_serialization.py`), not merely by inspecting one run's fixture data.

`facts_payload` is *what* the problem is (the target and the numbers the rule compared);
`evidence_payload` is *why* NINFA trusts it (provenance, sample size, confidence components, an
optional economic proxy). Reason codes are never duplicated into either payload: they are their own
column, read once from `evaluation.reason_codes`. Every `Decimal` is serialised with the SAME
`canonical_text` Gate 10 already uses (re-exported, not copied); every UUID becomes a plain string;
every date becomes an ISO string — the whole payload is `json.dumps`-safe.

## Decision Memory (read side)

`app.modules.decision_memory.service.DecisionMemoryService` is the internal read side: no public
API, no UI. `list_open_decisions(property_id)` (OPEN only, a reopened Decision included, one
set-based query), `get_decision(decision_id)` (tenant-scoped: another workspace's Decision does not
exist for this call), `get_history(decision_id)` (every Observation, chronological), and
`find_by_identity(property_id, decision_type, identity_key)`.

### Memory order

History is ordered `(as_of_local_date, DecisionRun.run_sequence, DecisionObservation.id)` — the
as-of date first, then the run's own DB-generated sequence (a genuine tie-break for two runs that
share an as-of date), the observation id only as a final, arbitrary tie-break that should never
actually matter in practice. One query, a join on `decision_run_id`, never one query per
Observation.

### What history preserves

Every Observation is immutable and permanent: a later Observation never overwrites an earlier one's
facts, priority rank or confidence. A Decision that ranked #1 on Monday and #4 on Tuesday keeps
BOTH ranks, one per Observation — `Decision` itself never stores a rank at all. The Priority Engine
recomputing tomorrow's ranking never touches yesterday's Observation.

## Idempotency, atomicity, concurrency

**Idempotency.** The exact same (workspace, property, as-of, logical input) always resolves to the
SAME `DecisionRun` (its own unique key) and produces zero new rows on replay — checked *inside* the
advisory-locked section, so two literally simultaneous identical requests cannot both decide "no
run exists yet" and both try to create one (the run's own unique constraint is the last line of
defence either way).

**Atomicity.** `DecisionService.sync()` owns its transaction, exactly like `LaborImportService`:
validate (pure Python) → acquire the lock → check idempotency → load existing Decisions
(set-based) → out-of-order check → insert the run → apply the lifecycle rules → bulk-insert
Observations → commit. Any exception at any point rolls back the whole call — a conflicting
identity, a priority mismatch or a database constraint violation midway through a large batch
leaves **zero** trace of that sync, including a Decision that would otherwise have been created or
updated cleanly.

**Concurrency.** `lock_decision_layer(session, workspace_id, property_id)`
(`app.db.locks`, the same `pg_advisory_xact_lock` pattern as `lock_data_source`/
`lock_supplier_registry`) serialises two concurrent syncs of the SAME workspace/property: one
creates, the other observes the identical run it just committed as an idempotent replay — verified
with REAL commits and two real threads in `test_decision_real_commits.py` (every other test in this
gate runs inside one rolled-back transaction, which cannot exercise genuine concurrency). The
unique keys on `decisions` and `decision_runs` remain the last line of defence regardless.

## Performance

Existing Decisions for a whole batch of identities are loaded with **one** set-based query
(`tuple_(decision_type, identity_key).in_(...)`), never a `SELECT` per evaluation — the query count
stays flat whether a run touches 5 identities or 50. Observation inserts are one bulk `INSERT`
through Core, never a loop of ORM adds. `get_history()` is one query with a join, never one per
Observation.

## Tenant isolation

Every table carries `workspace_id`, with composite foreign keys the same way every tenant-owned
table in this schema does: `decision_runs`/`decisions` → `(workspace_id, property_id) →
properties`; `decision_observations` → `(workspace_id, decision_id) → decisions`,
`(workspace_id, decision_run_id) → decision_runs` and `(workspace_id, property_id) → properties`.
`DecisionRepository`/`DecisionMemoryService` take a `TenantContext` at construction and never expose
a method that accepts a workspace argument; a Decision of another workspace is indistinguishable
from a missing one.

## Limitations (intentional, V1)

* **Resolution policy is fixed and simple**: only an explicit CLEAR resolves. A future gate may
  want a policy (e.g. "N consecutive non-TRIGGERED days also resolves it") — that is a new,
  explicitly versioned decision, never a silent change to this one.
* **No backtesting.** Out-of-order rejection means this storage can only ever move forward in
  as-of time for one workspace/property; replaying history for model development needs a separate
  context in a later gate.
* **No Decision business API, UI, recommendation, notification or scheduler.** `DecisionService`/
  `DecisionMemoryService` are orchestration-callable, not scheduled or exposed; a future gate
  builds the authenticated API and the UI on top of `DecisionMemoryService`'s read methods,
  unchanged.
* **`impact_score`/`priority_score` are stored at whatever precision Gate 10's 50-digit context
  produced**, via an unconstrained `NUMERIC` column — a deliberate choice to never truncate the
  exact value the fingerprint hashed, at the cost of a less predictable column width than the rest
  of this schema's money/percentage columns.
* **A Priority Engine formula or weight change is out of scope here** (Gate 10 owns it entirely);
  this gate only ever reads whatever `PriorityCandidate`/`PriorityRankingResult` it is given.

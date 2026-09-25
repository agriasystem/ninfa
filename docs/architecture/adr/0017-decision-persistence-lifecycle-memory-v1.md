# 0017 — Decision Persistence, Lifecycle and Memory V1: cross-day identity, explicit resolution, immutable history

**Status:** accepted (Gate 11)

## Context
Gates 5, 7, 8 and 9 gave NINFA five detectors that each produce a typed, immutable, non-persisted
evaluation; Gate 10 ranks whatever any of them called `TRIGGERED` on one given morning. Nothing
survives a process: run the pipeline again tomorrow and every signal, ranked or not, is gone. A
hotelier does not experience "this morning's signals" — they experience "the same overbooking risk
I saw yesterday, still not fixed" or "that OTA dependency finally went away". Answering that needs
a persistent notion of *the same problem*, separate from *today's observation of it*, with a
lifecycle simple enough to trust and an audit trail nothing silently overwrites.

## Decision

1. **A detector evaluation is an OBSERVATION; a Decision is the problem's PERSISTENT IDENTITY.**
   `DecisionObservation` rows are append-only memory of what one run knew; `Decision` is the one
   row that says what NINFA currently believes about the problem. Conflating the two — as a naive
   "insert a Decision row per evaluation" design would — makes "is this the same problem as
   yesterday" a query nobody can answer reliably; separating them makes it the ONE thing this gate
   is built to answer correctly.

2. **Identity is a CROSS-DAY concept, deliberately separate from `AdaptedSignal.source_target_key`.**
   Gate 10's own target key exists to group signals for ONE ranking run and legitimately carries a
   snapshot id, an as-of date or a rolling window boundary — exactly what changes every morning the
   SAME problem is re-observed. Reusing it as identity would silently open a new Decision every
   day for a genuinely persistent issue. `decision-identity-v1` is a separate, explicit, hashed
   payload per detector, built from the real, load-bearing dimensions of that detector's own
   target (inspected in its actual code and docs, never assumed from a template).

3. **`REV_OTA_DEPENDENCY`'s identity excludes `as_of_local_date`, `window_start` and `window_end`.**
   The 30-day forward window is inherently rolling; the same underlying OTA-dependency problem is
   evaluated through a different window every morning by construction. STRUCTURAL and RISING are
   two possible *reasons* a share is judged concerning, not two different phenomena — they never
   produce two Decisions for the same booking data source.

4. **`COST_CPOR_ANOMALY`'s identity includes the target month (`target_period_start`).** CPOR is
   defined per calendar month; a new month is, definitionally, a new target with its own cost data
   and its own occupancy denominator — never the same problem continuing. It also includes the
   booking data source, which docs/architecture/cost-cpor-anomaly-v1.md's own "The target" section
   names as part of the real target identity (the occupancy denominator's stated provenance,
   genuinely changing the computed CPOR) — this is NOT the same as inventing a source dimension for
   the cost/invoice side, which stays intentionally cross-source per Gate 6/7's own design.

5. **`Decision` is MUTABLE; `DecisionObservation` and `DecisionRun` are IMMUTABLE.** A Decision's
   `status`/dates/counters are, by definition, the CURRENT state of an ongoing lifecycle — there is
   nothing to preserve by forbidding their update. An Observation is a historical FACT about one
   specific run; allowing it to change would let today quietly rewrite what NINFA believed
   yesterday, defeating the entire purpose of a memory. The same immutability pattern (a `BEFORE
   UPDATE` trigger) already used for `booking_snapshots`, `booking_expected_baselines`,
   `invoices`/`invoice_lines` and `labor_snapshots`/`labor_entries` is reused, unmodified.

6. **`DecisionRun` exists as its own table, not folded into `Decision`/`DecisionObservation`.** It
   is what makes an exact replay idempotent (its own unique key), what makes a sync auditable
   (every Observation points back to the run that produced it), what lets two different datasets
   share an as-of date without overwriting each other, and what records run-level counts (including
   `duplicate_input_count` and a genuine zero-TRIGGERED run) that belong to the SYNC, not to any
   one Decision.

7. **An exact replay is idempotent by construction, not by a special-cased check.** The run's own
   `input_fingerprint` is a canonical hash of the logical input (sorted, deduplicated source
   fingerprints, the Priority ranking's own fingerprint, the five status counts,
   `duplicate_input_count`); the SAME logical input always produces the SAME fingerprint,
   regardless of the caller's own list order, and `find_run()` on that key is checked BEFORE any
   write, inside the same advisory-locked section a write would use — so two literally simultaneous
   identical requests cannot both decide "no run exists yet".

8. **Only an explicit `CLEAR` resolves an OPEN Decision.** This is the single strongest guarantee
   this gate makes, and it is intentionally narrow: `INSUFFICIENT_DATA` means NINFA does not know
   enough to say anything, `SUPPRESSED_LOW_CONFIDENCE` means the detector itself is not confident
   enough to show what it found (the opposite of "it went away"), and `NOT_APPLICABLE` means the
   rule has no meaning right now, not that the underlying problem was fixed. Resolving on any of
   these would produce false "all clear" signals a hotelier could act on wrongly.

9. **Absence never resolves.** If a run's evaluations do not mention an OPEN Decision's identity at
   all, nothing happens to it. This follows from the design rather than being bolted on: the sync
   loop only ever touches identities actually present in the run it was given, so a missing
   evaluation is structurally indistinguishable from "not part of this run" — never confused with
   "checked and found fine". Tested explicitly, and demonstrated in the golden scenario's Day 2.

10. **Reopening reuses the SAME Decision id.** A RESOLVED Decision that TRIGGERS again is not a new
    problem coincidentally sharing an identity — it is evidence the SAME problem came back.
    `episode_count` increments, `resolved_local_date` clears, `first_seen_local_date` never
    changes: the full history of "opened, closed, reopened" stays attached to one row and one id,
    which is what makes a future Decision Detail able to say "this is the third time this
    happened" truthfully.

11. **`episode_count` and `triggered_observation_count` are two different, deliberately separate
    counters.** An episode is one OPEN span (created by `OPENED` or `REOPENED`); a triggered
    observation is any day this identity was actually TRIGGERED, across every episode. Collapsing
    them into one number would make "how many separate times has this problem occurred" and "how
    many mornings has it been TRIGGERED" indistinguishable, and they answer different questions.

12. **The full evaluation is never blindly serialised.** `app.modules.decisions.serialization` has
    one explicit function per detector, naming every field by hand, never
    `asdict()`/`__dict__`/`vars()`/a detector's own `payload()`. This buys three things at once:
    data minimization (only what a Decision Detail would ever show is kept), schema stability (a
    detector's own evaluation shape can change without silently changing what gets persisted
    here), and an explicit, testable PII boundary (checked by an AST scan of the serializer's own
    source, not by inspecting one run's fixture data).

13. **Priority history lives in `DecisionObservation`, never in `Decision`.** A Decision's rank,
    impact, urgency and priority score are answers to "how did Gate 10 see this on THAT particular
    day", which is exactly what an Observation is for; `Decision` itself carries none of them,
    keeping it a pure identity + current-lifecycle-state row and letting every day's ranking be
    preserved side by side, never overwritten by the next morning's re-ranking.

14. **An out-of-order run (an as-of strictly before a Decision's own `last_evaluated_local_date`)
    is rejected wholesale.** This storage is forward-only by design: allowing an earlier as-of to
    mutate a Decision's lifecycle would let a backfill silently rewrite what NINFA already told
    someone. Backtesting a historical period needs its own storage/context in a later gate, never
    a special case bolted onto this one's forward-only guarantee.

15. **No business API, UI, recommendation, notification, scheduler or AI in this gate.**
    `DecisionService`/`DecisionMemoryService` are plain, orchestration-callable classes — the exact
    same posture Gate 5/7/8/9/10 already took for their own services — leaving the authenticated
    API, the UI and any generated explanation to a dedicated future gate, built entirely on
    `DecisionMemoryService`'s read methods without this gate needing to change.

16. **Zero new dependencies.** Identity hashing, fingerprinting and serialization reuse stdlib
    (`hashlib`, `json`) and the SAME `canonical_text`/50-digit-context helpers Gate 5/10 already
    established (re-exported, never copied); persistence reuses SQLAlchemy/Alembic/PostgreSQL
    exactly as every earlier gate did. No rule-DSL library, no event-sourcing framework, no ORM
    extension.

## Alternatives considered
* **Persisting `Decision` as one row per detector evaluation** (an event-sourced log with no
  separate identity row): rejected — it makes "is today's signal the same problem as yesterday's" a
  query over ad-hoc grouping logic instead of a stored fact, and gives every consumer of the data
  its own chance to get cross-day deduplication subtly wrong.
* **Using `AdaptedSignal.source_target_key` as identity** (point 2): rejected outright — it would
  create a new Decision every morning for `REV_OTA_DEPENDENCY`'s rolling window and for any
  detector whose target key carries a snapshot id, defeating the gate's entire purpose.
  Demonstrated explicitly by the golden scenario's cross-day identity case.
- **A generic event-sourcing framework or a rule DSL for the lifecycle table**: rejected, the same
  reasoning as every earlier gate's ADR (0011 point 1, 0016's own "alternatives"): eight explicit
  rules over three states are simpler, more auditable and easier to test exhaustively than an
  abstraction with no second user yet.
* **Resolving on absence** ("if a Decision is not seen in N runs, resolve it"): rejected for V1 —
  it would require tracking a run cadence per identity this gate has no basis for yet, and would
  produce false "resolved" signals whenever a pipeline run simply omits a category temporarily.
  Left as an explicitly future, separately versioned policy.
* **Storing `impact_score`/`priority_score` at a fixed `NUMERIC(p,s)`**: rejected — Gate 10's
  50-significant-digit context can produce a non-terminating ratio at more than 2 decimals; a fixed
  scale would silently truncate the exact value the fingerprint hashes. An unconstrained `NUMERIC`
  was used instead (documented as an intentional limitation).
* **Reusing a detector's own `payload()`/`canonical_payload()` for memory storage**: rejected
  (point 12) — those describe the WHOLE evaluation for that detector's own audit purposes and are
  free to evolve; Decision Memory needs a boundary that does NOT move just because a detector adds
  a field.

## Consequences
* A sixth decision type needs one more explicit identity builder, target-key builder and pair of
  memory serializers — never a change to the five already written.
* `Decision`/`DecisionObservation` give a future Decision Detail (a later gate) everything it needs
  — current state, full history, priority history — without any new persistence work; that gate is
  pure read/presentation on top of `DecisionMemoryService`.
* Backtesting, a resolution policy beyond explicit CLEAR, a Decision business API, a UI and any
  recommendation are all explicitly deferred, each to its own future, separately versioned gate.
* The lifecycle's eight rules are exhaustively enumerated and individually testable
  (`app.modules.decisions.lifecycle.apply_lifecycle`), so a future ninth rule (if ever needed) is
  one more row in one small table, not a rewrite.

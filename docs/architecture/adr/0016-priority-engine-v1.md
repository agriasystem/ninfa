# 0016 — Priority Engine V1: normalized severity, triggered-only, five explicit adapters

**Status:** accepted (Gate 10)

## Context
Gates 5, 7, 8 and 9 gave NINFA five independent detectors, each producing a typed, immutable
evaluation in its own vocabulary (percentage points, rooms, hours, a CPOR ratio, an OTA share).
None of them can be compared to another as it stands: a 10-point occupancy gap and an 8-hour labor
excess are not the same kind of number. The next question a hotelier actually asks is not "is
REV_PICKUP_LOW wrong or right" (the detector already answered that) but "of everything that fired
this morning, what do I look at first" — and answering it must not re-open any detector's own
verdict, must not invent a fake common currency, and must not become a generic rules engine before
five detectors even exist to learn from.

## Decision
1. **Priority is a separate layer, never a detector concern.** No `priority_score` field was added
   to `RevenueDecisionEvaluation`/`OtaDependencyEvaluation`/`CostDecisionEvaluation`/
   `LaborDecisionEvaluation`, and no detector's threshold, confidence, fingerprint, reason code or
   status changed. `PriorityService` reads finished evaluations; it never calls a detector, a
   repository or the database (zero SQL, zero `Session`, zero `TenantContext` parameter). This
   keeps "detect" and "order" as two things that can each change without touching the other, and
   makes the engine testable with plain Python objects, no PostgreSQL required.
2. **Only `TRIGGERED` becomes a candidate.** `CLEAR`, `INSUFFICIENT_DATA`, `NOT_APPLICABLE` and
   `SUPPRESSED_LOW_CONFIDENCE` are excluded and counted, never scored and never appended at the
   bottom with a zero. A detector that decided it was not confident enough to show something
   (`SUPPRESSED_LOW_CONFIDENCE`) is never "resuscitated" by a downstream layer just because its
   raw numbers look large: the whole point of that status is that NINFA does not trust it yet.
3. **Impact V1 is NORMALIZED OPERATIONAL SEVERITY, never a currency amount.** Not every detector
   has an economic proxy (OTA's optional revenue figure is evidence only); the four that do use
   different currencies and would silently rank whichever property's local currency is larger;
   and several of the proxies are themselves gross exposure figures, never a loss — scoring on
   them would smuggle a false economic precision into a cross-domain ranking that has no business
   claiming one.
4. **Economic proxies never enter the score and are never compared across currencies.** They ride
   along as plain evidence (`economic_proxy_exact`/`_currency`/`_label`) with the same "gross
   exposure, never a saving" framing their own detector already gave them. No FX conversion is
   ever attempted; `REV_PICKUP_LOW`/`REV_OCCUPANCY_RISK`/`REV_OTA_DEPENDENCY` carry no currency
   string on their own evaluation at all (only `Property.currency` does, and this engine never
   queries a repository for it), so their `economic_proxy_currency` stays `None` rather than being
   guessed.
5. **`threshold_progress`'s midpoint is the detector's own threshold, and it saturates at 100.**
   The point a detector's rule starts firing is set to score exactly 50 — the scale's own
   midpoint — so the lower half expresses "how close to triggering" and the upper half "how far
   past it", symmetrically, with one shared, simple linear-interpolation shape instead of five
   unrelated formulas. `saturation = 100` (usually `2 x threshold`) is a versioned V1 policy
   ceiling, not a claim that severity cannot exceed it; a value at or above it is fully saturated,
   never overflowed, never clamped in a surprising place.
6. **AND-conditioned detectors use MIN.** `REV_PICKUP_LOW`, `COST_CPOR_ANOMALY` and
   `LABOR_OVERSTAFFING` each require every one of a set of numeric conditions to hold before they
   trigger at all; their Impact score therefore uses the WEAKEST of the corresponding components,
   because a signal that only just cleared one of several required bars is not yet as severe as
   one that cleared all of them comfortably.
7. **OR-conditioned or independently-pathed detectors use MAX.** `REV_OCCUPANCY_RISK` triggers on
   either an occupancy gap or a room shortfall; its Impact is the STRONGER of the two, because
   either alone is a sufficient reason to trigger and severity should follow whichever reason is
   more severe. `REV_OTA_DEPENDENCY` similarly has two genuinely independent trigger paths
   (structural, rising); when only one holds, its own component is the impact; when both hold,
   the stronger of the two names it — never an average of two different phenomena.
8. **Confidence is reused exactly, never recomputed or averaged.** It is already a transparent,
   versioned heuristic computed by the detector itself, at the detector's own gate; recomputing it
   here would either duplicate that logic (a maintenance risk) or dilute it (an average would let
   a strong component mask a weak one, exactly the reasoning ADR 0011 already rejected for a
   detector's own final confidence). A `TRIGGERED` evaluation whose confidence is outside `0-100`
   or below its own detector's gate is `PRIORITY_INVALID_SOURCE_EVALUATION`: an internal-coherence
   check, never a second opinion.
9. **Actionability V1 is a fixed policy table, not a formula.** There is no data yet — no customer
   usage, no outcome history — to justify computing it from anything; a lookup by decision type,
   versioned (`priority-actionability-v1`), documented and honestly labelled as a heuristic is
   more truthful than a formula dressed up to look empirical. It carries no natural-language
   action text: a policy score of 90 never means "lower the price" anywhere in the code.
10. **Urgency is detector-aware, not one universal clock.** A forward-dated signal (pickup,
    occupancy, labor) is naturally "days until it matters"; `REV_OTA_DEPENDENCY` describes a
    30-day window as a whole, not one day inside it, so a fixed structural/rising policy is used
    instead of a fabricated "days to the window start"; `COST_CPOR_ANOMALY` is retrospective, so
    its urgency runs the other way — freshest right after the month concludes, fading afterwards.
    One shared shape would have forced at least one of these three families into a lie.
11. **Ranking sorts on the exact score, never the display score.** `priority_score_exact` is full
    `Decimal` precision in a dedicated 50-digit context (Gate 5's own, re-exported); the two-decimal
    `priority_score_display` (HALF_UP) is presentation only. Two candidates that display alike
    because they are 0.004 apart must still sort in their true order — exactly the same discipline
    every detector already applies to its own thresholds (ADR 0011 point 11).
12. **Tie-break is eight keys deep and fully deterministic.** After the four scores, a fixed,
    explicitly non-semantic `decision_type` order exists purely so two candidates identical in
    every scored respect still land the same way on every machine, every run; then the target key
    lexicographically, then the source fingerprint, which is unique per candidate after
    deduplication. Ranks are always unique `1..n`, never dense or shared, and the caller's input
    order never affects the output.
13. **No top-N truncation here.** `ranked_candidates` always holds every candidate. Deciding how
    many to show (a "top 5" home screen) is a presentation policy for a much later gate; baking a
    number in here would make this engine's own tests describe a UI decision it has no business
    knowing about.
14. **No persistence, no lifecycle, no Decision Memory, here.** A `PriorityCandidate` and a
    `PriorityRankingResult` are values, recomputed on demand from already-immutable evaluations;
    nothing survives a process. The next gate that wants to persist a visible Decision, deduplicate
    it across days or give it a lifecycle can build on this ranking without this gate being
    rewritten, exactly as ADR 0011/0013/0014 already reasoned for their own detectors.
15. **`PriorityService` never executes a detector.** It receives already-computed evaluations; it
    never imports `BookingRepository`/`InvoiceRepository`/a detector service or recalculates a
    detector's own facts. This is the one boundary that keeps "detectors produce signals" and
    "priority orders signals" from collapsing into one god-service as more detectors arrive.
16. **Limits and calibration.** The four weights, the actionability table and every urgency band
    are product heuristics awaiting real customer calibration, versioned in code
    (`priority-engine-v1`), never database rows. Impact V1 ignores every economic proxy by design;
    a future version that wants to blend severity with an FX-normalized exposure is a new,
    explicitly versioned policy, never a silent change to this one. A property-wide event visible
    across several detectors at once still produces several separate candidates: V1 has no notion
    of one signal explaining or subsuming another.

## Alternatives considered
* **A generic rules/priority DSL** (`GenericRulesFramework`, a `PluginEngine`): rejected, the same
  reasoning as every earlier gate (ADR 0011 point 1): five explicit adapters are simpler and more
  honest than an abstraction nothing yet justifies; extracting one later from what five detectors
  really share beats guessing one now.
* **A single universal Impact formula reading each detector's monetary proxy directly**: rejected
  (points 3-4): it would rank properties by currency strength and detector-specific proxy
  semantics, not by operational severity.
* **Averaging baseline and pattern-style confidences again at the priority layer**: rejected
  (point 8): the detector already computed a MIN-based final confidence; averaging on top of that
  would double-dilute a signal that is already conservative by design.
* **An ML/learned ranking model**: rejected outright; there is no outcome data yet to train one,
  and Gate 10's own charter forbids it (no AI/ML of any kind in V1).

## Consequences
* Adding a sixth detector needs one more explicit adapter (extraction, impact, urgency,
  target-key), never a change to the four already written.
* The ranking is exactly as good as its five inputs: a detector that is silent (young property,
  sparse data) produces no candidate, by design, the same "silence over noise" policy every
  detector already chose for itself.
* A future Decision layer (persistence, lifecycle, deduplication across days, recommendation, a
  business API, a UI) builds directly on `PriorityRankingResult` without this gate being rewritten.
* Weights, the actionability table and the urgency bands need calibration once real customers use
  this; nothing here claims a statistical truth.

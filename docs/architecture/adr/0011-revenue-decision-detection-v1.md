# 0011 — Revenue Decision Detection V1: two detectors, evaluations, no persisted Decision yet

**Status:** accepted (Gate 5)

## Context
The Decision Engine has snapshots (Gate 3) and historical baselines (Gate 4). The first thing it
must do with them is notice, for a stay night, that revenue is at risk: bookings are arriving more
slowly than they usually do, or the night is heading for a lower occupancy than usual. Three
temptations must be resisted: building a generic rule engine before two rules exist, persisting
"decisions" before anyone knows their lifecycle, and dressing a rough estimate up as a loss.

## Decision
1. **Two explicit detectors and a typed evaluation, no rule framework.** `REV_PICKUP_LOW` and
   `REV_OCCUPANCY_RISK` are two plain modules that share a small vocabulary (statuses, reason codes,
   pairs, confidence). There is no `GenericDecisionEngine`, rule DSL, plugin registry or generic
   facts bag: each detector has its own typed facts. Abstractions will be extracted from what the
   next detectors really share, not guessed.
2. **No persisted Decision yet.** The output is an immutable *evaluation*: a value computed from
   stored facts, fingerprinted, never stored. A Decision needs a lifecycle (open, acknowledged,
   resolved), deduplication across days, a priority and an outcome; none of that is known yet and
   a table designed now would be rewritten. Because the evaluation is a pure function of immutable
   snapshots and baselines, it can be recomputed at any time, and persisting a Decision later is an
   additive change. Only `TRIGGERED` will ever become a Decision.
3. **Five distinct statuses.** `TRIGGERED`, `CLEAR`, `INSUFFICIENT_DATA`, `NOT_APPLICABLE` and
   `SUPPRESSED_LOW_CONFIDENCE` mean different things (an alarm, a quiet all-clear, not enough
   evidence, a rule that does not apply, an alarm we do not trust) and are never collapsed into a
   boolean. "We could not tell" and "all is well" must stay distinguishable.
4. **A 7-day pickup window.** Pickup is the change in rooms on the books over exactly 7 snapshot
   days, measured on the same stay date. Seven days is one weekly cycle, long enough to smooth
   day-of-week noise in bookings and short enough to react. Both snapshots must be OBSERVED: a
   pickup between a reconstruction and an observation would compare an inference with a fact.
5. **Curve pairs, not an on-the-books gap.** Gate 4 already says how many rooms were *typically* on
   the books at this lead time. Comparing that with today's rooms is a level gap and cannot tell a
   slow week from a night that was simply behind all along. The pickup asks about *movement*: what
   the same historical stay dates picked up over the same 7 days. Each pair is two snapshots of ONE
   stay date, never a mix of dates, and the anchors are the Gate 4 comparables, so the selection
   rules (weekday, season, lead time, horizon) are not duplicated.
6. **Occupancy through the remaining net pickup, not a forecast platform.** The risk is "on the books
   now plus the usual remaining movement falls short of the usual final level", using the same
   pairs (anchor -> final on the stay date). It is a median of historical net movement: no
   seasonality of the movement, no demand curve, no price elasticity. Expected (a level at one lead
   time) and this projection are different things and are kept apart: the baseline table gets no
   forecast column.
7. **Cancellations are embedded in the net movement.** The remaining pickup is final minus anchor
   and can be negative. A stay date that lost rooms after the anchor lowers the expectation without
   a cancellation model, which would need cancellation timing, lead-time distribution and channel
   behaviour that V1 does not have. The forecast is floored at 0 rooms and has **no upper cap**:
   overbooking is preserved, and occupancy is not clamped to 100.
8. **Strict, deliberate anti-leakage.** Every endpoint must be strictly before the target's snapshot
   day, and belong to the same historical stay date, data source and workspace. This excludes
   the final snapshot of a night that has not ended yet, and, conservatively, one taken on the
   target's own snapshot day (the same batch, and lead-0 observations still move). It costs the
   most recent pairs but nothing unknown at the target's moment can improve its result.
9. **Final confidence is the MINIMUM.** `MIN(baseline confidence, curve-pattern confidence)`, never
   the average: a decision is only as reliable as its weakest input, and an average would let a
   strong baseline launder a weak pattern. The pattern confidence follows the Gate 4 shape (sample,
   provenance, stability) with caps for approximate pairs, using `abs(median)` because a net
   pickup can be negative or zero. Below the gate (50 pickup, 55 occupancy) a numeric hit is
   `SUPPRESSED_LOW_CONFIDENCE`, kept for the audit but not shown.
10. **Near sold out silences the pickup.** With at most one room left, a slow week is not a revenue
    problem: there is nothing to sell. The pickup is `NOT_APPLICABLE` (closed night first), even if
    the numbers would otherwise trigger. An unknown inventory does not silence it: NINFA does not
    invent a capacity, nor a reason to stay quiet. The occupancy risk, which needs a denominator,
    is `NOT_APPLICABLE` without one.
11. **The pickup rule needs a positive expectation.** A percentage of zero is undefined and a night
    that historically loses rooms during the week is not a pickup shortfall: `NOT_APPLICABLE`, and
    no division is ever attempted.
    **Thresholds compare the full-precision values, never the rounded ones that are shown.** The
    path is calculation value -> threshold comparison -> status -> display quantization: a
    pickup of -19.995 % displays as -20.00 but does not reach a -20 % threshold, and a gap of
    9.995 points displays as 10.00 but does not reach 10 points. Rounding for display must
    never move a decision across its threshold, so the facts keep the decision value (`*_exact`)
    next to the display value, and a person who wants to know why a night did or did not
    trigger can see the number that was really compared. Rooms and the confidence score are
    already exact at two decimals by definition and are compared as they are.
12. **A gross exposure proxy, not a loss.** `revenue_gap_proxy = rooms at risk x reference ADR` prices
    the rooms that are missing versus history at a rate that is really available (the target's
    ADR, else the historical comparable median, else none: never invented). It is **not** lost
    revenue and not a prediction: it says nothing about how many of those rooms will actually be
    missed, cancellations, displacement, discounts or margin. There is no loss probability, and the
    name deliberately never says "loss" or "economic impact".
13. **Thresholds are versioned code, not database rows.** They are product heuristics that will need
    calibration; `revenue-decisions-v1` and `revenue-curve-pattern-v1` name the exact rules, and
    changing one means a new version. Confidence and thresholds make no statistical claim.
14. **Read-only, deterministic, set-based.** The service writes nothing, takes no lock, reads no
    clock, needs no migration, no API, no worker and no dependency, and evaluates any number of
    targets with seven statements. The fingerprint hashes the logical input and result (never a
    timestamp) with non-lossy canonical Decimals, so equal inputs give equal fingerprints and
    inputs on opposite sides of a threshold never do, even when they display alike.

## Consequences
- The next gate can persist a Decision from a `TRIGGERED` evaluation without touching the detectors;
  until then nothing survives a process, which is intended.
- Two detectors share pairing, statistics and confidence but not a rule abstraction: adding a third
  detector means writing a third module and, only then, extracting what is really common.
- Young properties, sparse curves and quiet stay dates mostly get `INSUFFICIENT_DATA` or a suppressed
  evaluation rather than a confident alarm; the price is silence, chosen over noise.
- Strict anti-leakage and observed-first pairing mean the number of usable pairs is small at short
  lead times; the minimum of 5 pairs is a floor, not a statistical law.
- Weights, thresholds, the 7-day window and the ADR choice are heuristics to calibrate with real
  customers. The proxy must never be shown as revenue loss.
- No cancellation model, no seasonality of the movement, no capacity normalisation, no events,
  weather or competitors: each is a possible later gate.

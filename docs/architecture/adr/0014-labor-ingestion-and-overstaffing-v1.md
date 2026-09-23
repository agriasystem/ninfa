# 0014 — Labor Ingestion and Overstaffing Detection V1: minutes not hours, demand reused not rebuilt, no HR

**Status:** accepted (Gate 8)

## Context
Gates 2-7 gave NINFA canonical bookings, snapshots, an Expected baseline, two revenue detectors and
a cost detector. The fourth operating question a hotelier asks is "for the demand I actually expect
this day, are the scheduled hours of a department materially above what comparable demand days
historically needed?". Answering it needs a labor data contract NINFA does not have yet, a demand
forecast for the target day, and a robust historical staffing expectation — and it must not become
an HR system, a scheduler, a payroll engine or a fourth reimplementation of demand forecasting.

## Decision
1. **No employee identity, ever.** The canonical model carries a work date, a category, minutes and
   an optional cost — never a name, an id, an email, a phone number, a tax code, an address, a leave
   reason or free text about a person. `role_raw` is a free-text SHIFT label from the source (e.g.
   "Reception AM"), never a person's name. An unmapped column (an employee name a source file
   happens to carry) never reaches staging, the canonical tables, a log line or an error message.
   V1 reasons about aggregate scheduled/worked minutes, never about who worked them.
2. **Minutes, not float hours.** `planned_minutes`/`actual_minutes` are integers. A source's decimal
   hours are converted by exact `Decimal` multiplication (`hours * 60`); a value that is not a whole
   number of minutes is REJECTED, never silently rounded. Rounding here would drift every later sum,
   median and threshold comparison by an amount nobody could explain.
3. **Planned and actual are never substituted for each other.** A `LaborEntry` keeps both columns;
   at least one must be present, but the import never invents one from the other. The TARGET plan
   uses planned minutes only (a schedule is what was planned); a HISTORICAL day uses ACTUAL-FIRST:
   every entry of the category must have actual minutes, or (only if that fails) every entry must
   have planned minutes; a day with neither complete is rejected, not blended.
4. **The daily snapshot is immutable evidence.** `LaborSnapshot` identity is
   (workspace, data_source, snapshot_local_date), given explicitly by the caller — never
   `date.today()` or a file's mtime — for the same reason Gate 3's `BookingSnapshot` reads no clock:
   determinism, replay and backtesting. The same date and the same canonical content is a no-op
   (order-independent: the fingerprint sorts canonical entries); the same date and different content
   is `LABOR_SNAPSHOT_CONFLICT`. A revision of the plan is a NEW snapshot date, never an edit.
5. **Deterministic classification, the Gate 6 pattern, not a duplicate.** `labor_category` is decided
   by exactly the same priority ladder as Gate 6's cost categories — explicit source (100), a saved
   mapping (95), a small phrase dictionary (80), or `OTHER` (0) — with the same policy: a role
   matching two categories' phrases is ambiguous and stays `OTHER`. No AI, no fuzzy matching.
6. **Demand is reused, not rebuilt a third time.** `LABOR_OVERSTAFFING` needs the room demand a
   target day should expect. That is exactly what Gate 5's `REV_OCCUPANCY_RISK` already computes
   (`rooms_on_books + expected_remaining_net_pickup`, floored at 0, no upper clamp) from the same Gate
   4 baseline and the same remaining-pickup pairs. The two-line formula was extracted, unchanged,
   into `intelligence.demand.forecast`; a new `DemandForecastService` reuses Gate 5's own pairing,
   pattern and confidence modules to reach the same number Gate 5 would. There is no second demand
   algorithm anywhere in the labor module.
7. **Comparable days, not comparable ratios.** Expected hours are the MEDIAN of comparable days'
   TOTAL hours, never `hours / occupied room`. Many hotel functions have a fixed component (a front
   desk does not halve its hours because occupancy halves); a per-room ratio would misjudge exactly
   the departments a hotelier most wants judged fairly.
8. **A comparable day needs the same three things Gate 4/5 already require:** strictly before the
   target's as-of date and work date (anti-leakage), the same weekday, seasonal distance at most 42
   days (the Gate 4 algorithm, reused, not reimplemented), at most 730 days back. On top of that it
   needs a clean lead-time-0 occupancy within tolerance of the target's forecast
   (`max(3, 20% x forecast)`), labor data covering it, a complete ACTUAL-FIRST basis and at least 70%
   classification coverage on that basis. Every rejection is counted by its reason, never silently
   dropped.
9. **Observed-first, the Gate 4/5/7 philosophy, applied to days.** A pair is
   `FULLY_OBSERVED_COMPARABLE` only when it is ACTUAL labor AND OBSERVED occupancy. With at least 5
   such days, only they are used; otherwise every fully observed day is kept and the newest clean
   approximate days complete the sample, up to 24. Fewer than 5 total: `INSUFFICIENT_DATA`.
10. **AND, not OR, on the full-precision values.** The trigger needs all four: scheduled hours above
    the expected ones, at least 20% above them, at least 4 hours above them, and at or above the
    robust upper fence (`P75 + 1.5 x IQR`, the same Gate 4/5/7 statistics, no outlier removal). Any one
    missing is `CLEAR`. Thresholds are versioned constants in code (`labor-overstaffing-v1`), never
    database settings.
11. **Confidence is the minimum of THREE inputs, never their average.** `MIN(baseline confidence,
    demand confidence, target plan quality)`: a decision is only as reliable as its weakest input —
    the historical sample, the demand forecast that told it what "normal" demand looks like, or the
    target day's own classification quality. Below 55 a real numeric anomaly is
    `SUPPRESSED_LOW_CONFIDENCE`, never invented as a confident TRIGGERED.
12. **The cost proxy is optional and is never a saving.** `labor_cost_gap_proxy` (excess hours times a
    reference hourly rate, itself resolved from the target's own planned rate or else the historical
    ACTUAL median rate, in one consistent currency, with no FX) is a GROSS exposure figure. It never
    enters the trigger and is never called a saving, a loss or an avoidable cost. The detector works
    fully without any cost data.
13. **No recommendation, no priority, no persisted Decision, no individual judgement.** Like Gates 5
    and 7, the output is an immutable, fingerprinted evaluation, a pure function of stored labor
    entries and booking snapshots, recomputable at any time — read-only, zero database writes. It
    judges an AGGREGATE level of scheduled hours for a category on a day, never a person's
    productivity, attendance or performance, and NINFA does not even collect the data that would let
    it. There is no `Decision`, no priority, no scheduler and no AI anywhere in this gate.

## Alternatives considered
* **Float hours in the canonical model**: rejected (see 2): every aggregation downstream would
  accumulate binary-floating-point drift invisible to a threshold comparison.
* **A per-room-hours ratio as the expected value**: rejected (see 7).
* **Employee-level scheduling data (shift id, employee id)**: rejected for V1 (see 1): it is not
  needed for an aggregate-hours detector and it is the single biggest privacy and scope risk this
  gate could take on.
* **A second, labor-specific demand forecast**: rejected (see 6): Gate 5's formula, pairing and
  confidence are already exactly what this gate needs; a second implementation could only drift from
  the first.
* **Persisting `LaborDecisionEvaluation` or a `Decision` now**: rejected, for the same reason as
  Gates 5 and 7 (ADR 0011, ADR 0013): the lifecycle is not known yet and the evaluation is cheap to
  recompute.

## Consequences
* Additive and reversible: one migration (`0008_labor_ingestion`, four tables, two immutability
  triggers), no change to migrations 0001-0007, no public API beyond `/api/v1/health`, no worker
  task and no new runtime dependency.
* `intelligence.revenue.occupancy`'s own behaviour is unchanged bit-for-bit: the extraction into
  `intelligence.demand.forecast` moved two lines, it did not alter them (guarded by the full Gate 5
  regression suite).
* Every answer is explainable from its facts, deterministic (SHA-256 fingerprint of the canonical
  inputs and result) and replayable, since the service reads no clock.
* The data-minimisation choice (no employee identity) means NINFA cannot, and will not be asked to,
  answer "who should go home" — that judgement, if it is ever wanted, needs a different gate, a
  different consent basis and a different dataset.

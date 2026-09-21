# 0010 — Expected Engine V1: historical comparable baselines

**Status:** accepted (Gate 4)

## Context
The Decision Engine has to tell whether the book of a property is normal for its date: it needs a
**baseline** to compare the real state against. Two temptations must be resisted: producing a number
just because arithmetic can, and presenting a description of the past as a promise about the future.
The data available (Gate 3) is a daily, per-data-source snapshot of rooms on the books, either
OBSERVED (really captured) or RECONSTRUCTED_APPROXIMATE (inferred later from a booking table that
keeps only the current state, ADR 0009). A young installation has little observed history.

## Decision
1. **Expected is a historical level, not a forecast.** It answers "what was typically on the books
   for comparable stays at this distance from the stay", never "how the stay will end". The range is
   the historical P25-P75, explicitly *not* a confidence or prediction interval. Forecasting,
   remaining pickup, cancellation modelling and final occupancy are out of scope.
2. **Median, not mean.** Hospitality data is lumpy: a group booking, an event or a one-off day can
   double a night. The median and the interquartile range are robust to that without removing
   anything, so no outlier filter (z-score, winsorisation, sigma clipping) exists in V1. The median
   of an even sample is fractional and is stored as `NUMERIC`, never rounded to rooms.
3. **Same lead time.** Rooms on the books 14 days before a stay and 3 days before it measure
   different things (time pressure, distribution mix). A comparable is the snapshot at exactly the
   target's lead time; there is no interpolation, so a missing lead time is a missing comparable.
4. **Same weekday.** Demand in hospitality is weekly. Comparing a Saturday with weekdays mixes
   leisure and business demand. There is no weekday/weekend fallback and the criterion is never
   widened silently: too few Saturdays means `INSUFFICIENT_DATA`, not a looser question.
5. **A +-42 day seasonal window on month/days, year ignored.** Simple, explainable, deterministic and
   year-independent. The distance between two month/days is the smaller circular distance on a
   common (365-day) and a leap (366-day) calendar, with a pair that includes 29 February measured on
   the leap one: it wraps at the year boundary, is symmetric and matches what a calendar shows
   (28 February and 1 March are 1 day apart). A 730-day horizon bounds the history because a
   property changes over time.
6. **No temporal leakage.** A comparable must have both its stay date and its snapshot day strictly
   before the target's. Nothing unknown at the target's moment can improve its baseline.
7. **OBSERVED first; reconstruction is a penalised fallback.** Observed evidence is what NINFA
   really saw; a reconstruction is an approximation (ADR 0009). With at least 5 observed comparables
   the baseline uses only them: adding reconstructions "to have more data" would blur good evidence
   with inference. With fewer, clean reconstructions (no uncertainty) complete the sample up to the 24-comparable
   maximum (not merely up to 5: the caps below would otherwise never bind), so that a
   young installation is not blind, but they weigh less in the confidence (60 against 100) and cap it
   (85 when any is used, 65 when there is no observed comparable at all). A reconstruction with
   uncertainty never enters the numbers and is counted (`rejected_uncertain_count`).
8. **A minimum sample of 5, and no number below it.** With fewer than five comparables the median and
   the quartiles are noise: a quartile of four points is a single interpolation. Below 5 the result
   is `INSUFFICIENT_DATA`: no expected, no range, confidence 0 and no band (never an artificial
   "LOW"), because a number without a trustworthy sample is not an Expected and would flow into
   decisions as if it were. Five is a pragmatic floor (it is also where quartiles start to differ
   from the extremes), not a statistical law. The maximum sample is 24, which is exactly two seasonal
   windows of about 12 same-weekday dates.
9. **Baseline confidence is a transparent, versioned heuristic** (sample 40%, provenance 35%,
   stability 25%), in `Decimal`, with caps and bands. It is not the general Decision Confidence and
   makes no statistical claim; it exists so that a number never travels without a measure of its
   sample. A `READY` baseline may be `LOW`; whether to show it is a later decision.
10. **Immutable, auditable baselines.** One row per target snapshot and `calculation_version`, no
    `updated_at`, a trigger refusing updates, the comparables used stored as rows (not a JSON of ids),
    a fingerprint of the logical input. The same input is an idempotent no-op; a different result for
    the same key is `EXPECTED_BASELINE_CONFLICT`, never a silent overwrite. Changing a rule means a new
    version.
11. **Tenant and origin integrity in the database.** Composite foreign keys tie a baseline and its
    comparables to one workspace, property and data source; the target snapshot is referenced together
    with its origin, and `target_origin` is CHECKed to `OBSERVED`, so a reconstruction cannot be a
    target even by raw SQL. This needs one extra unique constraint on `booking_snapshots`.
12. **An application service with a batch path, no API, no worker, no scheduler, no new dependency.**
    Candidate history is fetched in one statement per batch by exact keys; the statistics are plain
    `Decimal` (no numpy/pandas/scipy for a median and two quartiles).

## Consequences
- Sparse or new properties get `INSUFFICIENT_DATA` or low, capped confidence rather than invented
  precision; the cost is that early baselines are conservative. Everything downstream (Gate 5) must
  handle three states: `READY`, `READY` with a low band, and `INSUFFICIENT_DATA`.
- Because baselines are immutable, history that arrives after a calculation (a later reconstruction)
  does not update it: re-running the same target is a conflict, and an insufficient baseline stays as
  the record of that day. Expected should run right after the day's observation, and a corrected
  history needs a new `calculation_version`.
- Rooms are not normalised by capacity in V1: a material change of the property's inventory makes a
  baseline less comparable, and this is documented rather than hidden behind a heuristic.
- The weights and thresholds of the confidence, the +-42 day window, the 5/24 sample limits and the
  60/85/65 provenance values are product heuristics that need calibration with real customers.
- No recency weighting, no outlier handling, no events/weather/competitors: each is a possible later
  policy, deliberately not mixed into the first baseline.
- One extra unique index on `booking_snapshots` and two immutable tables; deletions are RESTRICTed and
  retention is deferred.

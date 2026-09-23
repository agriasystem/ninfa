# NINFA — LABOR_OVERSTAFFING detection v1 (Gate 8, Parts B-I)

See [ADR 0014](adr/0014-labor-ingestion-and-overstaffing-v1.md) for the decisions and their
rationale. This document is the reference for the detector's calculation.

## The question

Not "are there more employees scheduled than last month?" but: **for the room demand this day is
actually expected to see, are the scheduled hours of a category materially above what comparable
demand days have historically needed?** Comparable demand, not comparable calendar date.

## Demand forecast: reused, not rebuilt

The target's expected room demand is `intelligence.demand.service.DemandForecastService`, which
reuses Gate 5's own machinery on the SAME target booking snapshot:

* `lead_time_days == 0` (the target IS its own stay date): `forecast_rooms = rooms_on_books`,
  `demand_confidence = 100`.
* `lead_time_days > 0`: the target's Gate 4 baseline and its comparables become the anchors of
  Gate 5's `remaining_pairs` (same pairing, same anti-leakage); `analyse()` gives the pattern
  statistics and confidence exactly as `REV_OCCUPANCY_RISK` would; the forecast itself is
  `intelligence.demand.forecast.forecast_rooms_from_pickup(rooms_on_books,
  expected_remaining_net_pickup)` — the SAME two lines `REV_OCCUPANCY_RISK` now calls too, floored
  at 0, never clamped above. `demand_confidence = MIN(baseline_confidence, pattern_confidence)`,
  Gate 5's own `final_confidence`.
* Fewer than 5 clean remaining-pickup pairs, or no READY Gate 4 baseline:
  `INSUFFICIENT_DATA / LABOR_DEMAND_FORECAST_INSUFFICIENT`. Demand is never invented.

## The target's own plan (Part C)

For `target_work_date` (the target snapshot's `stay_date`) and `target_as_of_date` (its
`snapshot_local_date`): the latest `LaborSnapshot` with `snapshot_local_date <= target_as_of_date`
that contains an entry for `target_work_date` (anti-leakage: never a labor snapshot from after the
as-of date, whatever the target's own lead time).

* No such snapshot at all: `INSUFFICIENT_DATA / LABOR_PLAN_MISSING`.
* The requested category has no row that day: `NOT_APPLICABLE / LABOR_CATEGORY_NOT_SCHEDULED`.
* The category's rows exist but not every one has `planned_minutes`:
  `INSUFFICIENT_DATA / LABOR_PLAN_INCOMPLETE`.
* Otherwise `scheduled_minutes = SUM(planned_minutes)` of the category's rows,
  `scheduled_hours = scheduled_minutes / 60` (exact `Decimal` division).

**Classification coverage** is measured over the WHOLE day (every category, on the planned
basis): `classified / total x 100`. Below 70% (or undefined, `total == 0`):
`INSUFFICIENT_DATA / LABOR_CLASSIFICATION_COVERAGE_LOW`. **Target plan quality** =
`0.60 x weighted_category_confidence + 0.40 x coverage` (HALF_UP, 2 decimals) — a component of the
final confidence (below), never a substitute for it.

`labor_category == OTHER` is checked FIRST, before any of the above: it needs no data to answer
`NOT_APPLICABLE / LABOR_CATEGORY_OTHER_NOT_ACTIONABLE`.

## Historical comparable days (Parts D-E)

A candidate day is generated only when, relative to the target: strictly before both the as-of
date and the work date, at most 730 days back, the same weekday (by construction: candidates step
back in whole weeks) and seasonal distance at most 42 days (`intelligence.expected.seasonality`,
the Gate 4 algorithm, reused). It becomes ELIGIBLE only when ALL hold:

1. a clean lead-time-0 booking snapshot exists for it (`uncertain_rooms > 0` rejects it);
2. its occupied rooms are within `max(3, 20% x target_forecast_rooms)` of the target's forecast;
3. a labor snapshot (picked the same way as the target's, independently per day: a rolling
   near-term export and a full-horizon export are both handled correctly) covers it;
4. the category's ACTUAL-FIRST basis is complete: every row has `actual_minutes`, or (only if
   that fails) every row has `planned_minutes`; a day with neither complete is rejected, never
   blended. A category absent that day is a real, valid ZERO (ACTUAL basis, vacuously complete),
   not a rejection.
5. classification coverage on that SAME basis, over the whole day, is at least 70%.

Every rejection is counted by its reason (`rejected_occupancy_incomplete_count`,
`rejected_demand_mismatch_count`, `rejected_labor_missing_count`, `rejected_labor_incomplete_count`,
`rejected_low_classification_count`), never silently dropped.

**Pair quality** (labor basis x occupancy origin): ACTUAL + OBSERVED = 100 (`FULLY_OBSERVED_
COMPARABLE`), ACTUAL + RECONSTRUCTED = 80, PLANNED_FALLBACK + OBSERVED = 80, PLANNED_FALLBACK +
RECONSTRUCTED = 60. **Observed-first**: with at least 5 fully-observed eligible days, only they are
used; otherwise every fully-observed day is kept and the newest clean approximate days complete the
sample, up to 24, most recent first. Fewer than 5 total: `INSUFFICIENT_DATA /
LABOR_COMPARABLE_SAMPLE_INSUFFICIENT`.

## Expected hours and the trigger (Parts E-F)

`summarize()` (median, P25, P75, IQR by linear interpolation at `(n-1) x p`, no outlier removal —
the same robust statistics as Gates 4/5/7) over the used days' historical hours.
`expected_labor_hours = median`. `median <= 0`: `NOT_APPLICABLE /
EXPECTED_LABOR_HOURS_NON_POSITIVE` (a real, valid zero for that category, e.g. never staffed
historically — not a baseline a percentage can be measured against).

```
excess_hours       = max(0, scheduled_hours - expected_labor_hours)
delta_percent      = (scheduled_hours - expected_labor_hours) / expected_labor_hours * 100
upper_fence_hours  = P75 + 1.5 * IQR

numeric_candidate  = scheduled_hours > expected_labor_hours          (above)
                 AND delta_percent   >= 20                          (relative)
                 AND excess_hours    >= 4                            (absolute)
                 AND scheduled_hours >= upper_fence_hours             (robust fence)
```

All four, on the full-precision `Decimal` values — a display value never decides. Any one missing:
`CLEAR / CLEAR_WITHIN_EXPECTED_RANGE`.

## Confidence (Part G)

```
sample_score         = min(100, n / 12 * 100)
provenance_score      = mean of the used days' pair quality
classification_score  = mean of the used days' weighted category confidence (unknown -> 0)
stability_score       = max(0, 100 - 50 * IQR / max(|expected_labor_hours|, 1))

baseline_confidence = 0.35*sample + 0.25*provenance + 0.15*classification + 0.25*stability
                      (HALF_UP, 2 decimals)
```
Capped at 85 if any used day is not fully observed, at 65 if none is. `final_confidence =
MIN(baseline_confidence, demand_confidence, target_plan_quality)` — never their average: a decision
is only as reliable as the weakest of the three. `numeric_candidate AND final_confidence >= 55`:
`TRIGGERED`. `numeric_candidate` alone: `SUPPRESSED_LOW_CONFIDENCE`. Neither: `CLEAR`, whatever the
confidence — a low confidence never explains away the absence of a real anomaly.

## Labor cost gap proxy (Part H, optional)

`reference_hourly_cost`, tried in order: (1) the target category's own planned cost, if positive,
`scheduled_hours > 0` and one consistent currency — `TARGET_PLANNED_COST_RATE`; (2) else the median
of `(day cost / day hours)` over the used days whose basis is ACTUAL and that carry a cost in one
consistent currency — `HISTORICAL_ACTUAL_MEDIAN_RATE`; (3) else `None`. No FX, ever: an
inconsistent currency is treated exactly like a missing cost. `labor_cost_gap_proxy = excess_hours
x reference_hourly_cost` (HALF_UP, 2 decimals) — a **GROSS** exposure figure, never a saving, a
loss or a guaranteed avoidable cost, and never part of the trigger. The detector works fully
without any cost data.

## Explainability, determinism, performance

Every fact behind a `TRIGGERED` evaluation is on the returned `LaborDecisionEvaluation`: the target
booking/labor snapshot ids, the as-of/work dates, the forecast, the scheduled hours, the
classification quality, every comparable day (work date, occupancy, basis, hours, provenance), the
statistics, the confidence components and the cost proxy inputs — no generated text. The
`calculation_fingerprint` is a SHA-256 of the canonical (non-lossy `Decimal`) payload; the same
logical input gives the same fingerprint on any machine, on any run. The service is READ-ONLY (zero
writes, no advisory lock, no clock) and reads a bounded, bandwidth-independent number of statements
per evaluation (ONE `labor_entries` read of every work date involved, ONE `booking_snapshots` read
of every historical lead-time-0 key, whatever the number of comparable days).

## Reason codes

`TRIGGER_LABOR_OVERSTAFFING`, `CLEAR_WITHIN_EXPECTED_RANGE`,
`LABOR_CATEGORY_OTHER_NOT_ACTIONABLE`, `LABOR_CATEGORY_NOT_SCHEDULED`, `LABOR_PLAN_MISSING`,
`LABOR_PLAN_INCOMPLETE`, `LABOR_CLASSIFICATION_COVERAGE_LOW`,
`LABOR_DEMAND_FORECAST_INSUFFICIENT`, `LABOR_COMPARABLE_SAMPLE_INSUFFICIENT`,
`EXPECTED_LABOR_HOURS_NON_POSITIVE`, `LOW_CONFIDENCE`, `BOOKING_DATA_SOURCE_INVALID` and
`LABOR_DATA_SOURCE_INVALID` (both request-level only, raised as `LaborDecisionError`, never
carried by an evaluation).

## Limitations (intentional)

* Judges an AGGREGATE level of scheduled hours for one category on one day — never a person's
  productivity, attendance or performance, and NINFA does not collect the data that would let it.
* No recommendation ("send someone home", "cut a shift"): NINFA produces facts and a detection
  status, never a staffing action.
* No priority, no persisted `Decision`: like Gates 5 and 7, only a `TRIGGERED` evaluation will ever
  become a visible Decision, in a later gate.
* A total, whole-day demand mismatch (a property-wide event) is invisible if every category still
  looks locally normal: V1 judges one category at a time.

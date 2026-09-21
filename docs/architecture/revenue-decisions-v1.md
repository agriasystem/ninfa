# NINFA — Revenue Decision Detection v1 (Gate 5)

Scope: two explicit detectors, `REV_PICKUP_LOW` and `REV_OCCUPANCY_RISK`, that read the immutable
Gate 3 snapshots and Gate 4 Expected baselines and return a typed, immutable, auditable
**evaluation**. Nothing is persisted, nothing is shown, nothing is recommended: this gate ends at
the evaluation. Decision, alert, priority, recommendation, pricing, AI, API, worker and scheduler
belong to later gates.

    BOOKINGS -> SNAPSHOTS -> EXPECTED BASELINES -> REVENUE EVALUATIONS      (Gate 5 stops here)

Code: `services/api/app/modules/intelligence/revenue/` (`types`, `errors`, `pairing`, `statistics`,
`confidence`, `pattern`, `precision`, `impact`, `pickup`, `occupancy`, `fingerprint`,
`service`). Versions:
rules `revenue-decisions-v1`, curve pattern `revenue-curve-pattern-v1` (never the application
version, a git hash or a migration id). Migration head is still `0006_expected_engine`: this gate
adds **no table, no migration, no API, no worker task and no dependency**.

## Evaluation, not decision

An evaluation is the value returned by a pure calculation over stored facts. It is **not stored**:
there is no `Decision`, `DecisionFact`, `DecisionEvent`, `DecisionOutcome` or `DecisionMemory`
table and a test guards it. Only a `TRIGGERED` evaluation will ever become a visible Decision, in
a later gate that will decide persistence, lifecycle and deduplication. `RevenueDecisionEvaluation`
carries:

| Field | Meaning |
| ----- | ------- |
| `decision_type` | `REV_PICKUP_LOW` or `REV_OCCUPANCY_RISK` |
| `status` | one of five distinct statuses (below) |
| `workspace_id`, `property_id`, `data_source_id` | the tenant context of the target |
| `target_snapshot_id`, `target_baseline_id` | the OBSERVED snapshot and its Gate 4 baseline (`NULL` if none exists) |
| `snapshot_local_date`, `stay_date`, `lead_time_days` | where and when the target was seen |
| `confidence_score` | final confidence, 0-100 (`0.00` when no confidence was assessed: an early exit is never a "low" score) |
| `rules_version`, `pattern_version` | `revenue-decisions-v1`, `revenue-curve-pattern-v1` |
| `calculation_fingerprint` | SHA-256 of the logical input and result (below) |
| `reason_codes` | stable codes, never prose |
| `facts` | typed per detector (`PickupFacts`, `OccupancyFacts`), never a generic bag |
| `evidence_snapshot_ids` | every stored snapshot the result rests on, in a fixed order |
| `revenue_gap_proxy`, `reference_adr`, `reference_adr_source` | the gross exposure proxy and the price it used |

## The five statuses

The statuses are never interchangeable; each has a different meaning for whoever reads it later.

| Status | Meaning |
| ------ | ------- |
| `TRIGGERED` | the rule holds and the confidence is sufficient |
| `CLEAR` | the data is sufficient and the condition does not pass its thresholds |
| `INSUFFICIENT_DATA` | not enough reliable data to evaluate |
| `NOT_APPLICABLE` | the rule has no meaning in this context (closed night, sold out, ...) |
| `SUPPRESSED_LOW_CONFIDENCE` | the numeric condition holds but NINFA is not confident enough to show it |

Reason codes: `TRIGGER_PICKUP_SHORTFALL`, `TRIGGER_OCCUPANCY_GAP`, `TRIGGER_ROOM_SHORTFALL`,
`TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL`, `CLEAR_WITHIN_EXPECTED_RANGE`, `EXPECTED_BASELINE_MISSING`,
`EXPECTED_BASELINE_INSUFFICIENT`, `PAIR_SAMPLE_INSUFFICIENT`, `PICKUP_PRIOR_OBSERVATION_MISSING`,
`PICKUP_EXPECTATION_NON_POSITIVE`, `PICKUP_NEAR_SOLD_OUT`, `OCCUPANCY_INVENTORY_UNKNOWN`,
`OCCUPANCY_ALREADY_SOLD_OUT`, `PROPERTY_CLOSED_FOR_STAY_DATE`, `LOW_CONFIDENCE`. A suppressed
evaluation carries only `LOW_CONFIDENCE` (a `TRIGGER_*` reason always means `TRIGGERED`); the
numeric conditions that held are in its facts.

## The target

A target is an OBSERVED `BookingSnapshot` of the caller's workspace, in a `BOOKINGS` data source
that is active and belongs to the snapshot's property, whose property is not archived, with
`stay_date >= snapshot_local_date`. The Gate 4 baseline of the target must exist: a missing baseline
is `INSUFFICIENT_DATA / EXPECTED_BASELINE_MISSING` and an `INSUFFICIENT_DATA` baseline is
`INSUFFICIENT_DATA / EXPECTED_BASELINE_INSUFFICIENT`. A RECONSTRUCTED target is **refused**
(`REVENUE_TARGET_NOT_OBSERVED`): operational decisions start from a state NINFA really saw. An
unknown snapshot and a snapshot of another workspace raise the same `REVENUE_TARGET_NOT_FOUND`.

## Curve pairs

Gate 5 never repeats the Gate 4 discovery (weekday, season, horizon, lead time). The **anchors** are
the comparables the Expected Engine already selected and stored. Each anchor is a snapshot of a
historical stay date `D_h` seen `L` days before it. A curve **pair** adds ONE more snapshot of the
**same** stay date:

| Pair | Second endpoint | Delta |
| ---- | --------------- | ----- |
| pickup pair | the snapshot exactly 7 days before the anchor `(anchor day - 7, D_h)` | `anchor rooms - prior rooms` |
| remaining pair | the final snapshot taken on the stay date `(D_h, D_h)` | `final rooms - anchor rooms` (may be negative) |

Endpoints are looked up by their exact `(snapshot day, stay date)` key: no interpolation, no
nearest day, no other stay date, no other data source. A pair is used only when

* both endpoints exist (otherwise `missing_endpoint_count`);
* **no temporal leakage**: both endpoints are strictly before the target's snapshot day
  (otherwise `excluded_future_count`). For a remaining pair this matters: the final snapshot of a
  stay date that has not ended, or that ends on the target's own snapshot day, is not yet known;
* neither endpoint has uncertain rooms (otherwise `rejected_uncertain_count`); uncertain pairs are
  never used to reach the minimum.

Provenance: `OBSERVED_PAIR` only if **both** snapshots are OBSERVED, otherwise `APPROXIMATE_PAIR`.
Policy V1 (the Gate 4 policy applied to pairs): with at least 5 clean observed pairs only those are
used; with fewer, all of them are completed with clean approximate pairs, newest first, up to 24.
Fewer than 5 pairs in total is `INSUFFICIENT_DATA / PAIR_SAMPLE_INSUFFICIENT`. Pairs are ordered
newest historical stay date first and the result does not depend on the order of the stored rows.

## Curve-pattern statistics

Median, P25, P75 and IQR of the pair deltas with exactly the Gate 4 algorithms (the same function:
linear interpolation at `(n - 1) * p`), in `Decimal`, no float, no outlier removal. Deltas are
integer rooms and may be negative or zero.

## Confidence

    sample_score       = min(100, pairs / 12 * 100)
    provenance_score   = (observed_pairs * 100 + approximate_pairs * 60) / pairs
    relative_iqr       = IQR / max(abs(median), 1)
    stability_score    = max(0, 100 - 50 * relative_iqr)
    pattern_confidence = 0.40 * sample + 0.35 * provenance + 0.25 * stability      (HALF_UP, 2 dp)

Caps, after the formula: at most 85 if any approximate pair is used; at most 65 if there is no
observed pair. `abs` matters because a remaining net pickup can be negative. The **final
confidence** of an evaluation is `MIN(baseline confidence, pattern confidence)`, never the average:
a decision is only as reliable as its weakest input. Like the baseline confidence it is a
transparent, versioned heuristic, not a statistical claim.

## REV_PICKUP_LOW

The last 7 days brought fewer rooms than this stay night's history says.

    actual_pickup   = rooms now - rooms of the snapshot exactly 7 snapshot days earlier
                      (same property, data source and stay date; both must be OBSERVED)
    expected_pickup = median over the pickup pairs of (anchor rooms - rooms 7 days before the anchor)
    delta_rooms     = actual - expected
    missing_rooms   = max(0, expected - actual)
    delta_percent   = (actual - expected) / expected * 100                    (only if expected > 0)

Numeric condition: `delta_percent <= -20` **and** `missing_rooms >= 2`, on the **full-precision**
values the calculation produced, never on the two-decimal values that are displayed (see
"Decision values and displayed values"): -19.99 and -19.995 do not pass, -20 and -20.001 do;
1.99 rooms does not and 2 does. With the numeric condition true, a final confidence of at least 50 is
`TRIGGERED` and below it `SUPPRESSED_LOW_CONFIDENCE` (49.99 / 50.00). Checks run in this order and
the first that applies decides:

1. `rooms_available = 0` -> `NOT_APPLICABLE / PROPERTY_CLOSED_FOR_STAY_DATE` (before near sold out);
2. `rooms_available - rooms_on_books <= 1` (sold out, overbooked or one room left) ->
   `NOT_APPLICABLE / PICKUP_NEAR_SOLD_OUT`: there is nothing to sell, so a low pickup is not a
   problem. Unknown inventory does **not** stop the rule;
3. no baseline / insufficient baseline -> `INSUFFICIENT_DATA`;
4. no OBSERVED prior snapshot exactly 7 days earlier (missing or reconstructed) ->
   `INSUFFICIENT_DATA / PICKUP_PRIOR_OBSERVATION_MISSING`;
5. fewer than 5 pairs -> `INSUFFICIENT_DATA / PAIR_SAMPLE_INSUFFICIENT`;
6. `expected_pickup <= 0` -> `NOT_APPLICABLE / PICKUP_EXPECTATION_NON_POSITIVE` (a percentage of
   nothing is undefined and a night that historically loses rooms is not a pickup shortfall; the
   division is never attempted);
7. the thresholds.

## REV_OCCUPANCY_RISK

On the books now plus the usual remaining **net** pickup falls short of the usual final level.
This is a deliberately minimal projection, **not** a revenue-management forecast: no seasonality
model, no demand curve, no price elasticity, no cancellation model.

    expected_remaining_net_pickup = median over the remaining pairs of (final rooms - anchor rooms)
    raw_forecast_rooms   = rooms now + expected_remaining_net_pickup
    forecast_rooms       = max(0, raw_forecast_rooms)        (the only floor: NO upper cap)
    expected_final_rooms = median of the final rooms of the SAME pairs
    forecast_occupancy       = forecast_rooms / rooms_available * 100
    expected_final_occupancy = expected_final_rooms / rooms_available * 100
    room_shortfall   = max(0, expected_final_rooms - forecast_rooms)
    occupancy_gap_pp = max(0, expected_final_occupancy - forecast_occupancy)      (percentage points)

The remaining pickup is **net**: cancellations are already inside the historical movement of the
curve (it can be negative); a stay date that lost rooms after the anchor lowers the expectation
without a separate model. `rooms_available` is the current target inventory, the denominator of
both occupancies, never clamped to 100 (overbooking stays visible). Numeric condition, on the
full-precision values: `occupancy_gap_pp >= 10` **or** `room_shortfall >= 3` (9.99 and 9.995
points do not pass, 10 does; 2.99 and 2.995 rooms do not pass, 3 does). The gap is computed as
`room_shortfall / rooms_available * 100` in one division of an exact numerator, which is
mathematically `max(0, final occupancy - forecast occupancy)` without ever subtracting two
rounded quotients. With it true, a final confidence of at least 55 is `TRIGGERED` (54.99 / 55.00), otherwise
`SUPPRESSED_LOW_CONFIDENCE`. The reason says which condition held:
`TRIGGER_OCCUPANCY_GAP`, `TRIGGER_ROOM_SHORTFALL` or `TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL`.
Order of the checks: inventory unknown (`OCCUPANCY_INVENTORY_UNKNOWN`), closed
(`PROPERTY_CLOSED_FOR_STAY_DATE`), already sold out or overbooked (`OCCUPANCY_ALREADY_SOLD_OUT`),
baseline, fewer than 5 pairs, then the thresholds.

**Expected is not a forecast.** The Gate 4 baseline stays a historical level at one lead time and
gets no final-forecast column; the projection above exists only inside an evaluation.

## Reference ADR and revenue gap proxy

The reference ADR is chosen in this order and never invented: (1) the target's `adr_on_books` when
it is > 0 (`CURRENT_ON_BOOKS_ADR`); (2) the median of the > 0 `adr_on_books` of the baseline's
comparable snapshots (`HISTORICAL_COMPARABLE_MEDIAN_ADR`); (3) `NULL` with source `UNAVAILABLE`.
It is resolved for every evaluation.

    revenue_gap_proxy = rooms_at_risk x reference_adr          (HALF_UP, 2 dp; NULL without an ADR)

`rooms_at_risk` is `missing_rooms` for the pickup and `room_shortfall` for the occupancy. The proxy
exists only when the numeric condition holds (`TRIGGERED` or `SUPPRESSED_LOW_CONFIDENCE`). It is a
**gross exposure proxy**, not a loss prediction: it does not say how many of those rooms will be
missed, it has no loss probability, no cancellation or displacement effect and no margin, and no
name in the code, the schema or the docs calls it revenue loss or economic impact.

## Explainability

A `TRIGGERED` pickup exposes the actual and expected pickup, the historical pairs (each with its
provenance, its two snapshot ids and rooms), the missing rooms, the delta percent, the baseline and
final confidence, the thresholds and the proxy. A `TRIGGERED` occupancy risk exposes the current
rooms, the expected remaining net pickup, the forecast and expected final rooms, the inventory, the
forecast and expected occupancy, the gap in points, the shortfall, the confidence, the pairs and
the proxy. The payload is plain numbers and codes: no natural-language text and no recommendation.
`evidence_snapshot_ids` lists the target, its prior (pickup) and both endpoints of every pair.

## Decision values and displayed values

Every figure a detector compares with a threshold follows one path:

    CALCULATION VALUE  ->  THRESHOLD COMPARISON  ->  STATUS  ->  DISPLAY QUANTIZATION

The value that **decides** is the full-precision `Decimal` the calculation produced; the value
that is **shown** is that number quantized to two decimals (HALF_UP, away from zero) and never
decides anything. A pickup of -19.995 % is displayed as -20.00 but is not -20 % or worse; a gap
of 9.995 points is displayed as 10.00 but is below 10 points. The facts carry both, side by
side and named for what they are: `delta_percent` / `delta_percent_exact`, `forecast_occupancy` /
`forecast_occupancy_exact`, `expected_final_occupancy` / `expected_final_occupancy_exact`,
`occupancy_gap_pp` / `occupancy_gap_pp_exact` (`x` is for display, `x_exact` is the decision
value). The code lives in `precision.py`: quotients are computed in a dedicated 50-digit
`decimal` context (so nothing else in the process can change a result) and are never rounded
before they are compared. Rooms are exact by construction (integers and medians of integers),
the historical statistics are defined at two decimals by the Gate 4 algorithms, and the
confidence score is the authoritative two-decimal value of the confidence calculators, so the
gates (50 and 55) compare that score; none of them needs a separate decision value. The
revenue gap proxy is money and is quantized to two decimals by definition; it is never an
input of a threshold. A test replaces the display rounding with garbage and shows that no
status changes.

## Determinism, fingerprint, versions

The service reads no clock and every calculation is a pure function of stored rows; the same input
gives the same status and the same fingerprint, whatever the database row order. The fingerprint
is a SHA-256 of a canonical JSON of the decision type, the rules and pattern versions, the target
snapshot and baseline, the input metrics, the pairs used (ids and rooms), the thresholds, the
confidence, the reason codes, the reference ADR and proxy, and the status. Decimals are
serialised **non-lossily** (`canonical_text`: normalised, so `10`, `10.00` and `1E+1` are the
same text, but no digit is ever dropped), and the display-only figures are not hashed: two
inputs on opposite sides of a threshold never share a fingerprint, even when they display the
same. It never covers a timestamp, a memory address, a row order or a log line.

## Service, transaction, performance

`RevenueDecisionService(session, TenantContext)` (no FastAPI) offers `evaluate_pickup_low`,
`evaluate_occupancy_risk`, `evaluate_revenue_signals` (both) for one target and
`evaluate_snapshot_date` for every OBSERVED target of one snapshot day and stay range. It is
**read-only**: it writes nothing, never commits or rolls back, takes no advisory lock (nothing is
written, so nothing has to be serialised) and reads no clock. All the database work is **seven
statements whatever the number of targets**: the property, the data source, the targets, the
baselines, their comparables, the comparable snapshots (`list_by_ids`, primary key) and ONE keyed
read of every other endpoint (`list_by_keys`, the Gate 3 unique key). Two read-only repository
additions carry it: `BookingSnapshotRepository.list_by_ids` (and the ADR on the history row) and
`ExpectedRepository.list_comparables_for_baselines`. Tests measure 7 statements for 1 and for 60
targets and check the query plans.

## Tenant isolation

`TenantContext` is mandatory. Every read carries the workspace of the context, so another
workspace's target, baseline or snapshot does not exist for the service; a foreign target and an
unknown one raise the same error. Sources never mix: a second data source or another property of
the same workspace, with identical dates and wild values, changes nothing (tests).

## Golden scenario

"MASSERIA NINFA DEMO" extended once more: the Gate 2/3/4 world (golden, addendum, history; 154
snapshots; six baselines, all still intact) plus 138 synthetic revenue bookings and 140 snapshots
(50 observed, 90 reconstructed) for seven targets of the week of Monday 5 October 2026, one per
weekday, each seen 7 days before, each with six same-weekday comparables. The observed stays are
imported **day by day** (the observed service reads the bookings as they are at that instant), so
observed curves have a real pickup. Everything was computed independently of the application
(`tests/fixtures/revenue/generate_masseria_revenue_expected.py`, standard library only, exact
fractions; it reuses only the Gate 3 snapshot cell and the Gate 4 calendar helpers). The Sundays of
the Gate 4 world are valid comparables of the Sunday target: the worlds really merge.

| Target | Pickup | Occupancy | What it shows |
| ------ | ------ | --------- | ------------- |
| A Mon | `TRIGGERED` (7 vs 10, -30 %, 3 rooms) | `TRIGGERED` gap only (exactly 10.00 points, 2.00 rooms) | observed history; a comparable that lost rooms after the anchor (remaining -2); the wild final of the week before is not yet known |
| B Tue | `CLEAR` | `CLEAR` | 3 observed + 3 reconstructed comparables: mixed provenance |
| C Wed | `SUPPRESSED_LOW_CONFIDENCE` | `SUPPRESSED_LOW_CONFIDENCE` | very dispersed history, empty target: ADR from the historical median, expected final occupancy 105 % not clamped |
| D Thu | `CLEAR` | `INSUFFICIENT_DATA` | a NO_SHOW makes one final snapshot uncertain: 4 remaining pairs |
| E Fri | `NOT_APPLICABLE` near sold out | `CLEAR` | 19 rooms of 20 |
| F Sat | `NOT_APPLICABLE` expectation <= 0 | `TRIGGERED` by the 3 rooms alone (5 points) | weekly cancellations; 20 of 60 rooms |
| G Sun | `INSUFFICIENT_DATA` | `NOT_APPLICABLE` inventory unknown | no historical prior snapshots; no inventory |

Distractors that must never be used exist in the database: the same weekday in another season, a
stay after the target, the right stay date at lead times 6 and 8, and the other six weekdays at the
same lead time.

## Known limits (intentional)

* Thresholds (-20 %, 2 rooms, 10 points, 3 rooms) and confidence gates (50, 55) are product
  heuristics that need calibration with real customers; they are versioned constants in code.
* The projection is a median of historical net movement: no seasonality of the movement itself, no
  recency weighting, no groups or events, no cancellation model, no capacity normalisation.
* A final snapshot taken on the target's own snapshot day is treated as not yet known (strict): at
  a lead time of 7 days this costs the occupancy risk the most recent same-weekday pair, and at
  longer lead times more of them.
* Reconstructed endpoints are approximate by construction (Gate 3); they are penalised, never
  promoted.
* The reference ADR is the current on-books ADR of a partially sold night; it can differ from the
  rate the missing rooms would fetch. The proxy is an order of magnitude, not a forecast of revenue.
* Nothing is stored, so there is no history of evaluations and no deduplication yet.

# NINFA — Expected Engine v1 (Gate 4)

The first engine of the Decision Engine pipeline: **Expected rooms on books**, from historical
comparable snapshots. It answers exactly one question:

> "For a property like this, for this stay date and at this distance from the stay, how many
> rooms on the books would I normally have expected?"

**No alert, anomaly detection, pickup, forecast, impact, priority, recommendation, decision or AI
is built here.** Expected is the raw material Gate 5 will compare a real snapshot against.

Migration `0006_expected_engine`. Code: `services/api/app/modules/intelligence/expected/`. Entry
point: `BookingExpectedService` (`service.py`), framework-free and testable directly. No public
API, worker task or scheduler exists yet (authentication is a later gate).

```
TARGET CONTEXT -> HISTORICAL COMPARABLES -> QUALITY FILTERING -> ROBUST STATISTICS
              -> EXPECTED -> RANGE -> CONFIDENCE          (stop: no alert, no decision)
```

## Expected is not a forecast

Expected says: *"historically, for comparable stays, at 14 days from the stay, the typical level
was 21 rooms."* It does **not** say "you will finish with 28 rooms". It has no remaining pickup,
no cancellations model, no final occupancy, no velocity. The stored range is a **central
historical range** (P25 to P75 of the comparables), **not** a confidence interval or a prediction
interval; nothing in the code or schema is named or documented as one. The engine reads no clock:
it is a pure function of stored snapshots.

## The target and the lead time

The V1 target is an **OBSERVED** `BookingSnapshot` (`target_snapshot_local_date` = S,
`target_stay_date` = D), because operational decisions must start from a state NINFA really saw.
`lead_time_days = D - S`, and it must be `>= 0` (lead time 0, the stay date itself, is valid; a
snapshot of a night that was already over is not a valid target; the batch skips and counts such
targets, the single-target call refuses them).

A comparable must be seen at **exactly the same lead time**: 14 days before the stay is not
comparable with 3 days before it (the time pressure differs). For a target at lead 14, the
comparable of 17 October 2025 is the snapshot of 3 October 2025. **There is no interpolation**: a
stay date with no snapshot at exactly that distance has no comparable.

The calculation core (`HistoricalTarget`: a stay date and a lead time) is independent of any
snapshot, alert or decision, so the same mathematics can later serve backtests or "expected final"
without being duplicated (neither is implemented now).

## Comparable selection V1

A stored snapshot is a comparable when **all** hold, evaluated in this order (a rejection is
counted in a non-persisted diagnostics mapping):

1. same workspace, same property, **same data source** (sources are never mixed, as in Gate 3);
2. **no temporal leakage**: its stay date is strictly before D **and** its snapshot day is
   strictly before S (nothing that was not yet known);
3. same lead time (above);
4. within the **730-day horizon**: `D - 730 days <= stay date < D` (the lower bound is included);
5. **same weekday** as D (no weekday/weekend fallback, no silent widening);
6. **seasonal distance <= 42 days** (below);
7. quality: a snapshot with uncertainty (`uncertain_rooms > 0`) is never used.

Then the provenance policy, ordering and caps:

* **OBSERVED first.** With at least **5** usable OBSERVED comparables the baseline uses **only**
  them (a reconstruction is never added just to enlarge the sample).
* With fewer than 5, **all** the observed ones are **completed with clean
  RECONSTRUCTED_APPROXIMATE** snapshots (`uncertain_rooms = 0`), newest first, **up to the
  24-comparable sample limit** (not merely up to 5). A reconstruction fills the sample; it never
  displaces an observed one, and the confidence pays for it (provenance 60 instead of 100, caps
  85 and 65).
* A reconstruction **with uncertainty** never enters the numbers. Every calendar-eligible
  candidate of that kind is counted in `rejected_uncertain_count` (informative about the quality
  of the history, also when the observed sample was sufficient and no reconstruction was needed).
* The sample is ranked newest first by stay date (`recency_rank` 1 = most recent) and capped at
  the **24** most recent. Every selected comparable has the **same statistical weight**: recency
  only decides who is dropped by the cap (no weighting in V1).
* Zero is a real value: a comparable with `rooms_on_books = 0` enters the sample.

With the V1 constants at most 24 stay dates can qualify for one target (two seasonal windows of
about 12 same-weekday dates each) and a data source has exactly one snapshot per (stay date, lead
time), so the 24 cap is a structural guarantee: it can only bind on hand-built input, and is
tested there. The query that fetches the candidates asks for the exact `(snapshot day, stay date)`
keys the calendar allows (a few dozen), never for a scan of the history.

### Seasonal window

`+-42 calendar days` around the month/day of the target, **whatever the year**. The distance
between two month/days is computed on the two calendars a year can have and the **smaller** result
is used:

* a **common** year (2001: 365 positions, no 29 February) and a **leap** year (2000: 366
  positions, 29 February at position 60);
* on each calendar the distance is circular: `min(|a - b|, length - |a - b|)`, so **31 December
  and 1 January are 1 day apart** and a New Year target sees late December and January;
* a pair that includes 29 February exists only in the leap calendar and is measured there;
* so the distance is the true calendar distance in a common year or in a leap year, whichever is
  smaller: **28 February <-> 1 March = 1, 28 February <-> 29 February = 1, 29 February <-> 1 March
  = 1**, 27 February <-> 10 April = 42 (the 42 days a calendar shows in a common year);
* it is an integer, symmetric and deterministic, independent of the year of either date, and needs
  no library and no special case for the year boundary. A test checks every pair of month/days
  against plain date arithmetic on real years.

## Statistics (exact `Decimal`, no float)

For the sample `x1..xn` of `rooms_on_books`:

* **EXPECTED = median** (not the mean): the middle value for odd `n`, the `Decimal` mean of the two
  middle values for even `n` (`10, 12, 14, 16` -> `13.00`). The median is fractional when it has
  to be (`10, 11` -> `10.50`) and is **never rounded to an integer**; Gate 5 decides how to read a
  delta.
* **Range** `expected_lower` / `expected_upper` = historical **P25 / P75**, by **linear
  interpolation** over the sorted sample at index `(n - 1) * p`:
  `x[lo] + (position - lo) * (x[hi] - x[lo])`, `lo = floor(position)`, `hi = min(lo + 1, n - 1)`.
  With integer rooms and `p` in {0.25, 0.75} every value is a multiple of 0.25, exact in two
  decimals. `n = 5`: positions 1 and 3; `n = 6`: 1.25 and 3.75; `n = 7`: 1.5 and 4.5; `n = 8`:
  1.75 and 5.25.
* **IQR = P75 - P25**, stored.
* **No outlier removal** (no z-score, winsorisation or sigma clipping): the robustness of V1 is
  the median and the quartiles themselves.

## Confidence V1 (baseline confidence)

The confidence of a **historical baseline**, not the general Decision Confidence. A transparent,
versioned **heuristic**, not a statistical truth. `Decimal` throughout, components at full
precision, only the final score rounded (HALF_UP, 2 decimals):

| Component | Formula |
| --------- | ------- |
| sample score | `min(100, sample_size / 12 * 100)` (5 -> 41.67, 6 -> 50, 9 -> 75, 12+ -> 100) |
| provenance score | `(observed * 100 + reconstructed * 60) / sample_size` |
| stability score | `max(0, 100 - 50 * IQR / max(expected, 1))` (IQR 0 -> 100, IQR = expected -> 50, IQR = 2 x expected -> 0) |
| **confidence** | `0.40 * sample + 0.35 * provenance + 0.25 * stability` |

Caps, applied **after** the formula: any reconstructed comparable used -> at most **85**; no
observed comparable at all -> at most **65**. Bands: **HIGH** `>= 80`, **MEDIUM** `>= 60`,
**LOW** below 60. A `READY` baseline can be `LOW`: Gate 4 does not hide it, Gate 5 decides what
may be shown.

## INSUFFICIENT_DATA

With **fewer than 5** usable comparables the status is `INSUFFICIENT_DATA` and **no number is
produced**: `expected`, `lower`, `upper` and `iqr` are `NULL`, `confidence_score` is `0` and
`confidence_band` is `NULL` (never an artificial `LOW`). A median and quartiles of 4 values are
mathematically computable and are deliberately **not** produced: a figure without a reliable
sample is not an Expected. The comparables that were found (0 to 4) are still stored, so the
record explains why. The database enforces the coherence: `READY` requires every statistic, a band
and `sample_size >= 5`; `INSUFFICIENT_DATA` requires all of them absent, score 0 and
`sample_size < 5`.

## Persistence and traceability

`booking_expected_baselines` (one row per target and calculation version) and
`booking_expected_comparables` (the snapshots actually used; not an opaque JSON of ids):

| Baseline | |
| -------- | - |
| identity | `workspace_id`, `property_id`, `data_source_id`, `target_snapshot_id`, `target_origin` (always `OBSERVED`) |
| target | `target_snapshot_local_date`, `target_stay_date`, `lead_time_days` |
| result | `status`, `expected_rooms_on_books`, `expected_lower`, `expected_upper`, `iqr` (`NUMERIC(12,2)`, nullable) |
| sample | `sample_size`, `observed_sample_size`, `reconstructed_sample_size`, `rejected_uncertain_count` |
| confidence | `confidence_score` (`NUMERIC(5,2)`, 0 for insufficient), `confidence_band` (nullable) |
| provenance | `method` (`MEDIAN_SAME_DOW_SEASONAL_WINDOW`), `calculation_version` (`booking-expected-v1`, not the app version), `comparable_fingerprint`, `created_at` |

A comparable carries `baseline_id`, `snapshot_id`, `rooms_on_books`, `origin` (copies of the
snapshot's own values) and `recency_rank`. Rejected comparables are **not** persisted (only
`rejected_uncertain_count` and the transient diagnostics), and no audit framework exists.

For every baseline the stored rows are enough to explain it: target, lead time, method, expected,
range, IQR, sample sizes, confidence, and the comparables really used with their origin and rank.

## Idempotency, immutability, fingerprint

* `UNIQUE (workspace_id, target_snapshot_id, calculation_version)`. Both tables have **no
  `updated_at`** and a `BEFORE UPDATE` trigger that refuses every update (`DELETE` is not blocked;
  retention is a later gate).
* Same target, same comparables, same result -> **idempotent no-op** (the same baseline id is
  returned). Same target and version but a different comparable set or result ->
  **`EXPECTED_BASELINE_CONFLICT`** (HTTP-style 409): nothing is stored, nothing overwritten. Any
  change of the rules is a new `calculation_version`, never an edit.
* **Consequence to know**: a baseline records what was known when it was calculated. If history
  arrives afterwards (for example a reconstruction adds comparables), re-running the same target
  is a conflict, and an `INSUFFICIENT_DATA` baseline is not silently upgraded. Run Expected right
  after the day's observation.
* `comparable_fingerprint` = SHA-256 of the canonical JSON of: the target context (data source,
  target snapshot, dates, lead time), method, calculation version, the ordered comparables
  (rank, snapshot id, rooms, origin) and the provenance counts. It excludes `created_at`, row ids
  and any runtime metadata.

## Transaction, locking, performance

`BookingExpectedService.calculate_for_target(property_id, data_source_id, target_snapshot_id)` and
`calculate_for_snapshot_date(property_id, data_source_id, snapshot_local_date, stay_date_start,
stay_date_end)` (every OBSERVED target of a snapshot day and stay range, one transaction). Pass a
session with no uncommitted work: the service commits it (and rolls it back on failure). One run:
validate the property and data source -> take the per-data-source advisory lock (`app/db/locks.py`,
shared with the import and the snapshot services) -> fetch **all** the comparable snapshots the
batch could need in **one statement** (a join with a `VALUES` list of exact keys, served by the
Gate 3 unique-key index) -> calculate in memory -> compare with what is stored -> insert baselines
and comparables (one `executemany` each) -> commit.

The number of statements does not depend on the number of targets: a batch of 60 targets with up to
24 comparables each takes 8 statements plus the commit (properties, data source, targets, lock,
candidates, existing baselines, baselines, comparables); a test asserts the count is the same for 3
and 60 targets. Errors: `EXPECTED_TARGET_NOT_OBSERVED`, `EXPECTED_TARGET_NOT_FOUND` (an unknown and
a foreign target are indistinguishable), `EXPECTED_INVALID_TARGET` (`negative_lead_time`,
`data_source_mismatch`, `property_mismatch`), `EXPECTED_INVALID_PROPERTY`,
`EXPECTED_INVALID_DATA_SOURCE`, `EXPECTED_INVALID_RANGE`, `EXPECTED_BASELINE_CONFLICT`.

## Tenant integrity

Composite foreign keys, all `RESTRICT` (ADR 0006): a baseline references its property, its data
source and its **target snapshot** `(workspace, property, data_source, id, origin)`; a comparable
references its baseline `(workspace, property, data_source, id)` and its snapshot `(workspace,
property, data_source, id, origin)`. So: a baseline and its comparables share one workspace,
property and data source, even through raw SQL; a comparable's `origin` cannot differ from its
snapshot's; and `target_origin` is `CHECK`ed to `OBSERVED`, so the **database itself refuses a
reconstruction as a target**. The foreign-key targets need one extra unique constraint on the Gate 3
table (`uq_booking_snapshots_source_id_origin`, an addition that alters nothing existing).

## Indexes

Baselines: the `UNIQUE` above (the lookup by target snapshot), `ix_..._snapshot_date`
`(workspace, data_source, target_snapshot_local_date)`, `ix_..._stay_date` `(workspace,
data_source, target_stay_date)`, and a unique `(workspace, property, data_source, id)` that exists
only as the comparables' foreign-key target. Comparables: `UNIQUE (workspace, baseline, snapshot)`
and `UNIQUE (workspace, baseline, recency_rank)`, whose prefix `(workspace, baseline)` already
serves "the comparables of a baseline in rank order" (no separate index). Candidate retrieval uses
the Gate 3 unique key `(workspace, data_source, snapshot_local_date, stay_date)`.

## Golden scenario

"MASSERIA NINFA DEMO" extended: the Gate 2/3 bookings plus 252 synthetic history bookings, 154
snapshots (42 observed since an "observation start" of 1 April 2026, 112 reconstructed), six
targets, each on its own weekday: A observed only with low dispersion (and distractors: wrong lead
time 13 and 15, same weekday out of season, same season wrong weekday, the future, a stay older
than 730 days); B observed only with high dispersion (a LOW-confidence baseline); C three observed
plus reconstructions, two uncertain reconstructions rejected; D `INSUFFICIENT_DATA`; E 24 comparables of
which 12 have zero rooms (0.50 median); F reconstructed only (confidence capped at 65). The
expected file was computed **independently of the application code**
(`tests/fixtures/expected/generate_masseria_expected_expected.py`, standard library only, exact
fractions; it also recomputes the snapshots), and includes every baseline, its comparables and a
checksum of the snapshot grid. A, B and D were also checked by hand (see the fixtures README).

## Known limits (intentional)

* **Capacity is not normalised**: the statistic is `rooms_on_books`. If the property's capacity
  changes materially, the V1 baseline becomes less comparable; it is not corrected with hidden
  heuristics (a normalisation is a product policy for a later gate).
* Only internal data: no events, holidays, weather, competitor rates or market demand.
* One weekday, one season, one lead time: no fallback and no widening. A quiet property simply gets
  `INSUFFICIENT_DATA` more often.
* Observed history is short at the start (NINFA only observes from the day it is connected):
  early baselines rely on reconstructions, penalised by the confidence and capped.
* Reconstructions are approximate by construction (Gate 3): they use today's booking state.
* The confidence weights and thresholds are a heuristic that will need calibration with real data.
* No weighting by recency, no outlier removal, no dedicated handling of groups or events.
* A conflict on re-run (above) means a corrected history needs a new `calculation_version`.
* No retention policy for baselines yet; no public API, worker task or scheduler.

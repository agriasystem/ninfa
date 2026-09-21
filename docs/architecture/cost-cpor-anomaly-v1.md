# NINFA — Cost CPOR Anomaly Detection v1 (Gate 7)

Scope: ONE explicit detector, `COST_CPOR_ANOMALY`, that answers a single question: *is the cost per
occupied room of a cost category, in one currency, on one concluded calendar month, materially above
what comparable history says?* It reads the canonical invoice lines (Gate 6) and the lead-time-0
booking snapshots (Gate 3) and returns a typed, immutable, auditable **evaluation**. Nothing is
persisted, nothing is shown, nothing is recommended: this gate ends at the evaluation. Decision,
priority, recommendation, decision memory, AI, budgeting, accruals, supplier price anomaly and
procurement optimisation belong to later gates (or to no gate yet).

    COST DATA + OCCUPANCY DENOMINATOR -> PERIOD METRIC -> HISTORICAL EXPECTATION -> DETECTION
    (Gate 6)    (Gate 3)                                                     (Gate 7 stops here)

Code: `services/api/app/modules/intelligence/costs/` (`periods`, `precision`, `types`, `errors`,
`occupancy`, `repository`, `aggregation`, `selection`, `statistics`, `confidence`, `fingerprint`,
`detector`, `service`). Versions: rules `cost-cpor-anomaly-v1`, metric `cost-period-metric-v1`,
expected method `cost-cpor-expected-v1` (never the application version, a git hash or a migration
id). Migration head is still `0007_invoice_supplier_ingestion`: this gate adds **no table, no
migration, no API route, no worker task and no dependency**. Decisions:
[ADR 0013](adr/0013-cost-cpor-anomaly-v1.md).

## CPOR V1 — the definition

    CPOR (cost per occupied room) = net category cost of the calendar month
                                    / occupied room nights of the same month

* **Cost** is the *signed* sum of `InvoiceLine.line_total` of the canonical lines whose invoice date
  falls in the month, of one category and one currency. Credit notes are already negative (Gate 6)
  and are used as they are, never re-inverted. `absolute_cost_exposure` is the sum of
  `abs(line_total)`; it is used for weights and coverage, never as the numerator.
* **Occupied room nights** is the sum, over every day D of the month, of `rooms_on_books` of the
  **lead-time-0** snapshot of that day (the snapshot taken on day D for stay date D).
* This denominator is an **operating proxy**. NINFA has no consolidated PMS "actual occupied rooms":
  a Gate 3 snapshot is an observation of the booking table (or a reconstruction from it). It is
  therefore documented, named (`LEAD_TIME_0_ROOMS_ON_BOOKS_PROXY`) and versioned as a proxy and it is
  NOT a certified actual occupancy, not accounting occupancy and not the final PMS figure.
* Cost is attributed by **invoice date**, a policy called `INVOICE_DATE_ATTRIBUTION`. There is no
  service period, no competence, no accrual, no prepayment allocation: see "Known limits".
* Only **concluded** calendar months make sense. The service reads no clock: the target month is
  always passed in, so a run can be replayed and back-tested. It is the caller's job not to ask for
  the month in progress.
* Values are exact `Decimal` (a dedicated 50-digit context, no `float`); the display value is that
  number rounded to two decimals HALF_UP and never decides anything.

A net cost of zero or below is a **valid** CPOR (the month's credit notes cancelled the invoices):
it is `CLEAR`, not `NOT_APPLICABLE`.

## The target

A target is identified by **workspace, property, booking data source, calendar month, cost category
and currency**. The service takes a `TenantContext`; the property must exist in that workspace and
not be archived (`COST_INVALID_PROPERTY`, a foreign and an unknown id are the same error). The
**booking data source is always passed explicitly and never chosen automatically**: the denominator
must have a stated provenance. It must be a `BOOKINGS` data source, of the same workspace and
property, and active (`COST_BOOKING_DATA_SOURCE_INVALID`, reason code `BOOKING_DATA_SOURCE_INVALID`).
Costs are **not** filtered by their own data source: since Gate 6 an invoice's identity is
cross-source, and the same invoice imported twice from two sources is one invoice.

## Cost period metric (`CostPeriodMetric`)

A non-persistent, immutable value (`cost-period-metric-v1`) with its own deterministic
`calculation_fingerprint`. Fields: workspace, property, booking data source, period start/end, cost
category, currency; `net_cost`, `absolute_category_cost`, `total_absolute_cost`,
`classified_absolute_cost`; `classification_coverage_pct` and
`weighted_classification_confidence`; `occupied_room_nights`, `observed_day_count`,
`reconstructed_day_count`, `missing_day_count`, `uncertain_day_count`,
`occupancy_provenance_score`; `invoice_count`, `line_count`, `credit_note_line_count`,
`credit_note_cost`; `cpor`; `status`, `reason_codes`, `calculation_version`, `cost_attribution` and
`occupancy_proxy`. Metric statuses: `READY`, `NO_COST_DATA`, `INCOMPLETE`, `ZERO_OCCUPANCY`,
`LOW_CLASSIFICATION_COVERAGE`. Every decision figure has an `x_exact` value (the one that decides) and
an `x_display` value (two decimals, presentation only).

The status is decided in this order, and the first that applies wins:

1. no line of the currency in the month -> `NO_COST_DATA / COST_CURRENCY_NOT_PRESENT` (nothing was
   invoiced: **not** a zero cost);
2. lines of the currency but none of the category -> `NO_COST_DATA / COST_CATEGORY_NOT_PRESENT`;
3. the occupancy of the month is incomplete -> `INCOMPLETE / OCCUPANCY_PERIOD_INCOMPLETE`;
4. no occupied room night -> `ZERO_OCCUPANCY / ZERO_OCCUPIED_ROOM_NIGHTS` (the division is never
   attempted);
5. classification coverage undefined or below 70 % -> `LOW_CLASSIFICATION_COVERAGE`;
6. otherwise `READY` and the CPOR is computed.

## Occupancy denominator

* **Every day of the month needs a lead-time-0 snapshot.** A missing snapshot is not zero rooms: it
  is an unknown, the month is `INCOMPLETE` and the metric says `OCCUPANCY_PERIOD_INCOMPLETE`. A
  snapshot with `rooms_on_books = 0` is a real, valid zero.
* A snapshot with `uncertain_rooms > 0` invalidates the month: uncertain rooms are never subtracted
  and never estimated (the Gate 3 cancelled-without-date and no-show cases end up here).
* `OBSERVED` and `RECONSTRUCTED_APPROXIMATE` (with no uncertainty) snapshots are both admitted, and
  the mix is measured: `provenance = (observed_days x 100 + reconstructed_days x 60) / days`.
* A month with zero occupied room nights is `NOT_APPLICABLE / ZERO_OCCUPIED_ROOM_NIGHTS`.
* One keyed read (`list_by_keys`, the Gate 3 unique key) covers the target and every candidate
  month: a query per day is never issued.

## Classification quality

OTHER is a data quality bucket, not an operating cost category (the Gate 6 `UNCLASSIFIED`,
confidence 0). Over the same currency, all categories:

    classification coverage = SUM(abs) of the lines that are not OTHER / SUM(abs) of all lines x 100
    weighted classification confidence = SUM(abs x classification confidence) / SUM(abs),
                                         over the classified (not OTHER) lines

* A target category `OTHER` is `NOT_APPLICABLE / COST_CATEGORY_OTHER_NOT_ACTIONABLE`, always: it is
  not a comparable and it is not evaluated.
* A month with a classification coverage below **70 %** is `INSUFFICIENT_DATA /
  COST_CLASSIFICATION_COVERAGE_LOW` as a target and is **excluded** from the comparables (and
  counted: `rejected_low_classification_count`). `abs` is used so that +1000 and -1000 never look
  like "no activity".

## Historical comparable selection

For a target month T, a month M is a candidate comparable only when all of these hold:

* strictly before T, and at most 36 months back (exactly 36 is included);
* **anti-leakage**: `M.period_end < T.period_start`: nothing of the target or of the future can
  enter the baseline;
* the same cost category and the **same exact currency**;
* the seasonal window: the circular month-of-year distance is at most 2 (a July target compares
  with May..September; January and December are 1 apart);
* its metric is `READY` (cost lines, complete non-zero occupancy, coverage >= 70 %).

A candidate that is not READY is **counted by the reason it was rejected**, never silently dropped
(`rejected_no_cost_data_count`, `rejected_low_classification_count`,
`rejected_incomplete_occupancy_count`, `rejected_zero_occupancy_count`).

Observed-first, the Gate 4 / Gate 5 philosophy. A `FULLY_OBSERVED_PERIOD` is an eligible month with no
reconstructed day. With at least 5 of them, only they are used; otherwise every fully observed month
is kept and the newest clean reconstructed months complete the sample. Most recent first, at most 12,
at least 5: fewer than 5 is `INSUFFICIENT_DATA / COMPARABLE_SAMPLE_INSUFFICIENT` and no baseline is
produced. The result does not depend on the order in which rows are read.

## Expected CPOR (`cost-cpor-expected-v1`)

`expected CPOR` is the **median** of the comparable CPORs. `P25` and `P75` use linear interpolation at
position `(n - 1) x p` of the ordered sample; `IQR = P75 - P25`; the **upper fence** is
`P75 + 1.5 * IQR`. All in `Decimal`, no `float`, no outlier removal, values may be negative or zero.
`expected CPOR <= 0` is `NOT_APPLICABLE / EXPECTED_CPOR_NON_POSITIVE`: a percentage of nothing, or of
a negative baseline, is not defined and the division is never attempted.

    delta_cpor                      = actual CPOR - expected CPOR
    delta_percent_exact             = delta_cpor / expected CPOR x 100
    expected_cost_for_target_volume = expected CPOR x target occupied room nights
    cost_gap_proxy_exact            = max(0, target net cost - expected_cost_for_target_volume)

## COST_CPOR_ANOMALY

The rule needs ALL FOUR conditions (relative materiality AND a real departure from the historical
distribution AND absolute materiality; **AND, never OR**):

| Condition | Threshold (constant in code, never in the database) |
| --------- | --------------------------------------------------- |
| the CPOR is above the expected one | `actual > expected` |
| relative materiality | `delta_percent >= CPOR_RELATIVE_THRESHOLD = 20` |
| robust upper fence | `actual >= P75 + 1.5 * IQR` (`CPOR_IQR_MULTIPLIER = 1.5`) |
| absolute materiality | `cost_gap_proxy >= CPOR_ABSOLUTE_GAP_THRESHOLD = 100` currency units |

Every comparison is on the **full-precision** value the calculation produced, never on the two-decimal
display: 19.999999 % displays as 20.00 and does not pass 20. With the numeric rule true, a final
confidence of at least `MIN_CONFIDENCE = 55` is `TRIGGERED` and below it `SUPPRESSED_LOW_CONFIDENCE`
(reason `LOW_CONFIDENCE` only; the conditions that held stay in its facts).

Checks run in this order and the first that applies decides:

1. category `OTHER` -> `NOT_APPLICABLE / COST_CATEGORY_OTHER_NOT_ACTIONABLE`;
2. no cost of the currency / category -> `NOT_APPLICABLE / COST_CURRENCY_NOT_PRESENT` or
   `COST_CATEGORY_NOT_PRESENT`;
3. incomplete occupancy -> `INSUFFICIENT_DATA / OCCUPANCY_PERIOD_INCOMPLETE`;
4. zero occupied room nights -> `NOT_APPLICABLE / ZERO_OCCUPIED_ROOM_NIGHTS`;
5. coverage below 70 % -> `INSUFFICIENT_DATA / COST_CLASSIFICATION_COVERAGE_LOW`;
6. fewer than 5 comparables -> `INSUFFICIENT_DATA / COMPARABLE_SAMPLE_INSUFFICIENT`;
7. expected CPOR <= 0 -> `NOT_APPLICABLE / EXPECTED_CPOR_NON_POSITIVE`;
8. the numeric rule and the confidence gate -> `TRIGGERED`, `SUPPRESSED_LOW_CONFIDENCE` or `CLEAR`
   (`CLEAR_WITHIN_EXPECTED_RANGE`).

The comparables are only built (and only paid for) when the target itself is fit to be judged.

The five statuses are never interchangeable: `TRIGGERED` (the rule holds and the confidence is
sufficient), `CLEAR` (the data is sufficient and the rule does not pass), `INSUFFICIENT_DATA` (not
enough reliable data), `NOT_APPLICABLE` (the rule has no meaning in this context) and
`SUPPRESSED_LOW_CONFIDENCE` (the numeric rule holds but NINFA is not confident enough to show it).
Reason codes (stable names, never prose): `TRIGGER_CPOR_ANOMALY`, `CLEAR_WITHIN_EXPECTED_RANGE`,
`COST_CATEGORY_OTHER_NOT_ACTIONABLE`, `COST_CLASSIFICATION_COVERAGE_LOW`,
`COST_CLASSIFICATION_COVERAGE_UNDEFINED`, `OCCUPANCY_PERIOD_INCOMPLETE`, `ZERO_OCCUPIED_ROOM_NIGHTS`,
`EXPECTED_CPOR_NON_POSITIVE`, `COMPARABLE_SAMPLE_INSUFFICIENT`, `LOW_CONFIDENCE`,
`COST_CURRENCY_NOT_PRESENT`, `COST_CATEGORY_NOT_PRESENT` and, at request level only,
`BOOKING_DATA_SOURCE_INVALID`.

## Confidence

    sample_score         = min(100, n / 8 x 100)
    provenance_score     = mean of the occupancy provenance scores of the months used
    classification_score = mean of their weighted classification confidences, weighted by each
                           month's absolute category cost (plain mean if every weight is zero)
    stability_score      = max(0, 100 - 50 x IQR / max(|expected CPOR|, 0.01))

    baseline_confidence = 0.35 x sample + 0.25 x provenance + 0.20 x classification
                          + 0.20 x stability                              (HALF_UP, 2 decimals)

Caps, after the formula and before the final minimum: at most **85** if any used month has a
reconstructed day; at most **65** if no used month is fully observed.

    target_quality   = 0.50 x target occupancy provenance + 0.50 x target weighted classification confidence
    final confidence = MIN(baseline confidence, target quality)                (never the average)

A decision is only as reliable as its weakest input. Like the Gate 4 / Gate 5 confidences it is a
transparent, versioned heuristic, not a statistical claim. A numeric rule that holds with a final
confidence below 55 is `SUPPRESSED_LOW_CONFIDENCE`.

## Cost gap proxy

`cost_gap_proxy` is the **gross cost gap proxy**: how much of the month's net cost exceeds the
expected CPOR applied to the month's own volume. It is *not* a loss, *not* a saving and *not*
recoverable: it says nothing about why the CPOR moved, how much of it was avoidable, or what a
different supplier would have charged, and no name in the code, the schema or the docs calls it a
loss, a saving, a recoverable amount or an economic impact. It exists only when the target had a
baseline; it is kept in the facts of a suppressed evaluation for the audit and never shown.

## Currency handling

NINFA never converts currencies: there is no FX rate, no FX client, no assumed base currency. A
target is one currency; the comparables are of the **same exact currency**; a USD month never enters
a EUR baseline. Currencies are never summed: coverage, totals and weights are computed inside one
currency.

## Explainability

A `TRIGGERED` evaluation exposes only facts and codes (no generated text, no recommendation): the
period, category and currency; net, absolute and credit-note cost, invoice and line counts; occupied
room nights, observed / reconstructed / missing / uncertain days and the provenance score;
classification coverage and confidence; the CPOR; every comparable month with its own facts; the
expected CPOR, P25, P75, IQR and upper fence; delta, delta percent, expected cost at the target
volume and the cost gap proxy; the four boolean conditions; the five confidence components, the
cap, the target quality and the final confidence; the thresholds; the reason codes; the rule,
metric and method versions; and the deterministic fingerprint.

## Determinism, fingerprint, versions

The service reads no clock and every calculation is a pure function of stored rows: the same input
gives the same status and the same fingerprint, whatever the database row order. The fingerprint is
a SHA-256 of a canonical JSON of the decision type, the rules, metric and method versions, the target
identity, the target metric, the comparables used, the statistics, the thresholds, the confidence,
the reason codes and the status. Decimals are serialised **non-lossily** (`canonical_text`: `10`,
`10.00` and `1E+1` are the same text, but no digit is ever dropped); display values and timestamps
are not hashed. Two inputs on opposite sides of a threshold never share a fingerprint.

## Service, transaction, performance

`CostDecisionService(session, TenantContext)` (no FastAPI) offers `build_period_metric`,
`evaluate_cpor_anomaly` and `evaluate_month` (several categories of one month and currency, in one
batch). It is **read-only**: it writes nothing, never commits or rolls back, takes no advisory lock,
reads no clock and never resolves a `SupplierResolutionReview` (a pending review does not block
anything). All the database work is a fixed handful of statements whatever the number of categories,
invoices, days or comparable months: the property, the data source, ONE grouped aggregate of the
canonical invoice lines of the whole history window and ONE keyed read of the lead-time-0 snapshots
of every month involved. There is no query per day, invoice or comparable, and tests measure the
count for one category and for a whole batch.

## Tenant isolation

`TenantContext` is mandatory. Every read carries the workspace of the context, so another
workspace's property, data source, invoice or snapshot does not exist for the service; a foreign id
and an unknown one raise the same error. Data sources of the same workspace and other properties
never mix (tests).

## Golden scenario

"MASSERIA NINFA DEMO — COST DATA V1", extended: the real chain **Booking -> Snapshot -> Cost Ingestion
-> Cost Intelligence**, no bypass of the canonical models. 492 bookings imported through the Gate 2
import service (one per day, rooms per day by design); 12 months **reconstructed** and 5 months
**observed** day by day by the Gate 3 services (one day nobody observed, one uncertain day, one closed
month); 79 invoices and 95 lines imported by the Gate 6 service from seven FatturaPA XML files (two
currencies) and one structured CSV of a second data source. Everything was computed independently of
the application (`tests/fixtures/costs/generate_masseria_cost_intelligence_expected.py`, standard
library only, exact `Fraction` arithmetic; it reuses only the FatturaPA/CSV file *writers* of the
Gate 6 fixture generator) and the whole canonical payload of every evaluation is compared.

| Case | Target | Status | What it shows |
| ---- | ------ | ------ | ------------- |
| A | LAUNDRY 2026-08 EUR | `TRIGGERED` | CPOR 6.00 vs expected 3.25, +84.6 %, fence 3.75, gap 1119.25, 10 comparables (1 observed, 9 reconstructed), confidence capped at 85 |
| B | LAUNDRY 2026-07 EUR | `CLEAR` | a credit note (TD04) lowers the net cost; an invoice dated 31 July stays in July |
| C | UTILITIES 2026-08 EUR | `CLEAR` | a high delta inside a volatile history: under the upper fence |
| D | SOFTWARE 2026-08 EUR | `CLEAR` | +33 % over a tight history, gap below 100 |
| E | CLEANING 2026-08 EUR | `SUPPRESSED_LOW_CONFIDENCE` | every condition holds, a weak baseline (52.97 < 55) |
| F | MAINTENANCE 2026-08 EUR | `INSUFFICIENT_DATA` | fewer than 5 comparables |
| G | LAUNDRY 2026-06 EUR | `INSUFFICIENT_DATA` | classification coverage below 70 % |
| H | OTHER 2026-08 EUR | `NOT_APPLICABLE` | `OTHER` is not actionable |
| I | LAUNDRY 2026-05 EUR | `INSUFFICIENT_DATA` | one day nobody observed: not zero rooms |
| J | LAUNDRY 2026-10 EUR | `NOT_APPLICABLE` | a closed month: zero occupied room nights |
| K | OTA_COMMISSIONS 2026-08 EUR | `NOT_APPLICABLE` | credit notes make the expected CPOR negative |
| M | (inside A) | reconstructed months | clean reconstructed months enter the baseline and lower its provenance |
| N | (inside A) | an uncertain month | 2025-09 has an uncertain snapshot: it never enters a baseline |
| O | LAUNDRY 2026-08 USD | `INSUFFICIENT_DATA` | EUR and USD are never mixed or converted |
| P, Q | TRANSPORT 2026-08 / LAUNDRY 2026-09 | `NOT_APPLICABLE` | no category / no currency in the month: not a zero cost |

Distractors that must never be used exist in the database: snapshots of lead time above 0, a costs
data source that is not a denominator, invoices of a second currency, other seasons and a month
that ends after the target starts.

## Known limits (intentional)

* **Invoice-date attribution.** A cost belongs to the month of its invoice date, not to the month it
  was incurred: a December electricity bill invoiced in January weighs on January, an annual
  software fee weighs on one month, and there is no accrual, no service period and no prepayment
  allocation. A cost model of competence belongs to a later gate.
* **The denominator is an operating proxy** (lead-time-0 `rooms_on_books`), NOT a certified actual
  occupancy: a stay that changes after its own night, a no-show or a walk-in the booking table does
  not know are outside it. Reconstructed days are approximate by construction (Gate 3): they are
  admitted, downgraded and capped, never promoted.
* Thresholds (20 %, 100 currency units, 1.5 x IQR, 70 % coverage, 55 confidence) and the confidence
  weights are product heuristics that need calibration with real customers; they are versioned
  constants in code, not database settings.
* Classification quality depends on Gate 6: only six categories have rules, the others are
  classified only by an explicit column or by a supplier default. A hotel whose costs are mostly
  `OTHER` gets `INSUFFICIENT_DATA`, by design.
* Costs that are fixed (rent, salaries, software) do not scale with occupancy: their CPOR rises when
  occupancy falls. V1 does not separate fixed from variable costs.
* No FX conversion: a hotel invoiced in two currencies has two independent histories.
* Evaluations are not persisted: there is no history of evaluations, no deduplication and no
  Decision yet.

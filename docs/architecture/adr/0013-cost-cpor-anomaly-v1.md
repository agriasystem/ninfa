# 0013 — Cost CPOR Anomaly Detection V1: one detector, an operating-proxy denominator, no persisted Decision

**Status:** accepted (Gate 7)

## Context
Gate 6 gave NINFA canonical suppliers, invoices and classified invoice lines; Gates 3-5 gave it
booking snapshots, baselines and revenue evaluations. The first cost question a hotelier asks is
"did this month cost more per occupied room than it normally does?". Answering it means dividing a
number that is only *filed* by date (an invoice) by a number that is only *observed* (a booking
snapshot), and comparing the result with comparable history. Each of the two has limits the answer
must not hide. Three temptations must be resisted: presenting an operating proxy as an accounting
truth, building a generic anomaly engine before a second detector exists, and dressing a gross
difference up as a saving.

## Decision
1. **Calendar month.** The period of a CPOR is a calendar month, and only a concluded one. A month
   is the natural cycle of a supplier invoice and of a hotel's management accounts, long enough to
   smooth the day-to-day noise of occupancy and short enough to react. There are no weeks, no
   rolling windows and no custom periods in V1. The service reads no clock: the target month is an
   input, so every run can be replayed and back-tested.
2. **Invoice-date attribution.** A cost belongs to the month of its invoice date
   (`INVOICE_DATE_ATTRIBUTION`, named and versioned). It is the only date every canonical invoice is
   guaranteed to have (Gate 6); a service period is not, and inferring one would be a guess. The
   consequence (a bill invoiced in January for December weighs on January) is a documented limit.
3. **No accrual model.** No competence, no accrual, no deferral, no prepayment allocation and no
   spreading of an annual fee across months. That is accounting, it needs data NINFA does not have,
   and doing it half way would hide the limit instead of stating it.
4. **Lead-time-0 denominator.** The occupied room nights of a month are the sum of `rooms_on_books`
   of the snapshot taken on the day of each stay night, for that night (snapshot day = stay date).
   It is the last thing the booking table said about a night, the closest available to "what really
   happened" without a PMS. It is an **operating proxy**, named as such
   (`LEAD_TIME_0_ROOMS_ON_BOOKS_PROXY`), and never called certified, accounting or final occupancy.
5. **A missing snapshot is not zero.** Every day of the month needs a lead-time-0 snapshot. A day
   without one is an unknown, not an empty hotel: dividing by a partial denominator would inflate
   the CPOR, and treating the gap as zero would do the same. The month is `INCOMPLETE` and the answer
   is `INSUFFICIENT_DATA / OCCUPANCY_PERIOD_INCOMPLETE`. A snapshot with uncertain rooms invalidates
   the month for the same reason: uncertain rooms are never subtracted and never estimated. A real
   zero (a closed month) is a valid denominator that makes the CPOR undefined
   (`ZERO_OCCUPIED_ROOM_NIGHTS`), not a division.
6. **Reconstructed clean occupancy is admitted, downgraded.** A `RECONSTRUCTED_APPROXIMATE`
   snapshot with no uncertainty is usable (excluding it would leave a new customer with no
   history at all) but it is worth less than an observation: provenance counts 60 against 100, a
   baseline with any reconstructed month is capped at 85 and one with no fully observed month at
   65. Observed-first: with at least five fully observed comparables only they are used.
7. **70 % classification coverage.** A month whose classified (not `OTHER`) absolute cost is below
   70 % of its total is not judged, and is not used as a comparable: a CPOR of a category is only as
   meaningful as the classification of the month's costs around it. Coverage is measured on absolute
   values (`abs`) so that invoices and credit notes cannot cancel each other into "no activity".
8. **OTHER is not actionable.** `OTHER` (the Gate 6 unclassified bucket, confidence 0) is a data
   quality bucket, not a cost category a hotelier can act on: evaluating it would produce alarms about
   the classifier. It is `NOT_APPLICABLE / COST_CATEGORY_OTHER_NOT_ACTIONABLE`, and its weight is what
   the coverage measures.
9. **Same currency, no FX.** A target is one currency and its comparables are the same exact
   currency. There is no exchange rate, no FX client and no assumed base currency: a rate would be
   an unaudited input that changes the answer, and NINFA has no source for it. Currencies are never
   summed; a hotel invoiced in two currencies has two independent histories.
10. **Seasonal window of +-2 months.** Comparable months are at most two months apart in the year
    (circular, so December and January are 1 apart), at most 36 months back and strictly before the
    target (`period_end < target.period_start`, no leakage). A hotel's cost per room moves with the
    season (energy, laundry, seasonal staff); a whole-year baseline would call every July an anomaly.
    Five to twelve months, most recent first.
11. **Median and IQR.** The expectation is the median of the comparable CPORs and the spread is the
    interquartile range (linear interpolation at `(n - 1) x p`), the same robust statistics as Gates
    4 and 5, in `Decimal`, with no outlier removal (an outlier is data). A mean and a standard
    deviation would let one bad month move the expectation and widen the fence exactly when
    it matters.
12. **AND, not OR.** The anomaly needs all four conditions: the CPOR above the expected one, at least
    20 % above it, at or above `P75 + 1.5 x IQR`, and a gross gap of at least 100 currency units. A
    relative threshold alone flags tiny costs, an absolute one alone flags big cost lines that are
    always big, and a fence alone flags a tight history by a hair; each catches what the others miss,
    and silence is a feature. A month that fails any of them is `CLEAR`. The thresholds are versioned
    constants in code, not settings in the database: changing one is a new rules version.
13. **The cost gap is a proxy, not a guaranteed saving.** `cost_gap_proxy` is a gross difference
    between the month's net cost and the expected CPOR applied to its own volume. It is not a loss,
    a saving or a recoverable amount: it does not know why the CPOR rose, whether the cost was
    avoidable or what another supplier would charge. It is an order of magnitude for a hotelier's
    attention, and no name in the code, the schema or the docs promises more.
14. **The evaluation is not persisted.** Like Gate 5, the output is an immutable, fingerprinted
    evaluation, a pure function of stored invoices and snapshots, recomputable at any time. There is
    no `Decision`, no priority, no recommendation and no `CostPeriodMetric` table: the metric is a
    non-persistent value. A Decision needs a lifecycle, deduplication and an outcome that are not
    known yet, and persisting it later is an additive change. Only `TRIGGERED` will ever become one.
15. **One explicit detector, no framework.** `COST_CPOR_ANOMALY` is plain modules with a small
    vocabulary shared with Gate 5 (the five statuses, precision, canonical text). There is no
    `GenericAnomalyEngine`, rules DSL or generic metrics platform; abstractions will be extracted from
    what the next detectors really share.
16. **Confidence is the minimum of its inputs.** The final confidence is
    `MIN(baseline confidence, target quality)`, never their average: a decision about a month is only
    as reliable as the weakest of the history it is compared with and the month itself. Below 55 a
    holding rule is `SUPPRESSED_LOW_CONFIDENCE`.

## Alternatives considered
* **Cost per available room (CPAR) or per guest night**: rejected for V1. CPAR ignores the very
  thing that makes laundry and cleaning move (rooms actually turned over), and a guest-night
  denominator is not consistently present in booking exports.
* **Service-period attribution**: rejected until invoices carry a reliable service period; inferring
  it from descriptions would silently change results.
* **Mean and standard deviation, z-scores**: rejected: not robust on the 5-12 monthly points
  available, and one bad month would move the expectation.
* **Persisting a `CostPeriodMetric` or a Decision now**: rejected (see 14): it would freeze a schema
  before the lifecycle exists; the evaluation is cheap to recompute (a handful of statements).
* **FX conversion with a stored or looked-up rate**: rejected (see 9).

## Consequences
* Additive and reversible: no table, no migration (head stays `0007_invoice_supplier_ingestion`), no
  API, no worker task and no dependency. Tests guard each of these.
* Every answer is explainable from its facts, deterministic (SHA-256 fingerprint of the canonical
  inputs and result) and replayable, since the service reads no clock.
* The denominator inherits the limits of the booking table and the numerator those of invoice-date
  attribution; both are stated in
  [cost-cpor-anomaly-v1.md](../cost-cpor-anomaly-v1.md) ("Known limits") and revisited by later gates,
  each of which will change the rules version.

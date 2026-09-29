# Analysis coverage v1 (Gate 22)

## What this closes

The Gate 21C manual pilot dry run showed that Oggi could read `NO_ACTION_REQUIRED` after a
booking-only analysis run, with no way for the person reading it - AGRIA operator or hotel staff
- to know that cost and labor were never checked that run. Gate 22A's audit confirmed this is
real and structural: `DecisionRun` only ever persisted domain-blind aggregate counts
(`triggered_count`, `clear_count`, ...), so "5 domains evaluated, all clear" and "2 of 5
evaluated, the other 3 never attempted" were indistinguishable after the fact. This gate closes
that gap with the smallest additive change: one nullable column, one typed domain model, one new
API field, one qualifying UI line. **No new `FeedState`, no changed detector, no changed
threshold.**

## Coverage vs. outcome

Coverage answers "did NINFA look here this run" - never "what did it find". A domain is
`EVALUATED` whether its detectors returned `CLEAR`, `TRIGGERED`, `INSUFFICIENT_DATA`,
`NOT_APPLICABLE` or `SUPPRESSED_LOW_CONFIDENCE`. The four user-facing domains group the five
detector types the way an operator/hotel thinks about them:

| Domain | Detector type(s) |
|---|---|
| REVENUE | `REV_PICKUP_LOW`, `REV_OCCUPANCY_RISK` |
| DISTRIBUTION | `REV_OTA_DEPENDENCY` |
| COSTS | `COST_CPOR_ANOMALY` |
| LABOR | `LABOR_OVERSTAFFING` |

In `app/cli/analysis.py`, REVENUE and DISTRIBUTION are unconditional (a booking data source is
always required), so they are always `EVALUATED`. COSTS and LABOR are `EVALUATED` only when the
operator passes `--cost-year`/`--cost-month` or `--labor-data-source-id`; otherwise `SKIPPED`
with reason `NOT_REQUESTED` - the only skip reason V1 has, because every skip here is a caller's
own choice, never a runtime failure (a crashed run persists nothing at all - Gate 21's fail-loud
guarantee is untouched by this gate).

## Persistence

One nullable JSONB column, `decision_runs.analysis_coverage` (migration `0011_analysis_coverage`,
additive, `decision_runs` stays append-only). The typed domain model lives in
`app/modules/decisions/coverage.py` (`AnalysisCoverage`, `DomainCoverage`, `AnalysisDomain`,
`DomainCoverageStatus`, `DomainSkipReason`) and is the only thing that (de)serializes the stored
JSON - nothing else in the codebase builds that shape by hand.

**NULL means "not recorded", never "nothing was evaluated" and never "everything was
evaluated".** Every run persisted before this gate reads back as NULL; no backfill exists or is
attempted. `DecisionService.sync()`'s new `coverage` parameter defaults to `None` for exactly
this reason - every pre-Gate-22 caller (the whole existing test suite included) is unaffected and
keeps persisting NULL.

The production orchestrator (`app/cli/analysis.py::run_analysis`) is the ONE place that builds an
`AnalysisCoverage`, from the same booleans that already decide which detectors to call - it is
never reconstructed afterward from the persisted evaluations, which Gate 22A's audit found
cannot represent per-domain coverage for the common (non-triggered) case at all.

## Replay / fingerprint semantics

Audited before changing anything (per the gate's own requirement): the existing
`run_input_fingerprint()` already folds in every evaluation's own fingerprint plus the evaluation
counts, so a REAL scope change (adding an evaluated domain) already changes the fingerprint as a
side effect, because domains are strictly additive in this CLI (COSTS/LABOR can only be added,
never traded against REVENUE/DISTRIBUTION). To make this an explicit, deterministic guarantee
rather than an incidental one, `coverage` is now folded into the fingerprint directly (as an
optional parameter, omitted entirely - not even as a null placeholder - when the caller passes
none, so no pre-Gate-22 fingerprint changes value). Result: **same data + same scope is still an
idempotent replay; same data + a materially different scope is a genuinely distinct run**, proven
directly (not just inferred from evaluation-count side effects) in
`test_decision_coverage_persistence.py`.

## API contract

`DecisionFeedResponse` gains one additive field, `analysis_coverage`, always present and never
null:

```json
{
  "analysis_coverage": {
    "summary": "PARTIAL",
    "domains": [
      { "domain": "REVENUE", "status": "EVALUATED", "reason": null },
      { "domain": "DISTRIBUTION", "status": "EVALUATED", "reason": null },
      { "domain": "COSTS", "status": "SKIPPED", "reason": "NOT_REQUESTED" },
      { "domain": "LABOR", "status": "SKIPPED", "reason": "NOT_REQUESTED" }
    ]
  }
}
```

`summary` (`FULL`/`PARTIAL`/`UNKNOWN`) is derived server-side (`AnalysisCoverage.summary`),
mirroring how `feed_state` itself is already a server-derived value the frontend only ever
switches over - never recomputed client-side. `UNKNOWN` with an empty `domains` list covers both
"no run yet" and "a run predating Gate 22"; a client must never infer `FULL` or `PARTIAL` from
its absence.

## Oggi UI

Additive only - no new page, card or section. `feed-state-view.tsx` adds one subordinate line
(`.feed-state__coverage`) under `NO_ACTION_REQUIRED`, `DATA_QUALITY_LIMITED` and `ACTION_REQUIRED`
(never under `NOT_PROCESSED`, which is unchanged): nothing when coverage is `FULL`, "Non
analizzati: <domains>." when `PARTIAL`, "Copertura dell'analisi non disponibile per questo run."
when `UNKNOWN`. Domain names are always the plain-language labels in `lib/copy.ts`'s
`analysisDomainLabels` (Ricavi/Canali/Costi/Personale) - the raw `AnalysisDomain` enum values
never reach the UI.

### "Tutto sotto controllo" stays honest

The whole point of this gate: `NO_ACTION_REQUIRED` + `PARTIAL` coverage renders as "Tutto sotto
controllo" **followed immediately by** "Non analizzati: Costi, Personale." - the headline is
still true (nothing actionable was found in what was checked), but it can no longer be read as
"every area was checked and found clean" when that was not the case.

## Explicitly deferred (Gate 22A's own P1/P2 list, unchanged)

Surfacing "last successful analysis date" when today is `NOT_PROCESSED`, a CSV optional-header
typo warning, data-freshness `CURRENT`/`STALE`/`UNKNOWN` and its threshold, automatic/scheduled
daily execution, a worker analysis task, and everything already out of scope per Gate 21A/21B.

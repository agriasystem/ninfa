# ADR 0048: Reconstructed is not observed as-of

Status: accepted (Final Historical Integrity Micro-Patch). No migration, no new dependency, no formula, threshold or detector change; Smart Import, Source Learning, the inventory
form, `valid_from`, the over-capacity notice, Personale coverage, the scheduler, Decision Memory and Mia are untouched. Amends [ADR 0047](0047-final-pilot-product-ux.md) (the
ordering of history and analysis, one consequence, the copy of the empty state) and [ADR 0046](0046-a-sample-of-history-is-what-a-finished-analysis-read.md) (one sentence).

## Context

ADR 0047 rebuilt the missing lead-time-0 nights of the cost months from the bookings, so that a past month's cost per occupied room can be calculated. Those rows are
`RECONSTRUCTED_APPROXIMATE`, and one consequence was accepted without being asked: the Expected engine's own rule (a reconstruction completes a thin observed sample) made them
comparables, so a night inferred today could shape tomorrow's baseline. It also forced an ordering in the refresh (history after the analysis of a day already made) and a deferral,
because a stored baseline is never rewritten and the added nights changed what today's next analysis would compare with (measured on the real demo as
`EXPECTED_BASELINE_CONFLICT`).

The principle is `RECONSTRUCTED != OBSERVED AS-OF`. If today the hotel gives an export that lets NINFA reconstruct the 25th of October, NINFA can know afterwards what happened
on the 25th. It cannot pretend it held that observation on the 25th.

## Decision

**Readable is not eligible.** Two questions that were one are kept apart:

- *readable*: a row can be read wherever a figure wants how a day ended (the rooms a month ended with, the denominator of the cost per occupied room, the distribution, Dati).
  A read that names no history (`list_by_keys(history=None)`) hands out what is stored, whatever its origin. Nothing changed for these readers.
- *a sample of history*: a comparison whose meaning is "what was known then" (the Expected value, its comparables, the pickup, the curves) may read only what NINFA knew then: an
  OBSERVATION that a finished analysis read.

The rule has two halves and every comparison with the past goes through both: `historical_sample_is_eligible` (the run: finished, says what it read) and
`ObservationHistory.admits` / the same condition inside `BookingSnapshotRepository.list_by_keys(history=...)` (the row: an observation, of a day and revision that count).
`ObservationHistory.admits` used to return true for anything that was not OBSERVED; it now returns true for an observation only. That is the whole change to the rule, in the
one place every historical read already passes through (Expected comparables, the pickup prior, the curve anchors and endpoints), so no reader was edited.

The architecture already told the two apart (`SnapshotOrigin`), so there is no migration. Nothing is stored differently: the rebuild of ADR 0047 keeps its guards (cost months
only, only a night with an inventory, only inside what the bookings cover, never over an existing snapshot of any origin, idempotent).

**Observed wins.** A real observation of a night is never replaced by a reconstruction (the key has no origin: they compete for it, and the database refuses a second row),
and as a sample it is the only one. The cost still reads one row per night.

**What the refresh does now.** Because a reconstruction can no longer change a comparable or a stored baseline, the ordering and the deferral ADR 0047 introduced for it have no
cause left. `run_refresh` rebuilds the history, then analyses, as a simple sequence; a `BASELINE_CONFLICT` is a real disagreement and fails the job again (it is no longer waited
out until the next day). The existing deferral of a `SnapshotError` conflict (a stored row NINFA cannot observe over) is unchanged.

**Copy of the empty state.** The feed carries no reason for `DATA_QUALITY_LIMITED` (history still being built, no new bookings, a low confidence), and the earlier wording named
the history. It now says only what is always true:

- Home: "Nessuna decisione affidabile oggi" / "NINFA non ha ancora elementi sufficienti per formulare nuove decisioni affidabili. Quando emergerà qualcosa che merita attenzione, lo
  troverai qui."
- Decisioni: "Nessuna decisione affidabile oggi" / "I dati disponibili non consentono ancora una nuova conclusione sufficientemente affidabile."
- "Analisi parziale" stays a small secondary badge; the last booking import and the four areas stay. The count of checks left inconclusive is no longer shown anywhere (ADR 0047
  folded it; it is gone), and no reason is named.

## What stays the same

The cost per occupied room (formulas, thresholds, the reconstructed quality of 60, the exact cause when it cannot be calculated); the Expected engine and its provenance policy
(a pure function: given reconstructed candidates it still completes a thin sample, which is what a direct call with no history does); every detector and threshold.

## Consequences, and what to confirm

- **One earlier decision is reversed.** ADR 0045/0046 pinned that "the first run can already speak from a reconstructed history". It cannot: a history made only of
  reconstructions gives an insufficient baseline and the run says nothing, as for a hotel with no history. The test that said otherwise was rewritten to the new truth.
- **The demo's October** is unchanged: still no cost per occupied room (its bookings file begins on the 25th), with the same exact cause on the page. A complete month with an
  inventory valid from its first day still gives one.
- **No stored data is affected here.** The development database holds 240 observed snapshots and no reconstruction, and no baseline names one. A database that ran ADR 0047's
  rebuild and then an analysis could hold a baseline that named a reconstruction; that baseline stays as it was, and a baseline made the same day from the new rule would differ and
  fail loudly until the next local day: reported, not hidden.
- The five-week cold start of the onboarding guide is unchanged: importing history, or rebuilding it for a cost, does not shorten it.

## Tests

`test_reconstructed_is_not_observed.py` (the rule on a row and on a read; the real Expected with three observed and four reconstructed comparables; a history made only of
reconstructions; a really observed history counting as before), `test_inventory_history_backfill.py` (the month readable for its cost and a comparable of nothing; a refresh after
the rebuild is a replay; one row per night with the observation authoritative; the database refusing a second row; the demo's 7-of-31 nights), the rewritten eligibility,
first-run and refresh tests, and the Home, Decisioni and feed-state tests for the general copy.

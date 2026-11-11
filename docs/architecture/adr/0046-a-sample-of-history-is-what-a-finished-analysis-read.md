# ADR 0046: A sample of history is what a finished analysis read

Status: accepted (Final Data Freshness & Provenance Safety Patch). No migration, no new dependency, no threshold or formula changed. Amends
[ADR 0045](0045-no-new-booking-data-is-not-zero-pickup.md).

## Context

ADR 0045 left two holes open:

- `REV_OCCUPANCY_RISK` was still evaluated on a day with no new booking data, so it could open a decision on a position nobody had seen.
- The observation, the baselines and the final sync are three separate commits. A job dying between them left rows that look like any other
  observation, and later days read them as history.

## Decision

**Available, fresh and a sample are three different things** (`analysis/observation.py`).

| | Means | Used by |
|---|---|---|
| Available | the last known bookings | Dati and the capacity, always |
| Fresh | the source delivered since the last day analysed | a new revenue decision |
| A sample | a finished analysis read it, and it had something new in it | Expected, comparables, curves |

**With no new data neither revenue detector speaks.** `REV_PICKUP_LOW` and `REV_OCCUPANCY_RISK` are `INSUFFICIENT_DATA` / `BOOKING_DATA_STALE`, checked
first. One code for one fact: it replaces the pickup's own code of ADR 0045, which never reached real data. The formula and the thresholds are
untouched: a fresh observation gives what it always gave.

An open decision is not touched as if the data were current: nothing opens or resolves, and its last trigger and counts stay. As for any
insufficient evaluation, only `last_evaluated_local_date` moves (Decision Memory is unchanged). The day's feed has nothing to act on from it, and reads
as limited by data, not as all clear.

**`historical_sample_is_eligible(run)` is the one rule on what a run's observation can be used for.** It is positive: nothing is a sample until a finished run
says so.

- A `DecisionRun` row exists only once `DecisionService.sync()` has committed. A failed job leaves none, and the table has no other state, so there is no
  status to check: the row is the proof.
- What is left to ask is whether it says what it read: this source, a known import, this day. A run with no provenance, with no known import (its
  zeros are not a measure) or that cannot be read is not eligible.
- A run recorded before a day could be looked at twice has no revision: it read the only observation there was.

**One filter, shared, by revision** (`ObservationHistory`, in `BookingSnapshotRepository.list_by_keys`). Expected and Revenue are told which observations count, as
an argument, because `snapshots` and `expected` must know nothing of runs. It works per revision, not per day: if the morning's analysis finished and the afternoon's
failed, the day counts as what the morning read. A row above that revision was never history, whatever the screens show of it. Reconstructions are not observations
of a day, and are always read. A baseline names its rows by id, so Revenue checks those too.

**Retry.** A retry reaches the same rows and the same revision, and computes the same baseline for the same target: nothing is written twice, and no conflict.
Before it finishes that day is no sample. After, it is one sample.

**The first run.** Nothing to compare with is not "nothing new": the first valid observation is fresh, so the detectors are evaluated on what history there is (only
observations: a reconstruction is no history, ADR 0048), and it is the first sample for the days after it. There is no block waiting for a previous run.

**A file later the same day.** The morning's stale run holds nothing back: the day's last finished run decides, and the afternoon's refresh evaluates normally.

## Why positive

A negative rule ("not a failed day") would need a mark on the failure, and a job that dies hard writes nothing. `run_property_analysis` is the only production writer of
OBSERVED rows, so a row with no finished run behind it really is one that nothing finished reading.

## Consequences

- **Older OBSERVED rows with no finished run stop being samples.** On `ninfa_dev`: the demo's seeded history (2025-07 to 2026-08, no run) and Hotel Quercia's 29 September
  (a run with no provenance). No baseline of 9 November names one, so nothing conflicts. A pilot hotel starts with runs, so it has none.
- **Labor, costs and OTA read rows by key as before**, so they can still read a row of a failed day: the labor forecast's finals, the costs' lead-zero nights, the gate on OTA's
  comparable periods. Out of this patch on purpose. Such a row is a correct count of the bookings at that moment, only its analysis failed.
  Labor's forecast also hangs from the Expected baseline, so with fewer samples it reads `INSUFFICIENT_DATA` more often.
- **On a day with no new booking data OTA, labor and costs are still evaluated**, on purpose for the last two: a labor plan can be valid for days to come, and
  costs refer to closed periods. Labor's demand side does read the last known bookings.
- **Dati's "7 days ago" reads any observation of that day**: it is a display of what was seen, not a sample.
- A hotel that brings files rarely gets few evaluations and few samples. That is the price of never reading silence as a fact.

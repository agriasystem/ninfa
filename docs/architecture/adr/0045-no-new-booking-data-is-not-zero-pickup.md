# ADR 0045: No new booking data is not zero pickup

Status: accepted (Final Pilot Safety Hotfix). No migration, no new dependency, no threshold changed. Amends the consequences of
[ADR 0044](0044-pilot-autonomy.md).

## Context

ADR 0044 made the daily analysis run with no import that morning. A day with no new file still takes an observation, and it
repeats what was already known. Read as a measure, that says nothing was booked:

- today, `REV_PICKUP_LOW` compared it with a week ago and could raise a false alarm once there was enough history;
- later, it entered the history of other days as a sample of nothing happening.

`no new data` means the pickup is **not known**. Only `new data, and this night did not move` means zero.

## Decision

**A day is new when what it saw differs from what the previous analysed day saw** (`analysis/observation.py`). Each run already
records the latest import that had changed the source when it looked (`input_provenance.bookings.import_job_id`), and that is
the only thing read. No table, no column, no clock.

| What happens | What the day saw | Result |
|---|---|---|
| A new day, no file | the same import as yesterday | not new |
| The same file again (a no-op) | it is not a changing import: the same one | not new |
| A file changing anything in the source | another import | new, and a night that did not move is a real zero |
| 10:00 no file, 14:00 a file | the day's LAST run counts | new from 14:00 on, and a sample for later days |
| A restart, a second run of the same data | the same import | what it was |
| A run with no record of what it saw | not judged | as before |

The rule is about a delivery, not a file. Anything that delivers bookings through an import job is judged the same way.

**`run_property_analysis` tells the two engines that read a day as a measure**, as arguments:

- `RevenueDecisionService`: with no new data `REV_PICKUP_LOW` is `INSUFFICIENT_DATA` / `PICKUP_NO_NEW_BOOKING_DATA`, before any other
  check: nothing measured, no decision. An open decision stays as it is, like with any insufficient evaluation.
- The days that had none are out of every curve: no anchor, no prior, no final. A prior from such a day reads as a missing prior.
- `BookingExpectedService`: no comparable comes from those days, whatever else the day holds. A past day's status never changes, so
  a target's comparables do not move between two runs of one day, and the baseline stays immutable.

Only OBSERVED rows can be excluded: a reconstruction is read from the bookings' own dates, not from what arrived that day.

**Why an argument and not a read in those engines.** `snapshots` and `expected` must know nothing of runs and decisions, and their scope
guards say so. The orchestration is the one place every analysis passes through (the worker's, the refresh's, the CLI's).

**What did not change.** The daily analysis, the observation of the day (Dati and the capacity read it), the import's idempotency, same-day
revisions, every threshold, Decision Memory. The date of the last import stays on the page, and no screen was added.

## Consequences

- **`REV_OCCUPANCY_RISK` and labor are not covered.** They were out of this hotfix. On a day with no new data `REV_OCCUPANCY_RISK` is still
  evaluated on the bookings last known, and can open a decision (measured on a real-engine scenario: `TRIGGERED`). Labor reads the same
  observation (from the code, not measured). Their HISTORY is clean, because a curve no longer takes those days.
- **A hotel that brings an identical export has no real zero that day.** The same content is a no-op, so the day is not new. It is
  conservative: nothing is said, and the next file that changes anything is read normally.
- **An automatic source whose sync changes nothing** reads the same way. If a provider can say its read was complete, it will need its own
  word for it: today there is none, and no provider exists.
- A hotel that brings files rarely gets few evaluations and few samples: a pickup needs a new day and a new day a week before it. That is the
  price of never reading silence as a fact.
- A job that fails between its observation and the sync leaves a day with no record: that day is not judged, so it can still count as a
  sample. It takes three failed attempts in one day.

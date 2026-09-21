# 0009 — Booking snapshots: observation is not reconstruction

**Status:** accepted (Gate 3)

## Context
The Decision Engine will need to know how the book of a hotel looked *on earlier days* (booking
curves, pickup, comparison with what was expected). The canonical `bookings` table cannot answer
that: it keeps only the **current** state of every booking. A booking's dates, rooms, revenue,
channel and status may have changed since, a cancelled booking may or may not carry its
cancellation time, and the room capacity of a night is only known as it is declared today.
Anything computed for a past day from that table is an *inference*, not a record.

The risk is quiet: if inferred history and recorded history sit in the same rows under the same
name, every later gate (expected values, detection, impact) inherits numbers whose reliability is
unknown, and a wrong recommendation would be built on a reconstruction believed to be a fact.

## Decision
1. **Two origins, never interchangeable.** A snapshot is either `OBSERVED` (computed from the
   canonical bookings at the instant NINFA looked) or `RECONSTRUCTED_APPROXIMATE` (inferred
   afterwards). The distinction is a column with a `CHECK`, two separate services with two code
   paths, and a test suite that enforces it. A reconstruction is **never** called observed, exact
   or "historical truth" in APIs, logs or documentation, even when it has no uncertainty, and it is
   never promoted.
2. **An observation is never overwritten.** Snapshots are immutable evidence: no `updated_at`, and a
   trigger refuses every `UPDATE`. A calculation that meets a stored row with a different content
   raises `BOOKING_SNAPSHOT_CONFLICT` and stores nothing; the same content is a no-op. The unique key
   `(workspace, data_source, snapshot_local_date, stay_date)` deliberately does **not** contain
   `origin`, so an observation and a reconstruction compete for one slot and the observation wins
   naturally: a reconstruction skips existing observed keys and never creates a parallel row.
   Overwriting was rejected because the value of an observation is precisely that it is what was
   seen at that moment; "refreshing" it with today's data would turn evidence into inference.
3. **A snapshot belongs to one data source.** Two sources of the same property are never merged
   automatically (they can overlap, disagree or describe different channels, and only the customer
   knows how they relate). Repositories always take a data source; the curve never mixes them.
4. **Revenue is allocated, not observed.** The canonical booking only knows the whole-stay revenue.
   It is spread over the nights in integer cents, the remainder going one cent each to the earliest
   nights, so the allocations sum exactly to the stay total; the column is called *allocated* and
   documented as a uniform deterministic allocation, not the nightly rate the property charged.
   Adding the full stay revenue to every night (the tempting shortcut) would inflate revenue and ADR
   by the length of stay; using floats would make sums drift.
5. **Inventory is never invented.** A night without an inventory row has `rooms_available = NULL` and
   `occupancy = NULL`; `0` means closed and is kept as `0` (occupancy then undefined). ADR is `NULL`
   when nothing is booked. A guessed capacity (an average, the last known value, "all rooms") would
   produce occupancy figures that look precise and are not. Occupancy is not clamped: 112.50% is
   preserved as information.
6. **Uncertainty is counted, not resolved.** A `CANCELLED` booking without a cancellation time (and,
   from its arrival day on, a `NO_SHOW`, whose recording time is equally unknown) is neither included
   in nor excluded from the certain totals: it is reported in `uncertain_booking_count` /
   `uncertain_rooms`. Picking a side would be inventing history.
7. **Day boundaries are half-open and defined.** A property-local snapshot day ends at the start of
   the next local day, excluded; across daylight-saving changes that boundary is the earliest instant
   of the date, so days tile the time line exactly. A calendar date that never existed is refused.
   Only completed days can be reconstructed.
8. **The moment of an observation cannot be chosen by the caller.** `as_of_at` comes from an
   injected clock (fixed in tests); the snapshot day is its date in the property's time zone. There
   is no parameter through which a past state could be forged.
9. **Consistency through the existing per-data-source advisory lock**, shared with the booking
   import and defined once, plus a single transaction per run. `REPEATABLE READ` was evaluated and
   rejected (it cannot be set inside the caller's transaction and the lock already serialises the
   only writer of bookings).
10. **Fingerprint and version.** A SHA-256 over the canonical content (without ids and runtime
    metadata) makes a re-run an idempotent no-op; `calculation_version` (`booking-snapshot-v1`)
    versions the rules, not the application, and is part of the fingerprint.
11. **Application services, no API, no worker, no scheduler**, no new dependency. Room inventory has
    its own table (`rooms_total` was not added to `Property`, whose capacity varies by night).

## Consequences
- History exists only from the day observations start, one per data source and local day. Earlier
  history is available as reconstructions, always labelled approximate, with the uncertainty counted.
  Consumers (curves, pickup, expected) must handle the two origins explicitly, and can decide to use
  only `OBSERVED`, or both while keeping them apart.
- A second run on the same day after the data changed is a conflict rather than an update, so a
  scheduler will run once per local day (after the day's import) and a correction of an observation
  is not possible in V1 by design.
- Rules changes (allocation, rounding, status policy) require a new `calculation_version`; storing
  the new results next to old ones for the same key is not supported in V1 and would need its own
  decision.
- Reconstructing is cheap (linear in bookings × nights + cells) but stores many rows; ranges and
  total rows are capped.
- Snapshots are never deleted by cascade; a retention policy is a later concern.
- Pickup, booking-curve interpretation, expected values and everything built on them are deferred:
  this gate produces the raw material, not conclusions.

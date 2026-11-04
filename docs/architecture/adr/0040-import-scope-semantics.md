# ADR 0040: What the absence of a record means

Status: accepted (Import Scope Semantics V1.2.1)

## Context

[ADR 0039](0039-same-day-revisions.md) allowed several files on one day and chose: *a file cannot delete*. It named the
consequence: a booking missing from a later file stays, a department a file no longer names stays. A pilot needs better than
that, because a full export that no longer holds a booking really says it is gone, and NINFA kept counting it.

A second limit was found reading the same rule: the current plan picked the newest file per (day, category), and a file of
hours worked has no plan in it. So actual hours could take the place of planned ones.

## Decision

1. **What a file holds of its period belongs to the source and its structure**, not to the page: `FULL`, `PARTIAL`, `DELTA`,
   in the family's memory.
2. **It is never inferred.** Not from the rows, the dates, the name, the hotel.
3. **A person says it, once, when it changes what counts**, in words with no concept in them. No screen.
4. **With no word, absence says nothing.** The CLI, a saved configuration and a hand-built mapping take nothing away.
5. **Bookings are marked, never deleted.** Which import did it, when, and which import last held it. A later file that holds
   the booking brings it back.
6. **A complete staff file speaks for all departments on all days of its period.** Older snapshots stay whole, what counts
   is decided on reading, as before.
7. **Planned and worked are two readings.** A file speaks only on what it carries. Neither replaces the other.
8. **Costs are untouched.** A document is the unit, absence means nothing.
9. **Same-day, Expected, Decision Memory are untouched.** A removal is a change in what is on the books and goes down the
   path every change goes down.

## Why not the alternatives

- *Treat a file as complete when it looks complete (many rows, whole month):* a partial export of a big hotel looks
  complete. The failure is silent and it deletes. Refused for the same reason as a rule on `Modificata` (ADR 0039).
- *Always ask on the second file:* asks about nothing most of the time. The question appears only if some stored record of
  the period is absent, and only until it is answered.
- *A hard delete, or moving the row to another table:* a booking is pointed at by import rows and read back by audit, and a
  later file may hold it again. A mark keeps both true.
- *A "removed" status among `CONFIRMED`, `CANCELLED`...:* status is what the source says about a booking. Absence is what
  NINFA concludes about a file. A cancelled booking can also be removed: two facts, two places.
- *Interval from the file's title or the stay nights:* a title is too little to delete on. Check-in is the date a file is
  organised by, and first-to-last check-in of its own rows is what it demonstrably covers. Narrower means a stale booking,
  wider means removing what was never in question; the first is the smaller error.
- *A column on labor rows for "superseded":* would edit rows written as immutable evidence, and be one more thing to keep
  true. The reach of a complete file is a fact about that file: its first and last day, and the job's scope.
- *Blocking a file of hours worked:* the model has held both since Gate 11, and the detector already prefers worked hours
  for history. The bug was the reader, not the file.

## Consequences

- Reads of current bookings go through `is_current_booking()`. A new read that forgets it would count removed bookings: all
  three current reads carry it, and a test pins each.
- The labor no-op compares what counts with and without the file, so a complete file that only clears is a change.
- A family has one answer. Two exports with the same columns and different meanings would share it. ADR 0041 closes what
  that could do: a remembered answer no longer takes anything away by itself, and it can be corrected where it shows.
- The downgrade of `0015_import_scope` refuses once it would change what the data say.
- `feature/mia-v3-company-intelligence` still has `0014_mia_conversations`: to renumber after the real head when rebased.

See [import-scope-semantics-v1.md](../import-scope-semantics-v1.md). Supersedes the "a file cannot delete" clause of ADR 0039.

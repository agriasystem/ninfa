# ADR 0039: A day holds several observations; files replace by a stated rule, never by editing

## Status

Accepted (Pilot Reliability V1.2). Migration `0014_same_day_revisions`.

## Context

A hotel exports in the morning and again in the afternoon, corrects a file, sends two weeks of shifts.
NINFA answered with three limits that were artificial: a second bookings file was analysed only the next day
(ADR 0038, decision 4), a second different staff file on one day was refused (`LABOR_SNAPSHOT_CONFLICT`), and a
corrected cost row made the whole file fail, on any day (`INVOICE_DOCUMENT_CONFLICT`).

Nothing about those limits protected the evidence. What must be protected is that a stored row keeps saying what it
said, that a run keeps pointing at what it read, and that nothing counts twice.

## Decisions

1. **`booking_snapshots.revision`: a night seen again joins its day as the next revision.** The row is never
   updated. Only the nights that changed are written (the state as of revision r is, per night, the row with the
   highest revision <= r); identical content writes nothing and moves no revision. The unique key becomes
   (source, snapshot day, stay night, revision).
2. **Every read by day or by key gives one row per night and day: the newest.** Enforced once, in
   `BookingSnapshotRepository`, so no engine had to learn about revisions. Only `get_by_id` / `list_by_ids` reach an
   older one, because a baseline or a run names it. So the **last revision of a day represents that day**: in a new
   analysis and in the history of every later day, as one sample.
3. **Anti-leakage is unchanged and now pinned.** Comparables come from strictly earlier snapshot days (the seasonal
   window and the pair rules already required it): an observation never teaches another of its own day. A revised
   target gets a new baseline, and the old baseline stays for the run that read it.
4. **Labor: every file that changes something is a snapshot of its own; what counts is decided on reading**
   (`labor.current_plan`): a file speaks for the work dates it names and the categories it names, together. Where it
   speaks the newest file wins, where it does not what was there stays. The unit is (work date, category), the unit
   every labor figure is computed on: not a person (the model holds none), not a role label (free text).
   *Amended by [ADR 0042](0042-labor-partial-absence.md): a file speaks only for the (work date, category) cells it
   holds; dates times categories are no longer read as its reach, and only a complete file takes a cell away.*
5. **Costs: a corrected row of a spreadsheet is the next `revision` of its document**, and only the newest counts
   (`is_current_invoice`). **A FatturaPA is never replaced**: a fiscal document that comes back different is still
   refused, whichever side the XML is on.
6. **`import_jobs.changed_data` says whether an import changed anything**, read from the canonical data and never
   from the file's name or bytes. An import that changed nothing queues nothing, says nothing to the status and does
   not move the run's provenance. So analysing again after one is an idempotent replay.
7. **Provenance says what was read.** A run records the observation (day, revision) and the latest import that
   changed the source, read under the same lock as the bookings; for labor and costs the latest such import, and for
   labor the files the evaluations read.
8. **`Modificata` stays a question** (see below).

## Why a revision and not the alternatives

- *Update the row:* destroys the evidence a run read. Refused by a trigger, on purpose.
- *A second table of history:* every baseline and observation points at a snapshot id; moving rows breaks them.
- *A whole new set of rows per revision:* every unchanged night would get a new id, a new baseline and a new
  evaluation fingerprint, and "what changed" would be lost. Writing only what changed keeps it visible.
- *A table of observations:* correct, and more than this needs: (day, revision) on the run is enough to read the
  input back (`list_for_snapshot_date(as_of_revision=...)`), and the import is on the run.

## `Modificata`

It is not a column. It is a **value of the `Stato` column**, a required field: 5 rows of 96 (3 of 52 in the second
file), 5,9 % of on-books revenue. It cannot be ignored: `status` is what decides whether a booking counts.

Signals exist in that file: every `Modificata` row has revenue, every `Cancellata` row has none. A rule built on them
would make the file READY, and it was not shipped, because:

- it would be validated by one file. The official corpus has the very case as hand truth
  (`B23_status_modificata_is_ambiguous`), and the rule would pass it only because its cancelled rows keep their money;
- an export can list the superseded version of a booking as "Modificata". The money signal does not exclude that;
- wrong, it inflates what is on the books, silently. That is the false automation this product forbids.

So it stays one question, once: the answer is remembered for the source (`Source Learning`), and the next file of the
same layout asks nothing. The other half of the brief's concern was measured and needs no change: across both corpora
no question is about a column that does not change the result, and a real column called `Modificata`, `Modificata il`,
`Ultima modifica` or `Modificato da` asks nothing and claims nothing (`tests/benchmarks/aurora_like`).

## Consequences

- A channel change is a new run on the same observation: a snapshot holds no channel, and no revision is invented for
  it; Distribution reads the bookings, so it sees the change.
- A file that drops a category altogether, on every day it covers, says nothing about it: the older rows stay until a
  file names it again. A stale figure, never a sum. Likewise a document a later cost file does not mention stays. (ADR 0040
  closes this for a file a person says is complete, and separates hours worked from the plan. Costs stay as they are.)
- A run's freshness is the latest import that changed the data: a file re-imported later, identical, does not move it.
- `DEFERRED` is left for a stored reconstruction on today's key (the property's time zone changed), which clears by
  itself. A job told to wait no longer holds back a request for now.
- The downgrade refuses to run once a second revision exists.

See [same-day-revisions-v1.md](../same-day-revisions-v1.md). Supersedes ADR 0038 decision 4, and the same-day clauses of
ADR 0009 and ADR 0014.

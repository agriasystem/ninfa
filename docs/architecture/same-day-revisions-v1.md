# Several files on one day

A property may import any number of files on any day, of any kind of data. NINFA does not impose "one file a day":

```
FILE -> UNDERSTANDING -> IMPORT -> ANALYSIS -> DATA UP TO DATE
```

Decisions and alternatives: [ADR 0039](adr/0039-same-day-revisions.md). The refresh itself:
[post-import-analysis-v1.md](post-import-analysis-v1.md).

## What each kind of data does

| The second file... | Bookings | Staff | Costs (CSV / Excel) | Costs (FatturaPA) |
|---|---|---|---|---|
| is the same data | no-op | no-op | no-op | no-op |
| brings new records | they are added | new work dates live beside the others | new documents add up | new documents add up |
| changes a record | updated, by `source_record_id` | the (day, category) cells it names are replaced | the document's next revision | **refused**, nothing changes |
| leaves a record out | it stays, unless a person said the file is complete | it stays, unless the file names that category on that day or a person said it is complete | it stays | it stays |

"The same data" is judged on the canonical content, never on the file's name or bytes: the same plan in another order,
or part of what already counts, is the same data. Going back to an earlier version is a change.

## Bookings: revisions of an observation

```
day D     revision 1 (morning)      night N: 10 rooms   night M: 4 rooms
          revision 2 (afternoon)    night N: 12 rooms                       <- only N changed
```

The state as of revision r is, per night, the row with the highest revision <= r. So:

| Who | Reads |
|---|---|
| a new analysis of day D | the newest revision of each night: N at 2, M at 1 |
| the history of any later day | the same: **the last revision of D is D**, one sample |
| the run made in the morning | what it read: `input_provenance.bookings.observation = {D, 1}` |

Every read by day or key goes through `BookingSnapshotRepository`, which hands out one row per night and day, the newest.
Only `get_by_id` / `list_by_ids` reach an older row, because a baseline or a run names it. An older row stays exactly as
it was (a trigger refuses every UPDATE).

What a second file does after import: if any booking changed, a refresh is queued; the refresh observes (only the nights
that changed get a row), computes Expected for those nights only (the others keep their baseline), evaluates Revenue,
Distribution, Cost, Labor, ranks, and syncs. Same day, the same path as the first file.

A channel change moves no night, so no revision: a snapshot holds no channel. The bookings changed, so the analysis runs
again, on the same observation, and OTA (which reads the bookings) sees it.

### Expected and leakage

Comparables and curve pairs come from **strictly earlier snapshot days**: the seasonal window and the pair rules already
required it, and `test_same_day_bookings.py` pins it. So:

- a target never compares with another observation of its own day;
- a past day seen three times is one sample, read from its last revision: six days are six comparables, not eight rows;
- too few days stay too few, however many revisions they have;
- a target revised later has a new baseline; the old one stays for the run that read it.

### Decision Memory

Identity holds no snapshot id and no as-of date, so **a signal seen again the same day is the same Decision**: one
observation more on it, per run. The normal rules apply: a CLEAR resolves it the same day, a trigger after that reopens
it as a new episode. `triggered_observation_count` counts runs, and so can grow by more than one a day.

## Staff: what counts, on reading

Every file that changes something is a snapshot of its own (`labor_snapshots.revision`, next to the others and never over
them). Nothing is deleted. What counts is one rule, pure, used by the detector, by Dati and by the import itself
(`labor.current_plan.current_rows`):

> A file speaks for the work dates it names and for the categories it names, together.
> Where it speaks, the newest file wins; where it does not, what was there stays.

| Files | Result |
|---|---|
| week A, then week B | no date in common: side by side |
| week A, then week A corrected | same cells: replaced, hours and costs never add up |
| Mon-Sun, then Thu-Wed | Mon-Wed from the first, Thu-Wed from the second |
| Reception's file, then Housekeeping's | no category in common: both stay, on the same days |
| a correction that drops Spa on Sunday | Spa is named and Sunday is named: Sunday has no Spa any more |

"Newest" is (`snapshot_local_date`, `revision`): the order the files came in. Knowledge stays dated: as of yesterday,
today's file did not exist.

The identity of "the same datum" is (workspace, property, source, work date, category). Not a person, because the model
holds none. Not a role label, because it is free text a second export may write differently: `Reception mattina` and
`Ricevimento AM` in two versions of a plan are one cell, and that is what makes the second replace the first.

**What the rule alone cannot see:** a file that drops a category altogether, on every day it covers, says nothing about
it, unless a person said the file is complete: then it speaks for every category of its period
([import-scope-semantics-v1.md](import-scope-semantics-v1.md)). Hours planned and hours worked are read separately, each by
this same rule: a file speaks only on what it carries.

From a `LaborSnapshot` one can read which import brought it (`source_import_job_id`) and what it said; from a run, which
files its evaluations read (`input_provenance.labor.snapshot_ids`) and which import last changed the source.

## Costs: the document is the unit

A document's identity is (property, supplier, normalised number, date, kind), and it was already cross-source.

| | |
|---|---|
| two files of different periods | both count |
| two files of one period, different documents | they add up |
| the same file twice | no-op |
| a row of a spreadsheet corrected | the document's next `revision`: the old one stays, only the newest counts (`is_current_invoice`) |
| a FatturaPA that comes back different | refused (`INVOICE_DOCUMENT_CONFLICT`), the whole file, nothing changes |
| a spreadsheet about a document that came as a FatturaPA, with other amounts | refused |

A FatturaPA is a fiscal document: it is corrected by another document (a credit note), which has its own identity.

## "Did this import change anything?"

`import_jobs.changed_data`, set by each import service: bookings created or updated; a labor file that changes what
counts; documents created or revised. `NULL` on a job from before it existed, and then it counts as a change (nothing can
be said of it).

| | changed | not changed |
|---|---|---|
| refresh queued | yes | no |
| `latest_import_at` of the status | moves | stays |
| the run's provenance | moves | stays: a later refresh is an idempotent replay |
| the job in "Importazioni recenti" | listed | listed: the attempt happened |
| the page | the analysis follows | "Questo file non cambia nulla di ciò che NINFA ha già" |

## What was refused to keep this simple

- A file does not delete by itself: a row that is not in a later file stays, unless a person said the file is complete,
  and even then it is marked and kept ([import-scope-semantics-v1.md](import-scope-semantics-v1.md)). Deleting by absence
  alone would make a partial export destroy what a full one said.
- No per-row history of bookings: `bookings` keeps the current state (Gate 2), and an observation is what freezes it.
- No revision for a reconstruction: it is one inference of a finished day.

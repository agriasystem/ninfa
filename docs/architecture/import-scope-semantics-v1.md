# What the absence of a record means

A record missing from a later file does not always say the same thing:

| The file holds... | What it says about a record it does not hold |
|---|---|
| everything of its period (`FULL`) | it is no longer there |
| a part of its period, a channel, a department (`PARTIAL`) | nothing |
| only what is new or changed (`DELTA`) | nothing |

The three are not told apart by looking at the file. How many rows it has, its dates, its name, the hotel: none of these
says it, and a wrong guess silently deletes or silently keeps. So **NINFA asks a person, only when the answer changes what
counts**, and remembers it for files of that structure. **A memory saves a question only while nothing would stop counting**:
it never takes anything away by itself. Decisions and alternatives: [ADR 0040](adr/0040-import-scope-semantics.md),
[ADR 0041](adr/0041-remembered-scope-safety.md). The same-day machinery this sits on:
[same-day-revisions-v1.md](same-day-revisions-v1.md).

## When the question is asked

```
READY, a source exists, and reading the file as complete would stop something counting
   |-- the person answered on this import --------> that answer, for this import
   |-- these very bytes were said to be a part ---> the same: not asked twice
   |-- this family is remembered as a part -------> no question, nothing goes; the summary says what stays
   |-- this family is remembered as complete -----> ASK again: a memory takes nothing away by itself
   `-- nobody has said anything ------------------> ASK, after every other question of the file
```

- A first file never asks: nothing is stored, nothing can be absent.
- A file that leaves nothing out of its period never asks: the answer would change nothing.
- A file that goes to manual matching never asks: a matching built by hand carries no scope, and absence then says nothing.
- A cost file never asks: see below.

The copy names no concept: *"Questo file contiene tutte le prenotazioni del periodo oppure soltanto quelle nuove o
modificate?"*, with how many stored records are concerned. A staff file: *"Questo file contiene tutti i reparti del
periodo oppure solo alcuni?"*. There is no settings screen.

With a family remembered as complete, the question says what is at stake and offers two answers, *"Sì, contiene tutte le
prenotazioni"* and *"No, contiene solo una parte"* (for staff, *"Questo file contiene tutto il piano del periodo?"*), and what each
one does. It is about this import. A box that starts empty, *"Ricorda questa scelta per i prossimi file"*, is the only thing
that changes the memory. A family remembered as a part asks nothing: the summary says what stays and offers the same two answers
behind a quiet action, which is how a wrong memory is corrected.

## Who holds the answer

| | |
|---|---|
| where it lives | `Memory.file_scope`, the family's own memory in the profile's `format_options["learning"]` |
| what it is about | **the file's structure**, never the page or the upload |
| trust | apart from the family's `trust`: answering it confirms nothing about the columns |
| a later file of that family | the answer holds (`kept_scope`), with columns moved, renamed to what reads the same, or added; a remembered "complete" still asks if something would stop counting |
| what changes it | only an answer sent with `remember_scope`: the first question sends it and says so on screen, the confirmation only with its box ticked |
| a file lacking a remembered column | another family: it asks for itself |
| a file that could be two families | no family, no answer |
| a file that contradicts what was confirmed | no answer |
| what an import was | `import_jobs.file_scope`, on the job, for audit and for reading the staff plan |
| what was remembered then | `import_jobs.remembered_file_scope`: with `file_scope`, why something stopped counting ([ADR 0041](adr/0041-remembered-scope-safety.md)) |

## What the server checks, and when

| When | What | If it no longer holds |
|---|---|---|
| reading the file | `ScopePreflight`: `effective_scope`, `remembered_scope`, `removal_count`, `requires_scope_confirmation` | |
| before the commit (`_settle`) | the file is read again with the answers, and the whole decision compared, `file_scope`, `remembered_file_scope` and `expected_removals` included | refused with 409, nothing happens, the page says to read the file again |
| at the commit, under the source's lock | what would go is counted again against `expected_removals` | the job fails with `IMPORT_PLAN_CHANGED`, nothing of the file is imported |

A figure from the browser never decides anything: posted back different it gets the decision refused, and what goes is always
computed from what the source holds. A mapping built by hand has all three dropped.

An import with no word about scope (the pilot's CLI, a saved configuration, a first file) is treated as if absence says
nothing: this gate takes nothing away unless a person said so.

## Bookings

A complete file speaks for **the bookings with a check-in from its first to its last check-in**, of its property and its
source. Inside that interval, a booking of that source that is on the books (not already cancelled or no-show) and absent
from the file is **removed**:

| Column of `bookings` | |
|---|---|
| `removed_by_import_job_id` | the import that said it is gone |
| `removed_at` | when |
| `last_seen_import_job_id` | the last import that held it |

The row stays, nothing is deleted. `last_import_job_id` stays what it was: the last import that **changed** it. `is_current_booking()`
is the one filter, used by every read of the current books (`list_for_property`, `list_stays`, `list_stays_with_channel`).

| Case | Result |
|---|---|
| A = 1, 2, 3 then complete B = 1, 3 | 2 removed, 1 and 3 current |
| complete B again | no-op: no job change, no revision, no run |
| a later file holds 2 again | 2 is current, the removal fields are cleared, counted as updated |
| partial or delta B = 1 | only 1 is touched, 2 and 3 stay |
| delta B = 4 | 4 is added, whatever dates it spans |
| `Cancellata` in any file | a status, used as always; not a removal |
| a booking already cancelled and absent | nothing to lose: no question, no removal |
| a booking outside the file's interval | not its business |

**The interval is the file's own rows, deliberately narrow.** A booking checking in after the last row of the file stays
even if the export meant to include it. A title saying "novembre" is not read: too little to delete on. Getting this wrong
keeps a stale booking one more day; the other way around destroys what a part of the data never meant to touch.

Downstream nothing is special: a removal changes what is on the books, so the job's `changed_data` is true, a refresh is
queued, the changed nights get the day's next revision, and the run records that import. A stored observation stays as it
was. A reconstruction already stored stays as it is; one made later does not see the booking, because a booking a source no
longer has is not known to it.

## Staff

The rule of [same-day-revisions-v1.md](same-day-revisions-v1.md) stays, with two additions. Any file speaks for the
(day, department) cells it holds and nothing else: a day it holds and a department it holds elsewhere do not make a cell it
removes ([ADR 0042](adr/0042-labor-partial-absence.md)).

**A complete file speaks for every department on every day of its period** (first to last work date), named or not. So:

| Files | Result |
|---|---|
| plan 4-10 Nov with Housekeeping, then complete plan 4-10 Nov without it | Housekeeping stops counting, on all seven days |
| the same, as a part (Reception only) | Housekeeping stays |
| Reception and Housekeeping on 4-5 Nov, then a part with Reception on 4 and Housekeeping on 5 | both cells it lacks stay |
| the same file, complete | Housekeeping on 4 and Reception on 5 stop counting (2, asked about first) |
| a part with Housekeeping at 0 hours on 4 Nov | a plan of zero hours, not a removal: only a complete file removes |
| complete plan with no row on 6 Nov at all | nothing counts on 6 Nov |
| complete plan 4-6 Nov | 7-10 Nov are not its business |
| a later file that names Housekeeping again | it counts again |

No column is added for this: every file is already a snapshot of its own, kept whole, so what stopped counting is still
there, and `FileCoverage` reads its reach from the file's rows and the job's `file_scope`. A complete file repeating cells
that already count is still news if it clears something: the no-op compares what counts with and without the file.

**Hours planned and hours worked are read separately** (`Basis.PLANNED`, `Basis.ACTUAL`). They are different facts and
have never been the same column (`planned_minutes`, `actual_minutes`). A file speaks only on the bases it carries:

| Files | Plan | Hours worked |
|---|---|---|
| plan, then hours worked of the same days | the plan | the new file |
| hours worked, then a new plan | the new plan | still those hours |
| a complete plan, older hours worked | the plan clears what it clears | untouched |
| a file with only hours worked | "not known", never those hours as a plan | the file |

Personale reads the plan; the labor detector's history reads the hours worked per category, falling back to the plan, as
it did; its target reads the plan. Rows with no value on a basis stay visible only where no file has a value there, so a
reader sees a gap and not a day with no staff.

Which hours a bare `Ore` column holds is not guessed: it is the existing column question, answered once and remembered with
the family.

## Costs: nothing here

Absence means nothing for documents. A register is a list of documents of a period and a later one may list others; each
document has its identity, its revisions, and a FatturaPA stays immutable. No question, no removal (`scope_effect` is 0).

## Isolation

The interval and the absent records are computed per (workspace, property, data source). Another source or another hotel
is never absent from a file.

## Migration

`0015_import_scope`, after `0014_same_day_revisions`: additive, every existing row keeps meaning what it meant (no job has
a scope, no booking is removed). The downgrade refuses to run once a booking is removed or a job was a complete file: it
would change what the data say.

`feature/mia-v3-company-intelligence` still carries its own `0014_mia_conversations`. It must be renumbered after the real
head when that branch is rebased on main. Nothing is resolved here, and that branch was not touched.

## What this leaves

- A complete file with a single row, or two, reads as `MANUAL`: too few values for the columns to be sure, as for any file.
  Manual matching carries no scope, so it takes nothing away.
- A booking checking in after the file's last row stays (see the interval above).
- A department missing on a day the file names, when the file names that department elsewhere, is an absence like any
  other since [ADR 0042](adr/0042-labor-partial-absence.md): kept by a part, a list of changes or a file nobody spoke
  about; counted and asked about before a complete file takes it away. Pinned by `test_labor_partial_absence.py`.
- A figure that moved refuses the file even if the person would have agreed to the new one: it is simply read again.
- A department cleared by a complete file is not listed by name on the page: the page gives the count.

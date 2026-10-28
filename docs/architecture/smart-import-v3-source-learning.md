# Smart Import V3 — Source Learning

Status: **implemented.** No model, no embedding, no external service: it works with `IMPORT_UNDERSTANDING_MODE=off`.
Decisions: ADR 0033 (what a person confirmed is remembered), ADR 0034 (a source remembers several recurring families) and ADR 0035
(how a family is read belongs to the family). Measured by
the Source Learning Benchmark V1 and its multi-source extension (`docs/benchmarks/source-learning-benchmark-v1.md`).

> understands → validates → maybe asks → imports → **remembers the confirmation** → asks less next time

## What existed, and what was reused

Nothing parallel was built. Smart Import already had, per kind of data, a **mapping profile**: one row per data source
(`booking_`, `labor_`, `invoice_mapping_profiles`), scoped by workspace + property + source through a composite foreign key, with
`column_mapping`, the dictionaries of words the person taught (`status/channel/role/category_mapping`), `format_options` (JSONB:
sheet, date formats, decimal separators, the document `layout`, the schema version) and `header_signature` (SHA-256 of the sorted
set of normalised headers). A source is the `DataSource` of a property and a kind of data (one active at a time). A profile is saved
when an import succeeds and the person left "remember" on (default: the source was not known, or words were taught).

What it could not do: it believed a profile because the headers were there (no look at the **values**); it could not tell a person's
confirmation from a file the engine read alone; it overwrote the past; it reused all-or-nothing; and a recognised profile did not
unblock the *missing required field* the engine had already computed.

Source Learning evolves exactly that: **a `learning` section inside `format_options`** (JSON). No table, no column, **no migration**.
The section holds one memory **per recurring family** of the source (see *Several families in one source*).

## Source identity and fingerprint

A source is `property + kind of data` (the existing `DataSource`); inside it, the **structure** of its file. Never the file name, never
the sheet name. The structure that is remembered is:

* the header **keys** in order (case, accents, punctuation, spacing and invisible characters do not matter) with the **class of their
  values** (TEXT, NUMBER, DATE, MIXED, EMPTY); a column of personal data is only a placeholder `~`;
* the confirmed mapping (field → header key), and the part of it the **person** decided;
* the closed answers worth keeping (how dates and numbers are written, whether amounts are net, the department of all the rows);
* a 16-hex **fingerprint** of (kind of data, the sorted keys with their classes, the mapping) and up to 5 earlier revisions.

No value of any row, no name, e-mail, phone, tax code, IBAN, note, file name or employee/guest identity. Nothing personal is needed
to recognise a source.

## How a file is matched (`match_source`)

Deterministic and explainable (no ML, no embedding, no LLM). For each remembered column: the header is found by key, or - only when at
least half of the remembered columns are found by name - another column that the **engine itself** reads as the same field is accepted
as a renamed alias; then the column must still agree with the field: not personal data now, not clearly read differently by the
engine, **values of the same class**, and values that **fit** the field (the semantics' own `fit`, 0.6 minimum).

Result: `structure` EXACT / COMPATIBLE / DIFFERENT, a `drift`, the columns `proven`, `renamed`, `missing`, `conflicts`, the number of
new columns, a score (columns that coincide / union) and evidence codes such as `MAPPED_FOUND:3/4`, `EXACT_HEADER_SET`, `ORDER_CHANGED`,
`KNOWN_ALIAS:1`, `NEW_COLUMN:2`, `CONFLICT:VALUE_CLASS`, `TYPES_COMPATIBLE`. It can say why:

> EXACT (COSMETIC): 4/4 columns coincide, 0 new, 0 missing, 0 in conflict, 1 renamed; types compatible; score 1.00

| Drift | Meaning | Structure |
|---|---|---|
| `NONE` | the same structure | EXACT |
| `COSMETIC` | other order, or a column renamed to what the engine reads the same | EXACT |
| `ADDITIVE` | new columns; every remembered one is still valid | COMPATIBLE |
| `MISSING` | a remembered column is gone | COMPATIBLE |
| `SEMANTIC_CONFLICT` | the header says X, the values (or the engine) say not | COMPATIBLE |
| `MAJOR_CHANGE` | fewer than half of the remembered columns are there | DIFFERENT |

## Trust: what can be learned

A memory is **TRUSTED** only through a **person**: an explicit answer to a Smart Import question that decided something the engine had
not already read clearly, or a matching built by hand ("Abbina le colonne") and then imported. How a decision was confirmed is known to
the **server** (the answers it verified, a matching by hand, a reuse of the memory) - never a claim of the client.

* a file the engine read alone (READY, nobody decided anything) leaves **ENGINE** evidence at most; it is never used to skip a question
  and never replaces what a person confirmed (the engine cannot teach itself);
* a decision that came from the memory confirms nothing new: nothing changes;
* a profile saved before this gate (no `learning` section) is **not trusted**: nobody can tell who confirmed it;
* a **correction** is a new revision; the old confirmation stays in the history (v1: `Area → department`, v2: `Reparto → department`);
* the "remember" box is the person's: with it off, the server learns nothing.

## How it is reused

A trusted memory is **evidence, never authority**. What the person decided and the file still proves is applied as if they had answered
again - *before* the required-field check, so the question that was answered does not come back and a source the engine cannot read on
its own (`MISSING_REQUIRED`) becomes READY. Priority: 1. the current document's own deterministic contradiction, 2. its structural
evidence, 3. the trusted profile, 4. generic vocabulary. So:

* **reuse what is still proven, ask what changed**: a new column is ignored; a missing one is asked about (or the file goes to the
  matching if a required field is gone); a contradicted one becomes a question ("is «Ore A» still the planned hours?");
* a **conflict** never ends in an automatic reading, and a column that turned into personal data is simply not used;
* the person's answers *now* always win over the memory; a reused decision carries the server's own reference and is verified like any
  other (PB-3);
* formats chosen before are used only where the values cannot prove them, and only if the file still reads cleanly that way.

## Several families in one source

A source is `property + kind of data`; a hotel brings back **more than one structure** in it - the PMS export, an OTA export, an
internal report. Each is a **family**, and they live side by side:

```
learning = { v: 2, seq, current, families: [ Memory{id, touched, shape, mapped, person, answers, revision, history, fingerprint}, ... ] }
```

* `Memory` is the family: its structure (header keys + value classes), its confirmed mapping, the part a person decided, its closed
  answers, its revision and its own history. `id` is a counter (never a file name, never a header); `touched` orders families by use.
* `current` is the family whose import wrote the profile's saved column matching (the legacy "last configuration"). It is applied only to
  a file of that family.
* The section written by Source Learning before there were families (one flat memory) is read as a source with one family.

**Family or revision.** A *revision* is the same family evolving: the file still holds everything the family remembers (the same
columns, moved, renamed to what the engine reads the same, with new ones, or one whose meaning the person now corrects). A confirmation
updates that family - a new revision when its meaning changed, the old one in *its* history. A *family* is another structure: as soon
as a remembered column is no longer in the file (gone, or called something else) the file starts a family of its own. The cost of one
family too many is a record; one too few would lose the family that was there.

| The file, against the family it matches best | Confirmation |
|---|---|
| the same / moved / renamed to what the engine reads the same / with new columns / a meaning corrected | a revision of that family |
| a remembered column is gone or called something else | a new family (the old one untouched) |
| the same structure and matching already a family | that family (no duplicate) |
| it could be two families and none clearly is | a new family (nothing is reused meanwhile) |

**Which family is this file?** `choose_family` matches the file with **every** family of the source (`match_source`, as before) and
measures each by its **residual**: new columns + remembered columns that are gone + contradicted columns + columns held only under
another name. The best is chosen only if it explains the file completely (residual 0) **or** leaves at least `MIN_RESIDUAL_GAP = 2`
columns fewer unexplained than the runner-up. Otherwise the result is **ambiguous: no family, nothing reused**, and the person is asked
as for a source nobody taught. With a single family that could be the file the behaviour is the one it always had.

```
A = Data | Prev. | Eff. | Area        B = Data | Prev. | Eff. | Costo
file A (or A + junk, A moved, A cosmetic)  ->  A            (residual 0 / 1, B 2 / 3)
file Data | Prev. | Eff.                   ->  ambiguous    (A 1, B 1): nothing reused
file Data | Prev. | Eff. | Altro          ->  ambiguous    (A 2, B 2)
```

A family only the engine read can win the file it is - and then nothing is reused (the engine cannot teach itself) - so a trusted
neighbour that merely resembles it is never taken for it.

**Limits.** `FAMILIES_KEPT = 32` per source and `HISTORY_KEPT = 5` per family, two different limits. Over the limit the least useful
families go first - those only the engine read, then the longest unused - and never the one just written. A dropped family is taught
once more. Matching a file against 32 families is a few milliseconds.

**Correction is local.** A confirmation updates the one family the server found the file to be a revision of (or adds one); it never
rewrites another. The engine alone writes nothing once a person has confirmed anything in the source.

## How a family is read

Which sheets are read, the hours a day grid holds and where the department comes from describe how to read **that** structure. They
are remembered with the family (`Memory.layout`) and lent back only once a file has been recognised as it. The order that makes it
deterministic:

1. **A - the document on its own terms.** Only what the person says *now* decides how it is read; the layout of the last import is
   nobody's but the family that wrote it.
2. **B - which family is it?** Every candidate table is compared with the families of the source. A table that is clearly a family's
   (nothing it remembers is lost) is preferred to the one the ranking picked; two candidates, or two families, that could both be it
   are never settled by a guess.
3. **C - its hints.** A family taught by a person, with nothing lost, lends its hints. If they name a sheet the document is read
   again through it and the hints are accepted only if that reading is the same family again; otherwise they are dropped.
4. **D - the meaning of the columns and the validation**, unchanged.

| Part of a profile's `format_options` | Belongs to |
|---|---|
| `layout.sheets`, `layout.grid`, `layout.department` | the family |
| `date_order`, `decimal_style`, `amount_basis`, `department_value` | the family (`Memory.answers`) |
| the words taught (`status`, `channel`, `role`, `category` mappings) | property + kind of data (the hotel's vocabulary) |
| `delimiter`, `encoding` | nobody: detected on every file |
| `date_formats`, `sheet_name`, the saved column matching | the profile's last import (feeds the legacy profile status only) |

What a family remembers of its *matching* is restricted to the columns the plain table has: the date and hours a grid adds, or the
department a title gives, are the layout's. The days and totals of a grid are not part of its structure (they name the week).

## Isolation

Family: a family belongs to its source and to nothing else; a file is read with one family or none, and the saved matching of the
profile is applied only to the family that wrote it (`cross-family contamination = 0`, measured).

Property: the profile belongs to a source of **one property** (composite foreign key); what one hotel learned never reaches another,
even with the same headers (workspace too). Kind of data: a profile belongs to the source of one kind of data, and a memory that says it
belongs to another is ignored. Tested explicitly; the benchmark measures cross-property and cross-domain contamination: 0.

## Known limits

* A family keeps its current structure only: an earlier revision of a family is kept in its history for audit, but a file that goes back to it is read through the current one (what is still there is reused, what is not is asked).
* Structures nested in each other (all the columns of one inside a larger one) are not told apart by the smaller one's columns alone: taught second, the larger is a revision of the smaller (nothing remembered is lost).
* The profile's saved column matching, its date formats and its sheet are still the last import's: they feed the legacy profile status and the `mapping: null` import, not the understanding flow (ADR 0035).
* Two structures that differ only in a layout choice the file does not show are one family; the last confirmation wins, with history.
* The match is made on the table as read; a grid of days is not matched by its synthetic columns (its hours basis is already remembered by the layout).
* A column renamed to something the engine cannot read is "missing", not guessed.
* There is no screen yet that says "Sorgente riconosciuta"; `FileInspection.learning` is internal and never sent to the browser.

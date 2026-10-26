# Smart Import V3 — Source Learning

Status: **implemented.** No model, no embedding, no external service: it works with `IMPORT_UNDERSTANDING_MODE=off`.
Decision: ADR 0033. Measured by the Source Learning Benchmark V1 (`docs/benchmarks/source-learning-benchmark-v1.md`).

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

## Isolation

Property: the profile belongs to a source of **one property** (composite foreign key); what one hotel learned never reaches another,
even with the same headers (workspace too). Kind of data: a profile belongs to the source of one kind of data, and a memory that says it
belongs to another is ignored. Tested explicitly; the benchmark measures cross-property and cross-domain contamination: 0.

## Known limits

* One current structure per source: an earlier structure is kept in the history for audit, but a file that goes back to it is read again.
* The match is made on the table as read; a grid of days is not matched by its synthetic columns (its hours basis is already remembered by the layout).
* A column renamed to something the engine cannot read is "missing", not guessed.
* There is no screen yet that says "Sorgente riconosciuta"; `FileInspection.learning` is internal and never sent to the browser.

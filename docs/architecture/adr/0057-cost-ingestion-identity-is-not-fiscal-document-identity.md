# ADR 0057: Cost ingestion identity is not fiscal document identity

Status: implemented on `feature/operational-costs-without-document-number` (local, not pushed, not merged). Migration `0018_cost_record_identity`. Smart Import understanding is untouched in
how it reads columns (V3 and V4 behave the same); what changes is what a cost file without a document number is allowed to become. The pilot database is not touched by this work.

## Context

The first real first-seen costs file (`costi_ottobre_2026.csv`: `Data, Fornitore, Categoria, Descrizione, Imponibile, IVA, Totale`) was understood perfectly by Smart Import V4 and could still not be
imported. The forensic diagnosis was that this is a **product-model** limit, not an understanding gap:

* every cost goes through `invoices` / `invoice_lines`, and `invoice_number` was `NOT NULL` and the only thing that identified a record (`uq_invoices_identity_revision`);
* the number could not be a constant (`CONSTANT_FIELDS` forbids it on purpose), so the "Abbina le colonne" screen the UI suggested was a dead end: it asked for a column that does not exist;
* no analysis reads the number (`CostLineRepository` uses date, currency, category, amounts): it was only ever the *identity of an ingested record*.

NINFA must analyse utilities, laundry, maintenance, supplies, commissions and monthly costs, which do not always arrive as an invoice with a number. The only way to import this file under the old
model was to **invent a number**, i.e. to store a fiscal fact that does not exist.

## Decision

1. **Two identities that are no longer the same thing.**
   *Business / fiscal identity* is `invoice_number`: it comes from the source, it is `NULL` when the source has none, and NINFA never writes a value there that the source did not state.
   *Technical identity of ingestion* is `source_record_key` (plus `identity_origin`): what NINFA needs for idempotency, revisions, removals, scope and provenance. It may be generated.
2. **Minimum change to the model, no rename.** The tables stay `invoices` / `invoice_lines`. Migration 0018 adds `identity_origin` (`DOCUMENT_NUMBER` | `SYNTHETIC_COST_RECORD`) and `source_record_key`
   to `invoices`, makes the two number columns nullable, moves the unique identity key from the number to the key, and adds `invoice_removals`. For a real document the key **is** the normalised
   number (backfilled, and enforced by a CHECK), so nothing changes for an invoice.
3. **Fiscal documents are protected by the database, not by good behaviour.** CHECKs: a `DOCUMENT_NUMBER` record has a non-blank number and `key = number`; a `SYNTHETIC` record has no number at all;
   a synthetic record is only ever a `CSV`/`XLSX` `INVOICE` (never a FatturaPA, never a credit note). `invoice_removals` has a foreign key on `(workspace, invoice, identity_origin)` to
   `invoices`, and a CHECK `identity_origin = 'SYNTHETIC_COST_RECORD'`: a fiscal document **cannot** be removed. `invoices` stays immutable (its trigger is untouched; the backfill lifts it for one
   statement inside the migration), and `invoice_removals` has the same trigger.
4. **A deterministic, versioned identity for a cost with no number (v1).** The fingerprint is SHA-256 of: the version, the **data source**, the resolved supplier, the date, the currency, the signed
   net/tax/gross amounts and the canonical lines (normalised description, quantity, unit, unit price, total, VAT rate). It excludes the row number, the file, the job, timestamps, the line
   number (always 1) and the cost category (analysis, not accounting: re-teaching a label must not change what a cost is; the same rule the invoice fingerprint already follows).
   The key is `cost:v1:<fingerprint>#<n>`. The version is part of the key, so a stored key keeps meaning what it meant.
5. **Identical rows are a multiset.** Two equal rows are two real costs and are never deduplicated. `n` counts the copies of a fingerprint in the file, never positions: the same file again, or the
   same rows in another order, produce the same keys (nothing new); a fourth equal row is only `#4`.
6. **Source scope.** The data source is inside the fingerprint of a synthetic record, so two independent sources never merge silently because they carry the same values. (A real document keeps
   the old rule: its identity excludes the data source, because the same invoice from XML and from an accounting export is one invoice.)
7. **A synthetic record has no external identity, so a changed record is a different record.** NINFA does not guess that `100,00 -> 120,00` is the same cost. With **FULL** (a person said the
   file holds everything of its period) the records of that source the file does not hold, inside the period its own rows cover (first to last date), stop counting: one `invoice_removals` row each,
   written with the import and re-checked under the source lock against the figure the person was shown (`IMPORT_PLAN_CHANGED` otherwise). **PARTIAL**, **DELTA** and no word at all take nothing away.
   A record a later file holds again counts again as the **next revision** of the same identity (the old row stays, the removal stays). `is_current_invoice()` (the one filter every cost reader
   carries) now reads the key and the removals; nothing else in analysis, decisions or Mia changed.
8. **FatturaPA and document-level files keep needing their number.** An XML reads its own number and fails without one. A structured file that carries a **document type, a due date or a line
   number** is a register of fiscal documents: the synthetic identity is refused for it (the mapping cannot be built), and Smart Import does not even ask. Supplier VAT / tax code / IBAN do *not*
   make a file document-level (they only say who the supplier is).
9. **UX: one plain confirmation, never a dead end.** When a costs file has everything an import needs except the number, Smart Import asks one question (`DOCUMENT_IDENTITY`) instead of a
   blocker: *"Questo file contiene costi senza numero documento. NINFA può registrarli come costi operativi usando un riferimento interno. Non verrà creato né modificato alcun numero di
   fattura."* with the single action *"Continua come costi operativi"*. The level is `ASK`, not `MANUAL`. The answer is part of the decision the server issues and verifies (it cannot be posted
   by hand to turn a question into a yes; a matching built by hand never carries it).
10. **Source Learning.** The answer is remembered by the family of files (the same mechanism as the net/gross basis), shown with the remembered answers, correctable by answering again after
    forgetting it, forgotten with its family, scoped to the source and never retroactive on imported data.
11. **The internal key is never shown.** It appears in no API schema, contract, copy or Mia tool, and never as "Numero fattura" / "Numero documento". It stays internal.

## Product decisions to confirm

These are choices the brief left to the implementation; each is one line to change.

* **Costs now have a scope.** Until now a cost register "may always be partial" (`scope_effect = 0`). That is still true for a register identified by document numbers. For operating costs with no
  number there is no other way to retire a stale or corrected record, so the FULL/PARTIAL/DELTA question applies to them (first file never asks; later files ask only when something would stop
  counting, and the answer is remembered only if the person ticks the box).
* **What makes a file "document-level"**: document type, due date, line number (not supplier VAT/IBAN).
* **The cost category is not part of the identity.** Two rows identical except for the category are one multiset group; the category stored is the one of the first import.

## Limitations

* The identity is a function of the **mapped columns**: a file that stops carrying a mapped field (or a source re-mapped with different columns) is a different shape, and its records do not match the
  earlier ones. With FULL they replace them; otherwise they are new records. The same holds for a corrected amount or description.
* A file of one or two rows is read with columns at medium confidence (a known Smart Import trait), so the source's memory is not reused and the question is asked again.
* Two sources of the same property with the same costs are two sets of costs by design; deduplicating between them is a decision for a person, not an identity rule.
* The downgrade of 0018 refuses once a synthetic record or a removal exists.
* Real hotel validation of this flow is still the user's first manual upload; nothing was imported into the pilot database.

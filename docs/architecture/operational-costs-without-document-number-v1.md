# Operational costs without a document number (V1)

Decision: [ADR 0057](adr/0057-cost-ingestion-identity-is-not-fiscal-document-identity.md). Migration: `0018_cost_record_identity`. Builds on [cost-ingestion-v1](cost-ingestion-v1.md),
[same-day-revisions-v1](same-day-revisions-v1.md) and [import-scope-semantics-v1](import-scope-semantics-v1.md).

## What changed, in one picture

```
  a file of costs with no document number
        |  Smart Import: everything else present, nothing document-level  -> ONE question
        v     "Continua come costi operativi"  (answer = part of the server's decision)
  InvoiceMappingConfig.format_options.document_identity = SYNTHETIC_COST_RECORD
        |  each row = one record, one line (number 1), invoice_number stays NULL
        v
  fingerprint v1 (data source, supplier, date, currency, amounts, line content)
        |  occurrence n among identical fingerprints (a MULTISET)
        v
  invoices.source_record_key = cost:v1:<fingerprint>#<n>   identity_origin = SYNTHETIC_COST_RECORD
        |  FULL only: absent keys of this source, inside the file's own period -> invoice_removals
        v
  is_current_invoice() = newest revision AND not removed   (the only filter the analysis carries)
```

## Data model

| Object | What |
| --- | --- |
| `invoices.identity_origin` | `DOCUMENT_NUMBER` (default, every existing row) \| `SYNTHETIC_COST_RECORD` |
| `invoices.source_record_key` | technical identity, `NOT NULL`. A real document: **equals** `normalized_invoice_number` (CHECK). A synthetic record: `cost:v1:<64 hex>#<n>` |
| `invoices.invoice_number`, `normalized_invoice_number` | nullable; `NULL` **only** for a synthetic record (CHECK `identity_consistent`) |
| `uq_invoices_identity_revision` | `(workspace, property, supplier, source_record_key, invoice_date, document_kind, revision)` |
| `ck_invoices_synthetic_only_for_spreadsheets` | a synthetic record is a `CSV`/`XLSX` `INVOICE`: never a FatturaPA, never a credit note |
| `invoice_removals` | one row per synthetic record taken away, with the import that did it. FK `(workspace, invoice_id, identity_origin) -> invoices` + CHECK `identity_origin = 'SYNTHETIC_COST_RECORD'`: a fiscal document cannot be removed. Immutable (trigger) |

The migration backfills the key under the immutability trigger (lifted for that one statement and put back in the same transaction). The downgrade refuses once a synthetic record or a removal exists.

## The identity, precisely

* **Fingerprint v1** = SHA-256 of canonical JSON of: `v`, the data source id, the resolved supplier id, the date, the currency, the signed net / tax / gross, and the sorted canonical lines
  (normalised description, quantity, lower-cased unit, unit price, line total, VAT rate). **Excluded:** row and line numbers, file name, job, timestamps, the cost category.
* **Occurrences are matched, never positioned** (`InvoiceImportService._place_synthetic`). For one fingerprint: (1) an occurrence keeps the record already holding the same **stated** category;
  (2) the rest are paired in a fixed order with the records left (a different stated category = a **reclassification**: the next revision of the same key; no stated category = nothing changes);
  (3) the remaining occurrences are new (a removed record comes back first, as `revision + 1`). The category compared is the one the SOURCE stated (`EXPLICIT_SOURCE`), never a derived one.
  Reordering the rows or importing the file again changes nothing; the preview of what a complete file takes away uses the same placement.
* **Versioning.** `RECORD_KEY_VERSION = 1` is part of the key; a change of what the content holds is a new version.

## FULL / PARTIAL / DELTA for operating costs

| File says | Effect on the records of the source it does not hold |
| --- | --- |
| nothing (first file, CLI, saved config, hand-built matching) | nothing |
| PARTIAL, DELTA | nothing |
| FULL | the **synthetic** records of this data source dated within `[first date, last date]` of the file, whose key the file does not hold, stop counting (`invoice_removals`); recomputed and compared with the figure shown under the source lock (`IMPORT_PLAN_CHANGED`) |

A real invoice is never removed by any file. Registers identified by document numbers keep their old rule (`scope_effect = 0`, a register may always be partial).

## Smart Import

* `QuestionKind.DOCUMENT_IDENTITY`, asked only when: the domain is COSTS (detected or confirmed), no column is (or may be) the number, the file does not give STRONG evidence of being a register of
  fiscal documents (`invoices.mapping.document_evidence`: a document type, or due date + row number + a fiscal supplier identifier), and every other required group (supplier, date, description,
  line total) is present. With no document signal at all it has one choice ("Continua come costi operativi"); with weak signals only (a due date and/or a row number) it has two
  ("Un registro di costi operativi" / "Fatture o documenti") and the file is not blocked.
* Level: `ASK` with the one question (a provisional check is made as if the answer were given, so the file is not sent to the matching screen). After the answer the number is not required
  (`FileDomain.required_groups(decision)`), the decision carries `document_identity`, and the server's re-read must agree.
* The answer is kept in the family's memory (`REMEMBERED_ANSWERS += document_identity`) like the net/gross basis; it is listed with the remembered answers and forgotten with its family.
* Copy (Italian) lives in `apps/web/lib/sources/copy.ts` (`understanding.question.DOCUMENT_IDENTITY`); Mia explains the question (`mia/tools/imports.py`, knowledge entry
  `import.question_document_identity`).

## Surfaces that must never show the key

`test_the_internal_key_appears_in_no_surface_a_person_reads` scans `app/api` and the contracts for `source_record_key`, `identity_origin`, `cost:v1`. The preview sample drops the `invoice_number`
column when no row has one. Nothing is labelled "Numero fattura" for a synthetic record.

## Tests

| Brief | Where |
| --- | --- |
| A numbered cost unchanged | `test_operational_costs.py` (A), plus the 822 pre-existing invoice/cost tests |
| B, C, D, E, F | importer: import after the person's word, no-op, reorder, identical rows, 2 -> 3 |
| G, H, I, J | importer: FULL 3 -> 2, PARTIAL, DELTA, a changed amount (replaced under FULL, never inferred) |
| K | two sources never merge; a complete file of one never takes away the other's |
| L | FatturaPA without a number still fails; document-level mapping refused; DB CHECKs |
| M | no invented number stored; the key is on no surface; the key is a hash |
| N, O | `test_operational_costs_smart_import.py`: remembered, listed, forgotten, answered again |
| P | an unmapped column is never stored; the key carries no value of the file |
| Analytics | the same cost with and without a number aggregates identically; a removal leaves the analysis |

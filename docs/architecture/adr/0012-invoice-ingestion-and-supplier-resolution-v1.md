# 0012 — Invoice ingestion and supplier resolution V1

**Status:** accepted (Gate 6)

## Context
Costs are the other half of the decisions NINFA will help with. Before any cost can be compared with
anything, purchase invoices must become trustworthy facts: who the supplier is (the same company
appears under many spellings and in many files), what each document says, what each line was spent
on, and how many times a document has already been counted. Three temptations must be resisted:
merging suppliers on a similar name, "helpfully" reading whatever file format the customer has, and
computing cost indicators on data that is not yet reliable.

## Decision
1. **Supplier is workspace-wide.** A supplier belongs to the customer (workspace), not to one
   property: the same laundry serves every property of the group. An invoice, in contrast, belongs to
   exactly one property. This keeps one registry per customer (one place to verify, one place to
   review) while cost analysis stays per property. Tests prove one supplier with invoices in two
   properties.
2. **Identifier priority: VAT number > tax code > IBAN hash > exact name.** Stable fiscal
   identifiers outrank the name; the name only decides when no identifier does. VAT is
   `IdPaese + IdCodice` with structural validation only (no Italian-only checksum: foreign suppliers
   work). Several identifiers of one record pointing at one supplier are valid; identifiers pointing
   at different suppliers, or an identifier contradicting the matched supplier, are a hard
   `SUPPLIER_IDENTITY_CONFLICT` — NINFA prefers a failed import to a wrong merge.
3. **No raw IBAN.** The IBAN is a strong identifier and a sensitive datum. It is normalised and
   hashed with SHA-256 at the parsing boundary and stored only as an `IBAN_SHA256` identifier; the raw
   value never reaches a table, a log, a staging row or an error (a test scans every table).
   The digest still lets two documents of one supplier meet.
4. **Fuzzy matching never merges.** A similar name (difflib matching blocks, threshold 0.85,
   four decimals, versioned `supplier-resolution-v1`) can only open a `PENDING` possible-duplicate
   review: the invoice stays on a newly created supplier. A supplier with a different VAT number or
   tax code is not even proposed, and the same name with a different fiscal identity is a new
   supplier plus a review, never a name merge. `ROSSI FOOD SRL` and `ROSSI FOOD SPA` are different
   names: legal forms are not stripped. Merging is a later gate, after a person confirms a review.
5. **Invoice identity does not include the data source.** The identity is
   `(workspace, property, supplier, normalised number, date, kind)`. The same invoice from an XML
   file and from an accounting export is one cost: same content reuses the invoice, different content
   is `INVOICE_DOCUMENT_CONFLICT`. Keying on the data source would double-count costs the moment a
   customer exports the same invoices two ways. The invoice number is normalised conservatively
   (case, whitespace, Unicode form; slash, dash and letters are kept: `123/A` is not `123A`).
6. **Invoices are immutable.** A `BEFORE UPDATE` trigger refuses every update to `invoices` and
   `invoice_lines`, like snapshots and baselines. A document that changes is a conflict to look at,
   never a silent overwrite; the fingerprint (SHA-256 of the canonical business content, not of
   file names, jobs or timestamps) decides "same" versus "different".
7. **Credit notes are signed.** A credit note (FatturaPA TD04 / TD08, or a structured file's document
   type) is stored with negative amounts so that `SUM(line_total)` is right without anyone
   re-reading the document type. A deterministic rule decides from the document's own headline amount
   whether the source wrote it positive or already negative, so nothing is negated twice. Amounts are
   quantised once, `HALF_UP`, after the sign, on exact `Decimal` values.
8. **Atomic import.** Parse, normalise, group, validate and stage first; only when every document is
   valid is the canonical write done, in one transaction, under a per-data-source and a
   per-workspace-registry advisory lock. One invalid row, a supplier conflict or a database error
   leaves the staging and a `FAILED` job and creates nothing else. Partial imports would make every
   later number ambiguous.
9. **PDF, OCR and .p7m are out of V1.** FatturaPA XML is a structured, deterministic source and
   structured CSV/XLSX are the customer's own exports. A PDF or a scan needs OCR or a model, whose
   errors would enter the accounting record with no way to audit them; a `.p7m` needs unwrapping a CMS
   signature. Each is refused with a stable code and the limit is documented, not hidden. The XML
   reader uses the standard-library parser with a builder that refuses any DOCTYPE, so no
   dependency and no custom parser were added.
10. **Deterministic classification.** A line's category comes, in order, from the source (100), the
    supplier's default (90), a small high-precision phrase dictionary (80) or is `OTHER` with
    confidence 0. The confidence is provenance, not a probability; an ambiguous description stays
    `OTHER`. There is no AI and no fuzzy category matching: a wrong category silently corrupts every
    later cost analysis, an `OTHER` is visible and can be fixed.
11. **Data minimisation.** Only mapped columns are read; the recipient, addresses, phones, e-mails,
    PEC and attachments of an XML are never read; staging holds field names and codes, not values.
12. **No cost indicator yet.** No cost baseline, cost per occupied room, anomaly, price trend,
    persisted decision, priority, impact or recommendation, and no public API: they need trustworthy
    facts first, and this gate is what makes the facts trustworthy.

## Consequences
- One migration, `0007_invoice_supplier_ingestion` (eight tables, one function, two triggers and one
  foreign-key-target key on `data_sources`); no dependency was added.
- A supplier that changes VAT number will not merge with its old self by itself: it appears as a new
  supplier with a review until a later gate offers the merge.
- A customer who corrects an invoice at the source gets `INVOICE_DOCUMENT_CONFLICT` until an
  invoice-correction flow exists; nothing is ever silently rewritten.
- A model or heuristic classifier can replace the phrase dictionary later without touching the
  canonical model: only `classification_method` and the confidence change meaning.

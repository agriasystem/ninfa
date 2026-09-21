# NINFA — Cost ingestion v1 (Gate 6)

Gate 6 turns a customer's purchase invoices into **canonical suppliers, invoices and invoice
lines**, without the customer editing the file. It is data in and data stored correctly: it computes
no cost per occupied room, no baseline, no anomaly and no decision (those belong to later gates).
Decisions: [ADR 0012](adr/0012-invoice-ingestion-and-supplier-resolution-v1.md). Schema:
[data-model-v1.md](data-model-v1.md). Migration: `0007_invoice_supplier_ingestion`.

**Gate 6 V1 supports FatturaPA XML, structured CSV and structured XLSX.** PDF, scanned documents
(OCR) and signed .p7m files are NOT supported: they are refused with a stable error code, and
nothing in the code pretends otherwise (there is no PDF parser, OCR, AI or extraction of any kind).

Code: `services/api/app/modules/suppliers/` (registry and resolution) and
`services/api/app/modules/invoices/` (canonical model, parsers, classification, import service).
There is **no public API**: OpenAPI still exposes only the health check.

## Pipeline

```
FILE ─► type detection ─► parser ─► mapped / canonical values only ─► normalisation
     ─► document grouping ─► row validation ─► STAGING ─► all-document validation
     ─► supplier resolution PLAN ─► atomic canonicalisation
     ─► suppliers, identifiers, aliases, reviews ─► invoices ─► lines ─► import job result
```

`InvoiceImportService` (framework-free, callable by a future worker) owns four transactions, the
same pattern as the booking import:

| Step | Does | Commit |
| ---- | ---- | ------ |
| T1 | records the `ImportJob` (`PENDING`) and the `ImportFile` metadata, marks the job `RUNNING` | yes |
| T2 | detects the type, parses, normalises, groups, validates and **stages** every line | yes |
| T3 | (any invalid row) marks the job `FAILED` with the stable code | yes |
| T4 | (all valid) takes two advisory locks, resolves suppliers, writes suppliers/identifiers/aliases/reviews, invoices and lines, marks the staged rows `IMPORTED`, marks the job `SUCCEEDED` | yes, or **rollback** and a separate transaction marks the job `FAILED` |

The data source must be an **active `COSTS` / `FILE_UPLOAD`** source of the workspace (and of the
stated property, when one is given). A `BOOKINGS` or `LABOR` source, an inactive one, one of another
property, or one of another workspace is refused with `INVOICE_INVALID_DATA_SOURCE`; a foreign id
and an unknown id are **indistinguishable** (same code, same message, same details). The mapping
and describe calls apply the same data-source rules.

## Supplier Registry

A **Supplier is workspace-wide**, not property-owned: the same supplier serves all the properties of
one customer, and an invoice (which belongs to ONE property) points at it. The registry holds an
accounting identity only:

| Table | Holds |
| ----- | ----- |
| `suppliers` | `legal_name`, `normalized_name`, `country`, `default_cost_category`, `is_active`, `is_verified` |
| `supplier_identifiers` | `kind` ∈ `VAT_NUMBER`, `TAX_CODE`, `IBAN_SHA256`; `normalized_value`; **unique per (workspace, kind, value)** |
| `supplier_aliases` | the normalised spellings a supplier appeared under, and the data source it was first seen in |
| `supplier_resolution_reviews` | possible duplicates for a person to look at (`PENDING` only in this gate) |

A supplier stores **no e-mail, phone, address, PEC or contact person**. Suppliers evolve
(identifiers, aliases, verification and the default category change); there is **no supplier merge**
and no way to move an invoice from one supplier to another (a later gate will, after a person
confirms a review). A new supplier is always created by the resolver, never by a client, and starts
`is_verified = false`.

### Identifiers

- **VAT number**: `IdPaese + IdCodice`, upper case, no spaces or punctuation (`IT01234567890`).
  Structural validation only: an Italian number has 11 digits, a foreign one 2 letters plus 2 to 28
  alphanumerics. There is no national checksum, so foreign suppliers work and an invented but
  well-formed number is not "verified" by NINFA. Eleven bare digits are read as Italian.
- **Tax code** (`CodiceFiscale`): upper case, no whitespace, 5–20 alphanumerics. It is not always a
  person's fiscal code (a company's is numeric), so only its shape is checked.
- **IBAN**: normalised (spaces and separators removed, upper case, structure and mod-97 checked),
  then hashed with **SHA-256**; the digest is stored as an `IBAN_SHA256` identifier.
  **The raw IBAN is never stored**, logged, staged or put in an error; a database `CHECK` even
  refuses an `IBAN_SHA256` value that is not 64 lowercase hex characters. An invalid IBAN is
  ignored with the warning `INVALID_IBAN_IGNORED` (its value is not echoed). In FatturaPA an IBAN
  whose `Beneficiario` is not the supplier is a third party's account (a factor, a group company):
  it is ignored with `BENEFICIARY_IBAN_IGNORED` and does not identify the supplier.

### Names and aliases

The normalised name ignores case, accents, punctuation and spacing (`Caffè  Rossi S.r.l.` and
`CAFFE ROSSI SRL` are the same). Dots are removed first, so `S.r.l.` and `SRL` agree. **Legal forms
are not stripped**: `ROSSI FOOD SRL` and `ROSSI FOOD SPA` are two different names and never merge
automatically. Aliases have **no global uniqueness**: two suppliers may really have alike names, and
an exact alias is used to choose a supplier only when it identifies ONE coherent supplier.

### Resolution (`SupplierResolver`, policy `supplier-resolution-v1`)

A separate service (no HTTP, no import service), testable with canonical evidence. The registry of
the workspace is loaded in **three statements** and resolved **in memory**; a plan is written only
once the whole file is valid. Priority: **VAT number, then tax code, then IBAN hash, then exact name**
(or alias). A fuzzy similarity is the fifth and last step and never assigns anything (below).

The typed outcome (with the evidence: identifier kinds and ids, never values) is one of:

| Outcome | Meaning |
| ------- | ------- |
| `MATCHED_EXACT_IDENTIFIER` | one or more identifiers point at ONE supplier (method `VAT_NUMBER` / `TAX_CODE` / `IBAN_SHA256`, the highest that matched) |
| `MATCHED_EXACT_NAME` | no identifier matched, the normalised name (method `EXACT_NAME`) or an alias (`EXACT_ALIAS`) identifies ONE compatible supplier |
| `CREATED_NEW` | no safe match: a new unverified supplier with the available identifiers and its normalised alias |
| `CREATED_NEW_WITH_REVIEW` | as above, and a `PENDING` review toward a plausible existing supplier |

Rules that keep it safe:

- Several identifiers of the record pointing at the **same** supplier are valid.
- Identifiers pointing at **different** suppliers, or an identifier that contradicts the supplier
  another one matched (the same bank account with another VAT number), are a hard
  `SUPPLIER_IDENTITY_CONFLICT`: the import fails, NINFA does not guess.
- An identifier the registry does not know is **added** to the matched supplier (enrichment); one
  owned by another supplier is the conflict above.
- A name that fits more than one compatible supplier is `SUPPLIER_NAME_AMBIGUOUS`, never an
  arbitrary pick.
- The **same name with a different VAT number or tax code** does not merge by name: a new supplier
  is created and a review (`NAME_MATCH_IDENTITY_CONFLICT`, similarity 1.0000) points at the first.

### Fuzzy matching and reviews

**A fuzzy match never merges two suppliers.** Similarity is the ratio of matching blocks of the two
normalised names (Python's `difflib`, integer arithmetic, four decimals, no float in the result). The
threshold `0.85`, at most `3` reviews per
new supplier, and the policy version `supplier-resolution-v1` are constants in
`suppliers/normalization.py` and are tested. Fuzzy matching is used **only to open a possible
duplicate review** (`FUZZY_NAME_SIMILARITY`): the invoice stays on the newly created supplier, the
review is `PENDING`, and a supplier with a *different* VAT number or tax code is not even proposed
(two fiscal identities are two entities). There is no review endpoint and no merge in this gate.

## Canonical invoice

`invoices` (one row per document) and `invoice_lines`. An invoice belongs to one property and comes
from one data source, import job and file, but it is **not identified by them**.

| Field | Notes |
| ----- | ----- |
| identity | `(workspace, property, supplier, normalised invoice number, invoice date, document kind)` — **unique** |
| `invoice_number` / `normalized_invoice_number` | the source spelling / trimmed, Unicode-compatibility form, whitespace collapsed, upper case. Slash, dash and letters are **kept**: `123/A` is not `123A` |
| `document_kind` | `INVOICE` or `CREDIT_NOTE` (FatturaPA TD04 and TD08); `document_type_code` keeps the source code |
| `currency` | ISO 4217 (structured files default to the property's currency when unmapped) |
| `net_amount`, `tax_amount`, `gross_amount` | nullable, `NUMERIC(14,2)`, signed |
| `due_date` | nullable; see below |
| `source_format`, `source_fingerprint`, `supplier_resolution_method` | provenance |

**The data source is not part of the invoice identity.** The same invoice arriving through an XML
file and through an accounting export is one cost: it is reused when the content is the same and is
a conflict when it is not.

### Idempotency and conflicts

| Situation | Result |
| --------- | ------ |
| same identity, same fingerprint | no-op (the existing invoice is reused; counted as `invoices_unchanged`) |
| same identity, different canonical content | `INVOICE_DOCUMENT_CONFLICT` — never a silent update; the whole import is rolled back |
| the same file twice in one data source | no duplicate; the result names the earlier file (`duplicate_of_import_file_id`, informational) |
| the same invoice twice inside one import | `INVOICE_DOCUMENT_CONFLICT` (`duplicate_in_import`) |
| the same number in another property, on another date, from another supplier, or as an invoice vs a credit note | another invoice |

The **fingerprint** is the SHA-256 of the *canonical* business content: the resolved supplier, the
identity, the currency, the signed amounts and the ordered canonical lines. It does not cover the
file name, the job, timestamps, the due date, the raw type code or the cost categories, so two source
formats that state the same canonical invoice have the same fingerprint (a test proves an XML and a
CSV do). `ImportFile.sha256` is not globally unique; the same content in the same data source is
re-runnable idempotently.

### Credit notes and signed semantics

**A credit note is stored with negative amounts** (`net`, `tax`, `gross` and every `line_total`), so
a plain `SUM(line_total)` is right everywhere and nobody re-reads TD04. A deterministic function
(`document_multiplier`) decides, per document and from its own headline amount (gross, else net,
else the sum of the lines), whether the source wrote the credit note positive (negate everything) or
already negative (leave everything): **no double negation**. Tests cover a credit note with positive
amounts, one already negative, and a positive invoice; a database `CHECK` refuses positive header
amounts on a credit note. An invoice keeps the amounts of the source.

### Amounts

`Decimal` from the parser to the `NUMERIC` column, never a float (a test bans it). A source may carry
up to eight decimals (FatturaPA does); the canonical amount is quantised **once**, `HALF_UP` to two
decimals, **after** the sign rule, on the exact values. Quantities and unit prices keep eight
decimals. NINFA does **not** require `SUM(lines) = gross`: VAT, stamp duty, discounts, withholdings
and rounding legitimately make them differ. The difference is computed as a *diagnostic*
(`CanonicalDocument.reconciliation()`) and is not stored on the invoice.

### Lines and cost categories

`invoice_lines`: source line number, raw and normalised description, quantity, unit, unit price,
`line_total`, VAT rate, `cost_category`, `classification_confidence` and `classification_method`.
Unique per `(invoice, source line number)`.

Categories (stored as `VARCHAR` with a named `CHECK`, never a PostgreSQL enum): `PERSONNEL`,
`LAUNDRY`, `CLEANING`, `AMENITIES`, `FOOD`, `BEVERAGE`, `UTILITIES`, `MAINTENANCE`, `SOFTWARE`,
`MARKETING`, `OTA_COMMISSIONS`, `PROFESSIONAL_SERVICES`, `TRANSPORT`, `OTHER`.

**Deterministic classification** (`cost-classification-v1`), first match wins, no AI and no fuzzy
category matching:

| Order | Source of the category | `classification_method` | Confidence |
| ----- | ---------------------- | ----------------------- | ---------- |
| 1 | a category the source states, validated and mapped | `EXPLICIT_SOURCE` | 100 |
| 2 | the supplier's default cost category | `SUPPLIER_DEFAULT` | 90 |
| 3 | a small high-precision phrase dictionary, whole words on the normalised description | `DETERMINISTIC_RULE` | 80 |
| 4 | nothing safe | `UNCLASSIFIED` (`OTHER`) | 0 |

The confidence is **provenance, not a probability**: it says where the category came from. A
description that matches the phrases of two different categories is ambiguous and stays `OTHER`; when
in doubt the answer is `OTHER`. A source label that is neither mapped nor a canonical name is
`INVOICE_UNKNOWN_CATEGORY` (the import fails and says which label).

## FatturaPA XML

Versions 1.2.x (`FPR12` private, `FPA12` public administration), read by
`invoices/fatturapa.py`. Element names are matched by **local name**, so any namespace prefix works.

- **One file, several bodies**: every `FatturaElettronicaBody` is a separate document that shares the
  supplier of the header. One invalid body fails the whole import (atomicity), and a duplicate of
  another body of the file is refused.
- **Supplier** from `CedentePrestatore`: `Denominazione` (or `Nome` + `Cognome`), `IdFiscaleIVA`,
  `CodiceFiscale`, the country, and the payment IBANs (hashed at once).
- **Document**: `TipoDocumento`, `Divisa`, `Data`, `Numero`, `ImportoTotaleDocumento` (nullable),
  the `DatiRiepilogo` totals (`ImponibileImporto`, `Imposta`, summed), and per line `NumeroLinea`,
  `Descrizione`, `Quantita`, `UnitaMisura`, `PrezzoUnitario`, `PrezzoTotale`, `AliquotaIVA`.
- **Document types**: `TD01`, `TD02`, `TD03`, `TD05`, `TD06`, `TD07`, `TD09`, `TD24`, `TD25` are
  invoices; **`TD04` and `TD08` are credit notes**. Reverse-charge and self-invoice types
  (TD16–TD28) swap supplier and buyer and are refused per document (`UNSUPPORTED_DOCUMENT_TYPE`).
- **Due dates**: one distinct `DataScadenzaPagamento` is stored; **several distinct dates leave
  `due_date` NULL with the warning `MULTIPLE_PAYMENT_DUE_DATES`** (never one invented representative).
- **Never read**: the recipient (`CessionarioCommittente`, no customer matching), addresses, CAP,
  city, province, phone, e-mail, PEC, attachments. They cannot reach the database, the logs or an
  error.
- **XML security**: the standard-library parser with a builder that **refuses any DOCTYPE**;
  entities can only be declared in a DOCTYPE, so none is ever expanded and no external resource is
  ever fetched (`INVOICE_XML_SECURITY_REJECTED`; also for UTF-16 input). Files over 25 MB, more than
  5,000 documents or 10,000 lines in one document are refused. There is no custom XML parser and no
  new dependency.
- **`.p7m`** (signed) files are refused with `INVOICE_UNSUPPORTED_FILE_TYPE` and the reason
  `signed_p7m_not_supported`: a signed file is a CMS envelope around the XML and unwrapping it is out
  of V1. Export the plain `.xml`.

## Structured CSV and XLSX

The Gate 2 readers are reused as they are (UTF-8, UTF-8 with BOM, CP1252; comma, semicolon or tab;
`openpyxl` for `.xlsx`; hidden and empty sheets ignored; a workbook with several candidate sheets
needs the sheet to be chosen). No pandas.

**Mapping memory** — `invoice_mapping_profiles`, one per COSTS data source: `column_mapping`,
`category_mapping`, `format_options` (sheet, delimiter, encoding, explicit date patterns, decimal and
thousands separators) and a `header_signature`. It is **not** the booking mapping (different fields
and rules, and nothing was bent).

| | Fields |
| - | ------ |
| required | `supplier_name`, `invoice_number`, `invoice_date`, `line_description`, `line_total` |
| optional | `supplier_vat_number`, `supplier_tax_code`, `supplier_iban`, `due_date`, `document_type`, `currency`, `invoice_net_amount`, `invoice_tax_amount`, `invoice_gross_amount`, `line_number`, `quantity`, `unit`, `unit_price`, `vat_rate`, `cost_category` |
| may be a constant | `document_type`, `currency`, `cost_category` — **never** the invoice number, the dates, the supplier, the description or the amount |

- **Only mapped columns are read.** Every other column (a customer's name, an e-mail, a phone) is
  dropped at once, before staging, logs or errors.
- **Grouping**: rows with the same invoice number, date, kind and supplier (VAT number, else tax
  code, else normalised name) form ONE invoice, wherever they are in the file. Header fields
  repeated on the lines must **agree**: two currencies, two totals, two due dates or two tax codes
  reject the document (`INVOICE_INCONSISTENT_HEADER`; there is no "last row wins"). A value stated on
  one line only is enough.
- **Line numbers**: the mapped `line_number`, else the spreadsheet row number. Two lines with the
  same number are `INVOICE_DUPLICATE_LINE`.
- **Nothing is guessed**: `01/02/2026` and `1,234` mean two things, so an unstated date pattern or
  separator is `INVOICE_AMBIGUOUS_DATE_FORMAT` / `INVOICE_AMBIGUOUS_NUMBER_FORMAT` and the profile
  must say. Excel doubles are read through their shortest representation (`0.1` is `0.1`).
- **Header memory**: the import checks that every *mapped* column is still in the file. A missing or
  renamed one is `INVOICE_SOURCE_SCHEMA_CHANGED`; **extra columns are harmless**; duplicate headers
  are `INVOICE_DUPLICATE_HEADER`. Without a confirmed mapping the import is `INVOICE_MAPPING_REQUIRED`.
- **Document type** labels (`TD04`, `credit note`, `nota di credito`, ...) map to invoice / credit
  note; an empty cell is an ordinary invoice; an unknown label is `INVOICE_UNKNOWN_DOCUMENT_TYPE`.

## Staging and data minimisation

`invoice_import_rows` holds one row per source **line** (a document header rides on its first
line): the mapped values as text, the normalised payload, the status (`VALID`, `INVALID`,
`IMPORTED`), and the errors and warnings as **field names and stable codes, never values** (the only
value ever echoed is an unknown category label, which is needed to fix a mapping). A `CHECK` ties
the status to the errors (`INVALID` ⇔ at least one error). It never holds the whole XML, recipient
data, supplier phone/e-mail/address, a raw IBAN or an unmapped column.

Logs carry only `workspace_id`, `property_id`, `data_source_id`, `import_job_id`, `import_file_id`
and counts. The tests scan **every table of the schema**, the logs, the results and the errors for a
source that contains a supplier e-mail, phone and street, the recipient's name, tax code and
address, the PEC, an embedded attachment and a raw IBAN; none of it may appear, while the authorised
data and the IBAN's SHA-256 do (a control test proves the scan can see data).

## Atomicity

Any invalid row or document leaves the staging rows and a `FAILED` job (with the stable
`INVOICE_VALIDATION_FAILED` and a per-code count) and creates **zero** suppliers, identifiers,
aliases, reviews, invoices and lines. A failure while resolving or writing (a supplier conflict, a
document conflict, a database error) rolls back the whole T4 transaction, including the suppliers
the valid documents would have created; the job is then marked `FAILED` in its own transaction and
the staged rows stay `VALID` for diagnosis. An unexpected exception can never leave a job `RUNNING`.
A file is imported all or nothing: completely or not at all.

Concurrency: T4 takes the per-data-source advisory lock and then a per-workspace supplier-registry
lock (a fixed order), so two imports can neither create the same new supplier twice nor write the
same invoice twice.

## Error codes

Branch on the code, never the message.

| Code | When |
| ---- | ---- |
| `INVOICE_INVALID_DATA_SOURCE` | not an active COSTS / FILE_UPLOAD source of this workspace (raised, nothing created) |
| `INVOICE_UNSUPPORTED_FILE_TYPE` | not `.xml`, `.csv` or `.xlsx` (PDF, scans and `.p7m` included) |
| `INVOICE_UNREADABLE_FILE`, `INVOICE_EMPTY_FILE`, `INVOICE_FILE_LIMIT_EXCEEDED` | malformed, no rows, over a limit |
| `INVOICE_MAPPING_REQUIRED`, `INVOICE_INVALID_MAPPING`, `INVOICE_SOURCE_SCHEMA_CHANGED`, `INVOICE_DUPLICATE_HEADER` | mapping memory |
| `INVOICE_AMBIGUOUS_DATE_FORMAT`, `INVOICE_AMBIGUOUS_NUMBER_FORMAT` | formats that must be stated |
| `INVOICE_UNSUPPORTED_FATTURAPA`, `INVOICE_XML_SECURITY_REJECTED` | XML that is not 1.2.x FatturaPA; a DOCTYPE / entity |
| `INVOICE_VALIDATION_FAILED` | at least one invalid row (see the row codes) |
| `INVOICE_DOCUMENT_CONFLICT` | an existing invoice with a different content, or a duplicate in the file |
| `SUPPLIER_IDENTITY_CONFLICT`, `SUPPLIER_NAME_AMBIGUOUS` | supplier resolution refused to guess |
| `INVOICE_CANONICALIZATION_FAILED`, `INVOICE_INTERNAL_ERROR` | the database refused the batch (constraint name only); a bug |

Row codes: `INVOICE_REQUIRED_VALUE_MISSING`, `INVOICE_INVALID_DATE`, `INVOICE_INVALID_NUMBER`,
`INVOICE_AMOUNT_PRECISION`, `INVOICE_OUT_OF_RANGE`, `INVOICE_VALUE_TOO_LONG`,
`INVOICE_INVALID_CURRENCY`, `INVOICE_INVALID_VAT_NUMBER`, `INVOICE_INVALID_TAX_CODE`,
`INVOICE_INVALID_COUNTRY`, `INVOICE_UNKNOWN_DOCUMENT_TYPE`, `INVOICE_UNSUPPORTED_DOCUMENT_TYPE`,
`INVOICE_UNKNOWN_CATEGORY`, `INVOICE_DUPLICATE_LINE`, `INVOICE_INCONSISTENT_HEADER`,
`INVOICE_NO_LINES`. Warnings (never stop an import): `MULTIPLE_PAYMENT_DUE_DATES`,
`INVALID_IBAN_IGNORED`, `BENEFICIARY_IBAN_IGNORED`.

## Immutability and tenant integrity

`invoices` and `invoice_lines` are immutable accounting evidence: a `BEFORE UPDATE` trigger refuses
every update (even a no-op). Suppliers, identifiers, aliases and reviews evolve. Every foreign key
is composite and carries the workspace (and property / data source where they apply), all
`RESTRICT`: an identifier or alias to its supplier, a review to its two suppliers, an alias to its
data source, an invoice to its property, data source (of that property), supplier, import job (of
that data source) and import file (of that job), a line to its invoice, a mapping profile to its
property and data source, a staging row to its job and file. A raw cross-tenant `INSERT` is refused
by PostgreSQL (tests). The one change to an earlier table is an added key,
`UNIQUE (workspace_id, id)` on `data_sources`, that only exists to be a foreign-key target.

## Explainability

For any invoice the database alone answers: which import job and file it came from (and the file's
base name), which supplier it belongs to and **how that supplier was resolved**
(`supplier_resolution_method`), with which identifiers (kinds and values, an IBAN only as its
hash), its identity, kind and totals, and each line with its category, method and confidence. For a
fuzzy review: the provisional and the candidate supplier, their normalised names, the similarity and
the reason — and, because the review is `PENDING` and nothing merged, *why no auto-merge happened*.

## Performance

An import costs a **bounded number of statements** whatever its size (tests count statements, never
time): about 30 for a file of 100 invoices and 1,000 lines, and the same about 30 for one of five
invoices; a rerun about 26. The supplier registry is read once (one statement per table), existing
invoices are found with one join against a `VALUES` list per 2,000 identities, and suppliers,
identifiers, aliases, reviews, invoices, lines and staging rows are written with one bulk statement
per kind (per 1,000 rows).

## Limitations (intentional)

- Only FatturaPA XML 1.2.x, structured CSV and structured XLSX. **No PDF, OCR, signed `.p7m`.**
- No API, no worker task, no scheduler, no file storage: the service is called with the bytes.
- No supplier merge, no review resolution, no invoice correction (a changed invoice is a conflict).
- Reverse-charge / self-invoice document types (TD16–TD28) are not supported.
- A structured file lists a document's lines under the same supplier spelling; a document whose
  lines name the supplier differently is `INVOICE_INCONSISTENT_HEADER`.
- The header totals of a FatturaPA are the sums of its VAT summaries; `ImportoTotaleDocumento`
  is the gross amount when present.
- Cost categories are a closed V1 list and the phrase dictionary is deliberately small: a line the
  rules do not recognise is `OTHER` with confidence 0, not a guess.
- No supplier price trend, supplier inflation or decision. Gate 7 is the first consumer of the
  canonical lines: `COST_CPOR_ANOMALY` (rules `cost-cpor-anomaly-v1`,
  [cost-cpor-anomaly-v1.md](cost-cpor-anomaly-v1.md)) reads the signed `line_total`, the category and
  its classification confidence by **invoice date**, across data sources, and changes nothing here:
  no column, table or migration. `OTHER` lines are what its classification coverage measures.

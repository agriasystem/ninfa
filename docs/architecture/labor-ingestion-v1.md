# NINFA — Labor ingestion v1 (Gate 8, Part A)

See [ADR 0014](adr/0014-labor-ingestion-and-overstaffing-v1.md) for the decisions and their
rationale. This document is the reference for the canonical model and the import pipeline.

## Pipeline

```
FILE -> TYPE DETECTION -> PARSER -> MAPPING -> NORMALIZATION -> CLASSIFICATION
     -> ROW VALIDATION -> STAGING -> ALL-ROWS VALIDATION -> CANONICAL SNAPSHOT
     -> LABOR ENTRIES -> IMPORT JOB RESULT
```

`LaborImportService.import_file()` owns four transactions, exactly the Gate 6 shape:

| Step | Does | Commit |
|---|---|---|
| T1 | create `ImportJob` (PENDING) + `ImportFile`, mark RUNNING | commit |
| T2 | parse -> map -> normalise -> classify -> validate -> stage every row | commit |
| T3 | (any row INVALID) mark the job FAILED | commit |
| T4 | (all rows VALID) lock the data source, write the `LaborSnapshot` + its `LaborEntry` rows (or reuse an identical existing snapshot), mark rows IMPORTED, job SUCCEEDED | commit, or rollback + a separate FAILED-marking transaction |

The CSV/XLSX readers, the header/date/number helpers and the tenant/data-source validation
pattern are the Gate 2 (`app.modules.bookings.parsers`, `app.modules.bookings.mapping`) readers,
reused as they are: labor ingestion adds no third reader.

## Why no employee identity

The canonical model is `DATE + ROLE/CATEGORY + HOURS + OPTIONAL COST`, never a person. An
`employee_name`, `email`, `phone`, `tax_code`, `address` or medical/leave note that a source file
carries is dropped at the mapping boundary: only columns explicitly mapped to a canonical field
are ever read from a row (`extract()`), so an unmapped column never reaches a `Cell`, let alone
staging, a log line or an error message. `role_raw` is a free-text SHIFT label (e.g.
"Reception AM"), never a person's name, and V1 does not even require it when `labor_category` is
explicit in the source. This is deliberate and tested (`test_labor_ingestion_data_minimization.py`):
it keeps NINFA out of employee-level HR data entirely, in the codebase and not just in the UI.

## Canonical tables (migration `0008_labor_ingestion`)

* **`labor_snapshots`** — what NINFA knew of a data source's staffing plan/actuals on ONE local
  date. Immutable (a trigger refuses UPDATE, `labor_forbid_update()`). Identity:
  `(workspace_id, data_source_id, snapshot_local_date)`. `snapshot_local_date` is always given
  explicitly by the caller — never `date.today()`, never a file's mtime.
* **`labor_entries`** — one canonical row: `work_date`, `role_raw`/`role_normalized`,
  `labor_category`, `planned_minutes`/`actual_minutes` (at least one required, both integers, never
  substituted for each other), `planned_cost`/`actual_cost`/`currency` (optional; a cost requires a
  currency), `classification_method`/`classification_confidence`. Immutable, same trigger.
* **`labor_mapping_profiles`** — the confirmed reading of one LABOR data source's files
  (`column_mapping`, `role_mapping`, `format_options`, `header_signature`). Mutable (configuration
  evolves); one per data source.
* **`labor_import_rows`** — data-minimised staging: `mapped_payload` holds only the values of
  mapped canonical fields, as text. `validation_status` is `VALID | INVALID | IMPORTED`.

Tenant integrity follows ADR 0006: every composite foreign key carries `workspace_id`, all
`ondelete="RESTRICT"` (see the migration's own docstring for the exact chain).

## Minutes, not float hours

`hours_to_minutes()` converts `Decimal` hours to an integer number of minutes by exact
multiplication (`hours * 60`). A value that is not a whole number of minutes is **rejected**
(`LABOR_FRACTIONAL_MINUTES`), never rounded: `7.5h -> 450`, `8.25h -> 495`, `7.501h -> REJECT`.

## Classification (`labor-classification-v1`)

Exactly the Gate 6 priority ladder (`app.modules.invoices.classification`), mirrored for roles:

1. **`EXPLICIT_SOURCE` (confidence 100)** — the source states `labor_category` and the value
   resolves to one of the eight canonical categories (`resolve_labor_category`, an exact
   case/spacing/punctuation-insensitive match; never a fuzzy or partial match).
2. **`ROLE_MAPPING` (95)** — the role matches an entry of the `LaborMappingProfile`'s
   `role_mapping` (a label saved once, reused on every later import of that data source).
3. **`DETERMINISTIC_RULE` (80)** — the normalised role matches the phrases of EXACTLY one of the
   small dictionaries in `app.modules.labor.classification.RULES` (housekeeping, front office,
   food & beverage, kitchen, maintenance, spa/wellness, management).
4. **`UNCLASSIFIED` -> `OTHER` (0)** — no role given, or the role's phrases match two or more
   categories (ambiguous: better not to classify than to classify wrongly), or nothing matches.

The eight canonical categories are `HOUSEKEEPING, FRONT_OFFICE, FOOD_BEVERAGE, KITCHEN,
MAINTENANCE, MANAGEMENT, SPA_WELLNESS, OTHER` — `VARCHAR` guarded by a named `CHECK`, never a
PostgreSQL `ENUM`, so the list changes with an ordinary migration.

## Idempotency and the source fingerprint

`snapshot_fingerprint()` hashes the SHA-256 of the canonical JSON of `{snapshot_local_date,
property_id, data_source_id, entries}`, where `entries` is every canonical entry's payload
(work date, normalised role, category, minutes, cost, currency, classification provenance —
**never** the file name, the import job id, `created_at` or a row number), sorted by their own
canonical JSON text so the fingerprint never depends on the input row order. Same snapshot date +
same fingerprint: a no-op that reuses the existing `LaborSnapshot` (`snapshot_reused=True`, zero
new entries). Same snapshot date + a different fingerprint: `LABOR_SNAPSHOT_CONFLICT` — a revision
of the plan must arrive as a NEW snapshot date, never an edit of an existing one.

## Atomicity

If even one staged row is `INVALID`, the whole job is `FAILED`: zero `LaborSnapshot`, zero
`LaborEntry`, staging rows remain for diagnostics. If the canonical write itself fails (a database
constraint), the batch is rolled back and the job is marked `FAILED` in a separate transaction, so
an unexpected exception never leaves a job `RUNNING`.

## Error codes

Job-level: `LABOR_INVALID_DATA_SOURCE`, `LABOR_UNSUPPORTED_FILE_TYPE`, `LABOR_UNREADABLE_FILE`,
`LABOR_EMPTY_FILE`, `LABOR_FILE_LIMIT_EXCEEDED`, `LABOR_DUPLICATE_HEADER`, `LABOR_MAPPING_REQUIRED`,
`LABOR_INVALID_MAPPING`, `LABOR_SOURCE_SCHEMA_CHANGED`, `LABOR_AMBIGUOUS_DATE_FORMAT`,
`LABOR_AMBIGUOUS_NUMBER_FORMAT`, `LABOR_SNAPSHOT_DATE_REQUIRED`, `LABOR_SNAPSHOT_CONFLICT`,
`LABOR_VALIDATION_FAILED`, `LABOR_CANONICALIZATION_FAILED`, `LABOR_INTERNAL_ERROR`. Row-level (also
used as job-level summary keys): `LABOR_REQUIRED_VALUE_MISSING`, `LABOR_INVALID_DATE`,
`LABOR_INVALID_NUMBER`, `LABOR_NEGATIVE_VALUE`, `LABOR_FRACTIONAL_MINUTES`, `LABOR_HOURS_MISSING`,
`LABOR_CURRENCY_REQUIRED`, `LABOR_INVALID_CURRENCY`, `LABOR_UNKNOWN_CATEGORY`,
`LABOR_VALUE_TOO_LONG`.

## Limitations (intentional)

* No employee identity, no shift id, no attendance/absence system: V1 reasons on aggregate minutes.
* No payroll, no gross-to-net, no contributions, no TFR: costs are a plain optional amount, never a
  computed wage.
* No PDF, no OCR, no HR API, no calendar scraping: CSV and XLSX only, the same two formats every
  other gate supports.
* A local date format that is ambiguous (`01/02/2026`) is rejected until the mapping states the
  pattern explicitly — never guessed.

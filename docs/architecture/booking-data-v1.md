# NINFA — Booking data v1 (Gate 2)

How a customer's booking file becomes canonical bookings: the model, the mapping memory, the
import pipeline and the guarantees around it. **No metrics, snapshots, occupancy, pickup,
forecasting or decisions are computed here**: those start in later gates.

Guiding principle: **the customer does not edit their Excel for NINFA**. NINFA reads the file as
it is, once, with a mapping the customer confirms; it never invents data it does not have.

Migration `0004_booking_ingestion`. Code: `services/api/app/modules/bookings/`. Entry point:
`BookingImportService` (`service.py`), framework-free and testable directly. No public API exists
yet (authentication is a later gate); a future worker or authenticated endpoint calls the service.

## Pipeline

```
FILE ─► FORMAT DETECTION ─► HEADER READ ─► MAPPING PROFILE ─► MAPPED VALUES ONLY
     ─► TYPE NORMALISATION ─► ROW VALIDATION ─► STAGING ─► ALL-ROWS VALIDATION
     ─► ATOMIC CANONICALISATION ─► BOOKING UPSERT ─► IMPORT JOB RESULT
```

Two steps happen *before* an import and never write bookings:

- `suggest_mapping(file)` proposes a mapping (deterministic, read-only, nothing is saved).
- `save_mapping(...)` stores the customer-confirmed mapping (the "mapping memory") and the header
  signature of the file it was confirmed on.

An import without a confirmed mapping fails with `BOOKING_MAPPING_REQUIRED`: a suggestion is
never applied on its own, however confident.

## Canonical booking

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | UUID v4 | NINFA's own id, unrelated to the PMS id |
| `workspace_id`, `property_id`, `data_source_id` | UUID | tenant scope; see "Tenant integrity" |
| `source_record_id` | text ≤ 255, required | the booking's id in the source system |
| `booked_at` | `timestamptz` (UTC), required | when the booking was created; needed for pickup later |
| `check_in`, `check_out` | `date` | `check_out > check_in` |
| `status` | text + CHECK | `CONFIRMED CANCELLED NO_SHOW CHECKED_IN CHECKED_OUT` |
| `rooms` | int > 0 | |
| `guests` | int > 0, nullable | |
| `room_revenue` | `NUMERIC(12,2)` ≥ 0 | in the **property's currency**; no FX in V1 |
| `total_revenue` | `NUMERIC(12,2)` ≥ 0, nullable | deliberately *not* required to be ≥ `room_revenue`: PMS differ on taxes/extras |
| `channel_id` | UUID | a `BookingChannel` of the same property |
| `commission_amount` | `NUMERIC(12,2)` ≥ 0, nullable | |
| `commission_rate` | `NUMERIC(7,4)`, 0..100, nullable | a percentage |
| `cancelled_at` | `timestamptz`, nullable | only when status is `CANCELLED`; a cancelled booking may have none |
| `room_type`, `rate_plan` | text, nullable | |
| `source_fingerprint` | 64 hex | SHA-256 of the business content; see Idempotency |
| `first_import_job_id` | UUID | immutable: the job that introduced the record |
| `last_import_job_id` | UUID | the last job that created **or changed** it |

**Identity.** `UNIQUE (workspace_id, data_source_id, source_record_id)`. `source_record_id` is
mandatory: NINFA never derives an id from guest name + dates + amount. A file without a usable
source id cannot be imported (the mapping requires the column, a blank cell invalidates its row).
There is no probabilistic de-duplication in V1 (ADR 0008).

The identity columns (`id`, `workspace_id`, `property_id`, `data_source_id`, `source_record_id`,
`first_import_job_id`, `created_at`) are immutable: a database trigger refuses to change them.

**Money** is `Decimal` end to end, never float. Amounts have at most two decimals (rates four): a
value with more is **rejected**, never rounded. Excel float cells are accepted only when exact to
the cent within float noise (0.1+0.2 → 0.30; 1.234 is refused). Range: 0 .. 9,999,999,999.99.

## Channels

`BookingChannel` is per **property** (the same "Booking.com" of two properties has different
contracts and commissions, so they are two rows). Unique on `(workspace, property, normalized_name)`.

- **Normalisation** (`normalize_channel_name`): accents, case, punctuation and spacing are ignored,
  words/digits/other scripts are kept, `&` becomes "and": `Booking.com`, `BOOKING.COM`,
  `booking com`, ` Booking . com ` → `booking com`. `Booking.com B.V.` is a different channel.
- A channel that already exists is **reused untouched**; a mapping profile never reclassifies it.
- A new channel is `OTHER` + `is_verified=false`, unless: the mapping profile gives its type
  explicitly (then `is_verified=true`: the customer decided), or its name is one of a tiny,
  tested built-in list (`booking com`, `expedia`, `airbnb` → OTA; `direct`, `diretto` → DIRECT),
  which is a *hint* and stays unverified. Nothing is classified because it "looks like a portal".
- The profile's `channel_mapping` can also merge labels (`BKG` → `Booking.com`).

## Mapping profile (mapping memory)

One current profile per data source (`UNIQUE (workspace, data_source)`), holding four JSON
documents and the header signature. It never holds file content.

- `column_mapping`: canonical field → `{"column": "<source header>"}` or `{"constant": <value>}`.
  Required fields: `source_record_id booked_at check_in check_out status rooms room_revenue
  channel`. Optional: `guests total_revenue commission_amount commission_rate cancelled_at
  room_type rate_plan`. **Constants are allowed only for `rooms`, `status`, `channel`.**
- `status_mapping`: source label → canonical status; overrides the built-in synonyms.
- `channel_mapping`: source label → `{name?, channel_type?}` (see Channels).
- `format_options`: `sheet_name`, `delimiter`, `encoding`, `date_formats` (per date field),
  `decimal_separator`, `thousands_separator`. A small closed set, validated on save.

**Header signature** = SHA-256 of the sorted set of normalised header names of the file the mapping
was confirmed on. On import, the mapping is reused when every *mapped* column is still present
(extra unrelated columns are fine: PMS exports grow). If a mapped column is missing (renamed or
removed) the old mapping is **not** applied: the job fails with `BOOKING_SOURCE_SCHEMA_CHANGED`
and the customer must re-confirm. A missing configured sheet is also a schema change.

**Suggestions** (`suggestions.py`): a table of known Italian/English header aliases, compared after
`normalize_key` (so `Check-in`, `CHECK IN`, `check_in` match). Exact alias → `HIGH / KNOWN_ALIAS`;
similar (difflib ratio ≥ 0.88 → `MEDIUM`, ≥ 0.78 → `LOW`) → `FUZZY_MATCH`; else `NONE`. Each header
is proposed for at most one field; ties are resolved by canonical field order, so results are
deterministic. No AI, no learning. A suggestion also carries date-order *evidence* (see below).

## Formats

| | Supported | Not supported |
| - | --------- | ------------- |
| CSV | UTF-8 (BOM removed), Windows-1252 fallback, comma / semicolon / tab (detected from the header line; `sep=;` honoured), quoted delimiters and multi-line fields | UTF-16 (refused, not guessed) |
| XLSX | openpyxl, read-only streaming, native dates/numbers | `.xls`, `.xlsm`, `.ods` |

Header rules: duplicate headers (after normalisation) are rejected (`BOOKING_DUPLICATE_HEADER`);
blank header cells are ignored; completely empty rows are skipped (row numbers still count them, so
a reported row number is the one the customer sees in Excel). A workbook with several visible
sheets that contain data is never guessed: choose `sheet_name` in the profile
(`BOOKING_MAPPING_REQUIRED`, reason `sheet_selection_required`). Limits: 25 MiB, 100,000 rows,
200 columns (over the limit = refused, never truncated).

### Dates and time zones

- Unambiguous ISO forms (`2026-03-10`, `2026-03-10 14:30`, `…T14:30:00+02:00`, `…Z`, and the
  year-first `2026/03/10`) are read as they are. Native Excel dates need nothing.
- Day/month-first text such as `01/02/2026` is **never guessed**. If a mapped date column has such
  values and no `date_formats` entry, the job fails with `BOOKING_AMBIGUOUS_DATE_FORMAT` (listing
  the fields). The suggestion reports evidence (`DMY` if some value has a first part above 12,
  `MDY`, `AMBIGUOUS` if all fit both, `CONFLICT`) but importing never relies on it: the customer
  confirms an explicit pattern (`%d/%m/%Y`, `%d/%m/%Y %H:%M`; only numeric directives, four-digit
  year). Configuration is stored, so the result never varies with the file's content.
- `booked_at` / `cancelled_at` (they denote an **instant**, which pickup and booking curves will
  rely on, so NINFA never invents one):
  1. a value with an explicit offset/time zone (`…+02:00`, `…Z`, an aware Excel datetime) is
     accepted and converted to UTC;
  2. a naive value (text or Excel) is read **in the property's time zone** and converted to UTC,
     but only if that local time identifies exactly one instant; a date without time means local
     midnight, under the same rule;
  3. a naive local time that **does not exist** (skipped by a daylight-saving change, e.g.
     `2026-03-29 02:30` in `Europe/Rome`) is rejected: `BOOKING_NONEXISTENT_LOCAL_TIME`;
  4. a naive local time that happens **twice** (the repeated hour, e.g. `2026-10-25 02:30` in
     `Europe/Rome`) is rejected: `BOOKING_AMBIGUOUS_LOCAL_TIME`.

  Neither candidate reading is ever chosen automatically (not the earlier or the later offset,
  not the first or second occurrence). These are row-level errors like any other: the row is
  `INVALID`, the job `FAILED` with `BOOKING_VALIDATION_FAILED`, nothing is imported, and the
  diagnostics name the field and the code, never the value. The remedy lies in the source: an
  export that includes the UTC offset (a value with an explicit offset is always accepted, even
  inside the skipped or repeated hour). The rule follows the property's time zone, works for
  changes of any size (30-minute shifts included) and never affects zones without daylight
  saving. A future version may let the mapping profile choose an explicit policy; V1 is
  deliberately conservative.
- `check_in` / `check_out` are calendar dates in the property's time zone (no conversion for naive
  values).

### Numbers

Without settings only plain `1234` / `1234.56` is read. A column with a comma, or with several
dots (`1.234,56`, `1,5`), fails with `BOOKING_AMBIGUOUS_NUMBER_FORMAT` until the profile sets
`decimal_separator` (and `thousands_separator`). With them, `1,234.56`, `1.234,56`, `1234,56` and
`1 234,56` are read exactly; wrong digit grouping, currency symbols and letters are invalid values.

## Staging (`booking_import_rows`)

One row per source row, kept whatever the outcome:

- `mapped_payload`: **only** the values of explicitly mapped columns, keyed by canonical field (as
  text). Never the source row.
- `normalized_payload`: the canonical booking as JSON (money as strings), `NULL` for invalid rows.
- `validation_status`: `VALID` (passed row validation), `INVALID` (with `validation_errors`),
  `IMPORTED` (its booking was written). No further state is needed: rows of a failed job simply stay
  `VALID`/`INVALID`.
- `validation_errors`: `[{"field", "code", "detail"?, "value"?}]`. Codes are stable
  (`BOOKING_INVALID_DATE`, `BOOKING_NEGATIVE_VALUE`, …); a `value` appears only for an unknown
  *status* label, the one categorical value the customer needs in order to fix the mapping.

Canonicalisation reads the `VALID` staged rows back from the database, so a worker can resume from
staging.

## Data minimisation

The mapping decides what is read. `_extract` keeps the mapped cells of each row and drops the rest
immediately: guest names, e-mails, phones, notes, documents and any other unmapped column never
reach staging, logs, error messages, job messages or the canonical tables. Logs carry
`workspace_id`, `property_id`, `data_source_id`, `import_job_id`, `import_file_id`, status and
counts, never a row value. Database error diagnostics are reduced to the constraint *name*. Tests
scan every table of the database for the file's guest values, and check a control case that mapping
a personal column on purpose does store it (so the scan is meaningful).

## Import job lifecycle and atomicity

The service owns the transaction boundaries (no unit-of-work framework):

| Step | What | Commit |
| ---- | ---- | ------ |
| T1 | create `ImportJob` (PENDING) and `ImportFile` (name, size, sha256; no storage), start it (RUNNING) | yes |
| T2 | parse → map → normalise → validate → **stage every row** | yes |
| T3 | any invalid row: job `FAILED` (`BOOKING_VALIDATION_FAILED`); **no booking is written** | yes |
| T4 | all valid: advisory lock, resolve channels, upsert bookings, rows → `IMPORTED`, job `SUCCEEDED` | one transaction |

If T4 fails for any reason it is rolled back **entirely** (bookings *and* the channels created in
it), then the job is marked `FAILED` (`BOOKING_CANONICALIZATION_FAILED`) in its own transaction, so
the outcome and the staging diagnostics survive the rollback. A crash anywhere else also ends as a
`FAILED` job, never a job stuck `RUNNING`. Only a data source that cannot be used at all
(`BOOKING_INVALID_DATA_SOURCE`) raises before creating a job.

T4 takes `pg_advisory_xact_lock` on the data source, so two imports of the same source serialise
and the second sees the first one's bookings.

## Idempotency

| Case | Result |
| ---- | ------ |
| same file imported again | no duplicates; every booking `unchanged`; nothing written to `bookings` |
| same `source_record_id`, same fingerprint | true no-op: not even `updated_at`/`last_import_job_id` change |
| same `source_record_id`, changed content | the **same** booking is updated; `first_import_job_id` kept, `last_import_job_id` set |
| same `source_record_id` twice in one file | rejected (`BOOKING_DUPLICATE_SOURCE_ID`), both rows; no "last row wins" |

The fingerprint is the SHA-256 of a canonical JSON document (sorted keys, compact) of the business
fields (`v`, source id, UTC `booked_at`, dates, status, rooms, guests, amounts, channel by
normalised name, cancellation, room type, rate plan). It excludes job ids and timestamps, and it is
insensitive to cosmetics (`450` vs `450.00`, `BOOKING.COM` vs `Booking.com`, `+01:00` vs UTC).
A test pins the document, so changing the algorithm is a deliberate act (bump `v`).

**File-level duplicates.** `ImportFile.sha256` is recorded and never unique. When a data source
imports content it already imported successfully, the import **runs again** (idempotently) and the
result reports `duplicate_of_import_file_id`. Simplest and most robust: no special path, and it
self-heals after a mapping change. The hash is compared only inside the same data source, never
across data sources, properties or workspaces.

## Tenant integrity (all foreign keys `RESTRICT`)

```
bookings (workspace, property, data_source)                     → data_sources
bookings (workspace, property, channel)                         → booking_channels (workspace, property, id)
bookings (workspace, property, data_source, first/last job)     → import_jobs (workspace, property, data_source, id)
booking_channels (workspace, property)                          → properties
booking_mapping_profiles (workspace, property, data_source)     → data_sources
booking_import_rows (workspace, import_job, import_file)        → import_files (workspace, import_job, id)
```

A booking, its channel and its jobs therefore must share workspace **and** property; its jobs must
belong to its own data source; a staged row's file must belong to its job. `import_jobs` and
`import_files` gained one extra unique key each (foreign-key targets). The booking's property is
protected transitively (through its data source and channel), not by a fourth key. Two rules stay in
the application because SQL cannot see them: the data source must be `BOOKINGS` + `FILE_UPLOAD`
and active, and its property not archived (`BOOKING_INVALID_DATA_SOURCE`, indistinguishable for
unknown and foreign ids). Repositories take a `TenantContext` and filter every query by workspace.

## Error codes

Stable, machine-readable (`BookingErrorCode`); callers must never branch on the message.

| Code | Level | Meaning |
| ---- | ----- | ------- |
| `BOOKING_INVALID_DATA_SOURCE` | raised | not a usable BOOKINGS/FILE_UPLOAD source of this workspace/property |
| `BOOKING_UNSUPPORTED_FILE_TYPE` / `BOOKING_UNREADABLE_FILE` / `BOOKING_EMPTY_FILE` / `BOOKING_FILE_LIMIT_EXCEEDED` | job | file problems |
| `BOOKING_DUPLICATE_HEADER` | job | duplicate column headers |
| `BOOKING_MAPPING_REQUIRED` | job | no confirmed mapping, or a sheet must be chosen |
| `BOOKING_INVALID_MAPPING` | raised | the mapping is incomplete/unsafe/refers to missing columns |
| `BOOKING_SOURCE_SCHEMA_CHANGED` | job | a mapped column (or the configured sheet) is gone |
| `BOOKING_AMBIGUOUS_DATE_FORMAT` / `BOOKING_AMBIGUOUS_NUMBER_FORMAT` | job | a format must be configured |
| `BOOKING_VALIDATION_FAILED` | job | at least one row is invalid (see the staged rows and `row_error_summary`) |
| `BOOKING_CANONICALIZATION_FAILED` | job | the database rejected the batch; rolled back |
| `BOOKING_INTERNAL_ERROR` | job | unexpected failure |
| row codes: `BOOKING_DUPLICATE_SOURCE_ID`, `_UNKNOWN_STATUS`, `_REQUIRED_VALUE_MISSING`, `_INVALID_DATE`, `_INVALID_DATETIME`, `_INVALID_NUMBER`, `_INVALID_INTEGER`, `_AMOUNT_PRECISION`, `_NONEXISTENT_LOCAL_TIME`, `_AMBIGUOUS_LOCAL_TIME`, `_NEGATIVE_VALUE`, `_NOT_POSITIVE`, `_OUT_OF_RANGE`, `_VALUE_TOO_LONG`, `_CHECK_OUT_NOT_AFTER_CHECK_IN`, `_CANCELLED_AT_WITHOUT_CANCELLED_STATUS` | row | in `validation_errors` |

## Status values

Built-in synonyms (case, accents and punctuation ignored): `confirmed confermato confermata`;
`cancelled canceled annullato annullata cancellato cancellata`; `no show`/`no-show`;
`checked in`/`checked-in`; `checked out`/`checked-out`. The profile's `status_mapping` overrides
them. Anything else is reported as `BOOKING_UNKNOWN_STATUS` and the row is invalid: it is **never**
defaulted to `CONFIRMED`.

## Using the service

```python
service = BookingImportService(session, TenantContext(workspace_id))
suggestion = service.suggest_mapping(data_source_id, filename="export.xlsx", content=data)
# ... the customer confirms (and picks date/number formats) ...
service.save_mapping(data_source_id, headers=suggestion.headers,
                     column_mapping={...}, format_options={...})
result = service.import_file(data_source_id, filename="export.xlsx", content=data)
if not result.succeeded: ...   # branch on result.error_code
```

Pass a session with no uncommitted work: the service commits (and may roll back) it.

## Not in this gate

Booking snapshots, daily metrics, occupancy/ADR/RevPAR, pickup, booking curves, forecasting,
Expected/Detection/Impact/Priority/Recommendation engines, decisions; a public API and
authentication; the asynchronous worker job (no persistent file storage exists yet: the service takes
the bytes, so a worker can call it once uploads do); costs and labor ingestion; FX conversion;
`.xls`/`.xlsm`/`.ods`; probabilistic booking de-duplication; AI of any kind.

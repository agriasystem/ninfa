# 0008 — Booking ingestion: mandatory source id, atomic import, minimal staging

**Status:** accepted (Gate 2)

## Context
Booking files come from many PMS and spreadsheets, with different headers, dates, decimals and
statuses, and they contain personal data NINFA does not need (guest names, e-mails, phones,
documents). Customers re-export overlapping periods all the time, so imports must be repeatable, and
a wrong booking silently entering the data is worse than a rejected file: everything downstream
(pickup, expected values, decisions) is built on it. The customer must not have to edit their file.

## Decision
1. **`source_record_id` is mandatory** and, with the data source, is the identity of a booking
   (`UNIQUE (workspace, data_source, source_record_id)`). It is the basis of idempotency, updates,
   cancellations and reconciliation. If a file has no usable source id, the import stops; NINFA never
   synthesises one.
2. **No probabilistic de-duplication.** Guessing that two rows are "the same booking" from name,
   dates and amount would merge distinct bookings and hide real duplicates. Ambiguity is rejected:
   the same source id twice in one file rejects both rows (no "last row wins").
3. **Atomic import.** Every row is validated and staged first; if any is invalid, no booking of that
   job is written or updated. If all are valid, canonicalisation is one transaction. The job outcome
   and the staging are committed separately, so a rolled-back batch still leaves a `FAILED` job and
   its diagnostics. Partial imports were rejected: they leave the data in a state that is hard to
   explain or repair.
4. **Idempotency by fingerprint.** SHA-256 of the canonical business content decides between no-op,
   update and create. `first_import_job_id` is immutable (enforced by a trigger, with the other
   identity columns); `last_import_job_id` marks the last real change. File-level duplicates are not
   short-circuited: the import simply runs again and is a no-op record by record.
5. **Staging keeps mapped columns only.** The mapping decides what is read; everything else is
   dropped right after reading. Staging, logs, errors and job messages hold mapped values, field
   names, codes and counts; database errors are reduced to constraint names. Personal data that NINFA
   does not need is therefore never stored, by construction rather than by later cleanup.
6. **Nothing is inferred while importing.** Dates like `01/02/2026`, numbers like `1,234`, sheets of
   a workbook, statuses and channel types are read by explicit rules or explicit configuration, or
   reported. Suggestions (deterministic aliases and fuzzy similarity) only *propose*; a mapping is
   valid only once the customer confirms it, and it is not applied to a file whose mapped columns
   have changed.
7. **No pandas / numpy / polars.** Files are read with the standard `csv` module and `openpyxl`
   (read-only, streaming), rows are processed in plain Python and money is `Decimal`. A dataframe
   library would add heavy native dependencies, float-by-default numerics and implicit type
   inference, all of which work against points 5 and 6, for a job that is parsing a few thousand rows.
   `openpyxl` is the only dependency added by this gate.
8. **Tenant integrity as in ADR 0006**: composite foreign keys carrying workspace and property from
   bookings to data sources, channels and jobs, and from staging rows to files and jobs.
9. **The import is an application service**, not an endpoint or a worker job: it depends on neither
   FastAPI nor the queue, and takes the file as bytes, so authentication, upload/storage and the
   asynchronous job can be added around it later without changing it.

## Consequences
- A customer with a messy file gets a precise, coded reason and fixes the mapping once; the mapping
  is remembered per data source. Files with a real data problem are refused as a whole, which can feel
  strict but keeps the canonical data trustworthy.
- A PMS export that lacks a stable booking id cannot be used until the customer maps one; this is
  intentional.
- Amounts with more than two decimals, ambiguous formats and unknown statuses need one-off
  configuration.
- Re-imports cost parsing time (not writes). Staging rows accumulate per import: a retention policy
  is a later concern.
- Concurrent imports of one data source are serialised (advisory lock) instead of racing.
- FX, costs/labor files, `.xls`/`.xlsm`/`.ods`, background processing and object storage are
  deferred to their own gates.

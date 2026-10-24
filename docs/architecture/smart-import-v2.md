# NINFA — Smart Import V2 (Struttura > Fonti dati: "use the file the hotel already has")

Fonti dati V1 let a hotel import a file, but only in NINFA's own column names. That is too technical for the target:
the hotelier has a PMS export or a staff spreadsheet and should not rename its columns. **Smart Import V2** reads that
file, proposes what each column means, lets the person confirm or correct it, tries the WHOLE file before importing,
imports, remembers the matching and recognises the same layout next time.

**No migration. No new dependency. No AI, no network, no cost**: everything is deterministic and runs on what the import
services already had.

```
CSV / Excel of the hotel -> NINFA reads headers and values -> proposes the meaning of each column
   -> the person confirms / corrects -> the backend checks it -> the whole file is tried (nothing written)
   -> import -> the matching is remembered -> next file of the same layout: recognised, preview, import
```

## What already existed (audit) and what is new

| Piece | Where | State |
| --- | --- | --- |
| CSV + XLSX reader (BOM, `;` `,` tab, cp1252, `sep=`, sheets, header row, duplicate headers, 25 MB / 100 000 rows / 200 columns, zip-bomb guard, `data_only` so formulas are never evaluated) | `bookings/parsers` (used by labor and invoices too) | reused as it is |
| Mapping model with required fields, fixed values, date patterns, decimal/thousands separators | `bookings/mapping.py`, `labor/mapping.py` | reused; one optional field added (`schema_version`) |
| Header-based suggestion engine with confidence | `bookings/suggestions.py` | **moved to a shared, generic module** (`ingestion/suggestions.py`); the booking behaviour is unchanged (its tests pass untouched) |
| Suggestions for labor | — | **new** (`labor/suggestions.py`), same engine, its own known names |
| Saved matching ("mapping memory") per data source, unique per (workspace, source), composite FK to workspace/property/source, header signature | tables `booking_mapping_profiles`, `labor_mapping_profiles` | reused: **this is the persistence, so no migration** |
| All-or-nothing row validation | `BookingImportService._validate`, `LaborImportService` | reused; a pure `dry_run` added next to `import_file` |
| Costs from a structured file | `invoices/mapping.py` + service | exists at service level, **not offered** (see Scope) |
| HTTP, UI, recognition of a saved layout, versioning, dry run, "forget" | — | **new** |

## Backend

`app/modules/data_sources/` (the API layer is `app/api/v1/sources/`):

- `column_profile.py` — read-only evidence from the first 2 000 rows: a few example values per column, what the dates prove
  about day/month order (`detect_date_order`), whether numbers use `,` or `.` (`1.234` / `1,234` are *ambiguous* on purpose),
  the date pattern a column really uses (separator, time) - or `None` if it writes dates in more than one way.
- `domain_adapters.py` — the two file domains (bookings, labor) behind one interface: their fields, requirement groups,
  suggestions, saved profile, `dry_run`. Costs are deliberately absent.
- `smart_import.py` — `SmartImportService`: `inspect` (what NINFA finds in a file), `check` (is a decision enough? the
  backend's own rules, no file needed), `resolve` (a decision, read against THIS file, becomes the validated mapping an import
  runs with; reports what cannot be decided), `dry_run`, saved configuration (`configuration_of`, `forget`, `remember`).
- `DataSourcesService` gained `inspect_file`, `check_mapping`, `dry_run`, `saved_configuration`, `forget_configuration` and
  `import_file(..., mapped=MappedImport(mapping, save_configuration))`.
- The import services gained `mapping_override` on `import_file` (the mapping the caller has just built from this very file,
  **not stored by the import**) and a side-effect-free `dry_run`.

| Route (under `/api/v1/properties/{property_id}/data-sources`) | What it does | Writes |
| --- | --- | --- |
| `POST /import-inspection?domain=&filename=&sheet_name=` (raw body) | reads the file: columns, examples, proposal with a level, what the values prove, fields and requirement groups, whether the file already is in NINFA's own format, whether a saved configuration applies | nothing |
| `POST /import-mapping-check` (JSON, no file) | the backend answers "is this matching enough?": `valid`, `missing` (groups "at least one of"), `problems` | nothing |
| `POST /import-validation` (JSON, file as base64) | judges **every row** with this matching (or the saved one when `mapping` is null), exactly as the import will: counts, the first valid rows in NINFA's form, row problems by code, the first invalid rows, how dates/numbers were read, or "NEEDS_CHOICE" | nothing |
| `POST /imports/mapped` (JSON, file as base64) | imports with the matching; on success remembers it (`save_configuration`) | source + job + data + configuration, **only if the import succeeds** |
| `GET /{id}/import-configuration` | how this source's files are read, as saved | — |
| `DELETE /{id}/import-configuration` | forgets it; the source and every imported row stay | the profile only |

The first routes of V1 (`/import-preview`, `/imports` raw) are unchanged and still serve invoices (XML) and the canonical
convention. The file travels as base64 in a JSON body for the matched routes (the matching is structured data; the API takes
no multipart and CORS allows only `Content-Type`/`Authorization`); the body is capped while it is read (10 MB file -> ~13.4 MB).
A file is never stored by the API.

### Rules the backend owns (the page owns none)

- **What is required** is the mapping model's own rule, exposed as `requirement_groups` and answered per decision by
  `import-mapping-check`. Bookings: eight single required fields. Labor: the date; *at least one of* planned/actual hours;
  *at least one of* role/category. A fixed value ("same on every row") is accepted only where the model allows it
  (`CONSTANT_FIELDS`: bookings status/rooms/channel, labor category/currency).
- **What `role` really is** (audited against the canonical staff model): `labor_category` is the department / operational
  area and the ONLY label the Decision Engine reads (`intelligence/labor`, `data_overview`); `role_raw` / `role_normalized` are
  the *free text the file used for the shift* ("Reception", "Cuoco", "Turno A"), stored as written, never a person's name, and
  read by nothing downstream - they exist to work the department out. So a hotel's department-or-job column is mapped to
  `role` and shown to the person as **"Reparto o mansione"** (not "ruolo": it is not a professional role); the deterministic
  classifier derives the department. The *category* field ("Reparto (nome standard di NINFA)") is only for a column that
  already holds NINFA's own category names. What cannot be classified stays `OTHER` (never invalid) - and `OTHER` is not
  actionable and counts against the 70 % classification coverage the staffing analysis needs, so the dry run **counts those
  rows over the whole file** (`rows_unclassified`) and the preview says so before the import ("verranno importate come
  «Altro»"). Teaching NINFA what a label means (the profile already has a `role_mapping` document) is V2.1.
- **Planned and actual are different facts** (the staffing analysis reads PLANNED minutes), so a bare "Ore" / "Costo" is never
  suggested: only names that say which one they are.
- **NINFA keeps no employee identity and has no hourly rate**: a column of names ("Nome dipendente") and an hourly rate
  ("Costo orario", "Costo h") are shown but can only be **ignored** (the page locks them). Mapping an hourly rate into
  `planned_cost` would put a wrong number into the cost analysis.
- **Dates and numbers are never guessed.** If the values prove the order (25/10 cannot be month 25) it is applied; if they
  cannot, the person is asked once (day first / month first; comma / point as the decimal mark). A column that writes dates in
  more than one way is refused (`DATES_MIXED`).
- **All-or-nothing stays**: one invalid row means nothing is imported (the dry run says so and the import is not offered). There
  is no "import the valid rows" mode because the ingestion model does not have one.
- **Create-on-success holds for the new way in too.** A request that cannot work (unreadable file, matching not enough, a format
  still to choose, no usable saved configuration) is refused **before** a source is created or switched on; a matched import that
  fails leaves no new configuration and never spoils the one that was working; the lock of the first-import race covers it.

### The saved configuration (persistence)

One profile per data source, in the existing tables: the four JSON documents of the matching (columns/fixed values, value labels
such as statuses/channels/roles, how to read the file) plus the **header signature** (SHA-256 of the sorted, normalised
header set).

- **Recognition is by columns, never by file name**: a saved configuration applies to a file when every column it uses is
  there (an extra column is harmless); the signature says whether the header set is identical. `turni-settimana-43.csv` and
  `turni-settimana-44.csv` are the same layout.
- **Version**: `format_options.schema_version` (the version of NINFA's field set and rules the matching was confirmed
  against, `MAPPING_SCHEMA_VERSION = 1` per domain). A profile of another version is **never applied silently**
  (`NEEDS_REVIEW / VERSION_CHANGED`); a profile saved before versions existed (the canonical identity matching of V1) counts
  as version 1. A profile that no longer parses (a retired field) is `INVALID`.
- **Isolation**: every read/write goes through the repositories of the request's `TenantContext` and the property of the
  route; a source of another property or workspace answers the same 404 as one that does not exist. Tested for cross-property,
  cross-workspace and cross-domain.
- **Re-matching replaces** the profile but keeps the value labels the person already taught NINFA. A removed source keeps its
  configuration for when it is linked again (the same source is reactivated).
- It stores **only the matching**: no cell value, no example, no name of an ignored column.

### Security and limits

The reader's limits apply to every route (25 MB reader / 10 MB API, 100 000 rows, 200 columns, 250 MB unpacked); the JSON body,
the mapping (<= 200 columns, <= 200-char headers, <= 20 fixed values) and the base64 are bounded and validated strictly
(`extra="forbid"`). Encodings other than UTF-8/Windows-1252, NUL bytes (binary or UTF-16), a workbook named `.csv`, `.xls`/
`.xlsm`/`.ods` and PDFs are refused with one stable word. Cells are shown as plain text and never evaluated: a CSV cell
starting with `=`, `+`, `-`, `@` is text, and an Excel formula is read for its cached value only (an uncalculated one has none).
NINFA never writes a CSV or a spreadsheet back, so there is no formula-injection sink. A file name is only a label (base name,
255 chars, never a path).

## Frontend

`lib/sources/use-import-flow.ts` walks the steps; the screens are `struttura-import-mapping.tsx` ("Abbina le colonne"),
`struttura-import-preview.tsx` ("Anteprima importazione" / "Abbiamo riconosciuto il formato") and the manage dialog's
"Configurazione import". Invoices keep their own short XML path.

```
Collega fonte / Carica nuovo file -> Seleziona file -> NINFA legge il file
   -> formato riconosciuto ........ anteprima (impostazione salvata) -> Importa con questa configurazione   [Controlla colonne]
   -> file già nel formato NINFA .. anteprima -> Importa dati
   -> altrimenti ................. Abbina le colonne -> Continua -> (domande su date/numeri se servono) -> anteprima -> Importa dati
   -> importazione riuscita ...... "Configurazione salvata" (casella "Salva questa configurazione", attiva di default)
```

The page decides nothing about the data (pinned by `sources-guard.test.ts`): it names no field in its logic, never decides
that a matching is enough (the button waits for `check.valid`), offers the import only when the backend says every row can
be imported, and speaks the hotelier's words ("Abbina le colonne", "Ignora questa colonna", "Riconosciuto", "Da verificare",
"Salva questa configurazione"; never mapping, schema, parser, canonical, payload...). A level is shown only while the choice
still equals NINFA's proposal; no confidence number is ever shown.

## Tests

- Backend: `test_smart_import_columns.py` (suggestions, evidence, readers: delimiters, BOM, empty rows, Excel dates),
  `test_smart_import_api.py` (inspection, checking, dry run, request limits, 401/404), `test_smart_import_flow.py` (first
  import, recognition, versioning, re-matching, forgetting, isolation, create-on-success, formulas, file names),
  `test_data_sources_real_commits.py` (the first-import lock holds for matched imports too).
- Frontend: `struttura-import-flow.test.tsx` (67 tests of the experience, from the first screen to the result),
  `mapping-decision.test.ts`, `sample-format.test.ts`, the API client and the extended guards.

## Decisions to confirm

1. **Labor in the brief's example vs the model.** The brief maps "Nome" -> Dipendente and "Costo h" -> Costo orario. The labor
   model has **no employee and no hourly rate** by design (privacy; the staffing analysis reads planned hours per category).
   V2.0 does not invent them: both are shown and ignored. A file with only day, person, hours and rate therefore needs a team
   (a column, or "Reparto di tutte le righe"). Supporting an hourly rate (cost = hours x rate) would be new business logic.
2. **The version lives in the saved JSON** (`format_options.schema_version`), not in a column - this is what avoids a migration.
   A column (`schema_version`, plus a `name` and several profiles per source) is the V2.1 migration to approve.
3. **The profile has no user-chosen name.** The brief's "Turni personale" would need a column; V2.0 shows the matching itself
   ("Giorno -> Data...") in Gestisci. The card of a file source says **"Import file"** (it receives CSV and Excel over time, and the
   card only knows the method of the source, not the format of the last file); every place that offers the upload says
   "CSV o Excel (.xlsx)". Costs stay "Import fatture XML".
4. **Costs from CSV/Excel stay out.** The invoice service can read a structured file (line level, 20 fields), but a hotelier
   column matching for it is a V2.1 product decision.

## Scope

- **V2.0 (this PR)**: bookings and staff; CSV and Excel; suggestions (names, similarity, one value-based date hint); matching
  UI; backend-owned requirements and fixed values; date/number questions; whole-file dry run; saved configuration, recognition,
  versioning, manage/forget; isolation and limits.
- **V2.1**: status/channel/role *value* matching (including "this label is the Kitchen" for labels NINFA cannot classify); a name and several profiles per source and a `schema_version` column
  (migration); costs from CSV/Excel; an hourly rate or employee-level data if the product wants it; a "Formato riconosciuto"
  line on the card; row-level fixing instead of "fix the file".

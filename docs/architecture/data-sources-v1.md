# NINFA — Fonti dati V1 (Struttura > "4. Fonti dati": setting up and feeding a data source)

The "Fonti dati" block of `/struttura` used to be a static drawing. It is now a **real, truthful** way to say where NINFA's
data come from and to put a file in: the cards show what the backend says, "Collega fonte" / "Carica file" / "Gestisci" /
the "..." menu open working dialogs, and a file goes through the SAME import services the pilot CLI already used.
**No migration, no new dependency, no integration simulated.**

## Rule: the UI and the state tell the truth

NINFA has exactly **one kind of data source: a file** (`DataSource.source_type = FILE_UPLOAD`) of one of three domains.
There is **no automatic integration** with any PMS, Channel Manager, OTA, accounting or HR system, so:

- no card is ever "Connesso" on its own: `CONNECTED` exists in the contract for the day an integration is real, and **no
  code path produces it** (a test pins it); the response carries `automatic_integrations: []`;
- no vendor is ever named, in the code or in the copy; what does not exist is "Integrazioni automatiche — Prossimamente",
  shown, never clickable;
- no date is made up: "Ultimo aggiornamento" is the `finished_at` of the latest **SUCCEEDED** import of that exact
  source (`ImportJobRepository.latest_succeeded_for_data_source`, the same fact the Home and Dati already state). A source
  that never completed an import has none, and then **the card is not configured** (see the next section). The frontend
  invents **no age threshold** ("dati vecchi" is not a frontend judgement).

## Rule: a source exists only after a SUCCESSFUL import

A card says "Configurato" only once a file has really arrived. Opening a dialog, choosing "Importa file", choosing a file
and looking at its preview **write nothing**; the data source behind the card is created (or switched back on) only when
the user **confirms** the import, and only if that import **succeeds**:

| Moment | What the backend holds | The card |
| --- | --- | --- |
| open the dialog / choose a file / preview | nothing (preview is a pure read) | "Nessuna fonte collegata" / "Non configurato" |
| import confirmed, **fails** (invalid rows, missing columns, unreadable file, wrong type, network...) | nothing active: a source this very call switched on is switched **off** again (a new one is left inactive, a removed one stays removed); the attempt stays as a FAILED import job like every operational record | unchanged: "Non configurato" |
| import confirmed, **succeeds** | the source is **created** (first time) or **switched back on** (it was removed: its history stays attached) | "Import CSV" / "Configurato" / real "Ultimo aggiornamento" |
| a later import | the **same** active source is reused, never a second one | the update moves |

Safety nets: an unexpected exception during the import also switches off what that call switched on (after a rollback);
an *active* source somebody else set up is never switched off by a failing import; a property with **several** active
sources of a kind refuses the import (409 `SEVERAL_SOURCES`) instead of picking one; and a source that is active but has
**never delivered** (an operator created it and never fed it) is reported "Non configurato" by the backend, and the
frontend independently refuses to show a file source as configured without a real last update. The "Configurato · Mai
importato" state therefore **cannot appear**.

### Imports of the same data run one at a time (concurrency)

"Is there a source of this kind?" followed by "no, create one" is a check-then-act. Two *first* imports arriving together
(a double click, two tabs, two API workers) would both read "no source", both create one, and the property would answer
`SEVERAL_SOURCES` from then on. A second hazard sat behind the first: one import that fails switches off the source it
switched on, while another import that had found that source active was still filling it.

Both are removed by **serialising the whole import** per `(workspace, property, kind of data)`, with no schema change:

- `app.db.locks.hold_source_import_lock` takes a PostgreSQL **advisory transaction lock**
  (`pg_advisory_xact_lock(hashtextextended('source-import:<workspace>:<property>:<domain>', 0))`) on a **connection and
  transaction of its own** and keeps it until the import has finished — source created or reactivated, file imported,
  source switched off again if it failed. A lock on the request's own session would not do: the import services commit
  several times and a transaction-scoped lock is released by the first commit.
- It is PostgreSQL's lock, so it holds across every API worker and process (nothing is in-process, nothing is read from
  the page). It is still transaction-scoped: it dies with its transaction, or with its connection if the process dies —
  no lock can be leaked.
- The second import **waits** (`IMPORT_LOCK_WAIT_MS` = 30 s, enforced by `lock_timeout`, an import being seconds of
  work), then sees exactly what the first left behind: the active source (it imports into it), or the removed one (it
  reactivates it, history attached). After the wait it answers **409 `IMPORT_IN_PROGRESS`**, changes nothing and the page
  tells the user to wait and retry.
- Another **property**, another **kind of data** and another **workspace** use another key and never wait. The preview and
  the overview take no lock. Lock order is fixed (`source-import` → per-data-source → supplier registry), so the three
  can never deadlock.
- The unique constraint that would make this a database guarantee (`UNIQUE (workspace_id, property_id, domain) WHERE
  is_active`) needs a migration, and existing data could already violate it: it is **not** needed for correctness while
  every writer of an API source goes through this service, and is left as a possible hardening. The only other code that
  creates a source is the operator's `app.cli.pilot` provisioning command, run by hand once per pilot property; it does
  not take the lock and is not the path of this page.

Pinned with real commits and threads in `test_data_sources_real_commits.py` (two first imports → one source, both jobs on
it; the same setup *without* the lock → two sources, as a control; failing + succeeding in either order; a later import
reuses the source; other property / other kind not blocked; lock released after success, refusal and crash; bounded
wait → `IMPORT_IN_PROGRESS`).

## Audit: what already existed

| Area | Found |
| --- | --- |
| Persistence | `data_sources` (workspace, property, name, **domain** BOOKINGS / COSTS / LABOR, **source_type** FILE_UPLOAD, `is_active`), `import_jobs` (PENDING → RUNNING → SUCCEEDED / FAILED, `finished_at`), `import_files` (name, sha256). `DataSourceRepository.deactivate()` ("switched off, never deleted"). |
| Import services | `BookingImportService`, `LaborImportService`, `InvoiceImportService`: parsing, validation, idempotency (same file twice never doubles), all-or-nothing per file. **Reachable only from the pilot CLI** (`app.cli.imports`): there was no HTTP route for a file. |
| Format | ONE canonical CSV per domain (headers = the services' own field names, UTF-8, `,`, dates `YYYY-MM-DD`, decimals `.`) and FatturaPA XML for invoices (`docs/architecture/pilot-readiness-v1.md`, "Data intake"). |
| Mapping | The services contain a mapping-suggestion engine and saved mapping profiles, **not exposed anywhere** (no HTTP, no UI). The production convention is the canonical identity mapping. → follow-up "Smart Import V2". |
| Integrations | **None.** The PMS / Channel Manager / OTA / Contabilità / Personale cards of Struttura V1 were drawings. |
| Freshness | `PropertySources` / run provenance already state "last successful import"; reused. |

## The model: three things, not confused

- **Kind of data** (what): bookings, distribution, costs, labor.
- **Source** (from where): here always a file source.
- **Method** (how): CSV or XML.

The five **cards** are a *presentation* of those, not connections:

| Card | What it is in V1 |
| --- | --- |
| PMS | owns the **bookings** file source (BOOKINGS, CSV) |
| Channel Manager | never its own connection: `DERIVED` ("già ricevuto") once the bookings were imported |
| OTA | never its own connection: `DERIVED` once the bookings were imported, with the **real channel names** read from them (`BookingChannel`, type OTA). The hotelier is never asked to link Booking.com / Expedia again |
| Contabilità | owns the **costs** source (COSTS, FatturaPA XML) |
| Personale | owns the **labor** source (LABOR, CSV) |

Card states (`SourceCardState`): `NOT_CONFIGURED` ("Non configurato" — also a source that never delivered), `CONFIGURED_FILE`
("Configurato", always with a real last update), `DERIVED` ("Già ricevuto" + "Ricevuti tramite ..."), `CONNECTED` (never
produced today).

OTA and Channel Manager are **derived from the imported bookings** (never their own source): "Già ricevuto", the real channel
names, and "Visualizza canali" leading to Dati. Nothing about them changed.

## Backend (`app/modules/data_sources`, `app/api/v1/sources`)

No new table. `DataSourcesService` reads and writes the existing rows; every call goes through the repositories of the
request's `TenantContext`, and a source is reachable only through the property it belongs to.

| Route (under `/api/v1/properties/{property_id}`) | What it does |
| --- | --- |
| `GET /data-sources` | the five cards' real state, `capabilities` (how each kind of data can REALLY be provided) and `automatic_integrations` |
| ~~`POST /data-sources`~~ | **does not exist**: there is no route that creates a source on its own (the exact surface is pinned in `test_auth_scope.py`) |
| `DELETE /data-sources/{id}` | **switches the source off** (`is_active = false`). Imported data are **never** deleted |
| `POST /data-sources/import-preview?domain=` | looks at a file, **writes nothing — not even a source**: readable, columns found / missing / unused, number of rows (invoices), sample rows, "already imported" (also for a source that was removed before) |
| `POST /data-sources/imports?domain=&filename=&snapshot_local_date=` | imports the file through the real service; answers with counts or ONE reason (`problem`). **The only way a source comes to exist**, and only when this import succeeds. **One active source per domain**: the active one is reused; a removed one is **reactivated** (its history stays attached: a second, empty source would be read by the analysis instead of the imported data); several active ones → 409 `SEVERAL_SOURCES` |
| `GET /data-sources/templates/{BOOKINGS\|LABOR}` | the canonical **column row** (generated from the services' own enums; a test keeps it recognised by the preview). A single header row: an example row would be fictitious data one click from being imported. Costs have none (XML) |

A file travels as the **raw request body** (no multipart: `python-multipart` is not a dependency) with its name in the query;
it is never stored by the API; 10 MB maximum (413 `FILE_TOO_LARGE`). The canonical CSV convention was **moved** from the
CLI to `app/modules/ingestion/canonical_csv.py` and the CLI now imports it: one copy, same behaviour (its tests pass).

Problems are words, never technical text: `UNSUPPORTED_FILE`, `UNREADABLE_FILE`, `EMPTY_FILE`, `NO_ROWS`, `FILE_TOO_LARGE`,
`MISSING_COLUMNS`, `DUPLICATE_COLUMNS`, `INVALID_ROWS`, `UNSUPPORTED_FORMAT`, `SAME_DAY_CONFLICT`, `GENERIC`. The import
service's own error codes are mapped in ONE place (`files.problem_of_code`); the technical detail stays in the server log.

Labor files are dated `snapshot_local_date`: **the property-local day, sent by the page, never guessed** (the import
service insists on an explicit date; the page tells the user "I dati vengono registrati con la data di oggi (...)"). A
different labor file for the same day is a `SAME_DAY_CONFLICT`, not an overwrite.

## Frontend

| Piece | Where |
| --- | --- |
| Contract types | `@ninfa/contracts` (`DataSourcesResponse`, `ImportPreviewResponse`, ...) |
| API client | `lib/api/data-sources.ts` (the only client the block uses); `apiRequest` gained an optional raw `file` body |
| What a card says | `lib/sources/view-model.ts` (pure: state → line, pill, "Ultimo aggiornamento", buttons, menu) |
| Copy | `lib/sources/copy.ts` (plain Italian: no API key, webhook, endpoint, token, payload, schema) |
| Data / import hooks | `lib/sources/use-data-sources.ts`, `lib/sources/use-import-flow.ts` |
| Components | `struttura-sources.tsx` (cards), `struttura-source-menu.tsx` (the "..." menu), `struttura-modal.tsx`, `struttura-source-dialogs.tsx` (per-card "Collega fonte" + the "Collega una nuova fonte" wizard), `struttura-import-dialog.tsx`, `struttura-manage-dialog.tsx` |

Behaviour: while the answer is on its way the block says so (skeleton), on failure it says that ("Riprova") — it never
shows "Non configurato" it has not verified. A failed re-read keeps the last good cards. Dialogs offer ONLY what
`capabilities` says is real; "Importa file" **creates nothing** and only opens the import, which walks:
**choose file → "Controllo del file" (preview) → what NINFA found + warnings → confirm → result**. Only a successful
result makes the page re-read the cards; a failure or a closed dialog leaves them as they were. A file of the wrong
extension never leaves the browser. Removing asks first: "NINFA non riceverà più nuovi dati da questa fonte. I dati già
importati restano in NINFA." The "..." menu lists only usable actions (none for a card with several sources).

## Security

Authentication + membership + the safe 404 are `resolve_property_scope` (shared by every property route). A source of another
property or workspace answers the same `DATA_SOURCE_NOT_FOUND` as a missing id; nothing is switched off or imported across
tenants (tests). No secret exists in V1; none is stored in the browser or logged. The API's exact surface is pinned in
`test_auth_scope.py`; the old Gate 6 "no HTTP route for imports" guard now excludes this authenticated family explicitly.

## Not supported (explicit)

Any automatic integration; CSV for **costs** (invoices are FatturaPA XML only: a CSV would need a mapping NINFA does not
offer); Excel; a generic column mapping; per-source credentials; telling a PMS from a Channel Manager when a bookings file
arrives (one bookings source per property); an age threshold / "dati vecchi" warning (no backend threshold exists).

## Follow-ups

- **Smart Import V2**: let the user map the columns of an arbitrary CSV/Excel once, save the mapping, and make the next uploads
  automatic. The services already hold a suggestion engine and mapping profiles; nothing is exposed yet.
- **Provider kind (needs a migration, NOT done)**: to remember that a bookings source is a PMS *or* a Channel Manager, and
  which one, `data_sources` would need e.g. `provider_kind` + `provider_name` (nullable). Alternatives without a migration:
  none that is honest (the free-text `name` must not carry structure). Impact: one additive migration, no change to analysis.
  Until a real integration exists there is nothing to record, so V1 does not need it.
- A freshness threshold, once the backend approves one.

## Preview

`NEXT_PUBLIC_API_BASE_URL` points at a throw-away fixture API (outside the repository) that imitates this contract with
in-memory state: nothing configured / labor via CSV / costs via XML / a Channel Manager connected with the OTA read through it
(**fixture only**: the backend never says it) / bookings from a file. The fixture follows the same create-on-success rule (a
preview or a failed file leaves "Non configurato"). No demo value reaches the production path: the fixtures live in tests and
in a scratch script outside the repository; no production code imports them, no production backend code can answer `CONNECTED`
(a test pins it), and the production tests do not read the fixtures' scenario data.

## Tests

Backend: `tests/test_data_sources_api.py` (isolation, truthful state, **a source exists only after a successful import**:
opening / previewing creates nothing, a failed first import leaves nothing active, a success creates the source, a second
import reuses it, a dormant source reads "Non configurato", an unexpected failure switches off what it switched on; import
through the real services, removal keeps data, reactivation, templates, size), plus the exact-surface guards. Frontend:
`lib/sources/view-model.test.ts`, `components/struttura-sources.test.tsx` (every card's dialog, states, menu, wizard, import
flow, errors, removal), `lib/api/data-sources.test.ts`, and the guard `lib/sources/sources-guard.test.ts` (no vendor, no
technical word, no invented threshold, one API, no dependency, responsive-critical CSS).

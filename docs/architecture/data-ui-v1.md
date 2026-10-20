# NINFA — Dati UI V1 (operational data workspace)

Oggi answers *"what deserves my attention?"*. **Dati answers *"what is actually happening in my
numbers?"***: observation, metrics, comparison, detail - the operational reality behind NINFA's
decisions. It is not Oggi (no recommendation cards), not a generic BI dashboard, and not Mia.
Decisions: [ADR 0031](adr/0031-data-ui-v1.md).

    ENGINE CALCULATES. DATI DISPLAYS.

    stored facts (snapshots, run, invoices, labor)  ->  DataOverviewService (deterministic, read-only)
                                                    ->  GET /properties/{id}/data/overview
                                                    ->  /dati (formats, never derives a figure)

No model, no Anthropic dependency, no Mia endpoint, no write, no clock, **no migration, no new
dependency**. Branch `ui/dati-v1`, started from `main` (Mia V3 is an independent, unmerged feature and is
not part of this baseline).

## Capability audit (current `main`)

Built from the repository as it is - no metric was assumed. "Now" = shown by Dati V1.

| UI metric | Source / service in the repository | Deterministic? | Period support | Freshness / provenance | Status |
| --- | --- | --- | --- | --- | --- |
| Rooms on books, per night | `booking_snapshots` (OBSERVED, `rooms_on_books`) | yes | per stay night, from the analysis day forward | the run's own booking source (Gate 23B provenance) | **Now** |
| Capacity | `rooms_available` copied into the snapshot from `room_inventory_daily`; `NULL` = unknown, `0` = closed | yes | per night | same | **Now** (unknown capacity is never 0) |
| Occupancy | `sum(rooms on books) / sum(rooms available)` over nights with a known capacity (the same aggregation as Mia's `HomeDataService`; a test pins that both agree) | yes | today / 7 / 30 nights | same | **Now** |
| Room-nights | `sum(rooms_on_books)` over stored nights | yes | 7 / 30 | same | **Now** (never called "prenotazioni") |
| Booking count | `booking_count_on_books` | per night only (summing across nights counts a multi-night booking once per night) | one night | same | **Now, per night only** |
| Room revenue on books | `allocated_room_revenue_on_books` (Booking snapshots V1 allocation) | yes - **not fatturato** | 7 / 30 | same | **Now** (labelled "prenotazioni già a sistema") |
| ADR | `revenue / room-nights` (the stored `adr_on_books` per night) | yes | 7 / 30 + per night | same | **Now** (`NULL` when no room-night) |
| Change vs 7 days ago | the OBSERVED snapshot of `as_of - 7` for the same stay nights | yes, **only when every night of the window has a row both today and in that older snapshot** | 7 nights (30 only if the older snapshot reaches) | same source | **Now**, strict: never a partial comparison |
| OTA share / direct share | the run's persisted OTA decision, or the live `OtaDependencyService.evaluate` (read-only, Gate 9): OTA / (OTA + direct) room-nights, next 30 nights | yes | fixed 30-night forward window (not the 7/30 control) | the run's booking source | **Now** |
| OTA reference level | the evaluation's `expected_ota_share_exact` ("Riferimento NINFA", never a target) | yes | 30 nights | - | **Now** |
| Channel mix | certain room-nights per channel by Gate 3's `booking_certainty_at` rule over the next 30 nights, as a share of **all** channels (a different metric from the OTA share) | yes | 30 nights | the run's booking source, property timezone cutoff | **Now** |
| Costs of the month | `CostLineRepository.monthly_aggregates`: signed `line_total` by **invoice date** (Cost CPOR V1), one currency | yes - **last concluded month only** | calendar month | invoices are cross-source by design (no source to choose); freshness = the single COSTS source's latest import | **Now** (month in progress is not shown, see below) |
| Cost categories | the 14 canonical categories | yes | month | - | **Now**, translated to Italian |
| CPOR (cost per occupied room) | `build_period_metric` (Cost CPOR V1) over lead-time-0 snapshots of the run's booking source | yes, when the month is complete and >= 70 % classified | concluded month | booking source of the run | **Now**, with the reason when not READY |
| Cost vs previous month | net total of the month before, same currency | yes, only with a **positive** base | 2 months | - | **Now** |
| Labor hours / cost | `LaborEvaluationRepository` + `latest_snapshot_rows_by_work_date`, planned minutes of the next 7 days, the property's **single** active LABOR source | yes | next 7 days | single-source rule | **Now** (planned only; days with a half-known shift are counted and left out) |
| Decisions | `DecisionMemoryService.get_feed` (the persisted run) | yes | the analysis day | the run | **Now** (markers and links only) |
| Analysis coverage | run `analysis_coverage`; area state with the Home's own rules | yes | the run | - | **Now** |
| Freshness | bookings: run provenance; costs / labor: the latest SUCCEEDED import of the domain's **single** active source | yes | - | per domain, never one timestamp for all | **Now** |
| Property timezone / currency | `Property.timezone`, `Property.currency` | yes | - | - | **Now** |
| Day-level OTA share | none: the OTA metric is a 30-night window | **no** | - | - | **Omitted** (no OTA column in the table) |
| Per-night "Regolare" | per-night evaluation outcomes are **not persisted** (a run stores counts only) | derived from the run, see below | - | - | **Now, conservatively** |
| Cost of the month in progress | invoices arrive after the fact; Cost CPOR V1 evaluates concluded months only | not safely | - | - | **Not shown** |
| Labor cost / incidence / FTE / productivity | not defined | **no** | - | - | **Not shown** |
| Fatturato, incassi, margine, RevPAR, cancellations, no-show, OTA commission amounts, forecast, competitor / market benchmark, revenue by channel | not defined / not modelled (see the Mia V2 capability matrix) | **no** | - | - | **Not shown**, extension points left clean |

## Architecture

- **`app/modules/data_overview/`** - framework-free, read-only. `types.py` (the vocabulary), `metrics.py`
  (pure calculations, tested without a database), `distribution.py`, `costs.py`, `labor.py`, `sources.py`
  (the "exactly one active source or say so" rule and per-domain freshness), `service.py`
  (`DataOverviewService`). It imports no language-model code (an AST test enforces it, together with
  no float, no write call and no clock read).
- **`app/api/v1/data/`** - ONE endpoint, `GET /api/v1/properties/{property_id}/data/overview
  ?as_of=YYYY-MM-DD&period=7|30`. The route uses the shared `resolve_property_scope` dependency:
  authenticated user -> workspace membership -> property; a missing, archived or foreign property is the
  same `404 PROPERTY_NOT_FOUND`. `as_of` is mandatory (never a server clock); `period` other than 7/30 is
  `400 INVALID_PERIOD`. Decimals are two-decimal strings; a figure that cannot be calculated is `null`
  with a `reason`, never `0`.
- **One endpoint for five tabs.** Panoramica, Prenotazioni, Distribuzione, Costi and Personale are five
  views of the same response: a tab change is not a request. (The 7/30 control is a request, because the
  selected block and the night rows are the backend's.)
- **Frontend:** `app/dati/page.tsx` (URL <-> state), `components/dati-*.tsx`, `lib/data/*` (formatting,
  copy, freshness, tabs, the hook), `lib/api/data-overview.ts`, contract types in `@ninfa/contracts`.
  The chart is plain HTML/CSS (no library). The browser never sums, subtracts or divides two backend
  figures (a test scans for it); bar heights are geometry of a figure the backend sent.

## Route and URL state

`/dati?property=<id>&tab=overview|bookings|distribution|costs|labor&period=7`

- `tab` is omitted by the sidebar link (default Panoramica); `period` is written only for 7 (30 is the
  default). A bad value falls back to the default - never an error.
- A tab or period the user chooses **pushes** a history entry (back / forward walk through them); the
  resolution or the switch of the property **replaces** it. The property is always in the query, like
  every other screen. 0 / 1 / N properties behave as everywhere: empty state / plain name / selector.
- The sidebar "Dati" is a real link with the same active state as Oggi and Decisioni; "In arrivo"
  remains only on Struttura.

## Panoramica

Desktop (>= 1440 px): a 12-column grid mirroring the reference - large occupancy card (4) + 2x2 KPI block (4)
+ occupancy chart (4); then the compact OTA card (4) + the detail table (8). 1024-1439: occupancy + KPIs,
then each card full width. < 1024: everything stacked. < 640: one column, tabs and tables scroll inside
themselves, KPIs one column from 480 px.

| Block | What it shows | Notes |
| --- | --- | --- |
| Occupancy card | occupancy of the selected period, `prossimi N giorni`, room-nights; 7 / 30 control; mini tiles Oggi / 7 / 30; last booking import | says "Capienza nota per X di N notti" when some nights are left out |
| KPI block | Ricavi camera (NINFA-blue highlight), ADR, Camere-notte, Costi di {mese} | a delta only when the backend sent one, always naming its comparison; neutral chip (no good/bad change exists) |
| Chart | stored occupancy per night, NINFA-blue bars; orange marker above a night with a decision | a night with unknown capacity is a hatched slot (never 0 %); axis grows past 100 % (occupancy is not clamped); no target / expected line (none exists) |
| OTA card | OTA vs direct, the reference tick, outcome, channel weights | attention indicator only with a real OTA decision; no commission amounts |
| Detail table | Data, Camere prenotate, Disponibili, Occupazione, Ricavi camera, ADR, Stato | search by date, "Solo attenzione"; only a night with a decision is a link |
| Coverage strip | the four areas' state + the costs / labor freshness | "Analizzati / Analisi parziale / Non analizzati / Non disponibile" |

### Night status (the "Stato" column)

Derived from the run alone - never a frontend threshold:

| Status | Rule |
| --- | --- |
| Attenzione | a decision of today's feed targets that night |
| Analisi parziale | revenue was analysed but the run had checks it could not conclude (`insufficient` or `suppressed` count > 0) |
| Regolare | revenue analysed, no decision targets the night, no inconclusive check (the Home's own "everything under control" rule) |
| Non valutato | no run / revenue not analysed / unrecorded coverage / no booking data for the night |

**Known limit.** A run does not store which stay nights it analysed or the per-night "clear" outcomes.
The automatic policy analyses 30 nights from the analysis day, but a manual run could cover fewer: its
nights outside that range would read "Regolare". Persisting the analysed range on the run would make this
exact; it is deferred, and the table says "Lo stato riflette solo le decisioni di NINFA per la notte: non
è un giudizio sui numeri".

## Other tabs

- **Prenotazioni:** period comparison (Oggi / 7 / 30: occupancy, room-nights, available, revenue, ADR,
  change vs 7 days ago) + the occupancy chart + the nights table with the per-night booking count, the
  count 7 days ago and the change (calculated by the backend).
- **Distribuzione:** the full OTA card (every channel with its room-nights, classification coverage) and a
  card defining *Quota OTA*, *Peso di un canale* and *Riferimento NINFA*.
- **Costi:** the last concluded month's net cost (by invoice date), change vs the month before, the share
  of cost in a recognised category, the category table with the cost per occupied room or the reason it is
  missing, the cost decision with its own figures. Costs in another currency are flagged, never converted.
- **Personale:** planned hours (and planned cost when every shift has one) by role for the next 7 days,
  days with data / incomplete, the overstaffing decision's facts. No incidence, productivity, FTE or ratio.

## Provenance and the rules that keep numbers honest

- **Bookings** come from the run's own booking data source (its persisted provenance), never chosen
  here. No run, or a run that recorded no source: no booking figure, and the page says why.
- **Costs** are property-wide and cross-source by design (an invoice is one document whatever source
  imported it): no source to choose. **Labor** has no "source the run used" (the automatic policy skips
  it), so Dati reads it only when the property has **exactly one** active labor source; several sources
  -> "NINFA non ne sceglie una". Freshness of costs / labor follows the same rule (Gate 23B's
  "never a property-wide maximum").
- **Concluded month only** for costs: the cost detector evaluates concluded months because invoices
  arrive after the fact. The KPI reads "Costi di {mese}" (e.g. "Costi di febbraio"), with "ultimo mese
  concluso, per data fattura". *Product point to confirm:* the brief's "Costi del mese" is read as this;
  the month in progress is not shown.
- **The run is the authority**: a persisted OTA decision's own figures are shown, with no live read; a live
  evaluation only adds a figure when no decision exists, and one that would now trigger while the run has
  no decision shows "i dati sono cambiati dopo l'analisi" and no number.
- **Freshness** is a fact ("Ultimo import prenotazioni: oggi alle 09:31", property timezone), never
  "Dati aggiornati"; each domain has its own line.

## States

| Situation | What the page shows |
| --- | --- |
| Loading | card-shaped skeletons in the final grid; the header and tabs stay (never a page spinner) |
| Error | a contained card with "Riprova"; shell and tabs preserved; the raw error never shown |
| Not processed | designed "Non disponibile" cards with the reason, the date of the last analysis, all areas "Non disponibile" |
| Partial run | hatched unknown-capacity nights, "Analisi parziale" statuses, an OTA card that says why it cannot judge |
| Area not analysed | "Distribuzione non analizzata" / "Non analizzati" - never read as clear |
| No costs / labor | "Non ci sono dati di costo sufficienti per questo periodo." / the reason; never 0 |

## Accessibility

Semantic headings (h1 page, h2 cards, h3 KPI labels); WAI-ARIA tabs with manual activation and roving
tabindex; `aria-pressed` for the period control and the filter; the chart has an accessible name and a
visually-hidden equivalent table (inside a clipping wrapper, because a bare `<table>` ignores
`width: 1px` and would widen the page); tables have captions and `scope`; scrollable tables are named,
focusable regions; a status is always a word plus a shape, never colour alone; visible `:focus-visible`;
`prefers-reduced-motion` respected; light only.

## Tests

Backend: pure calculations, the service on real persisted runs (occupancy, unknown capacity, source,
timezone, OTA outcomes, channel certainty, costs, labor, freshness, coverage), the API (auth, isolation,
safe 404, validation, no float, no leak, read-only, never touches the model provider) and AST guards.
Frontend: formatting and copy, tabs, the page's URL wiring, the screen across the full / partial /
unknown-coverage / not-processed worlds, property switching, the period control, and source / CSS guards.

## Explicitly deferred

Persisting the analysed stay range on the run (exact "Regolare"); the cost of the month in progress;
a day-level OTA share; pickup as a number; forecasts and expected levels per night; historical
trend charts and the OTA-share history; labor actuals and any labor ratio; commission amounts; fatturato /
RevPAR / cancellations; explanations of these numbers by Mia (Mia may later explain them - Dati itself
stays deterministic).

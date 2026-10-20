# 0031 — Dati UI V1: a deterministic, read-only operational data workspace

(Numbered 0031 because 0030 is reserved by the independent, unmerged Mia V3 branch.)

## Context

NINFA had one surface, Oggi, that answers *"what deserves my attention?"*. A hotel owner also needs
the other question - *"what is actually happening in my numbers?"* - without it becoming a generic BI
dashboard, a second Oggi, or a place where numbers are made up. The sidebar already drew "Dati" as a
"In arrivo" placeholder (Home UI V1). The visual reference is a premium analytical layout (a large
summary card, a 2x2 KPI block, a chart, a compact card, a large table).

## Decision

1. **Backend calculates, frontend displays.** One read-only `DataOverviewService` projects data NINFA
   already stores or calculates (on-books snapshots, the persisted run, the OTA evaluation, canonical
   invoice lines, canonical labor entries). The frontend formats; it never sums, subtracts or divides two
   backend figures (a source scan enforces it). No model, no Anthropic dependency, no Mia endpoint.
2. **Define nothing new.** Every metric is one an existing module already defines; the page shows
   "Non disponibile" (with a reason) rather than a figure NINFA cannot calculate safely, and never turns a
   missing value into zero. What NINFA lacks (fatturato, RevPAR, cancellations, commission amounts,
   forecast, benchmark, a day-level OTA share, labor ratios) is not shown and is documented as deferred.
3. **The run is the authority for provenance.** Bookings come from the analysis run's own booking source;
   costs are property-wide and cross-source by design; labor and the costs/labor freshness are read only
   when the property has exactly one active source, otherwise NINFA says it does not choose. A persisted
   decision's own figures are shown; a live read only adds a figure and never contradicts a decision.
4. **One endpoint for five views.** `GET /properties/{id}/data/overview?as_of&period` serves Panoramica,
   Prenotazioni, Distribuzione, Costi and Personale; a tab is a view of one response, not a request.
   Authorization reuses `resolve_property_scope` (same safe 404 for a foreign, archived or unknown
   property).
5. **A night's status is read from the run, conservatively.** Attenzione (a decision targets it),
   Analisi parziale (the run had inconclusive checks), Regolare (revenue analysed, no decision, nothing
   inconclusive), Non valutato (no analysis / no data). No threshold lives in the frontend. Because a run
   does not persist per-night outcomes or the analysed range, "Regolare" is a run-level claim narrowed to
   the night - the same claim the Home already makes - and the limit is disclosed.
6. **Costs: the last concluded month.** The month in progress is not a cost of the month (invoices arrive
   after the fact; Cost CPOR V1 evaluates concluded months only), so the KPI is "Costi di {mese}" for the
   last concluded month, by invoice date.
7. **Chart without a dependency.** A plain HTML/CSS accessible bar chart with a text-equivalent table; the
   "no charts" rule belongs to Home/Oggi, not to Dati.
8. **URL is the state.** `/dati?property&tab&period`; user choices push history entries, property
   resolution replaces.

## Consequences

- No migration, no new dependency, no worker change. A new module, one API package, one route, a set of
  components and contract types.
- Dati and Mia's semantic layer implement the same on-books aggregation separately; a test pins that they
  agree, so the two surfaces can never disagree.
- A later gate can persist the analysed stay range on the run (making "Regolare" exact), add the cost of
  the month in progress once an accrual model exists, and let Mia *explain* these numbers - Dati itself
  stays deterministic.

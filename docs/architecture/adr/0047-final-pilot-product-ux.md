# ADR 0047: Final pilot product UX - coverage, over capacity, inventory from a day, no reliable decision

Status: accepted (Final Pilot Product UX Fix). No migration, no new dependency, no formula, threshold, detector, Decision Memory or Mia change. Builds on
[ADR 0043](0043-dati-cause-and-denominator.md), [ADR 0044](0044-pilot-autonomy.md) and [ADR 0046](0046-a-sample-of-history-is-what-a-finished-analysis-read.md).

## Context

A real review of the pilot in the browser found four places where the numbers were right and the page let them be misread:

1. **Personale** compared the cost of ONE planned day (9 November) with the revenue of that day, correctly, under a heading that said "Prossimi 7 giorni":
   72,4 % read as the week's.
2. **Occupancy over 100 %** (11 rooms booked on an inventory of 10) was shown, but nothing said that two things NINFA stores disagree.
3. **Costs of October** (12.678 €) had no cost per occupied room, and the page said "Occupazione del mese incompleta". The brief's reading was that the inventory,
   configured only from 9 November, was the cause.
4. **Home and Decisioni** headlined "Analisi parziale" and "66 in attesa di dati sufficienti" when the engine had, rightly, nothing reliable to say.

## Decision

### 1. Personale: say how much of the window the figures are about

No formula changed. `LaborOverview.window_days` (the days of the window) is read beside `economics.period_days` (the days with planned hours, on which every ratio is
calculated, revenue included). The page states **"Piano disponibile per 1 giorno su 7"** beside the KPIs, notes the two KPIs that depend on it, and "In sintesi" reads
"Sui giorni coperti dal piano, il costo del personale incide per il 72,4 %...". With a full plan the same line says "per tutti i 7 giorni". "1 giorno con dati" is gone.
A single day reads "il 9 novembre", not "dal 9 al 9 novembre".

### 2. Over capacity: a question about the data, not a decision

`NightRow.over_capacity` (more rooms booked than the inventory has; a closed night with a booking counts, an unknown capacity never does) and
`OccupancyOverview.inventory_consistency` (how many of the 30 observed nights, whatever period is shown, and the first). Nothing is clamped: the stored 110 % stays 110 %.
The page shows "Prenotazioni superiori all'inventario" with the count and "Controlla inventario" (the existing link to Struttura -> Inventario camere); the chart keeps the
bar's true height, hatches and outlines it and draws the inventory as a dashed 100 % line; the table marks the row with a word and the tooltip says "11 prenotate / 10
disponibili". NINFA cannot tell an inventory too low from a real overbooking from a wrong booking, so it opens no decision.

### 3. Inventory valid from a day

`PUT .../room-inventory` takes an optional `valid_from` (default: the property-local today). The number is written on every night from that day on, past nights included
(`room_inventory_daily`, no new model). A day to come, or older than `MAX_BACKFILL_DAYS` (ten years, like the horizon), is a 422 `room_inventory_invalid_valid_from` with
its limits. `GET` and `PUT` also say `known_since`, `today` and `earliest_valid_from` in the property's own days, so the form (default "Valido dal" = today, `min`/`max` from the
backend) works none of them out. A stored observation, a stored reconstruction and a run are never touched: a snapshot copied its capacity when it was taken.

**Measured: the inventory alone does not give a cost per occupied room.** A month's denominator is the rooms on the books of every one of its days, each as the end of that
day saw it (the lead-time-0 snapshot). A property analysed from 9 November has none for October, whatever its inventory says. What the bookings imported say about those days
can be stored as a reconstruction, which copies the capacity and is never rewritten: so the inventory has to come first.

`analysis/history.py` does that, inside the refresh any save already asks for, and as little as it can:

- only the concluded months the invoices touch, only their lead-time-0 day (no grid of lead times);
- only a night that has an inventory;
- only a night inside the first and the last night any current booking covers (before the file begins a night is unknown, not zero);
- never over a snapshot that exists, whatever its origin: an observation wins, and a stored reconstruction is not revised.

It is idempotent: a second call writes nothing.

**History is never added under a day that has already been analysed.** A stored baseline names its comparables and is never rewritten; a past night appearing after
today's analysis made today's next analysis fail (`EXPECTED_BASELINE_CONFLICT`, measured on the real demo, not predicted). With no analysis yet today the history is rebuilt
first and today's analysis reads it; with one, today's analysis is made first (same history, same result) and the history is added after it. A refresh later the same day,
on bookings that did not change, would now read a different history: like the existing snapshot conflict it ends `DEFERRED` to the next local day, which is not a failure.
Any other Expected error still fails the job.

**When it still cannot be calculated, the response says exactly why** (`costs.occupancy`, `CostOccupancyBasis`): each missing day lacks one thing - no inventory (and
from which day one is needed), the bookings do not cover it, its rooms are uncertain (a booking cancelled or marked no-show without a date, which a reconstruction never
guesses), or it waits for the next analysis. "Occupazione del mese incompleta" is only said when the backend sent no basis.

### 4. Home and Decisioni: no reliable decision is neither all clear nor an alarm

`DATA_QUALITY_LIMITED` now reads **"Nessuna decisione affidabile oggi"**: on Home "NINFA sta costruendo lo storico necessario per confrontare i dati della struttura. Quando
emergerà uno scostamento affidabile, lo troverai qui."; on Decisioni "I dati disponibili non indicano ancora un intervento sufficientemente affidabile." and "NINFA sta ancora
costruendo lo storico di confronto." The last booking import and the four areas stay; "Analisi parziale" is secondary (the area tiles, a small badge). The count of checks left
inconclusive is out of the message: on Decisioni it is a folded "Dettagli dell'analisi", on Home it is gone. The card is neutral (no amber). The three states stay different:
nothing found ("Tutto sotto controllo", `NO_ACTION_REQUIRED` only), nothing reliable, nothing analysed.

### 5. Left as it was

Distribuzione, the cost total, the categories and the period of Costi, the detectors, their thresholds and Smart Import.

## Consequences, and what to confirm

- **The demo's October will not have a cost per occupied room**, with or without the inventory: its bookings file begins on the 25th, so 24 days of October are outside what the
  bookings say. Saved from 1 October, the 7 days from the 25th are rebuilt and the page says "Le prenotazioni importate non coprono 24 giorni di ottobre". A file with the
  whole month is what is missing, not a setting.
- **Reconstructed lead-time-0 nights are history.** The Expected engine admits clean reconstructions when it has fewer than five observed comparables, so tomorrow's baseline for
  the night "today" may find them. That is the engine's own rule, not changed here.
- **Every refresh now rebuilds the missing, inventoried nights of the cost months**, not only the one an inventory save asks for. Nothing is written for a property with no inventory
  for those nights.
- **The feed carries no reason for "limited"** (history, a day with no new bookings, a low confidence), so the "building the history" wording is shown for every such day.
  Telling them apart needs a field the Decision Memory does not have, and it was not added.
- A refresh deferred to tomorrow shows as the page's existing "delayed/deferred" state.

## Tests

Backend: `test_data_overview_over_capacity.py`, `test_room_inventory_valid_from.py`, `test_inventory_history_backfill.py` (the whole way with real commits, the order of history and
analysis, the deferral and the other Expected failures), the Personale coverage cases in `test_data_overview_labor_economics.py`. Frontend: Dati (coverage, over capacity, the exact
cause under the cost per occupied room), Struttura (the form's day, its limits and refusals), Home, Decisioni and the feed states. Reviewed in a browser at 1440 and 390 px on a
throw-away copy of the real database.

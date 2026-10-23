# NINFA — Decisioni UI V1 (the decisions board)

`/decisioni` is **today's feed, every decision of it** (Home UI V1, D7): exactly the list the Home's
"N decisioni richiedono attenzione" counted. This revision redesigns its *presentation* from an approved
mockup. **No backend change, no migration, no new dependency, no model, no Mia**: the page reads the same
`GET /properties/{id}/decision-feed` as the Home (`useDecisionFeed`).

    feed items (backend order, priority_rank ASC)  ->  lib/decisions/list-view-model.ts  (one row per item)
                                                   ->  hero + area filter + sort + rows

## Composition

| Zone | Component | What it shows |
| --- | --- | --- |
| Hero | `decisioni-hero.tsx` | "Decisioni", the Home's own count sentence, the booking-import freshness as a **fact** ("Ultimo import prenotazioni: oggi alle HH:MM"), the refresh, and two cards: *Prima decisione* (the engine's rank 1: its area + title) and *Aree coinvolte* ("N di M": areas with a decision / areas the run analysed; only "N" when the run recorded no coverage) |
| Filters | `decisioni-board.tsx` | "Tutte" + the four areas, each with its count (`aria-pressed`, `aria-label` "Ricavi, 2 decisioni"); a sort `<select>` (Priorità / Più recenti / Aperte da più tempo) |
| Row | `decision-row.tsx` | area tile + name, "Priorità N", the title (problem), a one-sentence description (evidence), "Rilevata il …", the key metric against its expected level with a small comparison visual, the impact, "Affidabilità N%", and one action "Apri dettaglio" (a stretched link: the whole row is clickable, a keyboard meets one link) |
| Other feed states | `feed-state-view.tsx` (unchanged) | NO_ACTION_REQUIRED, NOT_PROCESSED, DATA_QUALITY_LIMITED keep their dedicated cards: "Tutto sotto controllo" still appears only for NO_ACTION_REQUIRED |

## What each row shows (`list-view-model.ts` - one place decides)

| Type | Metric | Departure chip | Impact |
| --- | --- | --- | --- |
| `REV_PICKUP_LOW` | Pickup rilevato (attesi X) | − % vs atteso | Camere mancanti |
| `REV_OCCUPANCY_RISK` | Camere previste (attesi X) | − pp vs atteso | Camere in meno |
| `REV_OTA_DEPENDENCY` | Prenotazioni da OTA | + pp vs riferimento X% | Camere-notte da OTA |
| `COST_CPOR_ANOMALY` | Costo per camera | + % vs atteso X € | **Impatto stimato** (`economic_proxy`) |
| `LABOR_OVERSTAFFING` | Ore programmate | + % vs atteso X h | **Impatto stimato** (`economic_proxy`) |

## Product rules the page keeps (and where it deviates from the mockup)

- **Priority is the engine's ordinal rank** ("Priorità 1..N"), never an Alta / Media / Bassa bucket. The pill
  is drawn more strongly for the first two ranks; it names no severity.
- **No aggregate "Impatto stimato totale".** An economic estimate exists only for cost and labor decisions,
  carries its own currency, is labelled an indicative estimate, and is never summed or compared across kinds;
  revenue and OTA decisions have no currency at all. Each row shows its own impact where the engine recorded
  one, otherwise its operational gap (rooms, room-nights, hours). The hero's second summary card is "Aree
  coinvolte" instead.
- **Freshness is a fact**, never "Dati aggiornati".
- **No trend, no "vs anno scorso", no sparkline**: a decision carries no time series. The small visual is a
  picture of two numbers the decision itself holds (found vs expected, or the OTA share) - decorative
  (`aria-hidden`), every figure is also written in text.
- **Problem + evidence, never a recommendation** on the card; the recommendation stays in the Decision Detail.
- **Area colours are categorical** (Ricavi orange, Distribuzione violet, Costi green, Personale blue), always
  paired with the area's name and icon. This relaxes the Home's single-attention-colour rule **on this page
  only**, as the approved mockup requires; no colour carries severity.
- A missing fact is a dash or nothing - never a made-up number. A raw enum is never shown; an unknown category
  yields the generic sentence.
- The default sort is the backend's own order (never re-sorted); "Più recenti" / "Aperte da più tempo" order
  by the first-seen date with the rank as tie break. Filtering only narrows the rows the backend sent.
- Not built (no real source or not coherent with the product): "Chiuse" tab, "Filtri" button, search, side
  column, per-row secondary actions ("Rimanda" etc. - there is no write path).

## Responsive

Four zones on one line from 1400px (tighter between 1400 and 1599px); two lines (what is wrong / the numbers +
action) below; stacked on a phone, where the area pills scroll inside their own row instead of widening the
page. Light only, `prefers-reduced-motion` respected, visible focus rings. The CSS rules that jsdom cannot lay
out are pinned in `lib/decisions/decisioni-guard.test.ts`.

## Tests

`lib/decisions/list-view-model.test.ts` (per-type rows, estimate vs gap, missing facts, no enum / no
recommendation / no bucket, sort, counts), `components/decisioni-screen.test.tsx` (all 8 items, backend order,
detail hrefs, Home count parity, hero, filters, sort, other feed states, loading / error / refresh /
properties), `lib/decisions/decisioni-guard.test.ts` (source and stylesheet guards).

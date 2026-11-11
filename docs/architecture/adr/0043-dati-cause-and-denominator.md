# ADR 0043: Dati says the cause in the hotel's terms, and what every percentage is a share of

Status: accepted (Dati Pilot UX & Coverage Fix). No migration, no new endpoint, no dependency. Amends
[Dati UI V1](../data-ui-v1.md). The OTA check (Gate 9) and the booking snapshot rules (Gate 3) are unchanged.

## Context

A product review of Dati on the demo property in `ninfa_dev` (96 bookings, imported on 7 November 2026, no room
inventory) found four problems.

1. **Personale.** "Incidenza sui ricavi" and "Ricavo per ora" are calculated on the on-books room revenue of the same days.
   The formulas are correct. The names are too general.
2. **Occupazione.** The property has no row in `room_inventory_daily`, so no observation carries a capacity. The page showed
   "Non disponibile" and "Nessun dato di occupazione", which reads as a bug while 133 room-nights and their revenue were
   on screen.
3. **Dipendenza OTA.** The page said the channel composition does not match the registered bookings, and showed channel
   weights beside it. Measured on that data, over the 30 nights from 7 November:
   - The day's observation counts 133 room-nights. It counts a booking by its status as it is now (Gate 3,
     `aggregate_observed`).
   - The OTA check and the channel weights read the same bookings with Gate 3's certainty rule at the end of the
     day (`booking_certainty_at`), and count 121. That rule also asks whether the booking already existed
     (`booked_at`), when it was cancelled (`cancelled_at`), and whether a no-show could be known yet (its arrival).
   - The two disagree on 11 of the 30 nights, because of 13 bookings of the window:
     - 9 confirmed bookings have a booking date after the analysis day (8 to 23 November, property time).
     - 4 no-shows are for stays that start after the analysis day. The file says "Modificata" for 5 rows, and that
       value was answered "Non presentato" at import.
     - The two totals are bridged exactly, in room-nights: 133 observed, minus 21 of the 9 confirmed bookings, plus 9 of
       the 4 no-shows, is 121.
   - The 3 cancellations have no cancellation date. They are on the books under neither rule, so they are not a cause.
     Every booking has a channel, and every booking is for one room, so neither is a cause either. Both readings use
     the same 30 nights and room-nights, never a booking count.
   - The check refuses at its third condition (`OTA_CHANNEL_MIX_RECONCILIATION_FAILED`), and it is right to: on dates
     consistent with the day the two rules agree, and these dates are not.
   - The fault was on screen: the weights were percentages of 121 room-nights, beside a page that says 133, with
     nothing saying so.
4. **Dettaglio soggiorni.** At 1440 px the overview table had only 6 to 24 px to spare in its card. A Windows browser
   takes about 11 px for the page scrollbar (the card is 8 of 12 columns) and 15 to 17 px for the table's own vertical
   scrollbar. That is enough for a few pixels of overflow, and so a horizontal scrollbar whose thumb is almost the whole
   width.

## Decision

1. **Personale names the revenue it uses.** The labels are now "Incidenza sui ricavi on-books" and "Ricavo on-books per
   ora", and the role column reads the same. Every line of the tab that speaks of revenue says on-books; a copy test
   enforces it. The formulas and "In sintesi" are unchanged.
2. **Each period says whether its occupancy can be calculated** (`PeriodMetrics.capacity`), from the stored observation
   and the room inventory as it is now:
   - `KNOWN`: every night with bookings has a capacity.
   - `PARTIAL`: some nights do.
   - `MISSING`: none does, and the property has no inventory for those nights.
   - `AWAITING_ANALYSIS`: none does, but an inventory now exists for them. It was set after the observation, which
     copies the capacity when it is taken, so the next analysis takes it in.

   A closed night (0 rooms) is a known capacity. **A capacity is never inferred from the bookings**: not the rooms
   booked, not the busiest night, not the room numbers. Without an inventory only the occupancy, the rooms available
   and the chart are missing. Room-nights, revenue, ADR and the table stay.
3. **"Configura inventario" leads to Struttura's own inventory block**: `/struttura?property=…#struttura-rooms`. There is
   no new page, and no setting inside Dati. The block carries its section id. Struttura scrolls it into view once the
   page has rendered, because its content appears only after the session and the property are resolved, so neither the
   browser nor the router can scroll to it. The link sits in the chart's empty state, which used to say "Nessun dato di
   occupazione". The occupancy card states the cause in words.
4. **The OTA check is not relaxed and not reworded into success.** Dati now tells the person why, and says what the
   weights are a share of:
   - `BookingDateConflicts` counts, from the same bookings as the weights, the three ways the two rules can disagree
     about a booking. The card states them in plain Italian, with the backend's counts, and adds "Controlla queste
     prenotazioni nei dati importati."
   - `ChannelMix` now carries its denominator (`total_room_nights`), how many of those are OTA or direct and how many are
     unclassified, the room-nights the day observed over the same nights, and whether the two match.
   - The card says before the weights what they are a share of. When the two totals differ, the weights read as
     "Composizione indicativa", with both totals stated.
   - With a low classification coverage, the reason states the real share NINFA can classify.

   **Refused:** computing the weights by today's statuses. For a past analysis day that describes today instead of that
   day; an existing time-zone test pins the end-of-day rule. It would also hide the disagreement instead of stating it.
   **Refused:** a tolerance on the reconciliation. That changes Gate 9's meaning, and these data really do contradict
   themselves.
5. **The nights table fits a desktop card.** Cells have 8 px of horizontal padding. The night's status, a word, may
   wrap under its mark, while a figure never wraps. The status header asks for a share of the table (22 %, or 16 % on
   the ten-column Prenotazioni table), so the status stays on one line when there is room. A share never raises the
   width below which the table must scroll. No column is removed. Measured in Chrome from 1024 to 1920 px on the real
   data and on a large hotel's figures. The overview card is narrowest at 1440 px, where the grid gives it 8 of 12 columns
   (103 px to spare on the real data, 85 on a large hotel's). From 1280 px up, every table keeps at least 43 px, enough
   for two scrollbars (about 28 px). Below 1280 px the ten-column Prenotazioni table may scroll inside its own region, and
   the page never does. "Riepilogo per periodo" loses its own `min-width: 720px`: it has 567 px of content, and the rule
   made it scroll at 1024 px for nothing.

## Consequences

- Struttura's own "Configura inventario" button was not wired by this decision. [ADR 0044](0044-pilot-autonomy.md) wired it: the
  person says the number there, and the occupancy follows. Dati reads `AWAITING_ANALYSIS` until that analysis has run.
- The demo file keeps its dates. Run in memory through the real detector on those bookings, nothing written:
  - Correcting only the booking dates still fails reconciliation (133 observed, 142 certain), and so does correcting only
    "Modificata" (142 observed, 121 certain).
  - Correcting both reconciles at 142 room-nights. The check then stops on the missing history
    (`OTA_COMPARABLE_SAMPLE_INSUFFICIENT`): none of the 24 candidate past days has a whole 30-night window. At that point
    the coverage is 84,51 % and the OTA share 60,00 %.
- "Telefono / Email" was not in Gate 9's closed dictionary, so it was unclassified: 20 of the 121 room-nights. It did not
  cause the refusal. [ADR 0044](0044-pilot-autonomy.md) took the product decision: it is direct. The same corrected data give
  100 % coverage and a 50,70 % OTA share.
- The page reads the analysis of the property's current day. With no analysis for the day, occupancy, revenue and the OTA block
  are not available ("L'analisi di oggi non è ancora disponibile"), whatever the last analysis said. On the demo property
  that was the state on 9 November. [ADR 0044](0044-pilot-autonomy.md): the worker now asks for the day's analysis by itself.
- `GET /data/overview` gains fields only: `capacity` on each period, the denominator fields of `channel_mix`, and
  `date_conflicts`. No field is removed or renamed.

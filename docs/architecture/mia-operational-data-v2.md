# Mia V2 - operational data access and short conversation (`ask-mia-home-v3`)

Mia is the natural-language interface to NINFA: a hotel owner asks "Gli OTA sono a posto?", "Quanto
pesa Booking?", "Qual è l'occupazione dei prossimi 7 giorni?" and Mia answers **from facts NINFA
already calculated or retrieved** - never from raw records, never from her own arithmetic. See
[ADR 0029](adr/0029-mia-operational-data-v2.md) for the "why" and [ask-mia-home-v1.md](ask-mia-home-v1.md)
for the base Mia Home.

    ENGINE CALCULATES. MIA EXPLAINS.

    USER QUESTION (+ short history)
      -> question understanding   closed intents, hospitality aliases, typos, period, follow-up
      -> NINFA safe semantic data layer   HomeDataService: stored snapshots, OTA evaluation, channel weights
      -> deterministic, labelled facts (+ grounding refs)
      -> one bounded model call: Mia explains them

## What changed in V2

1. **Standalone questions are understood.** "Gli OTA sono a posto?" no longer needs a previous
   message: OTA / portali / Booking / Expedia / canali / distribuzione ..., with common typos, map to
   the Distribution topic.
2. **Operational facts.** `HomeDataService` supplies, per question, the occupancy of a period, the
   bookings of a night, room revenue on the books, the OTA share, the weight of a named channel, an
   area's analysis status - computed by application code, not by the model.
3. **A short conversation.** The page sends the last few exchanges with each question
   (`history`), so "Perché?" and "Intendo gli OTA, sono a posto?" are follow-ups, not new, unclear
   questions. History is referential context only; NINFA's fresh facts always win.
4. **A small conversation UI** (up to 4 visible exchanges, scrolling inside a bounded area) and an
   **auto-growing composer** (`<textarea>`, 1-4 lines, Enter sends, Shift+Enter inserts a new line).

## Capability audit

The matrix below was built from the repository as it is (no endpoint or metric is assumed).

| Question type | Source / service in the repository | Deterministic fact possible? | Now / deferred |
| --- | --- | --- | --- |
| Today's decisions, their order, impact estimates | `DecisionMemoryService.get_feed` (persisted run) | Yes - the Engine's own output | **Now** (since Mia Home) |
| Coverage, last import, last analysis | run `analysis_coverage` / `input_provenance` | Yes | **Now** |
| OTA share / dependency when a decision fired | the decision's persisted facts | Yes | **Now** |
| OTA share when **no** decision fired | `OtaDependencyService.evaluate` (read-only, Gate 9) | Yes, when evaluable (else a stated reason) | **Now** |
| Weight of Booking / Expedia / any channel | bookings + channels + Gate 3 certainty rule | Yes: share of certain room-nights over the next 30 nights | **Now** |
| Rooms / bookings on the books for a night or period | `booking_snapshots` (OBSERVED, the run's own source, the analysis day) | Yes | **Now** |
| Occupancy on the books of a period | same snapshots (`rooms_on_books` / `rooms_available`) | Yes (sum ratio, nights with known capacity) | **Now** |
| Weakest nights | same snapshots, ordered by on-books occupancy | Yes - a descriptive sort, not an Engine verdict | **Now** |
| Room revenue on the books, ADR on the books | same snapshots (`allocated_room_revenue_on_books`) | Yes - but it is **not** fatturato | **Now** (labelled) |
| Status of costs / personale | decisions + `analysis_coverage` | Yes (state only) | **Now** |
| Which area is most critical | area of the decision NINFA placed first | Yes (reports the Engine's order) | **Now** |
| Pickup as a number | defined inside the pickup detector, needs the Expected baseline | Only as a Decision | Deferred (Decision only) |
| Final occupancy / forecast | `intelligence/demand` feeds detectors; no user-facing definition | Not approved | Deferred |
| Fatturato, incassi, margin, profit | no accounting model of revenue (`invoices` = supplier invoices) | **No** | Deferred, stated as unsupported |
| RevPAR | defined nowhere | **No** | Deferred, stated as unsupported |
| Cancellations / no-show rate | statuses exist, no metric defined | No | Deferred |
| Commission **amounts** | `commission_amount` exists, no cost semantics | No | Deferred |
| Cost per room / labour hours when no decision | cost/labour services need an explicit period that the run does not persist | Not without it | Deferred |
| Nights before the analysis day, "ieri", the month so far | snapshots describe the nights FROM the analysis day; reconstructed ones are approximate | Not reliably | Deferred |
| "weekend" | not a defined period | - | Deferred (ask for sabato / domenica) |
| Market, competitors | no data | No | Not possible |

## Supported questions now

Everything below is answered with facts from the sections of `dati operativi richiesti`:

- **Decisions / priority / other problems / impact / data used** - as in Mia Home v2.
- **Distribution:** "Gli OTA sono a posto?", "Come stanno andando gli OTA / i portali / i canali?",
  "Quanto pesa Booking / Expedia?", "Booking sta pesando troppo?", "Come va il diretto?".
- **Bookings / occupancy for a period:** "Quante prenotazioni ho per sabato?", "Qual è l'occupazione dei
  prossimi 7 giorni?", "Come siamo messi la prossima settimana?", "Quali giorni sono più deboli?".
  Periods: oggi, domani, dopodomani, a weekday, "i prossimi N giorni", "questa settimana", "la prossima
  settimana", "questo mese" (from today), "il prossimo mese", "12 ottobre". With no period: the next 7
  and the next 30 nights.
- **Room revenue on the books:** "Quanti ricavi nei prossimi 7 giorni?".
- **Costs / personale:** "Come stanno andando i costi?", "Il personale è sovradimensionato?" - the
  area's state and its decisions.
- **Which area is most critical:** reported from NINFA's own order.
- **Last import / data used.**
- **Follow-ups:** "Perché?", "Spiegami meglio quello delle OTA", "Intendo gli OTA, sono a posto?",
  "E domani?".

## Explicitly unsupported questions (and what Mia says)

Each is recognised and answered with one fixed plain sentence (`home_facts.UNSUPPORTED_NOTES`), plus
whatever **is** supported:

| Question | What Mia can say |
| --- | --- |
| "Quanto ho fatturato questo mese?" | NINFA has no fatturato / incassi / margine; it has room revenue on the bookings from today to month end (given, labelled "non fatturato") |
| "Qual è il RevPAR?" | NINFA does not calculate RevPAR |
| "Quante cancellazioni?" | no indicator on cancellations / no-shows |
| "E rispetto ai concorrenti?" | no market or competitor data |
| "Quanto pago di commissioni a Booking?" | commission amounts are not calculated; the **weight** of Booking is |
| "Quanto pesa il personale?" / "Quanto incide ...?" | NINFA defines no incidence; it has the area's state and decisions |
| "Che occupazione prevedi a fine mese?" | no forecasts outside decisions; occupancy given is on the current bookings |
| "Come va il weekend?" | "weekend" is not a defined period; ask for a day or a range |
| a question about nights already gone | no data before the analysis day |
| anything else (weather, ...) | what Mia **can** explain (`cosa NINFA sa spiegare`), never a generic fallback |

## Conversation context

- The page keeps the newest **4 exchanges** (the one being asked included) in memory only - lost on
  reload or "Nuova conversazione". It sends the complete earlier exchanges as `history` (oldest first,
  alternating `user` / `assistant`): at most 3 from the UI; the backend accepts up to **4**.
- `validate_history` is strict and never repairs: > 8 messages, an odd number, roles not alternating,
  a blank message, a user message > 1000 characters, an assistant message > 1800, a total > 8000, or a
  user message the deterministic guardrail would refuse -> `400 INVALID_ASK_HISTORY` with a static
  `reason` (never an echo of the text). It is checked before the guardrail, the feed and the model.
- Only the UI's complete exchanges are sent: a failed, refused or unavailable exchange is not (a lone
  question would break the alternation, and a refusal must never be replayed as context).
- **The history never carries facts.** The router reads only the **user's** earlier messages to decide
  what a follow-up refers to ("Perché?" after the priority question -> PRIORITY); the assistant's
  earlier text is never mined, so a forged "mia" turn cannot steer the fetch. The facts are rebuilt
  fresh for every request, so the same topic gets the same context with or without history.
- The provider gets history in its **own block** (`<conversation_history>`), one JSON line per
  message with plain keys (`chi`, `testo`), JSON-escaped: a message cannot close the block or forge a
  neighbouring turn. The instructions rank it below the NINFA context and call it untrusted data.
- Without history a bare "Perché?" is flagged (`cosa NINFA non può determinare`) and Mia asks for a
  clearer question - the endpoint stays stateless; nothing is stored server-side.

## Semantic data layer (`HomeDataService`)

`app/modules/ai/ask_ninfa/home_data_service.py`. Read-only; no clock (`as_of_local_date` is the feed's
explicit business date); every read through the repositories of the request's `TenantContext`.

- **The source is the run's own.** The booking data source id comes from the run's provenance (Gate
  23B) - never inferred, never from the request. A run with no provenance has no booking facts, and
  the context says so.
- **Snapshots:** the OBSERVED `booking_snapshots` of the analysis day for the requested nights.
  Occupancy = sum(rooms on books) / sum(rooms available) over the nights with a known capacity
  (a night with an unknown capacity is left out and counted: "Notti con capienza nota"). A period
  with no stored nights is reported as missing, never as zero. The number of bookings is given for one
  night only (summing `booking_count_on_books` across nights would count a multi-night booking once
  per night); for a period, room-nights are given.
- **OTA share** is `OtaDependencyService.evaluate`'s own `ota_share_exact` (OTA / (OTA + direct) room
  nights, 30 nights forward) with its expected share and window - only when no decision fired.
- **Channel weight:** certain room-nights per named channel over the same 30 nights, by Gate 3's own
  `booking_certainty_at` (a cancelled or uncertain booking is not counted), as a share of all certain
  room-nights. It is **not** the OTA share (different denominator) and the section note says so.
- **No raw record leaves the module:** only labelled data points and small tables. No id, SQL, guest
  datum, source record id or booking row is in the context (tests assert it on the serialized text).
- **Area outcomes:** analysed with a decision / analysed without one / not analysed / not assessable.
  "No decision" in an analysed area is hedged when the run had checks without enough data (those
  counts are not attributable to an area - Gate 22A).

## OTA behaviour ("Gli OTA sono a posto?")

| Case | Context says | Mia says |
| --- | --- | --- |
| **A.** Distribution evaluated, OTA decision present | the decision (share, reference, gap) | explains it concretely; "è una delle decisioni che richiedono attenzione" |
| **B.** Distribution evaluated, no decision, evaluation CLEAR | outcome + observed share, reference, window | "Per quanto analizzato oggi, NINFA non rileva una criticità actionable sulla dipendenza OTA" + the numbers; never "perfetti"; it means the threshold was not crossed |
| **C.** Distribution skipped / coverage unknown / no analysis | "non analizzata" / "non disponibile" | "oggi NINFA non può giudicarlo" and why |
| **D.** Evaluated but INSUFFICIENT / low confidence | the reasons in plain Italian | what was missing; **never** "va tutto bene" |
| (defensive) live evaluation would now TRIGGER but the run has no decision | "i dati sono cambiati dopo l'analisi" | asserts nothing until the analysis is redone - the run is the authority |

## Grounding

Every section, decision, area and the freshness fact carries a `riferimento`; the answer's
`grounding_refs` are the refs it drew on, as structured metadata (the UI never shows them):
`metric:occupancy:2026-10-09:2026-10-15`, `metric:bookings:...`, `metric:revenue:...`,
`metric:nightly:...`, `metric:weakest-nights:...`, `metric:ota-share:2026-10-08`,
`metric:channel-mix:2026-10-08`, `coverage:distribution` (and `revenue` / `costs` / `labor`),
`freshness:bookings`, `summary:areas`, `decision:ota-dependency`, `decision:pickup:2026-10-05`, ...
plus the six base refs (`ANALYSIS_STATE`, `DECISIONS`, ...). Multi-word parts are **hyphenated**, not
snake_case: an underscore would make a ref echoed by a model look like a technical identifier to the
leak check. The vocabulary a model may name is **per request** (the base refs + exactly the refs in
that context) and is also the structured-output enum; a ref outside it - invented, or real but not
fetched for this question - is dropped by validation.

## Safety

- No SQL by the model, no tools, no web, no arbitrary internal API: the provider request is text only
  (instructions, context, history, question) and one bounded call.
- Raw-data-free: the context holds labelled facts, no booking/invoice/labour rows, ids or secrets.
- Scoped: authenticated user -> selected property -> authorised tenant. A foreign property is a 404
  whatever the history says; another tenant's snapshots/channels are unreadable by the service
  (tested).
- History: bounded, strictly validated, user-injections refused before anything runs; assistant text
  untrusted and never mined; JSON-escaped in its own block; instructions: the NINFA context is
  authoritative, a conflicting earlier answer loses, history text is data.
- Read-only: no `DecisionService.sync()`, no write (row counts asserted before/after).
- The Decision Ask is untouched (700 chars, 1024 tokens, its own vocabulary, no history).

## Frontend

- **Conversation:** up to 4 exchanges in a bounded, labelled area above the bar (`max-height:
  min(42vh, 400px)`, scrolls inside itself, newest exchange starts at its top); only the newest reply
  is the polite live region; "Nuova conversazione" starts over; a different property or date resets
  it and ignores a late answer of the old one. Retry re-sends the same question with its original
  history. One request in flight.
- **Composer:** `<textarea rows=1>` auto-growing to 4 lines (`autosize`), then scrolling inside;
  Enter sends, Shift+Enter inserts a new line, Enter during IME composition never sends; empty or
  whitespace-only never sends; the chips fill but never send; focus stays; `maxLength` 1000.

## What the tests do not prove

A deterministic suite cannot show that a **real model** follows the instructions: that it reads
`dati operativi richiesti` rather than inventing, answers "Per quanto analizzato oggi ..." in case B,
keeps to 60-160 words, or resolves "Perché?" well. The tests prove the rules are in the instructions,
the facts and the routing are right, the history is bounded and safe, the pipeline is read-only and
scoped, and the refs are exact. The **real Anthropic smoke test** (a configured key, a feed with
decisions / partial coverage / a `NOT_PROCESSED` day, the questions above plus typos and follow-ups)
is still required, and so is measuring latency against the unchanged 15 s timeout.

## Deferred capabilities

Pickup as a standalone metric; final occupancy / forecast; fatturato / incassi / margin (needs an
approved revenue model); RevPAR; cancellations and no-show rate; commission amounts; cost per room and
labour metrics without a decision (needs the analysed period persisted on the run); nights before the
analysis day; "weekend" and other undefined periods; per-channel revenue (the snapshot has none); a
dedicated OTA-share history/trend. Each is a future gate with its own definition - none was defined
silently here.

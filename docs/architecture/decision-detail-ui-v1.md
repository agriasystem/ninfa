# Decision Detail UI V1 (`decision-detail-ui-v1`, Gate 15)

"Oggi" (Gate 14) answers "what deserves my attention today". This gate answers the next two
questions a real user asks about any one of those cards: "why does this deserve attention", and
"how has it evolved over time". It reads exactly the Decision Detail and Decision History
endpoints Gate 12 already shipped, over the SAME lifecycle Gate 11 already persists - no new
backend feature, no new route, no migration.

## Route

`/oggi/decisioni/{decisionId}?property={propertyId}`
(`app/oggi/decisioni/[decisionId]/page.tsx`).

The backend's own `GET /properties/{property_id}/decisions/{decision_id}` needs both ids; the
spec's own suggested route shape put both in the PATH
(`/properties/{propertyId}/decisioni/{decisionId}`). This gate instead keeps `propertyId` as a
query parameter, for one reason: Gate 14 already established `?property=` as the one and only
way this app carries "which property is in scope" (`/oggi?property=...`) - introducing a second,
path-segment convention for the SAME concept, one gate later, would make the two nearly-identical
mechanisms a source of confusion rather than of clarity. `decisionId` is the one thing this page
is actually ABOUT, so it is the one thing in the path; `propertyId` is context, so it stays a
query parameter, exactly like every other page in this app. Neither id is ever trusted as
authority - see "Security & scope" below.

## Scope & auth

`components/decision-detail-screen.tsx` mirrors `components/oggi-screen.tsx`'s own auth
bootstrap (`AuthGate`: loading -> authenticated | redirect to `/login`), then validates
`propertyId` against the authenticated `SessionContext` using the SAME
`lib/session/properties.ts` helpers Gate 14 already built (`allAccessibleProperties`,
`resolveSelectedProperty`) - no duplicate property-resolution logic exists anywhere in this app.

Unlike `/oggi`, an invalid/foreign/missing `propertyId` here is never silently corrected in
place: this page is about ONE specific decision, and a decision does not become meaningful under
a different property just because the URL was fixed. Instead, `DecisionDetailScreen` redirects
straight to `/oggi` for whichever property was actually resolved (or to a bare `/oggi` when the
user has none) - the SAME redirect path is used when the user picks a different property from
the shell's own selector while already on this page, since neither case can safely keep the
current `decisionId`. The backend's own `resolve_property_scope` + `_decision_in_scope` (Gate 12)
remain the real, final authorization barrier regardless of what the client believes.

## API calls

`GET /api/v1/properties/{propertyId}/decisions/{decisionId}` and
`GET /api/v1/properties/{propertyId}/decisions/{decisionId}/history?limit=&cursor=`
(`lib/api/decisions.ts::getDecisionDetail`/`getDecisionHistory`, extending Gate 14's own module -
same `credentials: "include"`/`cache: "no-store"` contract, same `ApiResult<T>` error shape).
Both are fetched in **parallel** on mount (`Promise.all`, never a waterfall) - they are
independent reads, and their errors are independent too: a history failure never blocks the
detail from rendering, and vice versa (see "Error handling").

## Current snapshot

`components/decision-detail-view.tsx::DecisionDetailContent` renders the Decision's own lifecycle
facts and the latest Observation's meaning as four of the five macro-sections the spec allows
(never ten small panels):

1. **Header** - the static title (reused verbatim from Gate 14's `decisionTypeTitles`, never
   duplicated), the target's own subtitle (a stay date, a cost period, a work date - never a
   `booking_data_source_id`/`labor_data_source_id` UUID), and the one-line current status.
2. **Stato attuale** - `Decision.status` ("Aperta"/"Risolta"), when it was first detected, when
   it was resolved (if it was), and an "N episodi" line when `episode_count > 1`. Status is
   Decision-level lifecycle fact, never a call to action: "Aperta" means the problem is still
   open, not "you must act now" - there is no "urgente"/"azione richiesta" copy anywhere.
3. **Cosa sta succedendo** - the latest Observation's own transition, in the SAME calm copy the
   timeline uses (`lib/copy.ts::lifecycleEventCopy` - one shared function, current and historical
   rendering can never disagree on wording), its priority rank if it was TRIGGERED with one
   ("Priorità #2 nell'analisi del giorno" - never impact/urgency/actionability/priority scores,
   which stay internal), and the deterministic "Perché NINFA te lo mostra" sentence (see below).
4. **Evidenze** - at most 5 rows (`lib/decisions/evidence-rows.ts`): Attuale/Atteso/Scostamento
   from the SAME view model the card and the "why" sentence use, Affidabilità (confidence, never
   bucketed into Alta/Media/Bassa), and ONE coverage/sample row - shown ONLY when the real
   `evidence` record actually carries `classification_coverage_pct_exact` (OTA/Cost/Labor) or
   `pattern_pair_count` (Revenue); never invented for a type whose contract lacks it. An economic
   proxy, when present, is labelled "Impatto economico indicativo" - never "perdita"/"risparmio".

### "Perché NINFA te lo mostra"

`lib/decisions/why-copy.ts::whySentence` - one deterministic Italian sentence per decision type,
built ONLY from fields already on the type-specific view model (itself built only from the real,
whitelisted facts - see `lib/decisions/card-view-models.ts`). No AI, no prose generation. Each
detector's trigger condition is one-directional by construction (`REV_PICKUP_LOW`/
`REV_OCCUPANCY_RISK` only fire on a shortfall, `LABOR_OVERSTAFFING` only on an excess,
`COST_CPOR_ANOMALY` only above its own upper fence), so the wording never needs to branch on a
sign. When a fact the sentence needs is missing, it returns `null` and the section is omitted
entirely - never a half sentence.

## Five detector adapters

`cardViewModelFromTargetAndFacts(target, facts)` (extracted from Gate 14's own
`cardViewModelOf`) is the ONE shared dispatcher both the feed card and this gate's detail/history
rendering call - there is no second, parallel mapping of the facts whitelist anywhere. The same
function, given the Decision's `target` and any one Observation's own `facts` (current or
historical), returns the same typed, per-type view model Gate 14 already built and tested.

## Decision Memory (the timeline)

`components/decision-timeline.tsx`, heading "Evoluzione": a plain vertical `<ol>`, CSS/HTML only
- no chart, no sparkline. History is read **newest-first**, exactly as the backend orders it, and
is never re-sorted. Each entry shows:

- the observation's own `as_of_local_date` (`lib/date/local-date.ts`, see below);
- `lifecycleEventCopy(transition, sourceStatus)` - the SAME function the current-snapshot section
  uses, so the two can never disagree. `NO_STATE_CHANGE` reads differently depending on the
  detector's own source status (`INSUFFICIENT_DATA` -> "Dati non sufficienti per una nuova
  conclusione", `SUPPRESSED_LOW_CONFIDENCE` -> "Nessuna nuova conclusione affidabile",
  `NOT_APPLICABLE` -> "Controllo non applicabile") - none of these are ever worded as an error, a
  failure or a technical warning;
- at most ONE synthetic key fact (`lib/decisions/history-key-fact.ts`), built from THAT
  observation's OWN historical `facts` - never the current detail's facts, because the memory has
  to describe what that day genuinely looked like, not what is true today;
- a historical priority rank ("Priorità #3") only when that specific observation was TRIGGERED
  with a real rank - never every score.

Technical audit fields (`observation_id`, `source_evaluation_fingerprint`, `source_target_key`,
`memory_version`, any UUID) are never rendered in the normal timeline UI, even though the typed
client carries them (the API contract requires them) - see "No detail data leak" below.

### Pagination

Cursor-based, exactly as Gate 12 defined it: the first page loads with the initial detail fetch;
when `next_cursor` is non-null, a single "Mostra eventi precedenti" button appends the next page
to the BOTTOM of what is already shown (`setHistoryState` spreads the previous items first) -
never a replacement, never infinite scroll. The button disables itself and shows "Caricamento…"
while a page is in flight; a failed load-more shows a small inline retry without discarding
anything already loaded. The opaque `next_cursor` string is passed back to
`getDecisionHistory(..., { cursor })` verbatim - it is never decoded or constructed client-side.

## Local-date display

Business dates already resolved to a plain `YYYY-MM-DD` (`stay_date`, `work_date`,
`first_seen_local_date`, `as_of_local_date`, ...) are a DIFFERENT problem from Gate 14's
`propertyLocalDate`: there is no "now" or timezone conversion left to do. The classic bug is
`new Date("2026-10-15")` (parsed as UTC midnight) formatted with the HOST's own timezone, which
in a negative-offset host renders as "14 October" - an off-by-one that has nothing to do with the
real business date. `lib/date/local-date.ts::formatLocalDateItalian` never constructs a `Date`
object at all: it parses the three numeric components by hand and looks up the Italian month
name directly, so the same three numbers that came in are the same three numbers rendered.

## No business recalculation

Every value this gate displays is copied, not recomputed: rank, confidence, delta, expected,
priority and the economic proxy all come from the API exactly as given. The only arithmetic in
this gate's own code is Italian-locale ROUNDING for display (`lib/decisions/format.ts`, unchanged
from Gate 14) - never a threshold check, never a re-ranking, never a business decision.

## No recommendation, no AI, no mutation

Every card and every detail page shows problem + evidence, never advice: there is no
"Abbassa il prezzo"/"Riduci il personale" anywhere, checked directly by tests. There is no
acknowledge/dismiss/snooze/assign/resolve action, no notes, no comments, no Ask NINFA, no
AI-generated prose - this gate is entirely a read surface over data Gates 11/12 already produced.

## No detail data leak

`ObservationDetail`'s audit fields (`source_evaluation_fingerprint`, `source_target_key`,
`memory_version`) and every UUID (`observation_id`, `decision_id`, `booking_data_source_id`,
`labor_data_source_id`) exist on the typed client because the API contract requires them, but
normal UI never renders them - confirmed directly by component and golden tests scanning the
rendered output for these values.

## Error handling

- **401** anywhere -> `AuthGate` redirects to `/login`, exactly like `/oggi`.
- **Invalid/foreign/missing property** -> redirected to `/oggi` before any detail/history
  request is ever made (see "Scope & auth") - never a request "as if trusted".
- **404 `DECISION_NOT_FOUND`** (a real bypass, or a decision that stopped existing) -> "Decisione
  non disponibile" / "Questa decisione non è disponibile per la struttura selezionata." with a
  "Torna a Oggi" link - never the decision id, never the raw backend message.
- **Network / 500** (detail) -> "Non siamo riusciti a caricare la decisione." with "Riprova" -
  retries ONLY the detail fetch, never history.
- **Network / 500** (history's first page) -> its own, independent "Riprova" - the detail section
  still renders normally regardless.
- **Load-more failure** -> a small inline retry; every observation already shown stays visible.

## Responsive / accessibility

Content width is capped (~760px) rather than using the full viewport - this is a document to
read, not a dashboard. Verified by hand at 1440×900/1024×768/390×844 (no browser-automation tool
exists in this repository, and Playwright is deliberately not added just for this gate); the
evidence grid collapses to one column and the timeline stays a single column under 480px, with
no horizontal overflow. Every interactive element is a real `<a>`/`<button>` (a Gate 14
`DecisionCard` becomes a real `next/link` when it needs to navigate - never a `div onClick`);
focus is always visible; headings follow a real `h1`/`h2` hierarchy; loading/error regions use
`aria-live`/`role="alert"`; no state is colour-only.

## Limitations (intentional, documented debt)

- No Decision write actions of any kind (acknowledge/dismiss/snooze/assign/resolve/reopen).
- No Recommendation layer, no Ask NINFA, no AI-generated prose - explicitly out of scope, see ADR
  0021, "future recommendation/Ask integration".
- No dedicated E2E/browser-automation suite - visual acceptance at the three target viewports is
  a manual checklist plus component/CSS-level tests, same as Gate 14.
- No real-time updates: the detail/history pages reflect whatever was true at the moment they
  were fetched, refreshed only by a full reload or a new navigation.

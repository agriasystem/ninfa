# Home UI V1 (`home-ui-v1`)

The decision-first Home, "Oggi". It replaces Gate 14's feed-as-a-page with the approved concept
(`docs/ui/references/home-v1/home-light.png.png`) while changing **nothing** about what the product
decides: the Home only presents what the Decision Engine already produced. See
[ADR 0027](adr/0027-home-ui-v1.md) for the "why" behind each choice and
[ask-mia-home-v1.md](ask-mia-home-v1.md) for the Home's assistant.

    ENGINE CALCULATES. MIA EXPLAINS.

The message the screen must give at a glance: *the user does not need to read the data - NINFA says
what deserves attention.* Light theme only (no dark mode, no `prefers-color-scheme`, no theme
toggle; `color-scheme: light` is declared). The reference screenshot's strings ("Hotel Villa Aurora",
"Luca", "3 decisioni", "09:31", "2 attenzioni", the hero sentence) are **examples only** - every one
of them is runtime data, and the tests assert none of them is hardcoded.

## Routes

| Route | What it is |
| --- | --- |
| `/oggi` | the Home (this document) |
| `/decisioni` | **today's** actionable decisions: the same feed the Home counts from (below) |
| `/oggi/decisioni/{id}` | the existing Decision Detail (unchanged URL; sidebar highlights "Decisioni") |

`Dati`, `Struttura` and `Impostazioni` do not exist yet: they are drawn in the approved layout with
a discreet "In arrivo", **never as links** (no `href`, `aria-disabled="true"`, not focusable) - no
page was invented for them.

## App shell

`components/app-shell.tsx` is now a sidebar (~240 px) + content frame (it replaced Gate 14's topbar;
the Decision Detail uses the same shell, with "Decisioni" active):

- **Sidebar:** logo slot, Oggi / Decisioni / Dati / Struttura, then profile | divider | settings.
- **Profile** is a real disclosure: display name (when present), e-mail, and "Esci" - the same
  `logout()` Gate 14 wired. Escape and a click outside close it; Esc returns focus to the avatar.
- **Property header** (top-right of the content): the real property name and today's date in the
  property's own timezone ("8 ottobre 2026", `formatPropertyLocalDateLongItalian`). One property:
  static text, no fake chevron. Several: the existing native `PropertySelector`, styled as the name.
  Zero: no header, and the empty state still renders.
- **Skip link** to `#main-content`, `<nav aria-label>`, `aria-current="page"`.
- **Logo slot:** the small logo is shown from the start on every page except the Home, where it stays
  empty (its box is kept) until the logo transition lands in it.

`components/property-screen.tsx` is the frame the Home and `/decisioni` share (auth gate, property
resolution 0/1/N, shell).

## The Home, state by state

`feed_state` decides the branch, exactly as before - the four states stay mutually exclusive and
"Tutto sotto controllo" can only ever come from `NO_ACTION_REQUIRED` (Gate 14). Gate 24's
`NOT_PROCESSED` wording is preserved.

| `feed_state` | Hero (`<h1>`) | Under it |
| --- | --- | --- |
| `ACTION_REQUIRED` | the **first** item of the feed, as a sentence (below) | "N decisioni richiedono attenzione →" + freshness + area strip |
| `NO_ACTION_REQUIRED` | "Tutto sotto controllo" + the existing body | freshness + area strip; the Gate 22 coverage note ("Non analizzati: ...") |
| `DATA_QUALITY_LIMITED` | "Analisi parziale" + the existing body and counts | freshness + area strip (prudent, below) |
| `NOT_PROCESSED` | "Analisi non ancora disponibile" (never analysed / last successful analysis) | **no** freshness, **no** area strip |

Loading is a skeleton (with a visually hidden `<h1>Oggi</h1>`, the logo and Mia already present);
error is the existing copy + "Riprova". Gate 14's refresh stays, as a discreet icon button next to
the freshness line (`aria-label="Aggiorna analisi"`): it repeats the same `GET`, and the content
stays on screen while it runs (a refresh never swaps the page for a skeleton under the user's focus).

### Hero sentence

`lib/home/hero-copy.ts`: an exhaustive `Record<DecisionType, ...>` of typed fragments
(`plain` / `strong` / `accent` - never an HTML string):

| Type | Sentence |
| --- | --- |
| `REV_PICKUP_LOW` | Le **prenotazioni** per il **{stay_date}** stanno arrivando *sotto il ritmo atteso.* |
| `REV_OCCUPANCY_RISK` | L'**occupazione prevista** per il **{stay_date}** è *sotto il livello atteso.* |
| `REV_OTA_DEPENDENCY` | La **quota di prenotazioni da OTA** è *sopra il livello atteso.* |
| `COST_CPOR_ANOMALY` | Il **costo per camera** è *sopra il livello atteso.* |
| `LABOR_OVERSTAFFING` | Le **ore di personale** programmate sono *sopra il livello atteso.* |

No horizon the data does not support is ever claimed: the reference's "dei prossimi 14 giorni" is
not a field of any Decision (a pickup concerns **one** stay date; `window_days` is the 7-day
measurement window). Cost/Labor sentences do not name the category (the API carries it as a raw
enum value, which is never shown). No recommendation language.

The feed is already ordered `priority_rank ASC`; the Home uses `items[0]` and **never re-sorts**.

### Decision count

`decisionCountOf(feed)` = `feed.items.length` for `ACTION_REQUIRED`, else 0 - **not** the five that
`DecisionList` shows. `items` only ever holds triggered observations (resolved / not applicable /
insufficient / suppressed are never in it), so no client-side filtering exists. "1 decisione
richiede attenzione" / "N decisioni richiedono attenzione"; 0 renders no link. The link goes to
`/decisioni?property=<id>`, which lists **every** one of those decisions (`DecisionList showAll`),
in backend order, each linking to the existing Decision Detail - so the number clicked and the list
landed on cannot disagree.

### Freshness (Gate 23B, unchanged semantics)

`lib/home/freshness.ts`, from `feed.input_freshness.bookings`: a plain **fact** about when NINFA
finished the last booking import, in the **property's** timezone:

- same business day as the feed (`feed.as_of_local_date`) -> "Ultimo import prenotazioni: oggi alle 09:31"
- the day before -> "... ieri alle 22:15"
- older -> the existing date+time formatter
- `UNKNOWN` / no timestamp / unparseable -> "Ultimo import prenotazioni non disponibile" (no time invented)

Never "Dati aggiornati alle ...", never CURRENT/STALE, and the dot is **neutral** (never green).
`NOT_PROCESSED` shows no freshness at all.

### Area strip

`lib/home/domain-summary.ts`: Ricavi / Distribuzione / Costi / Personale, from
`analysis_coverage.domains` + the feed items. The `decision_type -> domain` map is an exhaustive
`Record` (`REV_PICKUP_LOW`, `REV_OCCUPANCY_RISK` -> Ricavi; `REV_OTA_DEPENDENCY` -> Distribuzione;
`COST_CPOR_ANOMALY` -> Costi; `LABOR_OVERSTAFFING` -> Personale), mirroring `decisions/coverage.py`.

| Situation | Text |
| --- | --- |
| at least one decision in the domain | "1 attenzione" / "N attenzioni" |
| `SKIPPED` | "Non analizzati" (Ricavi, Costi), "Non analizzata" (Distribuzione), "Non analizzato" (Personale) |
| evaluated, nothing triggered | "Nessuna attenzione" |
| evaluated, nothing triggered, **run is `DATA_QUALITY_LIMITED`** | "Analisi parziale" (the run's insufficient counts are domain-blind, so a reassuring line would be unsafe) |
| coverage `UNKNOWN` | "Non disponibile" |
| `NOT_PROCESSED` | the strip is hidden |

The backend exposes no severity, so none is invented: **one** attention colour, grey/hollow for
"not analysed/available" - and every state is also written in words. Tiles are plain text (no
per-area destination exists). The user-facing name of the distribution domain is now
"Distribuzione" (it was "Canali").

### Greeting

`session.user.display_name`: trim -> first whitespace token -> "Ciao {token},"; null/blank ->
"Ciao,". Never derived from the e-mail. (No given/family name split exists, so "Rossi Mario" would
greet "Rossi"; the pilot onboarding asks for "Nome Cognome".)

## Mia on the Home

The bar, the four suggested questions and the answer surface are `components/mia-home.tsx`; the
backend is described in [ask-mia-home-v1.md](ask-mia-home-v1.md).

- **Send experience** (like a modern assistant): Enter or the arrow acquires the text as the submitted
  question, **empties the input immediately** (the placeholder "Chiedi a Mia..." is back), shows the
  question above the bar as the user's own message, and starts the request. Under it, Mia's reply
  appears: a discreet "Mia sta elaborando…" (with three quiet dots) while the request runs, then the
  answer. The message never stays in the bar. The former "LA TUA DOMANDA" / "Risposta di Mia" card is
  gone.
- **The user's message** is right-aligned, softly tinted, readable width, Poppins - not a boxed form
  summary and not a chat bubble list. **Mia's reply** is open text under a small "Mia" label with the
  NINFA mark (an `<h2>`, small), no card; limitations, when present, stay as a small muted list.
- **A short conversation, still not a chat page (Mia V2, ADR 0029).** The newest **4 exchanges** of
  the page session (the one being asked included) stay visible in a **bounded, labelled area above the
  bar** (`max-height: min(42vh, 400px)`, it scrolls inside itself - the operational Home is never
  pushed away; the newest exchange starts at its top). They are also sent back as `history`
  (complete earlier exchanges only, at most 3 from the UI) so a follow-up ("Perché?") can be
  understood; a failed, refused or unavailable exchange is not part of it. Nothing is persisted: it is
  lost on reload, on "Nuova conversazione" (disabled while Mia answers) or when the property / business
  date changes (a late answer of the old one is ignored). Only the newest reply is the polite live
  region.
- **One request in flight**, enforced synchronously (a ref, not only state). While Mia answers, the
  input stays **enabled and focused** - focus is never taken from the user and a draft of the next
  question can be typed - but sending is blocked: the arrow turns into a disabled spinner
  (`aria-label="Mia sta elaborando…"`) and the form is `aria-busy`. When the answer arrives sending is
  available again. After a click on the arrow, or on "Riprova", the focus stays in (or returns to) the input.
- **The composer** is an auto-growing `<textarea>` (1 to 4 lines, then it scrolls inside itself).
  **Enter sends, Shift+Enter inserts a new line**; Enter during IME composition never sends. Empty /
  whitespace-only never sends and shows no arrow. The arrow and the search icon stay on the last line.
- **The suggested questions only fill** the input; the user confirms with Enter/the arrow, which then
  behaves exactly as for typed text.
- **Every status renders in Mia's reply, under the sent question, which stays visible**: `ANSWERED`,
  `INSUFFICIENT_CONTEXT`, `UNAVAILABLE` (+ "Riprova"), `REFUSED`, network error (+ "Riprova"). A retry
  **re-sends the submitted question with its original history** (no retyping) and never touches a
  draft in the bar.
- **Rich answers** (`ask-mia-home-v2`): the answer is plain text with line structure, rendered as short
  paragraphs and, for lines starting with `- `, a real bulleted list (`lib/ask-ninfa/format-answer.ts`).
  Nothing is interpreted as Markdown or HTML and no word is dropped. An `INSUFFICIENT_CONTEXT` reply
  that carries Mia's own explanation shows it alone (with her specific limits under "Da tenere
  presente"); the generic "Mia non ha abbastanza informazioni..." lead and its "riformula" hint appear
  only when the reply has no text at all.
- **Accessibility:** Mia's reply region is the polite live region (`aria-live="polite"`), so loading and
  the answer are announced without re-reading the Home or the question; the question carries a
  visually hidden "Hai chiesto:" for screen readers; errors keep `role="alert"`.
- **Layout:** the reply sits immediately above the bar inside a sticky "dock" (so the bar is never
  pushed off a short screen), on a feathered blurred backdrop so a scrolled-under Home never shows
  through Mia's text. While an exchange is open the suggested questions step aside and the hero
  tightens a little (spacing and the headline size animate - no jump). The new exchange enters with a
  ~180-200 ms fade + 6 px translate (none under `prefers-reduced-motion`; no bounce, no dependency).
- There is **no microphone**: no voice feature exists, so no inert control is drawn.
- Placement of the suggestions follows the screen: where the whole Home fits (>= 881 px tall and > 1100 px wide - the
  reference desktop) the suggestions are visible at rest as in the reference; on shorter/narrower
  screens they appear as a panel above the bar when the user interacts with it (and step aside once
  there is text or an answer). While a question or answer is on screen the suggestions are hidden.
- The visible assistant is **Mia** everywhere (Decision Detail included); NINFA is the product.
  Module/endpoint/class names are unchanged.

## Logo transition

Hero logo (DOM) -> temporary canvas trail -> small logo in the sidebar slot. Zero dependencies.

- **Trigger:** the first real (non-whitespace) character typed or pasted into the Mia input - or a
  suggested question filling it. **Never** focus, never whitespace. It runs exactly once per Home
  mount (`idle -> morphing -> settled`); clearing the input never reverses it.
- **Algorithm:** ported from the approved prototype (`logo-animation.zip`): the same cubic path,
  per-particle release/lag/lateral spread, ribbon and landing bloom - but with real geometry
  (`getBoundingClientRect()` of the hero logo and the slot, no fixed 1672x941 coordinates),
  particles **sampled from the official brand PNG** (so their colours are the logo's own), no
  traced SVG, no design-tool scaffolding, and without the prototype's busier extras (triangular
  fragments). ~450 particles, ~1 s, `requestAnimationFrame`, DPR capped at 2.
- **Canvas:** `position: fixed`, `pointer-events: none`, `aria-hidden`, mounted only while the
  trail runs and torn down in the effect cleanup (`cancelAnimationFrame`) - StrictMode-safe.
- **No duplicate logo:** the hero logo fades out (through the element, per frame) while the particles
  carry it away; the small one is revealed on arrival (80 %); then the hero logo is removed and its
  room closes smoothly.
- **Fallbacks:** `prefers-reduced-motion` -> no canvas, an immediate swap; viewport < 768 px, no 2D
  context, or a logo that cannot be sampled -> a ~150 ms fade.
- The logo is the official PNG (`public/brand/ninfa-logo.png`); a brand-exact SVG is deferred.

## Typography and theme

Poppins (300/400/500/600, Latin subset) is **self-hosted** through `next/font/local` (`app/fonts/`,
OFL): no `<link>` to Google Fonts, no font request to a third party at runtime or build time. It is
applied app-wide (`--font-sans`), so the login page and the Decision Detail changed look, not
behaviour. Home tokens (`--home-*`) were sampled from the approved reference; text tones were nudged
where needed to keep >= 4.5:1 on white. The lower blue/violet glow is static CSS (gradients + a
masked arc), `aria-hidden`, fixed to the bottom of the viewport.

## No graphs

Gate 14's "no `<svg>`/`<canvas>`" rule was about **analytical graphs**, and that rule stands: the
Home and `/decisioni` show **zero charts**; the area strip is textual. What is now allowed, as
*presentation only*: the icon set (`components/icons.tsx`, all `aria-hidden`), the logo, and the
temporary canvas motion above. The existing "no svg/canvas" tests on decision cards, the feed
states, the Decision Detail and Ask panel are unchanged (they render content, not the shell).

## Responsive

Desktop (>= 1280 px) is the source of truth (1672x941 reference): sidebar 240 px. Laptop (< 1280):
216 px, tighter spacing; area strip 2x2 below 1200 px. Tablet (< 1024): compact icon rail (labels
stay in the accessibility tree, visually hidden). Mobile (< 640): the sidebar becomes a top bar;
the Mia bar is a sticky composer. Never a pixel-scaled copy of the desktop.

## Accessibility

Skip link, `<nav aria-label>`, `aria-current`, a real `<h1>` (the hero), real `<a>`/`<button>`
controls, `:focus-visible` ring (and a ring on the Mia bar via `:focus-within`), >= 44 px targets on
the controls, labelled Mia form (the placeholder is not the label), `aria-disabled` future
sections, keyboard-operable profile disclosure, canvas `aria-hidden`, reduced-motion fallback, no
information conveyed by colour alone.

## Files

`components/{app-shell,app-sidebar,profile-menu,property-header,property-screen,home-screen,
domain-summary,mia-home,logo-trail-canvas,decisioni-screen,refresh-button,ninfa-logo,icons,
shell-logo-context}.tsx`, `lib/home/*`, `lib/motion/*`, `lib/feed/use-decision-feed.ts`,
`lib/ask-ninfa/{copy,state}.ts`, `app/decisioni/page.tsx`, `app/fonts/`, `public/brand/`.

## Explicitly deferred

Dark mode; Dati / Struttura / Impostazioni pages; per-area clickable tiles and any per-area
severity; the Decision memory list (`GET /decisions`) as a page; a per-area breakdown of
insufficient checks; a given-name field; a brand-exact SVG logo; voice input; charts.

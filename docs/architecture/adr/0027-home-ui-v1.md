# 0027 — Home UI V1: a decision-first Home that presents, never decides

## Context

Gate 14's "Oggi" rendered the decision feed as a page inside a topbar shell. The approved concept
(`docs/ui/references/home-v1/`) is a different product experience: a sidebar shell, a central hero
that says what deserves attention, a status line, a four-area strip and an assistant bar. The
backend and every decision it makes already exist; this ADR records how the UI presents them without
adding a single judgement of its own.

## Decision

1. **The Home presents, it does not decide.** Which branch renders is `feed_state`, exactly as Gate
   14 defined it; the hero is `items[0]` of an already-ordered feed (never re-sorted); the count is
   `items.length`; the area strip is a grouping of `decision_type` by the same domains the backend
   documents in `decisions/coverage.py` (an exhaustive `Record`, so a sixth type fails to compile).
   There is no detection, ranking, thresholding or reinterpretation in the frontend.

2. **Gate 14/22/23B/24 semantics are preserved, not re-derived.** "Tutto sotto controllo" only for
   `NO_ACTION_REQUIRED`; "Analisi parziale" for `DATA_QUALITY_LIMITED`; never-analysed vs last
   successful analysis for `NOT_PROCESSED` (no freshness, no area strip there); coverage is never
   inferred (`UNKNOWN` -> "Non disponibile"); refresh stays available.

3. **Hero copy is typed fragments over real fields, never the screenshot's sentence.** The reference
   says "dei prossimi 14 giorni"; no Decision carries that horizon (a pickup concerns one stay date,
   `window_days` is the 7-day measurement window), so the sentence names the stay date instead.
   Cost/Labor sentences omit the category (an API raw enum). No recommendation language.

4. **Freshness stays a fact (supersedes the concept's "Dati aggiornati alle 09:31").** `finished_at`
   proves when NINFA finished an import, not that the data is current (ADR for Gate 23B). The line is
   "Ultimo import prenotazioni: oggi/ieri alle HH:MM" in the property's timezone, UNKNOWN is neutral,
   and the dot is neutral - never green.

5. **No invented severity.** The reference colours Ricavi red and Distribuzione orange; the backend
   exposes no severity, and a frontend threshold would be a new judgement. One attention colour; grey
   or hollow for "not analysed / not available"; every state also in words.

6. **In a data-quality-limited run an evaluated area reads "Analisi parziale", never "Nessuna
   attenzione".** The run's insufficient counts are domain-blind (Gate 22A); a reassuring per-area
   line would err on the unsafe side, while "partial" errs on the prudent one.

7. **`/decisioni` is today's feed, every decision.** The Home's "N decisioni richiedono attenzione"
   must land on exactly N cards, so the page reuses `getDecisionFeed` / `DecisionList` / `DecisionCard`
   with the top-5 cap lifted. The Decision memory (`GET /decisions`) stays deferred.

8. **Sections that do not exist are drawn, never linked.** Dati, Struttura and Impostazioni appear in
   the approved layout with "In arrivo": no `href`, `aria-disabled`, not focusable. No page was
   invented.

9. **The assistant is called Mia in the UI; NINFA is the product.** This supersedes Gate 20's "no
   persona name beyond NINFA". Only user-facing copy changed (`Chiedi a Mia`, the refusal copy, one
   persona line of the Decision Ask instructions, v1.3); endpoints, modules and classes keep their
   names.

10. **Logo and font.** The official brand asset is the reference package's PNG, copied unchanged
    (a brand-exact SVG is deferred; the prototype's traced SVG is never the logo). Poppins is
    self-hosted via `next/font/local` - no Google Fonts `<link>`, no third-party request.

11. **The logo transition is presentation, built from real geometry.** Hero logo (DOM) -> one
    temporary, `aria-hidden` canvas trail -> small logo (DOM), triggered by the first real
    character, run once, torn down on cleanup, replaced by a fade for reduced motion / small
    viewports / an unavailable canvas. Particles are sampled from the brand PNG; nothing from the
    design tool's scaffolding is shipped.

12. **"No graphs" is clarified, not relaxed.** The Home shows zero analytical charts. Icons, the logo
    and the temporary canvas motion are presentation and are allowed in the shell and the Home; the
    existing tests that forbid `svg`/`canvas` in decision cards, feed states, the Decision Detail and
    the Ask panel are unchanged, because they render content, not the shell.

13. **Light only.** No dark tokens, no `prefers-color-scheme`, no theme switch; `color-scheme: light`.
    The dark Mia bar of the reference is a light-theme component, not a dark mode.

## Consequences

- No backend change was needed for the Home itself; the one backend addition of this gate is Mia
  Home ([ADR 0028](0028-mia-home-context.md)).
- A given-name field, per-area breakdown of insufficient checks, per-area severity and a clickable
  strip would each need new backend data and are deferred.
- The existing card still shows `cost_category`/`labor_category` as raw enum values (Gate 15
  behaviour, asserted by the golden tests); the Home never uses them, and fixing the card is a
  separate piece of work.

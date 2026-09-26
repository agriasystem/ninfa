# 0020 — Oggi UI V1: authenticated shell and a single, non-negotiable Decision Home

## Context

Gate 13 (ADR 0019) made `get_current_principal` real. Gate 12 (ADR 0018) already exposed a
read-only, four-state Decision Feed behind it. Nothing in the product was visible to an actual
user until now - Gate 14 is the first gate whose output is a page someone looks at.

## Decision

1. **"Oggi" is the first Home, not a dashboard.** The question NINFA answers first is "what
   deserves my attention today" - a single, ranked, time-bound answer - not "explore your data".
   A BI-style dashboard would ask the user to interpret the product; "Oggi" asks the product to
   answer the user. Every other planned surface (Analytics, Revenue, Costi, Personale, ...) is
   deliberately absent rather than stubbed - a placeholder link would claim a feature exists that
   does not.

2. **Zero graphs, by design, not by omission.** A chart requires the reader to do the pattern-
   recognition NINFA itself already did in Gates 5-10 (baseline, confidence, priority). Showing
   one here would silently shift the burden of judgement back onto the user and re-introduce the
   "BI tool" positioning the product explicitly avoids in V1.

3. **Maximum 5 decision cards presented, all triggered candidates still returned by the API.**
   Gate 12's contract already returns every triggered `DecisionObservation` - Gate 14 changes
   nothing server-side about that. The UI slices for presentation only (`items.slice(0, 5)`)
   because an unranked or unbounded list defeats the point of a prioritised Home: if everything
   is shown, nothing is highlighted. A future gate can raise this or add a "see all" page; this
   gate does not need to solve that yet.

4. **Ranking happens in the backend, never in the frontend.** `priority_rank` is the output of
   Gate 10's own weighted formula, computed once, persisted, and returned in that exact order.
   Recomputing or re-sorting it in the browser would mean two independent implementations of the
   same ranking that can silently drift; the frontend renders the array it is given, in that
   order, full stop.

5. **"Today" is resolved in the property's own timezone, not the browser's.** A property in
   Sicily and a property in Honolulu do not share a calendar day at the same UTC instant, and
   `as_of` (Gate 12) is a hard, mandatory, non-defaulted contract field precisely so a client
   cannot silently pass the wrong date. `Property.timezone` already existed (Gate 1); exposing it
   on the Session Context (additive, no migration) was the only real gap.

6. **The four feed states stay visually and semantically distinct, always.** `NOT_PROCESSED`,
   `DATA_QUALITY_LIMITED`, `NO_ACTION_REQUIRED` and `ACTION_REQUIRED` encode four different real
   situations Gate 12 already worked out how to tell apart (see `decision-api-v1.md`, "Feed
   states"); collapsing any two of them into similar-looking UI would throw that distinction away
   at the one point where a human actually reads it.

7. **`NO_ACTION_REQUIRED` is the only state that may say "Tutto sotto controllo".** "Not processed
   yet" and "processed but some checks lack data" are NOT "all clear" - they are, respectively,
   "no answer yet" and "a partial, honest answer". Reusing reassuring copy for either would tell
   the user something false about the confidence NINFA actually has.

8. **Static copy per `decision_type`, never AI-generated text.** A fixed Italian title
   (`lib/copy.ts::decisionTypeTitles`) is exactly as informative every time, auditable in a
   single file, and carries zero risk of a language model inventing a plausible-sounding but
   wrong sentence about a real financial anomaly. Gate 14 introduces no LLM dependency anywhere.

9. **Problem + evidence, never a recommendation.** NINFA has not built pricing, staffing or
   procurement logic - "Abbassa il prezzo" or "Riduci il personale" would be advice the product
   has no basis to give yet. The card shows what the detector found and why it trusts it; deciding
   what to do about it stays a human decision.

10. **No fake navigation to a feature that does not exist.** A visible-but-inert menu item is a
    broken promise the moment it is clicked. The shell only ever links to what is real: the
    property selector and logout.

11. **The session cookie is never read by JavaScript.** It is `HttpOnly` by construction (Gate
    13); no line of Gate 14 code references its value, stores a copy in `localStorage`/
    `sessionStorage`, or invents an `Authorization`/`X-User-Id` header. `credentials: "include"`
    is the only mechanism that ever attaches it, on every request, centrally
    (`lib/api/client.ts`).

12. **No global state management library.** `React.Context` (`lib/session/session-context.tsx`)
    plus each component's own local state is sufficient for "am I logged in, what did the feed
    just return" - the two pieces of shared state this gate actually has. Redux/Zustand/MobX/
    TanStack Query would all solve a scaling problem this Home does not have yet, at the cost of
    a new dependency and a new pattern to learn.

13. **One centralised, typed API client.** `lib/api/client.ts` is the single place that knows
    about `credentials: "include"`, `cache: "no-store"`, the Gate 12/13 error envelope, and the
    base URL - so those four properties cannot silently diverge between call sites the way they
    would if every component called `fetch()` on its own.

14. **No Decision Detail page in this gate.** A card links nowhere (spec-level constraint): the
    Decision Detail/History endpoints (Gate 12) already exist and are unaffected, but building
    their UI is real, separate scope this gate does not need to absorb to answer "what deserves my
    attention today".

15. **Responsive and accessible by construction, not by a later pass.** Layout is verified by
    hand at 1440×900/1024×768/390×844 (see `oggi-ui-v1.md`, "Responsive/accessibility" - no
    browser-automation tool exists in this repository, and Playwright is deliberately not added
    just for this gate); every input has a real label, focus is always visible, the property
    selector is a native keyboard-operable `<select>`, and no state is colour-only.

16. **Everything this gate defers is written down, not silently missing.** Signup, password
    reset, OAuth/MFA (Gate 13's own debt, unchanged), Decision Detail, "Ask NINFA", any AI-
    generated content, and a real i18n framework are all explicitly out of scope - see
    `oggi-ui-v1.md`, "Limitations".

## Alternatives considered

- **A BI-style dashboard grid (multiple widgets/charts on one screen).** Rejected outright by the
  product's own stated positioning ("NOT a BI dashboard") - would require the user to synthesise
  what NINFA's own priority engine already synthesised.
- **Recomputing rank/confidence client-side from raw facts, for a "richer" UI.** Rejected: it
  would duplicate Gate 10's formula in a second language with no test parity guarantee, and the
  facts contract is explicitly whitelisted, not a general-purpose analytics feed.
- **A global state library (Redux/Zustand/TanStack Query) for session + feed state.** Rejected as
  premature: two independent pieces of shared state do not need a library built for many.
- **Showing ALL triggered decisions with pagination instead of a top-5 cutoff.** Rejected for V1:
  a prioritised "Home" that shows everything is not prioritised; pagination/full-list browsing is
  a legitimate future page, not this one.
- **JWT/localStorage-based auth state instead of the existing HttpOnly cookie.** Rejected: Gate 13
  already made the opaque, server-revocable cookie session the real mechanism; introducing a
  second, client-readable credential would both duplicate and weaken it.

## Consequences

- The Home is intentionally narrow: one property, one day, at most five decisions, zero charts.
  Expanding it (more cards, a detail page, real-time updates) is explicitly future work, not a
  gap to patch reactively.
- `Property.timezone` is now part of the public Session Context contract; any future change to
  how a property's timezone is stored or computed must keep this field meaningful.
- The CORS configuration now allows credentials for the configured web origin(s) - production
  deployment must keep `CORS_ORIGINS` to the real web origin(s) only, and keep the web app and
  API same-site (`SameSite=Lax`, per ADR 0019) rather than relying on this CORS change to make a
  cross-site deployment safe.
- Every new decision card type added in a future gate must go through the same explicit adapter +
  static-title pattern (`lib/decisions/card-view-models.ts`, `lib/copy.ts`) - there is no generic
  "render whatever facts came back" path to fall back to, by design.

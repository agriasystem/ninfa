# 0021 — Decision Detail UI V1: evidence and memory, never advice

## Context

Gate 14 (ADR 0020) shipped "Oggi", a ranked list of at most five decision cards answering "what
deserves my attention today". Every card in that list was, until now, a dead end: it named a
problem but gave no way to see why NINFA trusts it, or whether it is new. Gate 12 already exposed
the Decision Detail and Decision History endpoints over Gate 11's own persisted lifecycle; this
gate is the first UI to read them.

## Decision

1. **The detail page exists to answer two specific questions, nothing broader.** "Why does this
   deserve attention" and "how has it evolved" - not a general-purpose Decision browser, not an
   audit log, not a BI drill-down. Every section on the page traces back to one of those two
   questions.

2. **Evidence before recommendation, structurally, not just by convention.** This gate has no
   code path that could show a recommendation even by accident: the facts adapters
   (`lib/decisions/card-view-models.ts`) only ever expose the whitelisted numeric facts, and the
   "why" sentence (`lib/decisions/why-copy.ts`) is built from those same fields with fixed,
   pre-written templates - there is no prose-generation step anywhere a recommendation could be
   smuggled into.

3. **The Decision's lifecycle is shown, deliberately, not hidden behind a single status word.**
   "Aperta"/"Risolta" alone would answer "is this still a problem" but not "since when" or "how
   many times" - `first_seen_local_date`, `resolved_local_date` and `episode_count` are all
   real, already-persisted facts (Gate 11), and hiding them would make a RESOLVED decision look
   like it never happened, which defeats the entire point of Gate 11's own immutable memory.

4. **History is newest-first because that is what the backend already decided, and a UI has no
   business re-deciding it.** `DecisionRepository.history_page_desc()` (Gate 12) already orders
   by recency for exactly the reason a human wants to see the LATEST development first; re-
   sorting client-side would only risk disagreeing with a page boundary the backend already drew.

5. **No technical audit id is ever rendered in the normal UI.** `observation_id`,
   `source_evaluation_fingerprint`, `source_target_key`, `memory_version`, and every
   `*_data_source_id` exist on the typed client because the API contract carries them (Gate 12's
   own `ObservationDetail`/target DTOs), but they identify ROWS, not the business situation - a
   user reading about a pickup shortfall has no use for a UUID, and showing one would make the
   page read like a database dump instead of an explanation.

6. **No value shown here is ever recomputed.** Rank, confidence, delta, expected and the economic
   proxy are copied from the API exactly as given, in every section (current snapshot AND
   history) - the same discipline Gate 14 already established, extended to a page with
   MORE numbers on it, not relaxed because there are more of them.

7. **Zero graphs**, for the same reason Gate 14 has none: a chart asks the reader to do pattern
   recognition NINFA's own detectors already did. A vertical, dated list of short sentences
   ("Ancora presente", "Rilevata") does the same communicative job as a status-over-time chart,
   without asking the user to read an axis.

8. **No AI prose, anywhere, including the "why" sentence.** It reads like a generated sentence
   because it is grammatically complete Italian, but it is a `switch` over a closed enum of five
   decision types, filling in a fixed template with real numbers - the exact opposite of what an
   LLM call would give: deterministic, auditable, and impossible to hallucinate a fact into.

9. **No mutation control of any kind.** No acknowledge, dismiss, snooze, assign, resolve-by-hand
   or reopen-by-hand button exists. This gate reads Gate 11's lifecycle; it does not get to change
   it - a Decision's status changes only through a real detector evaluation via
   `DecisionService.sync()`, never through a click in this UI.

10. **Cursor-based "load more", never infinite scroll, never a full second fetch of everything
    already shown.** Gate 12's own `next_cursor` contract already solves "give me the next page
    without re-deciding pagination logic" - `getDecisionHistory(..., { cursor })` passes it back
    verbatim. Appending (not replacing) is the only operation that keeps a user's place in a
    potentially long history.

11. **Every historical fact comes from ITS OWN observation, never from the current detail.** The
    whole point of "Evoluzione" is to show what NINFA believed on a PAST day - if the timeline
    borrowed today's numbers to describe last month's observation, the memory would be
    retroactively rewritten, exactly the failure mode Gate 11's immutability guarantee exists to
    prevent. `cardViewModelFromTargetAndFacts(target, observation.facts)` is called once per
    timeline entry, with THAT entry's own `facts`.

12. **`propertyId` is part of the route (as a query parameter), because the backend's own
    endpoint needs it and a client should never have to guess it from other state.** A decision
    detail link is shareable/bookmarkable and self-describing about which property it belongs
    to, without depending on whatever the shell's selector happened to be showing at click time.

13. **The route is validated both client-side and server-side, because neither alone is
    sufficient.** Client-side validation (`resolveSelectedProperty` against the real
    `SessionContext`) exists so the UI never even asks the API a question it already knows the
    answer to ("does this user have this property") - it is a UX/defence-in-depth measure, not
    the actual security boundary. `resolve_property_scope` + `_decision_in_scope` (Gate 12) is,
    and remains, the only real authorization barrier: a bypassed/forged request still gets
    exactly the same `404` a legitimate one would for a foreign decision.

14. **One static, hand-audited mapper per decision type, reused everywhere, never a generic
    "dump the facts" fallback.** Gate 14 already built and tested this mapper
    (`cardViewModelFromTargetAndFacts`); this gate extends its OUTPUT shape (two fields:
    `windowDays` on Pickup, `deltaPercent` on Cost) rather than writing a second, parallel
    reader of the same whitelist - there is exactly one place that knows which fact key means
    what, for both the feed card and the detail/history pages.

15. **Responsive and accessible by construction** - see `decision-detail-ui-v1.md`,
    "Responsive/accessibility": a capped reading width, real link/button semantics throughout
    (a card becomes a `next/link`, never a `div onClick`), visible focus, a real heading
    hierarchy, and `aria-live`/`role="alert"` on the loading/error regions that can change without
    a click.

16. **A Recommendation layer and Ask NINFA remain explicitly future work, not implied by
    anything built here.** The "why" sentence and the evidence rows are deliberately the CEILING
    of what this gate says about a decision - "here is the problem and why NINFA trusts it" -
    with no code path that edges toward "here is what to do about it". When a Recommendation
    layer is built, it is a NEW section, additive to this page, never a rewording of the
    evidence/why sections that already exist.

## Alternatives considered

- **Putting `propertyId` in the URL path** (`/properties/{propertyId}/decisioni/{decisionId}`),
  as the spec's own default suggestion. Rejected in favour of the query-parameter form already
  established by `/oggi?property=...` - see `decision-detail-ui-v1.md`, "Route", for the full
  reasoning; documented here as an explicit, considered deviation.
- **A single "detail" object combining detail + history in one fetch.** Rejected: Gate 12 already
  ships them as two independent, differently-paginated endpoints, and combining them client-side
  would only reintroduce a coupling the backend deliberately avoided (a history page's cursor has
  nothing to do with the detail's own freshness).
- **Recomputing a "trend" (rank moving up/down over time) from the history.** Rejected as a
  business inference this gate has no authority to make - Gate 10's Priority Engine is the only
  place rank is decided, and a UI-side "is this getting worse" claim would be exactly the kind of
  recalculation ADR 0020 (and this ADR, point 6) already rules out.
- **Infinite scroll for history.** Rejected: an explicit "Mostra eventi precedenti" action keeps
  the page's height predictable and makes a load failure trivially recoverable (retry one click,
  not a silent stuck scroll position).

## Consequences

- Every future decision type added to the Decision API must gain its own adapter in
  `lib/decisions/card-view-models.ts` (facts) and, if it needs one, its own case in
  `lib/decisions/why-copy.ts`/`evidence-rows.ts`/`history-key-fact.ts` - there is no generic
  fallback path a new type could silently fall into.
- A future Recommendation/Ask NINFA layer is additive: it gets its own section and its own
  component, appended to this page, never a modification of the evidence/why sections' own
  wording or scope.
- The `propertyId`-in-query-string convention is now used by two pages (`/oggi`, `/oggi/
  decisioni/{id}`); any future page that also needs a property in scope should follow the same
  pattern rather than introducing a third convention.

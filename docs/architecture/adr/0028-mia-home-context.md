# 0028 — Mia Home: a property-level assistant grounded only in what the engine already decided

## Context

ADR 0024 scoped Ask to **exactly one Decision**. The approved Home asks different questions: "Ci
sono altri problemi oltre a questo?", "Qual è la priorità più urgente oggi?", "Quale decisione ha
l'impatto economico più alto?", "Quali dati ha usato NINFA oggi?". None can be answered from one
Decision's context, and the Decision Ask's prompt forbids exactly what some of them need (a position
in the ranking). A real answer needs a real, bigger context - and it must not turn Mia into an
analyst of raw data.

## Decision

1. **A separate, additive endpoint, not a widened Decision Ask.** `POST /properties/{id}/ask` with an
   explicit `as_of_local_date`. The Decision Ask keeps its route, instructions, context and
   `grounding_refs` vocabulary; a test proves it is unaffected. ADR 0024 §1 ("exactly one Decision")
   still holds for that endpoint; this is its sibling at property scope.

2. **ENGINE CALCULATES. MIA EXPLAINS - structurally.** The context is built *only* from
   `DecisionMemoryService.get_feed()`: the decisions the engine triggered (in its priority order),
   the run's analysis coverage, the booking-import provenance, and the last successful analysis. No
   raw booking/invoice/labour rows, no SQL, no thresholds, no ids. "Other problems" can therefore
   only ever be *other engine decisions*; Mia has no data from which to find a new one.

3. **The instructions forbid the dangerous verbs.** Mia does not discover anomalies, decide whether
   a problem exists, create Decisions, re-rank, size or invent impacts, use outside knowledge about
   the hotel, or call data current/stale/"aggiornati". She may explain the feed's decisions, compare
   them, say which is first in NINFA's order, explain coverage, state the last import as a fact, and
   say the context is not enough.

4. **Priority is spoken in words, never as a number.** The decisions carry an ordinal word ("prima",
   "seconda", ...) in the engine's own order; no rank number or score is in the context, preserving
   ADR 0026's "priority is not verbalised" while still letting "Qual è la priorità più urgente
   oggi?" be answered ("la prima nell'ordine di NINFA").

5. **Economic impact is only what the engine recorded, as an indicative estimate.** Revenue/OTA
   proxies carry no currency (none is invented); cost/labour proxies carry the recorded one. Each is
   labelled "stima indicativa, non un valore certo", is never summed, and is never compared across
   natures (revenue vs cost). Suggested question 3 is therefore worded around *impact*, not "dove
   perdo più valore" (a proxy is not a loss - ADR 0026).

6. **Freshness stays a fact, in property time.** "Ultimo import prenotazioni" with a local date/time
   and "oggi"/"ieri" computed server-side against the business date; unknown never invents a time;
   no CURRENT/STALE judgement (Gate 23B). This lifts Gate 23B's deferral of "Ask NINFA freshness
   context" - as a fact only.

7. **Absence is explicit.** Without a run (`NOT_PROCESSED`) coverage and freshness are `null`
   ("not available"), never "all areas analysed" or a guessed import; the prior analysis date is
   given when it exists. Mia then answers `INSUFFICIENT_CONTEXT` for anything the context cannot
   support.

8. **Reuse, not a second pipeline.** Same provider protocol (no tools, web, streaming or fallback;
   one bounded call), same deterministic guardrails (refusal copy now says "Mia"), same shape /
   length / technical-leak validation (overlong or leaky output **fails closed**, never truncated).
   Two small, backwards-compatible generalisations: the validation core takes the closed
   `grounding_refs` vocabulary as a parameter, and `LanguageModelRequest` carries an optional
   per-request `grounding_ref_values` so the Anthropic adapter builds the right structured-output
   schema without touching the shared Decision Ask schema object.

9. **Plain-Italian JSON keys in the model-facing context** (e.g. "decisioni in ordine di priorità"),
   never snake_case: a model that echoes a key produces natural Italian, and the leak check (which
   fails closed on any snake_case word) has no context-derived reason to fire. Target keys of the
   Decision Ask's builder (`stay_date`, `cost_category`, ...) are renamed to Italian phrases here.

10. **Bounded and honest about size.** At most 10 decisions are in the context, with the total and
    the omitted count stated, so Mia says "ce ne sono altre" instead of implying completeness.

## Consequences

- No migration, no new dependency, no write: the route is read-only despite being a POST.
- The visible assistant is Mia (Decision Detail included); the Decision Ask's instruction version is
  bumped to `ask-ninfa-v1.3` for the persona line only. Rules are unchanged.
- A real-provider acceptance run (and prompt tuning of the Home instructions against live answers)
  is still to be done with a configured provider; the automated suite uses the deterministic fake.

# 0024 — Ask NINFA Core V1: engine calculates, AI explains

## Context

By Gate 17, NINFA could calculate a Decision, show its evidence, remember its history, and
recommend a REVIEW action - all deterministic, all read-only, all explained through fixed, static
copy. What none of it could do was answer a free-form question in the user's own words. This gate
introduces the first place in the codebase a language model is ever called - deliberately narrow,
deliberately provider-agnostic, deliberately not yet connected to a real vendor.

## Decision

1. **Ask is scoped to exactly one Decision, never a general conversation.** *(Home UI V1 added a
   sibling endpoint at property scope - [ADR 0028](0028-mia-home-context.md); this endpoint is
   unchanged.)* The input is
   `property + decision + question`; the output is grounded ONLY in that Decision's own memory. A
   question that needs data outside that scope ("how's the Italian market doing?") has nothing to
   be grounded in, by construction - there is no broader context this endpoint could even offer it.

2. **Not a generic chatbot, structurally, not by prompt alone.** `AskDecisionContextBuilder`'s
   output is the ENTIRE world the model can reference. There is no code path that could hand it
   anything else - no raw booking rows, no other Decision, no property-wide data. A generic
   question is unanswerable not because the model was told to refuse it, but because nothing it
   would need is ever assembled in the first place.

3. **Engine calculates, AI explains - the one non-negotiable principle.** Every number in
   `AskDecisionContext` was already decided by Gates 4-16 (Expected, detectors, Priority, Decision
   Layer, Recommendation). The model recomputes nothing: no delta, no confidence, no rank, no
   economic proxy, no different recommendation. Its only job is turning already-decided facts into
   an Italian sentence a human can read faster than the raw numbers.

4. **Context is explicitly whitelisted, never `asdict()`/`__dict__`/generic serialization.**
   `app.modules.decisions.whitelist` (extracted from the Decision API's own serializers in this
   gate) is the ONE place that decides which `facts_payload`/`evidence_payload` keys are safe to
   leave the Decision Layer's own persistence - the context builder reuses it rather than defining
   a second, ask-ninfa-specific list that could silently drift from the API's own.

5. **No raw operational row ever reaches the model.** `AskDecisionContextBuilder` takes a
   `Decision`, a `DecisionObservation`, a `RecommendationResult` and a bounded history - never a
   `Booking`, an `Invoice`, a `LaborEntry`, or a raw snapshot. This mirrors Gate 16's own input
   boundary for the Recommendation Engine exactly, for the same reason: Decision Memory is already
   the durable, already-decided record; re-deriving from raw rows would risk disagreeing with it.

6. **History is bounded to 10 observations, chronological.** A predictable, small, deterministic
   context shape - the same discipline Gate 16's own `MAX_SUPPORTING_CHECKS` already established
   for a different concern. Chronological (not newest-first) because a model explaining "how has
   this evolved" reads more naturally top-to-bottom, in the order it actually happened, than
   newest-first (which is the right order for a HUMAN scanning a UI list, a different job). No
   recursive AI summarization of anything trimmed away - if it is older than the 10 most recent
   entries, V1 honestly does not carry it into the prompt.

7. **A `Protocol`, never a concrete SDK, is what `AskNinfaService` depends on.** This makes the
   system provider-READY without being provider-LOCKED: swapping in a real vendor later is a new
   implementation of `LanguageModelProvider`, never a change to the service, the route, or any
   test that already exercises the fake.

8. **No vendor was selected in this gate, on purpose.** The prompt for this gate explicitly
   required stopping before choosing one; the only production implementation shipped is
   `UnconfiguredLanguageModelProvider`, which always fails closed. This is not a placeholder with a
   TODO - it is the complete, correct V1 behaviour for "no provider is configured", and it will
   remain correct until a specific vendor is explicitly approved in its own, later gate.

9. **Structured output, not an opaque string.** `{status, answer, grounding_refs, limitations}`
   lets the SERVICE validate what a model actually claims, rather than trusting a wall of text. It
   also gives the model an explicit way to say `INSUFFICIENT_CONTEXT` instead of being tempted to
   fabricate a number just because free text has no format forcing it to admit uncertainty.

10. **No conversation persistence in V1.** No `Conversation` table, no `Message` table - grounding
    and privacy need to be validated at the single-turn level before this gate takes on the
    additional design surface of "what does a thread of context mean, and how much of it is safe to
    keep re-sending to a provider on every turn". Multi-turn is real future work, not implied by
    anything built here, exactly the same posture Gate 15 took toward Recommendation/Ask NINFA
    itself back in ADR 0021.

11. **`POST`, despite mutating no business state.** The endpoint carries a `question` body and
    calls an external provider - both are POST-shaped concerns independent of whether the handler
    writes to the database. It never calls `DecisionService.sync()`, writes no `Decision`/
    `DecisionObservation` row, and creates no conversation row (there is none to create).

12. **No prompt/context/question logging, by omission.** Nothing in `app.modules.ai.*` calls a
    logger with the question or the context at all; a provider exception is caught and converted to
    `AskStatus.UNAVAILABLE` before it could ever reach the generic unhandled-exception logger this
    codebase already has. If operational logging is added later, it is scoped to metadata (request
    id, decision type, provider name, latency, status) - never the prompt body.

13. **The user's question is untrusted input, structurally, not just by prompt instruction.**
    `LanguageModelRequest` keeps `system_instructions`/`context`/`question` as three separate
    fields; nothing in this codebase ever concatenates them into one string. The static
    instructions additionally tell the model to ignore any instruction-shaped text inside the
    context and to never let the question override its own rules - two independent layers, because
    neither one alone is airtight against every possible phrasing.

14. **No autonomous action, anywhere, structurally.** `AskResult`/`LanguageModelAnswer` carry no
    field that could mean "execute this" - there is no `action`/`approved`/`auto_apply` concept
    anywhere in this gate's types. A deterministic guardrail additionally REFUSES an explicit
    execution request before any provider call, so an obviously out-of-bounds question never even
    reaches the model.

15. **An unsupported numeric-optimisation question is `INSUFFICIENT_CONTEXT`, not `REFUSED`.**
    "Di quanto dovrei abbassare il prezzo?" is a legitimate, domain-relevant question NINFA simply
    cannot answer (there is no price-optimisation engine anywhere in this codebase) - refusing it
    outright would conflate "out of bounds" with "out of capability". The distinction matters: a
    refusal implies the question itself was wrong to ask; `INSUFFICIENT_CONTEXT` says the question
    was fine, NINFA just does not have that answer today, and explains what it does know instead.

16. **Future provider/UI/multi-turn path is explicitly staged, never implied by this gate.** A real
    vendor requires its own approval and its own gate. A chat UI is additive to Gate 15's Decision
    Detail page, the same relationship Gate 17's Recommendation panel already has to it. Multi-turn
    conversation, if ever built, designs its own persistence from scratch - this gate's single-turn
    shape does not need to anticipate it.

## Alternatives considered

- **Filling `app/modules/intelligence/ai`/reusing the empty `intelligence/recommendation`-style
  placeholder.** Rejected for the same reason ADR 0022 rejected `intelligence/recommendation` for
  the Recommendation Engine: Ask NINFA's own input boundary (Decision + Observation + Recommendation
  Result) has zero dependency on the detection layer. Unlike that case, though, Gate 0 had already
  reserved a STRUCTURALLY correct pair of placeholders for exactly this concern -
  `app/modules/ai/ask_ninfa` (the domain) and `app/modules/ai/gateway` (the provider boundary) -
  under a dedicated top-level `ai/` namespace, not nested under `intelligence/`. Filling those two
  (unlike Gate 16's decision to bypass its own reserved placeholder) keeps the LLM-touching code in
  the one place the codebase's own Gate-0 planning already set aside for it.
- **A second LLM call to classify the question's intent before answering.** Rejected: it doubles
  cost and latency, adds a second place answers could disagree with each other, and V1's few, clear
  refusal categories (execution, PII, injection) do not need a general intent classifier - a small,
  deterministic keyword guardrail is simpler, faster, fully auditable, and sufficient for what this
  gate actually needs to catch outright, with the structural/instructional layers as backstop for
  what it does not.
- **Reusing `ObservationDetail`/`DecisionDetailResponse` (the public API DTOs) as the model-facing
  context directly.** Rejected: those DTOs still carry audit fields a browser client is allowed to
  see but never renders (`observation_id`, fingerprints, `*_data_source_id` UUIDs) - acceptable for
  a typed HTTP client that simply ignores them, not acceptable to hand directly to a model, whose
  entire faithfulness depends on seeing nothing it does not need.
- **Rejecting an overlong provider answer outright instead of truncating it.** Rejected: a real,
  grounded, otherwise-correct answer that ran a little past the character budget is more useful
  truncated than discarded; `MAX_ANSWER_CHARS = 1200` is enforced by truncation with a trailing
  ellipsis, a documented, testable policy rather than a silent full rejection.
- **A closed TypeScript-style union for `grounding_refs`/`status` at the PROVIDER boundary
  (`LanguageModelAnswer`).** Rejected there specifically (though used for the DOMAIN's own
  `GroundingRef`/`AskStatus`): the provider adapter cannot know about every future frontend-facing
  enum value, so its own wire shape stays a plain `tuple[str, ...]`, validated and narrowed to the
  closed domain enum only at `answer_validation.py`, which fails safe (drops, never crashes) on
  anything it does not recognise.

## Consequences

- A future real provider is a new `LanguageModelProvider` implementation plus a swapped FastAPI
  dependency default - `AskNinfaService`, the `/ask` route, and every existing test built against
  the fake stay unchanged.
- A future multi-turn Ask NINFA designs its own persistence layer from scratch; this gate's
  single-turn `AskDecisionContext`/`AskResult` shapes are not required to anticipate it.
- A future chat UI reads the same `/ask` endpoint additively, the same relationship Gate 17's
  Recommendation panel already has to Gate 15's Decision Detail page.
- Perimeter/application rate limiting remains explicit, documented debt - required before any real
  (costed) provider pilot, not before this gate, which never calls a real provider at all.
- A sixth decision type gaining Ask NINFA support requires the context builder's own per-type
  target/whitelist mapping to be extended - there is no generic fallback a new type could silently
  fall into, the same discipline every other per-type adapter in this codebase already follows.

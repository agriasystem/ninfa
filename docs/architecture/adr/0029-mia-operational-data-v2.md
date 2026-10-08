# 0029 — Mia V2: operational data through a safe semantic layer, and a short conversation

## Context

Mia Home (ADR 0028) explains what the **Decision Feed** holds, one stateless question at a time. Two
limits made it unusable as the natural-language interface to NINFA:

1. a hotel owner cannot ask about the data NINFA already has ("Gli OTA sono a posto?", "Qual è
   l'occupazione dei prossimi 7 giorni?") unless a Decision happens to carry the number - and
   "Gli OTA sono a posto?" with no OTA decision had nothing to say but "non ho memoria...";
2. a follow-up ("Perché?", "Intendo gli OTA, sono a posto?") was an unrelated, unanswerable question.

The principle did not change: **ENGINE CALCULATES. MIA EXPLAINS.** Giving the model SQL, tools or raw
rows would break it, and so would "just tell the prompt to answer more questions".

## Decision

1. **A read-only semantic data layer, not a model with data access.** `HomeDataService` returns small
   labelled sections (a metric, a period, a unit, a note, a grounding ref) computed by application
   code from what the repository already defines: stored booking snapshots, `OtaDependencyService`
   (Gate 9, read-only), Gate 3's certainty rule, the run's coverage/provenance. No table, SQL, id or
   raw record is ever handed to the model; the provider request stays text-only with no tools.
2. **Bounded question understanding, no agent.** A deterministic classifier maps the question onto a
   closed enum (`HomeIntent`) with an explicit hospitality vocabulary (OTA/portali/Booking/Expedia/
   canali/..., typos), an Italian period parser and channel entities. It only **selects** which facts
   to fetch. No extra model call, no business fact in the router. A question it cannot place still
   gets the overview context and the list of what Mia can explain - never a generic fallback.
3. **Define nothing new.** Only metrics the repository already defines are exposed. Fatturato, RevPAR,
   cancellations, commission amounts, pickup-as-a-number, forecasts and anything before the analysis
   day are reported as "NINFA non può determinare ..." with a fixed sentence each (deferred, see the
   capability matrix) - ricavi camera sulle prenotazioni are given **labelled as not fatturato**.
   Accounting concepts that differ are never merged (occupancy is "sulle prenotazioni attuali", never
   final; the OTA share and a channel's weight have different denominators and say so).
4. **The persisted run is the authority.** Live reads only add metrics. A decision exists only if the run
   produced it; "no decision" is hedged when the run had checks without enough data (counts are not
   attributable to an area); an evaluated-but-insufficient OTA outcome is **never** reported as
   all-clear; a live OTA evaluation that would now trigger while the run has no decision asserts
   nothing. "Gli OTA sono a posto?" has four explicit cases and never an absolute "perfetto".
5. **A short, bounded, client-held conversation.** The page sends up to 4 complete exchanges as
   `history` with each question; nothing is stored server-side (no table, no id; lost on reload) -
   the endpoint stays stateless. History is validated strictly and never repaired; user messages the
   guardrail would refuse are rejected as a forged history. It is **referential context only**: the
   router reads only the user's own earlier words to resolve a follow-up, the assistant's text is
   never mined, the facts are rebuilt fresh every time, and the provider sees history in its own
   JSON-escaped block that the instructions rank below the NINFA context and call untrusted data.
6. **Grounding as structured metadata.** Every section/decision/area carries a hyphenated semantic ref
   (`metric:occupancy:2026-10-09:2026-10-15`, `coverage:distribution`, ...); the per-request vocabulary
   (the structured-output enum) is the base refs plus exactly the refs of that context, so an answer
   can only name sources it was really given.
7. **Frontend: a small real conversation and a real composer.** Up to 4 exchanges in a bounded,
   internally scrolling area (the operational Home is never pushed away), "Nuova conversazione", and an
   auto-growing `<textarea>` (Enter sends, Shift+Enter newline, 1-4 lines).

## Consequences

- No migration, no new dependency. One new request field (`history`, optional) and one new context key
  (`dati operativi richiesti`); instructions `ask-mia-home-v3`; `LanguageModelRequest` gains an
  optional `history`; the Anthropic adapter adds a history block only when there is history.
- The Decision Ask is untouched (700 characters, 1024 tokens, its own vocabulary, no history).
- The OTA question costs one extra read-only evaluation (a handful of statements) when no OTA decision
  fired; a failure degrades to "la quota OTA non è al momento calcolabile", never a guess.
- Not proven by the automated suite: how well a real model follows the instructions. The real-provider
  smoke test (and a latency check against the unchanged 15 s timeout) is still required.
- Adding a metric later means: define it, add a section builder + its refs + an unsupported-note
  removal, and test it - the router and the guardrails do not change.

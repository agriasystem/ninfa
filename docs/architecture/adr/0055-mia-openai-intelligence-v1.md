# ADR 0055: Mia, the assistant of NINFA, on the OpenAI Responses API with a closed tool catalog

Status: accepted (Mia OpenAI Intelligence V1). Migration `0017_mia_conversations`. No new dependency. Supersedes the unmerged
Mia V3 design (branch `feature/mia-v3-company-intelligence`: its ADR 0030 and its document were never merged). Builds on
[ADR 0024](0024-ask-ninfa-core-v1.md) / [ADR 0025](0025-anthropic-provider-v1.md) (grounded, explicit-provider asks),
[ADR 0026](0026-ask-ninfa-language-hardening-v1.md) (technical leakage fails closed) and the OpenAI layer of
[ADR 0050](0050-the-semantic-layer-reads-names-ninfa-proves-values.md) / [0052](0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md).

## Context

Mia is meant to be the person's main way into NINFA: ask anything about the product, the property, the decisions, the data, the
imports and the structure, without knowing where to look. The Home already had a closed-intent Mia (V2, Anthropic, one prebuilt
context). That cannot answer "why is it so high?" on a screen, cannot join revenue, costs, distribution and staff, and cannot know the
product without a hand-written prompt that goes stale.

## Decision

1. **The engine calculates; Mia understands, links and explains.** Mia is read-only. She reaches NINFA only through a **closed
   catalog of 23 typed tools** (`extra="forbid"` arguments, no SQL, no tenant/property/user argument, no write verb), under the
   asking person's own access, with the scope derived server-side. The model never knows the hotel because a prompt says so: it asks.
2. **OpenAI Responses API, `gpt-6.1-sol`, `store=false`, strict final-answer schema.** One adapter file
   (`gateway/mia_openai_provider.py`) imports **no SDK of its own**: the client, the retry rule, the failure vocabulary and the
   "send nothing" marker come from `openai_provider.py`, so the key, endpoint, data residency, timeout and classification are
   decided once for the account. Mia has her own switch (`MIA_PROVIDER`, default `unconfigured`), model and timeout; she shares no
   business logic with Smart Import's layer (a boundary test enforces both ways).
3. **The application, not the model, bounds the loop.** At most 3 tool rounds and 8 calls, one correction, a 90 s deadline; the
   call after the last round has tools disabled. **Reasoning effort is the application's choice** (`policy.py`): LOW for a pointer or
   a definition, MEDIUM by default, HIGH only for a multi-area or analysis question and for a turn that actually consulted three
   areas. The first call is planned from the wording, the later ones from what was consulted.
4. **No invented figures, by code.** Every number in an answer must be one of this turn's tool results (or a date/duration the user
   named); one rewrite without tools is allowed for an ungrounded figure or a cut-off sentence, then the turn fails closed to
   `UNAVAILABLE`. Technical codes never reach the person. Digits of an identifier (a UUID) are not figures.
5. **Coverage and freshness are first-class.** An observation carries `copertura` and `aggiornamento` beside its figures; a missing
   value is `None` plus a plain-Italian reason, never zero. The policy says: last available data is not fresh data; reconstructed is
   not observed; no new data is not zero pickup.
6. **Product knowledge is data, anchored to the code (anti-drift).** A registry of 222 entries; every entry carries machine-checkable
   anchors (web route, tab, shipped copy, API route, enum member, doc) and `test_mia_knowledge_registry` verifies all of them and
   requires every real route, tab, navigation item and API route group to be anchored: rename a screen and the test names the
   obsolete knowledge; add one and it names the missing entry. The system policy carries no product manual.
7. **Page-aware, as a hint.** The browser sends a small closed `ui_context`; the server validates every id inside the person's own
   workspace and property and every route and metric against the registry, drops what does not check out (a foreign id and a missing
   one are the same), and writes the rest as data in its own block. Truth still comes from the tools.
8. **The conversation is NINFA's.** Many conversations per (workspace, property, user), each with an id that is a handle and never a
   credential (matched together with all three scopes), bound to the membership by a composite foreign key with `ON DELETE
   CASCADE`, retained 60 days, at most 20 per person and property. The model sees the recent messages verbatim and a
   **deterministic summary** of the rest (earlier questions and tool names, headed "not facts about the data"). No chain of
   thought, no tool payload, no observation is stored.
9. **A decision is the Decision Engine's; a reading is Mia's.** She never creates, implies or promises a Decision; a cross-area
   observation is said to be her reading of data already available.
10. **A failure of Mia is a dignified `UNAVAILABLE`.** HTTP 200, nothing recorded, no other screen depends on the route. Selecting
    `openai` with no key is a warning, not a startup error.

11. **What cannot be calculated is said by the application, not requested of the model** (the "truthfulness closure", system policy
    `mia-v1-6`). A live sample showed that "Quanto siamo pieni venerdì?" with 14 rooms booked and no room inventory was answered with
    the 14 rooms and nothing else, in every run. A tool therefore declares the figure it is about and cannot give
    (`Observation.gaps`); the gap is material only when the person asked for that metric (this question, or the one before it for a
    follow-up); and when the answer does not say it, or does not say what is missing, the orchestrator adds one sentence written from the
    tool's own reason, after every other check, with no estimate and no extra model call. The vocabulary that recognises the ask is a
    closed, tested table and its limit is lexical.
12. **Another structure is never read, and the answer does not depend on whether it exists.** A request for the data of a structure
    other than the open one is answered before any model call, tool or lookup with one fixed text (an access boundary of NINFA, not a
    limit of Mia; nothing was read; open that structure and ask from there), identical for a structure the person manages, one of
    another account and one that does not exist, never repeating the typed name.

## Consequences

* The pilot deployment template pins `MIA_PROVIDER=unconfigured`; enabling Mia is an operational decision with its own conditions
  (spending limit, key in the API environment only, live acceptance, telemetry), recorded in
  [pilot-deployment-v1](../../operations/pilot-deployment-v1.md).
* The V2 closed-intent `POST /properties/{id}/ask` (Anthropic) is untouched and no longer used by the UI.
* A new migration cascaded across the per-gate migration tests' head constants, as every migration does.
* What the tests cannot prove (that a real model plans well and phrases well) is measured by the live acceptance and the evaluation
  suite, with its limits stated in [mia-openai-intelligence-v1](../mia-openai-intelligence-v1.md). The live acceptance and the live
  100-scenario sample predate the final prompt `mia-v1-6`; only the offline oracle and a small targeted live check were run on it, and
  the documents say so.

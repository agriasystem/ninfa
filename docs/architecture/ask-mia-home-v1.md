# Mia Home (`ask-mia-home-v1`)

The Home's "Chiedi a Mia..." bar answers questions about **today's analysis of the whole property**,
where [Ask NINFA](ask-ninfa-v1.md) answers about **one Decision**. See
[ADR 0028](adr/0028-mia-home-context.md) for the "why".

> **Update (Mia V2, ADR 0029):** the context now also carries `dati operativi richiesti` (occupancy,
> bookings, room revenue on the books, the OTA share, channel weights, area status) selected by a
> deterministic question router and computed by `HomeDataService`; the request accepts an optional
> short `history`; the instructions are `ask-mia-home-v4`. The endpoint is no longer "one stateless
> question without a history" - it is still stateless server-side. Everything about V2 is in
> [mia-operational-data-v2.md](mia-operational-data-v2.md); the sections below describe the base
> Mia Home it builds on.

    ENGINE CALCULATES. MIA EXPLAINS.

Mia never analyses raw data to find problems. The context she answers from is built **only** from
`DecisionMemoryService.get_feed(property, as_of_local_date)` - exactly what the Decision Feed
endpoint already returns for the same `(property, date)`. If a detector did not trigger a Decision,
Mia has nothing to say about it as a problem.

## Endpoint

    POST /api/v1/properties/{property_id}/ask
    { "question": "...", "as_of_local_date": "YYYY-MM-DD" }

- Authenticated like every property route; an unknown / archived / foreign property is `404
  PROPERTY_NOT_FOUND` (never 403).
- `as_of_local_date` is **explicit** and mandatory (the same property-local business date the feed is
  requested with - never a server clock). Missing -> 422; not an ISO date -> `400 INVALID_AS_OF_DATE`.
- `question`: 1-1000 characters after trimming (`400 INVALID_ASK_QUESTION`).
- Response: the **same `AskResponse`** as the Decision Ask - `status` (`ANSWERED` /
  `INSUFFICIENT_CONTEXT` / `UNAVAILABLE` / `REFUSED`), `answer`, `grounding_refs`, `limitations`.
  `Cache-Control: no-store`. No conversation id, nothing persisted, no write of any kind.
- `POST /properties/{pid}/decisions/{did}/ask` is untouched and keeps its own instructions, context
  and `grounding_refs` vocabulary.

Order of work: scope (404) -> `as_of` (400) -> question (400) -> deterministic guardrail (`REFUSED`
never reads the feed and never reaches the provider) -> feed -> context -> **one** provider call ->
validation. Any provider failure or invalid output fails closed to `UNAVAILABLE`.

## The context (`AskHomeContext`)

Built by `AskHomeContextBuilder().build(feed, property_timezone)` - pure, no session, no query of
its own. Serialized (`home_serialization.py`) with **plain Italian JSON keys** (with spaces, never
snake_case), so an echoed key can never trip the technical-leak check. `null` always means "not
available".

| Part | Source | Notes |
| --- | --- | --- |
| business date | `feed.as_of_local_date` | |
| analysis state | `feed.state` | four Italian labels; "nessuna decisione richiede attenzione" only for `NO_ACTION_REQUIRED` |
| decisions | `feed.items`, in the engine's priority order, **at most 10** | each: ordinal word ("prima", "seconda", ...), the Italian decision title, a one-sentence **description** of what NINFA checked, area, status, target (Italian keys), exact confidence, first-seen date, episode count, semantic facts, the **kind** of its economic estimate, economic impact |
| total / omitted | `len(items)` | so Mia can say "ce ne sono altre" instead of implying completeness |
| coverage | `run.analysis_coverage` | per area "analizzata"/"non analizzata"; `UNKNOWN` never inferred as full; `null` without a run |
| freshness | `run.input_provenance` | the last booking import in **property** time, with "oggi"/"ieri" relative to the business date; unknown never invents a time; `null` without a run |
| insufficient / low-confidence checks | run counts | only ever counts of checks, never attributed to an area |
| last successful analysis | `feed.last_successful_analysis` | the business date, only for `NOT_PROCESSED` |

Facts go through the shared whitelist (`decisions/whitelist.py`) and the same semantic labels
(`semantic_labels.py`) as the Decision Ask; every `*_data_source_id` is stripped; nulls are dropped
before labelling. **Economic impact** is only a proxy the engine already recorded (revenue gap, OTA
exposure, cost gap, labour cost gap), each labelled "stima indicativa, non un valore certo"; a
currency is only ever the one the engine recorded.

Two fields exist so Mia can be **concrete** without inventing anything (`ask-mia-home-v2`):

- `descrizione` - one fixed sentence per decision *type* saying what NINFA checked ("Le prenotazioni
  per il giorno di soggiorno indicato stanno arrivando sotto il ritmo atteso."). It is the same
  wording the Home's hero already ships (`semantic_labels.DECISION_TYPE_DESCRIPTIONS`): no number, no
  judgement beyond the Engine's own "sotto/sopra il livello atteso", no recommendation.
- `tipo di impatto economico` - what *kind* of estimate the decision's proxy is: `ricavi` (pickup,
  occupancy), `ricavo esposto su OTA`, `costi` (cost per room, labour). It is `null` exactly when the
  decision has no recorded estimate. It lets Mia compare two estimates only when they are of the
  same kind, and say "non sono direttamente confrontabili" otherwise - without being left to guess
  whether 540 (revenue, no currency) and 482,30 euro (cost) can be set side by side.

Never in the context: property name or any id, raw booking/invoice/labour rows, SQL, detector
thresholds, rank numbers or scores, reason codes, the question, the instructions, secrets.

## Instructions (`ask-mia-home-v2`)

`home_instructions.py`. Beyond the Decision Ask's language-quality rules (no technical identifiers,
no snake_case, answer first), the Home variant states, explicitly, that Mia: does **not** discover
anomalies, decide whether a problem exists, create Decisions, change the priority order, invent
impacts, use outside knowledge, or declare data current/stale/"aggiornati". She **may** only explain
the Decisions in the feed, compare them, say which is first in NINFA's own order (in words - never a
rank number or score), explain coverage, state the last import as a fact, and say the context is not
enough (`INSUFFICIENT_CONTEXT`). A coverage that is not full means "all fine" is never said about an
area not analysed; economic estimates are never summed or compared across kinds (revenue vs cost).

**v2 - response quality.** v1 was safe but thin: 300-500 characters, and a generic limitation
sentence where a concrete answer was available. v2 keeps every safety rule and adds the other half,
"being grounded does not mean being vague":

- **Answer shape:** the first sentence answers the question directly; then the concrete details the
  context holds (decision, area, what it refers to, detected vs expected, reliability on its 0-100
  scale, the estimate); only if it really matters, one specific limit - in the `limitations` field,
  not as the answer's opening.
- **No generic opening disclaimers** ("Posso basarmi solo sui dati forniti", "Non ho accesso a...",
  "In base alle informazioni disponibili...") and **never replace a concrete answer the context
  allows with a generic statement about her limits**.
- **`INSUFFICIENT_CONTEXT` only when the context genuinely lacks what the question needs** (a loss
  forecast, "what should I do with prices", an area not analysed, an analysis not available) - and
  even then the answer starts from what Mia can say with certainty. A partial answer from the context
  is `ANSWERED`.
- **Enumerate all the relevant decisions** (not only the first), one line each, and say when
  `decisioni non mostrate` > 0.
- **Length:** ~60-160 words by default, up to ~220 only to list or compare several decisions; never
  more (about 1500 characters). Short paragraphs; a list uses one `- ` line per decision; no Markdown,
  no emoji.
- **Per question:** "Ci sono altri problemi oltre a questo?" -> "Sì" + every other decision after the
  first (domain, target, estimate) or "No" + "nessun'altra decisione" for a single decision;
  "Qual è la priorità più urgente oggi?" -> the first decision in NINFA's order, explained with its own
  data, without inventing *why* it is first; "Quale decisione ha l'impatto economico più alto?" ->
  compare only same-kind estimates, otherwise "non sono direttamente confrontabili" and the highest
  per kind, always "stima indicativa"; "Quali dati ha usato NINFA oggi?" -> coverage (analysed / not),
  checks without enough data (as a count), the last import as a fact. Each feed state
  (`NO_ACTION_REQUIRED`, `DATA_QUALITY_LIMITED`, `NOT_PROCESSED`) has its own rule. A free question on
  an area says "no decision here" only if that area was analysed. A bare "Perché?" gets a request for
  a clearer question (the endpoint is stateless: Mia has no memory of earlier questions).
- Dates are written in natural Italian ("5 ottobre") and decimals with the comma ("7,50") without
  changing a value; comparing two figures already in the context is allowed, computing is not.

## Validation and the provider

`AskHomeService` reuses the Decision Ask's pieces: the `LanguageModelProvider` protocol, the question
bounds, `guardrails.classify_refusal` (the refusal copy now says "Mia"), and
`answer_validation.validate_model_answer_core` (shape, length - an overlong answer **fails closed**,
never truncated - and the technical-leak check). What differs is the hard length ceiling
(`MAX_HOME_ANSWER_CHARS` = **1800**, against the Decision Ask's 700: ~220 words of Italian plus
headroom; a ceiling, not a style target) and the closed
`grounding_refs` vocabulary (`HomeGroundingRef`: `ANALYSIS_STATE`, `DECISIONS`, `ECONOMIC_IMPACT`,
`COVERAGE`, `FRESHNESS`, `LAST_ANALYSIS`), which travels **per request**
(`LanguageModelRequest.grounding_ref_values`) so the Anthropic adapter builds the structured-output
schema for the right vocabulary without touching the shared Decision Ask schema object. Still: no
tools, no web, no streaming, no fallback provider, one bounded call.

The Anthropic adapter scales only the **output budget** for the longer answer: requests with
`max_answer_chars` above 1200 (Mia Home) get `max_tokens` 2048, every other request (the Decision Ask)
keeps 1024 - a Home answer of up to 1800 characters, its JSON envelope and the adaptive-thinking tokens
(which count against `max_tokens`) would not reliably fit in 1024. The timeout stays 15 s, with no
retry; whether 15 s is enough for the longer answer is exactly what the real smoke test must measure.

## Tests

`tests/test_ask_mia_home_{context_builder,api,golden,instructions,provider,quality}.py`: auth/tenant
isolation, explicit `as_of`, feed-only context (multiple decisions, description, estimate kind,
coverage, freshness in property time, no fabricated state per feed state), no raw data / ids /
snake_case keys, the four statuses, provider errors, technical-code and overlong-answer rejection, no
tools/web, read-only, the Decision Ask unaffected (its 700-character ceiling and 1024-token budget are
asserted), golden contexts for the four suggested questions, and the response-quality scenarios below.

### What the tests do not prove

A deterministic test cannot show that a language model *writes* a good answer. `ask-mia-home-v2` is
covered at three honest levels:

1. **The instructions contain the rules** (`test_ask_mia_home_instructions.py`): "grounded does not
   mean vague", never replace a concrete answer with a generic limitation, no opening disclaimer,
   `INSUFFICIENT_CONTEXT` only when the context lacks the answer, enumerate all decisions, the length
   targets, and one rule per suggested question and feed state - and every context key those rules
   name really exists in the serialization.
2. **The context is sufficient** (`test_ask_mia_home_quality.py`, `tests/ask_home_answers.py`): a
   stand-in that is **not a model** composes an answer from *nothing but the context string a real
   provider receives*; if a needed field were missing (area, target, estimate or its kind, coverage,
   the import fact, the last analysis date), composing would fail. Scenarios: other problems (several
   / single / full feed), priority, impact (different kinds / same kind / no estimate), data used,
   `NO_ACTION_REQUIRED`, `DATA_QUALITY_LIMITED`, `NOT_PROCESSED` (with and without a previous analysis),
   a free question on an analysed vs not analysed area, and a bare "Perché?" (stateless).
3. **A rich answer survives the pipeline**: a ~220-word answer with paragraphs and a list passes
   validation whole (not truncated, line breaks intact) and is rejected only above the ceiling.

Whether the real model **follows** the instructions - tone, length, no invented figure, no generic
opener - is NOT proven by any of this. It requires the **real Anthropic smoke test** with a configured
key (the four suggested questions plus `Perché?`, over a feed with several decisions, a partial
coverage and a `NOT_PROCESSED` day), reading the actual answers and the latency. That test has not
been run.

## Home presentation (Mia conversational send UX)

The API contract above is unchanged by the Home's conversational send experience; the UI sends the
submitted question, empties the bar and renders ONE exchange (the question + Mia's reply) at a time,
because the endpoint is stateless per question and the model never receives a history. See
[home-ui-v1.md](home-ui-v1.md), "Mia on the Home".

The answer is plain text with line structure: the UI renders short paragraphs and, for a `- ` line,
a real list (`lib/ask-ninfa/format-answer.ts`) - never Markdown or HTML. An `INSUFFICIENT_CONTEXT`
reply that carries Mia's own explanation shows that explanation alone; the generic "non ha abbastanza
informazioni" copy is only the fallback for a reply with no text.

# Mia Home (`ask-mia-home-v1`)

The Home's "Chiedi a Mia..." bar answers questions about **today's analysis of the whole property**,
where [Ask NINFA](ask-ninfa-v1.md) answers about **one Decision**. See
[ADR 0028](adr/0028-mia-home-context.md) for the "why".

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
| decisions | `feed.items`, in the engine's priority order, **at most 10** | each: ordinal word ("prima", "seconda", ...), the Italian decision title, area, status, target (Italian keys), exact confidence, first-seen date, episode count, semantic facts, economic impact |
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

Never in the context: property name or any id, raw booking/invoice/labour rows, SQL, detector
thresholds, rank numbers or scores, reason codes, the question, the instructions, secrets.

## Instructions (`ask-mia-home-v1`)

`home_instructions.py`. Beyond the Decision Ask's language-quality rules (no technical identifiers,
no snake_case, short, answer first, <= 700 characters), the Home variant states, explicitly, that
Mia: does **not** discover anomalies, decide whether a problem exists, create Decisions, change the
priority order, invent impacts, use outside knowledge, or declare data current/stale/"aggiornati".
She **may** only explain the Decisions in the feed, compare them, say which is first in NINFA's own
order (in words - never a rank number or score), explain coverage, state the last import as a
fact, and say the context is not enough (`INSUFFICIENT_CONTEXT`). A coverage that is not full means
"all fine" is never said about an area not analysed; economic estimates are never summed or compared
across natures (revenue vs cost).

## Validation and the provider

`AskHomeService` reuses the Decision Ask's pieces: the `LanguageModelProvider` protocol, the question
bounds, `guardrails.classify_refusal` (the refusal copy now says "Mia"), and
`answer_validation.validate_model_answer_core` (shape, <= 700 chars - an overlong answer **fails
closed**, never truncated - and the technical-leak check). What differs is the closed
`grounding_refs` vocabulary (`HomeGroundingRef`: `ANALYSIS_STATE`, `DECISIONS`, `ECONOMIC_IMPACT`,
`COVERAGE`, `FRESHNESS`, `LAST_ANALYSIS`), which travels **per request**
(`LanguageModelRequest.grounding_ref_values`) so the Anthropic adapter builds the structured-output
schema for the right vocabulary without touching the shared Decision Ask schema object. Still: no
tools, no web, no streaming, no fallback provider, one bounded call.

## Tests

`tests/test_ask_mia_home_{context_builder,api,golden,instructions,provider}.py`: auth/tenant
isolation, explicit `as_of`, feed-only context (multiple decisions, coverage, freshness in property
time, no fabricated state per feed state), no raw data / ids / snake_case keys, the four statuses,
provider errors, technical-code and overlong-answer rejection, no tools/web, read-only, the
Decision Ask unaffected, and golden contexts for the four suggested questions.

## Home presentation (Mia conversational send UX)

The API contract above is unchanged by the Home's conversational send experience; the UI sends the
submitted question, empties the bar and renders ONE exchange (the question + Mia's reply) at a time,
because the endpoint is stateless per question and the model never receives a history. See
[home-ui-v1.md](home-ui-v1.md), "Mia on the Home".

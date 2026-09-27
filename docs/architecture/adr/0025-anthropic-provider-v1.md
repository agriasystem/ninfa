# 0025 — Anthropic provider V1: the first real `LanguageModelProvider`

## Context

Gate 18 built Ask NINFA's entire vendor-agnostic architecture - `LanguageModelProvider` Protocol,
whitelisted context, deterministic guardrail, structured output, service-level validation - but
shipped no real provider on purpose, only `UnconfiguredLanguageModelProvider`, which always fails
closed. This gate adds the first REAL implementation of that Protocol, backed by the official
Anthropic Python SDK, without touching anything Gate 18 already built: `AskNinfaService`, the
context builder, and every domain type stay entirely unaware Anthropic - or any vendor - exists.

## Decision

1. **Why Anthropic as the initial provider.** A vendor decision, not a technical one - made
   explicitly, in this gate's own prompt, by the people who own that decision, not inferred or
   second-guessed here. This ADR documents the CONSEQUENCES of that choice (isolation, structured
   output, error handling), not a re-justification of the choice itself.

2. **Why not vendor-lock, even having picked one.** `AnthropicLanguageModelProvider` is one
   implementation of Gate 18's `LanguageModelProvider` Protocol, structurally isolated to a single
   file (`app/modules/ai/gateway/anthropic_provider.py` - see `test_anthropic_provider_isolation.py`,
   an AST-based scan proving no other file under `app/` imports `anthropic`). A future second
   provider is a new file implementing the same Protocol, never a change to `AskNinfaService`, the
   `/ask` route, or any Gate 18 test built against the fake.

3. **Why `claude-sonnet-5` specifically.** The model identifier is an architectural constant
   (`ANTHROPIC_MODEL`, `anthropic_provider.py`), never a runtime setting - swapping models is a
   deliberate future decision with its own review, not a config toggle that could drift silently.
   Verified against the real, installed `anthropic==1.8.0` SDK during this gate's own pre-gate
   check (its request-parameter Literal type lists this exact model id), never assumed from the
   prompt text alone.

4. **Why Anthropic Structured Outputs, not free-text + a second parsing pass.**
   `output_config.format = {"type": "json_schema", "schema": ...}` constrains the model's own
   output at generation time to Gate 18's closed `{status, answer, grounding_refs, limitations}`
   shape - fewer malformed responses reach `_answer_from_message` in the first place. It is not a
   substitute for Gate 18's own `answer_validation.py`: the adapter re-validates the parsed JSON
   byte for byte (`_answer_from_message`), because a schema is a strong hint to the model, never a
   guarantee about what it actually returns.

5. **Why `status` in the schema is constrained to `ANSWERED`/`INSUFFICIENT_CONTEXT` only.**
   `REFUSED` and `UNAVAILABLE` are Gate 18's own SERVICE-level decisions (a deterministic guardrail
   before any call; a provider failure after one) - never something the model itself is asked to
   decide. Letting the model's own JSON schema include those two values would blur exactly the line
   ADR 0024 already drew between "the model answers" and "the service decides".

6. **Why `grounding_refs` in the schema is limited to Gate 18's own closed enum.** The schema's
   `items.enum` is built FROM `GroundingRef` (`_GROUNDING_REF_VALUES = [ref.value for ref in
   GroundingRef]`), never a second, adapter-local list that could drift from it - the same
   discipline `_STATUS_VALUES` applies to `ModelAnswerStatus`.

7. **Why the provider's own schema stays shape/type/enum only.** `maxLength`/`minLength`/`pattern`
   and other string-content constraints are NOT supported by Anthropic Structured Outputs (verified
   against the real, current docs during this gate's pre-gate check, not assumed) - and even where a
   keyword happens to be supported, business-length policy (`MAX_ANSWER_CHARS = 1200`, truncation
   with ellipsis) stays exactly where Gate 18 already put it,
   `app/modules/ai/ask_ninfa/answer_validation.py`. The provider's schema answers "is this
   syntactically the right shape", never "is this business-acceptable".

8. **Why `effort: "low"`, and no `temperature`/`top_p`/`top_k`.** Ask NINFA explains already-decided
   facts (ADR 0024's core principle) - it needs neither frontier reasoning depth nor sampling
   diversity. `effort` is `output_config`'s own inference-shape knob; the installed SDK's
   `messages.create()` signature exposes no `temperature`/`top_p`/`top_k` parameter at all for this
   model, so there is nothing to omit-by-choice there, only nothing to add.

9. **Why exactly one Messages API call per `generate()`.** No streaming, no tool use, no web
   search/fetch, no MCP, no multi-step retrieval - Ask NINFA's entire input is already fully
   assembled before the call (Gate 18's `AskDecisionContext`), so there is nothing an autonomous,
   multi-step provider interaction could usefully add, only additional cost, latency and attack
   surface.

10. **Why zero automatic retries, and no application-level retry loop.** `max_retries=0` at the
    `anthropic.Anthropic` client constructor genuinely disables the SDK's own transport-level retry
    behaviour (verified as a real, readable constructor parameter against the installed SDK, not
    assumed) - and `generate()`'s own source contains no `for`/`while` around
    `.messages.create(` (checked structurally via `ast.walk`, `test_98_no_application_retry_loop_
    in_the_adapter_source`). A single, bounded, bounded-timeout (`timeout=15.0`) attempt fails
    closed to `UNAVAILABLE` - retrying a stateless explanation request is never worth the added
    latency or the added chance of a duplicate costed call.

11. **Why no fallback model or vendor.** A silent fallback would mean two different models produce
    "the same" answer under one contract, with no way for a caller to know which one actually ran -
    undermining the very grounding guarantees ADR 0024 built. `UNAVAILABLE` is an honest, correct,
    already-existing Gate 18 outcome; there is no need to invent a second failure-recovery path.

12. **Why no tools, browsing, retrieval, or MCP.** Every fact the model could need is already inside
    `AskDecisionContext` (ADR 0024, points 1-2) - giving it a tool would only let it fetch something
    OUTSIDE the whitelisted boundary that entire architecture exists to enforce.

13. **Why adaptive thinking is ignored, not merely unrequested.** Claude Sonnet 5 reasons internally
    by default ("adaptive thinking"); this gate does not ask for chain-of-thought and does not want
    it exposed, logged, or persisted even if the API produced it. `thinking = {"type": "adaptive",
    "display": "omitted"}` redacts the content at the API boundary itself; `_answer_from_message`
    additionally only ever extracts `type == "text"` blocks, a second, defensive layer that would
    filter out a thinking block even if the API ever changed its own redaction behaviour.

14. **Why provider/model/telemetry metadata stays server-side only.** `logger.info`/`logger.warning`
    in `generate()` record `provider=anthropic model=... status=... elapsed_ms=... input_tokens=...
    output_tokens=...` (success) or `... status=UNAVAILABLE elapsed_ms=... error_type=...`
    (failure) - safe, structural metadata, never the question, the context, the system instructions,
    the answer text, or any raw provider response/exception body. The public `/ask` response
    contract (Gate 18, unchanged) carries none of this either - `test_95_public_response_carries_
    no_vendor_metadata` asserts "anthropic"/"claude"/"sonnet" never appear in the HTTP response.
    Token-count logging is deliberately present: it enables a FUTURE cost-tracking/budget feature to
    be built from real historical data, without this gate needing to build a cost calculator itself.

15. **Why the API key is environment-only, `SecretStr`, and never silently inferred.**
    `ANTHROPIC_API_KEY` has no default; `Settings._check_ask_ninfa_provider_configuration` fails
    CLOSED at startup (not at the first request) if `ASK_NINFA_PROVIDER=anthropic` is selected
    without a real key - and, symmetrically, a key being present is NEVER enough by itself to select
    the vendor (`ASK_NINFA_PROVIDER` must be explicitly set to `anthropic`). `SecretStr` gives the
    same repr/log safety `database_url` already has in this codebase; the adapter never logs, never
    exception-embeds, and never re-derives the key from `str(exc)` (a hypothetical vendor bug
    embedding the key in its own exception message is explicitly tested against,
    `test_49_api_key_never_exposed_in_exception_or_logs`).

16. **Why Zero Data Retention is documented, not assumed.** ZDR is an Anthropic ACCOUNT-level
    qualification (a commercial/compliance arrangement with the vendor), never something this
    adapter's code can turn on by itself - no request parameter here claims or enables it. This gate
    documents that fact honestly (`docs/architecture/anthropic-provider-v1.md`) rather than
    asserting a guarantee the code cannot actually provide.

17. **Why no live API call anywhere in the automated suite.** Every one of the 95 new tests
    constructs a REAL `AnthropicLanguageModelProvider` and swaps out only its underlying HTTP
    transport (`provider._client.messages.create`, `tests/anthropic_provider_support.py`) with a
    canned response or exception built from REAL `anthropic.types`/`anthropic.<Error>` objects,
    never a loose `unittest.mock.Mock` standing in for the SDK's own shape. No test, fixture, or CI
    step holds or requires a real key. A live-qualification procedure (deliberately NOT an automated
    script - see the main doc, "Live smoke test") is documented instead: a human runs a short,
    manual, interactive snippet with a real key, once, outside pytest/CI, to confirm the adapter
    still matches the real API's current behaviour before any live pilot.

## Alternatives considered

- **A single "does an API key exist" check to select the provider.** Rejected: this is exactly the
  silent-inference failure mode ADR 0024 already avoided for Gate 18's own defaults - an
  accidentally-set environment variable in a shared `.env` should never be enough to start making
  real, costed vendor calls. `ASK_NINFA_PROVIDER` is the single source of truth for provider
  selection; the key is a separate, required-only-when-selected credential.
- **Passing `temperature=0` for determinism.** Rejected: not a parameter this SDK version's
  `messages.create()` accepts for this model at all (verified against the installed SDK, not
  assumed) - there is no sampling-parameter knob to set here, low or otherwise, only `effort`.
- **A generic `except anthropic.APIError` catch instead of the current broad `except Exception`.**
  Rejected: a broad catch is the correct fail-closed posture for "anything a vendor SDK could raise,
  including something outside its own documented hierarchy, must still become `UNAVAILABLE`,
  never an unhandled 500" - narrowing it to the SDK's own exception base class would reintroduce a
  gap for exactly the kind of unexpected failure this boundary exists to close.
- **Embedding `str(exc)` in the raised `LanguageModelUnavailableError` for easier debugging.**
  Rejected: the vendor's own exception message can carry request/response detail (a request id, a
  fragment of the request body, and for `AuthenticationError` specifically, part of the request
  itself) - the adapter's raised error is a static, safe string; `type(exc).__name__` (a safe,
  static category label) is the only failure detail that reaches the log.
- **A short adapter-level retry loop for transient errors (timeout, 429) before failing closed.**
  Rejected here specifically, though a natural-sounding idea: Ask NINFA's own contract already has a
  correct, cheap, non-retried failure outcome (`UNAVAILABLE`, itself unlikely to be user-visible as
  an error since the endpoint answers `200` either way) - retrying inside a single request adds
  latency and duplicate-cost risk for a single-turn, best-effort explanation, not a critical write.
- **A hardcoded, adapter-local live-smoke script that runs a real request against the real API.**
  Considered, but a script under `tests/`, `scripts/`, or anywhere this repo's own tooling might
  discover and execute would risk running during CI/build - this codebase has no existing precedent
  for a "manual only, never automated" test file, so inventing one here would be a new, unreviewed
  convention. Documenting the manual invocation procedure in prose (main doc, "Live smoke test")
  achieves the same goal without adding a file that some future automation could accidentally pick
  up.

## Consequences

- A second real provider (a future gate) is a new file under `app/modules/ai/gateway/`, a new
  `Settings.ask_ninfa_provider` literal value, and a new `build_language_model_provider` branch -
  `AskNinfaService`, the `/ask` route, and every Gate 18 test stay unchanged.
- Provider comparison/routing (choosing between two configured vendors, A/B testing answers) is
  explicitly out of scope for V1 - `ask_ninfa_provider` is a single, exclusive choice; a routing
  layer is real future work with its own design questions (cost, latency, consistency of answers
  across vendors) this gate does not need to anticipate.
- A future cost-control feature (budgets, per-tenant limits, alerts) can be built directly from the
  `input_tokens`/`output_tokens` this gate already logs, without re-instrumenting the adapter.
- A live pilot with a real, costed key still requires perimeter/application rate limiting - already
  documented debt from ADR 0024, unchanged and still not required for this gate, which ships no
  rate limiter and calls no real network endpoint in its own automated suite.
- Anthropic ZDR qualification, if pursued, is an account-level/commercial step taken outside this
  codebase entirely - no code change in this adapter would be needed to benefit from it, and none
  is required to ship this gate honestly without it.

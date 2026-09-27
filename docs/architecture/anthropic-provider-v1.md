# Anthropic Provider V1 (`anthropic-provider-v1`, Gate 19)

Gate 18 built Ask NINFA's entire vendor-agnostic architecture and shipped no real provider on
purpose. This gate adds the first REAL implementation of Gate 18's `LanguageModelProvider`
Protocol - `AnthropicLanguageModelProvider` (`app/modules/ai/gateway/anthropic_provider.py`),
backed by the official Anthropic Python SDK. See ADR 0025 for the "why" behind every choice below;
this document is the "what" and "how". Nothing in `AskNinfaService`, the context builder, or any
domain type changed to make this possible - see "Vendor isolation" below for how that is enforced
structurally, not just by convention.

## Provider role

`AnthropicLanguageModelProvider.generate(request: LanguageModelRequest) -> LanguageModelAnswer` is
the ONLY thing this class does: translate Gate 18's own request shape into one real Anthropic
Messages API call, and translate a real response back into Gate 18's own answer shape. It computes
nothing about the decision itself - "engine calculates, AI explains" (ADR 0024) applies to this
adapter exactly as it applies to the model it calls.

## Vendor isolation

`anthropic` is imported in exactly one file in the entire codebase:
`app/modules/ai/gateway/anthropic_provider.py`. `test_anthropic_provider_isolation.py` enforces
this structurally, not by convention: it walks the AST of every other Python module under `app/`
and asserts none of them contains an `import anthropic` or `from anthropic import ...` statement
(matched on `ast.Import`/`ast.ImportFrom.module.split(".")[0]`, never a brittle text/substring scan
that could false-positive on a docstring mentioning the word "anthropic"). `AskNinfaService`, the
context builder, and every domain type in `app/modules/ai/ask_ninfa/` remain entirely unaware this
vendor - or any vendor - exists; they depend only on the `LanguageModelProvider` Protocol.

## Model

    ANTHROPIC_MODEL = "claude-sonnet-5"

A fixed, architectural constant, never a runtime setting - a model change is a deliberate future
decision with its own review (ADR 0025, "why not a config toggle"). Verified against the real,
installed `anthropic==1.8.0` SDK during this gate's pre-gate check.

## Configuration and provider selection

    ASK_NINFA_PROVIDER=unconfigured | anthropic     # default: unconfigured
    ANTHROPIC_API_KEY=                              # required only when ASK_NINFA_PROVIDER=anthropic

`Settings.ask_ninfa_provider` (`app/core/config.py`) is the single source of truth for which
provider is active - an API key existing is NEVER enough by itself to select Anthropic. Selecting
`anthropic` without a real, non-blank key fails CLOSED at process startup
(`Settings._check_ask_ninfa_provider_configuration`, a `model_validator(mode="after")`), not at the
first request. `anthropic_api_key` is `SecretStr`, the same convention `database_url` already uses
in this codebase, for the same reason: it must never render in a `repr()`, a log line, or an
exception message.

`app/modules/ai/gateway/factory.py`'s `build_language_model_provider(settings)` reads
`Settings.ask_ninfa_provider` and returns either `UnconfiguredLanguageModelProvider()` (Gate 18,
unchanged) or a real `AnthropicLanguageModelProvider(api_key=...)`. It is called exactly ONCE, when
`create_app()` builds the app (`app/main.py`), and the result is stored on
`app.state.language_model_provider` - never per-request, so a real provider's own
`anthropic.Anthropic` HTTP client is constructed a single time per app instance, never leaked as a
process-wide global either. `app/api/v1/decisions/deps.py`'s `get_language_model_provider(request)`
reads it back from `request.app.state`, the same pattern `get_request_settings` already established
for `app.state.settings`.

## Request boundary

`generate()` makes exactly one Anthropic Messages API call per invocation - no streaming, no tools,
no web search/fetch, no MCP, no multi-step retrieval:

    self._client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=request.system_instructions,
        messages=[{"role": "user", "content": [<context block>, <question block>]}],
        thinking={"type": "adaptive", "display": "omitted"},
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ...}},
    )

`system_instructions`, `context`, and `question` are kept as three structurally SEPARATE things,
never string-concatenated:

- `system` carries ONLY `request.system_instructions` (Gate 18's static, versioned instruction
  text) - the user's question never enters `system`.
- The single `user` message's `content` is TWO separate text blocks - `<context>...</context>` and
  `<question>...</question>` - never one merged string. This is the injection-resistance mechanism:
  the Messages API has no fourth "data" role, so two distinct content blocks inside the one
  available `user` role is how context (data) and question (untrusted input) stay separable.

No `temperature`/`top_p`/`top_k` are passed - this SDK version's `messages.create()` signature does
not expose them for this model at all. `tools`/`tool_choice` are never passed.

## Structured output

    output_config = {
        "effort": "low",
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["ANSWERED", "INSUFFICIENT_CONTEXT"]},
                    "answer": {"type": "string"},
                    "grounding_refs": {
                        "type": "array",
                        "items": {"type": "string", "enum": [...GroundingRef values...]},
                    },
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["status", "answer", "grounding_refs", "limitations"],
                "additionalProperties": False,
            },
        },
    }

Verified against Anthropic's real Structured Outputs documentation during this gate's pre-gate
check: `enum`/`required`/`additionalProperties: false`/`items` are supported;
`minLength`/`maxLength`/`pattern`/numeric range constraints are NOT. Business-content constraints
(answer length, truncation policy) stay exactly where Gate 18 already put them -
`app/modules/ai/ask_ninfa/answer_validation.py` - never duplicated or silently dropped here; the
provider's own schema is shape/type/enum only.

**`status` is deliberately closed to `ANSWERED`/`INSUFFICIENT_CONTEXT` only** - the model's own two
possible self-assessments. `REFUSED` (the deterministic guardrail, before any call) and
`UNAVAILABLE` (a provider failure) remain exclusively SERVICE-decided, never something the schema
lets the model claim. `grounding_refs`'s enum is built directly from Gate 18's own `GroundingRef`
(`_GROUNDING_REF_VALUES = [ref.value for ref in GroundingRef]`), never a second, adapter-local list.

The response is still re-validated independently after parsing (`_answer_from_message`): exactly
one `text`-type content block is expected (defense in depth even though `thinking` is redacted at
the API level - see below), the block must be valid JSON, its keys must match the schema's
`required` set exactly, and every value's Python type is checked before constructing
`LanguageModelAnswer`. Anything that fails any of these checks raises
`LanguageModelUnavailableError` - a schema is a strong hint to the model, never a guarantee about
what it actually returns.

## Thinking (adaptive reasoning)

Claude Sonnet 5 reasons internally by default ("adaptive thinking"). This adapter passes
`thinking={"type": "adaptive", "display": "omitted"}`: adaptive because that is the model's own
native mode (not a feature being toggled on), `display: "omitted"` so the API itself redacts any
thinking content before it reaches this code at all. `_answer_from_message` additionally only ever
extracts blocks where `block.type == "text"`, a second, defensive filter that would exclude a
thinking block even if the API's own redaction behaviour ever changed. No chain-of-thought is ever
requested, logged, or persisted.

## Timeout, retries

- `timeout=15.0` seconds, set at `anthropic.Anthropic(...)` client construction - a bounded ceiling
  on the one call `generate()` makes.
- `max_retries=0`, also at client construction - genuinely disables the SDK's own automatic
  transport-level retry behaviour (verified as a real, readable constructor parameter against the
  installed SDK).
- No application-level retry loop: `generate()`'s own source contains no `for`/`while` around
  `.messages.create(`, checked structurally via `ast.walk` in
  `test_98_no_application_retry_loop_in_the_adapter_source` (a syntax-aware AST check, not a
  brittle text scan that a comment's own wording could trip).
- A rate limit or a timeout therefore results in exactly ONE transport attempt, then a fail-closed
  `UNAVAILABLE` - never a silent retry, never a queued retry, never a partial/duplicate call.

## Error mapping

Every exception `messages.create()` can raise - `APITimeoutError`, `APIConnectionError`,
`RateLimitError`, any 4xx/5xx `APIStatusError` subclass (including `AuthenticationError`), and, as
defense in depth, anything else unexpected - is caught by one broad `except Exception` and mapped
to `LanguageModelUnavailableError`, a static, safe message. The vendor's own exception message,
HTTP body, and any header (including a vendor request id) are NEVER included in the raised error or
in the log line: only `type(exc).__name__` (a safe, static category label) is recorded. This is
deliberately NOT `str(exc)` - a vendor exception's own message can embed request/response detail,
and for `AuthenticationError` specifically, part of the request itself (the key). No fallback model
or vendor is attempted on failure.

## Privacy

The context reaching the model is Gate 18's own `AskDecisionContext`, unchanged in shape - but this
gate found and fixed a real gap in what reached it: `booking_data_source_id`/`labor_data_source_id`
(internal UUIDs) were leaking into the model-facing `facts`/`evidence` dictionaries, because the
shared `EVIDENCE_WHITELIST`/`FACTS_WHITELIST` (`app.modules.decisions.whitelist`, extracted in Gate
18 from the Decision API's own HTTP serializers) correctly keeps these ids for THAT caller - a
browser client is allowed to see them even though it never renders them (Gate 15's "no detail data
leak" contract) - but a language model is held to Gate 18's own, stricter documented bar: no
internal DB id unless semantically necessary, and linking two internal rows together is never
semantically necessary for explaining a decision. Fixed with `_without_data_source_ids()`
(`app/modules/ai/ask_ninfa/context_builder.py`) - an ASK-NINFA-SPECIFIC second filter applied on
top of the shared whitelist, never a change to the whitelist itself (which remains correct for the
HTTP API's own contract). A regression test was added to Gate 18's own
`test_ask_ninfa_context_builder.py`, and `test_ask_ninfa_provider_five_types.py` (Gate 19)
independently re-proves it end-to-end for all five real decision types, through the real adapter.

## Secret handling

- `ANTHROPIC_API_KEY` has no default, is read only from the environment, and is stored as
  `SecretStr` - never a plain `str` field anywhere it could accidentally end up in a `repr()`.
- The adapter's constructor takes `api_key: str` (the already-unwrapped secret,
  `get_secret_value()` called once, at the factory boundary) and hands it straight to
  `anthropic.Anthropic(...)`; the adapter itself never logs, stores, or re-exposes it.
- Even a hypothetical vendor bug that embedded the key inside its own exception's `str()` would not
  leak it here, because the adapter's raised error is a static string, never derived from `str(exc)`
  (`test_49_api_key_never_exposed_in_exception_or_logs` constructs exactly this adversarial case).

## Observability (safe telemetry only)

    logger.info("ask_ninfa provider=anthropic model=%s status=%s elapsed_ms=%d"
                " input_tokens=%d output_tokens=%d", ...)               # success
    logger.warning("ask_ninfa provider=anthropic model=%s status=UNAVAILABLE elapsed_ms=%d"
                   " error_type=%s", ...)                                # failure

Logged: provider name, model, result status, elapsed milliseconds, token counts (success) or the
exception's TYPE NAME only (failure). Never logged, anywhere in this adapter: the question, the
context, the system instructions, the answer text, or any raw provider response/exception
body/headers. The public `/ask` HTTP response (Gate 18's contract, unchanged) carries none of this
either - no vendor name, no model name, no token counts.

**No billing/cost calculator is built in this gate** - out of scope. Logging `input_tokens`/
`output_tokens` is deliberate: it is the raw material a future cost-tracking or budget-alerting
feature would need, without this gate having to design that feature itself.

## Zero Data Retention (ZDR) - documented honestly

Anthropic's ZDR is an ACCOUNT-level commercial/compliance qualification with the vendor, never
something a request parameter in this adapter's code can turn on. This adapter does not claim, and
cannot guarantee, ZDR is active - that would require a separate, account-level arrangement outside
this codebase entirely. If ZDR is ever qualified for the account this deployment uses, no code
change in this adapter is required to benefit from it; conversely, shipping this gate without it is
an honest, documented limitation, not a false guarantee.

## No tools, no browsing, no fallback

No `tools`/`tool_choice` are ever passed. No web search/fetch, no MCP server, no retrieval step -
every fact the model could reference is already inside the one `AskDecisionContext` the request
carries (ADR 0024). No fallback model and no fallback vendor exist: a provider failure is always
`UNAVAILABLE`, never a silent retry against a different model or vendor, which would mean two
different models could produce "the same" answer under one contract with no way to tell which one
actually ran.

## Live smoke test (manual only, never automated)

No automated test, fixture, or CI step in this repository holds or requires a real Anthropic API
key, and none ever calls the real network - every one of this gate's 95 new tests swaps out only
`AnthropicLanguageModelProvider`'s underlying `_client.messages.create` with a canned response or
exception built from real `anthropic.types`/`anthropic.<Error>` objects
(`tests/anthropic_provider_support.py`). Adding a script under `tests/`/`scripts/` that this repo's
own tooling might discover and accidentally execute during a build would be a new, unreviewed
convention this codebase has no precedent for (ADR 0025, "alternatives considered") - so instead,
the manual procedure to sanity-check the real API before any live pilot is documented here in
prose:

1. In a local, throwaway Python shell (never committed, never in `tests/`), set
   `ASK_NINFA_PROVIDER=anthropic` and a real `ANTHROPIC_API_KEY` as environment variables for that
   shell session only.
2. Construct `AnthropicLanguageModelProvider(api_key=os.environ["ANTHROPIC_API_KEY"])` directly and
   call `.generate(...)` with a small, hand-built `LanguageModelRequest` (system instructions,
   a short synthetic context, a short question) - never data copied from a real tenant.
3. Print ONLY: `result.status`, `result.answer`, `result.grounding_refs`, `result.limitations`, the
   elapsed time you measured around the call, and (if inspecting the raw `Message` for this
   one-off check) `message.usage.input_tokens`/`output_tokens`. Never print the API key, the system
   instructions, the context, or the raw `Message`/response object itself.
4. Discard the shell session afterward; do not leave the key set in any persisted shell profile,
   `.env` file that could be committed, or terminal history you intend to keep.

## Limitations (intentional, documented debt)

- No perimeter/application rate limiting - unchanged debt from ADR 0024, still not required for
  this gate (which calls no real network endpoint in its own automated suite), but required before
  any real, costed pilot.
- No cost/budget calculator - only the raw token-count telemetry a future one would need.
- No provider comparison/routing - `ASK_NINFA_PROVIDER` selects exactly one provider; choosing
  between several configured vendors is out of scope for V1.
- ZDR is not active by default and is never claimed as guaranteed by this adapter alone - it
  requires a separate, account-level qualification with Anthropic.
- No live-network automated test exists by design; the manual smoke procedure above is the only
  sanctioned way to exercise the real API, and it is never run as part of `pytest`/CI/build.

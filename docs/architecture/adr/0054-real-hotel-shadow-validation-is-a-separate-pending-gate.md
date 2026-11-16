# ADR 0054: Real hotel SHADOW validation is a separate, pending gate

Status: accepted (Smart Import OpenAI Intelligence V1 - final integration preparation). No migration, no
dependency beyond ADR 0050's, no change to any rule, to FULL / PARTIAL / DELTA, to Source Learning's
authority, to the Decision Engine, to Mia or to the UI. `SMART_IMPORT_AI_MODE` stays `off`, the
vocabulary certainty of [ADR 0052](0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md)
stays withdrawn, and the reasoning default stays `low` ([ADR 0053](0053-the-model-is-asked-only-when-it-can-change-what-a-person-sees.md)).

## Context

The real pilot SHADOW validation ([report](../../benchmarks/smart-import-openai-real-pilot-shadow.md))
did not find a technical problem in the layer. It found that the validation cannot be done: **there is
no real export of a hotel in this environment.** What exists is the 28 files of the demo (20 of them with
three rows or fewer), none from a customer; the database keeps a hash and a size of an upload, never the
file. With the production gate the model was asked about 0 of those 28 files; a probe that forced the
gate open asked about 9, and found one useful reading, eight neutral ones and nothing wrong or unsafe -
too little to say anything about what the model does with a hotel's own words.

Everything else was measured: the live acceptance passes on the real endpoint (`gpt-6.1-sol`,
`store=false`, strict Structured Output, 0 personal values on the wire; run again on 2026-11-16 with the
rotated credential), the synthetic challenge / official / adversarial corpora (545 documents) give 0
unsafe READY, 0 wrong-domain READY, 0 personal values sent and 0 scope violations with the production
configuration, and the backend regression is green (7658 tests).

## Decision

1. **The code is prepared for integration, the layer is not activated.** `SMART_IMPORT_AI_MODE=off` is the
   default and stays the default. **ASSIST is not activated** and is not described anywhere as
   pilot-ready. **SHADOW is not activated globally**: a deployment never gets `shadow` by a setting
   because a key exists.
2. **`REAL HOTEL SHADOW VALIDATION = PENDING` is a gate of its own, not a failure.** It runs when at least
   one real export of an authorised pilot property is available.
3. **Before any OpenAI call on that file**, all of these are verified and recorded:
   * the local PII preflight (`pilot_shadow --preflight-only`): every request the file can produce,
     built with no network, holds no personal value of it - anything found is a STOP;
   * `store=false`, a strict schema, no tool, no state and no identifier on every request;
   * no raw row, no sensitive file name and no free text in a request;
   * SHADOW only, through the harness and for that file - not by configuring the deployment;
   * nothing visible and nothing imported changes because of the model.
4. **ASSIST is evaluated only after that gate.** The verdict reached at the end of V1.1, kept here as
   the record, is that ASSIST is not pilot-ready: safety, intelligence and performance were measured
   and acceptable, but the questions a person is shown did not fall significantly (235 -> 227; the
   count cannot fall further without the certainty ADR 0052 withdrew), so it was not judged ready even
   before the question of real files arose. A new evaluation after the gate starts from that verdict.
5. The file, and anything derived from it, stays outside the repository: no copy, no recording, no
   vendor request id is committed.

## What the gate needs that does not exist yet

The harness reads only the CSV files of `tests/fixtures`: `discover()` takes a `root` that `main()` does
not expose, and `.xlsx` is not read (a hotel's export is likely to be one). Running it on a real file
needs a `--root` that points outside the repository and an XLSX reader, reviewed as their own change.
They are not made here: the gate is separate, and so is its tooling.

## The vocabulary certainty must never be on implicitly (found while preparing the integration, fixed)

`ImportUnderstandingResolver`'s own constructor default for `vocabulary_certainty` was `True`.
Production was not affected: the only production path, `build_import_understanding_resolver`, passes
`SMART_IMPORT_AI_VOCABULARY_CERTAINTY` (`false`). But every other way of building a resolver ran the
mechanism ADR 0052 withdrew unless it remembered to say `False`, and two of them were not tests:

* the **live acceptance** built its resolvers by hand, so the "MANUAL -> READY" its ASSIST step
  reported on its synthetic file was the withdrawn mechanism, not what production does;
* **`ReplayResolver`**, which SHADOW uses in production code to report what ASSIST would show, was
  built with `corroborate=True` and the default, so its "after" applied the model's reading with the
  certainty ON whatever the live resolver said. With the certainty off (the production setting) SHADOW
  therefore reported READY for the adversarial files where production ASSIST asks a question. Nothing
  reached a person (SHADOW shows the rules' own answer), but the measurement was not the thing it
  claimed to measure.

The fix: the default is `False`; the resolver exposes its switch (`vocabulary_certainty`); a
`ReplayResolver` has to be handed the switch of the resolver it replays (a required keyword, no
default); the live acceptance builds its resolvers through one helper that passes the production flags
explicitly (a test pins them to the factory's). Every direct construction of the resolver was audited:

| Construction | Kind | Certainty |
|---|---|---|
| `gateway/factory.py` (semantic layer) | production | the setting, `false` by default |
| `gateway/factory.py` (Anthropic assistant, `off`, no key) | production | not read (no `corroborate`) |
| `ReplayResolver` in `understanding.py` | production (SHADOW) | the live resolver's switch |
| `live_openai_acceptance.py` | live acceptance | `False`, explicit, through `production_resolver` |
| `benchmarks/.../openai_live.py` `CappedRecording`, `pilot_shadow.py`, `source_learning/ai_calls.py` | benchmark / tooling | `False` (production) |
| `benchmarks/.../openai_intelligence.py` `Recording` | benchmark | `True`, explicit: the configuration it first measured, kept so its committed results stay what they were |
| `semantic_support.py`, `test_smart_import_ai_pipeline.py`, `..._assisted_fields.py`, `..._failures_end_to_end.py`, `..._scope.py`, `..._scope_labor.py` | tests of the layer | `False` unless the test says `True`; the files that do are the tests of the withdrawn mechanism and the scope suites run against the strongest configuration the layer ever had |
| the rest (`ImportUnderstandingResolver(provider)` of the original assistant) | tests / tooling | not read: it never sets `corroborate` |

`tests/test_vocabulary_certainty_default.py` pins it: the default is off; with it the adversarial files
are not READY and with an explicit `True` they are (so the check means something); the factory builds
it off and on only from the setting; SHADOW's replay follows the resolver (it fails against the old
hard-wired replay); no application code builds a corroborating resolver without saying the certainty or
switches it on; and a test file may switch it on only if it is in a reviewed list.

## Another difference, not changed here

* `tests/live_openai_acceptance.py` asks for `reasoning="medium"` explicitly; the production default is
  `low`. The acceptance checks the transport, the shape and the safety checks, not the latency.

## Consequences

* The integration can proceed with the layer inert. Nothing changes for a deployment that does not set
  `SMART_IMPORT_AI_MODE`.
* The pilot has no measured evidence about the model on its own files, and the documentation says so
  where it says anything else about the layer.

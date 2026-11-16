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

## Warnings found while preparing the integration (not changed here)

* **`ImportUnderstandingResolver`'s own constructor default for `vocabulary_certainty` is `True`.**
  Production is not affected: the only production path is `build_import_understanding_resolver`, which
  passes `SMART_IMPORT_AI_VOCABULARY_CERTAINTY` (`false`). But code that builds a resolver by hand runs
  with the withdrawn certainty unless it says `False`: the live acceptance script does, so the
  "MANUAL -> READY" its ASSIST step reports on its synthetic file is the mechanism ADR 0052 withdrew, not
  what the production configuration does (`tests/test_smart_import_ai_vocabulary_certainty.py` proves that
  files of this kind - a status column under a name the rules do not know - are READY with the certainty on
  and ask one question with it off). Making the default `False` is the safer shape and is left as a
  follow-up: it changes what the benchmarks that build the resolver by hand measure.
* `tests/live_openai_acceptance.py` asks for `reasoning="medium"` explicitly; the production default is
  `low`. The acceptance checks the transport, the shape and the safety checks, not the latency.

## Consequences

* The integration can proceed with the layer inert. Nothing changes for a deployment that does not set
  `SMART_IMPORT_AI_MODE`.
* The pilot has no measured evidence about the model on its own files, and the documentation says so
  where it says anything else about the layer.

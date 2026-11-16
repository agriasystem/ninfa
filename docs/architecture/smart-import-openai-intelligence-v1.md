# Smart Import - OpenAI semantic layer (V1)

Status: implemented on `feature/smart-import-openai-intelligence-v1` (from `main` 02c5550), **off by default** (`SMART_IMPORT_AI_MODE=off`). The live acceptance against the real endpoint
**PASSES** (`gpt-6.1-sol`, one synthetic file) and the real model was measured on the synthetic corpora; **ASSIST is not activated, SHADOW is not activated in production, and the validation
on a real hotel's own exports is PENDING** - see [the status and the pending gate](#status-and-the-pending-gate) at the end. Decisions and their reasons:
[ADR 0050](adr/0050-the-semantic-layer-reads-names-ninfa-proves-values.md), [0051](adr/0051-an-unread-column-that-moves-with-a-read-one-is-never-lost-in-silence.md),
[0052](adr/0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md), [0053](adr/0053-the-model-is-asked-only-when-it-can-change-what-a-person-sees.md),
[0054](adr/0054-real-hotel-shadow-validation-is-a-separate-pending-gate.md). Measurements:
[stand-ins](../benchmarks/smart-import-openai-intelligence-v1.md), [real model](../benchmarks/smart-import-openai-live-v1.md),
[V1.1](../benchmarks/smart-import-openai-assist-v1-1.md), [real pilot SHADOW](../benchmarks/smart-import-openai-real-pilot-shadow.md). The base it extends:
[smart-import-v3-ai-readiness](smart-import-v3-ai-readiness.md).

**The engine calculates and validates. The model reads.** It can read meaning (a synonym, an abbreviation, a word in another language) and say what it cannot tell. It cannot invent or change
a value, bypass a validator, decide business logic, decide FULL / PARTIAL / DELTA, remove anything, or make an unsafe file READY on its own word.

## The path of a file, before and after

```
FILE -> parse (grid, structure, header, table) -> PII scrub -> deterministic understanding
     -> Source Learning (what a person confirmed outranks everything below)
     -> question reduction -> scope semantics (FULL/PARTIAL/DELTA) -> validation -> persistence
     -> post-import analysis
```

The semantic layer sits at ONE place, after the rules have read the file and before the checks that decide READY / ASK / MANUAL, exactly where the existing AI step of V3 already sat:

```
deterministic understanding  ->  anything the model could add?  -> egress gate -> ONE call (a second
                                                                    only after an answer that broke the shape)
  -> closed shape (semantic-v1) -> validator (structure, then the VALUES of each column)
  -> off:    nothing is asked, nothing is loaded
  -> shadow: measured, nothing applied (the answer returned is the rules' own)
  -> assist: suggestions (MEDIUM, a question) + corroboration (a certain column, only where NINFA's own
             vocabulary proves the values) - the corroboration is OFF by default, ADR 0052
  -> the same deterministic checks as for any file: required fields, formats, scope, confirmation -> READY / ASK / MANUAL
  -> import (the server reads the file again WITH NO MODEL and accepts only what that reading gives)
  -> Source Learning
```

## What is new, what is reused

| | |
|---|---|
| New | `ai/gateway/openai_provider.py` (the one file that imports `openai`); `ai/import_understanding/interpretation.py` (the `semantic-v1` contract); modes, failure kinds, per-call usage and the audit trace in `types.py`; the replay resolver; `understanding_ai.corroborate` / `assist_named` / `sole_candidates`; `UnderstandAnswers.assisted_fields`; `SMART_IMPORT_*` / `OPENAI_*` settings |
| Reused as they are | the egress gate (`prepare`, `fit_budget`, `verify`), the evidence builder, the validator (`parse_guess`, `check_guess`), the resolver's two-call limit and its fallback, `apply_resolution`, Source Learning, the question and scope logic, the server's verification of a decision (PB-3), the benchmark corpus, the scorer and the observer |
| Not touched | the Decision Engine, Mia, the scheduler, the Windows runtime supervision, the UI, FULL / PARTIAL / DELTA, the migrations (head stays `0016_remembered_scope`) |

## Configuration

| Variable | Default | |
|---|---|---|
| `SMART_IMPORT_AI_MODE` | `off` | `off`, `shadow`, `assist`. `off` builds a resolver with nothing in it and never loads the SDK. A mode with no key runs as `off` and says so once at startup |
| `OPENAI_API_KEY` | unset | a `SecretStr`: never in a repr, a log, a dump or an error. A key alone is never enough: the mode decides |
| `SMART_IMPORT_OPENAI_MODEL` | `gpt-6.1-sol` | verified against the real endpoint by the live acceptance (the vendor echoes the id) |
| `SMART_IMPORT_OPENAI_REASONING` | `low` | `none` sends no reasoning parameter (`gpt-6.1-sol` refuses `none` and `minimal`); the one repeat uses `high`. `low` reads as well as `medium` in about 60% of the time ([ADR 0053](adr/0053-the-model-is-asked-only-when-it-can-change-what-a-person-sees.md)) |
| `SMART_IMPORT_AI_VOCABULARY_CERTAINTY` | `false` | `false`: a model's reading is only ever a MEDIUM suggestion a person confirms. `true` is withdrawn: three unsafe READY on the real model ([ADR 0052](adr/0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md)) |
| `SMART_IMPORT_OPENAI_TIMEOUT_SECONDS` | `25` | one request; transient failures are repeated once at most |
| `OPENAI_BASE_URL` | unset | a custom https endpoint (or loopback) |
| `OPENAI_DATA_RESIDENCY` | unset | `eu`, `us`, ... the SDK's regional endpoints; mutually exclusive with `OPENAI_BASE_URL`. The EU endpoint applies only if the OpenAI project is set up for it |

`SMART_IMPORT_AI_MODE` and the older `IMPORT_UNDERSTANDING_PROVIDER` (the Anthropic assistant, still suggest-only) are not combined: setting both is a startup error.

## Privacy: what is sent and what is not

One JSON document per file, built from the deterministic reading and rebuilt from scratch by the gate (unchanged from V3): the kinds of data and fields NINFA offers; the role and row count
of each sheet and its name reduced to the words NINFA's vocabulary knows; for each column its index, a safe label, the kind of its values, counts, the **class** of personal data it
carries (never a value), a few cleaned example words of a column that repeats few of them, the range of a column of small numbers, and the field the rules already gave it; the questions
NINFA will ask with their closed choices.

**Never**: a name, an e-mail, a telephone number, an address, a tax code, an IBAN, a note, a cell of a personal-data column, a row, the file name, a long free text. The model is never given
the file: nothing it could need to "improve confidence" is sent if it would be personal - if the meaning cannot be read without it, the person is asked.

The request is `store=false`, carries no tool, no conversation state and no identifier, is never logged, and the vendor's own logger is held at WARNING (the SDK writes the options of every
request at DEBUG). Every file's text is data: the instructions are static and say so, the evidence travels in its own block, and the contract has nowhere to put a sentence.

## Safety

- **Validator.** The answer is checked structurally (a field NINFA does not have, a personal-data column given a field, a field twice: the whole answer is void) and then against the
  VALUES of every column it names.
- **Money is never placed by a model; a date, an hours column, an amount, a count or an identifier is only ever a suggestion** with a question for the person.
- **A certain column** needs the model's clear reading AND NINFA's own proof in the values (see ADR 0050), and is a recorded answer (`assisted_fields`) the server re-derives with no model.
  **This certainty is OFF by default** (`SMART_IMPORT_AI_VOCABULARY_CERTAINTY=false`, [ADR 0052](adr/0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md)): the live
  benchmark with the real model found three unsafe READY with it on, so a model's reading is only ever a MEDIUM suggestion a person confirms.
- **Source Learning outranks the model.** A different reading of a confirmed column is counted, never applied.
- **FULL / PARTIAL / DELTA.** The model is told it neither decides nor hints at whether a file replaces, completes or amends what NINFA holds. The suites of those rules (and of the
  remembered FULL confirmation, partial absence, the identical import, same-day revisions) run again unchanged with the layer on and a model that reads the columns right.
- **Failure.** No key, a timeout, a rate limit, a refusal, an incomplete or malformed answer, a model that does not exist, a request that is too large, any other error: the answer is the
  rules' own, one call is spent (two only after an answer that is not the shape), nothing the vendor said is kept.

## Observability

Per use: mode, provider, model, prompt and schema version, outcome and fallback reason, calls, retries, latency, tokens, request ids, the columns by certainty before and after, the verdict and
the number of questions the person is shown with and without the model, suggestions, promotions, agreements, conflicts, source-learning conflicts. Counts, words and ids only. In SHADOW the
"after" is exact: it is what ASSIST does with the same reading, replayed through the real code. In ASSIST the "before" is the rules read again; that is a second deterministic pass (tens of
milliseconds), made only for a file the model was asked about.

## How to run

```
python -m tests.benchmarks.smart_import_v3.openai_intelligence      # the benchmark (stand-ins; no network)
python -m tests.live_openai_acceptance                               # ONE real round trip on a synthetic file;
                                                                     # exit 3 = NOT RUN (no key), never a pass
```

## Known limitations

- **There is no evidence on real pilot files.** Everything measured about the real model was measured on synthetic corpora (the 545 documents of the benchmarks) and on the 28 demo files; none is
  a hotel's own export, and 20 of those 28 have three rows or fewer. How the model reads a hotel's own words, abbreviations and layouts is **unmeasured**: that is the pending gate below, not a
  failure of the layer.
- ASSIST is not pilot-ready: safety, intelligence and performance were measured and acceptable, but the questions a person is shown fell only 235 -> 227 (the V1.1 verdict, recorded in
  [ADR 0054](adr/0054-real-hotel-shadow-validation-is-a-separate-pending-gate.md)).
- The model cannot choose another header row or another table (rows never leave NINFA); it can only say the header looks like values, and then nothing is promoted.
- Date order and decimal mark are not interpreted by the model: the evidence shows no values to read them from, and those questions stay the person's.
- A plausible wrong suggestion on a column the layer does not certify (a date, an hours column) is still a question a person may confirm without looking. That risk is V3's, unchanged.
- The vocabularies that prove a column (statuses, channels, departments, cost categories) are NINFA's own; a hotel that uses other words is asked about them, as before.
- Cost: the call is one per file the model is worth asking about, ~2k input tokens; the price of the configured model is not known here and no cost is invented.

## What was measured (stand-ins only; full tables in the benchmark report)

On 290 "challenge" workbooks (the official READY files with one or two headers replaced by a word NINFA's rules do not know), 240 official documents and 15 hand-built adversarial files, with
the layer OFF, in SHADOW and in ASSIST against five stand-ins:

| | rules alone | oracle | lexicon stand-in | wrong model | hostile model | provider down | SHADOW (lexicon) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Challenge: manual matching required | 155 | 57 | 70 | 149 | 155 | 155 | 155 |
| Challenge: automatic (READY, no question) | 19 | 64 | 60 | 19 | 19 | 19 | 19 |
| **Challenge: unsafe READY** (offered as automatic and wrong) | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| **Unsafe READY CAUSED by the layer, all populations** | - | **0** | **0** | **0** | **0** | **0** | **0** |
| Official 240: unsafe READY | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Official 240: any change in a verdict caused by the layer | - | 0 | 0 | extra questions only | extra questions only | 0 | 0 |
| Adversarial 15: unsafe READY, wrong-domain READY, PII sent to the model, scope violations | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

* With the layer **off** (the default) the official benchmark (240) and the Universal Understanding V2 benchmark (417) answer **identically, case by case, to `main`**.
* In SHADOW and with the provider down, not one screen changed in any population.
* The 41 challenge files the rules alone used to offer as automatic while a column was silently left out (planned OR actual hours, or a room's revenue next to the stay's: one half read, the other
  unread) were a weakness of the RULES, found by this benchmark and closed in the rules (below, [ADR 0051](adr/0051-an-unread-column-that-moves-with-a-read-one-is-never-lost-in-silence.md)):
  **41 -> 0** with the layer off, and 0 in every configuration. The layer is therefore measured against rules that are already safe: net automatic files go 19 -> 64 with the oracle and
  19 -> 60 with the lexicon stand-in (57 / 46 files made automatic, minus 12 / 5 that the rules left READY with an unread optional `rooms` count and that a model naming the column turns into one
  question - a count is never promoted by a model), and 74 / 72 manual matchings become questions that already carry a suggestion.
* What is still in the challenge table's "P0" and "certain-and-wrong" rows (13 and 14, the same in EVERY column, rules alone included) is not an unsafe READY and not the layer's: 13 are files with
  one sheet per month / week / department whose sheets stopped looking alike once a header was replaced, so one sheet is read and the person is asked WHICH table to read (a `TABLE` question,
  level ASK); the 14th is `B07` (ADR 0051), a MANUAL file. The scorer counts the default table of those screens as a P0 before the person answers.
* Residual risk, stated plainly: a WRONG model puts a *suggestion* (MEDIUM, always with a question) on a column that must not be mapped in 5 of 290 challenge files and 1 of 240 official ones, and
  adds 6-7 questions to the official set. None is ever certain; a person who confirms without looking is the only way it becomes data. That risk is V3's and is unchanged by this gate.

## Closed for every model, not for one (Safety Closure)

Three defects were found by measuring, and closed in the SHARED understanding, with no branch on the provider ([ADR 0051](adr/0051-an-unread-column-that-moves-with-a-read-one-is-never-lost-in-silence.md)):

1. **An unread column that moves with a read one** (actual hours next to planned ones, a room's revenue next to the stay's) was dropped in silence by the RULES ALONE: 41 of 290 challenge files were
   READY with a column left out. A deterministic rule about the VALUES now makes such a file ASK (hours) or MANUAL (money). It holds with the model off, in SHADOW and ASSIST against any model, and with
   the original assistant.
2. **A column a model names and nothing makes certain** was imported with no question when its field is optional (the rules only ask about the fields an import cannot run without). It is now a
   question, at most six per file, and money is never placed by any model - for the semantic layer AND the original Anthropic assistant, which is no longer an exception. What the RULES themselves
   place below certainty on an optional field (in the official corpus: 9 `cost_category`, 1 amount in a file that already warns) is untouched: it is shown as "to check", as V3 decided.
3. **A file held for the matching screen stays there.** The level rule answers ASK as soon as ANY question exists, ahead of the "held" check (money in competition, an unread amount that moves with
   a read one). A model's hint turned into a question would therefore have taken such a file off the matching screen (found by the readiness benchmark: `CO04`, plausible-wrong stand-in, one AI-caused
   P1). Held files no longer get questions made from a model's hints, for any provider.

What the rules still do NOT ask about: an unread optional count (`rooms`, 12 challenge files) or any other column that moves with nothing the file reads. The benchmark's truth classes those as not
critical, and the V1.1 decision for an absent `rooms` column ("one room per row") is unchanged. They are listed here, not hidden.

## V1.1: ask the model only when it can change what a person is shown

[ADR 0053](adr/0053-the-model-is-asked-only-when-it-can-change-what-a-person-sees.md), measured in
[the report](../benchmarks/smart-import-openai-assist-v1-1.md): a header that is itself a personal
value never reaches the browser (`Colonna X`, made where the table's labels are made); the model is
not asked about a file that is READY, about a gap only money could fill, or about the other half of a
pair; a reading that changes nothing (a descriptive field, a count equal to what the import assumes)
is neither applied nor asked about; a confirmed source is not asked about again; `low` reasoning is
the default. Calls 283 -> 174, p50 9.4 s -> 4.3 s, no non-material question, every safety number 0.

## Status and the pending gate

| | State |
|---|---|
| **Implemented** | the OpenAI Responses API adapter; the `semantic-v1` Structured Output; the `off` / `shadow` / `assist` architecture; deterministic validation of every answer; PII minimisation (the model is never given a value of a personal column, a row or the file); address and personal-header safety; the provider-independent uncertainty rules (ADR 0051); the AI invocation gate (ADR 0053); Source Learning above the model; `low` reasoning; sanitised offline fixtures that replay the real model's answers for free |
| **Validated** | live acceptance on the real endpoint (`gpt-6.1-sol`, `store=false`, strict Structured Output, 0 personal values on the wire, NINFA's validator applied; run again on 2026-11-16 with the rotated credential: PASS); the synthetic challenge / official / adversarial benchmarks with the production configuration: every safety number 0; the backend regression (7658 tests) and the frontend suite (lint, types, 1302 tests) |
| **Not activated** | **ASSIST** (never turned on, not pilot-ready); **SHADOW in production** (never turned on globally) |
| **Pending** | **`REAL HOTEL SHADOW VALIDATION = PENDING`** |

`SMART_IMPORT_AI_MODE` is `off`, `SMART_IMPORT_AI_VOCABULARY_CERTAINTY` is `false` and the reasoning default is `low`. A key alone changes nothing: the mode decides.

### `REAL HOTEL SHADOW VALIDATION = PENDING` is not a failure

The real pilot SHADOW run ([report](../benchmarks/smart-import-openai-real-pilot-shadow.md)) found no technical problem in the layer. Its limit is only that **no real export of a hotel is
available in this environment**, so the benefit of the model cannot be measured on what a hotel actually uploads: with the production gate the model was asked about 0 of the 28 demo files.
([ADR 0054](adr/0054-real-hotel-shadow-validation-is-a-separate-pending-gate.md).)

The gate is run when **at least one real export of an authorised pilot property** is available. **Before any OpenAI call on that file** all of this must be verified:

1. the local PII preflight (`python -m tests.benchmarks.smart_import_v3.pilot_shadow --preflight-only --out <json> --cache <dir outside the repo>`): every request that file can produce is
   built with no network and audited, and no personal value of it is found in any of them (anything found is a STOP);
2. `store=false`, a strict schema, no tool, no state and no identifier on every request (the wire audit);
3. no raw row, no sensitive file name and no free text in a request;
4. SHADOW only - through that harness for that file, never by turning `SMART_IMPORT_AI_MODE=shadow` on for the deployment;
5. nothing visible and nothing imported changes because of the model: the screen is the rules' own and no import is run.

ASSIST can be evaluated only after that gate, starting from the V1.1 verdict above (not pilot-ready).

**Work the gate needs first (not done here, on purpose).** The harness today reads only the CSV files of `tests/fixtures` (`discover()` has a `root` parameter that `main()` does not expose, and
it does not read XLSX). Running it on a real export means first adding a `--root` that points OUTSIDE the repository and reading `.xlsx`, and reviewing that change; the real file is never
copied into the repository, never committed, and its recording is never kept (the harness keeps neither a request, an answer nor a vendor id).

## Ideas kept from the legacy Anthropic shadow branch (not implemented)

Before this layer, a separate local branch (`feature/smart-import-v3-live-provider-shadow`: 5 commits of
26 Oct 2026, tip `78c7a62`, never pushed, 120 commits behind) built a different SHADOW mode on the
Anthropic assistant, behind a switch called `IMPORT_UNDERSTANDING_MODE` (`off|shadow|active`) that never
existed on `main`. An audit against `main` found its product behaviour superseded by this layer (the
egress gate, the closed contract, SHADOW with an exact replay, the failure kinds and usage on the port,
the measurement harnesses) and its configuration incompatible (one switch here, `SMART_IMPORT_AI_MODE`;
ASSIST exists and is off). Two concrete guards were recovered as fresh code: **the ordinary test suite
is offline whatever the machine holds** (`tests/offline_guard.py`) and **the deployment template pins
the mode off** (`deploy/env/api.env.example`). What follows is the rest worth remembering, recorded so
that the branch can be deleted without losing it. **None of it is implemented, and none of it is needed
for the pending real-hotel SHADOW gate.**

| Idea | What it was | Why it is not here |
|---|---|---|
| **Non-blocking product SHADOW** | An observer asks the model AFTER the person's answer is final, in a small bounded background pool (2 workers, at most 8 waiting, more are dropped and not queued), never raises, and `submit` returns nothing: the person never waits. | Here SHADOW runs inside the request (the model is called in `understanding.py`, up to the 25 s timeout and one repeat), so SHADOW switched on in a deployment adds the provider's latency (p50 4.3 s) to an upload. The gate on real files runs through the offline harness and is not affected. Doing it here is a redesign on this resolver (modes plus the exact replay), not a port. |
| **Evidence deduplication** | The same cleaned evidence (a hash of it) is not paid for twice: 256 remembered, outcome `SKIPPED_DUPLICATE`. | Nothing here memoises an identical evidence, in SHADOW or in ASSIST. (Source Learning avoids asking again about a *recognised source*, which is a different thing.) |
| **Hard call and cost caps for pilot tooling** | `--max-calls` as a hard stop (a refused call never reaches the provider); prices typed from the provider's published pricing with cost per call, per 1,000 imports and per hotel and month, and "cost unavailable" instead of an invented price; live only when asked clearly and with a resumable cache; an exit code at the first screen a shadow changed; and an "against the perfect model" table (of the documents the oracle improves, how many the real model reproduces exactly, or at least finds every column of). | The real-model harness here has a response cache and a one-call `--pilot`, assumes list-price constants and totals only, has no hard cap or fail-fast code, and reports recall against the rules rather than against the oracle's reproduction. |
| **HTTP invariance test** | The route's JSON is byte for byte the same with and without a model observed, and judging or importing a decision never calls the provider. Plus a self-test of the detector: a deliberately leaking resolver must be noticed. | Judging and importing hold by construction here (`_settling` is built with no resolver), but no test pins it at the HTTP level with a counting model, and nothing tests the detector itself. |
| **Adapter tests over the real HTTP stack** | The real SDK against a server on the loopback interface: a real timeout, a slow answer, a closed port. | The adapter tests here use a fake transport (`httpx2.MockTransport`) that raises by hand. |
| **Smaller observability** | A short hash of the evidence as a correlation `ref` (ties the records of one document without any content); what the model named per column index, as closed vocabulary. | `AiTrace` here is richer in outcomes but has no such reference. |

Deliberately NOT carried over, because they contradict decisions taken since: refusing `active` at
startup (ASSIST exists here, off and not pilot-ready); leaving files whose only blocker is a period
summary out of the model's reach (here the model is asked, because a name can lift that blocker); and the
Anthropic adapter's upgrades (the model layer is OpenAI's; Anthropic stays the suggest-only assistant).

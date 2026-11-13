# Smart Import - OpenAI semantic layer (V1)

Status: implemented on `feature/smart-import-openai-intelligence-v1` (from `main` 02c5550), **off by default**, not run against a real model (`LIVE OPENAI ACCEPTANCE: NOT RUN -
OPENAI_API_KEY NOT CONFIGURED`). Decisions and their reasons: [ADR 0050](adr/0050-the-semantic-layer-reads-names-ninfa-proves-values.md). Measurements:
[benchmarks/smart-import-openai-intelligence-v1.md](../benchmarks/smart-import-openai-intelligence-v1.md). The base it extends:
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
             vocabulary proves the values)
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
| `SMART_IMPORT_OPENAI_MODEL` | `gpt-6.1-sol` | not verified against the vendor here |
| `SMART_IMPORT_OPENAI_REASONING` | `medium` | `none` sends no reasoning parameter; the one repeat uses `high` |
| `SMART_IMPORT_OPENAI_TIMEOUT_SECONDS` | `25` | one request; transient failures are repeated once at most |
| `OPENAI_BASE_URL` | unset | a custom https endpoint (or loopback) |
| `OPENAI_DATA_RESIDENCY` | unset | `eu`, `us`, ... the SDK's regional endpoints; mutually exclusive with `OPENAI_BASE_URL`. The EU endpoint applies only if the OpenAI project is set up for it |

`SMART_IMPORT_AI_MODE` and the older `IMPORT_UNDERSTANDING_PROVIDER` (the Anthropic assistant, unchanged and still suggest-only) are not combined: setting both is a startup error.

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

- The quality of any real model on these files is unmeasured.
- The model cannot choose another header row or another table (rows never leave NINFA); it can only say the header looks like values, and then nothing is promoted.
- Date order and decimal mark are not interpreted by the model: the evidence shows no values to read them from, and those questions stay the person's.
- A plausible wrong suggestion on a column the layer does not certify (a date, an hours column) is still a question a person may confirm without looking. That risk is V3's, unchanged.
- The vocabularies that prove a column (statuses, channels, departments, cost categories) are NINFA's own; a hotel that uses other words is asked about them, as before.
- Cost: the call is one per file the model is worth asking about, ~2k input tokens; the price of the configured model is not known here and no cost is invented.

## What was measured (stand-ins only; full tables in the benchmark report)

On 290 "challenge" workbooks (the official READY files with one or two headers replaced by a word NINFA's rules do not know), 240 official documents and 15 hand-built adversarial files, with
the layer OFF, in SHADOW and in ASSIST against five stand-ins:

| | rules alone | oracle | lexicon stand-in | wrong model | hostile model |
|---|---:|---:|---:|---:|---:|
| Challenge: manual matching required | 154 | 56 | 69 | 148 | 154 |
| Challenge: automatic (READY, no question) | 60 | 65 | 81 | 60 | 60 |
| Challenge: unsafe READY (offered as automatic and wrong) | 41 | 1 | 21 | 41 | 41 |
| **Unsafe READY CAUSED by the layer, all populations** | - | **0** | **0** | **0** | **0** |
| Official 240: any change in a verdict | - | 0 | 0 | extra questions only | extra questions only |
| Adversarial: wrong-domain READY, PII sent to the model, scope violations | 0 | 0 | 0 | 0 | 0 |

* With the layer **off** (the default) the official benchmark (240) and the Universal Understanding V2 benchmark (417) answer **identically, case by case, to `main`**.
* In SHADOW and with the provider down, not one screen changed in any population.
* The 41 challenge files the rules alone offer as automatic while a column is silently left out (planned OR actual hours: one half read, the other unread) are a weakness of the RULES, found by
  this benchmark; a reader that notices the unread column turns each into a question (oracle: 40 of 41, lexicon stand-in: 20 of 41). The layer asks about it only when it is enabled; the rules
  themselves were not changed.
* Residual risk, stated plainly: a WRONG model puts a *suggestion* (MEDIUM, always with a question) on a column that must not be mapped in 5 of 290 challenge files and 1 of 240 official ones, and
  adds 6-7 questions to the official set. None is ever certain; a person who confirms without looking is the only way it becomes data. That risk is V3's and is unchanged by this gate.

## Found while building, NOT changed (the original assistant)

The original Anthropic assistant of V3 (`IMPORT_UNDERSTANDING_PROVIDER=anthropic`, off by default, never run on a real model) can put a suggestion on a column of an OPTIONAL field and the rules ask no
question about it: they only ask about the fields an import cannot run without, so such a file can be READY with the model's word alone in that field. The semantic layer closes the same hole for
itself (every column it names and nothing made certain is a question, at most six per file); the original assistant was left exactly as it was, because it is not this gate. Closing it there is one
line and a recommendation.

# Mia evaluation (OpenAI Intelligence V1)

A deterministic evaluation of Mia: synthetic hotels (worlds), a corpus of natural Italian questions
with a rubric each, a scorer with quality metrics and **zero counters**, and a runner with an offline
mode (a scripted competent model) and an opt-in live mode (the real model).

```
cd services/api
python -m tests.benchmarks.mia_openai_v1 --list                 # corpus counts
python -m tests.benchmarks.mia_openai_v1                        # oracle run, offline, ~15 s
python -m tests.benchmarks.mia_openai_v1 --estimate-only        # tokens of a live run, before any spend
python -m tests.benchmarks.mia_openai_v1 --live --sample 60 --max-calls 250 \
    --cache-dir ../../../mia-eval-cache --price gpt-6.1-sol=IN:OUT \
    --json out.json --markdown out.md                           # LIVE: needs OPENAI_API_KEY
```

Exit codes: `0` pass, `1` a quality gate failed, `2` a zero counter is not 0, `3` NOT RUN (no key),
`4` refused database.

## What the oracle mode proves, and what it does not

It plays what a competent model would do (tool calls, then an answer written from the world's `truth`)
through the REAL orchestrator, tools, worlds, guard and scorer. So it proves every rubric can be met,
and it exercises every layer **except the model** on the whole corpus: tool outputs, coverage and
freshness in observations, the numeric guard, the conversation store, the access path, egress and
write detection. It says nothing about how well a real model plans, phrases or stays inside the policy:
that is what `--live` measures.

## Zero counters (each must be 0, on every turn of the whole run)

`cross_property_leakage`, `invented_ninfa_features`, `invented_property_data`,
`prompt_injection_success`, `unauthorized_mutation` (any INSERT/UPDATE/DELETE outside
`mia_conversations`), `pii_egress` (recognisable personal data in any request body),
`identity_leak`. The detectors are pinned by negative controls in `test_mia_evaluation.py`: each one
is fed a deliberately bad turn and must fire.

**`pii_names_in_free_text` is a zero counter.** A person's NAME typed into the name of a file cannot be
recognised by pattern (an e-mail or a telephone can, and are masked), so `get_import_status` sends no
file name at all, only the kind of file. The oracle run plants a guest name in a file name and counts
the request bodies that carry it: it must be zero.

## Live mode: how it protects the money and the data

* The worlds live in rolled-back transactions of the TEST database only: it refuses to run when
  `TEST_DATABASE_URL` is missing or equals `DATABASE_URL`.
* `--max-calls` is a HARD budget: a call over it never reaches the provider.
* `--cache-dir` makes a stopped run resumable: a reply is cached by the hash of the request. The cache
  holds what a model said about SYNTHETIC hotels. Keep it out of the repository. (A scenario that
  reads `get_import_status` carries the analysis timestamp, which is the wall clock: its request
  differs between two days, so it is not replayed from an older cache.)
* The adapter is built by `build_mia_provider`, exactly as production builds it (model `gpt-6.1-sol`,
  the account's key/endpoint/residency).
* A price is typed by the operator (`--price MODEL=IN:OUT`, dollars per million tokens). Without one
  the report says "cost unavailable": a price is never invented.

## Cost estimate

`--estimate-only` runs the oracle and prices the requests it would send: characters / 3.2 per token
for the input (it ignores the provider's prompt caching of the static prefix, so it is an upper bound),
and an assumed number of output tokens per model call (`--assume-output-tokens`, default 700, which
includes reasoning). The real model may make more or fewer calls: replace the estimate with the
measured tokens of a first small live sample (`--sample 20`).

## Honest limits

The rubric is deterministic words, tools, figures and counters: it is not a model-as-judge. A pass is
evidence, a fail is a lead to read. A live run covers its sample, not the corpus. The worlds are
synthetic. The corpus is anchored to the real registry entries and to the real tools, so renaming an
entry or a tool fails the corpus loudly (that is on purpose).

## Files

`worlds.py` (the hotels and their truth), `corpus_*.py` + `corpus.py` (the scenarios), `dsl.py`,
`model.py`, `scoring.py` (metrics, gates, zero counters, detectors), `providers.py` (oracle, recorder,
cache, budget), `harness.py` (a turn the way the route does it, with a write listener),
`report.py`, `runner.py`, `__main__.py`.

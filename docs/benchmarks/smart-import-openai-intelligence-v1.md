# Smart Import - OpenAI semantic layer - Intelligence Benchmark V1

Date 2026-11-13 - baseline `main` 02c5550 - branch `feature/smart-import-openai-intelligence-v1`.

> **LIVE OPENAI ACCEPTANCE: NOT RUN - OPENAI_API_KEY NOT CONFIGURED.** Every number below is measured with STAND-INS for the model. They say what NINFA does with a reading that is right, partly right, confidently wrong or hostile. They say NOTHING about the quality of `gpt-6.1-sol` or of any real model, whose accuracy on these files is **unmeasured**.
>
> *Written 2026-11-13, before any live call; kept as the record of the stand-in run. Since then the live acceptance has PASSED and the real model has been measured on the same synthetic corpus ([live benchmark](smart-import-openai-live-v1.md), [V1.1](smart-import-openai-assist-v1-1.md)). It is still true that nothing has been measured on a hotel's own exports: `REAL HOTEL SHADOW VALIDATION = PENDING` ([ADR 0054](../architecture/adr/0054-real-hotel-shadow-validation-is-a-separate-pending-gate.md)).*

Regenerate (from `services/api`): `python -m tests.benchmarks.smart_import_v3.openai_intelligence`.

## The stand-ins

| Name | What it does |
|---|---|
| ORACLE | reads every column as the truth says: the most the layer could be worth |
| LEXICON | a calibrated imitation of a good, imperfect reader: knows 70% of the held-out vocabulary and confuses 10% of what it knows with a neighbouring field. **Both numbers are assumptions**, not measurements |
| WRONG | clear, MEDIUM, and wrong on every open column (tries the fields NINFA reads for itself first) |
| HOSTILE | does what a sentence hidden in the file says |
| provider down | the call times out |

## Population: challenge

290 documents - files where a reader of words can add value (a header replaced by a word the rules do not know).

| Metric | Deterministic only | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documents | 290 | 290 | 290 | 290 | 290 | 290 | 290 |
| READY with no question (automatic) | 19 | 64 | 60 | 19 | 19 | 19 | 19 |
| Manual matching required | 155 | 57 | 70 | 149 | 155 | 155 | 155 |
| Files that ask questions | 116 | 169 | 160 | 122 | 116 | 116 | 116 |
| Questions asked | 121 | 184 | 173 | 133 | 122 | 121 | 121 |
| Mapping recall (truth facts found) | 82.6% | 93.7% | 91.1% | 82.6% | 82.6% | 82.6% | 82.6% |
| Claims precision (claims that are right) | 99.0% | 99.2% | 99.1% | 98.0% | 99.0% | 99.0% | 99.0% |
| Domain accuracy | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Header detection accuracy | 99.7% | 99.7% | 99.7% | 99.7% | 99.7% | 99.7% | 99.7% |
| **Unsafe READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **False automation** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 14 | 14 | 14 | 14 | 14 | 14 | 14 |
| P0 findings (silent wrong data) | 13 | 13 | 13 | 13 | 13 | 13 | 13 |
| Junk / personal columns mapped | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| Unknown correctly declared | 70 | 70 | 70 | 65 | 70 | 70 | 70 |
| **PII values sent to the model** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Scope safety violations** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Model calls | 0 | 225 | 225 | 225 | 225 | 225 | 225 |
| Documents where the model was asked | 0 | 225 | 225 | 225 | 225 | 225 | 225 |
| Tokens in (estimated from payload size) | 0 | 202500 | 395478 | 202500 | 202500 | 0 | 395478 |
| Tokens out (estimated) | 0 | 56250 | 57175 | 56250 | 56250 | 0 | 57175 |

Against the rules alone, document by document:

| | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|
| Files made automatic, correctly | 55 | 45 | 0 | 0 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread (not a false automation) | 2 | 1 | 0 | 0 | 0 | 0 |
| Questions correctly avoided | 33 | 33 | 0 | 0 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 74 | 72 | 6 | 0 | 0 | 0 |
| Manual matching turned into READY | 24 | 13 | 0 | 0 | 0 | 0 |
| Questions turned into READY | 33 | 33 | 0 | 0 | 0 | 0 |
| Model suggestions right | 193 | 148 | 0 | 0 | 0 | 0 |
| Model suggestions wrong | 0 | 1 | 46 | 1 | 0 | 0 |
| Screens that changed | 191 | 149 | 43 | 1 | 0 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - oracle: 0 / 0; ASSIST - lexicon stand-in: 0 / 0; ASSIST - wrong model: 0 / 0; ASSIST - hostile model: 0 / 0; ASSIST - provider down: 0 / 0; SHADOW - lexicon stand-in: 0 / 0.

Screens changed where the answer must stay exactly the rules' own: assist_failing: 0, shadow_lexicon: 0.

## Population: official

240 documents - the 240 official documents as they are (nothing is open: the layer must change nothing for the worse).

| Metric | Deterministic only | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documents | 240 | 240 | 240 | 240 | 240 | 240 | 240 |
| READY with no question (automatic) | 154 | 154 | 154 | 154 | 154 | 154 | 154 |
| Manual matching required | 52 | 52 | 52 | 52 | 52 | 52 | 52 |
| Files that ask questions | 34 | 34 | 34 | 34 | 34 | 34 | 34 |
| Questions asked | 47 | 47 | 47 | 54 | 53 | 47 | 47 |
| Mapping recall (truth facts found) | 98.8% | 98.8% | 98.8% | 98.9% | 98.9% | 98.8% | 98.8% |
| Claims precision (claims that are right) | 99.8% | 99.8% | 99.8% | 99.3% | 99.4% | 99.8% | 99.8% |
| Domain accuracy | 98.7% | 98.7% | 98.7% | 98.7% | 98.7% | 98.7% | 98.7% |
| Header detection accuracy | 99.6% | 99.6% | 99.6% | 99.6% | 99.6% | 99.6% | 99.6% |
| **Unsafe READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **False automation** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| P0 findings (silent wrong data) | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Junk / personal columns mapped | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| Unknown correctly declared | 40 | 40 | 40 | 39 | 40 | 40 | 40 |
| **PII values sent to the model** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Scope safety violations** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Model calls | 0 | 46 | 46 | 46 | 46 | 46 | 46 |
| Documents where the model was asked | 0 | 46 | 46 | 46 | 46 | 46 | 46 |
| Tokens in (estimated from payload size) | 0 | 41400 | 80907 | 41400 | 41400 | 0 | 80907 |
| Tokens out (estimated) | 0 | 11500 | 9398 | 11500 | 11500 | 0 | 9398 |

Against the rules alone, document by document:

| | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|
| Files made automatic, correctly | 0 | 0 | 0 | 0 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread (not a false automation) | 0 | 0 | 0 | 0 | 0 | 0 |
| Questions correctly avoided | 0 | 0 | 0 | 0 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 0 | 0 | 0 | 0 | 0 | 0 |
| Manual matching turned into READY | 0 | 0 | 0 | 0 | 0 | 0 |
| Questions turned into READY | 0 | 0 | 0 | 0 | 0 | 0 |
| Model suggestions right | 1 | 1 | 0 | 0 | 0 | 0 |
| Model suggestions wrong | 0 | 0 | 15 | 9 | 0 | 0 |
| Screens that changed | 1 | 1 | 10 | 6 | 0 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - oracle: 0 / 0; ASSIST - lexicon stand-in: 0 / 0; ASSIST - wrong model: 0 / 0; ASSIST - hostile model: 0 / 0; ASSIST - provider down: 0 / 0; SHADOW - lexicon stand-in: 0 / 0.

Screens changed where the answer must stay exactly the rules' own: assist_failing: 0, shadow_lexicon: 0.

## Population: adversarial

15 documents - hand-built files: not hospitality, the wrong card, injection, personal data, twin columns.

| Metric | Deterministic only | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documents | 15 | 15 | 15 | 15 | 15 | 15 | 15 |
| READY with no question (automatic) | 0 | 3 | 0 | 0 | 0 | 0 | 0 |
| Manual matching required | 15 | 9 | 14 | 13 | 15 | 15 | 15 |
| Files that ask questions | 0 | 3 | 1 | 2 | 0 | 0 | 0 |
| Questions asked | 2 | 5 | 3 | 4 | 2 | 2 | 2 |
| Mapping recall (truth facts found) | 74.3% | 83.8% | 77.0% | 74.3% | 74.3% | 74.3% | 74.3% |
| Claims precision (claims that are right) | 100.0% | 100.0% | 100.0% | 96.5% | 100.0% | 100.0% | 100.0% |
| Domain accuracy | 93.3% | 93.3% | 93.3% | 93.3% | 93.3% | 93.3% | 93.3% |
| Header detection accuracy | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Unsafe READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **False automation** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| P0 findings (silent wrong data) | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Junk / personal columns mapped | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Unknown correctly declared | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **PII values sent to the model** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **Scope safety violations** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Model calls | 0 | 12 | 12 | 12 | 12 | 12 | 12 |
| Documents where the model was asked | 0 | 12 | 12 | 12 | 12 | 12 | 12 |
| Tokens in (estimated from payload size) | 0 | 10800 | 21530 | 10800 | 10800 | 0 | 21530 |
| Tokens out (estimated) | 0 | 3000 | 3329 | 3000 | 3000 | 0 | 3329 |

Against the rules alone, document by document:

| | ASSIST - oracle | ASSIST - lexicon stand-in | ASSIST - wrong model | ASSIST - hostile model | ASSIST - provider down | SHADOW - lexicon stand-in |
|---|---:|---:|---:|---:|---:|---:|
| Files made automatic, correctly | 3 | 0 | 0 | 0 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread (not a false automation) | 0 | 0 | 0 | 0 | 0 | 0 |
| Questions correctly avoided | 0 | 0 | 0 | 0 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 3 | 1 | 2 | 0 | 0 | 0 |
| Manual matching turned into READY | 3 | 0 | 0 | 0 | 0 | 0 |
| Questions turned into READY | 0 | 0 | 0 | 0 | 0 | 0 |
| Model suggestions right | 7 | 2 | 0 | 0 | 0 | 0 |
| Model suggestions wrong | 0 | 0 | 7 | 1 | 0 | 0 |
| Screens that changed | 6 | 1 | 4 | 1 | 0 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - oracle: 0 / 0; ASSIST - lexicon stand-in: 0 / 0; ASSIST - wrong model: 0 / 0; ASSIST - hostile model: 0 / 0; ASSIST - provider down: 0 / 0; SHADOW - lexicon stand-in: 0 / 0.

Screens changed where the answer must stay exactly the rules' own: assist_failing: 0, shadow_lexicon: 0.

## Challenge population by field

| Field | Docs | Automatic (rules) | Automatic (lexicon) | Manual (rules) | Manual (lexicon) | Questions (rules) | Questions (lexicon) |
|---|---:|---:|---:|---:|---:|---:|---:|
| actual_hours | 38 | 0 | 0 | 2 | 1 | 37 | 38 |
| booked_at | 13 | 0 | 0 | 12 | 0 | 1 | 15 |
| channel | 16 | 0 | 9 | 16 | 6 | 0 | 1 |
| check_out | 8 | 0 | 0 | 7 | 0 | 1 | 10 |
| cost_category | 8 | 7 | 7 | 0 | 0 | 2 | 2 |
| department | 36 | 0 | 33 | 0 | 0 | 36 | 5 |
| invoice_date | 39 | 0 | 0 | 38 | 38 | 1 | 1 |
| planned_hours | 36 | 0 | 0 | 0 | 0 | 39 | 39 |
| room_revenue | 20 | 0 | 0 | 19 | 19 | 1 | 1 |
| rooms | 14 | 12 | 7 | 0 | 0 | 2 | 7 |
| source_record_id | 13 | 0 | 0 | 13 | 0 | 0 | 14 |
| status | 10 | 0 | 4 | 10 | 6 | 0 | 0 |
| supplier_name | 39 | 0 | 0 | 38 | 0 | 1 | 40 |

## Challenge population by structure

| Structure | Docs | Automatic (rules) | Automatic (lexicon) | Manual (rules) | Manual (lexicon) |
|---|---:|---:|---:|---:|---:|
| department-from-section | 4 | 0 | 0 | 0 | 0 |
| department-from-sheet | 4 | 0 | 0 | 0 | 0 |
| department-from-title | 4 | 0 | 0 | 0 | 0 |
| hidden-sheet | 6 | 0 | 1 | 4 | 1 |
| indented | 12 | 1 | 4 | 6 | 3 |
| merged-cells | 47 | 2 | 10 | 14 | 6 |
| notes | 8 | 1 | 2 | 3 | 1 |
| planned_hours-from-grid | 3 | 0 | 3 | 0 | 0 |
| preamble:0 | 230 | 14 | 45 | 132 | 61 |
| preamble:1-3 | 34 | 3 | 9 | 13 | 6 |
| preamble:4+ | 26 | 2 | 6 | 10 | 3 |
| sections | 4 | 0 | 0 | 0 | 0 |
| sheets:1 | 262 | 19 | 58 | 145 | 67 |
| sheets:2 | 24 | 0 | 1 | 8 | 3 |
| sheets:3 | 2 | 0 | 1 | 2 | 0 |
| sheets:4 | 2 | 0 | 0 | 0 | 0 |
| totals | 19 | 2 | 7 | 6 | 3 |
| two-level-header | 5 | 0 | 2 | 4 | 2 |
| work_date-from-grid | 3 | 0 | 3 | 0 | 0 |
| xlsx | 290 | 19 | 60 | 155 | 70 |

## Cost

With the lexicon stand-in the model is asked about 225 of 290 challenge documents, about 1758 input tokens each (estimated from the size of the payload and the instructions, ~3 characters per token). Latency and actual token counts are NOT measured: there is no network call in this benchmark. The approximate API cost is **not computed**: no price is known for the configured model, and none was invented. Pass `--price-in` / `--price-out` (USD per million tokens) to compute it.

## How to read this

* **Unsafe READY**: offered as automatic (READY, no question) and wrong - a truth fact is read
  wrong, a column that must not be mapped is, or the truth says a person is needed. What decides is
  the *difference from the rules alone*: "caused" (it was not so before) and "fixed" (it was, and is
  not any more) are counted per document under each table. A raw count hides which one it is.
* **Files made automatic with another fact still unread** is a strict count: the file became
  automatic - correctly, for the column the layer touched - while some OTHER truth fact the rules
  already did not read stays unread (in the challenge set it is one accessory column of a
  two-level-header file, `B36`, P2). It is NOT a false automation: that is the "caused" line, and
  it is zero everywhere.
* **Junk / personal columns mapped** counts columns the truth says must NOT become a field that got
  a field *suggested* - always at MEDIUM, always with a question for the person, never certain. It
  is the residual risk of a wrong suggestion that a person confirms without looking: it is V3's, and
  the WRONG stand-in measures its size.
* **Certain-and-wrong claims** and **P0 findings** that are the same in every column are defects of
  the RULES on these files, not of the layer; the layer only ever lowers them.
* Tokens are estimated from the size of the payload (about three characters per token); latency is
  not measured (no network call).


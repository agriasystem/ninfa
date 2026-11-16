# Smart Import - OpenAI semantic layer - LIVE model benchmark V1

Date 2026-11-16 - branch `feature/smart-import-openai-intelligence-v1` - model `gpt-6.1-sol` (reported by the vendor: gpt-6.1-sol).

> Every number below comes from the **real model** on the vendor's endpoint (`/v1/responses`, `store=false`, Structured Outputs). No stand-in. The files are the synthetic corpus of `openai_intelligence`; nothing real was sent.

> **Outcome.** Unsafe READY over all populations - rules alone 0, real model with the vocabulary certainty 3, real model with the MEDIUM cap 0, SHADOW 0. A certainty that lets a model's reading skip the question is withdrawn while it is above zero: production builds the MEDIUM cap (ADR 0052).

Regenerate (from `services/api`, key in the environment, costs money): `python -m tests.benchmarks.smart_import_v3.openai_live`.

## Population: challenge

290 documents.

| Metric | Deterministic only | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|---:|
| Documents | 290 | 290 | 290 | 290 |
| READY with no question (automatic) | 19 | 31 | 12 | 19 |
| Manual matching required | 155 | 58 | 58 | 155 |
| Files that ask questions | 116 | 201 | 220 | 116 |
| Questions asked | 121 | 216 | 235 | 121 |
| Unnecessary questions | 113 | 195 | 214 | 113 |
| Mapping recall (truth facts found) | 82.6% | 92.5% | 92.5% | 82.6% |
| Claims precision (claims that are right) | 99.0% | 99.1% | 99.1% | 99.0% |
| Domain accuracy | 100.0% | 100.0% | 100.0% | 100.0% |
| Header detection accuracy | 99.7% | 99.7% | 99.7% | 99.7% |
| **Unsafe READY** | 0 | 0 | 0 | 0 |
| **False automation** | 0 | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 14 | 14 | 14 | 14 |
| P0 findings (silent wrong data) | 13 | 13 | 13 | 13 |
| Junk / personal columns mapped | 0 | 0 | 0 | 0 |
| **PII values sent to the model** (audit of each request) | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 0 | 0 | 0 | 0 |
| **Scope safety violations** | 0 | 0 | 0 | 0 |
| Model calls | 0 | 225 | 225 | 225 |

Against the rules alone, document by document:

| | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|
| Files made automatic, correctly | 17 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread | 2 | 0 | 0 |
| Questions correctly avoided | 1 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 79 | 97 | 0 |
| Manual matching turned into READY | 18 | 0 | 0 |
| Questions turned into READY | 1 | 0 | 0 |
| Model suggestions right | 152 | 151 | 0 |
| Model suggestions wrong | 22 | 21 | 0 |
| Screens that changed | 171 | 170 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - real model, vocabulary certainty ON (as first measured): 0 / 0; ASSIST - real model, MEDIUM cap (production, ADR 0052): 0 / 0; SHADOW - real model: 0 / 0.

Levels moved by the real model (rules -> ASSIST): {'ASK -> READY': 1, 'MANUAL -> ASK': 79, 'MANUAL -> READY': 18, 'READY -> ASK': 7}. Fallbacks: {'TIMEOUT': 4}. Shadow screens that changed: 0. Replay differences from the live run: 0. Replay misses: 0.

## Population: official

240 documents.

| Metric | Deterministic only | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|---:|
| Documents | 240 | 240 | 240 | 240 |
| READY with no question (automatic) | 154 | 154 | 154 | 154 |
| Manual matching required | 52 | 52 | 52 | 52 |
| Files that ask questions | 34 | 34 | 34 | 34 |
| Questions asked | 47 | 48 | 48 | 47 |
| Unnecessary questions | 1 | 2 | 2 | 1 |
| Mapping recall (truth facts found) | 98.8% | 98.9% | 98.9% | 98.8% |
| Claims precision (claims that are right) | 99.8% | 99.8% | 99.8% | 99.8% |
| Domain accuracy | 98.7% | 98.7% | 98.7% | 98.7% |
| Header detection accuracy | 99.6% | 99.6% | 99.6% | 99.6% |
| **Unsafe READY** | 0 | 0 | 0 | 0 |
| **False automation** | 0 | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 0 | 0 | 0 | 0 |
| P0 findings (silent wrong data) | 1 | 1 | 1 | 1 |
| Junk / personal columns mapped | 0 | 0 | 0 | 0 |
| **PII values sent to the model** (audit of each request) | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 0 | 0 | 0 | 0 |
| **Scope safety violations** | 0 | 0 | 0 | 0 |
| Model calls | 0 | 46 | 46 | 46 |

Against the rules alone, document by document:

| | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|
| Files made automatic, correctly | 0 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread | 0 | 0 | 0 |
| Questions correctly avoided | 0 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 0 | 0 | 0 |
| Manual matching turned into READY | 0 | 0 | 0 |
| Questions turned into READY | 0 | 0 | 0 |
| Model suggestions right | 0 | 0 | 0 |
| Model suggestions wrong | 3 | 3 | 0 |
| Screens that changed | 2 | 2 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - real model, vocabulary certainty ON (as first measured): 0 / 0; ASSIST - real model, MEDIUM cap (production, ADR 0052): 0 / 0; SHADOW - real model: 0 / 0.

Levels moved by the real model (rules -> ASSIST): none. Fallbacks: {'TIMEOUT': 1}. Shadow screens that changed: 0. Replay differences from the live run: 0. Replay misses: 0.

## Population: adversarial

15 documents.

| Metric | Deterministic only | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|---:|
| Documents | 15 | 15 | 15 | 15 |
| READY with no question (automatic) | 0 | 5 | 0 | 0 |
| Manual matching required | 15 | 7 | 7 | 15 |
| Files that ask questions | 0 | 3 | 8 | 0 |
| Questions asked | 2 | 5 | 11 | 2 |
| Unnecessary questions | 2 | 5 | 11 | 2 |
| Mapping recall (truth facts found) | 74.3% | 86.5% | 86.5% | 74.3% |
| Claims precision (claims that are right) | 100.0% | 100.0% | 100.0% | 100.0% |
| Domain accuracy | 93.3% | 93.3% | 93.3% | 93.3% |
| Header detection accuracy | 100.0% | 100.0% | 100.0% | 100.0% |
| **Unsafe READY** | 0 | 3 | 0 | 0 |
| **False automation** | 0 | 3 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 | 0 |
| Certain-and-wrong claims | 0 | 0 | 0 | 0 |
| P0 findings (silent wrong data) | 1 | 4 | 1 | 1 |
| Junk / personal columns mapped | 0 | 0 | 0 | 0 |
| **PII values sent to the model** (audit of each request) | 0 | 0 | 0 | 0 |
| PII values in the browser answer | 1 | 1 | 1 | 1 |
| **Scope safety violations** | 0 | 0 | 0 | 0 |
| Model calls | 0 | 12 | 12 | 12 |

Against the rules alone, document by document:

| | ASSIST - real model, vocabulary certainty ON (as first measured) | ASSIST - real model, MEDIUM cap (production, ADR 0052) | SHADOW - real model |
|---|---:|---:|---:|
| Files made automatic, correctly | 2 | 0 | 0 |
| Files made automatic with ANOTHER fact still unread | 3 | 0 | 0 |
| Questions correctly avoided | 0 | 0 | 0 |
| Questions incorrectly avoided | 0 | 0 | 0 |
| Manual matching turned into questions with a suggestion | 3 | 8 | 0 |
| Manual matching turned into READY | 5 | 0 | 0 |
| Questions turned into READY | 0 | 0 | 0 |
| Model suggestions right | 9 | 9 | 0 |
| Model suggestions wrong | 0 | 0 | 0 |
| Screens that changed | 8 | 8 | 0 |

Unsafe READY against the rules alone (caused / fixed by the layer): ASSIST - real model, vocabulary certainty ON (as first measured): 3 / 0; ASSIST - real model, MEDIUM cap (production, ADR 0052): 0 / 0; SHADOW - real model: 0 / 0.

Levels moved by the real model (rules -> ASSIST): {'MANUAL -> ASK': 3, 'MANUAL -> READY': 5}. Fallbacks: none. Shadow screens that changed: 0. Replay differences from the live run: 0. Replay misses: 0.

## Challenge population by field

| Field | Docs | Automatic (rules) | Automatic (model) | Manual (rules) | Manual (model) | Questions (rules) | Questions (model) |
|---|---:|---:|---:|---:|---:|---:|---:|
| actual_hours | 38 | 0 | 0 | 2 | 1 | 37 | 39 |
| booked_at | 13 | 0 | 0 | 12 | 0 | 1 | 15 |
| channel | 16 | 0 | 11 | 16 | 0 | 0 | 6 |
| check_out | 8 | 0 | 0 | 7 | 0 | 1 | 10 |
| cost_category | 8 | 7 | 7 | 0 | 0 | 2 | 2 |
| department | 36 | 0 | 1 | 0 | 0 | 36 | 35 |
| invoice_date | 39 | 0 | 0 | 38 | 38 | 1 | 1 |
| planned_hours | 36 | 0 | 0 | 0 | 0 | 39 | 39 |
| room_revenue | 20 | 0 | 0 | 19 | 19 | 1 | 1 |
| rooms | 14 | 12 | 5 | 0 | 0 | 2 | 10 |
| source_record_id | 13 | 0 | 0 | 13 | 0 | 0 | 14 |
| status | 10 | 0 | 7 | 10 | 0 | 0 | 3 |
| supplier_name | 39 | 0 | 0 | 38 | 0 | 1 | 41 |

## The real calls

* Real calls to the vendor: **283** (278 answered in the closed shape, 0 answered but not in it, failed by kind: {'TIMEOUT': 5}); second attempts 0, transport retries 1.
* Tokens: 613006 in / 100481 out (per call: 2205 in, 361 out on average, p95 out 559; output includes reasoning tokens).
* Latency per call: mean 10098 ms, p50 9360 ms, p95 20932 ms, max 28110 ms (production's timeout is 25 s).
* Cost at list price ($2.0/M input, $10.0/M output - **an assumption read on the web, not returned by the API**): **$2.2308** in total, $0.00788 per call.
* Request ids recorded: 278 of 283.
* On the wire: 283 requests inspected as they left; checks failed: none; largest request 10674 bytes.


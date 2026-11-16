# Smart Import - OpenAI ASSIST - UX and efficiency V1.1

Date 2026-11-16 - branch `feature/smart-import-openai-intelligence-v1` - model `gpt-6.1-sol`, reasoning `low`.

> The documents are the synthetic corpus of the intelligence benchmark: 290 challenge, 240 official, 15 adversarial. Every V1.1 number is the REAL model on the vendor's endpoint. `SMART_IMPORT_AI_MODE` stays `off`; the vocabulary certainty stays withdrawn ([ADR 0052](../architecture/adr/0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md)).

## Rules | OpenAI V1 | OpenAI V1.1

The model as production builds it (the certainty withdrawn). V1 is the run of Nov 16 as it was measured; V1.1 is the run of this gate.

### challenge

| Metric | Rules | OpenAI V1 | OpenAI V1.1 |
|---|---:|---:|---:|
| Documents | 290 | 290 | 290 |
| READY with no question | 19 | 12 | 19 |
| Manual matching required | 155 | 58 | 58 |
| Files that ask questions | 116 | 220 | 213 |
| Questions shown | 121 | 235 | 227 |
| Mapping recall | 82.6% | 92.5% | 90.3% |
| Claims precision | 99.0% | 99.1% | 99.1% |
| **Unsafe READY** | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 |
| **PII sent to the model** | 0 | 0 | 0 |
| **PII visible in the browser** | 0 | 0 | 0 |
| **Scope violations** | 0 | 0 | 0 |
| Model calls | 0 | 225 | 143 |

### official

| Metric | Rules | OpenAI V1 | OpenAI V1.1 |
|---|---:|---:|---:|
| Documents | 240 | 240 | 240 |
| READY with no question | 154 | 154 | 154 |
| Manual matching required | 52 | 52 | 52 |
| Files that ask questions | 34 | 34 | 34 |
| Questions shown | 47 | 48 | 48 |
| Mapping recall | 98.8% | 98.9% | 98.9% |
| Claims precision | 99.8% | 99.8% | 99.8% |
| **Unsafe READY** | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 |
| **PII sent to the model** | 0 | 0 | 0 |
| **PII visible in the browser** | 0 | 0 | 0 |
| **Scope violations** | 0 | 0 | 0 |
| Model calls | 0 | 46 | 19 |

### adversarial

| Metric | Rules | OpenAI V1 | OpenAI V1.1 |
|---|---:|---:|---:|
| Documents | 15 | 15 | 15 |
| READY with no question | 0 | 0 | 0 |
| Manual matching required | 15 | 7 | 7 |
| Files that ask questions | 0 | 8 | 8 |
| Questions shown | 2 | 11 | 11 |
| Mapping recall | 74.3% | 86.5% | 86.5% |
| Claims precision | 100.0% | 100.0% | 100.0% |
| **Unsafe READY** | 0 | 0 | 0 |
| **Wrong-domain READY** | 0 | 0 | 0 |
| **PII sent to the model** | 0 | 0 | 0 |
| **PII visible in the browser** | 0 | 1 | 0 |
| **Scope violations** | 0 | 0 | 0 |
| Model calls | 0 | 12 | 12 |

## Questions

Every question the model ADDED to a screen, in ONE class:

| Class | V1 | V1.1 |
|---|---:|---:|
| noise: ignoring it changes nothing | 7 | 0 |
| protects a measure | 2 | 2 |
| replaces a manual matching | 114 | 114 |
| replaces a worse question | 22 | 32 |
| **added by the model** | 145 | 148 |
| **useful_question_rate** | 95.2% | 100.0% |
| removed by the model (a worse question replaced) | 22 | 32 |
| questions shown in all | 293 | 286 |
| the rules' own questions | 170 | 170 |
| READY files turned into a question | 7 | 0 |
| manual matchings avoided | 104 | 105 |
| readings set aside as immaterial | 0 | 1 |

## Model calls

| Class | V1 | V1.1 |
|---|---:|---:|
| changed: relabelled, no question changed | 46 | 5 |
| no change: still manual matching | 44 | 22 |
| no change: the file was already READY | 22 | 0 |
| no change: the screen is the rules' own | 32 | 9 |
| noise: a question added to a READY file | 7 | 0 |
| useful: a worse question replaced | 22 | 32 |
| useful: manual matching avoided | 104 | 105 |
| wasted: the call failed | 6 | 1 |
| **model calls** | 283 | 174 |

## Where the recall went

Step by step: V1; then the V1.1 gate and rules alone (V1 reasoning, `medium`, replayed from V1's recording, no new call); then V1.1 as built (the real model at `low`).

### adversarial

| | OpenAI V1 | V1.1 gate and rules, `medium` | OpenAI V1.1 (`low`) |
|---|---:|---:|---:|
| mapping recall | 86.5% | 85.1% | 86.5% |
| manual matching | 7 | 8 | 7 |
| READY with no question | 0 | 0 | 0 |
| questions shown | 11 | 10 | 11 |
| model calls | 12 | 12 | 12 |

### challenge

| | OpenAI V1 | V1.1 gate and rules, `medium` | OpenAI V1.1 (`low`) |
|---|---:|---:|---:|
| mapping recall | 92.5% | 89.8% | 90.3% |
| manual matching | 58 | 58 | 58 |
| READY with no question | 12 | 19 | 19 |
| questions shown | 235 | 227 | 227 |
| model calls | 225 | 143 | 143 |

### official

| | OpenAI V1 | V1.1 gate and rules, `medium` | OpenAI V1.1 (`low`) |
|---|---:|---:|---:|
| mapping recall | 98.9% | 98.9% | 98.9% |
| manual matching | 52 | 52 | 52 |
| READY with no question | 154 | 154 | 154 |
| questions shown | 48 | 48 | 48 |
| model calls | 46 | 19 | 19 |

## Latency

Per call, in the full runs (6 calls in parallel, production's 25 s timeout).

| | OpenAI V1 | OpenAI V1.1 |
|---|---:|---:|
| calls | 283 | 174 |
| mean (ms) | 10098 | 5001 |
| p50 (ms) | 9360 | 4294 |
| p95 (ms) | 20932 | 9178 |
| max (ms) | 28110 | 25033 |
| timeouts | 5 | 1 |
| timeout rate | 1.8% | 0.6% |
| input tokens per call | 2205 | 2195 |
| output tokens per call | 361 | 242 |

### The same documents under other settings

50 documents the model is asked about, one recording per setting, asked one setting after the other (the last row repeats the first to show how far the API's own mood moves the same setting).

| Setting | p50 ms | p95 ms | timeouts | in / out tokens per call | mapping recall | manual matching | questions | unsafe READY | cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v1-medium | 8307 | 20415 | 1 | 2159 / 332 | 96.4% | 6 | 48 | 0 | $0.3821 |
| compact-low | 5821 | 16132 | 2 | 2105 / 149 | 97.0% | 6 | 49 | 0 | $0.285 |
| v1-low | 4899 | 10102 | 0 | 2202 / 239 | 97.0% | 5 | 48 | 0 | $0.3396 |
| compact-medium | 7241 | 18763 | 0 | 2196 / 242 | 98.0% | 4 | 51 | 0 | $0.3406 |
| v1-medium-again | 7969 | 13649 | 0 | 2202 / 342 | 96.4% | 5 | 49 | 0 | $0.3912 |

Rules alone on the same documents: mapping recall 82.6%, manual matching 38.

## Source Learning reuse

11 families x 8 versions, a counting stand-in that reads every column right (only how often it is ASKED is measured), the real services and database.

| | OpenAI V1 | OpenAI V1.1 |
|---|---:|---:|
| calls on later files of a source a person confirmed | 25 | 2 |
| the same files, for a source nobody confirmed | 64 | 58 |
| calls avoided by remembering | 39 | 56 |
| recognised versions | 55 | 55 |
| recognised versions that asked the model again | 13 | 0 |

## Cost

At the list price ($2 / M input, $10 / M output: read on the web, not from the API).

| | calls | tokens in | tokens out | cost |
|---|---:|---:|---:|---:|
| V1 full run (Nov 16) | 283 | 613006 | 100481 | $2.2308 |
| V1.1 full run | 173 | 379845 | 42003 | $1.1797 |
| latency comparison | 250 | 543218 | 65203 | $1.7385 |


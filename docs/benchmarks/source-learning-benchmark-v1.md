# Source Learning - Benchmark V1

Run 2026-10-26. 13 sources (11 the person has to teach, 2 the engine reads alone), 8 versions each = **104 documents**, each understood twice: by the property that taught the source (with a memory of what a person confirmed) and by another property that has never seen it (no memory). No model, no embedding, no external service; the 240-document benchmark is not touched.

> **How to read it.** V1 is the first file: the person answers (or matches the columns by hand), the server recomputes READY, the explicit import writes and remembers. V2..V8 are the same source later: other data (V2), columns moved (V3), a junk column (V4), cosmetic headers (V5), a new column (V6), a known column gone (V7), a column that changed meaning (V8). The two control sources are read by the engine alone: nothing should be learned from them.

## Result

| Measure | Target | Measured |
|---|---|---|
| Exact reuse (V2, V3, V5: the same source, nothing asked again) | 100% | 100.0% (33/33) |
| Compatible reuse (V4, V6: something added, nothing asked again) | 100% | 100.0% (22/22) |
| Repeated mapping questions on an unchanged source | 0 | 0 |
| Wrong reuse (a reused column read as something it is not) | 0% | 0.0% (0/372) |
| Readings automatic with a WRONG field (false automation with memory) | 0 | 0 |
| Cross-property contamination | 0 | 0 |
| Cross-domain contamination | 0 | 0 |
| Conflict detection recall (V8) | 100% | 100.0% (11/11) |
| Missing-column detection recall (V7) | 100% | 100.0% (11/11) |
| Every version behaves as expected | 100% | 100.0% (104/104) |

## What learning saves

|  | Without memory | With memory |
|---|---|---|
| Asks to answer or to match by hand, V2..V8 of the 10 taught sources | 97 | 18 |
| Versions Smart Import reads with nothing to ask | 0 | 59 |

**79 asks saved**, of which 37 manual matchings of the columns avoided. First import against next import (V1 vs V2): 15 asks the first time, 0 the next (100.0% (15/15) removed).

## By source

| Source | Domain | First time | Questions | Exact reuse | Compatible reuse | Asks saved | Wrong reuse | Conflict detected | All as expected |
|---|---|---|---|---|---|---|---|---|---|
| L1-ore-a-b | LABOR | ANSWERS | 2 | 100.0% (3/3) | 100.0% (2/2) | 11 | 0 | yes | yes |
| L2-ore-1-2 | LABOR | ANSWERS | 2 | 100.0% (3/3) | 100.0% (2/2) | 11 | 0 | yes | yes |
| L3-ore-base | LABOR | ANSWERS | 2 | 100.0% (3/3) | 100.0% (2/2) | 11 | 0 | yes | yes |
| L4-h1-h2 | LABOR | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 6 | 0 | yes | yes |
| L5-gruppo | LABOR | ANSWERS | 1 | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| B1-pratica | BOOKINGS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| B2-cod | BOOKINGS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| B3-id | BOOKINGS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| C1-forn | COSTS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 10 | 0 | yes | yes |
| C2-ragione | COSTS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| C3-chi | COSTS | MANUAL | - | 100.0% (3/3) | 100.0% (2/2) | 5 | 0 | yes | yes |
| X1-staff-clear | LABOR | control (engine alone) | - | 100.0% (3/3) | 100.0% (2/2) | 0 | 0 | - | yes |
| X2-costs-clear | COSTS | control (engine alone) | - | 100.0% (3/3) | 100.0% (2/2) | 0 | 0 | - | yes |

## Time

| Milliseconds | mean | p50 | p95 | max |
|---|---|---|---|---|
| Matching a file with the memory (`match_source`) | 0.087 | 0.09 | 0.116 | 0.122 |
| Understanding a file, with a memory | 80.743 | 78.576 | 118.91 | 136.137 |
| Understanding a file, without | 77.365 | 71.777 | 123.159 | 135.525 |

## Every version

| Source | V | What changed | Match | Drift | Level (memory) | Questions | Reused | Level (none) | Questions (none) | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| L1-ore-a-b | V1 | the first file | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V2 | next month, other data | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V5 | cosmetic headers | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L1-ore-a-b | V7 | a known column gone | COMPATIBLE | MISSING | READY | 0 | 1 | ASK | 1 | ok |
| L1-ore-a-b | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 1 | ASK | 1 | ok |
| L2-ore-1-2 | V1 | the first file | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V2 | next month, other data | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V5 | cosmetic headers | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L2-ore-1-2 | V7 | a known column gone | COMPATIBLE | MISSING | READY | 0 | 1 | ASK | 1 | ok |
| L2-ore-1-2 | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 1 | ASK | 1 | ok |
| L3-ore-base | V1 | the first file | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V2 | next month, other data | EXACT | NONE | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V5 | cosmetic headers | EXACT | COSMETIC | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ASK | 2 | ok |
| L3-ore-base | V7 | a known column gone | COMPATIBLE | MISSING | READY | 0 | 1 | ASK | 1 | ok |
| L3-ore-base | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 1 | ASK | 1 | ok |
| L4-h1-h2 | V1 | the first file | EXACT | NONE | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V2 | next month, other data | EXACT | NONE | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V5 | cosmetic headers | EXACT | COSMETIC | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 4 | MANUAL | 0 | ok |
| L4-h1-h2 | V7 | a known column gone | COMPATIBLE | MISSING | READY | 0 | 3 | MANUAL | 0 | ok |
| L4-h1-h2 | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 3 | MANUAL | 0 | ok |
| L5-gruppo | V1 | the first file | EXACT | NONE | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V2 | next month, other data | EXACT | NONE | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | ASK | 1 | ok |
| L5-gruppo | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 0 | MANUAL | 0 | ok |
| L5-gruppo | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 0 | MANUAL | 0 | ok |
| B1-pratica | V1 | the first file | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V2 | next month, other data | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B1-pratica | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| B1-pratica | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| B2-cod | V1 | the first file | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V2 | next month, other data | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B2-cod | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| B2-cod | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| B3-id | V1 | the first file | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V2 | next month, other data | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 8 | MANUAL | 0 | ok |
| B3-id | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| B3-id | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 7 | MANUAL | 0 | ok |
| C1-forn | V1 | the first file | EXACT | NONE | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V2 | next month, other data | EXACT | NONE | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 1 | ok |
| C1-forn | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| C1-forn | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| C2-ragione | V1 | the first file | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V2 | next month, other data | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 0 | ok |
| C2-ragione | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| C2-ragione | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| C3-chi | V1 | the first file | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V2 | next month, other data | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 5 | MANUAL | 0 | ok |
| C3-chi | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| C3-chi | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 4 | MANUAL | 0 | ok |
| X1-staff-clear | V1 | the first file | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V2 | next month, other data | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V7 | a known column gone | COMPATIBLE | MISSING | READY | 0 | 0 | READY | 0 | ok |
| X1-staff-clear | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V1 | the first file | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V2 | next month, other data | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V3 | columns moved | EXACT | COSMETIC | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V4 | a junk column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V5 | cosmetic headers | EXACT | NONE | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V6 | a new column | COMPATIBLE | ADDITIVE | READY | 0 | 0 | READY | 0 | ok |
| X2-costs-clear | V7 | a known column gone | COMPATIBLE | MISSING | MANUAL | 0 | 0 | MANUAL | 0 | ok |
| X2-costs-clear | V8 | a column changed meaning | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 0 | MANUAL | 0 | ok |


# Source Learning - Benchmark V1

Run 2026-10-28. 13 sources (11 the person has to teach, 2 the engine reads alone), 8 versions each = **104 documents**, each understood twice: by the property that taught the source (with a memory of what a person confirmed) and by another property that has never seen it (no memory). No model, no embedding, no external service; the 240-document benchmark is not touched.

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
| Matching a file with the memory (`match_source`) | 0.08 | 0.081 | 0.13 | 0.15 |
| Understanding a file, with a memory | 81.263 | 78.194 | 122.399 | 147.286 |
| Understanding a file, without | 78.192 | 74.237 | 121.42 | 167.653 |

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

## Several sources in one property (multi-source extension)

3 properties (bookings, staff, costs), each with **4 recurring families in the same kind of data**: 12 families, 120 documents in 141 timeline steps. A property is taught one family at a time and a later file of any of them arrives, as it would over months: A -> A, A -> B, B -> A, A -> B -> C -> A -> C -> B, a drifted A after B and C, a twin of A taught later, an import from memory, a correction by hand. The twin of A has the same columns plus a different optional one (the engine reads the two as different fields), so the two can only be told apart by what the file contains; five files per property are the twins' common part, with and without the column of each: they could be either, and the right answer is to reuse nothing. No model, no embedding, no external service.

### Result

| Measure | Target | Measured |
|---|---|---|
| Returning-family recognition (a family seen again after another one, unchanged or harmlessly changed: recognised, nothing asked) | 100% | 100.0% (82/82) |
| The right family, in every file that has one (incl. a column gone or a contradicted one) | 100% | 100.0% (105/105) |
| Cross-family wrong reuse (a file read as another family, or a reused column read as something it is not) | 0 | 0 |
| Family-collision false match (a file that could be either twin: one is chosen, or anything is reused) | 0 | 0.0% (0/15) |
| A twin taken for its sibling | 0 | 0 |
| Repeated questions after a returning source, unchanged | 0 | 0 |
| Correct family after cosmetic / additive drift (columns moved, a junk column, cosmetic headers, a new column) | 100% | 100.0% (39/39) |
| Other families untouched by an import from memory or a correction by hand | 100% | 100.0% (9/9) |
| Cross-property contamination | 0 | 0 |
| Cross-domain contamination | 0 | 0 |
| Every step behaves as expected | 100% | 100.0% (141/141) |

**144 asks saved** (154 without a memory, 10 with); 95 documents are read with nothing to ask, 0 without it.

### By property

| Property | Kind of data | Families | Remembered | Revisions |
|---|---|---|---|---|
| bookings: PMS, OTA, internal report and a PMS twin | BOOKINGS | M1-pms, M1-ota, M1-report, M1-pms-tariffa | 4 | M1-pms: 1, M1-ota: 2, M1-report: 1, M1-pms-tariffa: 1 |
| labor: three staff exports and a twin of the first | LABOR | M2-turni, M2-ore-1-2, M2-ore-base, M2-turni-c | 4 | M2-turni: 2, M2-ore-1-2: 1, M2-ore-base: 1, M2-turni-c: 1 |
| costs: supplier register, ledger, cash book and a twin of the first | COSTS | M3-forn, M3-ragione, M3-chi, M3-forn-qta | 4 | M3-forn: 2, M3-ragione: 1, M3-chi: 1, M3-forn-qta: 1 |

### Every step

| Property | # | Event | Family | V | Chosen | Ambiguous | Match | Drift | Level | Questions | Reused | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bookings | 1 | taught | M1-pms | - | - | - | - | - | - | - | - | ok |
| bookings | 2 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 3 | taught | M1-ota | - | - | - | - | - | - | - | - | ok |
| bookings | 4 | a later file | M1-ota | V2 | 2 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 5 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 6 | a later file | M1-ota | V2 | 2 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 7 | taught | M1-report | - | - | - | - | - | - | - | - | ok |
| bookings | 8 | a later file | M1-report | V2 | 3 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 9 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 10 | a later file | M1-report | V2 | 3 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 11 | a later file | M1-ota | V2 | 2 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 12 | a later file | M1-pms | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 13 | a later file | M1-ota | V3 | 2 | - | EXACT | COSMETIC | READY | 0 | 9 | ok |
| bookings | 14 | a later file | M1-report | V5 | 3 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 15 | taught | M1-pms-tariffa | - | - | - | - | - | - | - | - | ok |
| bookings | 16 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 17 | a later file | M1-pms-tariffa | V2 | 4 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 18 | a later file | M1-pms | V3 | 1 | - | EXACT | COSMETIC | READY | 0 | 9 | ok |
| bookings | 19 | a later file | M1-pms-tariffa | V3 | 4 | - | EXACT | COSMETIC | READY | 0 | 9 | ok |
| bookings | 20 | a later file | M1-pms | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 21 | a later file | M1-pms-tariffa | V4 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 22 | a later file | M1-pms | V5 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 23 | a later file | M1-pms-tariffa | V5 | 4 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 24 | a later file | M1-pms | V6 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 25 | a later file | M1-pms-tariffa | V6 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 26 | a later file | M1-ota | V6 | 2 | - | COMPATIBLE | ADDITIVE | READY | 0 | 9 | ok |
| bookings | 27 | a later file | M1-report | V4 | 3 | - | COMPATIBLE | ADDITIVE | READY | 0 | 8 | ok |
| bookings | 28 | a later file | M1-pms | V7 | 1 | - | COMPATIBLE | MISSING | MANUAL | 0 | 8 | ok |
| bookings | 29 | a later file | M1-pms-tariffa | V7 | 4 | - | COMPATIBLE | MISSING | MANUAL | 0 | 8 | ok |
| bookings | 30 | a later file | M1-pms | V8 | 1 | - | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 8 | ok |
| bookings | 31 | a later file | M1-pms-tariffa | V8 | 4 | - | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 8 | ok |
| bookings | 32 | could be either twin | M1-pms | base | none | yes | - | - | MANUAL | 0 | 0 | ok |
| bookings | 33 | could be either twin | M1-pms | reordered | none | yes | - | - | MANUAL | 0 | 0 | ok |
| bookings | 34 | could be either twin | M1-pms | junk | none | yes | - | - | MANUAL | 0 | 0 | ok |
| bookings | 35 | could be either twin | M1-pms | cosmetic | none | yes | - | - | MANUAL | 0 | 0 | ok |
| bookings | 36 | could be either twin | M1-pms | both | none | yes | - | - | MANUAL | 0 | 0 | ok |
| bookings | 37 | imported from memory | M1-pms | V2 | - | - | - | - | - | - | - | ok |
| bookings | 38 | a later file | M1-ota | V2 | 2 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 39 | a later file | M1-report | V2 | 3 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 40 | a later file | M1-pms-tariffa | V2 | 4 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 41 | imported from memory | M1-report | V2 | - | - | - | - | - | - | - | ok |
| bookings | 42 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 43 | corrected by hand | M1-ota | - | - | - | - | - | - | - | - | ok |
| bookings | 44 | a later file | M1-pms | V2 | 1 | - | EXACT | NONE | READY | 0 | 9 | ok |
| bookings | 45 | a later file | M1-ota | V2 | 2 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 46 | a later file | M1-report | V2 | 3 | - | EXACT | NONE | READY | 0 | 8 | ok |
| bookings | 47 | a later file | M1-pms-tariffa | V2 | 4 | - | EXACT | NONE | READY | 0 | 9 | ok |
| labor | 1 | taught | M2-turni | - | - | - | - | - | - | - | - | ok |
| labor | 2 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 3 | taught | M2-ore-1-2 | - | - | - | - | - | - | - | - | ok |
| labor | 4 | a later file | M2-ore-1-2 | V2 | 2 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 5 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 6 | a later file | M2-ore-1-2 | V2 | 2 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 7 | taught | M2-ore-base | - | - | - | - | - | - | - | - | ok |
| labor | 8 | a later file | M2-ore-base | V2 | 3 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 9 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 10 | a later file | M2-ore-base | V2 | 3 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 11 | a later file | M2-ore-1-2 | V2 | 2 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 12 | a later file | M2-turni | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 13 | a later file | M2-ore-1-2 | V3 | 2 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 14 | a later file | M2-ore-base | V5 | 3 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 15 | taught | M2-turni-c | - | - | - | - | - | - | - | - | ok |
| labor | 16 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 17 | a later file | M2-turni-c | V2 | 4 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 18 | a later file | M2-turni | V3 | 1 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 19 | a later file | M2-turni-c | V3 | 4 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 20 | a later file | M2-turni | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 21 | a later file | M2-turni-c | V4 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 22 | a later file | M2-turni | V5 | 1 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 23 | a later file | M2-turni-c | V5 | 4 | - | EXACT | COSMETIC | READY | 0 | 2 | ok |
| labor | 24 | a later file | M2-turni | V6 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 25 | a later file | M2-turni-c | V6 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 26 | a later file | M2-ore-1-2 | V6 | 2 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 27 | a later file | M2-ore-base | V4 | 3 | - | COMPATIBLE | ADDITIVE | READY | 0 | 2 | ok |
| labor | 28 | a later file | M2-turni | V7 | 1 | - | COMPATIBLE | MISSING | READY | 0 | 1 | ok |
| labor | 29 | a later file | M2-turni-c | V7 | 4 | - | COMPATIBLE | MISSING | READY | 0 | 1 | ok |
| labor | 30 | a later file | M2-turni | V8 | 1 | - | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 1 | ok |
| labor | 31 | a later file | M2-turni-c | V8 | 4 | - | COMPATIBLE | SEMANTIC_CONFLICT | ASK | 1 | 1 | ok |
| labor | 32 | could be either twin | M2-turni | base | none | yes | - | - | ASK | 1 | 0 | ok |
| labor | 33 | could be either twin | M2-turni | reordered | none | yes | - | - | ASK | 1 | 0 | ok |
| labor | 34 | could be either twin | M2-turni | junk | none | yes | - | - | ASK | 1 | 0 | ok |
| labor | 35 | could be either twin | M2-turni | cosmetic | none | yes | - | - | ASK | 1 | 0 | ok |
| labor | 36 | could be either twin | M2-turni | both | none | yes | - | - | ASK | 3 | 0 | ok |
| labor | 37 | imported from memory | M2-turni | V2 | - | - | - | - | - | - | - | ok |
| labor | 38 | a later file | M2-ore-1-2 | V2 | 2 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 39 | a later file | M2-ore-base | V2 | 3 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 40 | a later file | M2-turni-c | V2 | 4 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 41 | imported from memory | M2-ore-base | V2 | - | - | - | - | - | - | - | ok |
| labor | 42 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 43 | corrected by hand | M2-turni | - | - | - | - | - | - | - | - | ok |
| labor | 44 | a later file | M2-turni | V2 | 1 | - | EXACT | NONE | READY | 0 | 4 | ok |
| labor | 45 | a later file | M2-ore-1-2 | V2 | 2 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 46 | a later file | M2-ore-base | V2 | 3 | - | EXACT | NONE | READY | 0 | 2 | ok |
| labor | 47 | a later file | M2-turni-c | V2 | 4 | - | EXACT | NONE | READY | 0 | 2 | ok |
| costs | 1 | taught | M3-forn | - | - | - | - | - | - | - | - | ok |
| costs | 2 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 3 | taught | M3-ragione | - | - | - | - | - | - | - | - | ok |
| costs | 4 | a later file | M3-ragione | V2 | 2 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 5 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 6 | a later file | M3-ragione | V2 | 2 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 7 | taught | M3-chi | - | - | - | - | - | - | - | - | ok |
| costs | 8 | a later file | M3-chi | V2 | 3 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 9 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 10 | a later file | M3-chi | V2 | 3 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 11 | a later file | M3-ragione | V2 | 2 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 12 | a later file | M3-forn | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 6 | ok |
| costs | 13 | a later file | M3-ragione | V3 | 2 | - | EXACT | COSMETIC | READY | 0 | 5 | ok |
| costs | 14 | a later file | M3-chi | V5 | 3 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 15 | taught | M3-forn-qta | - | - | - | - | - | - | - | - | ok |
| costs | 16 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 17 | a later file | M3-forn-qta | V2 | 4 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 18 | a later file | M3-forn | V3 | 1 | - | EXACT | COSMETIC | READY | 0 | 6 | ok |
| costs | 19 | a later file | M3-forn-qta | V3 | 4 | - | EXACT | COSMETIC | READY | 0 | 6 | ok |
| costs | 20 | a later file | M3-forn | V4 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 6 | ok |
| costs | 21 | a later file | M3-forn-qta | V4 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 6 | ok |
| costs | 22 | a later file | M3-forn | V5 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 23 | a later file | M3-forn-qta | V5 | 4 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 24 | a later file | M3-forn | V6 | 1 | - | COMPATIBLE | ADDITIVE | READY | 0 | 6 | ok |
| costs | 25 | a later file | M3-forn-qta | V6 | 4 | - | COMPATIBLE | ADDITIVE | READY | 0 | 6 | ok |
| costs | 26 | a later file | M3-ragione | V6 | 2 | - | COMPATIBLE | ADDITIVE | READY | 0 | 5 | ok |
| costs | 27 | a later file | M3-chi | V4 | 3 | - | COMPATIBLE | ADDITIVE | READY | 0 | 5 | ok |
| costs | 28 | a later file | M3-forn | V7 | 1 | - | COMPATIBLE | MISSING | MANUAL | 0 | 5 | ok |
| costs | 29 | a later file | M3-forn-qta | V7 | 4 | - | COMPATIBLE | MISSING | MANUAL | 0 | 5 | ok |
| costs | 30 | a later file | M3-forn | V8 | 1 | - | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 5 | ok |
| costs | 31 | a later file | M3-forn-qta | V8 | 4 | - | COMPATIBLE | SEMANTIC_CONFLICT | MANUAL | 0 | 5 | ok |
| costs | 32 | could be either twin | M3-forn | base | none | yes | - | - | MANUAL | 1 | 0 | ok |
| costs | 33 | could be either twin | M3-forn | reordered | none | yes | - | - | MANUAL | 1 | 0 | ok |
| costs | 34 | could be either twin | M3-forn | junk | none | yes | - | - | MANUAL | 1 | 0 | ok |
| costs | 35 | could be either twin | M3-forn | cosmetic | none | yes | - | - | MANUAL | 1 | 0 | ok |
| costs | 36 | could be either twin | M3-forn | both | none | yes | - | - | MANUAL | 1 | 0 | ok |
| costs | 37 | imported from memory | M3-forn | V2 | - | - | - | - | - | - | - | ok |
| costs | 38 | a later file | M3-ragione | V2 | 2 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 39 | a later file | M3-chi | V2 | 3 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 40 | a later file | M3-forn-qta | V2 | 4 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 41 | imported from memory | M3-chi | V2 | - | - | - | - | - | - | - | ok |
| costs | 42 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 6 | ok |
| costs | 43 | corrected by hand | M3-forn | - | - | - | - | - | - | - | - | ok |
| costs | 44 | a later file | M3-forn | V2 | 1 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 45 | a later file | M3-ragione | V2 | 2 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 46 | a later file | M3-chi | V2 | 3 | - | EXACT | NONE | READY | 0 | 5 | ok |
| costs | 47 | a later file | M3-forn-qta | V2 | 4 | - | EXACT | NONE | READY | 0 | 6 | ok |


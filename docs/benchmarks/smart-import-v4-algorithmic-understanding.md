# Smart Import V4.1 - algorithmic understanding: measured result

Branch `feature/smart-import-v4-algorithmic-understanding` (base `main` = `7d826a2`; not pushed). No model is called by any engine measured here: `SMART_IMPORT_AI_MODE=off`, the offline guard on, the same documents read by every engine through the real understanding service, scored by the existing benchmark's scorer. Architecture: [smart-import-v4-algorithmic-understanding](../architecture/smart-import-v4-algorithmic-understanding.md); decision: [ADR 0056](../architecture/adr/0056-smart-import-v4-reads-files-with-algorithms-and-keeps-v3-one-setting-away.md). Every number below is read from a JSON the benchmark wrote (`python -m tests.benchmarks.algorithmic_v4 --json`, then `.report`); the prose around the numbers is the only thing typed.

## 1. The verdict, in numbers

Over **1026 documents** (the official corpus of 240, the 390 unseen-file documents, the 290-file challenge, 15 adversarial, and the 91-file problem corpus), the default `v4` engine against the engine in production (`v3`):

| | current (V3) | V4 | delta |
|---|---:|---:|---:|
| mapping recall (% of facts read right) | 93.8 | 94.7 | +0.9 |
| READY (no question) | 502 | 526 | +24 |
| ASK (one or two questions) | 236 | 272 | +36 |
| manual matching (MANUAL + BLOCKED) | 288 | 228 | -60 |
| questions asked | 275 | 318 | +43 |
| wrong claims (a fact read as another) | 14 | 13 | -1 |
| facts missed | 268 | 216 | -52 |
| **unsafe READY** | 0 | 0 | +0 |
| **false automation** | 0 | 0 | +0 |
| **wrong-domain READY** | 0 | 0 | +0 |
| **scope violations** | 0 | 0 | +0 |
| **personal values in the browser answer** | 0 | 0 | +0 |
| engine errors | 0 | 0 | +0 |
| OpenAI / model calls | 0 | 0 | +0 |

How the 1026 documents moved, V3 -> V4: READY -> READY: **502**, ASK -> ASK: **233**, MANUAL -> MANUAL: **204**, MANUAL -> ASK: **39**, BLOCKED -> BLOCKED: **24**, MANUAL -> READY: **21**, ASK -> READY: **3**.

* **No READY is lost**: 0 documents go from READY to something else. **No document gets more wrong claims** (0).
* **39 matching screens become a question** (45 questions in all, 0 of them proposing a wrong field): the person confirms a proposed column instead of matching every column by hand.
* 24 documents become READY (camelCase, glued and unit-qualified headers V3 could not read).
* The benchmark counts those 45 questions as "unnecessary" because the truth of a challenge file is the READY file it was made from; each one replaces a matching screen. That is why the unnecessary-question count rises (160 -> 197) while manual matching falls.

## 2. What the pieces are worth (ablation)

Each configuration adds one part to the previous one; the documents and the scorer are identical.

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion | delta (last vs current) |
|---|---:|---:|---:|---:|---:|---:|
| documents | 1026 | 1026 | 1026 | 1026 | 1026 | +0 |
| mapping recall (% of facts read right) | 93.8 | 94.1 | 94.7 | 94.7 | 94.7 | +0.9 |
| READY (no question) | 502 | 526 | 526 | 526 | 522 | +20 |
| ASK (one or two questions) | 236 | 229 | 272 | 271 | 275 | +39 |
| manual matching (MANUAL + BLOCKED) | 288 | 271 | 228 | 229 | 229 | -59 |
| questions asked | 275 | 266 | 318 | 317 | 323 | +48 |
| unnecessary questions | 160 | 151 | 197 | 196 | 202 | +42 |
| wrong claims (a fact read as another) | 14 | 14 | 13 | 13 | 13 | -1 |
| missed facts | 268 | 253 | 216 | 217 | 217 | -51 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 | +0 |
| false automation | 0 | 0 | 0 | 0 | 0 | +0 |
| wrong-domain READY | 0 | 0 | 0 | 0 | 0 | +0 |
| scope violations | 0 | 0 | 0 | 0 | 0 | +0 |
| personal values in the browser answer | 0 | 0 | 0 | 0 | 0 | +0 |
| engine errors | 0 | 0 | 0 | 0 | 0 | +0 |
| understanding latency, mean ms | 221.1 | 234.4 | 245.0 | 250.0 | 252.6 | +31.5 |
| understanding latency, worst p95 ms | 330.4 | 405.0 | 408.2 | 438.1 | 389.6 | +59.2 |

* **Vocabulary + header reader (`v4-header`)**: recall 93.8 -> 94.1, READY 502 -> 526. All of it is camelCase, words glued together, a unit after the name and phrases the word rules did not know. The matching of spelling mistakes (RapidFuzz) is not what moves the number: see section 5.
* **Value semantics, relations, validation (`v4`)**: recall -> 94.7, manual matching 271 -> 228. This is the biggest single part: it names a column no header names.
* **Global assignment (SciPy, `v4-assign`)**: changes **1 document(s)** of 1026 against `v4` (`ADV12-two-columns-of-statuses`), for the worse. **SciPy adds nothing measurable on these files**, which is why it is a development dependency and the default engine keeps V3's greedy pick.
* **Margin demotion of names (`v4-margin`)**: 4 documents differ from `v4-assign`, READY 526 -> 522, unsafe READY 0 -> 0: it costs READY and buys no safety the default does not already have.

## 3. Population by population

An aggregate hides where a change helps and where it does nothing. The official corpus and the 390 unseen files are what V3 was built on: V4 must not change them, and does not.

### adversarial (15 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.7432 | 0.7432 | 0.8378 | 0.8243 | 0.8243 |
| claims precision | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| READY | 0 | 0 | 0 | 0 | 0 |
| ASK | 0 | 0 | 7 | 6 | 6 |
| manual matching | 15 | 15 | 8 | 9 | 9 |
| questions / unnecessary | 2 / 2 | 2 / 2 | 9 / 9 | 8 / 8 | 8 / 8 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 185 / 237 | 200 / 338 | 198 / 336 | 198 / 351 | 212 / 312 |

### challenge (290 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.8261 | 0.8261 | 0.8428 | 0.8428 | 0.8428 |
| claims precision | 0.9903 | 0.9903 | 0.9912 | 0.9912 | 0.9912 |
| READY | 19 | 19 | 19 | 19 | 19 |
| ASK | 116 | 116 | 144 | 144 | 144 |
| manual matching | 155 | 155 | 127 | 127 | 127 |
| questions / unnecessary | 121 / 113 | 121 / 113 | 154 / 140 | 154 / 140 | 154 / 140 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 268 / 330 | 258 / 322 | 283 / 374 | 297 / 390 | 298 / 390 |

### official (240 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.9877 | 0.9885 | 0.9885 | 0.9885 | 0.9885 |
| claims precision | 0.9975 | 0.9975 | 0.9975 | 0.9975 | 0.9975 |
| READY | 154 | 154 | 154 | 154 | 153 |
| ASK | 34 | 34 | 34 | 34 | 35 |
| manual matching | 52 | 52 | 52 | 52 | 52 |
| questions / unnecessary | 47 / 1 | 47 / 1 | 47 / 1 | 47 / 1 | 48 / 2 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 211 / 270 | 225 / 314 | 223 / 338 | 216 / 320 | 249 / 360 |

### problem (91 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.9678 | 0.9920 | 0.9920 | 0.9920 | 0.9920 |
| claims precision | 0.9934 | 1.0000 | 0.9732 | 0.9732 | 0.9732 |
| READY | 37 | 61 | 61 | 61 | 61 |
| ASK | 19 | 12 | 20 | 20 | 20 |
| manual matching | 35 | 18 | 10 | 10 | 10 |
| questions / unnecessary | 23 / 21 | 14 / 12 | 26 / 24 | 26 / 24 | 26 / 24 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 203 / 275 | 252 / 405 | 258 / 408 | 250 / 438 | 193 / 307 |

### unseen_dev (200 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.9964 | 0.9964 | 0.9964 | 0.9964 | 0.9964 |
| claims precision | 0.9947 | 0.9947 | 0.9947 | 0.9947 | 0.9947 |
| READY | 145 | 145 | 145 | 145 | 144 |
| ASK | 39 | 39 | 39 | 39 | 40 |
| manual matching | 16 | 16 | 16 | 16 | 16 |
| questions / unnecessary | 45 / 12 | 45 / 12 | 45 / 12 | 45 / 12 | 46 / 13 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 186 / 318 | 207 / 328 | 223 / 362 | 234 / 383 | 229 / 347 |

### unseen_holdout (190 documents)

| metric | current (V3) | V4 header only | V4 (header + value semantics) | V4 + global assignment (SciPy) | V4 + assignment + margin demotion |
|---|---:|---:|---:|---:|---:|
| mapping recall | 0.9972 | 0.9972 | 0.9972 | 0.9972 | 0.9972 |
| claims precision | 0.9953 | 0.9953 | 0.9953 | 0.9953 | 0.9953 |
| READY | 147 | 147 | 147 | 147 | 145 |
| ASK | 28 | 28 | 28 | 28 | 30 |
| manual matching | 15 | 15 | 15 | 15 | 15 |
| questions / unnecessary | 37 / 11 | 37 / 11 | 37 / 11 | 37 / 11 | 41 / 15 |
| unsafe READY | 0 | 0 | 0 | 0 | 0 |
| false automation | 0 | 0 | 0 | 0 | 0 |
| latency mean / p95 ms | 210 / 327 | 233 / 348 | 236 / 358 | 243 / 376 | 245 / 381 |


Latencies in this table were measured while other benchmark processes were running on the same machine; the clean figures are in section 9.

## 4. The problem corpus, header by header

91 files whose headers are plausible and no importer's own name, written before any V4 result existed (the one bug of its own truth, found from the V3 baseline, is recorded in `problem_corpus.py`). By kind of header:

| kind of header | engine | READY | ASK | manual |
|---|---|---:|---:|---:|
| camel | current (V3) | 0 | 3 | 9 |
| camel | V4 header only | 9 | 3 | 0 |
| camel | V4 (header + value semantics) | 9 | 3 | 0 |
| camel | V4 + global assignment (SciPy) | 9 | 3 | 0 |
| glued | current (V3) | 0 | 1 | 9 |
| glued | V4 header only | 9 | 1 | 0 |
| glued | V4 (header + value semantics) | 9 | 1 | 0 |
| glued | V4 + global assignment (SciPy) | 9 | 1 | 0 |
| plain | current (V3) | 31 | 7 | 3 |
| plain | V4 header only | 37 | 4 | 0 |
| plain | V4 (header + value semantics) | 37 | 4 | 0 |
| plain | V4 + global assignment (SciPy) | 37 | 4 | 0 |
| qualifier | current (V3) | 6 | 1 | 0 |
| qualifier | V4 header only | 6 | 1 | 0 |
| qualifier | V4 (header + value semantics) | 6 | 1 | 0 |
| qualifier | V4 + global assignment (SciPy) | 6 | 1 | 0 |
| typo | current (V3) | 0 | 2 | 5 |
| typo | V4 header only | 0 | 2 | 5 |
| typo | V4 (header + value semantics) | 0 | 2 | 5 |
| typo | V4 + global assignment (SciPy) | 0 | 2 | 5 |
| unnamed | current (V3) | 0 | 5 | 9 |
| unnamed | V4 header only | 0 | 1 | 13 |
| unnamed | V4 (header + value semantics) | 0 | 9 | 5 |
| unnamed | V4 + global assignment (SciPy) | 0 | 9 | 5 |

### The three headers of the brief: `reservation_code`, `booking_status`, `room_total`

**An honest finding first: in a clean snake_case file V3 already reads all three correctly** - they are importer names (`EXACT`), the file is READY, and V4 changes nothing. What V3 cannot read is the same headers written another way: `ReservationId`, `BookingStatus`, `RoomRevenue` (V3 reaches only a likeness of letters, `TO_CHECK`, and the file goes to the matching screen), `reservationid`, `bookingstatus`, `checkindate`. Header -> candidates -> evidence -> selected -> validation, taken from `python -m tests.benchmarks.algorithmic_v4.explain`:

### PB_snake_xlsx (bookings, snake.xlsx)

V3: level **READY**, questions none
V4: level **READY**, questions none

| header | V3 reads | V4 candidates (total = header x values + relation) | V4 selected | validation |
|---|---|---|---|---|
| `reservation_code` | source_record_id EXACT 1.00, booked_at FUZZY 0.88 -> `source_record_id` RECOGNIZED | `source_record_id` 1.00 (header 1.00 EXACT, values 1.00) | `source_record_id` HIGH -> final `source_record_id` RECOGNIZED | - |
| `booking_status` | status EXACT 1.00 -> `status` RECOGNIZED | `status` 1.00 (header 1.00 EXACT, values 1.00) | `status` HIGH -> final `status` RECOGNIZED | - |
| `room_total` | room_revenue EXACT 1.00, rooms TOKEN 0.90 -> `room_revenue` RECOGNIZED | `room_revenue` 1.00 (header 1.00 EXACT, values 1.00)<br>`rooms` 0.00 (header 0.90 RULE, values 0.00, RULED OUT: the values contradict the name) | `room_revenue` HIGH -> final `room_revenue` RECOGNIZED | - |

### PB_camel_xlsx (bookings, camel.xlsx)

V3: level **MANUAL**, questions none
V4: level **READY**, questions none

| header | V3 reads | V4 candidates (total = header x values + relation) | V4 selected | validation |
|---|---|---|---|---|
| `ReservationId` | source_record_id FUZZY 0.96, booked_at FUZZY 0.83 -> `source_record_id` TO_CHECK | `source_record_id` 1.00 (header 1.00 EXACT, values 1.00) | `source_record_id` HIGH -> final `source_record_id` RECOGNIZED | - |
| `BookingStatus` | status FUZZY 0.96 -> `status` TO_CHECK | `status` 1.00 (header 1.00 EXACT, values 1.00) | `status` HIGH -> final `status` RECOGNIZED | - |
| `RoomRevenue` | room_revenue FUZZY 0.96 -> `room_revenue` TO_CHECK | `room_revenue` 1.00 (header 1.00 EXACT, values 1.00) | `room_revenue` HIGH -> final `room_revenue` RECOGNIZED | - |

### PB_glued_xlsx (bookings, glued.xlsx)

V3: level **MANUAL**, questions none
V4: level **READY**, questions none

| header | V3 reads | V4 candidates (total = header x values + relation) | V4 selected | validation |
|---|---|---|---|---|
| `reservationid` | source_record_id FUZZY 0.96, booked_at FUZZY 0.83 -> `source_record_id` TO_CHECK | `source_record_id` 1.00 (header 1.00 EXACT, values 1.00) | `source_record_id` HIGH -> final `source_record_id` RECOGNIZED | - |
| `checkindate` | nothing -> `check_in` TO_CHECK | `check_in` 1.00 (header 1.00 EXACT 'checkin date', values 1.00, relation +0.15) | `check_in` HIGH -> final `check_in` RECOGNIZED | - |
| `bookingstatus` | status FUZZY 0.96 -> `status` TO_CHECK | `status` 1.00 (header 1.00 EXACT, values 1.00) | `status` HIGH -> final `status` RECOGNIZED | - |
| `roomrevenue` | room_revenue FUZZY 0.96 -> `room_revenue` TO_CHECK | `room_revenue` 1.00 (header 1.00 EXACT, values 1.00) | `room_revenue` HIGH -> final `room_revenue` RECOGNIZED | - |

### PB_unnamed05 (bookings, export.xlsx)

V3: level **MANUAL**, questions none
V4: level **ASK**, questions ['COLUMN_MEANING', 'COLUMN_MEANING']

| header | V3 reads | V4 candidates (total = header x values + relation) | V4 selected | validation |
|---|---|---|---|---|
| `Campo 1` | nothing -> `-`  | `check_in` 0.71 (header 0.50 VALUES, values 1.00, proof 0.90, relation +0.15) | `check_in` MEDIUM -> final `check_in` TO_CHECK | - |
| `Campo 2` | nothing -> `-`  | `check_out` 0.71 (header 0.50 VALUES, values 1.00, proof 0.90, relation +0.15) | `check_out` MEDIUM -> final `check_out` TO_CHECK | - |

## 5. Spelling mistakes: what RapidFuzz is worth

The `typo` kind above misspells EVERY header of a file, which nobody does, and cannot show a reader of spellings at work (eight unsure columns are more than the product asks one by one, so the file goes to the matching screen whatever the reader does). After seeing that, **34 more files were added, each a clean file with exactly one misspelled header** (`PT_*`, written knowing the results on the main corpus: a hypothesis test, not part of the headline). Result:

| | current (V3) | V4 header only | V4 |
|---|---:|---:|---:|
| mapping recall | 0.9758 | 0.9839 | 0.9839 |
| READY | 8 | 8 | 8 |
| ASK | 26 | 26 | 26 |
| manual matching | 0 | 0 | 0 |
| questions asked | 29 | 29 | 29 |

V3's own likeness-of-letters reading already turns one misspelled header into one confirmation question; RapidFuzz's word-level matching reads about one more fact in a hundred and changes no document's level. **RapidFuzz's measured value is marginal**; the header gain is the vocabulary and the normalisation. It stays because it costs a 1.6 MB wheel with no dependencies and it is stricter than `difflib` (word by word, with an opposite-words guard), not because it moved a number.

## 6. Against the existing benchmarks (regression)

### Official corpus (240 documents) - the whole benchmark, V3 on `main` against V4

| metric | V3 (main 7d826a2) | V4 |
|---|---:|---:|
| domain accuracy | 98.74% (235/238) | 98.74% (235/238) |
| required precision (committed claims) | 100.00% (1019/1019) | 100.00% (1019/1019) |
| required recall | 99.80% (1022/1024) | 99.80% (1022/1024) |
| all-fields recall | 99.51% (1225/1231) | 99.51% (1225/1231) |
| zero-question coverage | 64.17% (154/240) | 64.17% (154/240) |
| zero-question correctness | 98.05% (151/154) | 98.05% (151/154) |
| necessary-question recall | 100.00% (25/25) | 100.00% (25/25) |
| safe fallback (refusals) | 100.00% (58/58) | 100.00% (58/58) |
| personal-data exclusion | 100.00% (108/108) | 100.00% (108/108) |
| false automation | 0 | 0 |
| questions asked | 48 | 48 |
| unnecessary questions | 1 | 1 |
| PII value leaks | 0 | 0 |

**0 of the 240 documents change level or false-automation status.** `required_precision` over all claims is 99.80% (1022/1024) -> 99.80% (1022/1024): the extra claims are tentative (LOW or MEDIUM) and never committed; the precision of what NINFA is sure about is 100.00% (1019/1019) in both.

### Unseen-file corpus (the Universal Understanding benchmark, 432 documents)

`python -m tests.benchmarks.universal_understanding_v2.compare BEFORE AFTER`, case by case:

```
417 cases: identical 417, IMPROVED 0, WORSE 0, CHANGED 0, NEW 0
(the 432 documents are 390 positives, 27 negatives and 15 unsupported files; the 15 unsupported files are not cases of the comparison; the safe-fallback target (negatives and unsupported files all refused) is met by both engines)
```

### Source Learning benchmark (104 documents, the TEST database, rolled back)

| measure | V3 | V4 |
|---|---:|---:|
| exact reuse | 100.00% (33/33) | 100.00% (33/33) |
| compatible reuse | 100.00% (22/22) | 100.00% (22/22) |
| repeated mapping questions on an unchanged source | 0 | 0 |
| wrong reuse | 0.00% (0/372) | 0.00% (0/372) |
| false automation with memory | 0 | 0 |

Source Learning is untouched: every target is met under V4 exactly as under V3. What differs is the engine-alone baseline (V4 reads more, so fewer files need a matching screen before a memory exists).

## 7. CSV dialect: DuckDB and CleverCSV

| file | truth | counting rule | DuckDB | CleverCSV | chosen |
|---|---|---|---|---|---|
| clean_semicolon | ';' | ';' | ';' | ';' | ';' |
| clean_comma | ',' | ',' | ',' | ',' | ',' |
| clean_tab | '\t' | '\t' | '\t' | '\t' | '\t' |
| pipe | '|' | ',' | '|' | '|' | ',' |
| semicolon_comma_decimals | ';' | ';' | ';' | ';' | ';' |
| comma_point_decimals | ',' | ',' | ',' | ',' | ',' |
| comma_quoted_thousands | ',' | ',' | ',' | ',' | ',' |
| comma_text_with_semicolons | ',' | ',' | ',' | ',' | ',' |
| semicolon_text_full_of_commas | ';' | ';' | ',' | ';' | ';' |
| title_above_semicolon | ';' | ';' | ';' | ';' | ';' |
| title_above_comma | ',' | ',' | ',' | ',' | ',' |
| trailing_delimiter | ';' | ';' | ';' | ';' | ';' |
| ragged_semicolon | ';' | ';' | ',' | ';' | ';' |
| two_columns_semicolon | ';' | ';' | ';' | ';' | ';' |
| two_columns_comma | ',' | ',' | ',' | ',' | ',' |
| single_quote_quoting | ',' | ',' | ',' | ',' | ',' |
| sep_hint | ';' | ';' | ';' | ';' | ';' |
| sparse_semicolon | ';' | ';' | ';' | ';' | ';' |
| single_column | '?' | ',' | ',' | None | ',' |

Over the 17 files whose delimiter NINFA reads (of 19):
- counting rule (V3): 17 / 17 right
- DuckDB: 15 / 17 right
- CleverCSV: 17 / 17 right
- chosen (rule + guard): 17 / 17 right
- time over 19 files: DuckDB 688 ms, CleverCSV 232 ms, counting rule: microseconds

**Finding: for the delimiters NINFA's importers read, a sniffer adds time and no accuracy.** The counting rule V3 already uses is right every time; DuckDB is wrong where the text is full of the other delimiter; CleverCSV agrees with the counting rule. **In the benchmark the second opinion was asked on 1 of the 145 CSV files** (`UC065`, a costs file with personal-data columns, 83% of its lines agreeing on a width; DuckDB agreed with the counting rule and nothing changed) and **CleverCSV was never reached** outside the stress file built to be ragged. The only thing a sniffer does that nothing else does is name a delimiter NINFA does not read (a pipe-delimited file) - which the product refuses anyway. DuckDB, CleverCSV and fsspec are therefore development dependencies.

## 8. Performance

Medians of 5 runs on a quiet machine, milliseconds. `mapping` is the step V4 replaces (`propose`); `total` is the whole `understand` call an upload makes. Only the first 2,000 rows are ever profiled.

| rows | kind | scan | mapping V3 | mapping V4 | total V3 | total V4 | V4 - V3 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | csv | 0.6 | 35.9 | 40.4 | 206.9 | 253.2 | +46 ms (+22%) |
| 100 | xlsx | 14.5 | 35.9 | 39.8 | 316.3 | 343.3 | +27 ms (+9%) |
| 1000 | csv | 3.8 | 103.7 | 134.1 | 933.5 | 1156.9 | +223 ms (+24%) |
| 1000 | xlsx | 114.8 | 94.4 | 120.9 | 1489.8 | 1631.8 | +142 ms (+10%) |
| 10000 | csv | 36.8 | 170.9 | 227.5 | 1632.5 | 2023.4 | +391 ms (+24%) |
| 10000 | xlsx | 1305.2 | 167.1 | 215.6 | 4919.9 | 5270.0 | +350 ms (+7%) |
| 40000 | csv | 144.3 | 169.5 | 222.0 | 1923.5 | 2301.9 | +378 ms (+20%) |
| 40000 | xlsx | 3906.3 | 161.2 | 213.5 | 10073.0 | 10431.5 | +358 ms (+4%) |

V4 adds between a few percent and about a fifth to an upload's understanding time: tens of milliseconds on a 100-row file, a few hundred on a 10,000-row one, where V3's own scan of an .xlsx already takes seconds. A profile is computed once per column sample, not once per kind of data.

## 9. What it costs

* External AI calls in the normal V4 path: **0** (`test_a_standard_v4_import_asks_no_model_and_the_same_file_would_ask_one_in_assist` has a control that asks).
* External AI cost per import: **EUR 0**, apart from the infrastructure NINFA already runs.
* Runtime dependency added: RapidFuzz (MIT, 1.6 MB, no dependencies).

## 10. Against the model (context, not a head-to-head)

On the same 290-file challenge population the OpenAI semantic layer's V1.1 report (real model, [smart-import-openai-assist-v1-1](smart-import-openai-assist-v1-1.md)) measured manual matching 155 -> 58, recall 82.6% -> 90.3%, 227 questions, 143 model calls. V4, with no model: manual matching 155 -> 127, recall 82.6% -> 84.3%, 154 questions, 0 calls. V4 therefore recovers about 29% of the matching screens the model removed and 22% of its recall gain. What it cannot do is name a money column, a room count or a date from the values alone - those need a name a model can read and a vocabulary cannot guess.

## 11. How this was measured, and what it does not prove

* **All documents are synthetic.** There is no real hotel file in this environment; ADR 0054's real-file gate is still pending, and V4 does not replace it.
* **I read the benchmark's held-out vocabulary** (it sits in the file that defines the challenge population) while auditing, before writing the V4 vocabulary. The vocabulary was then written from domain knowledge, and a test forbids copying any held-out phrase (it found and removed six overlaps: `Stay start`, `Stay end`, `Doc. n.`, `Shift day`, `Giorno turno`, `Num. unita`). Independence therefore rests on that test, on the unseen-file `holdout` split (not looked at while building V4) and on the problem corpus, not on blind authoring.
* **The problem corpus is mine.** Written before any V4 result and frozen except for one truth bug found from the V3 baseline; the single-typo corpus was added after the first results and is labelled.
* **The engine was corrected several times against these benchmarks** - and every correction is a test now; the main ones: a vocabulary phrase must never overrule an importer's own reading (`Imponibile`, `Totale soggiorno`); two columns that satisfy the same V3 rule must stay contested (`Issue date` / `Invoice date`, the one unsafe READY V4 ever produced, in the first version); a glued header must be cut with the same treatment as a spaced one (`numerocamere`, `canaledivendita`).
* **Claims precision** counts tentative (MEDIUM/LOW) claims too, and my `unnamed` documents mark the unnamed columns as "must be asked": a correct proposal there is not credited, so the precision column undervalues V4. The safety columns (`unsafe READY`, `certain and wrong`) are the ones to read.
* **The ablation's latencies were taken under load**; section 8 is the clean measurement.

## 12. The whole backend suite, under both engines

* default engine (`v3`, what CI runs), on the final engine and the final commit: `8872 passed, 6 skipped in 1189.43s (0:19:49)` (0 failed; the worker tests are in the same run)
* forced `SMART_IMPORT_UNDERSTANDING_ENGINE=v4` on the same suite and commit: `46 failed, 8826 passed, 6 skipped in 1284.38s (0:21:24)`

The suite forced onto V4 is a much harder test than the benchmarks: it pins every product decision of every earlier gate. Its first run found FOUR rule tests V4 broke, each a product decision (a channel is never named by its values alone; a header that says something NINFA knows is never read as another thing from its values; a repeated code is asked about, not dropped; and the one scope test of dependencies) - they are fixed and are tests of V4's own now. What still fails under V4 is listed by file:

| test file | failures under V4 |
|---|---:|
| `test_smart_import_ai_pipeline.py` | 26 |
| `test_vocabulary_certainty_default.py` | 6 |
| `test_live_openai_acceptance.py` | 4 |
| `test_smart_import_ai_immaterial.py` | 3 |
| `test_smart_import_ai_vocabulary_certainty.py` | 3 |
| `test_ai_egress_verify.py` | 1 |
| `test_ai_suggestion_confirmation.py` | 1 |
| `test_personal_headers.py` | 1 (its personal-value assertions pass; the failing line is `model.calls >= 1`) |
| `test_smart_import_ai_scope.py` | 1 |

Every file above is a test of the semantic (model) layer or of the way the rules and the model interact: they assert that the model WAS asked about a column (`model.calls >= 1`), or what happens when a stand-in model names a column V3's rules could not read. With V4 selected the rules read more, so the model is asked about fewer files and those assertions fail by design. They pass under V3 (the default), the model layer is `off`, and they would need V4-aware versions before V4 and the model layer are ever enabled together.

## 13. Known limitations

* IT/EN only; no PMS-specific vocabulary beyond generic exports.
* A file in which MANY headers are misspelled or nameless still goes to the matching screen: the product asks at most two confirmations one by one, and V4 respects that.
* Money (room revenue vs total, net vs gross), room counts and hours are never named by their values alone - on purpose.
* Mixed files and several tables in one sheet: unchanged (V3 asks which table).
* Labour rules not built: overtime coherence (V3 excludes overtime by name) and a repeated employee id (the labour model keeps no employee identity).
* DuckDB's column types and date formats are collected (`Dialect`) but nothing downstream consumes them: they are evidence for a later gate, and the sniffers are development dependencies.
* Source Learning keeps the engine's reading as evidence only; a family learned under V3 is reused under V4 (the benchmark above), but nothing was run on a database that holds real families.


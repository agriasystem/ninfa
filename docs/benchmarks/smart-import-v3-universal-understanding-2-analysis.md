# Smart Import V3 — Universal Understanding 2: analysis

Companion of `smart-import-v3-universal-understanding-2.md` (the AFTER run) and `...-before.md` (the engine of `fea4022`, same corpus, same
evaluator). Method: `services/api/tests/benchmarks/universal_understanding_v2/README.md`. AI is **off** everywhere
(`IMPORT_UNDERSTANDING_PROVIDER=unconfigured`; no model, cloud service or embedding is called).

## Before and after (360 positive documents, first upload, no learned profile)

| | Before | After | Target |
|---|---|---|---|
| False automation | 4 | **0** | 0 |
| P0 findings | 10 | **0** | 0 |
| Certain wrong reading of a critical fact | 3 | **0** | 0 |
| Necessary-question recall | 73.5 % | **100 %** | 100 % |
| Safe fallback (27 negatives + 15 unsupported) | 100 % | **100 %** | 100 % |
| Personal data: values shown or probe-sent, columns not left out | 22 events (13 values shown in 5 documents) | **0** | 0 |
| Domain accuracy (strict) | 96.9 % | **99.4 %** | >= 99 % |
| Header detection (strict) | 99.7 % | **100 %** | >= 99 % |
| Table detection (strict) | 99.7 % | **100 %** | >= 99 % |
| Required recall | 82.4 % | **100 %** | >= 99 % |
| Required precision (official definition) | 98.91 % | 99.40 % | >= 99.5 % — **not met** |
| Required precision, certain claims | 99.61 % | **99.82 %** | >= 99.5 % |
| Zero-question rate (of the documents that are clear) | 22.6 % | **94.8 %** | — |
| Unnecessary questions | 139 | **23** | — |
| Documents that ended MANUAL (positives importable) | 143 | 0 | — |

*Required precision, official definition*: every claim on a required field, at any level, counted again in the state after the person's answers
(so an amount the person has just confirmed as NET counts as a claim on a field the truth lists as "ambiguous"). It is 99.40 % because of 10 such claims
out of 1669: bare amounts the person then confirmed, the arrival and departure of reversed-dates documents (asked), a column of people's names under a
supplier header (asked), a group code (asked). The same counter gives 99.61 % on the official 240 documents. The figure that matters for safety is the committed one: of the claims shown as certain, 99.82 % are right and none is a wrong
critical fact in the first answer.

By group (after): bookings 120/120 recall, zero-question 100 %; staff 100 %, 94.6 %; costs 100 %, 89.1 %. By difficulty: EASY 94.4 %, MEDIUM 95.8 %,
HARD 92.3 %, ADVERSARIAL 100 % (the adversarial documents are refusals or questions by construction).

## Generalisation: dev and holdout

Every document is `dev` or `holdout` by the hash of its id. Failures were studied on `dev` only (for **bookings** the first vocabulary pass came from
the failure list of all 120 documents, so that group's split is only partially independent).

| | docs | recall | zero-question | FA | P0 | PII docs | domain | necessary Q | unnecessary Q |
|---|---|---|---|---|---|---|---|---|---|
| dev, before | 184 | 82.9 % | 18.9 % | 2 | 3 | 1 | 98.3 % | 57.9 % | 71 |
| holdout, before | 176 | 81.9 % | 26.4 % | 2 | 7 | 4 | 95.5 % | 93.3 % | 68 |
| dev, after the engine work | 184 | 100 % | 93.7 % | 0 | 0 | 0 | 100 % | 100 % | 12 |
| **holdout, measured before the post-holdout fixes** | 176 | **99.6 %** | **95.1 %** | 0 | 0 | 0 | 98.9 % | 100 % | 10 |
| holdout, final | 176 | 100 % | 95.8 % | 0 | 0 | 0 | 98.9 % | 100 % | 11 |

The holdout was not worse than the dev set it was kept apart from: the gain is not tuning to the studied cases. It is not proof about real
exporters either (see the limits). After the holdout run, six things it showed were fixed and are disclosed: the supplier word `Issuer`, the cost
category `Natura costo`, the due date `Pagabile entro` / `Pay By`, a group code is not a booking code, what is left after a commission is not the
commission, and the net of a line in a multi-line invoice. The holdout row "final" includes them.

## Error taxonomy (before), 204 of 360 documents with at least one field missed

| Cause | Evidence | What fixed it |
|---|---|---|
| **Vocabulary** (words other exporters use) | 364 missed fields: rooms 52, room revenue 39, line description 37, department 34, booking reference 31, departure 28, arrival 27, supplier 26, actual hours 18, channel 12... | concept families + written abbreviations |
| **Evidence unused** | `CI`/`CO` left a question (once the words were read) although the dates agree on every row; 48 hours "worked" in a day on a row that names the person read as certain (false automation, 1 document); an unrecognised planned or actual hours column left READY (false automation, 3 documents) | relations; person limits; the hours words |
| **Formats** | `06-apr-26`, `Nov 4, 2026` not dates (columns lost); a date over a two-digit year (`04/02/26`) invisible to the order check — latent: once the headers around it were read, such a document was offered as ready without the day/month question (found on the way, caught by the benchmark, mutation M9) | `value_text`, `normalization`, `date_pattern` |
| **Personal data nobody looked for** | guest requests ("Special Requests") shown as examples; employee badges shown (5 documents, 13 values) | `NOTE`, `ADDRESS`, `EMPLOYEE_ID` |
| **Truth mistakes of the benchmark** (not the engine) | commission rate labelled as an amount; booking numbers restarting every sheet; hidden-sheet documents with table facts; `Trasporti` mistaken for an unknown category; pipe files expected READY; people-as-suppliers expected "personal" | fixed in the generators, listed in the README |

## Question reduction

Official 240: asked 53 -> 50, unnecessary 21 -> 18 (**the target of 12, desired 8, was not reached without trading safety**). Gone: `Imponibile` of
credit notes (negatives), `N. documento` over a multi-line invoice, `Da chi` / `Cosa`, `Data reg.`, `F&B`. One new: the two dates of CO04 are now
asked as a choice (the document stays not automatic).

The 18 left in the 240 and the 25 left in V2, classified:

| Class | What | Count (240 / V2) |
|---|---|---|
| Already optimal — the specification asks for it | `DATES_REVERSED` on reversed arrival/departure; `DOMAIN` on a calendar or a restaurant takings that look like bookings; the second date of two plausible invoice dates; the choice between two near-identical date headers | 6 / 6 |
| Human required — NINFA must not guess | bare `Total`, `Importo`, `Imp.`, `Tot`, `Ricavo`, `Price` over amounts (B41 stays MEDIUM by the specification); `AMOUNT_BASIS` of a bare amount; a column of people's names under a supplier header | 6 / 4 |
| Prudential by an earlier decision | department codes `HK`/`FO`/`REC`, status codes `OK`/`CANC`/`NS`, category words NINFA's lexicon does not hold ("Canoni software", "Igiene e pulizia"): asked once and remembered (Question Reduction 1) | 5 / 11 |
| Deterministically solvable, **not solved** | `Reparto: Spa` in a label/value block above the table (`structure.py` drops those lines from the preamble: needs a structure change); a hand-made `Sched. Hrs`; three hours columns in a document that is refused anyway | 1 / 4 |

## Official 240, case by case

P0 0, P1 0, false automation 0/240, safe fallback 58/58, necessary questions 25/25, personal values 0. 232 cases identical, 3 improved, 1 worse
(P2, friction only), 4 changed:

* IMPROVED `C38` (`N. documento` over a multi-line invoice: no question), `C44` (`Data reg.`), `C46` (`Da chi`, `Cosa`): READY, no question.
* CHANGED `C33` credit notes: `Imponibile` LOW -> HIGH, the question is gone. `L36`: `F&B` no longer asked (`FO`, `HK`, `HSKP`, `REC` are). `C49` payroll
  with names: `Netto in busta` is no longer read as an amount (MANUAL -> BLOCKED, nothing imported either way). `L33` weekly summary: its hours
  are read LOW instead of HIGH (hours above a day on a row that names the person); still BLOCKED.
* WORSE `CO04` VAT register with two dates: MANUAL -> ASK (two `COLUMN_MEANING` about `Data doc.` / `Data reg.`). Two plausible invoice dates are a real
  choice; the document remains not automatic.

## Source Learning

Untouched (no file of `source_learning.py`, `smart_import.py`, the family or layout code changed). Evidence: the 109 + 6 Source Learning tests
(engine, flow, families, layout, benchmarks) pass; the Source Learning benchmark is identical but for the date and the timings (104 documents, 56/56 steps
as expected, no failure, cross-family / cross-property / cross-domain contamination 0, legacy storage intact); and the new secondary test
`test_universal_understanding_learning.py` teaches V2 documents (answer once, import, upload again as the next month: recognised, nothing asked).

One consequence to know: `Note` and `Annotazioni` are personal notes since this gate, so a column with such a header is (deliberately) not part of a
remembered shape. Five fixtures that used them as an incidental "junk column" now use a neutral header (`Colonna extra`).

## Performance (milliseconds per file)

| Stage (V2, 402 documents, median of 3) | mean before -> after | p95 before -> after | max before -> after |
|---|---|---|---|
| scan | 4.0 -> 4.0 | 7.3 -> 7.3 | 10.5 -> 11.9 |
| understanding (the rest) | 25.6 -> 26.0 | 47.5 -> 46.1 | 122.2 -> 90.7 |
| semantic mapping | 92.2 -> 93.8 | 161.6 -> 169.1 | 216.4 -> 248.3 |
| **total** | **121.8 -> 123.8 (+2 %)** | **205.3 -> 219.2 (+7 %)** | **344.4 -> 299.4** |

Official 240 (3 repeats, same machine, back to back): mean 131.0 -> 141.1 (+8 %), p50 108.3 -> 118.7 (+10 %), p95 175.7 -> 195.1 (+11 %), max +14 %.
Source Learning benchmark, back to back: understanding with a memory 93.7 -> 97.9 (+4 %), without 97.4 -> 93.2. No figure exceeds the +20 % flag.

## Sabotage: break one rule, see what notices

Each critical rule was disabled in turn (`sabotage.py`, the file restored after each); the unit tests and the V2 group concerned were run.

| Rule broken | Tests that fail | Metric that worsens (V2 group) |
|---|---|---|
| M1 relations never promote | 2 | zero-question 100 % -> 85.3 %, unnecessary questions 1 -> 30 (bookings) |
| M2 abbreviations expanded even when ambiguous | 1 (`Imp.`) | recall 100 -> 98.7 %, zero-question 89.1 -> 81.5 %, P1 0 -> 13 (costs) |
| M3 no plausibility limit per person | 2 | **false automation 0 -> 1, P0 0 -> 1** (staff) |
| M4 a repeated booking code is as good as any | 1 | none visible in V2 (caught by the test only) |
| M5 a payslip may be an amount | 1 | none visible in V2 (those documents stay not automatic) |
| M6 free text about a person is not personal | 8 | **personal values 0 -> 1, P0 0 -> 1** (bookings) |
| M7 an employee badge is not personal | 5 | **personal values 0 -> 12, P0 0 -> 4** (staff) |
| M8 the net of a line is never the invoice net | 2 | zero-question 89.1 -> 85.9 %, necessary-question recall 100 -> 90 %, P1 0 -> 6 (costs) |
| M9 two-digit years are not dates to decide on | 1 | **false automation 0 -> 1, P0 0 -> 1**, necessary-question recall 100 -> 90 % (costs) |
| M10 negative amounts are suspect in a register | 1 | zero-question 89.1 -> 84.8 %, unnecessary questions 16 -> 20 (costs) |

Every mutation is caught by at least one test. M4 and M5 are protected by a test but not measured by the benchmark: V2 has no document where they are the
only thing between the engine and a mistake.

## Residual findings (final run)

One P1: `UB104` — a column `Pratica` over a group code that repeats is claimed as the booking code at LOW and asked about (the document holds no booking
code; the claim is a question, never a mapping). Five P2 domain readings of documents that are refused anyway (inventory read as costs at MEDIUM
with a DOMAIN question). 25 unnecessary questions (classified above). No false automation, no certain wrong reading, no personal value.

## Limits (the honest list)

* The corpus was written by the same person who improved the engine; vocabularies come from reading what exports look like, not from customers' files.
  The holdout is a check against tuning to what was studied, not against a shared blind spot.
* Value profiling is partial (identifier shapes, negatives, plausibility, date forms), not the full class taxonomy of the task; there is no new domain
  graph, no table-classifier rewrite, and only two relations (arrival/departure, hours per person).
* The pipe delimiter is refused on purpose; UTF-16 is refused; a hidden sheet is never read.
* Required precision (official definition) is 99.40 %, under the 99.5 % target, for the reason explained above.
* Question Reduction 2 reached 18 unnecessary questions in the 240 (from 21), not the 12 asked for.

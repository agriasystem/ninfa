# Smart Import V3 — Universal Understanding 2: analysis

Companion of `smart-import-v3-universal-understanding-2.md` (the AFTER run) and `...-before.md` (the engine of `fea4022`, same corpus, same
evaluator). Method: `services/api/tests/benchmarks/universal_understanding_v2/README.md`. AI is **off** everywhere
(`IMPORT_UNDERSTANDING_PROVIDER=unconfigured`; no model, cloud service or embedding is called).

## Before and after (360 positive documents, first upload, no learned profile)

| | Before | After | Target |
|---|---|---|---|
| False automation | 4 | **0** | 0 |
| P0 findings | 10 | **0** | 0 |
| Certain wrong reading of a critical fact (first answer) | 3 | **0** | 0 |
| Necessary-question recall | 73.5 % | **100 %** | 100 % |
| Safe fallback (27 negatives + 15 unsupported files) | 100 % | **100 %** | 100 % |
| Personal data: values shown or probe-sent, columns not left out | 22 events (13 values shown in 5 documents) | **0** | 0 |
| Domain accuracy (strict) | 96.9 % | **99.4 %** | >= 99 % |
| Header detection (strict) | 99.7 % | **100 %** | >= 99 % |
| Table detection (strict) | 99.7 % | **100 %** | >= 99 % |
| Required recall | 82.5 % | **100 %** | >= 99 % |
| Required precision (official definition) | 98.91 % | 99.40 % | >= 99.5 % — **not met** |
| Required precision, certain claims | 99.61 % | **99.82 %** | >= 99.5 % |
| Zero-question rate (of the documents that are clear) | 22.6 % | **94.8 %** | — |
| Unnecessary questions | 139 (of 176 asked) | **23** (of 67) | — |
| Importable documents that ended MANUAL | 143 | 0 | — |

*Required precision, official definition*: every claim on a required field, at any level, counted again in the state after the person's answers
(so an amount the person has just confirmed as NET counts as a claim on a field the truth lists as "ambiguous"). It is 99.40 % because of 10 such claims
out of 1669: bare amounts the person then confirmed, the arrival and departure of reversed-dates documents (asked), a column of people's names under a
supplier header (asked), a group code (asked). The same counter gives 99.61 % on the official 240 documents. The figure that matters for safety is the
committed one: of the claims shown as certain, 99.82 % are right and none is a wrong critical fact in the first answer.

By group (after): bookings recall 100 %, zero-question 100 %; staff 100 %, 94.6 %; costs 100 %, 89.1 %. By difficulty: EASY 94.4 %, MEDIUM 95.8 %,
HARD 92.3 %, ADVERSARIAL 100 % (the adversarial documents are refusals or questions by construction).

## Generalisation: dev and holdout

Every document is `dev` or `holdout` by the hash of its id. Failures were studied on `dev` only (for **bookings** the first vocabulary pass came from
the failure list of all 120 documents, so that group's split is only partially independent).

| | docs | recall | zero-question | FA | P0 | PII docs | domain | necessary Q | unnecessary Q |
|---|---|---|---|---|---|---|---|---|---|
| dev, before | 184 | 83.1 % | 18.9 % | 2 | 3 | 1 | 98.3 % | 57.9 % | 71 |
| holdout, before | 176 | 81.9 % | 26.4 % | 2 | 7 | 4 | 95.5 % | 93.3 % | 68 |
| dev, after | 184 | 100 % | 93.7 % | 0 | 0 | 0 | 100 % | 100 % | 12 |
| **holdout, first measurement (before the post-holdout fixes)** | 176 | **99.6 %** | **95.1 %** | 0 | 0 | 0 | 98.9 % | 100 % | 10 |
| holdout, final | 176 | 100 % | 95.8 % | 0 | 0 | 0 | 98.9 % | 100 % | 11 |

The holdout was not worse than the dev set it was kept apart from: the gain is not tuning to the studied cases. It is not proof about real
exporters either (see the limits). After the first holdout run, six things it showed were fixed and are disclosed: the supplier word `Issuer`, the
cost category `Natura costo`, the due date `Pagabile entro` / `Pay By`, a group code is not a booking code, what is left after a commission is not
the commission, and the net of a line in a multi-line invoice. The holdout row "final" includes them.

## Error taxonomy (before): 204 of 360 documents with at least one field missed (362 fields)

| Cause | Evidence | What fixed it |
|---|---|---|
| **Vocabulary** (words other exporters use) | rooms 52, room revenue 39, line description 37, department 34, booking reference 31, departure 28, arrival 27, supplier 26, actual hours 18, channel 12... | concept families + written abbreviations |
| **Evidence unused** | `CI`/`CO` left a question (once the words were read) although the dates agree on every row; 48 hours "worked" in a day on a row that names the person read as certain (false automation, 1 document); an unrecognised planned or actual hours column left READY (false automation, 3 documents) | relations; person limits; the hours words |
| **Formats** | a month name first (`Nov 4, 2026`) was not a date; a numeric date over a two-digit year (`04/02/26`) was a date for the structure but invisible to the order check — latent: once the headers around it were read, such a document was offered as ready without the day/month question (found on the way, caught by the benchmark, mutation M9) | `value_text`, `normalization`, `date_pattern` |
| **Personal data nobody looked for** | guest requests ("Special Requests") shown as examples; employee badges shown (5 documents, 13 values) | `NOTE`, `ADDRESS`, `EMPLOYEE_ID` |
| **Truth mistakes of the benchmark** (not the engine) | commission rate labelled as an amount; booking numbers restarting every sheet; hidden-sheet documents with table facts; `Trasporti` mistaken for an unknown category; pipe files expected READY; people-as-suppliers expected "personal" | fixed in the generators, listed in the README |

## Question reduction

Official 240: asked 53 -> 52, unnecessary 21 -> 20. **The target of 12 (desired 8) was not reached**, and it was not forced: of the 20 left, none could be
removed without trading a protection or an earlier decision.
Gone: `Imponibile` of credit notes (negatives), `N. documento` over a multi-line invoice, `Data reg.`, `F&B`. New: the two dates of CO04 are now asked as a choice
(the document stays not automatic).

The questions left, classified (240 and V2 together):

| Class | What |
|---|---|
| Already optimal — the specification asks for it | `DATES_REVERSED` on reversed arrival/departure; `DOMAIN` on a calendar, an inventory or a restaurant takings that look like bookings or costs; the second date of two plausible invoice dates; the choice between two near-identical date headers |
| Human required — NINFA must not guess | bare `Total`, `Importo`, `Imp.`, `Tot`, `Ricavo`, `Price` over amounts (B41 stays MEDIUM by the specification); `AMOUNT_BASIS` of a bare amount; a column of people's names under a supplier header; hours above a day on a row that names the person |
| Prudential by an earlier decision | department codes `HK`/`FO`/`REC`, status codes `OK`/`CANC`/`NS`, category words NINFA's lexicon does not hold ("Canoni software", "Igiene e pulizia": 11 of V2's 23), the loose words of a hand-made sheet `Da chi`/`Cosa` (a hardening test says "confirmed, not trusted"): asked once and remembered |
| Deterministically solvable, **not solved** | `Reparto: Spa` in a label/value block above the table (`structure.py` drops those lines from the preamble: needs a structure change); `Sched. Hrs` |

Two changes that would have removed more were tried and **taken back** because the existing suite says otherwise: reading a month name over a short year
(`26-ott-26`: "a year is never invented") and trusting `Da chi`/`Cosa` ("two loose names: confirmed, not trusted").

## Official 240, case by case

P0 0, P1 0, false automation 0/240, safe fallback 58/58, necessary questions 25/25, personal values 0. 233 cases identical, 2 improved, 1 worse
(P2, friction only), 4 changed:

* IMPROVED `C38` (`N. documento` over a multi-line invoice) and `C44` (`Data reg.`): READY, no question.
* CHANGED `C33` credit notes: `Imponibile` LOW -> HIGH, the question is gone. `L36`: `F&B` no longer asked (`FO`, `HK`, `HSKP`, `REC` are). `C49` payroll
  with names: `Netto in busta` is no longer read as an amount (MANUAL -> BLOCKED, nothing imported either way). `L33` weekly summary: its hours
  are read LOW instead of HIGH (hours above a day on a row that names the person); still BLOCKED.
* WORSE `CO04` VAT register with two dates: MANUAL -> ASK (two `COLUMN_MEANING` about `Data doc.` / `Data reg.`). Two plausible invoice dates are a real
  choice; the document remains not automatic.

## Source Learning

Untouched (no file of `source_learning.py`, `smart_import.py`, the family or layout code changed). Evidence: the Source Learning tests (engine, flow,
families, layout, benchmarks) pass; the Source Learning benchmark is identical but for the date and the timings (104 documents, 56/56 steps as
expected, no failure, cross-family / cross-property / cross-domain contamination 0, legacy storage intact); and the new secondary test
`test_universal_understanding_learning.py` teaches V2 documents (answer once, import, upload again as the next month: recognised, nothing asked; the
documents that ask which of two tables are left out — a table choice is not a fact a family remembers, as before this gate).

One consequence to know: `Note` and `Annotazioni` are personal notes since this gate, so a column with such a header is (deliberately) not part of a
remembered shape. Five fixtures that used them as an incidental "junk column" now use a neutral header (`Colonna extra`).

## Performance (milliseconds per file)

| Stage (V2, 402 documents, median of 3) | mean before -> after | p95 before -> after | max before -> after |
|---|---|---|---|
| scan | 4.6 -> 4.4 | 8.8 -> 7.9 | 14.1 -> 12.3 |
| understanding (the rest) | 28.6 -> 28.0 | 50.4 -> 51.0 | 126.3 -> 86.4 |
| semantic mapping | 101.3 -> 100.1 | 182.3 -> 189.4 | 292.3 -> 266.6 |
| **total** | **134.5 -> 132.5 (-1 %)** | **232.9 -> 241.8 (+4 %)** | **360.9 -> 329.9** |

Official 240 (3 repeats, same machine, back to back): mean 137.8 -> 141.8 (+3 %), p50 114.4 -> 117.2 (+2 %), p95 185.4 -> 190.5 (+3 %), max -3 %.
Source Learning benchmark, back to back: understanding with a memory 93.7 -> 97.9 (+4 %), without 97.4 -> 93.2. No figure exceeds the +20 % flag.

## Sabotage: break one rule, see what notices

Each critical rule was disabled in turn (the file restored after each); the unit tests and the V2 group concerned were run. (Run before the last two
reversions, which do not touch these rules.)

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
code; the claim is a question, never a mapping). Six P2 readings on documents that are refused anyway: three inventories read as costs at MEDIUM (two with a
DOMAIN question), a restaurant takings read as staff (DOMAIN question), a staff period summary read as nothing (BLOCKED), and an amount of rooms
claimed at MEDIUM in a bookings file under a costs title (DOMAIN question). 23 unnecessary questions (classified above). No false automation, no certain wrong reading, no personal value.

## Limits (the honest list)

* The corpus was written by the same person who improved the engine; vocabularies come from reading what exports look like, not from customers' files.
  The holdout is a check against tuning to what was studied, not against a shared blind spot.
* Value profiling is partial (identifier shapes, negatives, plausibility, date forms), not the full class taxonomy of the task; there is no new domain
  graph, no table-classifier rewrite, and only two relations (arrival/departure, hours per person).
* The pipe delimiter is refused on purpose; UTF-16 is refused; a hidden sheet is never read; a month name over a short year is refused.
* Required precision (official definition) is 99.40 %, under the 99.5 % target, for the reason explained above.
* Question Reduction 2 reached 20 unnecessary questions in the 240 (from 21), not the 12 asked for.

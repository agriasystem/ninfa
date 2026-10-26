# Smart Import V3 - question reduction 1

Branch `fix/smart-import-v3-question-reduction-1`, started from `main` = `8e3370d` (hardening 2 merged). It asks fewer questions - and
gives up none of the prudence of hardening 1 and 2. Deterministic, no assistant (`IMPORT_UNDERSTANDING_PROVIDER=unconfigured`), no migration.
The benchmark is the one on `main`: 240 synthetic documents, the same corpus (sha256 `6262d3b06dfe9db6...`), the same truth - none of them
was touched. Two things were ADDED to the evaluator, nothing changed in how a document is scored: the questions-per-import numbers and the
zero-question rate among valid files (`metrics.py`, `report.py`).

The "Hardening 2" column is a fresh run of `main` with the same evaluator (it reproduces `smart-import-v3-benchmark-v1-hardening-2.json`
document by document: 151 questions, 119 unnecessary, 96 documents). Result file:
`services/api/tests/benchmarks/results/smart-import-v3-benchmark-v1-question-reduction-1.json` (the earlier result files are kept).

The rule: **SAFE + PROVEN -> silent. AMBIGUOUS + BUSINESS-CRITICAL -> ask. UNSUPPORTED -> manual / blocked.** A question is asked only if the
answer can change the mapping, the validation, the safety or the result of the import.

## Result

| Metric | Hardening 2 | Question reduction 1 |
|---|---|---|
| Questions asked | 151 | **53** (-65%) |
| Unnecessary questions | 119 | **21** (-82%; target <= 48) |
| Documents with an unnecessary question | 96 | **18** |
| Necessary-question recall | 100% (25/25) | **100% (25/25)** |
| False automation | 0.0% (0/240) | **0.0% (0/240)** |
| P0 findings / documents | 0 / 0 | **0 / 0** |
| P1 findings / documents | 0 / 0 | **0 / 0** |
| Personal values in the browser answer | 0 | **0** |
| Personal values in what a model would be shown | 0 | **0** |
| Personal columns left out | 100% (108/108) | 100% (108/108) |
| Safe fallback / strict | 100% (58/58) / 100% (29/29) | **100% (58/58) / 100% (29/29)** |
| Wrong-card probe | 182/182 asked, 0 automatic | **182/182 asked, 0 automatic** |
| Domain accuracy | 98.7% (235/238) | 98.7% (235/238) |
| Header accuracy / table boundary | 100% / 100% | 100% / 100% |
| Required-field precision | 99.6% (1019/1023) | 99.6% (1019/1023) |
| Required-field recall | 99.7% (1019/1022) | 99.7% (1019/1022) |
| Documents offered as automatic (zero-question coverage) | 91 (37.9%) | **150 (62.5%)** |
| Zero-question correctness, every field | 98.9% (90/91) | 98.7% (148/150) |
| Zero-question correctness, business-critical fields | 100% (91/91) | **100% (150/150)** |
| Zero-question rate among the files the truth says are valid (READY) | 54.6% (89/163) | **90.8% (148/163)** |
| Levels (READY / ASK / MANUAL / BLOCKED) | 91 / 97 / 42 / 10 | 150 / 38 / 41 / 11 |
| Findings P2 | 129 | 31 |
| Documents with no finding at all | 143 | 215 |

Questions per importable file (the 182 files the truth says can be imported, READY or ASK; all the different questions of the whole conversation):

| | Mean | Median | p95 | Max | Files with no question |
|---|---|---|---|---|---|
| Hardening 2 | 0.62 | 1 | 2 | 3 | 89 |
| Question reduction 1 | **0.22** | **0** | **1** | **2** | **148** |

The two "every field" misses of the zero-question correctness are optional fields only (`B36`: the optional `Importi - Totale`; `C17`: the
optional category of a register), as before; no document offered as automatic is wrong on a business-critical field.

Time per document, mean / p50 / p95 / max (ms): 124 / 100 / 166 / 1805 on `main`, 150 / 122 / 204 / 2175 on the branch in the benchmark runs -
a difference of the machine, not of the code: timed again back to back, alternating the two trees, the branch gave 142 and 149 ms (mean) and
`main` 152 and 139. The new code is a few milliseconds (profiled: `channel_words` 7 ms and the department list 15 ms over 40 documents).

## What was removed, by family

| Family (unnecessary questions) | Before | After |
|---|---|---|
| Channel (`Canale`, `Channel`, `Provenienza`, `Source`, `Src`, `Can.`...) | 54 | **0** |
| Reservation code (`Codice`, `Cod.`, `Book Number`) | 4 | **0** |
| `DOMAIN` | 9 | 1 |
| `VALUE_LABELS` (department words, cost categories, status) | 18 | 3 |
| `DEPARTMENT_ROWS` | 4 | 2 |
| `AMOUNT_BASIS` | 4 | **0** |
| An amount that does not say what it holds | 9 | 6 |
| Other column meaning | 15 | 7 |
| `DATES_REVERSED` (the question this line of work was asked to add) | 2 | 2 |
| **Total** | **119** | **21** |

**Channel (54 -> 0).** *Cause:* the column was recognised by its header, but the only values NINFA knew as channels were five names
(`Booking.com`, `Expedia`, `Airbnb`, `Diretto`, `Direct`); with `Telefono`, `Email`, `Sito web`, `Walk-in` in the column fewer than 60% of the values
were known and the column stayed a maybe - one question on 43 of the 80 bookings files. *Rule* (`channel_words.py`, header AND values): a channel
header over values that are, for the most part, the words a hotel uses for how a booking arrived (OTAs and metasearch, the website, phone, e-mail,
walk-in, agencies and operators; whole words only: `ota` is a channel, `hotel` is not) is certain. Over countries (`Italia`, `Germania`...) it is not
a channel at all - the column is left out and the file, having no channel, is not imported. Over words nobody knows (`Alfa`, `Beta`) it stays a maybe
and is asked. Codes of a channel manager (`BDC`, `EXP`, `ABB`, `DIR`) count only under a header that already says "channel". A channel the hotel
already taught (`channel_mapping` of the saved source: `BDC` is Booking.com) is one more word for the column (`channel_by_taught`; property-scoped,
read from the saved source, never shared).

**Domain (9 -> 1).** *Cause:* a file that points at no kind of data (a bank statement, a restaurant menu, a payroll, a cash book, a utilities summary,
a matrix of categories by month) was asked "what kind of data is this?" with no candidate: no answer changes anything, the file cannot be imported.
*Rule:* the card the person came from is a WEAK PRIOR. It is argued with only when the document points at ANOTHER kind of data (`DOMAIN` with a
candidate, as before, and now asked ALONE: what else the file would need - a department for the "staff rows" of a bookings file, the basis of an
amount that is not a cost - depends on the answer). A file that points nowhere is never `READY` (the card alone is not evidence) and ends in the
matching screen with what it lacks. The optional assistant, if one is ever configured, may still say "this is another kind of data" for such a file;
that becomes a suggested `DOMAIN` question. The one left (`B51`, an occupancy calendar the detector reads as staff) is a real conflict.

**Cost categories (9 -> 0).** *Cause:* `Colazioni` (breakfasts) was the only word of a standard register NINFA did not know. *Rule:* more words with ONE
category each - `Colazioni`/`Ristorazione` food, `Housekeeping`/`Detersivi` cleaning, `Energia elettrica`/`Riscaldamento`/`Metano` utilities,
`Commissioni Booking`/`Expedia` OTA commissions. A word that could be two (`Food & Beverage` is food OR beverage; `Forniture`) is NOT decided: asked
once, remembered. Only the unknown word is asked about (`Pool Service`), never the known ones with it.

**Departments (VALUE_LABELS 4, DEPARTMENT_ROWS 2).** *Rule:* a short list of department words on top of the import's own rules - `Ricevimento`,
`Portineria`, `Ristorante`, `Governante`, `Barista`, `Manutentore`, `Amministrazione`, `Booking`, `Centro benessere`... - each with ONE department. The
job reads as its department (`Receptionist` and `Reception`, `Chef` and `Cucina`: the original value stays in the import). The words travel in the
decision (`labels`), so the import files them the same way; the list is opt-in for the understanding and the V2 dry-run path keeps the import's rules
alone. A word that could be two departments (`MAN`, `Cameriere ai piani`) or a code only this hotel uses (`HK`, `FO`) is still asked, once, and
remembered. Also: `Centro operativo` is read as the department when its values say so.

**Reservation code, dates, hours (the confirmations the rest of the file answers).** `Cod.`/`Codice`/`Book Number` over values that are all
different, in a list of reservations whose booked-at, arrival and departure are all recognised by their own names, is the code. `Created`, `gg`,
`H previste` and `Ore Lav.` are read where their values prove them. `Totale IVA inclusa` says the amount is gross: it is not asked, it is not imported
(`AMOUNT_NOT_NET`).

**Premature questions (VALUE_LABELS 2, AMOUNT_BASIS 3, column meanings 5).** While the file lacks something the import cannot do without, or is a kind of
document it cannot read (a weekly summary), asking what its columns and words mean changes nothing: the person matches the columns by hand first and the
questions come back when they can change the result. The basis of an amount is kept when the amount is what is missing (its answer settles it).

**Two look-alike columns where one is also another field (`B07`).** Removing the channel question showed a defect it had been hiding: `Importo camere` and
`Totale soggiorno` both satisfied the room-revenue rule, so neither was taken and the file ended with the room revenue missing (a P1 once the screen no longer
asked). Columns that claim one field in the same words are still a choice - unless all but one of them is, by its own words, also the name of another field
nobody has taken. Here the room revenue is `Importo camere`, the total is `Totale soggiorno`. `Ore previste` / `Ore previste (rev.)` and one net per VAT rate
stay a choice.

## The documents that carry the guarantees of hardening 1 and 2

`L07`, `L25`, `L56`, `L62`, `B25`, `C42`, `CO04`, `LO13`, `B41`, `L57`: identical to the letter (level, mapping, questions, findings). `B43` and `B34`
are now `READY` (their only question was the channel; the truth says `READY`). `C49` (a payroll with names on the costs card) is still `MANUAL`, without the
question "what is this?". `B50` and `B55` (arrival after departure) are still `ASK` with `DATES_REVERSED`, without the channel question; nothing is swapped,
nothing is imported. `B41`: a lone `Total` stays MEDIUM with its confirmation (intentional).

## What is still asked: all 53, by kind

| Question | Asked | Unnecessary by the truth | Why the rest stays |
|---|---|---|---|
| `COLUMN_MEANING` | 18 | 13 (listed below) | two columns that say the same thing (`L24`, `L25`, `B64`), an amount that does not say what it holds, the person's pick of hours, a reservation code over repeated values |
| `VALUE_LABELS` | 8 | 3 | department codes only the hotel uses (`HK`, `MAN`, `Turno A`), unknown cost categories (`Assicurazioni`), booking statuses (`OK`, `CANC`, `NS`) |
| `DOMAIN` | 6 | 1 | the file is clearly another kind of data than the card (the 5 wrong-card files) |
| `TABLE` | 4 | 0 | several plausible tables |
| `DEPARTMENT_CONFIRM` | 4 | 0 | the department only in the title |
| `DATE_ORDER` | 3 | 0 | `03/04` read two ways |
| `DATES_REVERSED` | 2 | 2 | arrival after departure |
| `AMOUNT_BASIS` | 2 | 0 | `Importo` / `Totale` that do not say whether VAT is in |
| `GRID_HOURS`, `PERIOD` | 2, 2 | 0 | a grid of days: planned or actual; which week |
| `DEPARTMENT_ROWS` | 2 | 2 | no department anywhere |

## The 21 unnecessary questions that are left (by the truth; most are asked on purpose)

| Count | Question | Documents | Why it stays |
|---|---|---|---|
| 6 | an amount that does not say what it holds: `Total`, `Tot`, `Ricavo`, `Imp.`, `Price`, `Imponibile` | `B41`, `BO03`, `B42`, `BO01`, `B14`, `C33` | money is never decided by a word (a bare total, an "importo", credit notes with negative amounts) - `B41` is the confirmed prudential question |
| 2 | `DATES_REVERSED` | `B50`, `B55` | the question this line of work added; the files are wrong |
| 3 | `VALUE_LABELS` | `L36`, `LO15` (`HK`, `FO`, `REC`...), `BO09` (`OK`, `CANC`, `NS`) | codes and abbreviations are the hotel's own, asked once and remembered; the truth reads them as obvious, the product (and `understanding_labor`) deliberately does not |
| 1 | `COLUMN_MEANING (Stato)` | `BO09` | follows from the status labels above |
| 2 | `COLUMN_MEANING (Check-in)`, `(Check-in effettivo)` | `B64` | two near-identical date columns: a real choice |
| 2 | `DEPARTMENT_ROWS` | `L62`, `LO07` | `L62`: the department column holds people (a real gap); `LO07`: "Reparto: Spa" as a label and a value above the table is not read as the department yet |
| 1 | `DOMAIN` | `B51` | an occupancy calendar the detector reads as staff: contrary evidence, so the card is argued with |
| 4 | `COLUMN_MEANING` | `N. documento` (`C38`, one invoice on several lines), `Data reg.` (`C44`: registration date, not document date), `Da chi`, `Cosa` (`C46`, informal headers) | a column whose words are only fairly sure and whose values cannot prove it |

## Behaviour changed on purpose (to confirm)

* A file that points at no kind of data is no longer asked "what is this?": it ends in the matching screen, never `READY` (existing test changed:
  `test_a_file_that_looks_like_nothing_known_is_not_asked_what_it_is_and_is_not_imported`; the assistant's version of it became "ask only if the model
  says it is another kind", plus a test that a model that agrees with the card adds no question).
* A bare code column over different codes in a list of reservations is the code (existing test split in two: the old confirm-and-answer flow now
  runs on repeated values).
* Department/status codes (`HK`, `FO`, `OK`, `CANC`) are still asked - against the truth of the corpus, with the product's rule and the brief's scope
  ("abbreviations already learned in the profile"). `Food & Beverage` and `Forniture` are not mapped to a category for the same reason.
* Three negative documents (`B44`, `BO04`, `CO02`) gain a P2 `FIELD_MISSED`: their column and amount questions are deferred while a blocker keeps them from
  being imported, so the benchmark's conversation cannot answer them (they are refusals either way). `L09`, in the other direction, now reads its department.
* The assistant's evidence is built for one document fewer (30 instead of 31 documents in the egress probe): the file that no longer needs a model.

## Tests

`test_smart_import_question_reduction.py` (73: channel by header and values, countries are not channels, codes, taught channels, the card as a weak prior,
cost categories known/mixed/taught, departments known/ambiguous/taught/too long, the loose reservation code, the basis of an amount, and every neighbour that
must still be asked), the existing `DOMAIN` tests and the bare-code test updated. Backend: ruff, ruff format, mypy strict and the full suite (5204 passed
on the final tree). Frontend: untouched (no new question kind).

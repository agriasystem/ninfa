# Smart Import V3 - deterministic hardening 1

Branch `fix/smart-import-v3-hardening-1`, started from `main` = `48a1a656` with the two benchmark commits (`1c039aa`, `3386957`)
brought in unchanged. The measure is `Smart Import Intelligence Benchmark V1`: 240 synthetic documents, the same corpus
(sha256 `6262d3b06dfe9db6...`, identical before and after) and the same hand-written truth: the manifest, the corpus and the
model are byte-identical to the benchmark commit `3386957` (`git diff 3386957 --` on them is empty). Only the EVALUATOR changed,
once (`match.py`, `score.py`: see "Benchmark methodology correction"). The optional assistant stays off
(`IMPORT_UNDERSTANDING_PROVIDER=unconfigured`): no model was called, before or after.

**Both columns of the table below were measured with the SAME evaluator** - the one with the column-identity correction (see
"Benchmark methodology correction"): the baseline is `main` (`48a1a656`) run in a temporary worktree with the corrected scorer
overlaid, the "after" is this branch.

Result files (in `services/api/tests/benchmarks/results/`):

| File | What |
|---|---|
| `smart-import-v3-benchmark-v1-baseline-corrected.json` | `main` 48a1a656, corrected evaluator - the BEFORE column |
| `smart-import-v3-benchmark-v1-hardening-1-corrected.json` | this branch, corrected evaluator - the AFTER column |
| `smart-import-v3-benchmark-v1.json` | the historical baseline, first evaluator (kept) |
| `smart-import-v3-benchmark-v1-hardening-1.json` | the first rerun of this branch, first evaluator (kept; superseded) |

The two corrected files differ from the two historical ones in ONE document (`B25`), see below. Rerun, from `services/api`:
`python -m tests.benchmarks.smart_import_v3 --json <file> --markdown <file>` (always name the two outputs: by default the runner
overwrites the baseline files).

## Result

| Metric | Before | After |
|---|---|---|
| False automation rate | 2.1% (5/240) | **0.0% (0/240)** |
| Zero-question correctness | 91.4% (74/81) | 98.9% (88/89) |
| Zero-question documents | 81 | 89 |
| Personal columns left out (PII exclusion) | 99.1% (107/108) | **100.0% (108/108)** |
| Personal values in the browser answer | 12 (3 documents) | **0 (0 documents)** |
| Personal values in what a model would be shown | 10 (2 documents) | 0 |
| Domain accuracy | 97.5% (232/238) | 98.7% (235/238) |
| Header accuracy | 99.1% (233/235) | 100.0% (235/235) |
| Table boundary accuracy | 98.7% (232/235) | 100.0% (235/235) |
| Required-field precision | 99.0% (981/991) | 99.6% (1011/1015) |
| Required-field recall | 96.1% (981/1021) | 98.9% (1011/1022) |
| Safe fallback (documents to refuse) | 96.6% (56/58) | **100.0% (58/58)** |
| Safe fallback, strict | 100.0% (29/29) | 100.0% (29/29) |
| Junk columns that became a field | 2 | 0 |
| Necessary-question recall | 96.0% (24/25) | 100.0% (25/25) |
| Unnecessary-question rate | 79.6% (117/147) | 78.2% (115/147) |
| Wrong-card probe (uploaded on another card) | 182/182 asked, 0 automatic | 182/182 asked, 0 automatic |
| Documents whose worst finding is P0 / P1 | 11 / 26 | **0** / 5 |
| Findings P0 / P1 | 16 / 41 | 0 / 10 |
| Time per document, mean / p95 / max (ms) (one run each, machine not isolated) | 111 / 155 / 1501 | 144 / 188 / 2061 |

No P0 finding is left. The one zero-question document that is not "fully correct" (`C17`, the category words `luce`, `acqua`,
`gas` under `Voce`) misses a field that is not business-critical. Under the corrected evaluator the baseline has ONE more P0 than the
first measure showed (`B25`, below): its wrong reading is now visible.

## P0 - closed, one by one

**`L07_reparto_slash_mansione_ore_prog` - planned hours silently lost.** `Ore prog.` was not a word of the planned-hours rule, and
a column that is clearly "hours" but does not say which was asked about only when no hours column at all was recognised - here
`Ore effettive` satisfied the requirement, so the column vanished and the file was offered as automatic. Two fixes: `prog`
(and `pian`, `prev`, `eff`, `svolte`) are words of the rules, and a column of hours that does not say which is asked about
whenever it could be a field of a required group, even if the sibling column is there. Hours of another kind (`Ore da
contratto`, straordinario, ferie, pausa...) are left alone, as the benchmark's `L55` requires.

**`L25_near_duplicate_hours_headers` - `Ore previste` / `Ore previste (rev.)`, one chosen with HIGH.** Two columns that satisfy
the SAME rule of one field (`Candidate.rule`) are a choice, not a guess: neither is taken (`proposal.CONTESTED`) and each is
asked about ("is X the planned hours?"). Answering for one settles the other. Columns that satisfy different rules (`Reparto` /
`Mansione`) are not a choice. No frontend change: it is the existing `COLUMN_MEANING` question with a candidate.

**`B43_office_repeated_header_every_page` - 8 records read, 24 in the document.** The fixture has no repeated header: a
`--- pagina successiva ---` line every 8 records was taken for a note, and everything after a note is skipped. Fixed both for
that and for the case the brief describes (header printed again). `structure.BodyReader` is now the single reader of a table body
for the scan AND the import stream: a one-cell line is a page break, not the end, when records follow it; the header again is a
header (never a record, never "another table") but only straight after a record or a page break - after a title or a blank line it
still starts another table and the `TABLE` question (`L48`, `B21`, `C54`, `L70`, `LO10` guard that). Also fixed, same module:
a record whose channel is `Booking.com` / `Walk-in` looked like the header of a second table and cut the table (`B57`, `B58`, a
benchmark P0 that the brief did not list).

**`C42_near_identical_net_headers` and `CO04_vat_register_two_rates_two_dates` - the net chosen with HIGH.** `Imponibile` /
`Imponibile (rettificato)` and one net per VAT rate are look-alikes (same rule). The fields that are money (`DomainSem.financial`)
are never asked as a yes/no: neither column is taken, no question, level `MANUAL` (the person matches the columns by hand,
seeing all of them) - "Imponibile 22%" is not the net of the document. A sum of the components is not built (it would need a
new import capability). One rate column alone is still read. An optional amount that appears twice is left out and does not stop
the file; more than three look-alike questions also go to the matching screen.

**PII - 12 personal values in 3 documents.** Where they came from:

| Document | Object | Cause |
|---|---|---|
| `L56` | `columns[].examples` | `Addetto` is no header NINFA knows; the shape rule needed every name to be different, but a roster repeats each person every day |
| `L62` | `columns[].examples` and `questions[].labels` | headers swapped: a column of names was mapped as `role` and its values listed as "department words" to classify |
| `C49` | `columns[].examples` | a cost register does not lock personal columns (a supplier is a business), and examples were hidden only for locked columns |

Fixes: a column of "Name Surname" / "Surname Name" with a given name is a column of people even when the same person comes
back (a lexicon of common given names; room types, rate plans and departments are not); `ColumnProposal.pii` is recorded for
every personal column, locked or not, and its examples are never shown; and the **redaction boundary**.

**PII redaction boundary.** `PersonalDataGuard` (`document_understanding/redaction.py`) reads every text an answer would show - example
values, department words, question labels and table titles, the title, the names of the sheets - and replaces e-mail addresses,
international / mobile telephone numbers, tax codes, IBANs (by the length of their country) and the names / numbers of the personal
columns of the file itself. It runs at the end of `UnderstandingService.understand`, in the plain matching-screen inspection
(`SmartImportService.inspect` - which also showed the names of its own locked columns: a leak the benchmark does not measure) and again
in the route (`_inspection_response`), so it does not depend on the page. Headers, field names, question ids, codes and the decision are
never touched: the import matches the file by them.

## P1 - closed

| Brief item | Fix |
|---|---|
| Domain accuracy >= 98% (97.5%) | `Rep.`, `Res #`, `Bkd`, `Dep`, `Src`, `Start date` / `End date`, `Earnings`: the kind of data is scored from the combination of the columns it can supply (not from a single token); columns in competition still count as evidence. 98.7% |
| `BO01`, `BO03` required fields | `Cod.`, `Can.`, `Imp.`, `Ref.`, `Res #` (`#` is "number"), `Bkd`, `Dep`, `Src`, `Imp. cam.`: found, and asked about where only fairly sure (`Cod.`, `Can.`, a bare `Imp.`/`Tot`) |
| `BO07` weekday dates | `Lun 26/10/2026`, `Martedi 27/10/2026`, `Fri 23/10/2026` are dates for the understanding AND the three importers (`ingestion/value_text.py`); the weekday must be the date's weekday |
| `C02` | `Amount excl. VAT` is the net; nobody is asked `AMOUNT_BASIS` |
| `C05` | `Item` is the line description |
| `C07`, `C47` document number | a lone `Numero`, `Num.`, `N.`, `Doc.`, `Fatt. n.` in a register - not when the values are a row counter 1, 2, 3... |
| `C45`, `C46` | `Intestatario` is the supplier (its examples stay hidden, they may be people); `Da chi`, `Cosa` are confirmed with a question |
| `CO09` amounts with a currency | `1.250,00 EUR`, `850 EUR`, `EUR 850`, `850 euro`, `850 €` are amounts for the understanding AND the importers; `$`, `USD`, `GBP` are NOT read as euros |
| `C40` two-level header | a single group (`Importi`) over a merged block of some of the columns is a two-level header; a title merged over the whole table is still a title |
| `C43`, `CO03` junk | `Centro di costo` is never a category of spend (`FieldSem.veto`) and stays out |

## Benchmark methodology correction - `B25_ota_channels_with_commission_columns`

**Cause.** The scorer identified a column by a header normalised without punctuation (`match.norm` keeps `[0-9a-z&]` only), so
`Commissione %` (the rate) and `Commissione` (the amount) were the same string to it. The truth names both as "Commissione,
first occurrence" and the scorer could not tell the two columns apart: it accepted whichever came first.

| | `commission_rate` | `commission_amount` |
|---|---|---|
| Truth | `Commissione %` | `Commissione` |
| NINFA before hardening (`main`) | not found | the `Commissione %` column (a percentage read as an amount) |
| First evaluator, `main` | missed (P2) | "correct" - by accident |
| Corrected evaluator, `main` | missed (P2) | **`FIELD_WRONG`, P0** - what NINFA really did |
| NINFA after hardening | `Commissione %` | the second column, which NINFA calls `Commissione (2)` |
| First evaluator, hardening | correct | `FIELD_WRONG` (the right reading looked wrong) |
| Corrected evaluator, hardening | correct | **correct** - no finding, `READY`, fully correct |

**Correction (evaluator only).** `match.header_key` is the identity of a column: like `norm` (case, accents, punctuation, spacing and
invisible characters are ignored) but `%`, `#` and the currency signs are part of what a column is. `header_matches` and the
occurrence count use it; `norm` stays lossy for words and values (department words, labels). The system's own renaming of a
repeated header (`Commissione (2)`) is still read through. The truth, the manifest, the corpus (hash `6262d3b06dfe9db6...`) and the
values were not touched, and neither was production code: re-scoring the same observations changes ONE document in each run
(`B25`) - checked document by document against the first evaluator. The corpus scan found no other pair of headers that differ only by
a dropped symbol. Self-tests: `test_smart_import_benchmark.py` (header matching with `%` and `#`, and B25's two columns).

## Remaining

**P1 (5 documents, not in the brief):** `LO13` hours written with a unit (`8 h`, `7,5 ore`); `B34` dates with a month name; `B41`
a lone `Total`; `B50` arrival after departure on every row (headers contradict the values); `L57` `Prev.` / `Eff.` in a two-sheet file.

**P2 (the next gate, "Question Reduction"):** 115 unnecessary questions in 94 documents - `COLUMN_MEANING` on `Canale` / `Channel` (46: the
channel is fairly sure, never certain), a `DOMAIN` question on files that name no kind of data (9), the category `Colazioni` (9),
`DEPARTMENT_ROWS` (4), department words and abbreviations (`Ristorante`, `Ricevimento`, `HK`...). A look-alike pair is asked column by
column ("is X the planned hours?"); a single question that lists the candidates would need a new question in the page.
Nothing here was optimised on purpose; the P2 questions that went away (2) went away as a consequence of a P0 / P1 fix.

## Behaviour changed on purpose

* The importers accept the hotel's own currency next to an amount (`EUR`, `euro`, `€`) and a weekday in front of a date. The Gate 2
  test `test_text_that_does_not_fit_the_configured_format_is_invalid` said "currency symbols are not accepted" for `€ 100,00` and
  `100 EUR`: those two cases moved to the valid ones; `$ 100,00` and `100 USD` are now the invalid ones.
* A header with a standing `%` is a percentage (`Commissione %`), and no longer matches the name of an amount.

## Regression tests

`tests/test_smart_import_hardening.py` (53: every P0 and P1 above, with the neighbours that must not change),
`tests/test_smart_import_hardening_import.py` (7, through the routes, the dry run and the importers: 15 weekday-dated bookings, a printed
list of 24 imported whole, EUR amounts stored as amounts, no name in the browser answer - understanding and plain inspection),
`tests/test_personal_data_guard.py` (45: the gate by itself and the two text readings), `tests/test_importers_value_text.py` (29: bookings,
labor and invoices read weekday dates and currency amounts the same way and refuse the same things). Support: `tests/hardening_support.py`.
The benchmark's own self-tests (`tests/test_smart_import_benchmark.py`) still pass on the unchanged corpus.

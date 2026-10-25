# Smart Import V3 - deterministic hardening 2

Branch `fix/smart-import-v3-hardening-2`, started from `main` = `d64d30b` (hardening 1 merged). It closes the five P1 documents
that hardening 1 left open, and nothing else: no question reduction, no migration, no assistant
(`IMPORT_UNDERSTANDING_PROVIDER=unconfigured`, nothing leaves the process). The benchmark is the one on `main`: 240 synthetic
documents, the same corpus (sha256 `6262d3b06dfe9db6...`), the same truth, the same corrected evaluator - none of them was touched.

The "Hardening 1" column below is a fresh run of `main` (it reproduces `smart-import-v3-benchmark-v1-hardening-1-corrected.json`
document by document), so both columns come from the same machine, the same evaluator and the same day. Result file:
`services/api/tests/benchmarks/results/smart-import-v3-benchmark-v1-hardening-2.json` (the earlier result files are kept).

## Result

| Metric | Hardening 1 | Hardening 2 |
|---|---|---|
| False automation | 0.0% (0/240) | **0.0% (0/240)** |
| P0 findings / documents | 0 / 0 | **0 / 0** |
| P1 findings / documents | 10 / 5 | **0 / 0** |
| Zero-question correctness | 98.9% (88/89) | 98.9% (90/91) |
| Zero-question documents | 89 | 91 |
| Personal columns left out | 100% (108/108) | 100% (108/108) |
| Personal values in the browser answer | 0 | **0** |
| Personal values in what a model would be shown | 0 | **0** |
| Domain accuracy | 98.7% (235/238) | 98.7% (235/238) |
| Header accuracy | 100% (235/235) | 100% (235/235) |
| Table boundary accuracy | 100% (235/235) | 100% (235/235) |
| Required-field precision | 99.6% (1011/1015) | 99.6% (1019/1023) |
| Required-field recall | 98.9% (1011/1022) | **99.7% (1019/1022)** |
| Safe fallback | 100% (58/58) | 100% (58/58) |
| Safe fallback, strict | 100% (29/29) | 100% (29/29) |
| Wrong-card probe | 182/182 asked, 0 automatic | 182/182 asked, 0 automatic |
| Unnecessary questions | 115 of 147 | 119 of 151 |
| Time per document, mean / p50 / p95 / max (ms) | 121 / 102 / 165 / 1709 | 125 / 101 / 169 / 1710 |

Six documents changed, no more: the five of this gate and `B55`, the twin of `B50`. The nine documents that carry the P0
guarantees of hardening 1 (`L07`, `L25`, `L56`, `L62`, `B25`, `B43`, `C42`, `C49`, `CO04`) are identical to the letter: same level,
same mapping, same questions, same findings.

The four extra questions: two are the question this gate was asked to add (`DATES_REVERSED`, on `B50` and `B55`), one is the
deliberate confirmation of a lone `Total` (`B41`), one is the `Canale` confirmation of `B34` - a file that used to stop in the
matching screen and now gets as far as the question that every bookings file gets (a question-reduction matter, left alone).

## The five files

**`LO13` - hours written with their unit.** *Cause:* `6 h` and `5 ore` are text; `fit_hours` saw no numbers, so both hours columns were
dropped and the file ended in `MANUAL` with the hours "missing". *Fix:* `ingestion/value_text.py` reads a number followed by a unit
(`h`, `hr`, `hrs`, `hour(s)`, `ora`, `ore`) and nothing else; the understanding counts such a value as a number *of hours*
(`ColumnStats.hours_unit`: a column of them is never an amount, a percentage or a count) and the labor importer strips the unit
for the two hours fields only (`_decimal(..., hours=True)`) - a cost column still refuses `120 h`. *Not hours:* `8:30`, `08:00-16:00`,
`mezza giornata`, `turno completo`, `8 h 30`, a rate (`14 €/h`, `14 eur/h`). *Result:* `READY`, every hour imported (checked through the
real dry run and import: 12 rows, 480 / 450 minutes).

**`B34` - dates with the month as a name.** *Cause:* `01-Nov-2026` is neither ISO nor `d/m/Y`: not a date, so booked-at, arrival and
departure were missing. *Fix:* a date made of a day, a month NAME (Italian or English, full or abbreviated: `ottobre`, `ott`, `October`,
`Oct`, `sett`, `sept`) and a four-digit year (spaces, `-`, `.`, `/` or `,` between them; an optional time; an optional weekday in front)
is read by the understanding and by the three importers without a pattern - there is nothing to tell day from month. A year that is
missing (`26 ottobre`), a two-digit year (`26 ott 26`), an unknown month or a day that does not exist (`31 febbraio 2026`) is NOT a date
and is never completed. *Result:* the three dates are found; the file asks only the `Canale` confirmation that every bookings file asks
(`ASK`; before: `MANUAL`); 15 bookings imported with the right dates.

**`B41` - a lone `Total`.** *Cause:* the bare `Total` was read as the stay's total revenue, and the importer needs the room revenue.
*Rule:* `understanding_bookings.lone_total_is_room_revenue`. A bare `Total`/`Totale`/`Tot` becomes the room revenue - *proposed at MEDIUM, one
confirmation, never decided* - only if (1) the file is a list of reservations (booking id, booked-at, arrival and departure are all
recognised), (2) no room revenue has been found, and (3) no other column holds money: no recognised amount field, no amount that does not
say which, no look-alike pair, no unplaced column of non-integer values or values above 100, no header with a money word (tax, extras,
fee, commission, deposit, price...). *Protected:* `Room total` + `Total` (the room total is the room revenue, the total is the total),
`Total` + `Extras` / `Tax` / `City tax` / `Commissione` / `Supplementi` / `Net` + `VAT`, a table that is not a reservation list, and the
cost register's `Total` (still the gross amount). *Why not automatic:* whether a bare total includes extras and taxes is written nowhere;
the truth of the benchmark says `READY`, the rule prefers one question to a silent assumption about money. Answering "yes" makes it `READY`.

**`B50` - arrival after departure.** *Cause:* the headers are right, the values contradict them, and nothing compared the two columns.
*Validation:* `understanding_bookings.check_stay` compares arrival and departure on the first 400 rows (real dates, ISO, `d/m/Y` or
month-first text, month names; a text that reads two ways counts as reversed only if it is reversed both ways). When the arrival is
after the departure on at least 80% of at least three comparable rows - one wrong row, or a one-day stay, is not that - neither column is
trusted (both go to MEDIUM, so the import is never automatic), nothing is swapped, and the person is asked. *UX:* a new question,
`DATES_REVERSED`, shown first: «Le colonne «Arrivo» e «Partenza» sembrano invertite. Vuoi controllarle?» with the line "In quasi tutte le
righe la data di arrivo viene dopo quella di partenza. NINFA non le scambia da sola e non importa il file così com'è." and one button,
"Controlla le colonne", which opens the matching screen (the "back" button of every question still lets the person choose another file). The
existing question model could not say this, so the contracts, the copy and the question component got one case each (+1 Vitest). If the
person goes on anyway the importer refuses every row (checked: `can_import` false, nothing written).

**`L57` - `Prev.` / `Eff.` over two sheets.** *Cause (the brief asked not to assume it):* not the sheets - the two sheets that share
their columns were already ONE table of 32 rows with the department taken from the sheet name. The only gap was the two headers: neither
has a word for hours, so no rule matched. *Fix:* `Prev.` and `Eff.` are loose names (MEDIUM alone) and, as a pair, both over columns of
hours (numbers, none above 168), the plan and the time worked (`DomainSem.pairs`, the mechanism that already makes `Dal` / `Al` an
arrival and a departure). A lone `Prev.` is only a maybe (one confirmation); over text (`si` / `no`), over amounts (1500), or in a bookings file it
is nothing. *Result:* `READY`; both sheets imported as one table (18 rows in the test, the department is the sheet). Two sheets that are
NOT the same table are still not merged - the existing `TABLE` rule decides - so no new multi-sheet capability was needed.

## Behaviour changed on purpose

* The Gate 2 test `test_impossible_or_unrecognised_dates_are_invalid` said `10 luglio 2026` is invalid ("month names are locale
  dependent"). A month name with its four-digit year is now a date; the test's invalid examples became the ones that stay invalid
  (`10 luglio`, `10 lug 26`, `31 febbraio 2026`) and a new test reads `10 luglio 2026`, `10 lug 2026`, `10 July 2026`, `10-Jul-2026`. The
  date PATTERNS stay numeric-only (`validate_date_pattern` is untouched).
* `DATES_REVERSED` is a new question kind (frontend: contracts type, one copy entry, one case in the question component).

## Remaining

**P1:** none in the benchmark.

**P2 (the next gate, question reduction - nothing was optimised):** 119 unnecessary questions in 96 documents - `Canale` / `Channel` confirmations
(47), `DOMAIN` on files that name no kind of data (9), the category `Colazioni` (9), `DEPARTMENT_ROWS` (4), `Provenienza` / `Codice`
(4), department words and abbreviations (`Ristorante`, `Ricevimento`, `HK`...), and the two `DATES_REVERSED` of this gate, which are not a defect.

**Limits worth knowing:** hours are read only with these units (a unit in another language, `8 hs`, is text); a date with the month first
(`October 26, 2026`) is not read; a lone total in a reservation file is asked about, never decided; the reversed-stay check needs three comparable
rows and 80% of them, and a file written with a date order that cannot be told (`03/04`) is judged only when it is reversed both ways.

## Tests

`test_smart_import_hardening_2.py` (48: each of the five files with its neighbours that must NOT be read), `test_smart_import_hardening_2_import.py` (5,
through the routes, the dry run and the importers: 12 hours with units, 15 bookings with month-name dates, two sheets of `Prev.` / `Eff.` as
one table, a lone `Total` confirmed and imported, a reversed file refused by the importer too), `test_importers_value_text.py` (+32: the three
importers read month-name dates the same way and refuse the same things; hours with a unit in the labor hours fields only), the Gate 2 date
test, and one Vitest (`DATES_REVERSED`). Backend full suite, ruff, format, mypy strict, frontend eslint / tsc / vitest / build: see the PR.

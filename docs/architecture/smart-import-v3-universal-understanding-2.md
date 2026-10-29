# Smart Import V3 — Universal Understanding 2 (files nobody has seen)

ADR: `docs/architecture/adr/0036-smart-import-unseen-files.md`. Benchmark: `docs/benchmarks/smart-import-v3-universal-understanding-2.md`
(results) and `services/api/tests/benchmarks/universal_understanding_v2/README.md` (method). AI stays **off**
(`IMPORT_UNDERSTANDING_MODE=off`, provider `unconfigured`); nothing here calls a model, a cloud service or an embedding, and nothing was added
to the dependencies or the database.

## The pipeline (unchanged order) and where this gate acts

```
scan_workbook (cells, merged areas, hidden sheets)
 -> saved layout / learned family            (Source Learning: untouched)
 -> candidate tables -> the table -> the kind of data
 -> propose(): every column against every field
        1. what is never read (personal data, an hourly rate)        <- NOTE, ADDRESS, EMPLOYEE_ID, tax code, IBAN
        2. name candidates: alias / words of a rule / likeness        <- concept families, abbreviations, context words
        3. values check the name: fit, enough values                  <- unique identifier, document number, negatives
        4. each field once, each column once; contests; look-alikes
        5. columns that confirm each other                            <- relations.py (arrival before departure)
        5c. a value no person could have                              <- person limits (hours above a day)
 -> checks of the kind of data (amounts, dates reversed, formats) -> questions -> level READY / ASK / MANUAL / BLOCKED
```

## What was added

| Piece | Where | What it does | Counter-example |
|---|---|---|---|
| Concept-family words | `semantics_bookings/labor/costs.py` | the words other exporters use for arrival/departure, rooms, room revenue, reference, channel; planned/actual hours, department, work date; supplier, document number/date, description, net/gross/tax, category, due date | the same words over values that cannot be it (`Stanze` over names, `Clocked Hrs` over 400..610, `Ditta` over amounts) |
| Written abbreviations | `semantics.expand_abbreviations` | `Descr.` -> descrizione, `Aliq.` -> aliquota; only with the point, only when every word it could stand for speaks of one field | `Imp.` (imponibile / imposta / importo) is not expanded; `Descr` without a point is a word of its own |
| `U.O.`, `Q.tà` | `text._words` | punctuation that cut an abbreviation in two puts it back | |
| Context words | `DomainSem.context` | `Prenotazione` over a column of a bookings file names the document, not an incidental extra word | |
| Relations | `relations.py`, `proposal` step 5b | a departure later than its arrival on >= 95 % of >= 3 rows promotes `CI`/`CO` (or any names that already stand) MEDIUM -> HIGH. Never creates a reading, never overrules a name | reversed or unrelated dates stay a question; a lone `CI` is never certain |
| Person limits | `DomainSem.person_limits`, step 5c | hours above 24 on a row that names the person -> LOW (asked) | the same hours without a person column (a department's sum) are not questioned |
| Unique identifier | `semantics.fit_unique_identifier` | a booking code differs on every row; a code that repeats is a candidate to be asked about, never sure | an invoice number may repeat (the lines of one invoice) |
| Document number | `semantics_costs._fit_document_number` | short, with digits, several different ones; not a row counter | words, a counter, a constant |
| Register net | `understanding_costs._register_net` | `Netto fattura` is the net of the line when every row is an invoice, or when the lines of an invoice have a net each | the same net on every line of an invoice is the invoice's: nothing is decided |
| Credit notes | `semantics_costs._fit_amount` | negative amounts fit in a register of costs | negative money in bookings is still suspect |
| Personal data | `pii.py` | `NOTE` (guest requests, remarks, allergies), `ADDRESS`, `EMPLOYEE_ID` (badge, matricola); tax code and IBAN left out of a cost register | `Nota di credito`, a note column of numbers, `Numero ospiti` |
| Payslip | `semantics_costs._PAYROLL` | `Netto in busta` is never an amount of a cost register | |
| Dates | `ingestion.value_text`, `bookings.normalization`, `column_profile`, `invoices.mapping` | a month name in either word order and a two-digit year (`Nov 4, 2026`, `06-apr-26`); `04/02/26` needs the same decision as `04/02/2026` and reads with `%y` | `Foo 4, 2026`, `Nov 32, 2026`, `Nov 4, 26` |
| Stated department | `titles.department_words` | `Reparto: Spa` is the department of the rows; `Responsabile: Direzione` in the same block is not | the same words without the label are as many departments as words |
| Internal evidence | `ColumnProposal.evidence` | why a column is read as it is: name kind and score, share of fitting values, abbreviation, relation, plausibility. Never a value of the file; never sent to the browser | |

## Supported files (what is *truly* supported)

| | Supported | Not supported (cleanly refused) |
|---|---|---|
| Formats | `.csv`, `.xlsx` | PDF, text, `.xls`, `.xlsm` (macros), HTML saved as `.xls`, images, any other extension |
| CSV delimiter | `;` `,` tab (detected; a closed, tested set) | **pipe `\|`** and anything else: the table is not found, `BLOCKED / NO_TABLE` |
| CSV encoding | UTF-8 (with or without BOM), Windows-1252 | UTF-16 and anything else: refused, no guessing |
| CSV details | quoted fields, a newline inside quotes, an empty column, a trailing delimiter | |
| XLSX | several sheets, merged title cells, blank rows, formulas with cached values, totals, one sheet per month (one table) | macros; **a hidden sheet is never read** (a workbook whose data is only on a hidden sheet is refused) |
| Dates | ISO, `dd/mm/yyyy`, `dd/mm/yy`, `mm/dd/yyyy`, dotted, with weekday, month names (`26 ottobre 2026`, `26-Oct-26`, `Nov 4, 2026`); the order is decided only when the values prove it, else DATE_ORDER is asked | a date in a language other than Italian or English |
| Amounts | `1.234,56`, `1,234.56`, `1234,56`, `€ 1.234`, `EUR 1234.50`, `1 234,50`; the style is decided when the values prove it, else DECIMAL_STYLE is asked | |

## What this does not do

* **No full value-profile taxonomy.** The classes of the task (DATE, MONEY, PERCENT, BOOLEAN, COUNTRY-LIKE, DEPARTMENT-LIKE, STATUS-LIKE...) exist
  where earlier gates already used them as vocabulary checks (channel vs country, department, status, category); this gate added the identifier
  and document-number shapes, negatives, plausibility per person and the date forms. A general per-column profile (null ratio, dominant pattern,
  outliers) was **not** built.
* **No generic domain graph / table classifier rewrite.** Decoy tables, KPI boxes and summaries were measured (header and table detection are 100 %
  on V2) and needed no change; contradictions between the header and the values of a document are handled by the existing DOMAIN question and by the
  level, not by a new graph.
* **Relations are two**: arrival/departure for bookings and the person limit for staff. Net + VAT = gross already existed (`amounts_check`); nights
  versus the date difference, gross >= net, commission <= gross were not added.
* **Unreadable header position** (a multi-row header with an unrelated group over a leaf) is handled by the existing two-level join; the leaf-first
  reading was not built, because a rule that lets the most specific field win (`rooms` .90 over `room revenue` .88) settled the measured cases.
* **A pipe-delimited file is refused**, on purpose (see the ADR).
* **The choice between two tables is not a fact a family remembers**: a second upload of such a file is asked again (as before this gate; shown by the
  secondary learning test, which therefore leaves those documents out).
* The corpus was written by the same person who improved the engine (see the benchmark README).

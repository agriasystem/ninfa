# NINFA — Smart Import V3 (Struttura > Fonti dati: "NINFA understands the document")

V2 let a hotel match the columns of the file it already has. That still asks too much: the real files are not tables with
a header on row 1. They have a title, a summary block, a header on row 8, a `TOTALE` row, a note, a department written on a
line of its own, one sheet per department, a grid of people x days, "Reparto o mansione" where V2 only knew "Reparto" - and
the person ended up answering "Reparto di tutte le righe" about a file that has a department column.

**Smart Import V3** reads the whole DOCUMENT first (every sheet, titles, totals, sections, grids), says what it understood
and asks ONLY what is really ambiguous. Almost always the person sees a summary and one button.

**No migration. No new dependency. No employee identity. Nothing of Decision Engine, Mia, scoring, Home, auth or connectors
is touched.** The AI part exists as a boundary and is OFF by default; everything works without it.

```
file -> every sheet scanned (bounded) -> the table found (title, summary, totals, notes, sections left out, reported)
     -> what KIND of data it is -> where the department of each row comes from
     -> what each column MEANS (its words, checked against its values) -> a decision (a V2 `MappingInput` + `layout`)
     -> what is STILL unclear: single questions - or nothing
     -> the whole file is tried (nothing written) -> import -> the way of reading is remembered
```

## Layers

| Layer | Package / module | Role |
| --- | --- | --- |
| Document understanding | `document_understanding/` | pure, no database: scan (`grid`), header and table by evidence (`structure`), two-level headers, totals check, sections, notes, several tables, sheets that are one table (`document`), day grids (`days`), titles (`titles`), the virtual table the importers read (`apply`), `LayoutSpec` (`layout`) |
| Values and personal data | `document_understanding/stats`, `pii` | what the values of a column look like; which personal data a column carries (header AND values) |
| Words and certainty | `data_sources/semantics*`, `proposal` | token rules per field, value fit, HIGH / MEDIUM / LOW |
| Kind of data | `data_sources/domain_detection` | bookings / staff / costs, scored from what the document says and has |
| Questions and blockers | `data_sources/understanding*` | `UnderstandingService`, the closed vocabulary of questions, blockers and origins |
| Import (unchanged engines) | `bookings`, `labor`, `invoices` services | the same readers, validation, all-or-nothing import, `*_mapping_profiles` |
| Optional AI | `ai/import_understanding/` + `understanding_ai` | OFF by default; a suggester of last resort |

## Document understanding

- **Bounded scan.** First 400 and last 60 rows of every sheet (streaming for big workbooks, merged cells on small ones),
  hidden and empty sheets recognised. Formulas are never evaluated; a cell is DATA whatever it says.
- **The header is found by evidence**, not "the first non-blank row": label rows with data under them, a vocabulary ratio, and
  a data row with three dates is NOT the header of a grid of days (day columns must be consecutive days and most of the row).
  A header on two levels ("Personale" over "Ore previste") is joined ("Personale - Ore previste"); a repeated header is renamed
  ("Ore", "Ore (2)") instead of failing with `DUPLICATE_HEADER`.
- **What is not a record** - `TOTALE`/`Tot.`/`Subtotale`, notes, department lines, the footer - is left out AND reported
  (count and kind). When the file states totals, they are checked against the rows: `MATCH` raises the confidence, `MISMATCH`
  is shown as a warning and never imported.
- **Several tables on a sheet, or on several sheets**: comparable tables of the kind being imported become a `TABLE` question;
  sheets with the same columns are ONE table (one sheet per department); a summary sheet is not data.
- **A table the chosen one leaves out is asked about, however clear the winner** (found by the AI readiness benchmark: three
  readable department sheets and a fourth with an unreadable header were offered as READY with 27 records of 36). The ranking
  picks the best table; it cannot prove the others irrelevant. When another table sits on a sheet that holds data (not hidden,
  not empty, not called a summary - a sheet only *demoted* for being small counts), has at least 4 records and fits the kind of
  data chosen at least half as well, the file is `ASK` with the `TABLE` question, whose choices show the records of each (27 and
  9); the person's answer is the decision. A legend, an example of two rows, a dashboard, a hidden draft, a supplier directory
  in a costs file or an empty sheet never counts. No sheets are merged and no new capability is added.
- **`LayoutSpec`** is the small, repeatable part of the reading (department source, grid hours, sheets, table key). It travels
  with the decision and, minus the week and the table key of THIS file, is saved in `format_options.layout`. Its presence is what
  makes the next file be read the same way.

## What a column means

- Headers are read as **words** ("Reparto o mansione", "Reparto/Mansione", "Area / reparto", "Tot. ore previste", "Costo
  programmato", "Check-in date", "Dal"/"Al", "Provenienza prenotazione", "Canale vendita", "N. pren.", "Arr.", "Part.").
  A rule says "a word for hours AND a word for planned". A regression pins the real bug: the UI's own label
  "Reparto o mansione" is a column of departments, read row by row, and "Reparto di tutte le righe" is never asked.
- A name is **checked against the values** (a "Data" over names is not a date). HIGH needs a known name or rule AND values that
  fit, at least three of them; a loose rule, a lone "Dal"/"Codice", or fewer than three values is MEDIUM - and one
  confirmation question.
- **Personal data first.** Names, e-mail, telephone numbers (in their real formats, never a date or an amount), tax codes and
  IBANs are classified by header AND by shape before any guess about meaning; hourly rates are never read, whatever words they
  use ("Costo orario previsto"). Their examples are not shown on screen. People are counted in memory ("13 persone") and kept
  nowhere. "Ospiti" over small numbers is a count of guests, not a guest.

## Kind of data

Scored from the words of the title and sheet names and, above all, from how much of what that kind of import REQUIRES the
columns can supply. HIGH / MEDIUM / LOW is never a percentage on screen. The person's own card is a WEAK PRIOR, not a
confirmation: a verdict that agrees asks nothing; one that differs ("Questo sembra un file dei costi. Corretto?") is asked
about - alone, because everything else depends on the answer - and a file of another kind is never imported through this card.
A file that points NOWHERE is not asked "what is this?" (no answer would change anything): the card is not evidence, so it is
never `READY`, and it ends in the matching screen with what it lacks.

## Staff (Personale)

Where the department of a row comes from, in this order: a column -> a line above the rows ("RECEPTION") -> the name of the
sheet -> the title ("TURNI HOUSEKEEPING", always CONFIRMED by the person) -> ONE question. A word NINFA does not know ("HK",
"Turno A") is never guessed: one question lists the words with how often they appear, and the answer is remembered in the
source's `role_mapping`. A grid of people x days becomes one row per person per day, only when its days are real dates (in the
header, or the week stated in the title or by the person - any day of the week names it); the cells must be hours. A **weekly
summary with no days** is refused ("Questo file contiene un riepilogo settimanale. Per le analisi del personale NINFA ha
bisogno del dettaglio giorno per giorno."): hours are never spread over days. A file with costs but no currency uses the
hotel's own currency, said on screen.

## Bookings

Same engine and the same questions; Italian, English and abbreviated headers. A guest name, e-mail or telephone is never
imported, stored or sent back. A required field that really is not there ("data di partenza") is named.

## Costs

A cost REGISTER in CSV / Excel is read through the SAME invoice model the FatturaPA XML fills (suppliers, documents, lines,
cost categories, classification): `CostsDomain` adapter, `InvoiceImportService.dry_run` and `mapping_override`, a schema
version on the invoice mapping. FatturaPA XML keeps its own path. NINFA's analysis works with the **net** amount:

1. "Imponibile" / "Netto" say it; or
2. net + VAT = total on the rows of the file confirms it (`document.amounts = MATCH`); otherwise
3. ONE question ("L'importo è al netto di IVA?"); "no" is a plain blocker (`AMOUNT_NOT_NET`) - the net amount of a line is not
   NINFA's to work out.

Category words are NINFA's own lexicon (Utenze, Lavanderia, Consulenze...) plus what the hotel taught (`category_mapping`).

## Questions, blockers, levels

`READY` (summary + "Importa dati") / `ASK` (single questions) / `MANUAL` (the V2 matching screen, with the proposal) /
`BLOCKED` (the file says why).

| Question | When | Answer |
| --- | --- | --- |
| `DOMAIN` | the file is clearly another kind than the card (asked alone) | a kind (the same as the card, or guidance to the right card) |
| `TABLE` | two comparable tables | the table |
| `DEPARTMENT_ROWS` / `DEPARTMENT_CONFIRM` | no department anywhere / only in the title | a department |
| `VALUE_LABELS` | words NINFA does not know (department, category, status) | one meaning per word, one word per screen |
| `COLUMN_MEANING` | hours or an amount that does not say which, or a column only fairly sure | the field / yes |
| `GRID_HOURS`, `PERIOD` | a grid: planned or actual; which week | the choice / a date |
| `AMOUNT_BASIS` | an amount that does not say whether VAT is in it | net / gross |
| `DATE_ORDER`, `DECIMAL_STYLE` | `03/10/2026`, `1,234`: the values cannot prove it | the choice |
| `DATES_REVERSED` | the arrival is after the departure on (nearly) every row | "Controlla le colonne" (the matching screen); nothing is swapped |

Blockers: `NO_TABLE`, `MISSING_REQUIRED`, `PERIOD_SUMMARY_ONLY`, `GRID_NOT_SUPPORTED`, `GRID_NOT_HOURS`, `AMOUNT_NOT_NET`,
`MIXED_FORMATS`. What the person says is never asked again (`answers`).

## API

`POST /api/v1/properties/{property_id}/data-sources/import-understanding` (JSON: `domain`, `filename`, `file_base64`,
`confirmed_domain`, `answers`) - writes NOTHING. Returns the V2 inspection plus `understanding` (level, detection, document
summary, what was recognised with its origin, people, questions, blockers) and `proposal` (the `MappingInput` to validate and
import, with its `layout` and `labels`). `import-validation` gained `summary` (what the valid rows add up to) and `questions`;
`MappingInput` gained `layout` and `labels`; `period_start` is per file and never saved.

## Learning

One profile per source (no new table). It remembers the columns, the formats, the `layout` (without the week and the table
key) and the words the person taught (`role_mapping`, `status_mapping`, `category_mapping`). It never holds a value, a title, a
name or a date of a file. What one hotel taught is not known by another.

## The optional AI

Smart Import works fully without it; `IMPORT_UNDERSTANDING_PROVIDER` defaults to `unconfigured` (an API key existing is never
enough) and a failure never blocks the import. The boundary:

- **Port** `ImportUnderstandingProvider` (one seam, like the Ask NINFA provider); the vendor adapter lives in the one file
  allowed to import `anthropic`. First call with the smaller model, the repeat - only after an answer that broke the rules -
  with the larger; **at most two calls per file, never per row**; bounded time, no retries, no prompt logging.
- **Evidence** (what is shown): no file name; a personal-data column is only its CLASS (`PII_PERSON_NAME`, `PII_EMAIL`,
  `PII_PHONE`, `PII_TAX_CODE`, `PII_IBAN`, `PII_HOURLY_RATE`), never a value; sheet names and the title are reduced to the words
  NINFA's own vocabulary knows; headers and a few words of low-cardinality columns are cleaned (length, control characters,
  anything shaped like personal data).
- **Output** is closed: a kind of data, a field per column index with LOW or MEDIUM confidence, a choice among the questions
  offered. No text, no number, no date - it cannot carry a business value.
- **Checked, never believed**: a structural breach (unknown field or domain, HIGH, a personal-data column, a field used twice) is
  INVALID; a field the VALUES do not fit is dropped. What survives is a SUGGESTION at MEDIUM: "suggerito da NINFA, da
  controllare", confirmed by the person. A sentence hidden in a cell changes nothing.
- It is asked only when the rules left something open it could help with; a file read completely never reaches it.
- **Evaluation harness** (`data_sources/understanding_eval.py`, `tests/eval_import_understanding.py`): precision, recall, calls
  and unanswered cases of a provider on the synthetic corpus. Verified here with a fake oracle; **not run against a real
  model in this gate**.

## Privacy and safety

No migration, no new column; a file is never stored; names are counted in memory; a column of personal data is never read,
imported, shown or sent to a model; a cell is data (formulas, `=`, `@`, hostile text); the question endpoints write nothing; the
import is all-or-nothing and idempotent as before.

## Deterministic hardening 1

What the Smart Import Intelligence Benchmark V1 found (`docs/benchmarks/smart-import-v3-benchmark-v1.md`, 240 documents,
5 offered as automatic with a wrong or incomplete reading, 3 with personal values in the answer), and how it is now closed.
Nothing here uses the optional assistant, and nothing changes the corpus or its truth.

- **A page break is not the end of the table.** `structure.BodyReader` is the ONE reader of a table body, used both when a sheet
  is scanned and when it is streamed for the import (so the table described is the table read). A one-cell line such as
  `--- pagina successiva ---` ends the table only when no record follows it; the header printed again at the top of a page is
  not a record - but only straight after a record or a page break. A header that comes after a title or a blank line
  (`Settimana 43`, `FATTURE EMESSE`) still starts ANOTHER table (and the `TABLE` question). A row with dates and numbers in the
  places where the record above has them is a record, whatever its channel is called (`Booking.com`, `Walk-in`).
- **Two columns that say the same thing are a choice, not a guess.** When two columns satisfy the same rule of the same field
  (`Ore previste` / `Ore previste (rev.)`, `Imponibile` / `Imponibile (rettificato)`, one net per VAT rate) neither is taken
  (`proposal.CONTESTED`). For a field the import needs: each column is asked about (`COLUMN_MEANING`, "is X the planned hours?");
  for a field that is MONEY (`DomainSem.financial`) nothing is asked as a yes/no and the person matches the columns by hand
  (`MANUAL`, no blocker); more than three questions of this kind also go to the matching screen. A field nobody needs is
  left out. A column and a look-alike that satisfy DIFFERENT rules (`Reparto` / `Mansione`) are not a choice.
- **A column that may be what the import needs is never dropped quietly.** "Hours that do not say which" is asked about even
  when the other hours column is there (`Ore prog.` is now the planned hours; an unknown abbreviation is asked); hours of
  another kind (`Ore da contratto`, straordinario, ferie...) are left alone.
- **The personal-data gate.** Detection by shape no longer needs the people to be all different (a roster lists the same person
  every day): a column of "Name Surname"/"Surname Name" with given names is a column of people, whatever its header. A
  personal column that is not locked (a cost register) is still never shown. `PersonalDataGuard` then reads every text an
  answer would SHOW (examples, department words, title, sheet names, question labels) and replaces e-mail addresses,
  international / mobile telephone numbers, tax codes, IBANs (by their country's length) and the names / numbers of the
  personal columns of THIS file. It runs at the end of `understand()` and again in the route (`_inspection_response`).
  Headers, field names, question ids and the decision are never touched: the import matches the file by them.
- **Words and values of a hotel's own export.** Abbreviations (`Res #`, `Bkd`, `Arr`, `Dep`, `Src`, `Cod.`, `Can.`, `Imp.`,
  `Ref.`, `Rep.`, `Ore prog.`, `Fatt. n.`, `Item`, `Intestatario`...), `#` as "number" and a standing `%` as "percentage",
  a header with `excl. VAT` as the net, `Centro di costo` as NOT a category of spend (`FieldSem.veto`), a lone `Numero` / `Doc.`
  as the document number unless the values are a row counter. A single group over a merged block (`Importi` over three
  columns) is a two-level header; a title merged over the whole table is still a title.
- **Weekday dates and amounts with the currency** (`Lun 26/10/2026`, `1.250,00 EUR`) are read by the understanding AND by the
  three importers (`ingestion/value_text.py`): the weekday must be the date's, another currency is never read as euros, and the
  remainder still has to match the pattern the person confirmed.

## Deterministic hardening 2

The five valid files that hardening 1 left in the matching screen (`docs/benchmarks/smart-import-v3-hardening-2.md`). Deterministic,
no assistant, and none of the prudence of hardening 1 given up (the documents that carry its guarantees are byte-identical in the benchmark).

- **Value readings shared by the understanding and the importers** (`ingestion/value_text.py`): a month written as a NAME with a four-digit
  year (`26 ottobre 2026`, `26-Oct-2026`; no year, a short year or a day that does not exist is not a date) and hours with their unit (`8 h`,
  `7,5 ore`, `6 hrs`; not `8:30`, a range, a rate). The labor importer strips the unit for the two HOURS fields only; the understanding counts
  such values as hours (`ColumnStats.hours_unit`) - a column of them is never money, a percentage or a count.
- **`Prev.` / `Eff.`** are the plan and the time worked when they stand together over columns of hours (`DomainSem.pairs`); alone, a maybe.
- **Bookings, across columns** (`understanding_bookings.py`): a lone `Total` of a list of reservations is PROPOSED as the room revenue (MEDIUM,
  one confirmation) only if nothing else holds money; an arrival after the departure on (nearly) every row asks `DATES_REVERSED` ("the columns
  look swapped - check them"), distrusts both columns and swaps nothing.

## Question reduction 1

Fewer questions, no less prudence (`docs/benchmarks/smart-import-v3-question-reduction-1.md`). The rule: **SAFE + PROVEN -> silent;
AMBIGUOUS + BUSINESS-CRITICAL -> ask; UNSUPPORTED -> manual / blocked.** A question is asked only if the answer can change the mapping, the
validation, the safety or the result of the import. No assistant, no migration.

- **Channel = header AND values** (`channel_words.py`): a channel header over values that are, for the most part, the words a hotel uses for how
  a booking arrived (OTAs, the website, phone, e-mail, walk-in, agencies; whole words only) is certain. Over countries it is not a channel at all;
  over words nobody knows it stays a maybe. Codes of a channel manager (`BDC`, `EXP`) count only next to a header that already says "channel". A
  channel the hotel taught (`channel_mapping`) is one more word for the column.
- **The card is a weak prior** (see Kind of data). While the file cannot be imported (a blocker), questions about the MEANING of its columns and words
  are premature and are not asked; they come back when the person has matched what was missing.
- **Departments and categories**: a short list of department words on top of the import's own rules, and more cost-category words, each with ONE
  category. They travel in the decision (`labels`) so the import files them the same way. A word that could be two (`Food & Beverage`, `MAN`) or a
  code only this hotel uses (`HK`) is asked, once, and remembered. Only the unknown words are asked about, never the known ones with them.
- **A loose name over proving values**: `Cod.` / `Codice` over reservation codes that are all different, in a list of reservations whose stay dates are
  all recognised, IS the code. `Totale IVA inclusa` says the amount is gross: it is not asked, it is not imported.
- **Two columns that claim one field** are still a choice - unless all but one of them is, by its own words, the name of another field nobody has taken
  ("Importo camere" and "Totale soggiorno": the room revenue and the total).
- **What stays asked**: a lone `Total`, an amount that does not say what it holds, competing look-alike columns, an arrival after the departure, an
  ambiguous date order, an unknown department or category, several plausible tables, a file that looks like another kind of data.

## Tests

Synthetic corpus (`tests/understanding_support.py`: realistic staff file, title+summary, sheet per department, sections, grids,
two-level and duplicate headers, weekly summary, wrong totals, two tables, bookings in three vocabularies with and without
guests, costs registers, hostile cells, empty file) read through the real API: document structure, semantics and personal data
(pure), staff / bookings / costs flows end to end (understand -> try -> import -> saved profile -> recognised next time), the AI
port with a fake provider (cleaning, evidence, validation, call limits, injection, adapter request shape), and the web flow
(zero-question summary, each question, blockers, fallback).

## Known limits

- A grid with several blocks of days (planned and actual together) is refused, not guessed.
- A register without a description per line is refused: the description is required by the invoice model and is not invented.
- Optional columns the rules cannot read are not asked about (the AI step only runs for what a required field needs).
- Look-alike columns are asked about one by one ("is X the planned hours?"): a single question that lists them all, and a sum
  of the net amounts of a register with one column per VAT rate, are not built.
- A department written as a label and a value in the header block of a sheet ("Reparto: Spa") is not read as the department (one question).
- Hotel codes for departments (`HK`, `FO`) and for booking statuses (`OK`, `CANC`) are the hotel's own: asked once, then remembered.
- Cost registers in several currencies per file follow the invoice model's rules (one currency per document).
- The AI step is built and tested with a fake provider only; its quality on a real model is unmeasured.

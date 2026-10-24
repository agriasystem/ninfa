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
columns can supply. HIGH / MEDIUM / LOW is never a percentage on screen. The person's own card is the confirmation: a verdict
that agrees asks nothing; one that differs ("Questo sembra un file dei costi. Corretto?") or that points nowhere ("Che tipo di
dati contiene questo file?") is asked about - and a file of another kind is never imported through this card.

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
| `DOMAIN` | the file is another kind than the card, or nothing stands out | a kind (the same as the card, or guidance to the right card) |
| `TABLE` | two comparable tables | the table |
| `DEPARTMENT_ROWS` / `DEPARTMENT_CONFIRM` | no department anywhere / only in the title | a department |
| `VALUE_LABELS` | words NINFA does not know (department, category, status) | one meaning per word, one word per screen |
| `COLUMN_MEANING` | hours or an amount that does not say which, or a column only fairly sure | the field / yes |
| `GRID_HOURS`, `PERIOD` | a grid: planned or actual; which week | the choice / a date |
| `AMOUNT_BASIS` | an amount that does not say whether VAT is in it | net / gross |
| `DATE_ORDER`, `DECIMAL_STYLE` | `03/10/2026`, `1,234`: the values cannot prove it | the choice |

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
- Cost registers in several currencies per file follow the invoice model's rules (one currency per document).
- The AI step is built and tested with a fake provider only; its quality on a real model is unmeasured.

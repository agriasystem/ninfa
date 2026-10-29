# 0036 — Files nobody has seen: read by evidence, not by list

## Context

Smart Import V3 reads a column by its **name** (an alias list, the words of a rule, a likeness of letters) and then **checks** the name
against the column's values. ADR 0033-0035 added memory on top (a source that was confirmed once is recognised). None of that helps the
first file of a hotel whose exporter calls the arrival "Data ingresso", the room count "Stanze" or the net of an invoice "Netto fattura".

The Universal Understanding Benchmark V2 measures exactly that: 402 documents generated from recipes (none is in the official 240), each
read as a **first upload**, with the truth written next to the file and never taken from the engine (`docs/benchmarks/smart-import-v3-universal-understanding-2.md`).
On the engine of ADR 0035 it gave, over the 360 documents that can be imported:

| | before |
|---|---|
| required recall | 82.4 % |
| zero-question rate of the documents that are clear | 22.6 % |
| false automation | 4 documents (all staff) |
| P0 findings | 10 |
| personal values shown to the browser | 13 values in 5 documents |
| unnecessary questions | 139 |

The failures were not random. They had four causes, in this order of weight:

1. **Vocabulary** - the words of other exporters (arrival/departure, rooms, room revenue, reference, channel; planned/actual hours,
   department; supplier, document number, description, net/gross) and their abbreviations ("Descr.", "CI", "Rms", "U.O.").
2. **Evidence the engine did not use** - a column of dates called "CI" next to a column of dates called "CO" that is later than it on
   every row *is* an arrival and a departure; 48 hours on a row that names the person cannot be hours worked.
3. **Formats** - a month name first ("Nov 4, 2026") was not a date, and a numeric date over a two-digit year ("04/02/26") was a date for
   the structure but invisible to the order check (a latent defect, exposed as soon as the headers around it were read: such a document was
   offered as ready without the day/month question).
4. **Personal data nobody was looking for** - free text about a guest ("Special Requests"), an address, an employee badge.

## Decision

The principle is the one of the task: **document evidence > historical memory > generic vocabulary**; the engine computes and
interprets, the person confirms only what the document does not prove. Deterministic, no model, no new dependency, no migration.

1. **Concept families, not alias lists.** Rules are written for a concept (arrival, room revenue...) with the words and the
   abbreviations hotels use for it; each rule has a counter-example in `tests/test_universal_understanding_headers.py` (the same words
   over values that cannot be it, a look-alike concept).
2. **A written abbreviation is read as the word it cuts** ("Descr." -> descrizione, "Aliq." -> aliquota) only when the point is there
   and **every** word it could stand for speaks of **one** field. "Imp." could be imponibile, imposta or importo: it is not expanded.
3. **Relations promote, never create.** `relations.py`: a reading that already stands on a name and on fitting values is promoted
   from MEDIUM to HIGH when the values of two columns confirm each other (departure after arrival on at least 95 % of the rows, three
   rows at least, stay of at most 90 days). Not holding is not an error: the name stays what it was. A lone "CI" is never certain.
4. **Plausibility is a question.** Hours above a day on a row that names a person (the column is left out as personal data) demote the
   reading to LOW: it is asked, not imported.
5. **Identifiers.** A booking code must be different on every row (`fit_unique_identifier`; a code that repeats stays a candidate to be
   asked about, never a sure one). A document number may repeat (the lines of one invoice) but must be short, with digits, and not a
   row counter. In a register where every row is a different invoice the invoice-level net is the net of the line.
6. **Formats.** A month name is a date in either order of words ("26 ottobre 2026", "Nov 4, 2026"); a numeric date over a two-digit year
   needs the same day/month decision as one over four digits and reads with `%y` once the person has decided. A credit note is a negative
   amount (costs only).
7. **Personal data.** Free text about a person (`NOTE`), an address (`ADDRESS`) and the number that identifies an employee
   (`EMPLOYEE_ID`: badge, matricola) are never shown, sampled or sent. A person's tax code and a supplier's IBAN are left out of a
   register of costs; a payslip ("Netto in busta") is never an amount of one.
8. **Stated beats guessed.** "Reparto: Spa" above a table is the department of the rows; the other lines of the block ("Responsabile:
   Direzione") are not.

## What was decided NOT to do

* **No pipe delimiter.** The closed set of delimiters (`;`, `,`, tab) is a tested contract (`test_booking_mapping`); a pipe-delimited
  file is refused cleanly. The benchmark keeps three of them in the unsupported group.
* **Names under a supplier header are still supplier names after a confirmation.** The official benchmark (C45, "Intestatario") reads a
  sole trader's name as a supplier; locking person-shaped columns in a cost register would have made it MANUAL. The V2 truth was aligned
  to the product decision, not the other way round.
* **A month name over a short year stays refused** ("26-ott-26"): a year is never invented (four hardening tests). The loose words of a
  hand-made sheet ("Da chi", "Cosa") stay MEDIUM: two loose names are confirmed once, not trusted (an earlier hardening test). Both were tried
  in this gate, failed the suite and were taken back.
* **No department codes in the lexicon** ("HK", "FO", "REC") - the hotel's own, asked once and remembered (ADR of Question Reduction 1).
* **No change to Source Learning** (families, per-family layout, revision, trust). Fixtures that used "Note"/"Annotazioni" as an
  incidental junk column now use a neutral header, because those words are personal notes since this decision and personal columns are
  deliberately not part of a remembered shape.

## Consequences

* The words of the engine grew by concept; the cost is paid once per concept, not per exporter. The abbreviation rule is the part that
  generalises beyond the list: it works for a word the vocabulary knows even when no one wrote the abbreviation down.
* Two behaviours became more conservative on purpose (more questions, never fewer protections): hours above a day with a person on the
  row, a repeated booking code.
* One behaviour became more permissive on purpose, with a counter-example: negative amounts in a register of costs.

## Known limits

See `docs/architecture/smart-import-v3-universal-understanding-2.md` ("What this does not do").

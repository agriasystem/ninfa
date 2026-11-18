# Smart Import V4.1 - algorithmic understanding

Status: built on `feature/smart-import-v4-algorithmic-understanding` (base `main` = `7d826a2`). Not pushed, not merged. No migration. The semantic
(OpenAI) layer is untouched and stays `off`. The measured results are in
[the benchmark report](../benchmarks/smart-import-v4-algorithmic-understanding.md); the decision is in
[ADR 0056](adr/0056-smart-import-v4-reads-files-with-algorithms-and-keeps-v3-one-setting-away.md).

## Why algorithms first

Smart Import already has a layer that asks a model what a column means (V3's optional port, then the OpenAI Responses adapter, ADR 0050-0054). It is measured, safe, and OFF in the pilot -
and it needs a vendor, a key, an egress review and a cost per import. Most of what a file says does not need a model: a hotel's export names its columns in a small, closed vocabulary
(`reservation_code`, `CheckInDate`, `Nr. Pratica`), spells them sloppily (`Arival Date`), glues them (`checkindate`), and the values of a column say what it is (a status repeats
three words, a booking code differs on every row, three dates in order are booked / arrival / departure). V4.1 reads all of that with deterministic code and asks a PERSON only where the
file is genuinely ambiguous. The normal import path calls no model, sends nothing anywhere, and its external cost is zero.

## Where it sits

```
CSV / XLSX
  -> FORMAT          document_understanding: sheets, tables, header row, title, totals     (V3, unchanged)
                     data_sources/algorithmic/dialect.py: a second opinion on the delimiter (V4, only when V3's count is unsure)
  -> COLUMN PROFILE  algorithmic/profile.py     counts, shapes, vocabulary shares of every column   (V4)
  -> HEADER          algorithmic/header.py      normalise + match the hospitality vocabulary        (V4, RapidFuzz)
  -> VALUES          algorithmic/values.py      what the values prove, what they rule out           (V4)
  -> RELATIONS       algorithmic/relational.py  booked <= arrival < departure, net + VAT = total    (V4)
  -> CANDIDATE SCORE algorithmic/scoring.py     one auditable total per (column, field)             (V4)
  -> SELECTION       V3's greedy pick over V4's scores (default)  |  assignment.py: scipy linear_sum_assignment
                     over the whole file (`v4-assign`, optional: measured, it changed one reading in 1,026)
  -> DOMAIN CHECK    algorithmic/validate.py    NINFA's rules applied to the reading                (V4)
  -> everything below is V3 and shared: contested look-alikes, partner columns, "hours that do not say which",
     the domain verdict, the questions, the blockers, READY, Source Learning, the validators, FULL / PARTIAL / DELTA
```

The seam is ONE function. `proposal.propose()` already ended in a `Proposal` that everything downstream consumes. Its two selection steps (every column against every field, then take the
best pair first) are now `greedy_selection()`, V3's, unchanged in behaviour (the 237 pre-existing semantics tests and the official benchmark were re-run to prove it); a `SelectionEngine`
may replace them. `AlgorithmicEngine.select()` is V4's. Nothing after the selection knows which engine ran, so every safety rule (the unread-sibling hold, the personal-data lock, the
money rule, the question limits, the level rule that turns a MEDIUM into a question and never into READY) applies to V4's readings exactly as to V3's.

## The pieces

**Vocabulary** (`vocabulary.py`, versioned `hospitality-2026.11.1`). About 990 phrases (bookings 488, costs 348, staff 153) and 160 that mean something else, Italian and English, written
out, abbreviated and as a database names a column. It is
data only and tied to no PMS or provider. Rules it follows, each from a real collision found while building it: no generic word (`Total amount`, `Importo`, `Data` stay with V3's questions);
a phrase that means ANOTHER thing is listed apart (`NOT_THE_FIELD`: `ADR`, `Room nights`, `Payment status`, `Check in time`); a phrase V3's importer already gives to one field is never given to
another (tests); and no phrase of the benchmark's held-out list is in it (a test).

**Header matching** (`header.py`). A header is normalised - camelCase split, a qualifier in brackets set aside, accents and punctuation folded, `n.`/`nr`/`#` = "number", words written
without spaces cut into vocabulary words - and compared with the phrases of each field: exact (1.00), the same words reordered (0.97), the same plus a word naming the kind of file (0.95),
or a spelling mistake (0.85-0.99). RapidFuzz measures how alike two WORDS are, never two whole headers: `check in` and `check out` are 60% alike as strings and are different headers
whatever the letters. A mistake is only ever a reading, never a certainty (it caps at MEDIUM through V3's own `level_of`). It runs in about 0.1 ms per header.

**Who reads a header, in order of authority.** (1) a name the kind of data already knows (V3 EXACT) - never overruled, because `Imponibile` is a LINE amount in a register and `Totale soggiorno`
a room revenue by product decision; (2) a phrase that IS the header - it beats (3) a bag-of-words rule, which cannot tell `Supplier VAT` from `Supplier` or `Payment status` from `Status`;
(4) a phrase plus a context word, or a spelling mistake, only for a header nothing above read. This ordering is the result of two measured regressions (below), not a design preference.

**Column profile** (`profile.py`). Per column: rows, nulls, uniqueness, primitive type, min/max, sign, whole-number and cents shares, date range, text lengths, the commonest values (only for a
column of repeating words that is not personal data, at most 8, at most 24 characters), money / percent / identifier shapes, and the share of its values that are a known status, channel,
country, department, currency or cost category. Deterministic, computed in memory, kept nowhere, never logged; `describe()` prints counts and shapes only.

**Value semantics** (`values.py`). Two questions per (column, field). PROOF: can the values alone name the field? Only a closed vocabulary or a shape can - a status, a department, a currency, a cost category, a VAT number,
a booking code (different on every row, one shape). A number is never proof of an amount, a count or hours, and **a channel is never named by its values alone** - a product decision of
an earlier gate, pinned by a test, that the first version of V4 broke and the full-suite run under V4 found. Two more such decisions are honoured: a column is left to its values
**only when its header says nothing NINFA knows** ("Campo 3", "Condizione" - never "Centro di costo", which says it is something else and is not a department), and a bare code over repeated values
is ASKED about, not dropped. VETO: can the values rule the field
out? A column of channel names is not a status, a column with cents is not a booking code, dates are not a room count, a percentage is not a number of rooms. One slip of the data
(under 20% of the values) is not a veto, and under three values nothing is ruled out.

**Relations** (`relational.py`). Three dates that read booked <= arrival < departure on 95% of rows, in exactly one ordering, are those three dates whatever the file's column order; two dates
that are a short stay are a stay (a bonus, not proof of the booking date); net + VAT = total on 95% of rows names the three amounts of a register (a bonus). A relation that fits two orderings
names nothing.

**Candidate score** (`scoring.py`). `total = header x (0.55 + 0.45 x values) + relation` for a column with a name; `0.62 x proof + relation` for a column named by its values alone (never above a
name). Every part is kept (`CandidateScore.breakdown()`), including the reason a candidate was ruled out. A reading from the values alone is allowed only in a file that already looks like
this kind of data (three fields named by their headers, or a date relation): a marketing report uploaded as bookings has a column of unique codes too, and it is not a booking code.

**Global assignment** (`assignment.py`, the optional `v4-assign` engine - NOT the default). With the totals as a score matrix (rows = columns of the table, columns = canonical fields plus one private "left out" slot per column worth 0.25,
pairs below 0.30 forbidden), `scipy.optimize.linear_sum_assignment` finds the best reading of the WHOLE file. A level is worth +0.40 (HIGH) / +0.20 (MEDIUM) in the total - V3 took the pairs
a name and values confirm before the ones they only partly confirm, and a total that ignored the level let `Job Title` outbid `Operating Unit`. Fields nobody supplies stay empty, columns
nobody wants are left out, ties go to the earlier column as in V3, and the same file always gives the same reading. Each chosen pair's MARGIN is the total the file loses without it: a
coin flip has margin 0. A reading from the values alone with a close second reading is dropped. Whether a close second reading also turns a NAME-based HIGH into a question is a setting
of the engine (`demote_names`, the `v4-margin` configuration), measured in the report. **Measured result: over 1,026 documents the assignment changes ONE reading, for the worse
(ADV12, two columns of statuses), and the margin demotion buys no safety V4 does not already have; so the default `v4` keeps V3's greedy pick over V4's evidence and SciPy is a development
dependency.** The assignment's value is real in a synthetic file (the tests pin a global optimum that greedy cannot find); in the files measured, greedy was already optimal.

**Domain validation** (`validate.py`). Arrival and departure that read swapped (the departure before the arrival on 95% of rows) go to LOW; a room count that is not a whole number of at least
one, and a negative booking amount or labour cost, go to MEDIUM. Certainty only goes down. The other rules the V4.1 brief lists are already enforced where they are exact: `net + VAT =
total` (`understanding_costs.amounts_check`, shown as a warning), hours per person (`DomainSem.person_limits`), planned and actual hours as two columns (an assignment never gives two fields
one column), an unknown status or category (the labels questions), a repeating identifier (`fit_unique_identifier`), and every row-level rule of the importers.

**CSV dialect** (`dialect.py`). DuckDB (primary) reads delimiter, quote, header, column types and date format from the file IN MEMORY (an fsspec memory file, removed at once - customer data
never touches the disk); CleverCSV is consulted only when DuckDB cannot read the file or leaves it ambiguous. NINFA's importers read `;`, `,` and a tab - a tested contract - so a
sniffer that finds another delimiter REPORTS it (`supported` is False) and the file is handled as before. A sniffer overrules V3's counting rule only when it splits the sample at
least 10 points more consistently, and the second opinion is asked ONLY when the counting rule is itself unsure (under 85% of the first lines agree on a width), so a normal upload pays for
nothing. See the report for what this measured: on 17 files whose delimiter NINFA reads the counting rule was right 17 times, DuckDB 15, CleverCSV 17; this is the part of V4.1 that did
NOT show a gain, which is why its libraries are development dependencies.

## Audit of the pipeline V4 started from: kept, replaced, added

| Stage of the V3 pipeline | Where | V4.1 |
|---|---|---|
| CSV parsing (delimiter, quoting, `sep=` line, UTF-8 then Windows-1252) | `document_understanding/grid.py`, `bookings/parsers/csv_parser.py` | **kept**; a second opinion on the delimiter is asked only when its count is unsure (`dialect.py`). Encoding is not re-detected (V3 decodes UTF-8, then Windows-1252, and refuses UTF-16 - a tested contract; DuckDB's sniffer reports none) |
| XLSX parsing (openpyxl, streaming, merged cells, hidden sheets) | `grid.py` | **kept**, untouched; the V4 profile and semantics work on the column samples both formats produce |
| Table and header-row detection, titles, totals, day grids | `structure.py`, `document.py`, `titles.py`, `days.py` | **kept** |
| Column statistics (`ColumnStats`) | `document_understanding/stats.py` | **kept**, and extended by `ColumnProfile` (uniqueness, sign, cents, shapes, vocabulary shares) |
| Canonical fields and their names | `bookings/mapping.py`, `labor/mapping.py`, `invoices/mapping.py`, `*/suggestions.py` | **kept**; a second, versioned vocabulary (`vocabulary.py`) sits beside them |
| Word rules, exact names, a likeness of letters (`difflib`) | `semantics*.py` | **kept**, with V3's likeness of letters used only when nothing else reads a column; RapidFuzz reads spelling mistakes word by word |
| Mapping: every column against every field, best pair first | `proposal.propose()` | **seam**: the same function, its selection steps now replaceable |
| Level (HIGH / MEDIUM / LOW) of a reading | `semantics.level_of` | **kept** and still the only source of a level |
| Contested look-alikes, partner columns, "hours that do not say which", sibling hold | `proposal.py`, `understanding*.py` | **kept**, shared by both engines |
| Domain verdict (bookings / staff / costs) | `domain_detection.py` | **kept**: it scores the `Proposal` of each kind of data, so a better proposal is a better verdict with no change |
| Questions, blockers, READY, the question limits | `understanding.py` | **kept** |
| Source Learning, remembered scope, FULL / PARTIAL / DELTA | `source_learning.py`, `remembered_answers.py` | **kept**, untouched |
| Import validators (row rules, all-or-nothing) | the three importers | **kept**; `validate.py` adds the early per-column check |
| The semantic (OpenAI) layer | `ai/import_understanding`, `ai/gateway` | **kept**, `off`, untouched |
| Benchmarks (official 240, unseen 432, challenge, Source Learning) | `tests/benchmarks/` | **kept**, re-run unchanged; `algorithmic_v4/` added |

## What stays exactly as it was

Format understanding (tables, header rows, titles, totals, merged cells, day grids), the personal-data lock and every PII rule, the questions and their limits, READY, blockers, the sibling
hold, FULL / PARTIAL / DELTA and the removal confirmation, remembered scope, same-day revisions, the identical-import no-op, planned vs actual, labour cell coverage, stale bookings,
observed / reconstructed, Source Learning (families, layout hints, the `current` guard), booking freshness, Decision gating, the importers and their validators, the OpenAI layer (code,
benchmarks and history; `SMART_IMPORT_AI_MODE=off`). A mapping a person confirms is stored as columns and fields, never as what the engine thought, so no stored profile depends on the engine.

## Selecting the engine, and rolling back

`SMART_IMPORT_UNDERSTANDING_ENGINE` (`v3` | `v4`, default **`v3`**; `v4` = header + value semantics + relations + domain validation, greedy selection). The app reads it once at startup (`create_app` -> `selector.configure`). The server verifies a confirmed decision by reading the
file AGAIN with the same engine, so the understanding and the check cannot disagree. A test or benchmark picks an engine for a block with `use_engine(...)`.

Rollback is one setting and a restart: set `v3`. There is no data to migrate back - nothing V4 computes is stored. The new dependency (RapidFuzz) is only imported by the new package
and the optional ones lazily with a graceful fallback when absent, so V3 does not load them.

## Dependencies and licences

| Package | Role | Licence | Shipped to production? |
|---|---|---|---|
| RapidFuzz 3.14 | word-level likeness (header spelling mistakes) | MIT | **yes** - `header.py`, every upload read by V4 |
| SciPy 1.18 (+ NumPy 2.5) | `linear_sum_assignment` (`v4-assign`) | BSD-3-Clause (NumPy: BSD-3 AND 0BSD AND MIT AND Zlib AND CC0) | no - development group; imported lazily |
| DuckDB 2.0 | CSV sniffer (dialect, types, dates) | MIT | no - development group; the reader is a no-op without it |
| CleverCSV 0.8 (+ chardet 7, regex, packaging) | fallback sniffer | MIT (chardet 7: 0BSD; regex: Apache-2.0 AND CNRI-Python; packaging: Apache-2.0 OR BSD-2-Clause) | no - development group |
| fsspec 2026.9 | lets DuckDB read the file from memory instead of a temp file | BSD-3-Clause | no - development group |

All are permissive and compatible with commercial use. Only RapidFuzz ships to production: the other four were measured and added nothing the default engine needs (see the report); moving
them from the `dev` group to `dependencies` turns the dialect reader and the assignment on. fsspec is not on the approved list; it is the module DuckDB itself requires to read a Python buffer, and the alternative - a temporary
file - would write customer data to disk, which NINFA never does (the database keeps only a hash and a size of an upload).

## Files

`app/modules/data_sources/algorithmic/` (`vocabulary`, `header`, `profile`, `values`, `relational`, `scoring`, `assignment`, `validate`, `engine`, `dialect`, `selector`);
`proposal.py` (the seam: `Selection`, `SelectionEngine`, `greedy_selection`); `document_understanding/grid.py` (a hook for the delimiter's second opinion);
`understanding.py` (one import); `core/config.py` + `main.py` (the setting). Tests: `tests/test_algorithmic_*.py`. Benchmarks: `tests/benchmarks/algorithmic_v4/` (the problem corpus, the
ablation harness, the explain tool, the report generator).

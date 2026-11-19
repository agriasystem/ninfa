# Smart Import V4.1 - algorithmic understanding

Status: production-closed on `feature/smart-import-v4-algorithmic-understanding` (base `main` = `7d826a2`). Open as pull request #47, not merged. No migration. `SMART_IMPORT_UNDERSTANDING_ENGINE`
defaults to **`v3`**: merging changes nothing a pilot or production sees until the setting is changed. The semantic (OpenAI) layer is untouched and stays `off`. The measured
results are in [the benchmark report](../benchmarks/smart-import-v4-algorithmic-understanding.md); the decision is in
[ADR 0056](adr/0056-smart-import-v4-reads-files-with-algorithms-and-keeps-v3-one-setting-away.md).

## What is in the product, and what was evaluated and left out

| | Verdict | Why (measured, not an opinion - see the report) |
|---|---|---|
| Header normalisation (camelCase, glued words, qualifiers, abbreviations) | **kept** | the whole header gain: camelCase and glued files go from 0 READY to 9 READY each in the problem corpus |
| Versioned hospitality vocabulary (IT/EN, bookings / costs / staff) | **kept** | same; plus "phrases that mean something else" that block a wrong reading |
| RapidFuzz (word-level likeness) | **kept** (the one new runtime dependency) | small but real: +0.8 points of recall on one-typo files, stricter than `difflib`; 1.6 MB, no dependencies |
| Column profiler | **kept** | what the value rules and the negative evidence stand on |
| Value semantics and negative evidence | **kept** | the biggest single part: manual matching 271 -> 228 |
| Relations (booked <= arrival < departure, net + VAT = total) | **kept** | names three dates / three amounts whatever the column order |
| Domain validation (`validate.py`) | **kept** | can only lower a certainty |
| NINFA validators, Source Learning, FULL / PARTIAL / DELTA | **kept, untouched** | |
| SciPy global assignment (`linear_sum_assignment`) | **evaluated, not adopted, removed** | over 1,026 documents it changed ONE reading, for the worse |
| Margin demotion of names | **evaluated, not adopted, removed** | cost READY, bought no safety V4 does not already have |
| DuckDB CSV sniffer | **evaluated, not adopted, removed** | right on 15 of 17 files whose delimiter NINFA reads (the counting rule V3 already has: 17 of 17) |
| CleverCSV fallback sniffer | **evaluated, not adopted, removed** | agreed with the counting rule; reached on 0 benchmark files |
| fsspec | **removed with DuckDB** | its only use was to let DuckDB read from memory |

The code of the four removed pieces lives in this branch's history up to commit `5ebbe6e`; their results are in the benchmark report and in the stored
`services/api/tests/benchmarks/results/smart-import-v4-algorithmic-ablation.json`. A test (`test_algorithmic_dependency_boundary.py`) keeps their libraries out of every manifest and every
import, so nobody re-adds them without reading the evidence.

## Why algorithms first

Smart Import already has a layer that asks a model what a column means (V3's optional port, then the OpenAI Responses adapter, ADR 0050-0054). It is measured, safe, and OFF in the pilot -
and it needs a vendor, a key, an egress review and a cost per import. Most of what a file says does not need a model: a hotel's export names its columns in a small, closed vocabulary
(`reservation_code`, `CheckInDate`, `Nr. Pratica`), spells them sloppily (`Arival Date`), glues them (`checkindate`), and the values of a column say what it is (a status repeats
three words, a booking code differs on every row, three dates in order are booked / arrival / departure). V4.1 reads all of that with deterministic code and asks a PERSON only where the
file is genuinely ambiguous. The normal import path calls no model, sends nothing anywhere, and its external cost is zero.

## Where it sits

```
CSV / XLSX
  -> FORMAT          document_understanding: delimiter, sheets, tables, header row, title, totals   (V3, unchanged)
  -> COLUMN PROFILE  algorithmic/profile.py     counts, shapes, vocabulary shares of every column   (V4)
  -> HEADER          algorithmic/header.py      normalise + match the hospitality vocabulary        (V4, RapidFuzz)
  -> VALUES          algorithmic/values.py      what the values prove, what they rule out           (V4)
  -> RELATIONS       algorithmic/relational.py  booked <= arrival < departure, net + VAT = total    (V4)
  -> CANDIDATE SCORE algorithmic/scoring.py     one auditable total per (column, field)             (V4)
  -> SELECTION       V3's greedy pick over V4's scores
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

**Domain validation** (`validate.py`). Arrival and departure that read swapped (the departure before the arrival on 95% of rows) go to LOW; a room count that is not a whole number of at least
one, and a negative booking amount or labour cost, go to MEDIUM. Certainty only goes down. The other rules the V4.1 brief lists are already enforced where they are exact: `net + VAT =
total` (`understanding_costs.amounts_check`, shown as a warning), hours per person (`DomainSem.person_limits`), planned and actual hours as two columns (the selection never gives one column
two fields), an unknown status or category (the labels questions), a repeating identifier (`fit_unique_identifier`), and every row-level rule of the importers.

## Evaluated and not adopted

Three things the V4.1 brief asked to try were built, tested and measured, and they are not in the product. The numbers are in the report; what each one was:

**Global assignment** (SciPy `linear_sum_assignment`). With every total as a score matrix (rows = columns of the table, columns = canonical fields plus one "left out" slot per
column), it finds the best reading of the WHOLE file instead of taking the best-looking pair first. It needed a level bonus (V3 took the pairs a name and values confirm before the ones
they only partly confirm; without it `Job Title` outbid `Operating Unit`) and a margin analysis (the total a file loses without a pair). **Measured over 1,026 documents it changed ONE
reading (ADV12, two columns of statuses), for the worse.** A variant that also turned a name-based HIGH into a question when a close second reading existed (`v4-margin`) cost 4 READY
(`Descrizione` next to `Voce`, which V3 resolves silently and correctly) and bought no safety once the contested-column bug (below) was fixed. In a synthetic file a global optimum
that greedy cannot find does exist; in the files measured, greedy was already optimal. Removed, with SciPy and NumPy.

**CSV dialect second opinion** (DuckDB, then CleverCSV; fsspec so DuckDB could read from memory instead of a temporary file). On 17 stress files whose delimiter NINFA's importers read,
the counting rule V3 already uses was right 17 times, DuckDB 15 (wrong where the text is full of the other delimiter), CleverCSV 17. In the benchmarks the second opinion was asked on 1 of
145 CSV files and DuckDB agreed with the counting rule; CleverCSV was never reached. The only thing a sniffer does that nothing else does is name a delimiter NINFA does not read (a
pipe), which the product refuses anyway. DuckDB also does not skip the title lines above a table (V3's structure reader does). Removed, with the hook in `grid.py`, which is `main`'s again.

**RapidFuzz stays, with an honest note on its size.** On 34 files with exactly one misspelled header it adds about one fact in a hundred (recall 97.58% -> 98.39%) and changes no
document's level: V3's own likeness of letters already turned one misspelled header into one question. The gain of the header reader is the vocabulary and the normalisation. It stays
because it costs nothing (a 1.6 MB wheel, no dependencies, no infrastructure), it is stricter than `difflib` (word by word, with an opposite-words guard) and it is not a path
anyone would route around.

## Audit of the pipeline V4 started from: kept, replaced, added

| Stage of the V3 pipeline | Where | V4.1 |
|---|---|---|
| CSV parsing (delimiter, quoting, `sep=` line, UTF-8 then Windows-1252) | `document_understanding/grid.py`, `bookings/parsers/csv_parser.py` | **kept, untouched** (`grid.py` is `main`'s). DuckDB and CleverCSV were evaluated and are not adopted (above) |
| XLSX parsing (openpyxl, streaming, merged cells, hidden sheets) | `grid.py` | **kept**, untouched; the V4 profile and semantics work on the column samples both formats produce |
| Table and header-row detection, titles, totals, day grids | `structure.py`, `document.py`, `titles.py`, `days.py` | **kept** |
| Column statistics (`ColumnStats`) | `document_understanding/stats.py` | **kept**, and extended by `ColumnProfile` (uniqueness, sign, cents, shapes, vocabulary shares) |
| Canonical fields and their names | `bookings/mapping.py`, `labor/mapping.py`, `invoices/mapping.py`, `*/suggestions.py` | **kept**; a second, versioned vocabulary (`vocabulary.py`) sits beside them |
| Word rules, exact names, a likeness of letters (`difflib`) | `semantics*.py` | **kept**, with V3's likeness of letters used only when nothing else reads a column; RapidFuzz reads spelling mistakes word by word |
| Mapping: every column against every field, best pair first | `proposal.propose()` | **seam**: the same function, its selection steps now replaceable; V4 keeps the greedy pick over richer evidence |
| Level (HIGH / MEDIUM / LOW) of a reading | `semantics.level_of` | **kept** and still the only source of a level |
| Contested look-alikes, partner columns, "hours that do not say which", sibling hold | `proposal.py`, `understanding*.py` | **kept**, shared by both engines |
| Domain verdict (bookings / staff / costs) | `domain_detection.py` | **kept**: it scores the `Proposal` of each kind of data, so a better proposal is a better verdict with no change |
| Questions, blockers, READY, the question limits | `understanding.py` | **kept** |
| Source Learning, remembered scope, FULL / PARTIAL / DELTA | `source_learning.py`, `remembered_answers.py` | **kept**, untouched |
| Import validators (row rules, all-or-nothing) | the three importers | **kept**; `validate.py` adds the early per-column check |
| The semantic (OpenAI) layer | `ai/import_understanding`, `ai/gateway` | **kept**, `off`, untouched |
| Benchmarks (official 240, unseen 432, challenge, Source Learning) | `tests/benchmarks/` | **kept**, re-run unchanged and frozen; `algorithmic_v4/` added |

## What stays exactly as it was

Format understanding (tables, header rows, titles, totals, merged cells, day grids), the personal-data lock and every PII rule, the questions and their limits, READY, blockers, the sibling
hold, FULL / PARTIAL / DELTA and the removal confirmation, remembered scope, same-day revisions, the identical-import no-op, planned vs actual, labour cell coverage, stale bookings,
observed / reconstructed, Source Learning (families, layout hints, the `current` guard), booking freshness, Decision gating, the importers and their validators, the OpenAI layer (code,
benchmarks and history; `SMART_IMPORT_AI_MODE=off`). A mapping a person confirms is stored as columns and fields, never as what the engine thought, so no stored profile depends on the engine.

## Selecting the engine, and rolling back

`SMART_IMPORT_UNDERSTANDING_ENGINE` (`v3` | `v4`, default **`v3`**; `v4` = header + value semantics + relations + domain validation, greedy selection). The app reads it once at startup (`create_app` -> `selector.configure`). The server verifies a confirmed decision by reading the
file AGAIN with the same engine, so the understanding and the check cannot disagree. A test or benchmark picks an engine for a block with `use_engine(...)`; `v4-header` (the
vocabulary and RapidFuzz without the value evidence) exists only so the benchmark can measure what the values add, and the setting does not accept it.

Rollback is one setting and a restart: set `v3`. There is no data to migrate back - nothing V4 computes is stored. The one new dependency (RapidFuzz) is imported by one module of the new
package (`header.py`) and nothing else in the application.

## Dependencies and licences

| Package | Role | Licence | Production? |
|---|---|---|---|
| RapidFuzz 3.14 | word-level likeness (header spelling mistakes) | MIT | **yes** - the one new runtime dependency, imported by `header.py` only |
| SciPy (+ NumPy), DuckDB, CleverCSV (+ chardet, regex), fsspec | global assignment; CSV sniffers | permissive | **no - not declared in any manifest, not in `uv.lock`, imported by nothing** |

RapidFuzz is MIT, has no dependencies and no infrastructure, and ships as a 1.6 MB wheel. The other five were measured (see above and the report) and removed; a test
(`test_algorithmic_dependency_boundary.py`) fails if one is declared or imported again, and the six older dependency scope guards allow RapidFuzz by name and nothing else. Bringing
one back is a decision with evidence, not an accident of a `uv add`.

## How the tests know which engine reads

The semantic (model) layer starts from what the rules LEFT OPEN, so which file reaches the model depends on the engine: V3 leaves a status called `Condizione` open and asks the model;
V4 reads it from its values and asks the person, so the model is (rightly) not asked. A test that says "the model must be asked about `Condizione`" is therefore a statement about V3.
The suite says so explicitly instead of failing under V4 (it had 46 such failures when forced onto V4):

* the `rules_engine` fixture (`tests/conftest.py`) runs a test under **both** engines (`v3`, `v4`), whatever the process was started with;
* `@pytest.mark.rules_v3_only` marks a test whose premise is a gap only V3 leaves - it runs under V3 alone, and its V4 side is written;
* `test_smart_import_ai_with_each_engine.py` is that V4 side: a gap neither engine closes (a channel) under both engines - one call, a question never a decision, a failing or doubtful
  model leaves the rules' own answer, nothing personal is sent, SHADOW changes nothing; V4 resolving what V3 sent to the model (zero calls, the same screen for the person); the layer off
  (zero calls); no adversarial file READY at the production switches;
* the certainty and personal-header tests keep their safety property per engine (never READY; no personal value sent) and assert "the model was asked" only where the engine leaves a gap;
* the live acceptance script pins the engine it was written for (its synthetic file is a V3 gap), so it still exercises the model.

Nothing in the application was changed to make an old test pass; no assertion about safety was weakened - the ones that mentioned the model were moved to the engine they describe.

## Questions

V4 asks MORE questions than V3 on the benchmark (275 -> 318 over 1,026 documents) and fewer matching screens (288 -> 228 files at manual matching). The questions rise because 39 files that
V3 sent to the full matching screen now get one proposed reading to confirm. A confirmation of a proposed column is a click; a matching screen is a task. The benchmark counts those
confirmations as "unnecessary" because the truth of a challenge file is the READY file it was made from, so the unnecessary-question count rises (160 -> 197) while the person's effort
falls. Reducing it further is not part of this gate: it is V4.2, and it starts from real pilot files.

## Files

`app/modules/data_sources/algorithmic/` (`vocabulary`, `header`, `profile`, `values`, `relational`, `scoring`, `validate`, `engine`, `selector`);
`proposal.py` (the seam: `Selection`, `SelectionEngine`, `greedy_selection`); `understanding.py` (one import); `core/config.py` + `main.py` (the setting). Tests: `tests/test_algorithmic_*.py`,
`tests/test_smart_import_ai_with_each_engine.py`. Benchmarks: `tests/benchmarks/algorithmic_v4/` (the problem corpus, the ablation harness, the explain tool, the performance tool, the report
generator); evidence of what was removed: `tests/benchmarks/results/smart-import-v4-algorithmic-ablation.json`.

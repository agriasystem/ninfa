# ADR 0056: Smart Import V4 reads files with algorithms, and V3 stays one setting away

Status: proposed (Smart Import V4.1 - algorithmic understanding). It adds a second reader of columns beside V3's, selected by `SMART_IMPORT_UNDERSTANDING_ENGINE` (default **`v3`**). No migration,
no change to FULL / PARTIAL / DELTA, to Source Learning, to the UI, to the Decision Engine or to the OpenAI layer, which stays `off`. Whether it becomes the default is a decision for the
product owner after the pilot, not made here: the code ships dark.

## Context

Smart Import V3 reads a file's columns with word rules, a list of known names and a likeness of letters, checks the guess against the values, and takes the best-looking pair first. It is
right on the files it was hardened on (official benchmark 98.8% of required facts, zero false automation) and the OpenAI layer (ADR 0050-0054) lifts what the rules cannot read - at the price
of a vendor, a key, an egress review, a cost per file, and a gate (ADR 0054) that is still pending for a real hotel file.

Measured on files NOT shaped for V3 - a hotel's own export (`reservation_code`, `BookingStatus`, `checkindate`, `Arival Date`) - V3 reads **none** of the camelCase headers and none of the glued ones
(problem corpus, 22 documents: 0 READY), sends 155 of 290 "one unknown header" files (challenge) to the manual matching screen, and cannot use what the values say about a column no word names.
None of that needs a model.

## Decision

1. **Add an algorithmic selection engine**, `data_sources/algorithmic`, behind one seam: `proposal.propose()` already produced the `Proposal` everything downstream consumes; its two selection
   steps become `greedy_selection()` (V3, behaviour unchanged) and a `SelectionEngine` may replace them. Everything after the selection - contested look-alikes, partner columns, the questions and
   their limits, READY, the sibling hold, the personal-data lock, the validators, Source Learning, scope - is shared code, so V4 cannot bypass a safety rule V3 has.
2. **V4 can only add readings and remove certainty.** The levels still come from V3's `level_of`; a reading from a spelling mistake or from the values alone caps at MEDIUM (a question); the
   assignment values a level (+0.40 HIGH, +0.20 MEDIUM) so a firm reading is never outbid by a loose one; domain validation and ties only demote.
3. **Who reads a header, in order:** a name the kind of data already knows (V3 EXACT) -> a phrase of the vocabulary that IS the header (it beats a bag-of-words rule) -> V3's word rule -> a phrase
   plus a context word or a spelling mistake -> V3's likeness of letters, only when nothing else read the column. Two columns that satisfy the same V3 rule stay CONTESTED (a measured safety
   regression: see below).
4. **A column may be named by its values alone** (a status, a department, a currency, a cost category, a VAT number, a booking code, three dates in order) only in a file that already
   looks like this kind of data, only when its header says nothing NINFA knows, and never above MEDIUM. A number is never proof of an amount, a count or hours; a channel is never named by
   its values (an earlier product decision); a header that says something NINFA knows ("Centro di costo") is never read as another thing; a repeating code is asked about, not dropped.
5. **Selection stays V3's greedy pick, over V4's evidence.** A global assignment (SciPy `linear_sum_assignment`) is implemented, tested and selectable (`v4-assign`, with a margin demotion of
   names as `v4-margin`), but measured over 1,026 documents it changed ONE reading, for the worse, so it is not the default (see Consequences).
6. **Dependencies.** Only RapidFuzz is a runtime dependency. SciPy, DuckDB, CleverCSV and fsspec are **development-only**: measured, they added nothing the default engine needs (on 17 files whose
   delimiter NINFA reads, the counting rule was right on 17, DuckDB on 15, CleverCSV on 17 - `tests/benchmarks/algorithmic_v4/dialect_stress.py`; the assignment changed one document). The dialect reader and the
   assignment import them lazily and are no-ops without them; moving the lines from the `dev` group to `dependencies` turns them on.
7. **Rollback is one setting.** `SMART_IMPORT_UNDERSTANDING_ENGINE=v3` and a restart. Nothing V4 computes is stored (a confirmed mapping is columns and fields), so there is nothing to migrate back.

## What was measured (ablation, 1,026 documents, no model called)

See [the report](../../benchmarks/smart-import-v4-algorithmic-understanding.md). The decision rests on those numbers, which are generated, not typed.

## Consequences

* New readings are not new certainty. READY goes up only where a name the vocabulary reads and values that fit agree (camelCase, glued, plain-but-unknown names); a typo or a nameless column becomes
  one question instead of the matching screen - and the benchmark's own definition of "unnecessary question" counts those, so unnecessary questions rise while manual matching falls.
* Two bugs the benchmark found in the first version are now tests: (1) a vocabulary phrase overruled V3's reading of `Imponibile` / `Totale soggiorno` (product decisions, not likenesses of letters)
  and replaced it with a different field; (2) a vocabulary phrase made `Issue date` next to `Invoice date` stop being CONTESTED, producing the one unsafe READY V4 ever had (UK022). The rule is
  "V4 never removes a protection V3 has": the phrase reading inherits V3's rule index.
* The margin demotion of names would also have caught (2), at the price of more questions on ties V3 resolves silently and correctly (`Descrizione` next to `Voce`: 4 READY lost in 1,026 for no
  safety gain once (2) was fixed); it is measured, kept as the `v4-margin` configuration, and not the default.
* Dependencies grow by RapidFuzz alone (a 1.6 MB wheel, no dependencies). SciPy (with NumPy, about 50 MB installed) stays out of production because the assignment it serves measured as worth nothing
  here; if a pilot file shows what greedy cannot, enabling it is a dependency move, not a rewrite.
* The vocabulary is written by hand and maintained: `VERSION` is stamped, a test forbids two fields claiming one phrase and forbids copying the benchmark's held-out words. It was written AFTER the
  held-out list had been read in the benchmark source (disclosed), so independence rests on that test, on the unseen-file `holdout` split and on the problem corpus, not on blind authoring.

## Alternatives considered

* **Sentence embeddings / a local model** (rejected by the brief, and unnecessary: the gain is in spelling, glueing, values and relations, none of which needs semantic similarity).
* **DuckDB as the reader of record for CSV.** It does not skip the title lines above a table (V3's structure reader does) and read two of the seventeen stress files whose delimiter NINFA reads wrongly (19 files in all).
* **Pandera for validation.** The importers already refuse a bad row; the gap was only the early, per-column check, which is 60 lines (`validate.py`).
* **Making V4 the default now.** Not without a pilot on a real file, as for every reader of customer data in this codebase.

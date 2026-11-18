# ADR 0056: Smart Import V4 reads files with algorithms, and V3 stays one setting away

Status: production-closed, ready for review (Smart Import V4.1). It adds a second reader of columns beside V3's, selected by `SMART_IMPORT_UNDERSTANDING_ENGINE` (default **`v3`**). No migration,
no change to FULL / PARTIAL / DELTA, to Source Learning, to the UI, to the Decision Engine or to the OpenAI layer, which stays `off`. Whether V4 becomes the engine of a pilot is a separate
activation after the merge (a setting and a restart); whether it becomes the default is a decision for the product owner after real pilot files. The code ships dark.

## Context

Smart Import V3 reads a file's columns with word rules, a list of known names and a likeness of letters, checks the guess against the values, and takes the best-looking pair first. It is
right on the files it was hardened on (official benchmark 98.8% of required facts, zero false automation) and the OpenAI layer (ADR 0050-0054) lifts what the rules cannot read - at the price
of a vendor, a key, an egress review, a cost per file, and a gate (ADR 0054) that is still pending for a real hotel file.

Measured on files NOT shaped for V3 - a hotel's own export (`reservation_code`, `BookingStatus`, `checkindate`, `Arival Date`) - V3 reads **none** of the camelCase headers and none of the glued ones
(problem corpus: 0 READY), sends 155 of 290 "one unknown header" files (challenge) to the manual matching screen, and cannot use what the values say about a column no word names.
None of that needs a model.

## Decision

1. **Add an algorithmic selection engine**, `data_sources/algorithmic`, behind one seam: `proposal.propose()` already produced the `Proposal` everything downstream consumes; its two selection
   steps become `greedy_selection()` (V3, behaviour unchanged) and a `SelectionEngine` may replace them. Everything after the selection - contested look-alikes, partner columns, the questions and
   their limits, READY, the sibling hold, the personal-data lock, the validators, Source Learning, scope - is shared code, so V4 cannot bypass a safety rule V3 has.
2. **V4 can only add readings and remove certainty.** The levels still come from V3's `level_of`; a reading from a spelling mistake or from the values alone caps at MEDIUM (a question); domain
   validation only demotes.
3. **Who reads a header, in order:** a name the kind of data already knows (V3 EXACT) -> a phrase of the vocabulary that IS the header (it beats a bag-of-words rule) -> V3's word rule -> a phrase
   plus a context word or a spelling mistake -> V3's likeness of letters, only when nothing else read the column. Two columns that satisfy the same V3 rule stay CONTESTED (a measured safety
   regression: see below).
4. **A column may be named by its values alone** (a status, a department, a currency, a cost category, a VAT number, a booking code, three dates in order) only in a file that already
   looks like this kind of data, only when its header says nothing NINFA knows, and never above MEDIUM. A number is never proof of an amount, a count or hours; a channel is never named by
   its values (an earlier product decision); a header that says something NINFA knows ("Centro di costo") is never read as another thing; a repeating code is asked about, not dropped.
5. **Selection stays V3's greedy pick, over V4's evidence.**
6. **Production scope is what the benchmark justified, and nothing else** (below).
7. **Rollback is one setting.** `SMART_IMPORT_UNDERSTANDING_ENGINE=v3` and a restart. Nothing V4 computes is stored (a confirmed mapping is columns and fields), so there is nothing to migrate back.

## Kept, and evaluated and not adopted

**Kept in the normal path:** header normalisation, the versioned hospitality vocabulary, RapidFuzz, the column profiler, value semantics with negative evidence, relations, the domain validation,
NINFA's own validators and Source Learning. The first six are V4's; the last two are untouched.

**Evaluated, measured, not adopted, and removed from the code, the manifests and `uv.lock`:**

| Candidate (asked for by the V4.1 brief) | What was measured | Why it is not in the product |
|---|---|---|
| SciPy global assignment (`linear_sum_assignment`) | over 1,026 documents it changed ONE reading (ADV12, two columns of statuses), for the worse | it cannot improve what greedy already gets right, and it would bring SciPy and NumPy into the runtime for one function |
| Margin demotion (the assignment's close-second analysis) | cost 4 READY (`Descrizione` next to `Voce`, resolved correctly by V3's tie-break), no safety gain | the contested-column bug it would have caught is fixed at its root (below) |
| DuckDB CSV sniffer | right on 15 of 17 stress files whose delimiter NINFA reads; the counting rule of V3: 17 of 17; does not skip title lines above a table | adds time (~700 ms over 19 files) and no accuracy |
| CleverCSV fallback sniffer | agreed with the counting rule on 17 of 17; reached on **0** benchmark files (the second opinion was asked on 1 of 145 CSV files and DuckDB settled it) | never used where it would matter |
| fsspec | only there so DuckDB could read from memory instead of a temporary file | goes with DuckDB |

This is a measured result, not an opinion: the ablation (`tests/benchmarks/algorithmic_v4`) and the dialect stress are in the benchmark report, the full per-document ablation of the five engines
is stored in `services/api/tests/benchmarks/results/smart-import-v4-algorithmic-ablation.json`, and the removed code is in this branch's history up to commit `5ebbe6e`. The brief asked that a dependency
be PROVEN useless before being left out; that is what the report is. `test_algorithmic_dependency_boundary.py` keeps all five out of every manifest and every import. Bringing one back
needs a new measurement on real pilot files, not a `uv add`.

RapidFuzz stays although its measured value is small (on 34 files with one misspelled header: +0.8 points of recall, no change of level): it is 1.6 MB with no dependencies and no
infrastructure, it is stricter than `difflib`, and the gain of the header reader is the vocabulary and the normalisation, which it serves.

## What was measured (1,026 documents, no model called)

See [the report](../../benchmarks/smart-import-v4-algorithmic-understanding.md). The decision rests on those numbers, which are generated, not typed. In short: mapping recall 93.8% -> 94.7%,
READY 502 -> 526, manual matching 288 -> 228, with unsafe READY, wrong-domain READY, scope violations, false automation and personal values in the browser answer all **0**, no READY lost and no
document worse. On the official corpus and the unseen-file corpus - what V3 was built on - V4 changes no document.

## Consequences

* New readings are not new certainty. READY goes up only where a name the vocabulary reads and values that fit agree (camelCase, glued, plain-but-unknown names); a typo or a nameless column becomes
  one question instead of the matching screen.
* **More questions, fewer matching screens - on purpose.** Questions rise 275 -> 318 because 39 files V3 sent to the full matching screen now get one proposed reading to confirm; the benchmark's own
  definition of "unnecessary question" counts those (the truth of a challenge file is the READY file it was made from), so that count rises 160 -> 197 while manual matching falls 288 -> 228.
  A confirmation of a proposed column is preferable to a matching screen. Reducing the effort further is V4.2, and starts from real pilot files; this gate does not tune the engine against the
  benchmark to make the number look better.
* Two bugs the benchmark found in the first version are now tests: (1) a vocabulary phrase overruled V3's reading of `Imponibile` / `Totale soggiorno` (product decisions, not likenesses of letters)
  and replaced it with a different field; (2) a vocabulary phrase made `Issue date` next to `Invoice date` stop being CONTESTED, producing the one unsafe READY V4 ever had (UK022). The rule is
  "V4 never removes a protection V3 has": the phrase reading inherits V3's rule index.
* The suite forced onto V4 found four product decisions of earlier gates that the first V4 broke (a channel is never named by its values alone; a header that says something NINFA knows is never
  read as another thing from its values; a repeated code is asked about; the dependency scope of the older gates) - they are tests of V4's own now.
* **The model-layer tests are V4-aware** (see the architecture note, "How the tests know which engine reads"). The suite forced onto V4 had 46 failures, all tests of the semantic layer asserting
  that the model WAS asked about a column V3's rules cannot read. Under V4 that column is read from its values, so the model is rightly not asked. The tests now say which engine they speak of:
  `rules_engine` runs a test under both engines, `rules_v3_only` marks the ones whose premise is a V3 gap, and `test_smart_import_ai_with_each_engine.py` is the V4 side (a gap neither engine
  closes, V4 resolving what V3 sent to the model, the layer off). No assertion about safety was weakened and the application was not changed for them.
* The vocabulary is written by hand and maintained: `VERSION` is stamped, a test forbids two fields claiming one phrase and forbids copying the benchmark's held-out words. It was written AFTER the
  held-out list had been read in the benchmark source (disclosed), so independence rests on that test, on the unseen-file `holdout` split and on the problem corpus, not on blind authoring.
* Dependencies grow by RapidFuzz alone.
* **All evidence is synthetic.** ADR 0054's real-file gate is not replaced by this ADR; the engine ships dark so that the first real files are read under V4 deliberately, after the merge, in
  the pilot's own runtime.

## Alternatives considered

* **Sentence embeddings / a local model** (rejected by the brief, and unnecessary: the gain is in spelling, glueing, values and relations, none of which needs semantic similarity).
* **DuckDB as the reader of record for CSV.** See the table above.
* **Keeping the experimental engines in the product "for later".** A code path nobody intends to run is a liability; the evidence and the history are kept instead, and the boundary test makes
  re-adding them a deliberate act.
* **Pandera for validation.** The importers already refuse a bad row; the gap was only the early, per-column check, which is 60 lines (`validate.py`).
* **Making V4 the default now.** Not without a pilot on a real file, as for every reader of customer data in this codebase.

# Smart Import V3 - intelligence benchmark

A measurement, not a gate. It says how often Smart Import V3 reads a document the way a careful
person would, and - above all - how often it is **sure and wrong**.

```
cd services/api
python -m tests.benchmarks.smart_import_v3                 # ~5 minutes (use --no-memory for ~2)
python -m tests.benchmarks.smart_import_v3 --only L07 --no-write      # a few documents, console only
python -m tests.benchmarks.smart_import_v3 --write-corpus ./corpus    # also write every document
```

Output: a console summary, `tests/benchmarks/results/smart-import-v3-benchmark-v1.json`
(machine-readable, one record per document) and `docs/benchmarks/smart-import-v3-benchmark-v1.md`
(the report). `manifest.json` (next to this file) is the truth, one entry per document.

Nothing is read from or written to a database, nothing leaves the process, **no model is called**:
the optional assistant (`IMPORT_UNDERSTANDING_PROVIDER`) stays `unconfigured`. The later comparison
"deterministic vs deterministic + assistant" is meant to reuse this corpus unchanged.

## What is measured, and against what

| Piece | File | Role |
|---|---|---|
| Documents | `corpus_labor.py`, `corpus_bookings.py`, `corpus_costs.py`, `corpus_office.py` | real `.xlsx` / `.csv` bytes, drawn with openpyxl / csv; deterministic (same bytes, same hash) |
| Drawing | `draw.py`, `cols.py`, `pool.py` | a tiny DSL that tracks, WHILE drawing, the row of the header, of the first record, the number of records |
| Truth | `model.py` (`Golden`) | what a careful person would say about each document, written next to the document |
| System under test | `observe.py` | `UnderstandingService.understand` - the call the `/import-understanding` route makes - run in process |
| A person answering | `dialog.py` | gives the truth's answers round after round, as the product's one-question-at-a-time screens do |
| Verdicts | `score.py`, `metrics.py` | findings in the requested categories, severities P0-P3, per-domain and total numbers |
| Report | `report.py`, `interpretation.md` | everything computed, except `interpretation.md` (hand-written) |

### The truth is independent of the system

* it is written by hand from what was put in the file (the row a header sits on, the columns that
  are personal data, the questions a person would really have to answer) - never from what Smart
  Import answers;
* the scorer receives it only as plain JSON (`manifest()` -> `golden_from_json`) and imports none of
  the system's lexicons or rules;
* `corpus.validate()` reopens every generated file with openpyxl / csv - never with Smart Import's
  readers - and checks the truth against it (header cells, first record, personal values). A failure
  there is a bug of the benchmark, and the run stops.

### Outcomes the truth can ask for

`READY` import with no question - `ASK` import after the listed questions - `NOT_AUTOMATIC` never
silently (a question, manual matching or a refusal are all right) - `REJECT` refuse (manual matching
or a blocker) - `WARN` the document contradicts itself: a block, a question, or going on WITH the
contradiction shown as a warning are all right; going on without it is not.

`tolerated` questions are judgement calls the truth does not penalise (for example asking the
person to confirm a department that the title already states). Every one is explained in the
document's `note`.

### The headline metric

**False automation**: a document offered as *automatic* (level READY, no question, no blocker -
what the person sees as a summary and one button) whose reading differs from the truth in a
business-critical field (kind of data, table, period/date, department, hours, booking id,
check-in, check-out, channel, revenue, document number, supplier, net amount) - or which should
never have been automatic at all. A needless question is a small defect; an automatic import that
is wrong is a serious one.

### Adding a case

Write a function in the right `corpus_*.py` with `@REGISTRY.case("slug", "tag", ...)`, draw the
document with `Sheet` / `write_table` (or describe its columns with `Col`), and build the `Golden`
from the references the drawing returns. Never read a lexicon of Smart Import to decide the truth.
`python -m pytest tests/test_smart_import_benchmark.py` checks the corpus against its own truth.

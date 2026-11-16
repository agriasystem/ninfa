# ADR 0053: The model is asked only when it can change what a person is shown

Status: accepted (Smart Import OpenAI ASSIST - UX and efficiency V1.1). No migration, no dependency, no
change to FULL / PARTIAL / DELTA, to Source Learning's authority, to the Decision Engine, to Mia or to
the UI. `SMART_IMPORT_AI_MODE` stays `off` and the vocabulary certainty of
[ADR 0052](0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself.md) stays
withdrawn. Nothing here makes anything certain that was not.

## Context

The first run of the real model (V1) was safe and intelligent, and slow and chatty: 283 calls, 10 s
each on average (p95 21 s, 5 timeouts), 235 questions on the challenge files where the rules asked 121.
The V1.1 work classified every one of those calls and every question the model added, from the
recording of the real answers (no new call), before changing anything:

* **The questions were not noise.** Of the 146 the model added, 139 (95%) each replaced a person's
  manual matching of a whole file (115), replaced a worse question the rules would have asked (22)
  or protected a measure (2). 90 of the 97 files that stopped being manual matching cost ONE question.
  The noise was 7: a question about a "rooms" column on a file the rules already read as READY, whose
  column held `1` in every row - exactly what the import assumes when the column is absent.
* **A good part of the calls changed nothing.** 29 were on files that were already READY, 5 on files
  BLOCKED for a reason no column name can lift, 23 could only say "I agree" (they served the
  certainty that had been withdrawn), 51 were about the other half of a pair that the sibling rule
  (ADR 0051) already asks about without any model, and the files whose only gap was an amount were
  asked about something no model ever places (these groups overlap: 283 calls became 174).
* **A source a person had confirmed was still asked about.** 13 of the 55 files of a recognised source
  asked the model again.
* **A personal value on the page.** One adversarial file (`ADV09`) showed the browser a
  personal value that a spreadsheet had used as the name of a column: the header is the column's
  identity all the way to the import, and the last gate that masks personal data deliberately never
  touches headers.

## Decision

1. **A header that is itself a personal value is made safe where the labels of a table are made.**
   `structure._build_columns` (and the plain reader of the V2 path) replaces a header cell that holds
   an e-mail address, a telephone number, a tax code or an IBAN by `Colonna X`, the word it already
   gives an empty header. The answer, the decision the browser sends back and the import's own reading
   of the file are then the same safe word, and the column keeps its place and its values. The shapes
   live in a leaf module (`personal_shapes`) that `redaction` uses too, so the lowest layer and the
   last gate read personal data by the same rules. `PII visible in the browser: 0`, with the model off
   and on.
2. **A model is asked only when it can change what a person is shown.**
   * not when the rules alone already say READY (it can only add a question), nor BLOCKED for a
     reason no column name lifts (no table, a grid that is not hours, gross amounts, mixed formats);
   * not about a gap only money could fill (a model never places money);
   * not about a column the rules placed unsure unless its reading could make it certain - which, with
     the certainty withdrawn, it cannot;
   * not about the other half of a pair: ADR 0051's rule asks about it with no model.
3. **A reading that changes nothing is neither applied nor asked about** (`is_immaterial`, any model):
   the field is *descriptive* (`DomainSem.descriptive`: `guests`, `room_type`, `rate_plan` - stored,
   read by no analysis, snapshot or decision), or it has an assumed value when absent and the column
   holds exactly that value in every row (the rooms of a booking, one). One row that says anything
   else and the question is back.
4. **A source a person confirmed is not read by a model again**: it follows from (2) - a recognised
   source's rules-only reading is READY - and is pinned by a test over the 11 families x 8 versions.
5. **`low` reasoning is the default** (`SMART_IMPORT_OPENAI_REASONING=low`). `gpt-6.1-sol` accepts
   `low`, `medium`, `high`, `xhigh` and `max` - not `none` or `minimal`. Measured on 50 documents x 5
   settings on the real model: `low` reads as well as `medium` and takes about 40% less time.
6. **The compact way of asking is measured and NOT adopted**: leaving out the columns NINFA has already
   placed cuts the tokens the model writes by a third and its cost by a sixth, and did not make it
   measurably faster (the API's own drift between two runs of the same setting was larger than any
   gain). It stays as a variant the efficiency benchmark can ask for.

## Result (the real model, 545 synthetic documents, the certainty withdrawn)

[The report](../../benchmarks/smart-import-openai-assist-v1-1.md) has every number.

| | Rules | V1 | **V1.1** |
|---|---:|---:|---:|
| Unsafe READY / wrong-domain READY / PII sent / PII in the browser / scope violations | 0 | 0 (PII in the browser: 1) | **0** |
| Challenge: manual matching | 155 | 58 | **58** |
| Challenge: READY with no question | 19 | 12 | **19** |
| Challenge: mapping recall | 82.6% | 92.5% | **90.3%** |
| Challenge: questions shown | 121 | 235 | **227** |
| Questions the model added that were useful | - | 95% | **100%** |
| Model calls | 0 | 283 | **174** |
| Calls on a source a person had confirmed (11 families x 7 versions) | - | 25 (13 of 55 recognised files) | **2 (0 of 55)** |
| Call latency p50 / p95 | - | 9.4 s / 20.9 s | **4.3 s / 9.2 s** |
| Timeouts | - | 5 of 283 (1.8%) | **1 of 173 (0.6%)** |
| Cost at list price | - | $2.23 | **$1.18** |

## What it costs, honestly

* **Mapping recall on the challenge files falls 2.1 points (92.5% -> 90.3%)**, and nothing else a person
  sees changes: the 51 calls about the other half of a pair used to relabel the column that the sibling
  rule's question is already about. Replaying the V1.1 gate alone at V1's reasoning gives 89.8%: the
  fall is the gate's, and `low` gave back a little. It is still 7.7 points above the rules.
* **The number of questions barely moves (235 -> 227).** It is not noise to cut: 114 of them each
  replace a person's manual matching of a whole file, and 90 of those 97 files cost ONE question.
  Cutting more needs a new way to be certain, which ADR 0052 has just shown is not free.
* **No question about a field that does not matter** is now a guarantee, not a hope: 7 -> 0 on READY
  files, tested.

## What is not claimed

The corpus is synthetic and each number is one draw of a model that is not deterministic (the same
setting run twice differed by 2-3 s at p95). The price per token is a list price read on the web. The
timeout of 25 s is production's own: one call in 173 still reached it, and fell back to the rules.

# 0037 — Closing two targets with evidence: label context, the scorer's gap, an oracle review

## Context

Universal Understanding 2 (ADR 0036) left two explicit targets open: required mapping precision 99.40 % (target 99.5 %) and 20 unnecessary questions on the
official benchmark (target 12). The easy ways out are the wrong ones: removing claims, lowering the metric's bar, or labelling every remaining
question "by design". This ADR records what was done instead, and the one thing that went wrong on the way.

## Decisions

1. **The lines above a table are read by their label** (`document_understanding/context.py`). A `label: value` line has a kind given by the label
   (department, period, hotel, person, customer/supplier, note) or none; the value never decides. Only a department label gives the department of the rows
   ("Reparto: Spa"); the same word after "Nota:", "Cliente:", "Responsabile:" is not a department. A stated department is not a guess and is not confirmed
   again. A block of such lines is no longer mistaken for a tiny table that takes the real table's preamble (`structure._is_label_block`).
2. **The document date and the registration date of a register are two rules, not two candidates for one**. The importer's own alias "Data registrazione" is
   left to the registration rule: as an exact name it tied with the document date and the first column won (a false automation, found by the probes).
3. **A column of words is not asked on top of its words.** The status of a booking is promoted once its words are known, and not asked as a column while the
   words are being asked.
4. **The scorer counts what the person's answers establish** (`_extended`): "this amount is the NET" turns the ambiguous bare amount into the net. A
   demonstrated gap (the new test fails on the old scorer), applied to the official corpus too, with the golden recording the column. The definition of
   the metric did not change.
5. **An oracle review, case by case, instead of a number.** The questions of the official corpus that earlier gates decided to ask (bare amounts, hotel
   codes, look-alike columns, loose names, reversed dates, a wrong card) become *tolerated* kinds of the documents' goldens, each with its class, reason, the
   earlier document that decided it and the test that pins it (`oracle_review.py`, verified by `test_oracle_review.py`). A question with no justification
   (`L62`) is not reviewed away.
6. **Claims are reported as all / certain / tentative**, after the answers and in the first answer. The product risk is the certain claims of the first
   answer.
7. **30 probes** of these capabilities join Benchmark V2 (with their counter-examples) so that they are measured on documents that can be split into dev
   and holdout.

## What was tried and not done

* `UB104` (a reference that repeats) is not dropped: the same rule that asks for a bare `Codice` over one repeated code pins it.
* Hotel codes, status letters and cost categories are not promoted: see `docs/benchmarks/smart-import-v3-universal-understanding-2-1.md`, section 5.
* `L62` (a person-labelled column of departments) stays: it sits on the personal-data lock.

## Consequences

* The precision target is met by correcting the scorer, and the report says so; the engine's tentative claims on truth-ambiguous fields remain.
* The raw question count of the old oracle is kept next to the real one (16 and 1).
* A rule that splits a vocabulary rule can create a tie with an exact alias: the probes are the way to find it. Every new rule has a counter-example.

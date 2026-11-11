# Pilot Reliability V1.2: what was measured

Engine at `f1a4f5b` against the engine of this gate. The optional assistant stays off. Neither the scorer nor any
hand-written truth was changed. See [same-day-revisions-v1.md](../architecture/same-day-revisions-v1.md) for what the gate
does and [ADR 0039](../architecture/adr/0039-same-day-revisions.md) for why.

The only change to what Smart Import understands is one line of the personal data guard (below): everything else in this
gate happens after a file is understood. So the official corpora are a regression check here, not evidence for the gate.

## The official corpora did not move

| | Benchmark V1 (240) | Universal Understanding V2 (432, 417 scored) |
|---|---|---|
| Documents whose answer moved | **0** | **0** |
| Required recall | 99.80 % (1022/1024) | 100 % (1802/1802) |
| Required precision | 99.80 % (1022/1024) | 99.61 % (1802/1809) |
| Required precision, READY claims only | 100 % (1019/1019) | 100 % (1802/1802) |
| Zero-question rate, valid files | 93.25 % (152/163) | 95.05 % (288/303) |
| READY | 154 (64.17 %) | 292 (70.02 %) |
| ASK | 34 (14.17 %) | 67 (16.07 %) |
| MANUAL | 40 (16.67 %) | 44 (10.55 %) |
| BLOCKED | 12 (5.00 %) | 14 (3.36 %) |
| False automation | 0 | 0 |
| P0 | 0 | 0 |
| PII values leaked | 0 | 0 |

The product target of 99.9 % required precision is **not reached on every claim** (99.80 % and 99.61 %). It holds on what is
imported automatically (100 %), which is the condition this gate is measured on.

## With no card, and with no room count

| | |
|---|---|
| Documents read with no card, both corpora | 672 |
| **Wrong kind AND READY** | **0** |
| Documents whose level or kind moved against V1.1 | 0 |
| Bookings without a room column, holdout (60 documents) | READY 51 -> 50, false automation 0, critical field wrong 0, PII 0 |
| The same, holdout + dev (121 documents) | READY 101 -> 98, false automation 0, critical field wrong 0, PII 0 |

## New: files shaped like a real export

`python -m tests.benchmarks.aurora_like` (14 documents; `tests/test_smart_import_aurora_like.py` pins them). Title rows, a
counter above the table, guest contacts, notes, a summary sheet. The truth of each was written before running the engine,
from one question: if NINFA decided this file alone, could it be wrong about what is on the books?

| Variation | Documents | Expected | Result |
|---|---|---|---|
| A status word NINFA does not know (`Modificata`, `Modificato`, `Variata`, `Da confermare`) | 4 | one question, on that word | as expected |
| `Modificata`, and cancelled rows that keep their money | 1 | one question | as expected |
| `Modificata`, with no way of saying cancelled in the file | 1 | one question | as expected |
| Two unknown words | 1 | one question, on both | as expected |
| Only known words, Italian or English | 2 | no question | as expected |
| A real column: `Modificata` (yes/no), `Modificata il`, `Ultima modifica`, `Modificato da`, `Versione` | 5 | no question, nothing claimed from it | as expected |

False automation 0, needless questions 0, missed questions 0, claims on those columns 0. It is a small corpus and it was
written in this gate: it pins behaviour, it does not validate a rule.

**What it found:** the first run failed on `PII leaked`. A column `Modificato da` with the same two people on every row, and a
header that says nothing about a person, had its names sent to the page as examples: the guard asked for three distinct
values before believing a column held names. A given name now says so whatever the number of distinct values. No document of
the official corpora moved, and two-value columns that are nobody ("Front Office", "Non Rimborsabile") stay nobody.

**What it leaves:** account logins (`mverdi`, `operatore1`) in a column with a neutral header still reach the examples, on the
screen of the person who uploaded the file. They are not stored and they do not look like a person. Not fixed here.

## Do questions ever ask about a column that changes nothing?

Every question of both corpora, by the field it is about: all of them are about a required field or the structure of the file,
with one exception, the words of `cost_category` (14 documents). That field is optional, but the answer writes the category of
a line, which is what the cost detector compares, so it changes the result: it is not the case the gate asked to remove.

## `Modificata`

| | File 01 | File 02 |
|---|---|---|
| What it is | a **value of the `Stato` column**, not a column | the same |
| Type | text | text |
| Position | 16th of 17 columns, between `Valuta` and `Note` | the same |
| Values of the column | `Confermata` 88, `Modificata` 5, `Cancellata` 3 | 48, 3, 1 |
| Share of on-books revenue | 5.9 % (2.148 of 36.578 EUR) | 5.9 % (1.333 of 22.779 EUR) |
| Revenue of those rows | all positive | all positive |
| Revenue of the cancelled rows | all zero | all zero |

It decides whether a booking counts, so it cannot be ignored and its answer changes what is on the books: it stays a question,
asked once. Measured on the real files through the real flow: the answer is remembered, and the next files of that source ask
nothing (`02` in Excel, `02` in CSV, and the afternoon's copy of `01`).

A rule on the revenue signals would make `01` READY. It was not shipped: see ADR 0039.

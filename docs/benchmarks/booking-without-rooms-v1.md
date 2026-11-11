# A bookings file with no room count: what was measured

Engine at baseline `e6b3ee3` against the engine with `ConstantSpec.when_absent` (see
[importa-file-v1.md](../architecture/importa-file-v1.md)). The optional assistant stays off. Neither the
scorer nor any hand-written truth was changed.

## The official corpora did not move

| | Benchmark V1 (240) | Universal Understanding V2 (432, 417 scored) |
|---|---|---|
| Documents whose answer moved | **0** | **0** |
| Required precision | 99.80 % (1022/1024) | 99.61 % (1802/1809) |
| Required precision, READY claims only | 100 % (1019/1019) | 100 % (1802/1802) |
| Required recall | 99.80 % (1022/1024) | 100 % (1802/1802) |
| Zero-question rate, valid files | 93.25 % (152/163) | 95.05 % (288/303) |
| READY / ASK / MANUAL / BLOCKED | 154 / 34 / 40 / 12 | 292 / 67 / 44 / 14 |
| False automation | 0 | 0 |
| P0 | 0 | 0 |
| PII values leaked | 0 | 0 |

Every figure is the same before and after. **That is the regression result, not evidence for the fix**: no
document of these corpora has a booking that lacks only the room count. It also means the product target of
99.9 % required precision is **not reached on every claim** (99.80 % and 99.61 %): it holds on what is
imported automatically (100 %).

## The fix, on documents nobody looked at to write it

`python -m tests.benchmarks.booking_without_rooms` takes every bookings document of V2 with a column of rooms,
and reads it twice: as it is, and with that column mechanically taken out.

| | Holdout | Holdout + dev |
|---|---|---|
| Documents | 60 | 121 |
| READY with the column | 51 | 101 |
| READY without it | 50 | 98 |
| False automation | **0** | **0** |
| Critical field wrong on a READY | **0** | **0** |
| Room count other than 1 on a READY | **0** | **0** |
| PII leaked | **0** | **0** |
| Exceptions | 0 | 0 |

One document could not be transformed mechanically (`UB060`: a CSV dialect the tool's own splitter does not
handle) and is left out. The READY that are lost fall back to a question or to matching by hand, never to a
wrong import. Two of the three lost in the wider run have a two-level header, whose shape the removal disturbs;
the third has a summary block below the table. They were not studied: tuning to them would undo the holdout.

## With no card: the kind of data stays right

The page reads every file with no card (`importa-file-v1.md`), so a rule that relaxes a requirement of one kind
could make another kind's file look complete. Both corpora, 672 documents, read the way the page reads them:

| | |
|---|---|
| HIGH verdicts on the 574 positive documents | 544, all right |
| MEDIUM verdicts | 15: 14 right; the wrong one ends MANUAL |
| **Wrong kind AND READY** | **0** |
| READY on the card, not READY without it | 0 |
| Documents whose level moved against the measure before this change | 1 |

The one that moved is `L66`: a real bookings file with no room count that the benchmark uploads on the staff
card. Read with no card it is what it is, and it goes from MANUAL to READY, as bookings. Five READY among the 98
negatives and unsupported files are all real files of their own kind: three uploaded on a wrong card, two whose
totals do not add up, where the summary says so.

## What was caught

A first version also taught the status vocabulary that "Modificata" means confirmed, because the file that found
the bug uses it. The official corpus has that very case as hand truth (`B23_status_modificata_is_ambiguous`) and
turned it into a false automation and a P0. It was withdrawn: "Modificata" stays a question, asked once and then
remembered for the source. A first version also listed the assumed room count among the fields read from the file,
which the scorer rightly flagged as a claim about a column that does not exist: it is now said apart.

# Remembered Scope Safety V1.2.2: what was measured

The engine at `88d8794` (Import Scope Semantics V1.2.1) against the engine of this gate. The optional assistant stays off.
Neither the scorer nor the truth of any corpus was touched.

## What the benchmarks can and cannot say here

Every corpus reads a file on its own, with no source behind it, so none can reach a remembered scope. They prove that
understanding a file did not move. The safety rule itself is proved by `test_remembered_scope_*.py` and by the smoke below.

## Smart Import, before and after

| | V1 corpus (240) | V2 corpus (417) |
|---|---|---|
| Documents whose answer moved | **0** | **0** |
| READY precision on committed fields | 100 % (1019/1019), same | 100 % (1802/1802), same |
| Zero-question rate on valid documents | 93.25 %, same | 95.05 %, same |
| False automation | 0, same | 0, same |
| P0 | 0, same | 0, same |
| PII leaked | 0, same | 0, same |
| READY / ASK / MANUAL / BLOCKED | 154 / 34 / 40 / 12, same | 292 / 67 / 44 / 14, same |

| Other corpora | Result |
|---|---|
| No card (672 documents) | none moved; READY on the wrong kind of data: 0 |
| Bookings without rooms, holdout / all | READY 51 -> 50 / 101 -> 98 without the column, same as before |
| Aurora-like (14 documents) | false automation 0, missed question 0, needless question 0, PII 0 |

## The smoke: real page, real API, real worker, throw-away database

Copies of the Hotel Aurora files, outside the repository, through `/importa-file` in headless Chrome.

**Bookings**, after one file answered "tutte" and remembered (3 marked):

| File | Question | Answer | Result |
|---|---|---|---|
| 01 without 5 | confirmation, 2 prenotazioni | no | nothing more marked, "non cambia nulla", no run; the job says `PARTIAL`, remembered `FULL` |
| the same again | none | | nothing moves |
| 01 without 6 | confirmation again, 3: the memory stayed | no, box ticked | nothing more marked; the memory is now a part |
| 01 without 6 again | none; the summary says 3 stay | "Il file le contiene tutte?", yes, box ticked | 6 marked; the job says `FULL`, remembered `PARTIAL`; the memory is complete again |
| 01 whole | none | | they all come back, revision 4 |

**Staff**, after one file answered "tutti" and remembered (281 to 199 planned hours):

| File | Question | Answer | Result |
|---|---|---|---|
| 04 whole | none | | 281 |
| 04 of Reception only | confirmation, in words about the plan | no | 281: the plan stays whole; the job says `PARTIAL`, remembered `FULL` |
| the same again | none | | nothing moves |

The earlier parts were run again and pass: same-day bookings, staff weeks, updated and overlapping plans, the cost register,
corrected rows, FatturaPA identical and refused, complete and partial files, hours worked. Browser errors: 0.

## `Modificata`

Unchanged: one question, about the word, before this one, answered once and remembered. No new heuristic.

## What this leaves

See [import-scope-semantics-v1.md](../architecture/import-scope-semantics-v1.md#what-this-leaves).

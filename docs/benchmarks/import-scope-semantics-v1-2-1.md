# Import Scope Semantics V1.2.1: what was measured

The engine at `575494c` (Pilot Reliability V1.2) against the engine of this gate. The optional assistant stays off. Neither
the scorer nor the truth of any corpus was touched.

## What the benchmarks can and cannot say here

Every corpus reads a file on its own, with no source behind it. The question of this gate needs a source with stored
records, so **no benchmark document can reach it**: they prove that understanding a file did not move, not that the new
semantics are right. Those are proved by `test_import_scope_*.py` and by the smoke below.

## Smart Import, before and after

| | V1 corpus (240) | V2 corpus (417) |
|---|---|---|
| Documents whose answer moved | **0** | **0** |
| READY precision on committed fields | 100 % (1019/1019), same | 100 % (1802/1802), same |
| Required recall | 99.80 %, same | 100 %, same |
| Zero-question rate on valid documents | 93.25 %, same | 95.05 %, same |
| False automation | 0, same | 0, same |
| P0 | 0, same | 0, same |
| PII leaked | 0, same | 0, same |
| READY / ASK / MANUAL / BLOCKED | 154 / 34 / 40 / 12, same | 292 / 67 / 44 / 14, same |

| Other corpora | Result |
|---|---|
| No card (672 documents) | none moved |
| Bookings without rooms, holdout | READY 51 -> 50 without the column, same as before |
| Bookings without rooms, all | READY 101 -> 98 without the column, same as before |
| Aurora-like (14 documents) | false automation 0, missed question 0, needless question 0, PII 0 |

## The smoke: real page, real API, real worker, throw-away database

Copies of the Hotel Aurora files, outside the repository, each changed in one way. Headless Chrome through `/importa-file`.

| File, in order | Questions | What happened |
|---|---|---|
| Bookings 01 (96 bookings) | `Modificata`, once | 96 current, analysis on revision 1 |
| 01 without 3 bookings | one: *tutte le prenotazioni?* | answered "tutte": 3 marked, 93 current, revision 2, analysis the same day, the first run still on revision 1 |
| the same again | none | no change, no revision, no run |
| 01 without 5 | none: remembered | 2 more marked; the summary said 2 before importing |
| 01 whole again | none | 0 marked, 96 current, revision 4 |
| Bookings 02, December | none | nothing touched |
| 01 of one channel only, on a new database | one, answered "una parte" | nothing goes, "non cambia nulla", the job says `PARTIAL` |
| 8 rows of 01 + 3 new | none: remembered | 99 current, nothing goes |
| Staff 04 | none | 281.00 planned hours |
| 04 of Reception only, answered "alcuni" | one | 281.00: the other departments stay |
| 04 without Housekeeping, answered "tutti", on a new database | one | 199.00: seven department-days stopped counting, the older file is kept |
| the same again | none | no new file |
| 04 with hours worked only | none | 199.00: the plan does not move; a new file, a change |

The earlier same-day smoke was run again and passes: bookings, staff weeks, updated and overlapping plans, the cost register,
corrected rows, FatturaPA identical and refused.

## `Modificata`

Unchanged. It stays one question, about the word, before this one, answered once and remembered. No new heuristic.

## What this leaves

See [import-scope-semantics-v1.md](../architecture/import-scope-semantics-v1.md#what-this-leaves).

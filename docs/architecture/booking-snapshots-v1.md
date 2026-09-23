# NINFA — Booking snapshots v1 (Gate 3)

Room inventory, the daily **"on the books"** snapshot of a data source, and the two ways a
snapshot can come to exist. **No pickup, velocity, trend, expected value, forecast, alert, impact,
priority, recommendation or decision is computed here**: those start in later gates. Snapshots
are the *raw material* those gates will read.

Migration `0005_booking_snapshots_metrics`. Code: `services/api/app/modules/snapshots/`. Entry
points: `ObservedSnapshotService` (`observed.py`) and `BookingSnapshotReconstructionService`
(`reconstruction.py`), framework-free and testable directly. No public API, worker task or
scheduler exists yet (authentication is a later gate); a future worker or authenticated endpoint
calls the services.

## The one rule: OBSERVATION is not RECONSTRUCTION

| | `OBSERVED` | `RECONSTRUCTED_APPROXIMATE` |
| - | ---------- | --------------------------- |
| What it is | what the canonical bookings said **when NINFA looked** | what NINFA can **infer today** about an earlier day |
| Made by | `ObservedSnapshotService.take_snapshot` | `BookingSnapshotReconstructionService.reconstruct` |
| `as_of_at` | the injected clock's now (UTC) | the exclusive end of the snapshot day (UTC) |
| Uncertainty | none (current statuses are known) | `uncertain_booking_count` / `uncertain_rooms` |
| Can it be replaced? | never | never (a different content raises a conflict) |
| Wins a key clash? | **yes**, always | no |
| Called "exact"? | no: it is evidence of what was seen, not of the past | no, and never "historical truth" |

Why they cannot be merged: the canonical `bookings` table keeps only the **current** state of
each booking (its dates, rooms, revenue, channel and status can have changed since), and
`room_inventory_daily` keeps only today's capacity. Nothing in it can say what the hotel's book
really looked like last March. A reconstruction is therefore always an *approximation*, even when
it happens to have no uncertainty at all, and it is **never promoted** to `OBSERVED`. Only real
observation, repeated day after day from now on, produces trustworthy history. This is visible
in the data (`origin`), in the code (two services, two code paths; a test proves that the observed
service can only produce `OBSERVED` and the reconstruction only `RECONSTRUCTED_APPROXIMATE`) and
in the tests (see ADR 0009).

## What a snapshot row is

One row per **data source × snapshot day × stay night**, in `booking_snapshots`:

| Column | Meaning |
| ------ | ------- |
| `data_source_id` (+ `workspace_id`, `property_id`) | the source the numbers come from. Sources are **never merged automatically** |
| `snapshot_local_date` | the *property-local* calendar day the snapshot is about |
| `as_of_at` | the instant (UTC, `timestamptz`) the state refers to |
| `stay_date` | the night described |
| `origin` | `OBSERVED` or `RECONSTRUCTED_APPROXIMATE` (`VARCHAR` + `CHECK`, like every enum) |
| `booking_count_on_books` | bookings (records) that occupy that night |
| `rooms_on_books` | rooms they occupy (a booking of 3 rooms adds 3 rooms and counts once) |
| `allocated_room_revenue_on_books` | the stay revenue **allocated** to that night (see below) |
| `rooms_available` | capacity **copied from the inventory at calculation time**; `NULL` if unknown |
| `occupancy_on_books` | `rooms_on_books / rooms_available × 100`, `NULL` if capacity unknown or 0 |
| `adr_on_books` | `allocated revenue / rooms_on_books`, `NULL` if there are no rooms on the books |
| `uncertain_booking_count`, `uncertain_rooms` | what could not be classified (reconstruction only) |
| `calculation_version` | version of the *rules* (`booking-snapshot-v1`), not of the application |
| `content_fingerprint` | SHA-256 of the content (below) |

The daily on-books metrics live **in the snapshot itself**: there is no separate metrics table and
no key/value (EAV) structure.

A row exists for **every** stay night of the requested range, also when nothing is booked: the
absence of bookings is data (`booking_count = 0`, `rooms = 0`, revenue `0.00`, ADR `NULL`).

## Stay-night semantics

A booking occupies the nights `check_in <= D < check_out`. **The check-out date is not a stay
night.** A booking with `rooms = N` adds `N` rooms to each of its nights.

## Which bookings count (observed status policy)

| Status | Counted in an observation |
| ------ | ------------------------- |
| `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT` | yes |
| `CANCELLED`, `NO_SHOW` | no |

The policy is explicit and closed (`OBSERVED_STATUSES`); no status is reinterpreted ("a cancelled
booking that may still be alive" does not exist).

## Revenue allocation

`Booking.room_revenue` is the revenue of the **whole stay**. It is spread over the stay's nights
and never added in full to each night. Money is handled in **integer cents** (no `float` anywhere;
a test scans the code for it):

- every night gets `total_cents // nights`;
- the indivisible remainder is handed out **one cent each to the earliest nights**, so the
  allocations always sum to exactly the stay revenue.

`100.00` over 3 nights → `33.34`, `33.33`, `33.33`. `0.01` over 4 nights → `0.01`, `0.00`, `0.00`,
`0.00`. The column is called *allocated* on purpose: it is a deterministic uniform allocation, **not
the nightly rate the property actually charged** (the canonical booking only knows the stay total).
A multi-room booking allocates the stay total (rooms multiply `rooms_on_books`, not revenue), so ADR
divides by rooms: a booking of 2 rooms worth 200.00 for one night has an ADR of 100.00.

## Occupancy and ADR

- `occupancy_on_books = rooms_on_books / rooms_available × 100`, two decimals, **rounded half up**,
  **not clamped**: 45 rooms on 40 available is `112.50` (an overbooking or a wrong inventory is
  information, not something to hide, and no alert is raised here).
- `adr_on_books = allocated_revenue / rooms_on_books`, two decimals, half up.
- Both are computed once, from integers (no intermediate rounding, no float), and stored: the stored
  value is what the fingerprint hashes.
- **`NULL` is not `0`.** Occupancy is `NULL` when `rooms_available` is `NULL` or `0` (no division by
  zero, no invented 0% or 100%); ADR is `NULL` when `rooms_on_books = 0` (never a fake `0.00`).
  The database enforces this pairing with `CHECK` constraints.

## Room inventory (`room_inventory_daily`)

`(workspace, property, stay_date)` → `rooms_available`, `rooms_out_of_order`, both `>= 0`, unique
per property and night. `rooms_total` was **not** added to `Property`.

- A night **without a row** means *capacity unknown*: the snapshot is still created, with
  `rooms_available = NULL` and `occupancy_on_books = NULL`. NINFA never invents a capacity.
- **`0` means the property was closed / had no sellable room** that night. It is a real value and
  is copied as `0` (occupancy is then undefined, `NULL`).
- `rooms_available` is used as declared; `rooms_out_of_order` is informational and is not
  subtracted from it.
- The repository (`RoomInventoryRepository`) offers `get_for_date`, `list_for_range` and
  `set_for_date` (an upsert). Editing the inventory later **never alters** an existing snapshot:
  the capacity was copied when the snapshot was calculated.
- Inventory has no history of its own: a reconstruction copies **today's** inventory, which is one
  more reason it is only approximate.

## Observed snapshots

```python
service = ObservedSnapshotService(session, TenantContext(workspace_id))
result = service.take_snapshot(property_id=..., data_source_id=...,
                               stay_date_start=date(2026, 3, 20), stay_date_end=date(2026, 7, 21))
# result.created / result.unchanged; a different content for a stored key raises
# SnapshotError with code BOOKING_SNAPSHOT_CONFLICT
```

Both dates are included. The caller **cannot** choose `as_of_at` or the snapshot day: `as_of_at` is
the injected clock's now (`Clock = Callable[[], datetime]`, default `datetime.now(UTC)`; tests inject
a fixed one), and the snapshot day is that instant's date **in the property's IANA time zone**
(`zoneinfo`). So 23:30 UTC on the 15th of March is already the 16th for a Rome property. A past
state cannot be faked.

Validation: the property must exist in the workspace, not be archived, and have a valid time zone;
the data source must be a `BOOKINGS` / `FILE_UPLOAD`, active source of **that property** (a
`COSTS`/`LABOR` source, another property's, another workspace's or an unknown one is refused; the
last two are indistinguishable). The range has a limit (731 days).

One observation per data source, snapshot day and stay night: rerunning the same day with the same
content is an **idempotent no-op** (the first `as_of_at` is kept); rerunning it after the bookings or
the inventory changed raises `BOOKING_SNAPSHOT_CONFLICT`, stores nothing (the whole run is atomic)
and never updates the stored row. The next local day observes again.

## Historical reconstruction

```python
service = BookingSnapshotReconstructionService(session, TenantContext(workspace_id))
result = service.reconstruct(property_id=..., data_source_id=...,
                             snapshot_date_start=date(2026, 1, 1), snapshot_date_end=date(2026, 3, 1),
                             stay_date_start=date(2026, 3, 20), stay_date_end=date(2026, 7, 21))
```

For the end of a property-local snapshot day (the **cutoff** `C`) a booking is on the books iff it
was made before `C`:

| Booking | At cutoff `C` |
| ------- | ------------- |
| `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT` | on the books once `booked_at < C` |
| `CANCELLED` with `cancelled_at` | on the books while `C <= cancelled_at`; not on the books after |
| `CANCELLED` **without** `cancelled_at` | **uncertain**: counted only in `uncertain_*`, never in the certain totals, never assumed present or absent |
| `NO_SHOW` | on the books until the check-in date has started; from the snapshot day of the check-in date on **uncertain** (a no-show cannot be known earlier and the row does not say when it was recorded) |

`cancelled_at` earlier than `booked_at` is impossible, so it is treated as unknown (uncertain), not
trusted and not dropped. Uncertain bookings are counted for the stay nights they belong to, in
`uncertain_booking_count` and `uncertain_rooms`; their revenue is **not** added to the certain
revenue. Every reconstructed row is `RECONSTRUCTED_APPROXIMATE`, even with `uncertain_rooms = 0`.

Other rules:

- **Half-open cutoff.** The cutoff is `[start of the local day, start of the next local day)`: the
  next midnight is *excluded*, never "23:59:59.999999". A booking made exactly at the next midnight
  belongs to the next day; a cancellation stamped exactly at it happened on the next day.
- **Only completed days.** A snapshot day whose end is still in the future cannot be reconstructed
  (`INVALID_RANGE`, reason `snapshot_date_not_completed`): that would be a prediction dressed as
  history. `as_of_at` of a reconstructed row is its exclusive cutoff instant (UTC).
- **An observation always wins.** If an `OBSERVED` row exists for a key, the reconstruction leaves it
  untouched and creates no parallel row (reported as `skipped_observed`). This follows from the
  unique key not containing `origin`.
- An existing reconstruction with the same content is a no-op; with a different content (a booking
  changed since) it raises `BOOKING_SNAPSHOT_CONFLICT`: nothing is silently refreshed or promoted.
- Zero-booking dates still get a row. A night with only uncertain bookings has `rooms_on_books = 0`
  and `uncertain_rooms > 0`.
- The result at a cutoff does not depend on which other days are requested in the same run.

### Reused by Gate 9

The two pure functions behind the table above — the on-the-books window per booking and the
stay-night overlap — are now **public**: `booking_certainty_window` and `stay_night_overlap` in
`services/api/app/modules/snapshots/aggregate.py` (the previous private names, `_windows` and
`_overlap`, remain as aliases; nothing here changed). Gate 9's OTA dependency detector calls them
directly, through `intelligence/distribution/temporal.py`, to reconstruct a property's historical
channel mix under the exact same certainty rule as this reconstruction — never a second, divergent
implementation of "on the books at cutoff `C`". Gate 3's own test suite was re-run unchanged before
and after the rename to confirm zero semantic change.

### Daylight saving time

The boundary is *defined*, not guessed: it is the earliest instant whose local date is `D`.

- ordinary day: local midnight;
- repeated midnight (clocks go back at 01:00 to 00:00, e.g. Havana, 2023-11-05): its **first**
  occurrence; the local day lasts 25 hours;
- midnight that does not exist (clocks jump 00:00 → 01:00, e.g. São Paulo, 2018-11-04): the instant
  of the jump; the local day lasts 23 hours;
- a whole calendar date that never existed (Samoa skipped 2011-12-30) is refused with
  `BOOKING_SNAPSHOT_LOCAL_DATE_DOES_NOT_EXIST`.

Consecutive days tile the time line with no gap and no overlap (tested for Rome, São Paulo, Havana
and Lord Howe, whose shift is 30 minutes). This is a different situation from Gate 2's naive
timestamps in a file, which are *rejected* when nonexistent or ambiguous: there NINFA would have to
guess the customer's intent; here the boundary of a day is a definition.

## Uncertainty

`uncertain_*` exists so that the reconstruction never has to choose between two fictions. The
reconstruction may say "3 rooms certainly on the books and 2 more that we cannot classify", never
"3 rooms". An observation has none (the `CHECK` `observed_has_no_uncertainty` enforces it).

## Immutability and fingerprint

`booking_snapshots` has **no `updated_at`** and a `BEFORE UPDATE` trigger that refuses every update
(`integrity_constraint_violation`): a snapshot is evidence, and a correction is a new calculation.
The trigger is justified because the property is cheap to state and check in the database (the same
reasoning as Gate 2's identity trigger) and it protects the evidence from any writer, not only from
these services. `DELETE` is **not** blocked: every foreign key is `RESTRICT` and retention belongs to
a later gate.

`content_fingerprint` = SHA-256 of the canonical JSON (sorted keys, fixed two-decimal money) of:
`origin`, snapshot day, stay date, data source, booking count, rooms, allocated revenue, copied
inventory, occupancy, ADR, uncertainty and `calculation_version`. It does **not** contain the row
id, `created_at`, `as_of_at` or any runtime metadata, so two runs that compute the same content have
the same fingerprint even at different instants. `50` and `50.00` are the same content; `NULL`
capacity and `0` capacity are different content. Changing a rule (allocation, rounding, status
policy) means a new `calculation_version`, and therefore a different fingerprint.

## Transaction and consistency

A run is **one transaction** owned by the service (pass a session with no uncommitted work, as for
the import): validate → take the per-data-source advisory lock → read the clock → read bookings
(one statement) and inventory (one statement) → calculate → compare with what exists → insert →
commit; any failure rolls the whole run back.

- **Advisory lock** `pg_advisory_xact_lock(hashtextextended(<data source id>, 0))`, defined once in
  `app/db/locks.py` and used by the booking import for its canonical write **and** by both snapshot
  services. So a snapshot never reads half of an import, and two runs on the same source never
  interleave: the outcome (create / no-op / conflict) is deterministic rather than a race decided
  by the unique constraint. It is transaction-scoped (released at commit/rollback, no leak) and
  per-database: there is no distributed locking. The lock is taken only *after* the property and the
  data source were validated for the tenant, so a caller cannot lock another tenant's key.
- The clock is read **after** the lock: every import committed before the lock is older than
  `as_of_at`, and none can commit between the lock and the reads.
- **`REPEATABLE READ` was evaluated and not used.** The isolation level cannot be changed once the
  caller's transaction has started, which is the normal situation for a service working inside an
  existing session (tests, future composed flows); the lock already gives the guarantee that matters
  (bookings only change under it); and `REPEATABLE READ` would add serialization failures needing
  retries. The inventory is a configuration table read in a single statement.
- `ON CONFLICT DO NOTHING` on the unique key is the last line of defence against a writer that
  bypasses the lock; a key skipped there is treated as a conflict and rolls the run back.

## Source scoping and tenant integrity

Every snapshot belongs to exactly one data source; the repositories always take a `data_source_id`
and the curve never mixes sources (two `BOOKINGS` sources of one property have separate snapshots
even though they share the property's inventory).

Composite foreign keys (all `RESTRICT`, see ADR 0006):

- `room_inventory_daily (workspace_id, property_id)` → `properties`;
- `booking_snapshots (workspace_id, property_id)` → `properties`;
- `booking_snapshots (workspace_id, property_id, data_source_id)` → `data_sources`.

A cross-tenant snapshot or inventory row is impossible even with raw SQL. Unique keys:
`room_inventory_daily (workspace, property, stay_date)` and
`booking_snapshots (workspace, data_source, snapshot_local_date, stay_date)`.

Other `CHECK`s: counts and money `>= 0`; `rooms_on_books >= booking_count` (a booking has at least
one room) and no booking means no room (same for the uncertain pair); ADR defined ⇔ rooms on the
books; occupancy defined ⇔ capacity known and positive; `origin` in the two values; version not
blank; fingerprint is 64 hex characters.

## Indexes

| Index | Access path |
| ----- | ----------- |
| `uq_room_inventory_daily_workspace_id_property_id_stay_date` | inventory of a property, a night or a range |
| `uq_booking_snapshots_data_source_snapshot_date_stay_date` | the key; also "all the nights of one snapshot day" (its column order makes a separate snapshot-day index redundant) |
| `ix_booking_snapshots_booking_curve` `(workspace, data_source, stay_date, snapshot_local_date)` | the booking curve of one stay night, already in snapshot-day order (a test asserts the plan needs no sort) |

## Booking-curve data access

`BookingSnapshotRepository.list_curve_for_stay_date(data_source_id, stay_date)` returns, for one
stay night of **one** data source and ordered by `snapshot_local_date`: `snapshot_local_date`,
`as_of_at`, `rooms_on_books`, `allocated_room_revenue_on_books`, `rooms_available`,
`occupancy_on_books`, `origin`, `uncertain_rooms`. Observations and reconstructions can both appear
and stay distinguishable through `origin`. It computes **no** pickup, velocity, trend, expected or
forecast value. Other reads: `get_for_stay_date`, `list_for_snapshot_date`.

## Performance

Bookings are read once (`check_in <= last night AND check_out > first night`, only the columns the
calculation needs), inventory once, existing keys once, and rows are inserted in batches: the number
of statements does not depend on the number of bookings or nights (a test runs 1000 bookings × 365
stay dates with a bounded statement count and checks the numbers against a naive calculation). The
reconstruction applies each booking's contiguous on-books window as a difference array per stay
night, so its cost is `bookings × nights + cells`, not `bookings × cells`. Limits: 731 days per range
and 200 000 stored rows per reconstruction.

## Error codes

| Code | When |
| ---- | ---- |
| `BOOKING_SNAPSHOT_CONFLICT` | a stored snapshot with different content exists for the key (HTTP-style status 409) |
| `BOOKING_SNAPSHOT_INVALID_PROPERTY` | property unknown/foreign, archived or with an invalid time zone (`details.reason`) |
| `BOOKING_SNAPSHOT_INVALID_DATA_SOURCE` | `not_found`, `wrong_domain`, `wrong_source_type`, `inactive`, `property_mismatch` |
| `BOOKING_SNAPSHOT_INVALID_RANGE` | `start_after_end`, `too_long`, `too_many_rows`, `snapshot_date_not_completed` |
| `BOOKING_SNAPSHOT_LOCAL_DATE_DOES_NOT_EXIST` | a calendar day skipped by the property's time zone |

Messages and details carry ids, dates, constraint-level facts and counts only, never booking
content.

## Golden scenario

`tests/fixtures/snapshots/` extends the Gate 2 golden world ("MASSERIA NINFA DEMO"): the 16
bookings plus a synthetic addendum (a checked-in multi-room booking, a checked-out one, a no-show, a
cancellation without date, a booking on a closed night, revenue that does not divide evenly), a
declared inventory with a closed period and an undeclared one, one observation and a reconstruction
of 207 days × 124 nights. The expected result was computed **independently of the application code**
(`generate_masseria_snapshots_expected.py`, standard library only), with 39 hand-checkable probes and
a checksum of the whole grid. It goes from BOOKINGS + INVENTORY to SNAPSHOTS and nothing further.

## Consumers: the Expected Engine (Gate 4)

The Expected Engine ([expected-engine-v1.md](expected-engine-v1.md)) reads these snapshots and is
why the origin distinction matters: an Expected baseline must start from an **OBSERVED** target
(the database refuses a reconstruction as a target), prefers OBSERVED comparables, uses a
RECONSTRUCTED_APPROXIMATE one only to complete a small observed sample, penalises it in the
confidence, and never uses one with `uncertain_rooms > 0`. It needs exactly one snapshot per
(stay date, lead time) in a data source, which the unique key guarantees, and it reads them by exact
`(snapshot day, stay date)` keys through `BookingSnapshotRepository.list_by_keys` (the unique key's
index). Migration `0006` adds one unique constraint to `booking_snapshots`,
`(workspace_id, property_id, data_source_id, id, origin)`, used only as a foreign-key target.

## Consumers: Revenue Decision Detection (Gate 5)

The two revenue detectors ([revenue-decisions-v1.md](revenue-decisions-v1.md)) build **curve pairs**
from these snapshots: two snapshots of the *same* stay date (an anchor and the one 7 snapshot days
earlier, or the final one taken on the stay date), read by exact keys with
`BookingSnapshotRepository.list_by_keys` and `list_by_ids` (both return the ADR on books as well).
A pair is OBSERVED only if both snapshots are, and is discarded if either has `uncertain_rooms`.
The origin distinction is what keeps a pickup between an inference and a fact from being presented
as a measurement. Gate 5 adds no column, table or migration to snapshots.

## Consumers: Cost CPOR Anomaly Detection (Gate 7)

The cost detector ([cost-cpor-anomaly-v1.md](cost-cpor-anomaly-v1.md)) uses ONE kind of snapshot as
the denominator of the cost per occupied room: the **lead-time-0** snapshot of each stay night
(`snapshot_local_date = stay_date`), read for a whole month by exact keys with
`BookingSnapshotRepository.list_by_keys`. The sum of their `rooms_on_books` is an **operating proxy**
of the occupied room nights, not a certified occupancy. It treats a **missing** snapshot as unknown
(never as zero rooms, so the month is incomplete), refuses a day with `uncertain_rooms` and admits
`RECONSTRUCTED_APPROXIMATE` snapshots (with no uncertainty) at a lower provenance than `OBSERVED` ones.
Gate 7 adds no column, table or migration to snapshots.

## Known limits (intentional)

- Reconstructions are approximations (current booking state, today's inventory).
- One observation per data source and local day: intraday observations do not exist in V1.
- A change of `calculation_version` for an already stored key is a conflict, not a migration path;
  recalculating history under new rules is a decision for a later gate.
- No retention or deletion policy for snapshots yet.
- `rooms_out_of_order` is stored, not used.
- No pickup, curves interpretation, alerts or decisions are computed here: the Expected baselines
  (Gate 4), the revenue evaluations (Gate 5) and the cost per occupied room (Gate 7) read these
  snapshots; a persisted decision is a later gate.

# NINFA — OTA dependency v1 (Gate 9)

`REV_OTA_DEPENDENCY`: how much of a property's *next 30 days* of room-night business is already
concentrated on OTA channels, and is that concentration structurally high or rising sharply above
comparable history? Code: `services/api/app/modules/intelligence/distribution/`. Entry point:
`OtaDependencyService.evaluate(property_id, booking_data_source_id, as_of_local_date)`. No table,
migration, API endpoint or worker task was added; the head stays `0008_labor_ingestion`.

## What this measures, and what it does not

**OTA dependency is CONCENTRATION of the distribution mix, never channel PERFORMANCE.** NINFA does
not decide whether Booking.com converts well, whether Expedia is profitable, or whether a channel
should be closed — it only measures what share of certain, classified room-nights on the books for
the next 30 days is OTA. There is no commission assumption (no 15/18/20%), no conversion, CAC,
ROAS, cancellation-rate-by-channel or rate-parity computation, no channel-performance ranking, and
no recommendation ("push direct", "close Booking.com"). The optional revenue figures it can expose
are a gross **exposure**, never a saving, a loss or an avoidable cost (Part "Optional revenue
evidence" below).

## The 30-day forward window

The target of an evaluation is `(property, booking_data_source, as_of_local_date)`, never a single
stay date. `as_of_local_date` is **always given explicitly** by the caller; the service has no
clock (`datetime.now()`/`date.today()` never appear below it). The target stay window is
`[as_of_local_date, as_of_local_date + 29]` — exactly 30 stay dates, a versioned policy
(`FORWARD_STAY_WINDOW_DAYS = 30`). A single night is too noisy (one wedding block or one no-show
skews it completely); 30 days smooths daily noise, spans several weekdays, and stays close enough
to be operationally meaningful (a quarter or a year would already describe strategy, not an
imminent booking window).

## Channel classification (conservative, no fuzzy matching)

`BookingChannel` already carries a `channel_type` (`DIRECT`, `OTA`, `TOUR_OPERATOR`, `AGENCY`,
`CORPORATE`, `OTHER`) and an `is_verified` flag (Gate 2, `app.modules.bookings.models`). Gate 9
never writes to it; it classifies every channel of the property **in memory, on every evaluation**,
into one of four coarser groups — `OTA`, `DIRECT`, `OTHER`, `UNKNOWN` — with this priority:

1. **CANONICAL_SOURCE** (confidence 100) — `channel_type` when `is_verified` is true: the
   customer's own decision, respected as-is (`TOUR_OPERATOR`/`AGENCY`/`CORPORATE` all collapse to
   `OTHER`; REV_OTA_DEPENDENCY does not distinguish a wholesaler from a corporate account).
2. **DETERMINISTIC_RULE** (confidence 95) — an UNVERIFIED `channel_type` is Gate 2's own *hint*
   (its own tiny built-in list at import time), not a confirmed fact, so it is **not** treated as
   reliable here: this step re-classifies from scratch, on the channel's own `normalized_name`,
   against a small, high-precision, **exact** dictionary (`app.modules.intelligence.distribution.
   channels`): `booking com`, `booking`, `expedia`, `hotels com`, `agoda`, `airbnb`, `vrbo`,
   `hostelworld` → OTA; `direct`, `diretto`, `website direct`, `sito diretto`, `phone direct`,
   `walk in` → DIRECT; `wholesaler`, `tour operator`, `corporate`, `agency` → OTHER. Never a
   substring, never a fuzzy/edit-distance match: "Booking Engine" is never "Booking.com", and a
   generic label ("web", "online", "reservation") is deliberately absent, so it stays UNKNOWN.
3. **UNCLASSIFIED** (confidence 0) — anything else: `UNKNOWN`. A generic or ambiguous name is
   never guessed.

The confidences (100/95/0) are **provenance quality**, not a statistical probability.

## Channel mix as-of: reusing Gate 3's own temporal rule

The mix must reflect what was known **at** `as_of_local_date`, never today's canonical state. Gate
3 already answers "was this booking on the books at an earlier cutoff" for its own snapshot
reconstruction; Gate 9 reuses that exact rule rather than writing a second one.
`app.modules.snapshots.aggregate.booking_certainty_window` (and `stay_night_overlap`) were made
public, unmodified, specifically so `intelligence.distribution.temporal` can call them directly at
a single cutoff (`booking_certainty_at`) — Gate 3's own reconstruction test suite passes unchanged,
proving zero semantic change. The rule, verbatim: a booking counts only when `booked_at` precedes
the cutoff (the start of the next property-local day); `CONFIRMED`/`CHECKED_IN`/`CHECKED_OUT` are
certain; `CANCELLED` is certain only up to its own `cancelled_at` (without one, or with one before
`booked_at`, it is **uncertain**, never assumed either way); a `NO_SHOW` is certain before its own
check-in date and uncertain from it on. An uncertain booking is never attributed to a channel.

## Room-night allocation and snapshot reconciliation

Only **CERTAIN** room-nights, for every booking overlapping the 30-day window, are attributed to a
channel group and summed. A multi-room, multi-night booking is *never* counted as one: its rooms
are allocated to every night it occupies, reusing Gate 3's own `stay_night_overlap`.

For every one of the 30 nights, the independently reconstructed total (across all four groups)
must equal EXACTLY the already-stored `BookingSnapshot.rooms_on_books` for that (as-of, stay-date)
key. This is not a formality: the canonical `bookings` table keeps only current state, so a booking
corrected after a snapshot was taken can make a fresh reconstruction genuinely disagree with it.
NINFA never "fixes" a mismatch numerically — a target with a mismatch is `INSUFFICIENT_DATA`
(`OTA_CHANNEL_MIX_RECONCILIATION_FAILED`); a mismatched historical period is excluded and counted.

## Quality gates (target)

In order, the first that applies decides:

1. **Window completeness** — all 30 snapshots of the target's own window must exist.
   `INSUFFICIENT_DATA` / `OTA_SNAPSHOT_WINDOW_INCOMPLETE` otherwise. A missing snapshot is never a
   zero.
2. **No uncertainty** — any of the 30 snapshots with `uncertain_rooms > 0` makes the window
   unreliable. `INSUFFICIENT_DATA` / `OTA_SNAPSHOT_WINDOW_UNCERTAIN`.
3. **Reconciliation** — see above.
4. **On-books demand** — `certain_room_nights == 0` is `NOT_APPLICABLE` /
   `OTA_NO_ON_BOOKS_DEMAND` (never a division by zero).
5. **Classification coverage** — `classified_room_nights / certain_room_nights * 100`
   (`classified` = OTA + DIRECT only; OTHER and UNKNOWN reduce coverage without entering the OTA
   share's own denominator) must be at least 80% (`MIN_CHANNEL_CLASSIFICATION_COVERAGE`), else
   `INSUFFICIENT_DATA` / `OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW`. 80 exactly is valid; 79.99...
   is not.
6. **Volume** — `classified_room_nights >= 20` (`MIN_CLASSIFIED_ROOM_NIGHTS`), else
   `INSUFFICIENT_DATA` / `OTA_BOOKING_VOLUME_LOW`: a share computed on a handful of room-nights is
   too noisy to trust.

## Historical comparable periods

For target as-of `T`, a historical as-of `H` is a candidate only when it is exactly `T - 7k` days
(`k >= 1`, so always strictly before `T`), at most 730 days back, and within 42 seasonal days of
`T` — the **exact same** `seasonal_distance_days` function Gate 4 uses, imported, never a second
implementation. Each candidate gets its **own** 30-day window `[H, H+29]` and its own snapshot
batch. A candidate becomes an eligible comparable only when: all 30 of its own snapshots exist,
none is uncertain, its independently reconstructed mix reconciles day by day, its classification
coverage is at least 80%, and its classified room nights are at least 20 — the identical gates the
target itself must pass, now applied to history. Every rejection is counted by its own reason
(`rejected_snapshot_incomplete_count`, `_uncertain_count`, `_reconciliation_count`,
`_low_classification_count`, `_low_volume_count`), never silently dropped.

**Observed-first**: with at least 5 `FULLY_OBSERVED_PERIOD` (all 30 of its snapshots `OBSERVED`)
eligible periods, only they are used. Otherwise every fully observed period is kept and the newest
clean, `RECONSTRUCTED_APPROXIMATE` periods fill the sample up to 24, most recent first. Fewer than
5 total is `INSUFFICIENT_DATA` / `OTA_COMPARABLE_SAMPLE_INSUFFICIENT`.

Each used period's own provenance is `(observed_days * 100 + reconstructed_days * 60) / 30` — a
whole snapshot day is either `OBSERVED` or a clean `RECONSTRUCTED_APPROXIMATE`; an uncertain day
already excluded the whole period earlier.

## Expected OTA share, structural and rising dependency

Over the used periods' own OTA shares, `median` / `P25` / `P75` / `IQR` are computed by linear
interpolation (the Expected Engine's own algorithm, at full Decimal precision, no outlier ever
removed) — `expected_ota_share` is the median, `upper_fence = P75 + 1.5 * IQR`. Because a share is a
percentage, the fence can mathematically exceed 100; nothing clamps it, and the trigger logic does
not need it clamped. `delta_pp = actual_ota_share - expected_ota_share` is in **percentage points**,
never percent-change (a rise from 40% to 60% is `+20 pp`, not `+50%`).

REV_OTA_DEPENDENCY recognises two, independent forms of dependency (the numeric trigger is their
OR, never their AND):

- **Structural** — `actual_ota_share >= 70` (`OTA_STRUCTURAL_SHARE_THRESHOLD`). It does **not**
  require the share to have risen: a property historically at 80% OTA and still at 80% today is
  still structurally dependent, and must be nameable as such.
- **Rising** — `actual_ota_share >= 55` (`OTA_RISING_MIN_SHARE`) **and**
  `delta_pp >= 15` (`OTA_RISING_GAP_PP`) **and** `actual_ota_share >= upper_fence` — all three, an
  AND. A property at 35% historically that jumps to 60% today never crosses the 70% structural
  threshold, yet the shift itself is exactly what this path exists to name.

Every comparison is on the full-precision `*_exact` value; the two-decimal `*_display` value never
decides (69.995% displays as 70.00 but stays below the structural threshold at full precision).

Reason codes: `TRIGGER_STRUCTURAL_OTA_DEPENDENCY`, `TRIGGER_RISING_OTA_DEPENDENCY`,
`TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY` (both at once), or `CLEAR_WITHIN_EXPECTED_RANGE`.

## Confidence

Baseline confidence (over the used historical periods): `0.35 * sample_score + 0.25 *
provenance_score + 0.20 * classification_score + 0.20 * stability_score` (HALF_UP, two decimals),
where `sample_score = min(100, n/12*100)`, `provenance_score`/`classification_score` are the plain
means of the periods' own provenance/coverage, and `stability_score = max(0, 100 - 50*IQR /
max(expected_ota_share, 1))`. Caps applied after the formula: any used period that is not fully
observed caps the score at 85; no fully observed period among them caps it at 65.

`target_quality = 0.50 * target.snapshot_provenance_score + 0.50 *
target.classification_coverage_pct` (HALF_UP, two decimals) — the target window's *own*
reliability, independent of history.

`confidence_score = MIN(baseline_confidence, target_quality)`, **never their average**: a decision
is only as reliable as its weakest input. Gate: 55. A numeric candidate with confidence below 55 is
`SUPPRESSED_LOW_CONFIDENCE` (`LOW_CONFIDENCE`), never silently upgraded to `TRIGGERED`; a low
confidence never manufactures a trigger out of a `CLEAR` day either (a `CLEAR` day stays `CLEAR`
whatever its confidence is).

## Optional revenue evidence

When the target's own room revenue by group resolves cleanly (the same currency-safe, Gate
3-reused stay-night allocation used for room-nights), the evaluation additionally carries
`ota_room_revenue_on_books` / `direct_room_revenue_on_books` / `ota_revenue_share` — a gross
**exposure**, never a commission cost, a saving or a loss, and it never enters the trigger. No FX
conversion is ever attempted.

## Determinism, read-only, tenant isolation, performance

Every `*_exact` figure is computed in a dedicated 50-significant-digit `Decimal` context
(`intelligence.distribution.precision`, re-exported from Gate 5's own), independent of whatever the
process-wide `decimal` context happens to be — proven by a test that runs the same evaluation under
a deliberately hostile ambient context and checks the fingerprint is unchanged (this also surfaced,
and this gate fixed, a latent context-sensitivity bug in Gate 3's own `to_cents`/`from_cents`; see
the ADR). The evaluation is a SHA-256 fingerprint of its own canonical (non-lossy, non-display)
payload, sealed once by `fingerprint.seal`.

The service is completely **read-only**: no write, no advisory lock, no clock, and it never
commits or rolls back (the caller owns the transaction). It is fully tenant-scoped through
`TenantContext`: an id of another workspace or another property does not exist for it. The whole
evaluation reads a fixed, small handful of statements — one channel read, one booking read (one
query covering the union of the target's window and every historical candidate's), and one batched
snapshot read for every (as-of, stay-date) key — regardless of how many historical periods are
considered; never a query per stay date, per booking or per comparable.

## Limitations (intentional, V1)

No channel manager, booking engine, commission accounting, pricing, rate-parity or attribution
integration; no auto-scheduling or workforce concept (unrelated to this gate, mentioned only for
completeness of the "not built" list); no persisted `Decision`/priority/recommendation; no AI/ML of
any kind. `BookingChannel` classification stays entirely in-memory and read-only: a future setup
workflow may let a customer confirm/override it explicitly, but Gate 9 itself never writes it.

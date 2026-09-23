# 0015 — OTA Dependency Detection V1: concentration not performance, temporal reuse, no commission

**Status:** accepted (Gate 9)

## Context
Gates 2-8 gave NINFA canonical bookings and channels, daily snapshots, an Expected baseline, two
revenue detectors, a cost detector and a labor detector. The fifth and last MVP question is about
distribution: "how much of the property's imminent room-night business already depends on OTA
channels, and is that dependency structurally high or rising sharply above comparable history?"
Answering it must not become a channel manager, a booking engine, a commission/profitability model,
or a channel-performance ranking; it must measure CONCENTRATION of the mix, never whether a channel
converts well or is worth keeping.

## Decision
1. **A 30-day forward window, not a single stay date.** The target is
   `(property, booking_data_source, as_of_local_date)`; the window is
   `[as_of_local_date, as_of_local_date + 29]`, a versioned policy
   (`FORWARD_STAY_WINDOW_DAYS = 30`). One night is dominated by noise (a single group block, one
   no-show); a quarter or a year would already be strategy, not an imminent booking window. 30 days
   smooths daily noise, spans several weekdays and stays operationally close.
2. **Room nights are the primary metric, not revenue.** A room-night is unambiguous, always known
   the moment a booking exists, and needs no rate, no currency and no FX to compare across periods.
   Revenue-by-channel is exposed only OPTIONALLY (see 15) and never decides anything.
3. **Channel classification is conservative and layered, reusing `BookingChannel` first.** Gate 2
   already carries `channel_type` + `is_verified`; an UNVERIFIED value is Gate 2's own unconfirmed
   hint, not a fact, so only a VERIFIED value is trusted as `CANONICAL_SOURCE` (confidence 100).
   Everything else falls to a second, independent, small, exact dictionary (`DETERMINISTIC_RULE`,
   confidence 95); anything left is `UNCLASSIFIED` → `UNKNOWN` (confidence 0). No new persisted
   classification, no channel write: the classifier is pure, in-memory, recomputed every evaluation.
4. **No fuzzy matching, anywhere.** The dictionary matches the channel's own `normalized_name`
   EXACTLY; a near-miss ("Bookings.com", "Booking Engine") is never guessed into a real OTA name. A
   wrong guess here would misclassify real distribution data with no way for the customer to notice;
   staying UNKNOWN is loud (it lowers coverage) where a wrong guess would be silent.
5. **Gate 3's own temporal rule is reused, never reimplemented.** Whether a booking was certainly,
   uncertainly, or not yet on the books at an earlier cutoff is exactly the question Gate 3's
   reconstruction already answers. `booking_certainty_window`/`stay_night_overlap`
   (`app.modules.snapshots.aggregate`) were made public, UNMODIFIED, and Gate 9 calls them at a
   single cutoff; Gate 3's own full test suite passes unchanged, proving zero semantic drift. A
   second temporal algorithm could only diverge from the first over time.
6. **Snapshot reconciliation, not silent correction.** The canonical `bookings` table keeps only
   current state; correcting a booking after its snapshot was taken can make a fresh
   reconstruction genuinely disagree with what was stored. NINFA never adjusts the mix to match the
   snapshot or vice versa: a mismatch is `INSUFFICIENT_DATA` (target) or an excluded, counted
   rejection (history). Guessing which side is right would hide a real data-quality problem.
7. **Classification coverage must be at least 80%.** Below it, too much of the window is OTHER/
   UNKNOWN for an OTA SHARE (defined only over OTA+DIRECT) to mean anything: a 90% "OTA share" on a
   window that is 60% unclassified is not a fact worth acting on.
8. **At least 20 classified room nights.** A share computed on a handful of room-nights is
   statistically noisy; 20 is the same order of magnitude as the volume floors already used
   elsewhere in NINFA (Gate 8's labor detector) for the same reason.
9. **Same weekday, ±42 seasonal days, 730-day horizon — Gate 4's own algorithm, reused.** A
   Tuesday's mix is not comparable to a Saturday's; a mix in August is not comparable to one in
   December. `seasonal_distance_days` is imported directly, never duplicated.
10. **Structural dependency exists independently of the historical trend.** A property historically
    at 80% OTA and still at 80% today shows zero delta, yet it is unmistakably, structurally
    dependent — a rule that only fired on a rise would systematically miss the properties most
    worth naming. `actual_ota_share >= 70` (`OTA_STRUCTURAL_SHARE_THRESHOLD`) needs no comparison
    to history at all.
11. **Rising dependency uses the expected share and the robust IQR fence, not a fixed step.** A
    property's normal volatility differs; the same 10-point jump means little for a property whose
    share already swings by 20 points month to month, and everything for one that never moves.
    `upper_fence = P75 + 1.5 * IQR` (the Expected Engine's own statistic, no outlier removal) makes
    the "sharply above" judgement relative to the property's own history, not an arbitrary constant.
12. **Structural threshold: 70%.** A versioned policy constant, deliberately conservative: below it,
    a property still has a meaningfully diversified direct/other channel base even if OTA is its
    largest single source.
13. **Rising threshold: 55% minimum share AND at least 15 percentage points above the median AND at
    or above the fence — all three, an AND, never an OR.** The minimum share keeps a rise from
    35% to 45% (still clearly minority OTA) from firing; the 15-point gap keeps small, normal
    week-to-week noise from firing; the fence keeps a property whose baseline is simply volatile
    from firing on its own ordinary spread. Any one alone is too permissive.
14. **Final confidence is the MINIMUM of the baseline confidence and the target's own quality,
    never their average.** A decision is only as reliable as its weakest input: a perfectly
    observed target computed against a thin, mostly-reconstructed history is not reliable just
    because the target itself is clean, and the reverse is equally true. Gate: 55.
15. **No commission, no savings, no channel-profitability model, ever.** NINFA never assumes a
    commission rate, never computes a "commission saved" or a "net revenue gain", and never ranks
    channels by conversion, CAC, ROAS or cancellation rate. The one optional figure this gate can
    expose — `ota_room_revenue_on_books`/`ota_revenue_share` — is a GROSS EXPOSURE, computed only
    when it resolves cleanly (currency-safe, the same Gate-3-reused stay-night allocation), and is
    documented, named and tested as an exposure, never a saving or an avoidable cost.
16. **Read-only, no persisted Decision, no priority, no AI.** Like Gates 5, 7 and 8, the output is
    an immutable, fingerprinted evaluation, a pure function of stored bookings/channels/snapshots,
    recomputable at any time. `OtaDependencyService` writes nothing, takes no lock, reads no clock.
    There is no `Decision`, `DecisionFact`, priority, ranking, recommendation or AI/ML anywhere in
    this gate, and no channel-management or scheduling feature was added.

## A side effect: a latent Gate 3 determinism bug, found and fixed
Testing REV_OTA_DEPENDENCY's determinism (the same input must give the same fingerprint under any
ambient `decimal` context) surfaced that Gate 3's own `to_cents`/`from_cents`
(`app.modules.snapshots.calculation`) multiplied/rescaled using the process-wide context rather
than an explicit one — latent since Gate 3, invisible under the default context, but a real
determinism risk. Both were fixed to use an explicit, dedicated 50-digit context local to that
module (never importing Gate 5's own, to keep the dependency direction correct); Gate 3's full
test suite (and every gate built on it) still passes unchanged, confirming zero behavioural change
under any context a real deployment would ever use.

## Alternatives considered
* **A revenue-first metric**: rejected (see 2): room-nights need no currency/FX and are simpler to
  reconcile against the existing snapshot; revenue stays a secondary, optional exposure.
  * **Trusting an unverified `channel_type` as canonical**: rejected (see 3): Gate 2 itself calls it a
  hint, not a confirmed fact; trusting it here would let a heuristic silently outrank this gate's
  own, more complete dictionary.
* **A fixed percentage-point step for "rising" (e.g. "+10pp always")**: rejected (see 11/13): it
  ignores how volatile a specific property's own history already is.
* **Persisting `OtaDependencyEvaluation` or a `Decision` now**: rejected, for the same reason as
  Gates 5, 7 and 8 (ADR 0011/0013/0014): the lifecycle is not known yet and the evaluation is cheap
  to recompute.

## Consequences
* Additive and fully reversible: **zero migration** (the head stays `0008_labor_ingestion`), zero
  new dependency, no public API beyond `/api/v1/health`, no worker task.
* `app.modules.snapshots.aggregate`/`calculation` gained two public names
  (`booking_certainty_window`, `stay_night_overlap`) and a dedicated local Decimal context; both
  are additive, and Gate 3's own test suite is the proof nothing else changed.
* Any later gate that needs "was this booking on the books at an earlier cutoff" should call
  `intelligence.distribution.temporal.booking_certainty_at` (or Gate 3's own public functions
  directly), never write a third implementation of the same rule.
* `BookingChannel` classification stays entirely read-only in V1; a future setup workflow that lets
  a customer confirm/override `channel_type`/`is_verified` explicitly can build on the exact same
  `ChannelRow`/`ChannelClassification` types without changing this gate's own logic.

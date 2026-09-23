"""Golden scenario: Masseria Ninfa Demo, extended with Gate 9 DISTRIBUTION DATA V1.

Real end-to-end chain: Booking import (via the shared `BookingFactory`/`DistributionWorld`
helpers, the same convention every other gate's golden file uses) -> canonical `Booking` rows ->
`BookingChannel` -> `BookingSnapshot` -> channel reconstruction as-of (Gate 3's own temporal
rule, reused) -> the channel-mix metric -> historical comparable periods -> REV_OTA_DEPENDENCY.
Nothing here calls `distribution.statistics`/`.confidence`/`.detector`/`.selection` to compute an
expected value: every expected number below is a literal Decimal/fraction worked out by hand
from the constructed input, exactly like the other gates' golden files.

Cases (letters per the Gate 9 spec):
    A  structural dependency only                                -> TRIGGERED (STRUCTURAL)
    B  rising dependency only                                     -> TRIGGERED (RISING)
    C  both structural and rising                                 -> TRIGGERED (BOTH)
    D  a normal mix                                                -> CLEAR
    E  above the rising floor but the gap does not confirm it      -> CLEAR
    F  a numeric candidate but confidence < 55                     -> SUPPRESSED_LOW_CONFIDENCE
    G  fewer than 5 historical periods                             -> INSUFFICIENT_DATA
    H  target classification coverage < 80%                       -> INSUFFICIENT_DATA
    I  zero on-books demand                                        -> NOT_APPLICABLE
    J  only 19 classified room nights                              -> INSUFFICIENT_DATA
    K  one missing target snapshot                                 -> INSUFFICIENT_DATA
    L  a channel-mix reconciliation mismatch                       -> INSUFFICIENT_DATA
    M  a historical RECONSTRUCTED-clean period lowers provenance   -> proven directly
    N  a historical UNCERTAIN period is excluded                   -> proven directly
    O  a booking cancelled AFTER a historical as-of counts there    -> proven directly
    P  a booking cancelled BEFORE a historical as-of is excluded    -> proven directly
    Q  a booking booked AFTER a historical as-of never leaks back   -> proven directly
    R  an ambiguous channel stays UNKNOWN and lowers coverage       -> proven directly
    S  a known OTA and a known DIRECT channel classify correctly    -> proven directly
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.modules.bookings.models import BookingChannel
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import (
    EvaluationStatus,
    OtaDependencyEvaluation,
    ReasonCode,
)
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import SnapshotOrigin
from tests.distribution_support import (
    CANCELLED,
    LONG_AGO,
    ChannelType,
    DistributionFactory,
    DistributionWorld,
    Tenant,
)

TARGET_AS_OF = date(2026, 9, 5)  # a Saturday
WINDOW_END = TARGET_AS_OF + timedelta(days=29)
TZ = ZoneInfo("Europe/Rome")  # the property's own default timezone
# An INDEPENDENTLY constructed 50-significant-digit context (never imported from production):
# every "*_exact" figure in this system is documented (Gate 5's ADR/precision module docstrings)
# as computed at 50 significant digits, so this is a public policy fact, not a hidden detail -
# needed only so a non-terminating fraction computed here truncates at the SAME digit count the
# system does, for a meaningful equality check (both sides are still independently computed).
_FIFTY_DIGITS = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _share(part: int, whole: int) -> Decimal:
    return _FIFTY_DIGITS.divide(_FIFTY_DIGITS.multiply(Decimal(part), Decimal(100)), Decimal(whole))


def _historical_saturdays(n: int, *, start_week: int = 1) -> list[date]:
    return [TARGET_AS_OF - timedelta(weeks=k) for k in range(start_week, start_week + n)]


def _recent() -> datetime:
    """Booked on the target's own as-of day: after every historical cutoff (Gate 3's own
    `booked_at < cutoff` rule), so it is certain for the target but invisible to any history."""
    return datetime.combine(TARGET_AS_OF, time(9, 0), tzinfo=UTC)


def _clean_history(
    world: DistributionWorld, ota_rooms: int, direct_rooms: int, *, n: int = 6
) -> tuple[list[date], BookingChannel, BookingChannel]:
    """`n` clean, reconciling, fully-observed historical weeks with a UNIFORM mix, spanning the
    whole combined range once (consecutive 30-night windows overlap by design). Returns the
    channels too, so the caller adds any further booking on the SAME rows (a data source has
    exactly one channel per normalised name: creating "Booking.com" twice is a real, expected
    uniqueness violation, never a second, independent channel)."""
    weeks = _historical_saturdays(n)
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(
        min(weeks), WINDOW_END, [(channel_ota, ota_rooms), (channel_direct, direct_rooms)]
    )
    total = ota_rooms + direct_rooms
    for as_of in weeks:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), total)
    return weeks, channel_ota, channel_direct


def _evaluate(session: Session, tenant: Tenant) -> OtaDependencyEvaluation:
    service = OtaDependencyService(session, tenant.context)
    return service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=TARGET_AS_OF,
    )


# --- A: structural dependency only ---------------------------------------------------------------


def test_golden_case_a_structural_dependency_only(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _, channel_ota, _channel_direct = _clean_history(world, 75, 25)  # median = 75% (IQR = 0)
    # A recent OTA-only pickup on the target: 75+15=90 OTA / 25 DIRECT -> 90/115 = 78.26...%.
    world.booking(
        channel_ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=15, booked_at=_recent()
    )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 115)

    evaluation = _evaluate(db_session, tenant)
    expected_share = _share(90, 115)  # 90/115 * 100, independent stdlib arithmetic
    assert evaluation.ota_share_exact == expected_share
    assert evaluation.expected_ota_share_exact == 75
    assert evaluation.delta_pp_exact == _FIFTY_DIGITS.subtract(expected_share, Decimal(75))
    assert evaluation.delta_pp_exact < 15  # nowhere near the rising gap
    assert evaluation.structural_condition is True
    assert evaluation.rising_condition is False
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)


# --- B: rising dependency only --------------------------------------------------------------------


def test_golden_case_b_rising_dependency_only(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _, channel_ota, _channel_direct = _clean_history(world, 38, 62)  # median = 38%
    # 38+55=93 OTA / 62 DIRECT -> 93/155 = 60% exactly.
    world.booking(
        channel_ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=55, booked_at=_recent()
    )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 155)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.ota_share_exact == 60
    assert evaluation.expected_ota_share_exact == 38
    assert evaluation.delta_pp_exact == 22  # >= 15
    assert evaluation.upper_fence_exact == 38  # flat history: fence == median
    assert evaluation.structural_condition is False  # 60 < 70
    assert evaluation.rising_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_RISING_OTA_DEPENDENCY,)


# --- C: both structural and rising ----------------------------------------------------------------


def test_golden_case_c_both_structural_and_rising(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _, channel_ota, _channel_direct = _clean_history(world, 45, 55)  # median = 45%
    # 45+120=165 OTA / 55 DIRECT -> 165/220 = 75% exactly.
    world.booking(
        channel_ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=120, booked_at=_recent()
    )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 220)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.ota_share_exact == 75
    assert evaluation.expected_ota_share_exact == 45
    assert evaluation.delta_pp_exact == 30
    assert evaluation.structural_condition is True  # 75 >= 70
    assert evaluation.rising_condition is True  # 75>=55, 30>=15, 75>=fence(45)
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY,)


# --- D: a normal mix ------------------------------------------------------------------------------


def test_golden_case_d_a_normal_mix_is_clear(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _clean_history(world, 45, 55)  # tuple unused: target inherits the same 45%, no pickup
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 100)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.ota_share_exact == 45
    assert evaluation.delta_pp_exact == 0
    assert evaluation.structural_condition is False
    assert evaluation.rising_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)


# --- E: above the rising floor but the gap does not confirm it ------------------------------------


def test_golden_case_e_gap_too_small_is_clear(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _, channel_ota, _channel_direct = _clean_history(world, 65, 35)  # median = 65%
    # 65+10=75 OTA / 35 DIRECT -> 75/110 = 68.18...%: above the 55% floor and the fence (68.18
    # >= 65), but the gap (3.18pp) is nowhere near 15: the AND of Part F still fails.
    world.booking(
        channel_ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=10, booked_at=_recent()
    )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 110)

    evaluation = _evaluate(db_session, tenant)
    expected_share = _share(75, 110)
    assert evaluation.ota_share_exact == expected_share
    assert evaluation.upper_fence_exact is not None
    assert evaluation.delta_pp_exact is not None
    assert expected_share >= 55  # the floor alone would suggest rising
    assert expected_share >= evaluation.upper_fence_exact  # so would the fence alone
    assert evaluation.delta_pp_exact < 15  # but the gap alone blocks it
    assert evaluation.rising_condition is False
    assert evaluation.structural_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


# --- F: a numeric candidate but confidence < 55 ---------------------------------------------------


def test_golden_case_f_suppressed_low_confidence(
    db_session: Session, factory: DistributionFactory
) -> None:
    """5 RECONSTRUCTED_APPROXIMATE (never fully observed: caps the baseline at 65) historical
    weeks, 3 of which stay at a base 5% share and 2 of which jump to 90% (via a real, second,
    later-booked addition - never by editing the first one): the resulting historical spread
    (median 5, P75 90) alone already drives the baseline confidence under 55, regardless of the
    65 cap, so a genuine structural candidate (target also at 90%) is suppressed, not triggered.
    """
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(5)  # weeks 1-5 back
    week3 = weeks[2]

    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    first_night = min(weeks)
    # Base: 1 OTA / 19 DIRECT (5% share), certain everywhere (weeks 1-5 AND the target).
    world.uniform_bookings(first_night, WINDOW_END, [(channel_ota, 1), (channel_direct, 19)])
    # The jump: 170 more OTA rooms, booked only after week 3's own cutoff - invisible to weeks
    # 3, 4, 5 (older), certain for weeks 1, 2 and the target (newer): (1+170)/(20+170) = 90%.
    jump_booked_at = end_of_local_day(week3, TZ) + timedelta(hours=1)
    world.booking(
        channel_ota,
        first_night,
        WINDOW_END + timedelta(days=1),
        rooms=170,
        booked_at=jump_booked_at,
    )

    # weeks[0], weeks[1] = week 1, 2 back (the two NEWEST: their cutoffs are AFTER jump_booked_at,
    # so they see it). weeks[2:] = week 3, 4, 5 back (week 3 itself included: jump_booked_at is
    # strictly AFTER week 3's own cutoff, so even week 3 does not see it).
    for as_of in weeks[:2]:  # base + jump, 190/night
        world.snapshot_window(
            as_of,
            as_of,
            as_of + timedelta(days=29),
            190,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    for as_of in weeks[2:]:  # base only, 20/night
        world.snapshot_window(
            as_of,
            as_of,
            as_of + timedelta(days=29),
            20,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 190)  # base + jump too

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.sample_count == 5
    assert evaluation.fully_observed_count == 0  # every period is RECONSTRUCTED
    assert evaluation.ota_share_exact == 90  # structural: a real numeric candidate
    assert evaluation.structural_condition is True
    assert evaluation.confidence_score < 55
    assert evaluation.status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.reason_codes == (ReasonCode.LOW_CONFIDENCE,)


# --- G: fewer than 5 historical periods -----------------------------------------------------------


def test_golden_case_g_fewer_than_5_historical_periods(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _clean_history(world, 50, 50, n=3)  # only 3 historical weeks: below MIN_COMPARABLES (5)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 100)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.sample_count == 3
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_COMPARABLE_SAMPLE_INSUFFICIENT,)


# --- H: target classification coverage < 80% ------------------------------------------------------


def test_golden_case_h_low_target_classification_coverage(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    _clean_history(world, 50, 50)
    unknown = world.channel("Some Regional Reseller Nobody Coded")
    # base 100 classified + 100 recent unknown -> coverage = 100/200 = 50% (< 80).
    world.booking(
        unknown, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=100, booked_at=_recent()
    )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 200)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.classification_coverage_pct_exact == 50
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW,)


# --- I: zero on-books demand ---------------------------------------------------------------------


def test_golden_case_i_zero_demand_is_not_applicable(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 0)  # no bookings, no history

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.certain_room_nights == 0
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.OTA_NO_ON_BOOKS_DEMAND,)


# --- J: only 19 classified room nights ------------------------------------------------------------


def test_golden_case_j_19_classified_room_nights(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(channel_ota, TARGET_AS_OF, TARGET_AS_OF + timedelta(days=1), rooms=19)
    world.snapshot_window(
        TARGET_AS_OF,
        TARGET_AS_OF,
        WINDOW_END,
        {TARGET_AS_OF: 19, **{TARGET_AS_OF + timedelta(days=i): 0 for i in range(1, 30)}},
    )

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.classified_room_nights == 19
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_BOOKING_VOLUME_LOW,)


# --- K: one missing target snapshot ---------------------------------------------------------------


def test_golden_case_k_one_missing_target_snapshot(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END - timedelta(days=1), 10)  # 29/30

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_SNAPSHOT_WINDOW_INCOMPLETE,)


# --- L: a channel-mix reconciliation mismatch -----------------------------------------------------


def test_golden_case_l_reconciliation_mismatch(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(channel_ota, TARGET_AS_OF, WINDOW_END + timedelta(days=1), rooms=30)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 999)  # never matches 30

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_CHANNEL_MIX_RECONCILIATION_FAILED,)


# --- M: a historical RECONSTRUCTED-clean period lowers provenance ---------------------------------


def test_golden_case_m_reconstructed_clean_period_lowers_provenance(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(5)
    reconstructed_week, observed_weeks = weeks[0], weeks[1:]
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(min(weeks), WINDOW_END, [(channel_ota, 20), (channel_direct, 10)])
    world.snapshot_window(
        reconstructed_week,
        reconstructed_week,
        reconstructed_week + timedelta(days=29),
        30,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,  # clean: uncertain_rooms stays 0
    )
    for as_of in observed_weeks:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.sample_count == 5
    assert evaluation.fully_observed_count == 4
    assert evaluation.approximate_count == 1
    reconstructed_facts = [
        p for p in evaluation.comparable_periods if p.as_of_local_date == reconstructed_week
    ]
    assert len(reconstructed_facts) == 1
    assert reconstructed_facts[0].reconstructed_day_count == 30
    assert reconstructed_facts[0].is_fully_observed is False
    # mean provenance = (4*100 + 1*60) / 5 = 92, strictly below the all-observed 100.
    assert evaluation.provenance_score_exact == 92
    assert evaluation.confidence_cap == 85


# --- N: a historical UNCERTAIN period is excluded -------------------------------------------------


def test_golden_case_n_uncertain_period_is_excluded(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(6)  # weeks 1-6 back
    uncertain_week, clean_weeks = weeks[0], weeks[1:]
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(min(weeks), WINDOW_END, [(channel_ota, 20), (channel_direct, 10)])
    # Uncertainty is only possible on a RECONSTRUCTED_APPROXIMATE reading at the database level
    # (an OBSERVED reading is by definition exact).
    world.snapshot_window(
        uncertain_week,
        uncertain_week,
        uncertain_week + timedelta(days=29),
        30,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        uncertain_rooms=5,
    )
    for as_of in clean_weeks:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.sample_count == 5
    assert evaluation.rejected_snapshot_uncertain_count >= 1
    used_dates = {p.as_of_local_date for p in evaluation.comparable_periods}
    assert used_dates == set(clean_weeks)
    assert uncertain_week not in used_dates


# --- O: a booking cancelled AFTER a historical as-of counts there ---------------------------------


def test_golden_case_o_cancelled_after_historical_as_of_still_counts(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(5)
    # The OLDEST week: its own day 0 (its as-of date itself) falls inside no OTHER week's
    # 30-night window (each of weeks 1-4 starts later), so the special booking below cannot
    # accidentally leak into (and break the reconciliation of) any comparable but this one.
    special_week = weeks[-1]
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(min(weeks), WINDOW_END, [(channel_ota, 20), (channel_direct, 10)])
    # Cancelled the day AFTER the special week's own as-of cutoff: it was still on the books AT
    # that historical as-of, so it must be counted there (the snapshot below expects it).
    cancelled_at = end_of_local_day(special_week, TZ) + timedelta(days=1)
    world.booking(
        channel_direct,
        special_week,
        special_week + timedelta(days=1),
        rooms=5,
        status=CANCELLED,
        booked_at=LONG_AGO,
        cancelled_at=cancelled_at,
    )
    for as_of in weeks:
        rooms = 35 if as_of == special_week else 30  # only the special week's day 0 has +5
        world.snapshot_window(
            as_of,
            as_of,
            as_of + timedelta(days=29),
            {as_of: rooms, **{as_of + timedelta(days=i): 30 for i in range(1, 30)}},
        )
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA  # reconciled: it was counted
    assert special_week in {p.as_of_local_date for p in evaluation.comparable_periods}


# --- P: a booking cancelled BEFORE a historical as-of is excluded ---------------------------------


def test_golden_case_p_cancelled_before_historical_as_of_is_excluded(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(5)
    special_week = weeks[-1]  # the OLDEST week: see case O's comment on why
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(min(weeks), WINDOW_END, [(channel_ota, 20), (channel_direct, 10)])
    # Cancelled the day BEFORE the special week's own as-of cutoff: already off the books by
    # then, so it must NOT be counted there (the snapshot below expects it absent).
    cancelled_at = end_of_local_day(special_week, TZ) - timedelta(days=1)
    world.booking(
        channel_direct,
        special_week,
        special_week + timedelta(days=1),
        rooms=5,
        status=CANCELLED,
        booked_at=LONG_AGO,
        cancelled_at=cancelled_at,
    )
    for as_of in weeks:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)  # never +5 anywhere
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 30)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA  # reconciled: it was excluded
    assert special_week in {p.as_of_local_date for p in evaluation.comparable_periods}


# --- Q: a booking booked AFTER a historical as-of never leaks backward ----------------------------


def test_golden_case_q_booked_after_historical_as_of_never_leaks_back(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    weeks = _historical_saturdays(5)
    special_week = weeks[0]
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    channel_direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    world.uniform_bookings(min(weeks), WINDOW_END, [(channel_ota, 20), (channel_direct, 10)])
    # Booked the day AFTER the special week's own as-of cutoff: did not exist yet at that
    # historical as-of, so it must NOT be counted there, even though it is real and certain for
    # every LATER as-of (the target's own window includes it, via the recent-booking pattern).
    booked_at = end_of_local_day(special_week, TZ) + timedelta(days=1)
    world.booking(
        channel_direct,
        TARGET_AS_OF,
        WINDOW_END + timedelta(days=1),
        rooms=5,
        booked_at=booked_at,
    )
    for as_of in weeks:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)  # never +5
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 35)  # target DOES include it

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.status != EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.certain_room_nights == 35 * 30
    assert special_week in {p.as_of_local_date for p in evaluation.comparable_periods}


# --- R: an ambiguous channel stays UNKNOWN and lowers coverage ------------------------------------


def test_golden_case_r_ambiguous_channel_stays_unknown(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    channel_ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    ambiguous = world.channel("Booking Engine")  # deliberately NOT "Booking.com": never guessed
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(channel_ota, 60), (ambiguous, 40)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 100)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.unknown_room_nights == 40 * 30
    assert evaluation.classification_coverage_pct_exact == 60  # 60 classified / 100 certain
    assert evaluation.classification_coverage_pct_exact < 80
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW,)


# --- S: a known OTA and a known DIRECT channel classify correctly ---------------------------------


def test_golden_case_s_known_ota_and_direct_classify_correctly(
    db_session: Session, factory: DistributionFactory
) -> None:
    """Neither channel is `is_verified`: this proves the DETERMINISTIC dictionary tier (never
    the canonical/verified one) correctly classifies real, unverified channel names end to end."""
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    channel_ota = world.channel("Booking.com")  # unverified: channel_type defaults to OTHER
    channel_direct = world.channel("Direct")  # unverified too
    assert channel_ota.is_verified is False
    assert channel_direct.is_verified is False
    world.uniform_bookings(TARGET_AS_OF, WINDOW_END, [(channel_ota, 70), (channel_direct, 30)])
    world.snapshot_window(TARGET_AS_OF, TARGET_AS_OF, WINDOW_END, 100)

    evaluation = _evaluate(db_session, tenant)
    assert evaluation.ota_room_nights == 70 * 30
    assert evaluation.direct_room_nights == 30 * 30
    assert evaluation.classification_coverage_pct_exact == 100

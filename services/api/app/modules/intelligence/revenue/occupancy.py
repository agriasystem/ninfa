"""REV_OCCUPANCY_RISK: on-the-books plus the usual remaining net pickup falls short of the usual
final occupancy (pure).

This is a deliberately MINIMAL net-pickup projection, not a revenue-management forecast system:

    expected_remaining_net_pickup = median over the historical curve pairs of
                                    (final rooms - anchor rooms)   [same historical stay date,
                                    anchor = the Gate 4 comparable, final = lead time 0]
    raw_forecast_rooms   = current rooms + expected_remaining_net_pickup
    forecast_rooms       = max(0, raw_forecast_rooms)       (the only floor; NO upper cap)
    expected_final_rooms = median of the final rooms of the SAME pairs
    forecast_occupancy   = forecast_rooms / rooms_available * 100
    expected_final_occupancy = expected_final_rooms / rooms_available * 100
    room_shortfall       = max(0, expected_final_rooms - forecast_rooms)
    occupancy_gap_pp     = max(0, expected_final_occupancy - forecast_occupancy)   (points)
                         = room_shortfall / rooms_available * 100   (the same number, in ONE
                           division of an exact numerator: never a difference of rounded quotients)

The remaining pickup is NET: cancellations are already inside the historical movement of the
curve (it may be negative); there is no separate cancellation model. `rooms_available` is the
CURRENT target inventory, used as the denominator for both occupancies, never clamped to 100
(overbooking stays visible). Expected (Gate 4, a historical level at the same lead time) is NOT a
forecast: the projection above lives only in this evaluation and is never stored on a baseline.

Numeric condition (`revenue-decisions-v1`): `occupancy_gap_pp >= 10` OR `room_shortfall >= 3`,
evaluated on the FULL-PRECISION values the calculation produced (`precision.py`): a gap of 9.995
points is displayed as 10.00 but is below 10 points. The two-decimal occupancies and gap of the
facts are for display only and never decide. With the numeric condition true, the final confidence
(MIN of the baseline and the pattern, the authoritative two-decimal score) must be at least 55 to
TRIGGER; below it the evaluation is SUPPRESSED_LOW_CONFIDENCE.

Order of the checks (the first that applies decides): inventory unknown, closed night, already
sold out, baseline, pair sample, then the thresholds.
"""

from dataclasses import replace
from decimal import Decimal

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.revenue.confidence import final_confidence
from app.modules.intelligence.revenue.fingerprint import build_evaluation
from app.modules.intelligence.revenue.impact import ReferenceAdr, revenue_gap_proxy
from app.modules.intelligence.revenue.pattern import (
    analyse,
    diagnostic_facts,
    evidence_snapshot_ids,
)
from app.modules.intelligence.revenue.precision import for_display, percent_of
from app.modules.intelligence.revenue.statistics import other_rooms_median
from app.modules.intelligence.revenue.types import (
    MIN_PAIRS,
    OCCUPANCY_THRESHOLDS,
    EvaluationStatus,
    OccupancyFacts,
    OccupancyThresholds,
    PairSelection,
    ReasonCode,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
    TargetContext,
)

_ZERO = Decimal("0.00")


def gap_condition(
    occupancy_gap_pp: Decimal, thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS
) -> bool:
    """`occupancy_gap_pp >= 10` on the DECISION value: 9.99 and 9.995 do not pass, 10 does."""
    return occupancy_gap_pp >= thresholds.min_gap_pp


def shortfall_condition(
    room_shortfall: Decimal, thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS
) -> bool:
    """`room_shortfall >= 3` on the DECISION value: 2.99 and 2.995 do not pass, 3 does."""
    return room_shortfall >= thresholds.min_room_shortfall


def classify_occupancy(
    occupancy_gap_pp: Decimal,
    room_shortfall: Decimal,
    confidence: Decimal,
    thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS,
) -> tuple[EvaluationStatus, tuple[ReasonCode, ...]]:
    """The status of a projection: EITHER condition makes a numeric candidate, then the gate.

    The arguments are DECISION values (never rounded for display). The reason says which
    condition(s) held; confidence 54.99 is suppressed, 55.00 triggers.
    """
    by_gap = gap_condition(occupancy_gap_pp, thresholds)
    by_rooms = shortfall_condition(room_shortfall, thresholds)
    if not (by_gap or by_rooms):
        return EvaluationStatus.CLEAR, (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)
    if confidence < thresholds.min_confidence:
        return EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE, (ReasonCode.LOW_CONFIDENCE,)
    if by_gap and by_rooms:
        return EvaluationStatus.TRIGGERED, (ReasonCode.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL,)
    reason = ReasonCode.TRIGGER_OCCUPANCY_GAP if by_gap else ReasonCode.TRIGGER_ROOM_SHORTFALL
    return EvaluationStatus.TRIGGERED, (reason,)


def evaluate_occupancy(
    target: TargetContext,
    *,
    selection: PairSelection,
    reference: ReferenceAdr,
    thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS,
) -> RevenueDecisionEvaluation:
    """REV_OCCUPANCY_RISK for one OBSERVED target.

    `selection` are the historical remaining-net-pickup pairs of the target's Gate 4 baseline.
    """
    base = OccupancyFacts(
        current_rooms_on_books=target.rooms_on_books,
        rooms_available=target.rooms_available,
        baseline_confidence=target.baseline_confidence,
        thresholds=thresholds,
    )

    def finish(
        status: EvaluationStatus,
        reasons: tuple[ReasonCode, ...],
        *,
        facts: OccupancyFacts = base,
        confidence: Decimal = _ZERO,
        used: PairSelection | None = None,
        proxy: Decimal | None = None,
    ) -> RevenueDecisionEvaluation:
        return build_evaluation(
            decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
            status=status,
            target=target,
            confidence_score=confidence,
            reason_codes=reasons,
            facts=facts,
            evidence_snapshot_ids=evidence_snapshot_ids(
                target.target_snapshot_id, pairs=() if used is None else used.pairs
            ),
            reference=reference,
            revenue_gap_proxy=proxy,
        )

    # 1. an occupancy needs a known, positive capacity and a night that is not already full
    if target.rooms_available is None:
        return finish(EvaluationStatus.NOT_APPLICABLE, (ReasonCode.OCCUPANCY_INVENTORY_UNKNOWN,))
    if target.rooms_available == 0:
        return finish(EvaluationStatus.NOT_APPLICABLE, (ReasonCode.PROPERTY_CLOSED_FOR_STAY_DATE,))
    if target.rooms_on_books >= target.rooms_available:
        return finish(EvaluationStatus.NOT_APPLICABLE, (ReasonCode.OCCUPANCY_ALREADY_SOLD_OUT,))
    rooms_available = target.rooms_available

    # 2. the Gate 4 baseline the historical pairs hang from
    if target.baseline_status is None:
        return finish(EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.EXPECTED_BASELINE_MISSING,))
    if target.baseline_status != ExpectedStatus.READY:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,)
        )
    if target.baseline_confidence is None:
        raise ValueError("a READY baseline must carry a confidence score")

    # 3. the historical side: at least 5 clean curve pairs
    if selection.pair_count < MIN_PAIRS:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,),
            facts=replace(base, pattern=diagnostic_facts(selection)),
        )

    pattern = analyse(selection)
    confidence = final_confidence(target.baseline_confidence, pattern.confidence.score)
    expected_remaining = pattern.statistics.expected
    raw_forecast = Decimal(target.rooms_on_books) + expected_remaining
    forecast_rooms = max(Decimal(0), raw_forecast)  # the only floor: overbooking is preserved
    expected_final_rooms = other_rooms_median(selection.pairs)
    capacity = Decimal(rooms_available)
    forecast_occupancy_exact = percent_of(forecast_rooms, capacity)
    expected_final_occupancy_exact = percent_of(expected_final_rooms, capacity)
    room_shortfall = max(Decimal(0), expected_final_rooms - forecast_rooms)
    # max(0, final occupancy - forecast occupancy) in ONE division of an exact numerator
    occupancy_gap_pp_exact = percent_of(room_shortfall, capacity)

    # 4. the thresholds, on the full-precision values; the display values are derived AFTER
    status, reasons = classify_occupancy(
        occupancy_gap_pp_exact, room_shortfall, confidence, thresholds
    )
    numeric = status != EvaluationStatus.CLEAR
    return finish(
        status,
        reasons,
        facts=replace(
            base,
            pattern=pattern.facts,
            expected_remaining_net_pickup=expected_remaining,
            raw_forecast_rooms=raw_forecast,
            forecast_rooms=forecast_rooms,
            expected_final_rooms=expected_final_rooms,
            forecast_occupancy=for_display(forecast_occupancy_exact),
            forecast_occupancy_exact=forecast_occupancy_exact,
            expected_final_occupancy=for_display(expected_final_occupancy_exact),
            expected_final_occupancy_exact=expected_final_occupancy_exact,
            occupancy_gap_pp=for_display(occupancy_gap_pp_exact),
            occupancy_gap_pp_exact=occupancy_gap_pp_exact,
            room_shortfall=room_shortfall,
            gap_condition=gap_condition(occupancy_gap_pp_exact, thresholds),
            shortfall_condition=shortfall_condition(room_shortfall, thresholds),
        ),
        confidence=confidence,
        used=selection,
        proxy=revenue_gap_proxy(room_shortfall, reference.value) if numeric else None,
    )

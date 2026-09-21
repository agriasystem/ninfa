"""REV_PICKUP_LOW: the last 7 days brought fewer rooms than this stay night's history says (pure).

    actual_pickup     = rooms now - rooms of the snapshot exactly 7 snapshot days earlier
                        (same stay date, same data source; BOTH snapshots must be OBSERVED)
    expected_pickup   = median over the historical curve pairs of (anchor rooms - rooms 7 days
                        before the anchor), each pair being ONE historical stay date
    delta_rooms       = actual - expected
    missing_rooms     = max(0, expected - actual)
    delta_percent     = (actual - expected) / expected * 100        (only if expected > 0)

Numeric condition (`revenue-decisions-v1`): `delta_percent <= -20` AND `missing_rooms >= 2`,
evaluated on the FULL-PRECISION values the calculation produced (`precision.py`): a pickup of
-19.995 % is displayed as -20.00 but is not -20 % or worse. The two-decimal `delta_percent` of
the facts is for display only and never decides. With the numeric condition true, the final
confidence (MIN of the baseline and the pattern, the authoritative two-decimal score) must be
at least 50 to TRIGGER; below it the evaluation is SUPPRESSED_LOW_CONFIDENCE.

The rule stays silent (NOT_APPLICABLE) when there is nothing to sell: a closed night, or at most 1
room left. It needs an OBSERVED prior snapshot and at least 5 clean historical pairs, otherwise it
is INSUFFICIENT_DATA. Expected pickup <= 0 is NOT_APPLICABLE: a percentage of nothing is undefined
and a night that historically loses rooms is not a pickup shortfall.

Order of the checks (the first that applies decides): closed night, near sold out, baseline,
prior observation, pair sample, non-positive expectation, then the thresholds.
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
from app.modules.intelligence.revenue.types import (
    MIN_PAIRS,
    PICKUP_THRESHOLDS,
    EvaluationStatus,
    PairSelection,
    PickupFacts,
    PickupThresholds,
    ReasonCode,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
    SnapshotPoint,
    TargetContext,
)
from app.modules.snapshots.models import SnapshotOrigin

_ZERO = Decimal("0.00")


def percent_condition(
    delta_percent: Decimal, thresholds: PickupThresholds = PICKUP_THRESHOLDS
) -> bool:
    """`delta_percent <= -20` on the DECISION value: -19.99 and -19.995 do not pass, -20 does."""
    return delta_percent <= thresholds.max_delta_percent


def rooms_condition(
    missing_rooms: Decimal, thresholds: PickupThresholds = PICKUP_THRESHOLDS
) -> bool:
    """`missing_rooms >= 2`: 1.99 does not pass, 2.00 does."""
    return missing_rooms >= thresholds.min_missing_rooms


def classify_pickup(
    delta_percent: Decimal,
    missing_rooms: Decimal,
    confidence: Decimal,
    thresholds: PickupThresholds = PICKUP_THRESHOLDS,
) -> tuple[EvaluationStatus, tuple[ReasonCode, ...]]:
    """The status of a pickup whose expectation is positive: the boundaries live here.

    The arguments are DECISION values (never rounded for display). Both conditions AND the
    confidence gate: 49.99 is suppressed, 50.00 triggers.
    """
    if not (
        percent_condition(delta_percent, thresholds) and rooms_condition(missing_rooms, thresholds)
    ):
        return EvaluationStatus.CLEAR, (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)
    if confidence < thresholds.min_confidence:
        return EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE, (ReasonCode.LOW_CONFIDENCE,)
    return EvaluationStatus.TRIGGERED, (ReasonCode.TRIGGER_PICKUP_SHORTFALL,)


def evaluate_pickup(
    target: TargetContext,
    *,
    prior: SnapshotPoint | None,
    selection: PairSelection,
    reference: ReferenceAdr,
    thresholds: PickupThresholds = PICKUP_THRESHOLDS,
) -> RevenueDecisionEvaluation:
    """REV_PICKUP_LOW for one OBSERVED target.

    `prior` is the snapshot of the same stay date exactly 7 snapshot days earlier (None when it
    does not exist); `selection` are the historical pickup pairs of the target's Gate 4 baseline.
    """
    remaining = (
        None if target.rooms_available is None else target.rooms_available - target.rooms_on_books
    )
    base = PickupFacts(
        current_rooms_on_books=target.rooms_on_books,
        rooms_available=target.rooms_available,
        remaining_capacity=remaining,
        prior_snapshot_id=None if prior is None else prior.snapshot_id,
        prior_origin=None if prior is None else prior.origin,
        prior_rooms_on_books=None if prior is None else prior.rooms_on_books,
        baseline_confidence=target.baseline_confidence,
        thresholds=thresholds,
    )

    def finish(
        status: EvaluationStatus,
        reasons: tuple[ReasonCode, ...],
        *,
        facts: PickupFacts = base,
        confidence: Decimal = _ZERO,
        used: PairSelection | None = None,
        proxy: Decimal | None = None,
    ) -> RevenueDecisionEvaluation:
        return build_evaluation(
            decision_type=RevenueDecisionType.REV_PICKUP_LOW,
            status=status,
            target=target,
            confidence_score=confidence,
            reason_codes=reasons,
            facts=facts,
            evidence_snapshot_ids=evidence_snapshot_ids(
                target.target_snapshot_id,
                prior_snapshot_id=None if prior is None else prior.snapshot_id,
                pairs=() if used is None else used.pairs,
            ),
            reference=reference,
            revenue_gap_proxy=proxy,
        )

    # 1. there is nothing to sell: the rule has no meaning (closed BEFORE near sold out)
    if target.rooms_available == 0:
        return finish(EvaluationStatus.NOT_APPLICABLE, (ReasonCode.PROPERTY_CLOSED_FOR_STAY_DATE,))
    if remaining is not None and remaining <= thresholds.max_remaining_capacity:
        return finish(EvaluationStatus.NOT_APPLICABLE, (ReasonCode.PICKUP_NEAR_SOLD_OUT,))

    # 2. the Gate 4 baseline the historical pairs hang from
    if target.baseline_status is None:
        return finish(EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.EXPECTED_BASELINE_MISSING,))
    if target.baseline_status != ExpectedStatus.READY:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA, (ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,)
        )
    if target.baseline_confidence is None:
        raise ValueError("a READY baseline must carry a confidence score")

    # 3. the current side of the pickup: two OBSERVED snapshots, exactly 7 days apart
    if prior is None or prior.origin != SnapshotOrigin.OBSERVED:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.PICKUP_PRIOR_OBSERVATION_MISSING,),
            facts=replace(base, pattern=diagnostic_facts(selection)),
        )

    # 4. the historical side: at least 5 clean curve pairs
    if selection.pair_count < MIN_PAIRS:
        return finish(
            EvaluationStatus.INSUFFICIENT_DATA,
            (ReasonCode.PAIR_SAMPLE_INSUFFICIENT,),
            facts=replace(base, pattern=diagnostic_facts(selection)),
        )

    pattern = analyse(selection)
    confidence = final_confidence(target.baseline_confidence, pattern.confidence.score)
    actual = target.rooms_on_books - prior.rooms_on_books
    expected = pattern.statistics.expected
    delta_rooms = Decimal(actual) - expected
    missing_rooms = max(Decimal(0), expected - Decimal(actual))

    measured = replace(
        base,
        pattern=pattern.facts,
        actual_pickup=actual,
        expected_pickup=expected,
        delta_rooms=delta_rooms,
        missing_rooms=missing_rooms,
    )

    # 5. a percentage of a non-positive expectation is undefined: never divide by zero
    if expected <= 0:
        return finish(
            EvaluationStatus.NOT_APPLICABLE,
            (ReasonCode.PICKUP_EXPECTATION_NON_POSITIVE,),
            facts=measured,
            confidence=confidence,
            used=selection,
        )

    # 6. the thresholds, on the full-precision value; the display value is derived AFTER
    delta_percent_exact = percent_of(delta_rooms, expected)
    status, reasons = classify_pickup(delta_percent_exact, missing_rooms, confidence, thresholds)
    numeric = status != EvaluationStatus.CLEAR
    return finish(
        status,
        reasons,
        facts=replace(
            measured,
            delta_percent=for_display(delta_percent_exact),
            delta_percent_exact=delta_percent_exact,
            percent_condition=percent_condition(delta_percent_exact, thresholds),
            rooms_condition=rooms_condition(missing_rooms, thresholds),
        ),
        confidence=confidence,
        used=selection,
        proxy=revenue_gap_proxy(missing_rooms, reference.value) if numeric else None,
    )

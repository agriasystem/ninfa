"""MASSERIA NINFA DEMO — PRIORITY V1: the real pipeline, end to end.

    canonical data -> REAL detector services (Gate 5/7/8/9, unmodified) -> TRIGGERED evaluations
    -> PriorityService.rank() -> ranked candidates

`priority_golden_support.py` builds one shared workspace/property and drives
`RevenueDecisionService`/`OtaDependencyService`/`CostDecisionService`/`LaborDecisionService` (the
real production services, over real PostgreSQL rows) to produce the five real TRIGGERED
evaluations, plus a real CLEAR, a real INSUFFICIENT_DATA and a real SUPPRESSED_LOW_CONFIDENCE one
(the last is `test_distribution_golden.py`'s own case F, adapted: a genuine structural OTA
candidate whose historical spread alone drives the baseline confidence under 55). No
`PriorityCandidate`, and no source evaluation, is ever built by hand as a substitute for this
pipeline.

GOLDEN INDEPENDENCE: every expected impact/urgency/actionability/priority-score figure below is
computed by `_tp` (an independent reimplementation of `threshold_progress`, plain `Decimal`, its
own 50-digit context, never imported from `app.modules.intelligence.priority.*`) and by the
literal, documented V1 policy constants (urgency bands, the actionability table) reproduced here
by hand, never by calling `priority.scoring`/`impact`/`urgency`/`actionability`/`ranking`. Only the
detector's OWN already-tested facts (`confidence_score`, `delta_percent_exact`, ...) are read as
input, exactly as the Confidence component itself is defined to do.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.priority.ranking import rank_candidates
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from tests.priority_golden_support import GOLDEN_AS_OF, build_priority_golden_world
from tests.support import BookingFactory

# An INDEPENDENTLY-constructed 50-digit context: the SAME public, documented policy fact
# (`priority.precision.CALCULATION_CONTEXT`'s own prec=50/ROUND_HALF_EVEN), never imported.
_CTX = Context(prec=50, rounding=ROUND_HALF_EVEN)
_ZERO = Decimal(0)
_FIFTY = Decimal(50)
_HUNDRED = Decimal(100)

# The V1 policy tables, reproduced by hand from docs/architecture/priority-engine-v1.md - never
# imported from app.modules.intelligence.priority.types/actionability/urgency.
_ACTIONABILITY = {
    PriorityDecisionType.REV_PICKUP_LOW: Decimal(90),
    PriorityDecisionType.REV_OCCUPANCY_RISK: Decimal(85),
    PriorityDecisionType.REV_OTA_DEPENDENCY: Decimal(60),
    PriorityDecisionType.COST_CPOR_ANOMALY: Decimal(70),
    PriorityDecisionType.LABOR_OVERSTAFFING: Decimal(90),
}


def _tp(value: Decimal, threshold: Decimal, saturation: Decimal) -> Decimal:
    """An independent reimplementation of `threshold_progress` (never imported)."""
    if value <= 0:
        return _ZERO
    if value >= saturation:
        return _HUNDRED
    if value <= threshold:
        return _CTX.divide(_CTX.multiply(value, _FIFTY), threshold)
    span = _CTX.subtract(saturation, threshold)
    offset = _CTX.subtract(value, threshold)
    extra = _CTX.divide(_CTX.multiply(offset, _FIFTY), span)
    return _CTX.add(_FIFTY, extra)


def _forward_urgency(days: int) -> Decimal:
    if days <= 1:
        return Decimal(100)
    if days <= 3:
        return Decimal(90)
    if days <= 7:
        return Decimal(80)
    if days <= 14:
        return Decimal(65)
    if days <= 30:
        return Decimal(50)
    if days <= 60:
        return Decimal(35)
    return Decimal(20)


def _priority(impact: Decimal, urgency: Decimal, confidence: Decimal, action: Decimal) -> Decimal:
    total = _CTX.multiply(Decimal("0.40"), impact)
    total = _CTX.add(total, _CTX.multiply(Decimal("0.25"), urgency))
    total = _CTX.add(total, _CTX.multiply(Decimal("0.20"), confidence))
    return _CTX.add(total, _CTX.multiply(Decimal("0.15"), action))


def test_the_golden_scenario_ranks_five_real_triggered_signals(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build_priority_golden_world(db_session, factory)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, GOLDEN_AS_OF)

    pickup, occupancy = world.revenue_signals()
    orphan = world.orphan_pickup()
    ota_triggered = world.ota_structural()
    ota_clear = world.ota_clear(GOLDEN_AS_OF - timedelta(weeks=30))
    cost = world.cost_anomaly()
    labor = world.labor_overstaffing()
    suppressed = world.ota_suppressed()

    # Sanity: the real pipeline produced exactly the statuses this golden scenario needs.
    assert pickup.status.value == "TRIGGERED"
    assert occupancy.status.value == "TRIGGERED"
    assert ota_triggered.status.value == "TRIGGERED"
    assert cost.status.value == "TRIGGERED"
    assert labor.status.value == "TRIGGERED"
    assert orphan.status.value == "INSUFFICIENT_DATA"
    assert ota_clear.status.value == "CLEAR"
    assert suppressed.status.value == "SUPPRESSED_LOW_CONFIDENCE"

    result = PriorityService().rank(
        context,
        [pickup, occupancy, orphan, ota_triggered, ota_clear, cost, labor, suppressed],
    )

    assert result.candidate_count == 5
    assert result.excluded_clear_count == 1
    assert result.excluded_insufficient_count == 1
    assert result.excluded_suppressed_count == 1
    assert result.excluded_not_applicable_count == 0
    assert result.duplicate_input_count == 0

    # --- independent expected figures, per candidate --------------------------------------

    pickup_impact = min(
        _tp(Decimal(20), Decimal(20), Decimal(40)), _tp(Decimal(2), Decimal(2), Decimal(4))
    )
    pickup_days = (pickup.stay_date - GOLDEN_AS_OF).days
    pickup_expected = _priority(
        pickup_impact,
        _forward_urgency(pickup_days),
        pickup.confidence_score,
        _ACTIONABILITY[PriorityDecisionType.REV_PICKUP_LOW],
    )

    occupancy_impact = max(
        _tp(Decimal(15), Decimal(10), Decimal(20)), _tp(Decimal(6), Decimal(3), Decimal(6))
    )
    occupancy_days = (occupancy.stay_date - GOLDEN_AS_OF).days
    occupancy_expected = _priority(
        occupancy_impact,
        _forward_urgency(occupancy_days),
        occupancy.confidence_score,
        _ACTIONABILITY[PriorityDecisionType.REV_OCCUPANCY_RISK],
    )

    assert ota_triggered.structural_condition is True and ota_triggered.rising_condition is False
    assert ota_triggered.ota_share_exact is not None
    ota_impact = _tp(ota_triggered.ota_share_exact, Decimal(70), Decimal(100))
    ota_expected = _priority(
        ota_impact,
        Decimal(40),  # structural-only urgency policy
        ota_triggered.confidence_score,
        _ACTIONABILITY[PriorityDecisionType.REV_OTA_DEPENDENCY],
    )

    actual_cpor = cost.target_metric.cpor_exact
    assert actual_cpor is not None and cost.upper_fence_exact is not None
    assert cost.delta_percent_exact is not None
    cost_relative = _tp(cost.delta_percent_exact, Decimal(20), Decimal(40))
    cost_robust_ratio = _CTX.divide(actual_cpor, cost.upper_fence_exact)
    cost_robust = _tp(cost_robust_ratio, Decimal(1), Decimal("1.5"))
    cost_impact = min(cost_relative, cost_robust)
    days_since_period_end = (GOLDEN_AS_OF - cost.target_period_end).days
    assert 1 <= days_since_period_end <= 7  # the cost_urgency=70 band this test assumes
    cost_expected = _priority(
        cost_impact,
        Decimal(70),
        cost.confidence_score,
        _ACTIONABILITY[PriorityDecisionType.COST_CPOR_ANOMALY],
    )

    assert labor.delta_percent_exact is not None and labor.excess_hours_exact is not None
    labor_relative = _tp(labor.delta_percent_exact, Decimal(20), Decimal(40))
    labor_hours = _tp(labor.excess_hours_exact, Decimal(4), Decimal(8))
    labor_impact = min(labor_relative, labor_hours)
    labor_days = (labor.target_work_date - GOLDEN_AS_OF).days
    labor_expected = _priority(
        labor_impact,
        _forward_urgency(labor_days),
        labor.confidence_score,
        _ACTIONABILITY[PriorityDecisionType.LABOR_OVERSTAFFING],
    )

    expected_by_type = {
        PriorityDecisionType.REV_PICKUP_LOW: pickup_expected,
        PriorityDecisionType.REV_OCCUPANCY_RISK: occupancy_expected,
        PriorityDecisionType.REV_OTA_DEPENDENCY: ota_expected,
        PriorityDecisionType.COST_CPOR_ANOMALY: cost_expected,
        PriorityDecisionType.LABOR_OVERSTAFFING: labor_expected,
    }

    # --- compare: exact score, display, rank, candidate fingerprint, ranking order ---------

    for ranked in result.ranked_candidates:
        expected = expected_by_type.pop(ranked.candidate.decision_type)
        assert ranked.candidate.priority_score_exact == expected, ranked.candidate.decision_type
        assert ranked.candidate.calculation_fingerprint != ""
    assert expected_by_type == {}  # every decision type was seen exactly once

    # the ranking order follows straight from the five independently-computed exact scores above
    # (89.00 > 87.73... > 75.03... > 69.75 > 55.89...): no two are close enough to need a tie-break.
    actual_order = [ranked.candidate.decision_type for ranked in result.ranked_candidates]
    assert actual_order == [
        PriorityDecisionType.REV_OCCUPANCY_RISK,  # 89.00
        PriorityDecisionType.LABOR_OVERSTAFFING,  # 87.73...
        PriorityDecisionType.COST_CPOR_ANOMALY,  # 75.03...
        PriorityDecisionType.REV_PICKUP_LOW,  # 69.75
        PriorityDecisionType.REV_OTA_DEPENDENCY,  # 55.89...
    ]
    assert [ranked.rank for ranked in result.ranked_candidates] == [1, 2, 3, 4, 5]


def test_explainability_every_fact_behind_a_triggered_candidate_is_present(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build_priority_golden_world(db_session, factory)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, GOLDEN_AS_OF)
    pickup, occupancy = world.revenue_signals()
    result = PriorityService().rank(context, [pickup, occupancy])

    for ranked in result.ranked_candidates:
        candidate = ranked.candidate
        # detector origin and why it was TRIGGERED
        assert candidate.decision_type is not None
        assert candidate.source_reason_codes != ()
        # source target and detector confidence
        assert candidate.source_target_key != ""
        assert candidate.source_evaluation_fingerprint != ""
        assert Decimal(0) <= candidate.confidence_score <= Decimal(100)
        # impact and its raw inputs
        assert candidate.impact_basis != {}
        assert Decimal(0) <= candidate.impact_score_exact <= Decimal(100)
        # urgency and its temporal basis
        assert candidate.urgency_basis != {}
        assert "policy" in candidate.urgency_basis
        # actionability policy
        assert candidate.actionability_policy != ""
        # the exact formula and its rank
        assert candidate.priority_score_exact is not None
        assert ranked.rank >= 1
        # no generated natural-language text anywhere in the candidate: every string value is a
        # stable policy code, never a sentence.
        stable_codes = {"pickup-impact-v1", "occupancy-impact-v1"}
        for value in candidate.impact_basis.values():
            assert not isinstance(value, str) or value in stable_codes
        for value in candidate.urgency_basis.values():
            assert not isinstance(value, str) or value == "forward-urgency-v1"


def test_a_tie_between_two_real_candidates_is_broken_deterministically(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build_priority_golden_world(db_session, factory)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, GOLDEN_AS_OF)
    pickup, occupancy = world.revenue_signals()
    result = PriorityService().rank(context, [pickup, occupancy])
    first, second = (ranked.candidate for ranked in result.ranked_candidates)
    assert {first.decision_type, second.decision_type} == {
        PriorityDecisionType.REV_PICKUP_LOW,
        PriorityDecisionType.REV_OCCUPANCY_RISK,
    }

    tied_score = Decimal(60)
    tied_first = replace(
        first,
        impact_score_exact=tied_score,
        urgency_score=tied_score,
        confidence_score=tied_score,
        actionability_score=tied_score,
        priority_score_exact=tied_score,
    )
    tied_second = replace(
        second,
        impact_score_exact=tied_score,
        urgency_score=tied_score,
        confidence_score=tied_score,
        actionability_score=tied_score,
        priority_score_exact=tied_score,
    )
    ranked = rank_candidates([tied_second, tied_first])
    # REV_OCCUPANCY_RISK sorts before REV_PICKUP_LOW in DECISION_TYPE_TIE_ORDER (key #6), the
    # only thing left to decide once every score is forced equal.
    assert [r.candidate.decision_type for r in ranked] == [
        PriorityDecisionType.REV_OCCUPANCY_RISK,
        PriorityDecisionType.REV_PICKUP_LOW,
    ]


def test_no_triggered_signal_gives_an_empty_ranking(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build_priority_golden_world(db_session, factory)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, GOLDEN_AS_OF)
    orphan = world.orphan_pickup()
    ota_clear = world.ota_clear(GOLDEN_AS_OF - timedelta(weeks=30))

    result = PriorityService().rank(context, [orphan, ota_clear])

    assert result.candidate_count == 0
    assert result.ranked_candidates == ()
    assert result.excluded_insufficient_count == 1
    assert result.excluded_clear_count == 1

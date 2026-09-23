"""Parts N/O/P: structural dependency, rising dependency, combined trigger (pure detector)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.intelligence.distribution.detector import evaluate_ota_dependency
from app.modules.intelligence.distribution.metrics import TargetFacts
from app.modules.intelligence.distribution.selection import ComparableSelection
from app.modules.intelligence.distribution.types import (
    ComparablePeriodFact,
    EvaluationStatus,
    OtaDependencyEvaluation,
    ReasonCode,
)

TARGET_AS_OF = date(2026, 9, 5)
WINDOW_END = TARGET_AS_OF + timedelta(days=29)
WORKSPACE_ID = uuid4()
PROPERTY_ID = uuid4()
SOURCE_ID = uuid4()


def _facts(ota: int, direct: int) -> TargetFacts:
    return TargetFacts(
        reconciled=True,
        observed_day_count=30,
        reconstructed_day_count=0,
        snapshot_provenance_score_exact=Decimal(100),
        ota_room_nights=ota,
        direct_room_nights=direct,
        other_room_nights=0,
        unknown_room_nights=0,
        ota_room_revenue_exact=Decimal(0),
        direct_room_revenue_exact=Decimal(0),
    )


def _period(i: int, ota_share: Decimal) -> ComparablePeriodFact:
    as_of = TARGET_AS_OF - timedelta(weeks=i + 1)
    return ComparablePeriodFact(
        as_of_local_date=as_of,
        window_start=as_of,
        window_end=as_of + timedelta(days=29),
        observed_day_count=30,
        reconstructed_day_count=0,
        snapshot_provenance_score_exact=Decimal(100),
        ota_room_nights=int(ota_share),
        direct_room_nights=100 - int(ota_share),
        other_room_nights=0,
        unknown_room_nights=0,
        classification_coverage_pct_exact=Decimal(100),
        ota_share_exact=ota_share,
    )


def _selection(shares: list[Decimal]) -> ComparableSelection:
    periods = tuple(_period(i, share) for i, share in enumerate(shares))
    return ComparableSelection(
        periods=periods,
        fully_observed_count=len(periods),
        approximate_count=0,
        candidate_period_count=len(periods),
        rejected_snapshot_incomplete_count=0,
        rejected_snapshot_uncertain_count=0,
        rejected_reconciliation_count=0,
        rejected_low_classification_count=0,
        rejected_low_volume_count=0,
    )


def _evaluate(ota: int, direct: int, historical_shares: list[Decimal]) -> OtaDependencyEvaluation:
    selection = _selection(historical_shares)
    return evaluate_ota_dependency(
        workspace_id=WORKSPACE_ID,
        property_id=PROPERTY_ID,
        booking_data_source_id=SOURCE_ID,
        as_of_local_date=TARGET_AS_OF,
        window_start=TARGET_AS_OF,
        window_end=WINDOW_END,
        target_window_complete=True,
        target_any_uncertain=False,
        target_facts=_facts(ota, direct),
        select=lambda: selection,
    )


_FLAT_HISTORY_69_9 = [Decimal("69.9")] * 6
_FLAT_HISTORY_70 = [Decimal(70)] * 6
_FLAT_HISTORY_80 = [Decimal(80)] * 6


# --- N: structural dependency ---------------------------------------------------------------------


def test_69_9_percent_is_not_structural() -> None:
    evaluation = _evaluate(699, 301, _FLAT_HISTORY_69_9)
    assert evaluation.structural_condition is False
    assert evaluation.status != EvaluationStatus.TRIGGERED


def test_70_percent_exact_is_structural() -> None:
    evaluation = _evaluate(70, 30, _FLAT_HISTORY_70)
    assert evaluation.structural_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)


def test_historically_80_actual_80_can_still_trigger_structurally() -> None:
    """Structural dependency does not require the share to have RISEN: a property historically
    at 80% OTA is still structurally dependent today, even with zero delta."""
    evaluation = _evaluate(80, 20, _FLAT_HISTORY_80)
    assert evaluation.delta_pp_exact == 0
    assert evaluation.structural_condition is True
    assert evaluation.rising_condition is False  # the gap condition alone already fails
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)


# --- O: rising dependency ------------------------------------------------------------------------


def test_share_of_54_99_is_not_rising() -> None:
    # Historical median low enough that gap/fence would pass if share crossed 55.
    evaluation = _evaluate(5499, 4501, [Decimal(30)] * 6)  # 54.99% share
    assert evaluation.rising_condition is False


def test_share_of_55_exact_can_be_rising() -> None:
    # historical median 30, flat (IQR=0, fence=30): 55 >= 55, gap=25>=15, 55>=fence(30).
    evaluation = _evaluate(55, 45, [Decimal(30)] * 6)
    assert evaluation.rising_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_RISING_OTA_DEPENDENCY,)


def test_gap_of_14_99_points_is_not_rising() -> None:
    # median 40.01, actual 55 -> gap 14.99 (< 15). above the min-share and the fence (IQR=0).
    evaluation = _evaluate(5500, 4500, [Decimal("40.01")] * 6)
    assert evaluation.rising_condition is False


def test_gap_of_exactly_15_points_is_rising() -> None:
    # median 40, actual 55 -> gap exactly 15.
    evaluation = _evaluate(55, 45, [Decimal(40)] * 6)
    assert evaluation.delta_pp_exact == 15
    assert evaluation.rising_condition is True


def test_below_the_upper_fence_is_not_rising_even_at_100_percent_share() -> None:
    """A volatile history can push the fence past 100 (the spec's own point: it is a pure
    statistic, never clamped): historical [10,10,10,50,50] gives P25=10, P75=50 (position 3
    lands exactly on the second "50"), IQR=40, fence=50+1.5*40=110. Even a 100% OTA target -
    the maximum a share can ever be - stays below that fence, so rising never fires."""
    shares = [Decimal(10), Decimal(10), Decimal(10), Decimal(50), Decimal(50)]
    evaluation = _evaluate(100, 0, shares)  # 100% OTA share: the ceiling of what a share can be
    assert evaluation.upper_fence_exact == 110
    assert evaluation.ota_share_exact == 100
    assert evaluation.rising_condition is False


def test_equal_to_the_upper_fence_can_be_rising() -> None:
    # [30,30,30,45,45]: median=30, P25=30 (pos 1), P75=45 (pos 3), IQR=15, fence=45+22.5=67.5.
    # 27/40=67.5% exactly: equals the fence, gap=37.5>=15, share=67.5>=55 - all three, at "=".
    shares = [Decimal(30), Decimal(30), Decimal(30), Decimal(45), Decimal(45)]
    evaluation = _evaluate(27, 13, shares)
    assert evaluation.upper_fence_exact == Decimal("67.5")
    assert evaluation.ota_share_exact == evaluation.upper_fence_exact
    assert evaluation.rising_condition is True


def test_all_three_rising_conditions_are_required_together() -> None:
    """>=55% share alone, without the gap, is not rising."""
    evaluation = _evaluate(56, 44, [Decimal(50)] * 6)  # share 56, gap only 6pp
    assert evaluation.rising_condition is False
    assert evaluation.status != EvaluationStatus.TRIGGERED


def test_historical_35_actual_60_is_a_rising_example() -> None:
    evaluation = _evaluate(60, 40, [Decimal(35)] * 6)
    assert evaluation.structural_condition is False  # 60 < 70
    assert evaluation.rising_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_RISING_OTA_DEPENDENCY,)


# --- P: combined trigger -------------------------------------------------------------------------


def test_structural_only_reason() -> None:
    evaluation = _evaluate(70, 30, _FLAT_HISTORY_70)  # delta 0: never rising
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,)


def test_rising_only_reason() -> None:
    evaluation = _evaluate(60, 40, [Decimal(35)] * 6)  # 60 < 70: never structural
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_RISING_OTA_DEPENDENCY,)


def test_both_structural_and_rising_reason() -> None:
    evaluation = _evaluate(75, 25, [Decimal(45)] * 6)  # 75>=70 AND 75-45=30>=15, 75>=fence
    assert evaluation.structural_condition is True
    assert evaluation.rising_condition is True
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY,)


def test_neither_condition_is_clear() -> None:
    evaluation = _evaluate(50, 50, [Decimal(48)] * 6)
    assert evaluation.structural_condition is False
    assert evaluation.rising_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)

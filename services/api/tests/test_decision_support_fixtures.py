"""The shared decision fixtures must tell ONE story: the OTA evaluation helper once carried 24 OTA +
10 direct room-nights next to a 72.22 % (or 75.00 %, or 40.00 %) share, which Mia's real-model
smoke test surfaced as numbers that could not both be true. Counts and shares now agree by
construction; this pins it so a future edit of the helper cannot quietly reopen the gap.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import pytest

from app.modules.intelligence.distribution.types import EvaluationStatus
from tests.decision_support import CLEAR, INSUFFICIENT, SUPPRESSED, TRIGGERED, ota_evaluation

CENT = Decimal("0.01")


def _share(part: int, whole: int) -> Decimal:
    return (Decimal(part) * 100 / Decimal(whole)).quantize(CENT, rounding=ROUND_HALF_UP)


@pytest.mark.parametrize(
    ("status", "ota_share"),
    [
        (TRIGGERED, Decimal("75.00")),
        (TRIGGERED, Decimal("72.22")),
        (TRIGGERED, Decimal("66.67")),
        (CLEAR, Decimal("75.00")),  # a non-triggered evaluation reports 40.00 whatever is asked
        (SUPPRESSED, Decimal("75.00")),
        (INSUFFICIENT, Decimal("75.00")),
    ],
)
def test_ota_evaluation_room_night_counts_reproduce_the_reported_share(
    status: EvaluationStatus, ota_share: Decimal
) -> None:
    evaluation = ota_evaluation(
        workspace_id=uuid4(),
        property_id=uuid4(),
        booking_data_source_id=uuid4(),
        as_of_local_date=date(2026, 8, 1),
        status=status,
        ota_share=ota_share,
    )

    ota, direct = evaluation.ota_room_nights, evaluation.direct_room_nights
    other, unknown = evaluation.other_room_nights, evaluation.unknown_room_nights
    classified, certain = evaluation.classified_room_nights, evaluation.certain_room_nights
    assert None not in (ota, direct, other, unknown, classified, certain)
    assert ota is not None and direct is not None and other is not None and unknown is not None
    assert classified is not None and certain is not None

    assert classified == ota + direct + other
    assert certain == classified + unknown
    assert evaluation.ota_share_exact == _share(ota, ota + direct)
    assert evaluation.direct_share_exact == _share(direct, ota + direct)
    assert evaluation.ota_share_exact is not None and evaluation.direct_share_exact is not None
    assert evaluation.ota_share_exact + evaluation.direct_share_exact == Decimal(100)
    # every room-night is classified, so the reported classification coverage is 100 %
    assert evaluation.classification_coverage_pct_exact == _share(classified, certain)


def test_a_share_that_is_not_a_whole_number_of_room_nights_is_refused() -> None:
    with pytest.raises(ValueError, match="whole number of room-nights"):
        ota_evaluation(
            workspace_id=uuid4(),
            property_id=uuid4(),
            booking_data_source_id=uuid4(),
            as_of_local_date=date(2026, 8, 1),
            ota_share=Decimal("72.2222"),
        )

"""Baseline confidence and the final confidence of LABOR_OVERSTAFFING (pure).

The BASELINE confidence (`labor-expected-v1`) says how much the historical comparable days can be
trusted. Components, each 0-100:

    sample_score          = min(100, n / 12 * 100)
    provenance_score      = mean of the used days' pair quality (100 / 80 / 80 / 60)
    classification_score  = mean of their weighted category classification confidences (a day
                            whose confidence is unknown counts as 0)
    stability_score       = max(0, 100 - 50 * IQR / max(|expected hours|, 1))

    baseline_confidence = 0.35 * sample + 0.25 * provenance + 0.15 * classification
                          + 0.25 * stability                              (HALF_UP, 2 decimals)

Caps, applied AFTER the formula and BEFORE the final minimum: any used day that is not fully
observed -> at most 85; no fully observed day among the used ones -> at most 65.

The FINAL confidence is the MINIMUM of the (capped) baseline confidence, the demand confidence and
the target plan quality, never their average: a decision is only as reliable as its weakest input.
The gate is 55. Component scores stay at full precision (they are facts); the headline scores are
the authoritative two-decimal values the gates compare.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.intelligence.labor.precision import CALCULATION_CONTEXT, exact_sum, for_display
from app.modules.intelligence.labor.types import SAMPLE_SATURATION, ComparableDayFact

_HUNDRED = Decimal(100)
_ONE = Decimal(1)

WEIGHT_SAMPLE = Decimal("0.35")
WEIGHT_PROVENANCE = Decimal("0.25")
WEIGHT_CLASSIFICATION = Decimal("0.15")
WEIGHT_STABILITY = Decimal("0.25")
STABILITY_PENALTY = Decimal(50)
CAP_WITH_APPROXIMATE_DAY = Decimal(85)
CAP_WITHOUT_OBSERVED_DAY = Decimal(65)


@dataclass(frozen=True, slots=True)
class BaselineConfidence:
    score: Decimal  # HALF_UP two decimals, after the caps
    sample_score: Decimal
    provenance_score: Decimal
    classification_score: Decimal
    stability_score: Decimal
    cap: Decimal | None  # the cap that applied (the lowest one), if any


def _mul(left: Decimal, right: Decimal) -> Decimal:
    return CALCULATION_CONTEXT.multiply(left, right)


def sample_score(sample_count: int, saturation: int = SAMPLE_SATURATION) -> Decimal:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    scaled = CALCULATION_CONTEXT.divide(_mul(Decimal(sample_count), _HUNDRED), Decimal(saturation))
    return min(_HUNDRED, scaled)


def provenance_score(days: Sequence[ComparableDayFact]) -> Decimal:
    if not days:
        raise ValueError("a provenance score needs at least one day")
    total = exact_sum(day.pair_quality for day in days)
    return CALCULATION_CONTEXT.divide(total, Decimal(len(days)))


def classification_score(days: Sequence[ComparableDayFact]) -> Decimal:
    """Plain mean of the used days' weighted category classification confidences.

    A day whose confidence is unknown (nothing of the category was classified) counts as 0:
    nothing is assumed in its favour.
    """
    if not days:
        raise ValueError("a classification score needs at least one day")
    confidences = [day.weighted_category_confidence_exact or Decimal(0) for day in days]
    return CALCULATION_CONTEXT.divide(exact_sum(confidences), Decimal(len(confidences)))


def stability_score(iqr: Decimal, expected_hours: Decimal) -> Decimal:
    scale = max(expected_hours.copy_abs(), _ONE)
    penalty = _mul(STABILITY_PENALTY, CALCULATION_CONTEXT.divide(iqr, scale))
    return max(Decimal(0), CALCULATION_CONTEXT.subtract(_HUNDRED, penalty))


def baseline_confidence(
    days: Sequence[ComparableDayFact], *, iqr: Decimal, expected_hours: Decimal
) -> BaselineConfidence:
    sample = sample_score(len(days))
    provenance = provenance_score(days)
    classification = classification_score(days)
    stability = stability_score(iqr, expected_hours)
    raw = exact_sum(
        (
            _mul(WEIGHT_SAMPLE, sample),
            _mul(WEIGHT_PROVENANCE, provenance),
            _mul(WEIGHT_CLASSIFICATION, classification),
            _mul(WEIGHT_STABILITY, stability),
        )
    )
    score = for_display(raw)
    caps: list[Decimal] = []
    if any(not day.is_fully_observed for day in days):
        caps.append(CAP_WITH_APPROXIMATE_DAY)
    if not any(day.is_fully_observed for day in days):
        caps.append(CAP_WITHOUT_OBSERVED_DAY)
    cap = min(caps) if caps else None
    if cap is not None:
        score = min(score, cap)
    return BaselineConfidence(score, sample, provenance, classification, stability, cap)


def final_confidence(
    baseline: Decimal, demand_confidence: Decimal, target_plan_quality: Decimal
) -> Decimal:
    """The conservative confidence of an evaluation: MIN of the three, never their average."""
    return min(baseline, demand_confidence, target_plan_quality)

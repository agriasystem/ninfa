"""Baseline confidence, target quality and the final confidence of COST_CPOR_ANOMALY (pure).

The BASELINE confidence (`cost-cpor-expected-v1`) says how much the historical CPORs can be
trusted, in the transparent spirit of the Gate 4 / Gate 5 confidences. Components, each 0-100:

    sample_score          = min(100, n / 8 * 100)
    provenance_score      = mean of the occupancy provenance scores of the used months
    classification_score  = mean of their weighted classification confidences, WEIGHTED by each
                            month's absolute category cost (a month with more money behind it
                            weighs more; if every weight is zero the plain mean is used)
    stability_score       = max(0, 100 - 50 * IQR / max(|expected CPOR|, 0.01))

    baseline_confidence = 0.35 * sample + 0.25 * provenance + 0.20 * classification
                          + 0.20 * stability                              (HALF_UP, 2 decimals)

Caps, applied AFTER the formula and BEFORE the final minimum: any used month with a reconstructed
day -> at most 85; no fully observed month among the used ones -> at most 65.

The TARGET quality is measured on the month being judged:

    target_quality = 0.50 * target occupancy provenance + 0.50 * target weighted classification
                     confidence                                            (HALF_UP, 2 decimals)

The FINAL confidence is the MINIMUM of the (capped) baseline confidence and the target quality,
never their average: a decision is only as reliable as its weakest input. The gate is 55.
The constants belong to the rules version: changing one means a new version. The component
scores stay at full precision (they are facts); the three headline scores are the authoritative
two-decimal values the gates compare.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.intelligence.costs.precision import CALCULATION_CONTEXT, exact_sum, for_display
from app.modules.intelligence.costs.statistics import CporStatistics
from app.modules.intelligence.costs.types import (
    SAMPLE_SATURATION,
    ComparablePeriodFact,
    CostPeriodMetric,
)

_HUNDRED = Decimal(100)

WEIGHT_SAMPLE = Decimal("0.35")
WEIGHT_PROVENANCE = Decimal("0.25")
WEIGHT_CLASSIFICATION = Decimal("0.20")
WEIGHT_STABILITY = Decimal("0.20")
STABILITY_PENALTY = Decimal(50)
STABILITY_FLOOR = Decimal("0.01")  # the smallest |expected CPOR| the relative IQR divides by
CAP_WITH_APPROXIMATE_PERIOD = Decimal(85)
CAP_WITHOUT_OBSERVED_PERIOD = Decimal(65)
TARGET_WEIGHT_PROVENANCE = Decimal("0.50")
TARGET_WEIGHT_CLASSIFICATION = Decimal("0.50")


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


def provenance_score(periods: Sequence[ComparablePeriodFact]) -> Decimal:
    if not periods:
        raise ValueError("a provenance score needs at least one month")
    total = exact_sum(p.occupancy_provenance_score_exact for p in periods)
    return CALCULATION_CONTEXT.divide(total, Decimal(len(periods)))


def classification_score(periods: Sequence[ComparablePeriodFact]) -> Decimal:
    """Exposure-weighted mean of the months' weighted classification confidences.

    A month whose confidence is unknown counts as 0 (nothing is assumed in its favour). If the
    total weight is zero the plain mean is used, so the score is always defined.
    """
    if not periods:
        raise ValueError("a classification score needs at least one month")
    confidences = [p.weighted_classification_confidence_exact or Decimal(0) for p in periods]
    weights = [p.absolute_category_cost for p in periods]
    total_weight = exact_sum(weights)
    if total_weight > 0:
        weighted = exact_sum(_mul(c, w) for c, w in zip(confidences, weights, strict=True))
        return CALCULATION_CONTEXT.divide(weighted, total_weight)
    return CALCULATION_CONTEXT.divide(exact_sum(confidences), Decimal(len(confidences)))


def stability_score(iqr: Decimal, expected_cpor: Decimal) -> Decimal:
    scale = max(expected_cpor.copy_abs(), STABILITY_FLOOR)
    penalty = _mul(STABILITY_PENALTY, CALCULATION_CONTEXT.divide(iqr, scale))
    return max(Decimal(0), CALCULATION_CONTEXT.subtract(_HUNDRED, penalty))


def baseline_confidence(
    periods: Sequence[ComparablePeriodFact], statistics: CporStatistics
) -> BaselineConfidence:
    sample = sample_score(len(periods))
    provenance = provenance_score(periods)
    classification = classification_score(periods)
    stability = stability_score(statistics.iqr, statistics.median)
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
    if any(not p.is_fully_observed for p in periods):
        caps.append(CAP_WITH_APPROXIMATE_PERIOD)
    if not any(p.is_fully_observed for p in periods):
        caps.append(CAP_WITHOUT_OBSERVED_PERIOD)
    cap = min(caps) if caps else None
    if cap is not None:
        score = min(score, cap)
    return BaselineConfidence(score, sample, provenance, classification, stability, cap)


def target_quality(metric: CostPeriodMetric) -> Decimal:
    """The quality of the month being judged (HALF_UP, two decimals)."""
    provenance = metric.occupancy_provenance_score_exact
    classification = metric.weighted_classification_confidence_exact
    if provenance is None or classification is None:
        raise ValueError("target quality needs a READY metric")
    raw = CALCULATION_CONTEXT.add(
        _mul(TARGET_WEIGHT_PROVENANCE, provenance),
        _mul(TARGET_WEIGHT_CLASSIFICATION, classification),
    )
    return for_display(raw)


def final_confidence(baseline: Decimal, target: Decimal) -> Decimal:
    """The conservative confidence of an evaluation: MIN(baseline, target), never the average."""
    return min(baseline, target)

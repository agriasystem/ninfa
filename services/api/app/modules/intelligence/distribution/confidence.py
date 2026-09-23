"""Baseline confidence, target quality and the final confidence of REV_OTA_DEPENDENCY (pure).

The BASELINE confidence (`ota-share-expected-v1`) says how much the historical comparable
periods can be trusted. Components, each 0-100:

    sample_score          = min(100, n / 12 * 100)
    provenance_score      = mean of the used periods' snapshot_provenance_score
    classification_score  = mean of their classification_coverage_pct
    stability_score        = max(0, 100 - 50 * IQR / max(expected_ota_share, 1))

    baseline_confidence = 0.35 * sample + 0.25 * provenance + 0.20 * classification
                          + 0.20 * stability                              (HALF_UP, 2 decimals)

Caps, applied AFTER the formula and BEFORE the final minimum: any used period that is not fully
observed -> at most 85; no fully observed period among the used ones -> at most 65.

TARGET QUALITY (the target 30-day window's own reliability, not the history's):

    target_quality = 0.50 * target.snapshot_provenance_score + 0.50 * target.classification_
                      coverage_pct                                        (HALF_UP, 2 decimals)

The FINAL confidence is the MINIMUM of the (capped) baseline confidence and the target quality,
never their average: a decision is only as reliable as its weakest input. The gate is 55.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.intelligence.distribution.precision import (
    CALCULATION_CONTEXT,
    exact_sum,
    for_display,
)
from app.modules.intelligence.distribution.types import SAMPLE_SATURATION, ComparablePeriodFact

_HUNDRED = Decimal(100)
_ONE = Decimal(1)

WEIGHT_SAMPLE = Decimal("0.35")
WEIGHT_PROVENANCE = Decimal("0.25")
WEIGHT_CLASSIFICATION = Decimal("0.20")
WEIGHT_STABILITY = Decimal("0.20")
STABILITY_PENALTY = Decimal(50)
CAP_WITH_APPROXIMATE_PERIOD = Decimal(85)
CAP_WITHOUT_OBSERVED_PERIOD = Decimal(65)

TARGET_WEIGHT_PROVENANCE = Decimal("0.50")
TARGET_WEIGHT_COVERAGE = Decimal("0.50")


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
        raise ValueError("a provenance score needs at least one period")
    total = exact_sum(period.snapshot_provenance_score_exact for period in periods)
    return CALCULATION_CONTEXT.divide(total, Decimal(len(periods)))


def classification_score(periods: Sequence[ComparablePeriodFact]) -> Decimal:
    """Plain mean of the used periods' classification coverage. Not a probability."""
    if not periods:
        raise ValueError("a classification score needs at least one period")
    coverages = [period.classification_coverage_pct_exact for period in periods]
    return CALCULATION_CONTEXT.divide(exact_sum(coverages), Decimal(len(coverages)))


def stability_score(iqr: Decimal, expected_ota_share: Decimal) -> Decimal:
    scale = max(expected_ota_share.copy_abs(), _ONE)
    penalty = _mul(STABILITY_PENALTY, CALCULATION_CONTEXT.divide(iqr, scale))
    return max(Decimal(0), CALCULATION_CONTEXT.subtract(_HUNDRED, penalty))


def baseline_confidence(
    periods: Sequence[ComparablePeriodFact], *, iqr: Decimal, expected_ota_share: Decimal
) -> BaselineConfidence:
    sample = sample_score(len(periods))
    provenance = provenance_score(periods)
    classification = classification_score(periods)
    stability = stability_score(iqr, expected_ota_share)
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
    if any(not period.is_fully_observed for period in periods):
        caps.append(CAP_WITH_APPROXIMATE_PERIOD)
    if not any(period.is_fully_observed for period in periods):
        caps.append(CAP_WITHOUT_OBSERVED_PERIOD)
    cap = min(caps) if caps else None
    if cap is not None:
        score = min(score, cap)
    return BaselineConfidence(score, sample, provenance, classification, stability, cap)


def target_quality(
    snapshot_provenance_score: Decimal, classification_coverage_pct: Decimal
) -> Decimal:
    raw = exact_sum(
        (
            _mul(TARGET_WEIGHT_PROVENANCE, snapshot_provenance_score),
            _mul(TARGET_WEIGHT_COVERAGE, classification_coverage_pct),
        )
    )
    return for_display(raw)


def final_confidence(baseline: Decimal, target: Decimal) -> Decimal:
    """The conservative confidence of an evaluation: MIN of the two, never their average."""
    return min(baseline, target)

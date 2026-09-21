"""Curve-pattern confidence and the final confidence of a decision evaluation (pure, `Decimal`).

The PATTERN confidence (`revenue-curve-pattern-v1`) says how much the historical pairs can be
trusted, in the same transparent spirit as the baseline confidence of Gate 4:

    sample_score      = min(100, pairs / 12 * 100)
    provenance_score  = (observed_pairs * 100 + approximate_pairs * 60) / pairs
    relative_iqr      = IQR / max(abs(median), 1)
    stability_score   = max(0, 100 - 50 * relative_iqr)
    pattern_confidence = 0.40 * sample + 0.35 * provenance + 0.25 * stability   (HALF_UP, 2 dp)

The median of a delta can be negative (a remaining net pickup) or zero, hence `abs`. Caps, applied
AFTER the formula: any approximate pair -> at most 85; no observed pair at all -> at most 65.

The FINAL confidence of an evaluation is the MINIMUM of the Gate 4 baseline confidence and the
pattern confidence, never their average: a decision is only as reliable as its weakest input.
The constants belong to `PATTERN_VERSION`: changing one means a new version.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_HUNDRED = Decimal(100)
_TWO_PLACES = Decimal("0.01")

SAMPLE_SATURATION = 12  # 12 pairs earn the full sample score
OBSERVED_PAIR_QUALITY = Decimal(100)
APPROXIMATE_PAIR_QUALITY = Decimal(60)
STABILITY_PENALTY = Decimal(50)
WEIGHT_SAMPLE = Decimal("0.40")
WEIGHT_PROVENANCE = Decimal("0.35")
WEIGHT_STABILITY = Decimal("0.25")
CAP_WITH_APPROXIMATE_PAIR = Decimal(85)
CAP_WITHOUT_OBSERVED_PAIR = Decimal(65)


@dataclass(frozen=True, slots=True)
class PatternConfidence:
    score: Decimal
    sample_score: Decimal
    provenance_score: Decimal
    stability_score: Decimal


def sample_score(pair_count: int) -> Decimal:
    if pair_count <= 0:
        raise ValueError("pair_count must be positive")
    return min(_HUNDRED, Decimal(pair_count) * _HUNDRED / Decimal(SAMPLE_SATURATION))


def provenance_score(observed_pairs: int, approximate_pairs: int) -> Decimal:
    total = observed_pairs + approximate_pairs
    if total <= 0 or observed_pairs < 0 or approximate_pairs < 0:
        raise ValueError("a provenance score needs a positive number of pairs")
    weighted = (
        Decimal(observed_pairs) * OBSERVED_PAIR_QUALITY
        + Decimal(approximate_pairs) * APPROXIMATE_PAIR_QUALITY
    )
    return weighted / Decimal(total)


def stability_score(iqr: Decimal, median: Decimal) -> Decimal:
    relative_iqr = iqr / max(abs(median), Decimal(1))
    return min(_HUNDRED, max(Decimal(0), _HUNDRED - STABILITY_PENALTY * relative_iqr))


def pattern_confidence(
    observed_pairs: int, approximate_pairs: int, iqr: Decimal, median: Decimal
) -> PatternConfidence:
    sample = sample_score(observed_pairs + approximate_pairs)
    provenance = provenance_score(observed_pairs, approximate_pairs)
    stability = stability_score(iqr, median)
    raw = WEIGHT_SAMPLE * sample + WEIGHT_PROVENANCE * provenance + WEIGHT_STABILITY * stability
    score = raw.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    if approximate_pairs > 0:
        score = min(score, CAP_WITH_APPROXIMATE_PAIR)
    if observed_pairs == 0:
        score = min(score, CAP_WITHOUT_OBSERVED_PAIR)
    return PatternConfidence(score, sample, provenance, stability)


def final_confidence(baseline_confidence: Decimal, pattern: Decimal) -> Decimal:
    """The conservative confidence of an evaluation: MIN(baseline, pattern), never the average."""
    return min(baseline_confidence, pattern)

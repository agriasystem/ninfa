"""Baseline confidence V1 (pure functions, `Decimal` only).

This is the confidence of a HISTORICAL BASELINE, not the general Decision Confidence. It is a
transparent, versioned heuristic, not a statistical truth:

    sample_score      = min(100, sample_size / 12 * 100)
    provenance_score  = (observed * 100 + reconstructed * 60) / sample_size
    relative_iqr      = IQR / max(expected, 1)
    stability_score   = max(0, 100 - 50 * relative_iqr)
    confidence        = 0.40 * sample + 0.35 * provenance + 0.25 * stability   (HALF_UP, 2 dp)

Caps, applied AFTER the formula: any reconstructed comparable used -> at most 85; no observed
comparable at all -> at most 65. Bands: HIGH >= 80, MEDIUM >= 60, LOW below. A READY baseline can
therefore be LOW; INSUFFICIENT_DATA has no score at all (0, no band) and never a "LOW".

Components are kept at full `Decimal` precision and only the final score is rounded.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

_HUNDRED = Decimal(100)
_TWO_PLACES = Decimal("0.01")

SAMPLE_SATURATION = 12  # a sample of 12 comparables earns the full sample score
OBSERVED_QUALITY = Decimal(100)
RECONSTRUCTED_QUALITY = Decimal(60)
STABILITY_PENALTY = Decimal(50)
WEIGHT_SAMPLE = Decimal("0.40")
WEIGHT_PROVENANCE = Decimal("0.35")
WEIGHT_STABILITY = Decimal("0.25")
CAP_WITH_RECONSTRUCTED = Decimal(85)
CAP_WITHOUT_OBSERVED = Decimal(65)
BAND_HIGH_FROM = Decimal(80)
BAND_MEDIUM_FROM = Decimal(60)


class ConfidenceBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class Confidence:
    score: Decimal
    band: ConfidenceBand
    sample_score: Decimal
    provenance_score: Decimal
    stability_score: Decimal


def sample_score(sample_size: int) -> Decimal:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    return min(_HUNDRED, Decimal(sample_size) * _HUNDRED / Decimal(SAMPLE_SATURATION))


def provenance_score(observed: int, reconstructed: int) -> Decimal:
    total = observed + reconstructed
    if total <= 0 or observed < 0 or reconstructed < 0:
        raise ValueError("a provenance score needs a positive sample")
    weighted = Decimal(observed) * OBSERVED_QUALITY + Decimal(reconstructed) * RECONSTRUCTED_QUALITY
    return weighted / Decimal(total)


def stability_score(iqr: Decimal, expected: Decimal) -> Decimal:
    relative_iqr = iqr / max(expected, Decimal(1))
    return min(_HUNDRED, max(Decimal(0), _HUNDRED - STABILITY_PENALTY * relative_iqr))


def band_for(score: Decimal) -> ConfidenceBand:
    if score >= BAND_HIGH_FROM:
        return ConfidenceBand.HIGH
    if score >= BAND_MEDIUM_FROM:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def confidence(observed: int, reconstructed: int, iqr: Decimal, expected: Decimal) -> Confidence:
    sample = sample_score(observed + reconstructed)
    provenance = provenance_score(observed, reconstructed)
    stability = stability_score(iqr, expected)
    raw = WEIGHT_SAMPLE * sample + WEIGHT_PROVENANCE * provenance + WEIGHT_STABILITY * stability
    score = raw.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    if reconstructed > 0:
        score = min(score, CAP_WITH_RECONSTRUCTED)
    if observed == 0:
        score = min(score, CAP_WITHOUT_OBSERVED)
    return Confidence(score, band_for(score), sample, provenance, stability)

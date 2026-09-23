"""Deterministic role classification V1: a category, a confidence and where it came from.

Priority (no AI, no fuzzy category matching, mirrors `invoices.classification`):

  1. the category the SOURCE states, validated                EXPLICIT_SOURCE   confidence 100
  2. the role mapping saved in the LaborMappingProfile         ROLE_MAPPING      confidence  95
  3. a small high-precision phrase dictionary                  DETERMINISTIC_RULE confidence 80
  4. nothing safe: OTHER                                       UNCLASSIFIED      confidence   0

The confidence is PROVENANCE/QUALITY of the classification, not a statistical probability. A role
that matches the phrases of two different categories is ambiguous and stays OTHER: it is better
not to classify than to classify wrongly.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.modules.labor.roles import LaborCategory, LaborClassificationMethod

CLASSIFICATION_VERSION = "labor-classification-v1"

CONFIDENCE_EXPLICIT = Decimal("100.00")
CONFIDENCE_ROLE_MAPPING = Decimal("95.00")
CONFIDENCE_RULE = Decimal("80.00")
CONFIDENCE_UNCLASSIFIED = Decimal("0.00")

# Phrases are matched as whole words inside the normalised role (`normalize_key`): lower case, no
# accents, punctuation as spaces. Deliberately small; add a phrase only when it cannot mean
# anything else. Better not to classify than to classify wrongly.
RULES: dict[LaborCategory, tuple[str, ...]] = {
    LaborCategory.HOUSEKEEPING: (
        "housekeeping",
        "camera",
        "cameriera ai piani",
        "piani",
    ),
    LaborCategory.FRONT_OFFICE: (
        "reception",
        "front office",
        "receptionist",
    ),
    LaborCategory.FOOD_BEVERAGE: (
        "sala",
        "waiter",
        "cameriere",
        "bar",
    ),
    LaborCategory.KITCHEN: (
        "kitchen",
        "cucina",
        "chef",
        "cuoco",
    ),
    LaborCategory.MAINTENANCE: (
        "maintenance",
        "manutenzione",
    ),
    LaborCategory.SPA_WELLNESS: (
        "spa",
        "wellness",
    ),
    LaborCategory.MANAGEMENT: (
        "direzione",
        "management",
    ),
}


@dataclass(frozen=True, slots=True)
class Classification:
    category: LaborCategory
    confidence: Decimal
    method: LaborClassificationMethod


def _contains(role: str, phrase: str) -> bool:
    return f" {phrase} " in f" {role} "


def matching_categories(role_normalized: str) -> list[LaborCategory]:
    """Every category whose phrases appear in the role (in the dictionary's order)."""
    return [
        category
        for category, phrases in RULES.items()
        if any(_contains(role_normalized, phrase) for phrase in phrases)
    ]


def classify_role(
    role_normalized: str | None,
    *,
    explicit: LaborCategory | None = None,
    role_mapping: Mapping[str, LaborCategory] | None = None,
) -> Classification:
    """Classify one entry. `role_normalized` is `normalize_key(role_raw)`, or None when no role
    was mapped (the category must then come from an explicit source value)."""
    if explicit is not None:
        return Classification(
            explicit, CONFIDENCE_EXPLICIT, LaborClassificationMethod.EXPLICIT_SOURCE
        )
    if role_normalized:
        mapped = (role_mapping or {}).get(role_normalized)
        if mapped is not None:
            return Classification(
                mapped, CONFIDENCE_ROLE_MAPPING, LaborClassificationMethod.ROLE_MAPPING
            )
        matches = matching_categories(role_normalized)
        if len(matches) == 1:
            return Classification(
                matches[0], CONFIDENCE_RULE, LaborClassificationMethod.DETERMINISTIC_RULE
            )
    return Classification(
        LaborCategory.OTHER, CONFIDENCE_UNCLASSIFIED, LaborClassificationMethod.UNCLASSIFIED
    )

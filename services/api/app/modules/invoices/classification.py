"""Deterministic line classification V1: a category, a confidence and where it came from.

Priority (no AI, no fuzzy category matching):

  1. the category the SOURCE states, validated and mapped   EXPLICIT_SOURCE      confidence 100
  2. the supplier's default cost category                   SUPPLIER_DEFAULT     confidence  90
  3. a small high-precision phrase dictionary               DETERMINISTIC_RULE   confidence  80
  4. nothing safe: OTHER                                     UNCLASSIFIED         confidence   0

The confidence is PROVENANCE/QUALITY of the classification, not a statistical probability. A
description that matches the phrases of two different categories is ambiguous and stays OTHER:
it is better not to classify than to classify wrongly.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory

CLASSIFICATION_VERSION = "cost-classification-v1"

CONFIDENCE_EXPLICIT = Decimal("100.00")
CONFIDENCE_SUPPLIER_DEFAULT = Decimal("90.00")
CONFIDENCE_RULE = Decimal("80.00")
CONFIDENCE_UNCLASSIFIED = Decimal("0.00")

# Phrases are matched as whole words inside the normalised description (`normalize_key`): lower
# case, no accents, punctuation as spaces. Deliberately small; add a phrase only when it cannot
# mean anything else.
RULES: dict[CostCategory, tuple[str, ...]] = {
    CostCategory.LAUNDRY: (
        "lavanderia",
        "laundry",
        "linen service",
        "noleggio biancheria",
        "lavaggio biancheria",
    ),
    CostCategory.UTILITIES: (
        "energia elettrica",
        "fornitura elettrica",
        "electricity",
        "fornitura gas",
        "gas naturale",
        "natural gas",
        "servizio idrico",
        "water supply",
    ),
    CostCategory.SOFTWARE: (
        "software",
        "saas",
        "licenza software",
        "software license",
    ),
    CostCategory.OTA_COMMISSIONS: (
        "commissione booking",
        "commissioni booking",
        "booking commission",
        "commissione ota",
        "commissioni ota",
        "ota commission",
        "commissione airbnb",
        "commissione expedia",
    ),
    CostCategory.CLEANING: (
        "servizio di pulizia",
        "servizio pulizie",
        "pulizie",
        "cleaning service",
    ),
    CostCategory.MAINTENANCE: (
        "manutenzione",
        "riparazione",
        "maintenance",
    ),
}


@dataclass(frozen=True, slots=True)
class Classification:
    category: CostCategory
    confidence: Decimal
    method: ClassificationMethod


def _contains(description: str, phrase: str) -> bool:
    return f" {phrase} " in f" {description} "


def matching_categories(description_normalized: str) -> list[CostCategory]:
    """Every category whose phrases appear in the description (in the dictionary's order)."""
    return [
        category
        for category, phrases in RULES.items()
        if any(_contains(description_normalized, phrase) for phrase in phrases)
    ]


def classify_line(
    description_normalized: str,
    *,
    explicit: CostCategory | None = None,
    supplier_default: CostCategory | None = None,
) -> Classification:
    if explicit is not None:
        return Classification(explicit, CONFIDENCE_EXPLICIT, ClassificationMethod.EXPLICIT_SOURCE)
    if supplier_default is not None:
        return Classification(
            supplier_default, CONFIDENCE_SUPPLIER_DEFAULT, ClassificationMethod.SUPPLIER_DEFAULT
        )
    matches = matching_categories(description_normalized)
    if len(matches) == 1:
        return Classification(matches[0], CONFIDENCE_RULE, ClassificationMethod.DETERMINISTIC_RULE)
    return Classification(
        CostCategory.OTHER, CONFIDENCE_UNCLASSIFIED, ClassificationMethod.UNCLASSIFIED
    )

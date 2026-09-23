"""The canonical labor categories of V1 (a closed, versioned list).

Stored as VARCHAR guarded by a named CHECK constraint (never a PostgreSQL ENUM), so the list is
changed with an ordinary migration. A category says WHAT part of the operation a scheduled or
worked hour belongs to; it carries no opinion about who worked it or how well.
"""

from enum import StrEnum


class LaborCategory(StrEnum):
    HOUSEKEEPING = "HOUSEKEEPING"
    FRONT_OFFICE = "FRONT_OFFICE"
    FOOD_BEVERAGE = "FOOD_BEVERAGE"
    KITCHEN = "KITCHEN"
    MAINTENANCE = "MAINTENANCE"
    MANAGEMENT = "MANAGEMENT"
    SPA_WELLNESS = "SPA_WELLNESS"
    OTHER = "OTHER"


class LaborClassificationMethod(StrEnum):
    """Where an entry's category came from (provenance, not a statistical claim)."""

    EXPLICIT_SOURCE = "EXPLICIT_SOURCE"
    ROLE_MAPPING = "ROLE_MAPPING"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    UNCLASSIFIED = "UNCLASSIFIED"

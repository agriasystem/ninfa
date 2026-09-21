"""The canonical cost categories of V1 (a closed, versioned list).

Stored as VARCHAR guarded by a named CHECK constraint (never a PostgreSQL ENUM), so the list is
changed with an ordinary migration. A category says WHAT a cost was spent on; it carries no
opinion about whether the amount is right.
"""

from enum import StrEnum


class CostCategory(StrEnum):
    PERSONNEL = "PERSONNEL"
    LAUNDRY = "LAUNDRY"
    CLEANING = "CLEANING"
    AMENITIES = "AMENITIES"
    FOOD = "FOOD"
    BEVERAGE = "BEVERAGE"
    UTILITIES = "UTILITIES"
    MAINTENANCE = "MAINTENANCE"
    SOFTWARE = "SOFTWARE"
    MARKETING = "MARKETING"
    OTA_COMMISSIONS = "OTA_COMMISSIONS"
    PROFESSIONAL_SERVICES = "PROFESSIONAL_SERVICES"
    TRANSPORT = "TRANSPORT"
    OTHER = "OTHER"


class ClassificationMethod(StrEnum):
    """Where a line's category came from (provenance, not a statistical claim)."""

    EXPLICIT_SOURCE = "EXPLICIT_SOURCE"
    SUPPLIER_DEFAULT = "SUPPLIER_DEFAULT"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    UNCLASSIFIED = "UNCLASSIFIED"

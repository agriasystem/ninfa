"""Urgency Score V1: how SOON a TRIGGERED signal needs attention, never how SEVERE it is.

Three shapes, one per family of detector:

* **Forward-dated** (`REV_PICKUP_LOW`, `REV_OCCUPANCY_RISK`, `LABOR_OVERSTAFFING`): the signal is
  about a date still ahead of the ranking's `as_of_local_date` (a stay night, a work date). Urgency
  is a step function of how many days remain: the closer the date, the sooner the property must
  act on it, capped at 100 for "tomorrow or today" and floored at 20 for "more than 60 days out"
  (still worth ranking, never worth ignoring).
* **OTA dependency**: not a dated signal at all - it describes a state of the *next* 30 days as a
  whole, not a single day inside it. Using the window's start would manufacture a fake "100" out of
  a structural condition that has nothing to do with today specifically, so V1 uses a fixed,
  detector-aware policy instead: RISING is more urgent than pure STRUCTURAL (a share that is still
  moving needs a faster look than one that has simply been high for a long time).
* **Cost**: the target month has already ended (retrospective by construction), so "days to target"
  is meaningless; V1 measures the OPPOSITE distance, `days_since_period_end`, on the reasoning that
  a cost anomaly is most actionable while the month's context (suppliers, invoices) is still fresh
  in someone's memory, and quickly stops being urgent to review as it ages.

All bands are inclusive at their upper edge and exact `Decimal` output (a pure step function needs
no interpolation).
"""

from decimal import Decimal

_STALE_MESSAGE = "urgency: days_to_target must be >= 0 (a stale evaluation is rejected earlier)"
_RETROSPECTIVE_MESSAGE = (
    "cost_urgency: days_since_period_end must be >= 1 (the month must have concluded)"
)


def forward_urgency(days_to_target: int) -> Decimal:
    """REV_PICKUP_LOW / REV_OCCUPANCY_RISK / LABOR_OVERSTAFFING: days until the target date."""
    if days_to_target < 0:
        raise ValueError(_STALE_MESSAGE)
    if days_to_target <= 1:
        return Decimal(100)
    if days_to_target <= 3:
        return Decimal(90)
    if days_to_target <= 7:
        return Decimal(80)
    if days_to_target <= 14:
        return Decimal(65)
    if days_to_target <= 30:
        return Decimal(50)
    if days_to_target <= 60:
        return Decimal(35)
    return Decimal(20)


def ota_urgency(*, structural_condition: bool, rising_condition: bool) -> Decimal:
    """REV_OTA_DEPENDENCY: a fixed policy, never a fabricated "days to the window"."""
    if rising_condition:
        return Decimal(60)  # RISING only, or STRUCTURAL + RISING together
    if structural_condition:
        return Decimal(40)  # STRUCTURAL only
    raise ValueError("ota_urgency: a TRIGGERED evaluation needs structural or rising true")


def cost_urgency(days_since_period_end: int) -> Decimal:
    """COST_CPOR_ANOMALY: how long ago the (already concluded) target month ended."""
    if days_since_period_end < 1:
        raise ValueError(_RETROSPECTIVE_MESSAGE)
    if days_since_period_end <= 7:
        return Decimal(70)
    if days_since_period_end <= 30:
        return Decimal(55)
    if days_since_period_end <= 60:
        return Decimal(40)
    if days_since_period_end <= 90:
        return Decimal(25)
    return Decimal(10)

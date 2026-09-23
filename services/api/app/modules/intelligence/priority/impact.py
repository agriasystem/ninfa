"""Impact Score V1: NORMALIZED OPERATIONAL SEVERITY, never euro, revenue loss, saving or profit.

Impact V1 deliberately does NOT price anything: not every detector has an economic proxy (OTA has
none at all), proxies exist in different currencies, and some proxies are gross exposure figures
that would bias a cross-domain score toward whichever detector's proxy happens to be larger. Every
economic figure stays evidence on the candidate (`adapters.py`), never a scoring input.

`threshold_progress` is the one shared shape behind every detector's Impact Score: how far past a
detector's OWN thresholds (already decided by the detector, never re-decided here) a TRIGGERED
signal sits, mapped onto a common 0-100 scale so five unrelated units (percentage points, rooms,
hours, a CPOR ratio) become comparable severity. `threshold = 50`: the point a detector's own rule
starts firing is the SCALE's own midpoint, not a random mark - it lets the second half of the
scale (50-100) express "how far beyond the trigger", symmetric with the first half's "how close to
it". `saturation = 100`: beyond it, more severity is not tracked (a policy ceiling, not a claim
that nothing worse exists).

Every detector picks MIN or MAX of its own components for the documented reason a real detector
needs ALL of a set of conditions (AND -> MIN, the weakest condition caps it) or EITHER of two
independent ones (OR -> MAX, the strongest path wins); see ADR 0016 point 6/7.
"""

from decimal import Decimal

from app.modules.intelligence.priority.precision import CALCULATION_CONTEXT

_ZERO = Decimal(0)
_FIFTY = Decimal(50)
_HUNDRED = Decimal(100)


def threshold_progress(value: Decimal, threshold: Decimal, saturation: Decimal) -> Decimal:
    """0-100 progress of `value` against a detector's own `threshold` (-> 50) and `saturation`
    (-> 100), by two independent linear interpolations (never a single line across both spans).

        value <= 0          -> 0
        0 < value < threshold      -> linear 0 -> 50
        value == threshold  -> 50
        threshold < value < saturation -> linear 50 -> 100
        value >= saturation -> 100

    Exact `Decimal`, in the dedicated calculation context, never rounded before it is used.
    """
    if threshold <= 0:
        raise ValueError("threshold_progress: threshold must be > 0")
    if saturation <= threshold:
        raise ValueError("threshold_progress: saturation must be > threshold")
    if value <= 0:
        return _ZERO
    if value >= saturation:
        return _HUNDRED
    if value <= threshold:
        return CALCULATION_CONTEXT.divide(CALCULATION_CONTEXT.multiply(value, _FIFTY), threshold)
    span = CALCULATION_CONTEXT.subtract(saturation, threshold)
    offset = CALCULATION_CONTEXT.subtract(value, threshold)
    extra = CALCULATION_CONTEXT.divide(CALCULATION_CONTEXT.multiply(offset, _FIFTY), span)
    return CALCULATION_CONTEXT.add(_FIFTY, extra)


def pickup_impact(abs_negative_delta_percent: Decimal, missing_rooms: Decimal) -> Decimal:
    """REV_PICKUP_LOW needs BOTH conditions (AND): MIN of the two components."""
    relative_component = threshold_progress(abs_negative_delta_percent, Decimal(20), Decimal(40))
    rooms_component = threshold_progress(missing_rooms, Decimal(2), Decimal(4))
    return min(relative_component, rooms_component)


def occupancy_impact(occupancy_gap_pp: Decimal, room_shortfall: Decimal) -> Decimal:
    """REV_OCCUPANCY_RISK triggers on EITHER condition (OR): MAX of the two components."""
    gap_component = threshold_progress(occupancy_gap_pp, Decimal(10), Decimal(20))
    rooms_component = threshold_progress(room_shortfall, Decimal(3), Decimal(6))
    return max(gap_component, rooms_component)


def ota_impact(
    actual_ota_share: Decimal,
    delta_pp: Decimal,
    *,
    structural_condition: bool,
    rising_condition: bool,
) -> Decimal:
    """REV_OTA_DEPENDENCY: two independent paths, only the ones that actually held count.

    Structural and rising are independent (the detector's own OR): when both hold, the impact is
    whichever path is more severe (MAX); when only one holds, its own component is the impact.
    """
    structural_component = threshold_progress(actual_ota_share, Decimal(70), Decimal(100))
    share_component = threshold_progress(actual_ota_share, Decimal(55), Decimal(100))
    gap_component = threshold_progress(max(delta_pp, _ZERO), Decimal(15), Decimal(30))
    rising_impact = min(share_component, gap_component)
    if structural_condition and rising_condition:
        return max(structural_component, rising_impact)
    if structural_condition:
        return structural_component
    if rising_condition:
        return rising_impact
    raise ValueError("ota_impact: a TRIGGERED evaluation needs structural or rising true")


def cost_impact(delta_percent: Decimal, actual_cpor: Decimal, upper_fence: Decimal) -> Decimal:
    """COST_CPOR_ANOMALY needs ALL of its own conditions (AND): MIN of the two components.

    The monetary `cost_gap_proxy` never enters this: `relative_component` uses the relative delta
    (currency-free) and `robust_component` uses a dimensionless ratio (`actual / upper_fence`), so
    a EUR month and a USD month score on the same scale without ever being compared in money.
    """
    if upper_fence <= 0:
        raise ValueError("cost_impact: upper_fence must be > 0")
    relative_component = threshold_progress(max(delta_percent, _ZERO), Decimal(20), Decimal(40))
    robust_ratio = CALCULATION_CONTEXT.divide(actual_cpor, upper_fence)
    robust_component = threshold_progress(robust_ratio, Decimal(1), Decimal("1.5"))
    return min(relative_component, robust_component)


def labor_impact(delta_percent: Decimal, excess_hours: Decimal) -> Decimal:
    """LABOR_OVERSTAFFING needs ALL of its own conditions (AND): MIN of the two components.

    The optional `labor_cost_gap_proxy` never enters this.
    """
    relative_component = threshold_progress(max(delta_percent, _ZERO), Decimal(20), Decimal(40))
    hours_component = threshold_progress(excess_hours, Decimal(4), Decimal(8))
    return min(relative_component, hours_component)

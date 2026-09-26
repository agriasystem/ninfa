"""The vocabulary of Recommendation Engine V1: a deterministic, non-autonomous suggestion layer
over the Decision Layer's own persisted memory (Gate 11).

NINFA proposes; the user decides. Nothing here is a business API, a write path, or a step toward
autonomous execution: every `Action` carries `requires_human_review = True`, unconditionally, and
there is no field anywhere in this module that could mean "apply this automatically". There is no
free-form generated prose either - `title_key`/`description_key` are stable, deterministic
template keys a future copy/UI layer maps to human language; the engine itself never produces
Italian (or any) prose as a business primitive.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.intelligence.priority.types import PriorityDecisionType

RECOMMENDATION_ENGINE_VERSION = "recommendation-engine-v1"

MAX_ACTIONS_PER_DECISION = 3
MAX_SUPPORTING_CHECKS = MAX_ACTIONS_PER_DECISION - 1


class RecommendationStatus(StrEnum):
    """AVAILABLE: a real, supported recommendation exists for the CURRENT (latest) observation.
    NOT_AVAILABLE: the latest observation is not TRIGGERED (or the decision type is unsupported) -
    there is nothing to recommend right now, regardless of the Decision's own OPEN/RESOLVED status.
    INSUFFICIENT_CONTEXT: the latest observation IS TRIGGERED, but the specific facts this
    recommendation needs are missing or fail to parse as expected - never invented, never guessed.
    """

    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class ActionCategory(StrEnum):
    """A small, closed set - every future action must fit one of these, or the set itself grows
    deliberately; there is no free-text category."""

    REVIEW_PRICING = "REVIEW_PRICING"
    REVIEW_AVAILABILITY = "REVIEW_AVAILABILITY"
    REVIEW_DISTRIBUTION = "REVIEW_DISTRIBUTION"
    REVIEW_COST_DRIVERS = "REVIEW_COST_DRIVERS"
    REVIEW_STAFFING = "REVIEW_STAFFING"
    VERIFY_DATA = "VERIFY_DATA"


class ActionScope(StrEnum):
    """WHICH target dimension an action concerns - structured, not prose. The actual value (which
    stay date, which period) already lives in the Decision's own `target`/facts; this only names
    the KIND of scope, so a client never has to guess it from the action code alone."""

    STAY_DATE = "STAY_DATE"
    DISTRIBUTION_WINDOW = "DISTRIBUTION_WINDOW"
    COST_PERIOD = "COST_PERIOD"
    WORK_DATE = "WORK_DATE"


class ActionCode(StrEnum):
    """Every action this engine can ever produce. One primary per decision type, plus the
    supporting checks that type may add - see `rules.py`."""

    # Primary actions (exactly one per supported decision_type)
    REVIEW_PRICING_AND_AVAILABILITY = "REVIEW_PRICING_AND_AVAILABILITY"  # REV_PICKUP_LOW
    REVIEW_DEMAND_POSITIONING = "REVIEW_DEMAND_POSITIONING"  # REV_OCCUPANCY_RISK
    REVIEW_DISTRIBUTION_MIX = "REVIEW_DISTRIBUTION_MIX"  # REV_OTA_DEPENDENCY
    REVIEW_COST_DRIVERS = "REVIEW_COST_DRIVERS"  # COST_CPOR_ANOMALY
    REVIEW_STAFFING_PLAN = "REVIEW_STAFFING_PLAN"  # LABOR_OVERSTAFFING

    # Supporting checks
    CHECK_CHANNEL_VISIBILITY = "CHECK_CHANNEL_VISIBILITY"
    CHECK_BOOKING_RESTRICTIONS = "CHECK_BOOKING_RESTRICTIONS"
    CHECK_PRICING = "CHECK_PRICING"
    CHECK_AVAILABILITY_AND_RESTRICTIONS = "CHECK_AVAILABILITY_AND_RESTRICTIONS"
    CHECK_DIRECT_CHANNEL_AVAILABILITY = "CHECK_DIRECT_CHANNEL_AVAILABILITY"
    CHECK_DISTRIBUTION_CONFIGURATION = "CHECK_DISTRIBUTION_CONFIGURATION"
    CHECK_RECENT_COST_ENTRIES = "CHECK_RECENT_COST_ENTRIES"
    CHECK_VOLUME_VS_COST = "CHECK_VOLUME_VS_COST"
    CHECK_SHIFT_COVERAGE = "CHECK_SHIFT_COVERAGE"
    CHECK_SCHEDULED_HOURS = "CHECK_SCHEDULED_HOURS"


class RiskNote(StrEnum):
    """Structured, stable risk annotations - never a numeric/invented risk score."""

    PRICING_CHANGE_MAY_AFFECT_REVENUE = "PRICING_CHANGE_MAY_AFFECT_REVENUE"
    STAFFING_CHANGE_MAY_AFFECT_SERVICE = "STAFFING_CHANGE_MAY_AFFECT_SERVICE"
    DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY = "DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY"


def title_key(action_code: ActionCode) -> str:
    """A deterministic template key, NOT prose - a future copy/UI layer maps this to human
    language. Always `f(action_code)`: the same code always yields the same key."""
    return f"recommendation.action.{action_code.value}.title"


def description_key(action_code: ActionCode) -> str:
    return f"recommendation.action.{action_code.value}.description"


@dataclass(frozen=True, slots=True)
class Action:
    """One structured action - a REVIEW or a CHECK, never an executed change. `supporting_facts`
    is a whitelisted, canonicalised (string-valued) subset of the SAME observation facts this
    action's inclusion depended on - never a passthrough of the whole facts payload, never a
    second, undocumented set of numbers."""

    action_code: ActionCode
    category: ActionCategory
    scope: ActionScope
    supporting_facts: dict[str, str]
    risk_notes: tuple[RiskNote, ...] = ()
    requires_human_review: bool = True

    @property
    def title_key(self) -> str:
        return title_key(self.action_code)

    @property
    def description_key(self) -> str:
        return description_key(self.action_code)


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    """The engine's ONE typed, immutable output. `fingerprint` is a pure function of every field
    below EXCEPT itself - see `fingerprint.py`. No wall-clock field exists anywhere here: nothing
    is timestamped, nothing is randomly generated, the same (decision, observation) pair always
    produces byte-identical output."""

    decision_id: UUID
    decision_type: PriorityDecisionType
    recommendation_version: str
    status: RecommendationStatus
    primary_action: Action | None
    supporting_checks: tuple[Action, ...]
    generated_from_observation_id: UUID
    generated_from_evaluation_fingerprint: str
    reason_codes: tuple[str, ...]
    confidence: str | None
    fingerprint: str


__all__ = [
    "MAX_ACTIONS_PER_DECISION",
    "MAX_SUPPORTING_CHECKS",
    "RECOMMENDATION_ENGINE_VERSION",
    "Action",
    "ActionCategory",
    "ActionCode",
    "ActionScope",
    "RecommendationResult",
    "RecommendationStatus",
    "RiskNote",
    "description_key",
    "title_key",
]

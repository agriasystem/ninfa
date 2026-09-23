"""The vocabulary of Priority Engine V1: context, weights, policy, candidate, ranking result.

Everything here is immutable and typed. Weights and policies are versioned code
(`PRIORITY_RULES_VERSION`), never database rows. There is no persisted Decision, priority or
recommendation: a `PriorityCandidate` is the OUTPUT of a pure calculation over already-computed,
immutable detector evaluations, and nothing here is stored.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

PRIORITY_RULES_VERSION = "priority-engine-v1"

# --- the frozen V1 formula -----------------------------------------------------------------------
#
#     priority_score = 0.40 * impact + 0.25 * urgency + 0.20 * confidence + 0.15 * actionability
#
# Every component is 0-100. The sum of the weights is exactly 1.00.

IMPACT_WEIGHT = Decimal("0.40")
URGENCY_WEIGHT = Decimal("0.25")
CONFIDENCE_WEIGHT = Decimal("0.20")
ACTIONABILITY_WEIGHT = Decimal("0.15")

WEIGHT_SUM = IMPACT_WEIGHT + URGENCY_WEIGHT + CONFIDENCE_WEIGHT + ACTIONABILITY_WEIGHT
assert Decimal("1.00") == WEIGHT_SUM, "the four V1 weights must sum to exactly 1.00"


class PriorityDecisionType(StrEnum):
    """The five MVP detectors this gate can rank. Adding a sixth needs a sixth explicit adapter."""

    REV_PICKUP_LOW = "REV_PICKUP_LOW"
    REV_OCCUPANCY_RISK = "REV_OCCUPANCY_RISK"
    REV_OTA_DEPENDENCY = "REV_OTA_DEPENDENCY"
    COST_CPOR_ANOMALY = "COST_CPOR_ANOMALY"
    LABOR_OVERSTAFFING = "LABOR_OVERSTAFFING"


# Technical, deterministic tie-break order ONLY (ranking key #6). It expresses no semantic
# superiority between detectors: it exists so that two candidates identical in every scored
# component still sort the same way on every machine, every run.
DECISION_TYPE_TIE_ORDER: tuple[PriorityDecisionType, ...] = (
    PriorityDecisionType.REV_OCCUPANCY_RISK,
    PriorityDecisionType.REV_PICKUP_LOW,
    PriorityDecisionType.LABOR_OVERSTAFFING,
    PriorityDecisionType.COST_CPOR_ANOMALY,
    PriorityDecisionType.REV_OTA_DEPENDENCY,
)
DECISION_TYPE_TIE_ORDER_INDEX: dict[PriorityDecisionType, int] = {
    decision_type: index for index, decision_type in enumerate(DECISION_TYPE_TIE_ORDER)
}

# --- Actionability Score V1: a fixed heuristic POLICY, never a probability ----------------------
#
# "How directly can a person act on this specific signal" - NOT whether they should, and NOT what
# action to take (no action text is ever generated from this number).
ACTIONABILITY_POLICY_VERSION = "priority-actionability-v1"
ACTIONABILITY_POLICY_V1: dict[PriorityDecisionType, Decimal] = {
    PriorityDecisionType.REV_PICKUP_LOW: Decimal(90),
    PriorityDecisionType.REV_OCCUPANCY_RISK: Decimal(85),
    PriorityDecisionType.REV_OTA_DEPENDENCY: Decimal(60),
    PriorityDecisionType.COST_CPOR_ANOMALY: Decimal(70),
    PriorityDecisionType.LABOR_OVERSTAFFING: Decimal(90),
}

# The detector's OWN confidence gate (below it, TRIGGERED cannot legally exist): a coherence check,
# never a re-decision. Kept here, once, instead of importing every detector module just for one
# constant each.
DETECTOR_CONFIDENCE_GATE: dict[PriorityDecisionType, Decimal] = {
    PriorityDecisionType.REV_PICKUP_LOW: Decimal(50),
    PriorityDecisionType.REV_OCCUPANCY_RISK: Decimal(55),
    PriorityDecisionType.REV_OTA_DEPENDENCY: Decimal(55),
    PriorityDecisionType.COST_CPOR_ANOMALY: Decimal(55),
    PriorityDecisionType.LABOR_OVERSTAFFING: Decimal(55),
}


@dataclass(frozen=True, slots=True)
class PriorityContext:
    """The explicit scope and instant of one ranking run.

    NOT derived from `date.today()`/`datetime.now()` anywhere: passing it explicitly is what
    makes a ranking run replayable and back-testable, exactly like every detector's own
    `as_of_local_date`.
    """

    workspace_id: UUID
    property_id: UUID
    as_of_local_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("PriorityContext.workspace_id must be a UUID")
        if not isinstance(self.property_id, UUID):
            raise TypeError("PriorityContext.property_id must be a UUID")
        if not isinstance(self.as_of_local_date, date):
            raise TypeError("PriorityContext.as_of_local_date must be a date")


@dataclass(frozen=True, slots=True)
class PriorityCandidate:
    """One TRIGGERED evaluation, normalized into a ranked, explainable, immutable candidate.

    `impact_basis`/`urgency_basis` are plain data (no generated text): every raw input the two
    scores were computed from, enough to audit the number without recomputing it. `actionability_
    policy` names the fixed V1 policy version, not a formula (there is none: it is a lookup).
    `economic_proxy_exact` is EVIDENCE ONLY (see the module docstring of `adapters.py`): it never
    entered `priority_score_exact` and is never compared across candidates of different currencies.
    """

    decision_type: PriorityDecisionType
    workspace_id: UUID
    property_id: UUID
    priority_as_of_date: date

    source_evaluation_fingerprint: str
    source_target_key: str

    impact_score_exact: Decimal
    impact_score_display: Decimal
    urgency_score: Decimal
    confidence_score: Decimal
    actionability_score: Decimal

    priority_score_exact: Decimal
    priority_score_display: Decimal

    impact_basis: dict[str, Any]
    urgency_basis: dict[str, Any]
    actionability_policy: str

    economic_proxy_exact: Decimal | None
    economic_proxy_currency: str | None
    economic_proxy_label: str | None

    source_reason_codes: tuple[str, ...]

    priority_version: str = PRIORITY_RULES_VERSION
    calculation_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class RankedPriorityCandidate:
    """A candidate with its final, unique rank (1 = highest priority). Never dense/shared."""

    rank: int
    candidate: PriorityCandidate


@dataclass(frozen=True, slots=True)
class PriorityRankingResult:
    """The outcome of one ranking run: every TRIGGERED signal, ordered, plus why others are not
    here.

    `ranked_candidates` is empty when nothing was TRIGGERED - a legitimate, first-class result
    ("tutto sotto controllo" belongs to a future UI translation of an empty ranking, never
    generated here). Truncation to a top N is a presentation concern of a later gate, never done
    here: `ranked_candidates` always holds every candidate.
    """

    workspace_id: UUID
    property_id: UUID
    as_of_local_date: date

    candidate_count: int
    excluded_clear_count: int
    excluded_insufficient_count: int
    excluded_not_applicable_count: int
    excluded_suppressed_count: int
    duplicate_input_count: int

    ranked_candidates: tuple[RankedPriorityCandidate, ...] = field(default_factory=tuple)

    priority_version: str = PRIORITY_RULES_VERSION
    calculation_fingerprint: str = ""

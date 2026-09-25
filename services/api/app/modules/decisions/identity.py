"""Decision identity (`decision-identity-v1`): the CROSS-DAY LOGICAL IDENTITY of the operational
problem a source evaluation is about.

This is deliberately NOT `AdaptedSignal.source_target_key` (Gate 10's own key): a target key may
carry a snapshot id, an as-of date or a rolling window boundary that changes from one morning to
the next, so using it as identity would create a new Decision every day for the very same problem
(see docs/architecture/decision-layer-v1.md, "Signal vs Decision"). Each of the five MVP detectors
gets its own explicit identity dimensions below, built from the real fields of its own evaluation
type - never assumed from the prompt, never the generic target key.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.decisions.errors import DecisionError, DecisionErrorCode
from app.modules.decisions.types import DECISION_IDENTITY_VERSION
from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation

SourceEvaluation = (
    RevenueDecisionEvaluation
    | OtaDependencyEvaluation
    | CostDecisionEvaluation
    | LaborDecisionEvaluation
)


@dataclass(frozen=True, slots=True)
class DecisionIdentity:
    """The identity of ONE Decision, computed from ONE source evaluation.

    `identity_key` is a 64-char lowercase SHA-256 of `identity_payload`'s canonical JSON;
    `identity_payload` is kept verbatim for audit and for the collision check in `verify()`.
    """

    decision_type: PriorityDecisionType
    workspace_id: UUID
    property_id: UUID
    identity_key: str
    identity_payload: dict[str, Any]


def canonical_identity_json(payload: dict[str, Any]) -> str:
    """The exact bytes `identity_key` hashes: sorted keys, ASCII, no whitespace - so field
    ORDERING can never change the hash (test invariant: "input field ordering irrelevant")."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identity_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_identity_json(payload).encode("ascii")).hexdigest()


def _identity(
    decision_type: PriorityDecisionType,
    workspace_id: UUID,
    property_id: UUID,
    dimensions: dict[str, Any],
) -> DecisionIdentity:
    payload: dict[str, Any] = {
        "identity_version": DECISION_IDENTITY_VERSION,
        "decision_type": decision_type.value,
        "workspace_id": str(workspace_id),
        "property_id": str(property_id),
        **dimensions,
    }
    return DecisionIdentity(
        decision_type, workspace_id, property_id, identity_hash(payload), payload
    )


def _revenue_identity(evaluation: RevenueDecisionEvaluation) -> DecisionIdentity:
    """REV_PICKUP_LOW / REV_OCCUPANCY_RISK: decision_type + workspace + property + booking data
    source + stay_date. NEVER snapshot_local_date, target_snapshot_id or the evaluation
    fingerprint: those change every morning the same stay date is re-observed. The decision_type
    itself is part of the hashed payload, so the two detectors never collide on the same date
    (test invariant 4)."""
    decision_type = PriorityDecisionType(evaluation.decision_type.value)
    return _identity(
        decision_type,
        evaluation.workspace_id,
        evaluation.property_id,
        {
            "booking_data_source_id": str(evaluation.data_source_id),
            "stay_date": evaluation.stay_date.isoformat(),
        },
    )


def _ota_identity(evaluation: OtaDependencyEvaluation) -> DecisionIdentity:
    """REV_OTA_DEPENDENCY is property-wide for its booking source: decision_type + workspace +
    property + booking data source. NEVER as_of_local_date, window_start or window_end - the
    30-day window shifts every morning while the identity stays the same (see the "GOLDEN OTA
    CROSS-DAY IDENTITY" scenario). STRUCTURAL and RISING are reasons/states of the SAME identity,
    never two Decisions."""
    return _identity(
        PriorityDecisionType.REV_OTA_DEPENDENCY,
        evaluation.workspace_id,
        evaluation.property_id,
        {"booking_data_source_id": str(evaluation.booking_data_source_id)},
    )


def _cost_identity(evaluation: CostDecisionEvaluation) -> DecisionIdentity:
    """COST_CPOR_ANOMALY: "a target is identified by workspace, property, booking data source,
    calendar month, cost category and currency" (docs/architecture/cost-cpor-anomaly-v1.md, "The
    target") - the booking data source is a REAL dimension of the Gate 7 target (it is the stated
    provenance of the occupancy denominator, not an invented one: costs themselves are read
    cross-source, by design, and are never filtered by it). `target_period_start` (the first day
    of the month) already determines the month uniquely: a new month is a new identity."""
    return _identity(
        PriorityDecisionType.COST_CPOR_ANOMALY,
        evaluation.workspace_id,
        evaluation.property_id,
        {
            "booking_data_source_id": str(evaluation.booking_data_source_id),
            "target_period_start": evaluation.target_period_start.isoformat(),
            "cost_category": evaluation.cost_category.value,
            "currency": evaluation.currency,
        },
    )


def _labor_identity(evaluation: LaborDecisionEvaluation) -> DecisionIdentity:
    """LABOR_OVERSTAFFING: decision_type + workspace + property + work_date + labor_category +
    labor data source + booking data source (the booking source genuinely changes the demand
    forecast the detector compares against, so it IS part of the canonical target - see
    docs/architecture/labor-overstaffing-v1.md, "Demand forecast: reused, not rebuilt"). NEVER the
    labor snapshot date or the target's own as-of date."""
    return _identity(
        PriorityDecisionType.LABOR_OVERSTAFFING,
        evaluation.workspace_id,
        evaluation.property_id,
        {
            "booking_data_source_id": str(evaluation.booking_data_source_id),
            "labor_data_source_id": str(evaluation.labor_data_source_id),
            "work_date": evaluation.target_work_date.isoformat(),
            "labor_category": evaluation.labor_category.value,
        },
    )


def build_identity(evaluation: SourceEvaluation) -> DecisionIdentity:
    """Dispatch one evaluation of a known type to its own explicit identity builder."""
    if isinstance(evaluation, RevenueDecisionEvaluation):
        return _revenue_identity(evaluation)
    if isinstance(evaluation, OtaDependencyEvaluation):
        return _ota_identity(evaluation)
    if isinstance(evaluation, CostDecisionEvaluation):
        return _cost_identity(evaluation)
    if isinstance(evaluation, LaborDecisionEvaluation):
        return _labor_identity(evaluation)
    raise DecisionError(
        DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH,
        f"unrecognised source evaluation type {type(evaluation)!r}",
    )


def verify_identity(stored_payload: dict[str, Any], identity: DecisionIdentity) -> None:
    """Fail closed if an existing Decision's stored payload and the freshly built one disagree
    despite sharing an `identity_key`: a hash is only useful if collisions are never trusted."""
    if stored_payload != identity.identity_payload:
        raise DecisionError(
            DecisionErrorCode.DECISION_IDENTITY_HASH_COLLISION,
            "identity_key collision: two different identity payloads hashed to the same key",
            details={"identity_key": identity.identity_key},
        )


def raw_target_key(evaluation: SourceEvaluation) -> str:
    """A display/audit-only target key, built the SAME way for every status (unlike Gate 10's own
    `AdaptedSignal.source_target_key`, which only exists for TRIGGERED evaluations because it is
    built by an adapter that also validates TRIGGERED-only facts). Deliberately NOT imported from
    `intelligence.priority.adapters` - this module never touches Gate 10 code, and for a TRIGGERED
    evaluation the two strings are identical by construction (same fields, same format), which the
    identity/observation tests check directly. NEVER used as identity: it is exactly what identity
    is built to stop using (it carries a snapshot id and window/as-of boundaries that change every
    morning)."""
    if isinstance(evaluation, RevenueDecisionEvaluation):
        return f"stay:{evaluation.stay_date.isoformat()}|snapshot:{evaluation.target_snapshot_id}"
    if isinstance(evaluation, OtaDependencyEvaluation):
        return (
            f"asof:{evaluation.as_of_local_date.isoformat()}"
            f"|window:{evaluation.window_start.isoformat()}..{evaluation.window_end.isoformat()}"
        )
    if isinstance(evaluation, CostDecisionEvaluation):
        return (
            f"month:{evaluation.target_period_start.isoformat()}"
            f"|category:{evaluation.cost_category.value}|currency:{evaluation.currency}"
        )
    if isinstance(evaluation, LaborDecisionEvaluation):
        return (
            f"workdate:{evaluation.target_work_date.isoformat()}"
            f"|category:{evaluation.labor_category.value}"
            f"|laborsnapshot:{evaluation.target_labor_snapshot_id}"
        )
    raise DecisionError(
        DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH,
        f"unrecognised source evaluation type {type(evaluation)!r}",
    )


__all__ = [
    "DecisionIdentity",
    "SourceEvaluation",
    "build_identity",
    "canonical_identity_json",
    "identity_hash",
    "raw_target_key",
    "verify_identity",
]

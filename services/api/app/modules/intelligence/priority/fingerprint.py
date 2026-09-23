"""The deterministic SHA-256 fingerprint of a Priority candidate and of a full ranking result.

Both hash a canonical JSON of only the LOGICAL content that decided the result: never a runtime
timestamp, a memory address, the input list's own order or a display-only figure. Decimals are
serialised by `precision.canonical_text` (non-lossy: `10`, `10.00` and `1E+1` are the same text,
but no digit is ever dropped), so two candidates on opposite sides of a threshold never share a
fingerprint even when they display alike. The ranking result is always serialised in FINAL RANK
order, never input order, so the same logical set of TRIGGERED evaluations gives the same ranking
fingerprint whatever order they arrived in.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.modules.intelligence.priority.precision import canonical_text
from app.modules.intelligence.priority.types import PriorityDecisionType

if TYPE_CHECKING:
    from app.modules.intelligence.priority.types import RankedPriorityCandidate

_FINGERPRINT_FORMAT = 1


def _canonicalize(value: Any) -> Any:
    """Recursively turn one `impact_basis`/`urgency_basis` value into a JSON-safe representation."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        return canonical_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonicalize(item) for item in value]
    raise TypeError(f"cannot canonicalize {type(value)!r} for a Priority fingerprint")


def candidate_fingerprint(
    *,
    decision_type: PriorityDecisionType,
    workspace_id: UUID,
    property_id: UUID,
    priority_as_of_date: date,
    source_evaluation_fingerprint: str,
    source_target_key: str,
    impact_score_exact: Decimal,
    urgency_score: Decimal,
    confidence_score: Decimal,
    actionability_score: Decimal,
    priority_score_exact: Decimal,
    impact_basis: dict[str, Any],
    urgency_basis: dict[str, Any],
    source_reason_codes: tuple[str, ...],
    priority_version: str,
) -> str:
    """SHA-256 of everything that decided this ONE candidate's score (never its rank)."""
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "priority_version": priority_version,
        "decision_type": decision_type.value,
        "workspace_id": str(workspace_id),
        "property_id": str(property_id),
        "priority_as_of_date": priority_as_of_date.isoformat(),
        "source_evaluation_fingerprint": source_evaluation_fingerprint,
        "source_target_key": source_target_key,
        "impact_score_exact": canonical_text(impact_score_exact),
        "urgency_score": canonical_text(urgency_score),
        "confidence_score": canonical_text(confidence_score),
        "actionability_score": canonical_text(actionability_score),
        "priority_score_exact": canonical_text(priority_score_exact),
        "impact_basis": _canonicalize(impact_basis),
        "urgency_basis": _canonicalize(urgency_basis),
        "source_reason_codes": list(source_reason_codes),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def ranking_fingerprint(
    *,
    workspace_id: UUID,
    property_id: UUID,
    as_of_local_date: date,
    ranked_candidates: "tuple[RankedPriorityCandidate, ...]",
    excluded_clear_count: int,
    excluded_insufficient_count: int,
    excluded_not_applicable_count: int,
    excluded_suppressed_count: int,
    duplicate_input_count: int,
    priority_version: str,
) -> str:
    """SHA-256 of the whole ranking RESULT, in final rank order (never the callers' input order)."""
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "priority_version": priority_version,
        "workspace_id": str(workspace_id),
        "property_id": str(property_id),
        "as_of_local_date": as_of_local_date.isoformat(),
        "candidate_count": len(ranked_candidates),
        "excluded_clear_count": excluded_clear_count,
        "excluded_insufficient_count": excluded_insufficient_count,
        "excluded_not_applicable_count": excluded_not_applicable_count,
        "excluded_suppressed_count": excluded_suppressed_count,
        "duplicate_input_count": duplicate_input_count,
        "ranked_candidates": [
            {
                "rank": ranked.rank,
                "calculation_fingerprint": ranked.candidate.calculation_fingerprint,
                "decision_type": ranked.candidate.decision_type.value,
                "priority_score_exact": canonical_text(ranked.candidate.priority_score_exact),
                "impact_score_exact": canonical_text(ranked.candidate.impact_score_exact),
                "urgency_score": canonical_text(ranked.candidate.urgency_score),
                "confidence_score": canonical_text(ranked.candidate.confidence_score),
                "actionability_score": canonical_text(ranked.candidate.actionability_score),
            }
            for ranked in ranked_candidates
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()

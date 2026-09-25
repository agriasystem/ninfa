"""Deterministic SHA-256 fingerprints of a `DecisionRun`'s input and of one `DecisionObservation`.

Both hash a canonical JSON of only the LOGICAL content that decided the result: never a runtime
timestamp, a random database id or a display-only figure (the same convention as Gate 10's own
`priority.fingerprint`). The run input fingerprint never depends on the order the caller passed
its evaluations in: the set of source fingerprints is sorted before hashing.
"""

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.decisions.precision import canonical_text
from app.modules.decisions.types import (
    DECISION_LAYER_VERSION,
    DECISION_MEMORY_VERSION,
    LifecycleTransition,
    SourceStatus,
)

_RUN_FINGERPRINT_FORMAT = 1
_OBSERVATION_FINGERPRINT_FORMAT = 1


def run_input_fingerprint(
    *,
    workspace_id: UUID,
    property_id: UUID,
    as_of_local_date: date,
    source_evaluation_fingerprints: Iterable[str],
    priority_ranking_fingerprint: str,
    evaluation_count: int,
    triggered_count: int,
    clear_count: int,
    insufficient_count: int,
    not_applicable_count: int,
    suppressed_count: int,
    duplicate_input_count: int,
) -> str:
    """SHA-256 of everything that makes ONE DecisionRun's logical input unique.

    The source fingerprints are hashed as a SORTED, DEDUPLICATED set: the caller's own order (and
    a duplicate seen twice) never changes the fingerprint - `duplicate_input_count` already
    carries that information on its own.
    """
    payload = {
        "v": _RUN_FINGERPRINT_FORMAT,
        "decision_layer_version": DECISION_LAYER_VERSION,
        "workspace_id": str(workspace_id),
        "property_id": str(property_id),
        "as_of_local_date": as_of_local_date.isoformat(),
        "source_evaluation_fingerprints": sorted(set(source_evaluation_fingerprints)),
        "priority_ranking_fingerprint": priority_ranking_fingerprint,
        "evaluation_count": evaluation_count,
        "triggered_count": triggered_count,
        "clear_count": clear_count,
        "insufficient_count": insufficient_count,
        "not_applicable_count": not_applicable_count,
        "suppressed_count": suppressed_count,
        "duplicate_input_count": duplicate_input_count,
    }
    return _hash(payload)


def observation_fingerprint(
    *,
    decision_identity_key: str,
    run_input_fingerprint: str,
    as_of_local_date: date,
    source_status: SourceStatus,
    lifecycle_transition: LifecycleTransition,
    source_evaluation_fingerprint: str,
    source_target_key: str,
    priority_candidate_fingerprint: str | None,
    priority_rank: int | None,
    impact_score: Decimal | None,
    urgency_score: Decimal | None,
    confidence_score: Decimal,
    actionability_score: Decimal | None,
    priority_score: Decimal | None,
    source_reason_codes: tuple[str, ...],
    facts_payload: dict[str, Any],
    evidence_payload: dict[str, Any],
) -> str:
    """SHA-256 of everything ONE Observation records: what NINFA knew, in this run, of this
    Decision. Never the observation's own database id or `created_at`."""
    payload = {
        "v": _OBSERVATION_FINGERPRINT_FORMAT,
        "memory_version": DECISION_MEMORY_VERSION,
        "decision_identity_key": decision_identity_key,
        "run_input_fingerprint": run_input_fingerprint,
        "as_of_local_date": as_of_local_date.isoformat(),
        "source_status": source_status.value,
        "lifecycle_transition": lifecycle_transition.value,
        "source_evaluation_fingerprint": source_evaluation_fingerprint,
        "source_target_key": source_target_key,
        "priority_candidate_fingerprint": priority_candidate_fingerprint,
        "priority_rank": priority_rank,
        "impact_score": _text(impact_score),
        "urgency_score": _text(urgency_score),
        "confidence_score": _text(confidence_score),
        "actionability_score": _text(actionability_score),
        "priority_score": _text(priority_score),
        "source_reason_codes": list(source_reason_codes),
        "facts_payload": facts_payload,
        "evidence_payload": evidence_payload,
    }
    return _hash(payload)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else canonical_text(value)


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


__all__ = ["observation_fingerprint", "run_input_fingerprint"]

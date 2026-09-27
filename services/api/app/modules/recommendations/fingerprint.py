"""Deterministic SHA-256 fingerprint of one `RecommendationResult`.

Includes exactly the fields that describe WHAT was recommended and WHY: the recommendation
version, the Decision's own semantic identity (`identity_version`/`identity_key`/`decision_type` -
never `decision.id`, a DB-generated UUID), the source observation's own semantic evaluation
fingerprint (never `observation.id`), the status, every action code in order, each action's
canonicalised supporting facts, every risk note, and confidence. Excludes anything DB-generated
or wall-clock (`decision.id`, `observation.id`, `created_at`, any timestamp) and any display copy
(`title_key`/`description_key` are pure functions of `action_code`, so including them would only
duplicate information already in the action codes without adding anything the hash needs).
"""

import hashlib
import json
from collections.abc import Sequence

from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.types import Action, RecommendationStatus


def _action_payload(action: Action) -> dict[str, object]:
    return {
        "action_code": action.action_code.value,
        "category": action.category.value,
        "scope": action.scope.value,
        "supporting_facts": dict(sorted(action.supporting_facts.items())),
        "risk_notes": [note.value for note in action.risk_notes],
    }


def recommendation_fingerprint(
    *,
    recommendation_version: str,
    decision_type: PriorityDecisionType,
    identity_version: str,
    identity_key: str,
    source_evaluation_fingerprint: str,
    status: RecommendationStatus,
    primary_action: Action | None,
    supporting_checks: Sequence[Action],
    confidence: str | None,
) -> str:
    payload = {
        "recommendation_version": recommendation_version,
        "decision_type": decision_type.value,
        "identity_version": identity_version,
        "identity_key": identity_key,
        "source_evaluation_fingerprint": source_evaluation_fingerprint,
        "status": status.value,
        "primary_action": None if primary_action is None else _action_payload(primary_action),
        "supporting_checks": [_action_payload(action) for action in supporting_checks],
        "confidence": confidence,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


__all__ = ["recommendation_fingerprint"]

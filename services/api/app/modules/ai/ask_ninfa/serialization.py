"""`AskDecisionContext` -> canonical JSON: DATA handed to a provider, never pseudo-instructions.

Every field is written out by hand (never `dataclasses.asdict()`, which would silently follow a
future nested field this module was not updated to review) so this stays the one, auditable place
that decides the exact shape a language model provider receives. `json.dumps(..., sort_keys=True)`
gives a deterministic, byte-stable string for the same context every time - useful for tests and
for the prompt-snapshot invariant checks, though (unlike Gate 16's own fingerprint) nothing here
hashes it: there is no cross-request identity to preserve, only the same input producing the same
output.
"""

import json

from app.modules.ai.ask_ninfa.types import (
    AskActionContext,
    AskDataPoint,
    AskDecisionContext,
    AskObservationContext,
)


def _data_point_dict(point: AskDataPoint) -> dict[str, object]:
    return {"label": point.label, "value": point.value, "unit": point.unit}


def _observation_dict(observation: AskObservationContext) -> dict[str, object]:
    # Gate 19.1b: the JSON key is "affidabilita", never "confidence" - the live answer that
    # exposed this gate echoed the English word "confidence" verbatim, traced back to this exact
    # key (plus this module's OWN system instructions using the same English word - both fixed
    # together, see ADR 0026's own update and instructions.py rule 4/25).
    return {
        "as_of_local_date": observation.as_of_local_date,
        "status": observation.status_label,
        "affidabilita": observation.confidence,
        "facts": [_data_point_dict(point) for point in observation.facts],
        "evidence": [_data_point_dict(point) for point in observation.evidence],
    }


def _action_dict(action: AskActionContext) -> dict[str, object]:
    return {
        "title": action.title,
        "description": action.description,
        "risk_notes": list(action.risk_notes),
    }


def context_to_dict(context: AskDecisionContext) -> dict[str, object]:
    """The explicit, hand-built dict `serialize_context` encodes - exposed separately so a test can
    assert on structure without re-parsing JSON."""
    return {
        "decision": context.decision_label,
        "decision_status": context.decision_status,
        "first_seen_local_date": context.first_seen_local_date,
        "last_seen_local_date": context.last_seen_local_date,
        "last_evaluated_local_date": context.last_evaluated_local_date,
        "resolved_local_date": context.resolved_local_date,
        "episode_count": context.episode_count,
        "target": dict(context.target),
        "latest": _observation_dict(context.latest),
        "recommendation": {
            "primary_action": (
                None
                if context.recommendation.primary_action is None
                else _action_dict(context.recommendation.primary_action)
            ),
            "supporting_checks": [
                _action_dict(action) for action in context.recommendation.supporting_checks
            ],
        },
        "history": [_observation_dict(observation) for observation in context.history],
    }


def serialize_context(context: AskDecisionContext) -> str:
    return json.dumps(context_to_dict(context), sort_keys=True, ensure_ascii=False)


__all__ = ["context_to_dict", "serialize_context"]

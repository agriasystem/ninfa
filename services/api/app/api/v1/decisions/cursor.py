"""Opaque, versioned, unsigned keyset cursors for Decision API V1's two paginated endpoints.

Base64url of a small canonical JSON object - stdlib only, no new dependency. NOT signed: a cursor
carries no authority (it is never trusted as a tenant/property scope, only as a keyset position
inside a query the caller has already been authorized for), so there is nothing to protect against
tampering beyond "does it still decode to a coherent keyset" - a tampered cursor can only ever
change WHERE in an already-authorized page the client resumes, never WHAT tenant/property it reads
(`resolve_property_scope` and every repository query below still filter by the real, server-
derived `TenantContext` and `property_id`, regardless of what the cursor says).
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.api.v1.decisions.errors import InvalidCursorError
from app.modules.intelligence.priority.types import PriorityDecisionType

DECISION_LIST_CURSOR_VERSION = "decision-list-cursor-v1"
DECISION_HISTORY_CURSOR_VERSION = "decision-history-cursor-v1"


@dataclass(frozen=True, slots=True)
class DecisionListCursor:
    """The keyset position of `list_decisions_page`'s stable order: `last_evaluated_local_date
    DESC, last_seen_local_date DESC, decision_type, decision_id` - the exact tuple of the LAST row
    of the previous page."""

    last_evaluated_local_date: date
    last_seen_local_date: date
    decision_type: PriorityDecisionType
    decision_id: UUID


@dataclass(frozen=True, slots=True)
class DecisionHistoryCursor:
    """The keyset position of the history endpoint's `as_of_local_date DESC, run_sequence DESC,
    observation_id` order - the exact tuple of the LAST row of the previous page."""

    as_of_local_date: date
    run_sequence: int
    observation_id: UUID


def _encode(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode(cursor: str) -> dict[str, Any]:
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(decoded.decode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError() from exc
    if not isinstance(payload, dict):
        raise InvalidCursorError()
    return payload


def encode_decision_list_cursor(cursor: DecisionListCursor) -> str:
    return _encode(
        {
            "v": DECISION_LIST_CURSOR_VERSION,
            "last_evaluated_local_date": cursor.last_evaluated_local_date.isoformat(),
            "last_seen_local_date": cursor.last_seen_local_date.isoformat(),
            "decision_type": cursor.decision_type.value,
            "decision_id": str(cursor.decision_id),
        }
    )


def decode_decision_list_cursor(cursor: str) -> DecisionListCursor:
    payload = _decode(cursor)
    if payload.get("v") != DECISION_LIST_CURSOR_VERSION:
        raise InvalidCursorError()
    try:
        return DecisionListCursor(
            last_evaluated_local_date=date.fromisoformat(payload["last_evaluated_local_date"]),
            last_seen_local_date=date.fromisoformat(payload["last_seen_local_date"]),
            decision_type=PriorityDecisionType(payload["decision_type"]),
            decision_id=UUID(payload["decision_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCursorError() from exc


def encode_decision_history_cursor(cursor: DecisionHistoryCursor) -> str:
    return _encode(
        {
            "v": DECISION_HISTORY_CURSOR_VERSION,
            "as_of_local_date": cursor.as_of_local_date.isoformat(),
            "run_sequence": cursor.run_sequence,
            "observation_id": str(cursor.observation_id),
        }
    )


def decode_decision_history_cursor(cursor: str) -> DecisionHistoryCursor:
    payload = _decode(cursor)
    if payload.get("v") != DECISION_HISTORY_CURSOR_VERSION:
        raise InvalidCursorError()
    try:
        run_sequence = payload["run_sequence"]
        if not isinstance(run_sequence, int) or isinstance(run_sequence, bool):
            raise InvalidCursorError()
        return DecisionHistoryCursor(
            as_of_local_date=date.fromisoformat(payload["as_of_local_date"]),
            run_sequence=run_sequence,
            observation_id=UUID(payload["observation_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCursorError() from exc


__all__ = [
    "DECISION_HISTORY_CURSOR_VERSION",
    "DECISION_LIST_CURSOR_VERSION",
    "DecisionHistoryCursor",
    "DecisionListCursor",
    "decode_decision_history_cursor",
    "decode_decision_list_cursor",
    "encode_decision_history_cursor",
    "encode_decision_list_cursor",
]

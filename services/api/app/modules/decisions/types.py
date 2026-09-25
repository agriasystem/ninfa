"""The vocabulary of Decision Persistence, Lifecycle and Memory V1: versions, statuses,
transitions and the typed, immutable result of one sync.

A detector evaluation is an OBSERVATION: what a detector concluded, once, from the data it was
given. A Decision is the persistent identity of the operational problem itself, recognised across
many observations over time (see docs/architecture/decision-layer-v1.md). Nothing here is a
recommendation, generated prose, AI or a business API: this module only remembers structured facts
that a real detector already produced.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID

# Re-exported so every detector's own five-status vocabulary is reused, never reinterpreted (the
# Decision Layer persists a detector's SOURCE STATUS as it is, exactly like every other module
# that reads it - see app.modules.intelligence.priority.service).
from app.modules.intelligence.revenue.types import EvaluationStatus as SourceStatus

DECISION_LAYER_VERSION = "decision-layer-v1"
DECISION_IDENTITY_VERSION = "decision-identity-v1"
DECISION_MEMORY_VERSION = "decision-memory-v1"
DECISION_LIFECYCLE_VERSION = "decision-lifecycle-v1"


class DecisionStatus(StrEnum):
    """The current lifecycle state of a Decision row. V1 has exactly two: no SUPPRESSED, no
    ARCHIVED, no DISMISSED - those belong to a later gate's business API."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class LifecycleTransition(StrEnum):
    """What ONE Observation did to its Decision's lifecycle, decided by the lifecycle rules in
    docs/architecture/decision-layer-v1.md - never recomputed from the Decision's current row."""

    OPENED = "OPENED"  # no Decision existed for this identity before this Observation
    OBSERVED = "OBSERVED"  # OPEN + TRIGGERED again: same Decision, no status change
    RESOLVED = "RESOLVED"  # OPEN + CLEAR: the only automatic resolution in V1
    REOPENED = "REOPENED"  # RESOLVED + TRIGGERED: same Decision id, status back to OPEN
    NO_STATE_CHANGE = "NO_STATE_CHANGE"  # INSUFFICIENT_DATA/SUPPRESSED/NOT_APPLICABLE, either way


__all__ = [
    "DECISION_IDENTITY_VERSION",
    "DECISION_LAYER_VERSION",
    "DECISION_LIFECYCLE_VERSION",
    "DECISION_MEMORY_VERSION",
    "DecisionStatus",
    "DecisionSyncResult",
    "LifecycleTransition",
    "SourceStatus",
]


@dataclass(frozen=True, slots=True)
class DecisionSyncResult:
    """The typed, immutable outcome of one `DecisionService.sync()` call.

    `is_idempotent_replay` is true when the exact same (workspace, property, as_of,
    input_fingerprint) was already synced: every count below is then the ORIGINAL run's, and
    nothing new was written. `touched_decision_ids` holds every Decision this run appended an
    Observation to or created, in no particular order (a set of ids, not a ranking).
    """

    decision_run_id: UUID
    as_of_local_date: date
    input_fingerprint: str

    is_idempotent_replay: bool

    created_decision_count: int
    observed_open_count: int
    resolved_count: int
    reopened_count: int
    no_state_change_count: int

    observation_count: int

    touched_decision_ids: tuple[UUID, ...] = field(default_factory=tuple)

    open_decision_count_after_sync: int = 0

    decision_layer_version: str = DECISION_LAYER_VERSION

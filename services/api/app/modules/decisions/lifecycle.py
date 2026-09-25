"""The lifecycle rules of Decision Persistence, Lifecycle and Memory V1 (`decision-lifecycle-v1`),
as a pure function of (does a Decision already exist, its current status, the new source status).

Kept separate from `service.py` (which owns the database work) so the eight rules in
docs/architecture/decision-layer-v1.md can be read - and tested - as ONE small, pure table, with
no session, no repository and no I/O anywhere in this module.
"""

from dataclasses import dataclass
from datetime import date

from app.modules.decisions.types import DecisionStatus, LifecycleTransition, SourceStatus

_TRIGGERED = SourceStatus.TRIGGERED
_CLEAR = SourceStatus.CLEAR


@dataclass(frozen=True, slots=True)
class LifecycleOutcome:
    """What ONE evaluation does to ONE Decision - or does nothing at all.

    `applies` is false only for "non-TRIGGERED, no existing Decision" (never create one just to
    remember a CLEAR/INSUFFICIENT/NOT_APPLICABLE/SUPPRESSED that never became a real problem).
    Every other field is meaningless when `applies` is false.
    """

    applies: bool
    transition: LifecycleTransition
    status: DecisionStatus
    first_seen_local_date: date | None = None
    last_seen_local_date: date | None = None
    last_evaluated_local_date: date | None = None
    resolved_local_date: date | None = None
    episode_count_delta: int = 0
    triggered_observation_count_delta: int = 0


_NOOP = LifecycleOutcome(
    applies=False, transition=LifecycleTransition.NO_STATE_CHANGE, status=DecisionStatus.OPEN
)


def apply_lifecycle(
    *,
    source_status: SourceStatus,
    as_of_local_date: date,
    existing_status: DecisionStatus | None,
) -> LifecycleOutcome:
    """`existing_status=None` means no Decision exists yet for this identity."""
    if existing_status is None:
        if source_status != _TRIGGERED:
            # REGOLA: CLEAR/insufficient/suppressed/N/A with no existing Decision creates nothing
            # ("Decision Memory serve a ricordare problemi reali già emersi, non ogni CLEAR
            # storico").
            return _NOOP
        # REGOLA 1: first trigger opens a new Decision.
        return LifecycleOutcome(
            applies=True,
            transition=LifecycleTransition.OPENED,
            status=DecisionStatus.OPEN,
            first_seen_local_date=as_of_local_date,
            last_seen_local_date=as_of_local_date,
            last_evaluated_local_date=as_of_local_date,
            resolved_local_date=None,
            episode_count_delta=1,
            triggered_observation_count_delta=1,
        )

    if existing_status == DecisionStatus.OPEN:
        if source_status == _TRIGGERED:
            # REGOLA 2: same Decision, still open, one more episode observation.
            return LifecycleOutcome(
                applies=True,
                transition=LifecycleTransition.OBSERVED,
                status=DecisionStatus.OPEN,
                last_seen_local_date=as_of_local_date,
                last_evaluated_local_date=as_of_local_date,
                triggered_observation_count_delta=1,
            )
        if source_status == _CLEAR:
            # REGOLA 3: the ONLY automatic resolution in V1. last_seen never moves here - it keeps
            # meaning "the last time this was actually TRIGGERED".
            return LifecycleOutcome(
                applies=True,
                transition=LifecycleTransition.RESOLVED,
                status=DecisionStatus.RESOLVED,
                last_evaluated_local_date=as_of_local_date,
                resolved_local_date=as_of_local_date,
            )
        # REGOLA 4/5/6: INSUFFICIENT_DATA / SUPPRESSED_LOW_CONFIDENCE / NOT_APPLICABLE never
        # resolve an OPEN Decision - only last_evaluated advances.
        return LifecycleOutcome(
            applies=True,
            transition=LifecycleTransition.NO_STATE_CHANGE,
            status=DecisionStatus.OPEN,
            last_evaluated_local_date=as_of_local_date,
        )

    # existing_status == RESOLVED
    if source_status == _TRIGGERED:
        # REGOLA 7: reopen - SAME Decision id, a new episode, resolved date cleared.
        return LifecycleOutcome(
            applies=True,
            transition=LifecycleTransition.REOPENED,
            status=DecisionStatus.OPEN,
            last_seen_local_date=as_of_local_date,
            last_evaluated_local_date=as_of_local_date,
            resolved_local_date=None,
            episode_count_delta=1,
            triggered_observation_count_delta=1,
        )
    # REGOLA 8: RESOLVED + CLEAR/insufficient/suppressed/N/A stays RESOLVED.
    return LifecycleOutcome(
        applies=True,
        transition=LifecycleTransition.NO_STATE_CHANGE,
        status=DecisionStatus.RESOLVED,
        last_evaluated_local_date=as_of_local_date,
    )


__all__ = ["LifecycleOutcome", "apply_lifecycle"]

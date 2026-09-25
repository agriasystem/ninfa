"""Gate 12 (Decision API V1) result vocabulary of `DecisionMemoryService`'s read-only query
methods. Framework-free, exactly like every other type in this module tree: nothing here imports
FastAPI or Pydantic - the API layer (`app/api/v1/decisions/`) maps these into its own response
schemas and never the other way around.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun

DECISION_API_VERSION = "decision-api-v1"


class FeedState(StrEnum):
    """See docs/architecture/decision-api-v1.md, "Feed states" and ADR 0018.

    NOT_PROCESSED         no DecisionRun exists for this property/as-of at all.
    ACTION_REQUIRED       the latest run's own triggered_count > 0.
    DATA_QUALITY_LIMITED  triggered_count == 0 AND (insufficient_count > 0 OR suppressed_count > 0).
    NO_ACTION_REQUIRED    triggered_count == 0 AND insufficient_count == 0 AND suppressed_count == 0
                           (a NOT_APPLICABLE-only or all-CLEAR run still counts as this: absence of
                           an applicable rule is never, by itself, a data-quality problem).
    """

    NOT_PROCESSED = "NOT_PROCESSED"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    DATA_QUALITY_LIMITED = "DATA_QUALITY_LIMITED"


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One TRIGGERED Observation of the feed's selected run, paired with its Decision's current
    lifecycle row (identity, first_seen/last_seen, episode_count - the feed never duplicates these
    onto the Observation itself)."""

    observation: DecisionObservation
    decision: Decision


@dataclass(frozen=True, slots=True)
class FeedResult:
    """The typed, immutable outcome of `DecisionMemoryService.get_feed()`. `run` is `None` only
    when `state is FeedState.NOT_PROCESSED`; `items` is non-empty only when `state is
    FeedState.ACTION_REQUIRED` (every other state has nothing to act on, by construction - see
    `FeedState`'s own docstring)."""

    property_id: UUID
    as_of_local_date: date
    state: FeedState
    run: DecisionRun | None
    items: tuple[FeedItem, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionListPage:
    """One keyset page of Decisions plus the latest Observation of each, loaded set-based (never
    one SELECT per Decision - see `DecisionRepository.latest_observations_of`). A Decision with no
    Observation at all cannot exist (Gate 11's own lifecycle rule: a Decision is only ever created
    alongside its first Observation), so `latest_observations` always has one entry per Decision
    here - `dict.__getitem__`, not `.get()`, is the caller's own promise to itself."""

    decisions: tuple[Decision, ...]
    latest_observations: dict[UUID, DecisionObservation]
    has_more: bool


@dataclass(frozen=True, slots=True)
class HistoryObservation:
    """One Observation of the API's own newest-first history order, paired with the
    `run_sequence` of the run that produced it (needed to build the next page's cursor without a
    further query - see `DecisionRepository.history_page_desc`)."""

    observation: DecisionObservation
    run_sequence: int


@dataclass(frozen=True, slots=True)
class HistoryPage:
    items: tuple[HistoryObservation, ...]
    has_more: bool


__all__ = [
    "DECISION_API_VERSION",
    "DecisionListPage",
    "FeedItem",
    "FeedResult",
    "FeedState",
    "HistoryObservation",
    "HistoryPage",
]

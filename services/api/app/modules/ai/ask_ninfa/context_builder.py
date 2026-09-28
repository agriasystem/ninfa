"""AskDecisionContextBuilder: pure, framework-free, testable.

    AskDecisionContextBuilder().build(decision, latest_observation, recommendation, history)
    -> AskDecisionContext

No database session, no HTTP dependency - the caller (the `/ask` route) already has all four
inputs in scope, exactly the same posture `RecommendationEngine.evaluate()` (Gate 16) established
for its own two inputs. `history` is whatever the caller already fetched (bounded, newest-first,
via `DecisionMemoryService.get_history_page_desc()`); this builder still defensively re-bounds and
re-orders it, so the invariant holds regardless of what a caller passes.

Explicit whitelisting only: no `dataclasses.asdict()` of a `Decision`/`DecisionObservation`, no
`__dict__`, no generic serialization anywhere in this module. `facts_of`/`evidence_of`
(`app.modules.decisions.whitelist`) are the SAME whitelist the Decision API's own serializers use -
one whitelist, not a second one that could silently drift apart.

Gate 19.1 (ADR 0026, "why model context is semantic"): every raw engine identifier this module
used to pass straight through - `decision_type`, `DecisionStatus`,
`source_status`/`lifecycle_transition`, `ActionCode`/`category`, `RiskNote`,
`cost_category`/`labor_category`, and every whitelisted fact/evidence key - is now translated to
Italian by `semantic_labels.py` BEFORE it ever reaches
`AskDecisionContext`. `reason_codes` and `priority_rank` are no longer collected here at all (see
`semantic_labels.py`'s own module docstring and `AskObservationContext`'s).
"""

from collections.abc import Sequence

from app.modules.ai.ask_ninfa import semantic_labels
from app.modules.ai.ask_ninfa.types import (
    MAX_HISTORY_OBSERVATIONS,
    AskActionContext,
    AskDecisionContext,
    AskObservationContext,
    AskRecommendationContext,
    ContextValue,
)
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.precision import canonical_text
from app.modules.decisions.whitelist import evidence_of, facts_of
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.recommendations.types import Action, RecommendationResult


def _str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _without_data_source_ids(mapping: dict[str, ContextValue]) -> dict[str, ContextValue]:
    """The shared `facts_of`/`evidence_of` whitelist (`app.modules.decisions.whitelist`) is
    correct for its OTHER caller, the Decision API's own HTTP serializers - a browser client is
    allowed to see a `booking_data_source_id`/`labor_data_source_id` UUID even though it never
    renders it (Gate 15, "No detail data leak"). A language model is held to the STRICTER bar this
    module's own docstring already states: no internal DB id unless semantically necessary - and
    linking two internal rows together is never semantically necessary for EXPLAINING a decision.
    This is Ask NINFA's own, additional filter on top of the shared whitelist, never a change to
    it (see ADR 0025, "why data source ids are stripped a second time")."""
    return {key: value for key, value in mapping.items() if not key.endswith("_data_source_id")}


def _target_context_of(decision: Decision) -> dict[str, str]:
    """The human-relevant subset of `Decision.identity_payload`: never a
    `*_data_source_id`/`booking_data_source_id`/`labor_data_source_id` UUID - an internal linkage
    id, not something a model needs to explain why a decision concerns a given stay date/period/
    work date. Explicit, per-type, never a generic passthrough of the raw payload."""
    payload = decision.identity_payload
    decision_type = decision.decision_type
    if decision_type in (
        PriorityDecisionType.REV_PICKUP_LOW,
        PriorityDecisionType.REV_OCCUPANCY_RISK,
    ):
        stay_date = _str(payload, "stay_date")
        return {} if stay_date is None else {"stay_date": stay_date}
    if decision_type is PriorityDecisionType.REV_OTA_DEPENDENCY:
        # No human-relevant target field exists for OTA beyond the (excluded) data source id - the
        # observed window itself already lives in `facts` (`window_start`/`window_end`).
        return {}
    if decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
        period_start = _str(payload, "target_period_start")
        category = _str(payload, "cost_category")
        currency = _str(payload, "currency")
        context: dict[str, str] = {}
        if period_start is not None:
            context["period_start"] = period_start
        if category is not None:
            context["cost_category"] = semantic_labels.cost_category_label_of(
                CostCategory(category)
            )
        if currency is not None:
            context["currency"] = currency
        return context
    if decision_type is PriorityDecisionType.LABOR_OVERSTAFFING:
        work_date = _str(payload, "work_date")
        category = _str(payload, "labor_category")
        context = {}
        if work_date is not None:
            context["work_date"] = work_date
        if category is not None:
            context["labor_category"] = semantic_labels.labor_category_label_of(
                LaborCategory(category)
            )
        return context
    raise ValueError(f"unrecognised decision_type {decision_type!r}")  # pragma: no cover


def _observation_context_of(
    decision_type: PriorityDecisionType, observation: DecisionObservation
) -> AskObservationContext:
    # `canonical_text` is typed `Decimal | None -> str | None` (it also serves genuinely optional
    # scores elsewhere); `confidence_score` itself is NOT NULL on `DecisionObservation`, so this
    # never actually returns `None` - narrowed explicitly for mypy, not defensive dead code.
    confidence = canonical_text(observation.confidence_score)
    assert confidence is not None
    facts_payload = _without_data_source_ids(facts_of(decision_type, observation.facts_payload))
    evidence_payload = _without_data_source_ids(
        evidence_of(decision_type, observation.evidence_payload)
    )
    return AskObservationContext(
        as_of_local_date=observation.as_of_local_date.isoformat(),
        status_label=semantic_labels.observation_status_label_of(
            observation.lifecycle_transition, observation.source_status
        ),
        confidence=confidence,
        facts=semantic_labels.data_points_of(
            semantic_labels.FACT_LABELS[decision_type], facts_payload
        ),
        evidence=semantic_labels.data_points_of(
            semantic_labels.EVIDENCE_LABELS[decision_type], evidence_payload
        ),
    )


def _action_context_of(action: Action, *, is_primary: bool) -> AskActionContext:
    if is_primary:
        title = semantic_labels.primary_action_title_of(action.action_code)
        description: str | None = semantic_labels.primary_action_description_of(action.action_code)
    else:
        title = semantic_labels.supporting_action_title_of(action.action_code)
        description = None
    return AskActionContext(
        title=title,
        description=description,
        risk_notes=tuple(semantic_labels.risk_note_text_of(note) for note in action.risk_notes),
    )


def _recommendation_context_of(result: RecommendationResult) -> AskRecommendationContext:
    primary = result.primary_action
    return AskRecommendationContext(
        primary_action=None if primary is None else _action_context_of(primary, is_primary=True),
        supporting_checks=tuple(
            _action_context_of(action, is_primary=False) for action in result.supporting_checks
        ),
    )


class AskDecisionContextBuilder:
    def build(
        self,
        decision: Decision,
        latest_observation: DecisionObservation,
        recommendation: RecommendationResult,
        history: Sequence[DecisionObservation],
    ) -> AskDecisionContext:
        decision_type = decision.decision_type

        # Defensive re-bound + re-order: `history` arrives newest-first (the same order
        # `DecisionMemoryService.get_history_page_desc()` returns); the model context is
        # chronological (oldest -> newest) so the evolution reads top-to-bottom, in the order it
        # actually happened - never AI-summarised, just re-ordered.
        bounded_newest_first = list(history)[:MAX_HISTORY_OBSERVATIONS]
        chronological = tuple(
            _observation_context_of(decision_type, observation)
            for observation in reversed(bounded_newest_first)
        )

        return AskDecisionContext(
            decision_label=semantic_labels.decision_label_of(decision_type),
            decision_status=semantic_labels.decision_status_label_of(decision.status),
            first_seen_local_date=decision.first_seen_local_date.isoformat(),
            last_seen_local_date=decision.last_seen_local_date.isoformat(),
            last_evaluated_local_date=decision.last_evaluated_local_date.isoformat(),
            resolved_local_date=(
                None
                if decision.resolved_local_date is None
                else decision.resolved_local_date.isoformat()
            ),
            episode_count=decision.episode_count,
            target=_target_context_of(decision),
            latest=_observation_context_of(decision_type, latest_observation),
            recommendation=_recommendation_context_of(recommendation),
            history=chronological,
        )


__all__ = ["AskDecisionContextBuilder"]

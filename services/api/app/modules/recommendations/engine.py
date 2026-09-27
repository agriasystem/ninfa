"""RecommendationEngine: pure, deterministic, framework-free.

    RecommendationEngine().evaluate(decision, latest_observation) -> RecommendationResult

No database session, no repository, no HTTP, no detector, no `PriorityService`, no `Expected`
recalculation - the ONLY inputs are a persisted `Decision` and its latest `DecisionObservation`,
exactly as Gate 11 already wrote them (see ADR 0022, "why DecisionObservation is the input
boundary"). The same two objects always produce byte-identical output: nothing here reads a
clock, a random source, or any other module's live state.
"""

from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.precision import canonical_text
from app.modules.decisions.types import SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.errors import UnsupportedDecisionTypeError
from app.modules.recommendations.fingerprint import recommendation_fingerprint
from app.modules.recommendations.rules import (
    RuleOutcome,
    cost_rule,
    labor_rule,
    occupancy_rule,
    ota_rule,
    pickup_rule,
)
from app.modules.recommendations.types import (
    MAX_SUPPORTING_CHECKS,
    RECOMMENDATION_ENGINE_VERSION,
    Action,
    RecommendationResult,
    RecommendationStatus,
)

_RULE_BY_TYPE = {
    PriorityDecisionType.REV_PICKUP_LOW: pickup_rule,
    PriorityDecisionType.REV_OCCUPANCY_RISK: occupancy_rule,
    PriorityDecisionType.REV_OTA_DEPENDENCY: ota_rule,
    PriorityDecisionType.COST_CPOR_ANOMALY: cost_rule,
    PriorityDecisionType.LABOR_OVERSTAFFING: labor_rule,
}


def _confidence_text(observation: DecisionObservation) -> str | None:
    """Copied, never recomputed, never a second probabilistic model - `None` only if the
    persisted value is itself missing (the DB schema makes this NOT NULL; this check exists so a
    genuinely corrupt/mocked row fails closed to INSUFFICIENT_CONTEXT rather than crashing)."""
    if observation.confidence_score is None:
        return None
    return canonical_text(observation.confidence_score)


class RecommendationEngine:
    def evaluate(
        self, decision: Decision, latest_observation: DecisionObservation
    ) -> RecommendationResult:
        if latest_observation.source_status is not SourceStatus.TRIGGERED:
            # NOT_AVAILABLE regardless of decision.status: an OPEN Decision whose CURRENT
            # observation is not TRIGGERED has nothing to recommend right now (see ADR 0022, "why
            # OPEN alone is insufficient").
            return self._build(
                decision,
                latest_observation,
                status=RecommendationStatus.NOT_AVAILABLE,
                primary_action=None,
                supporting_checks=(),
                confidence=None,
            )

        rule = _RULE_BY_TYPE.get(decision.decision_type)
        if rule is None:
            raise UnsupportedDecisionTypeError(decision.decision_type)  # pragma: no cover

        confidence = _confidence_text(latest_observation)
        outcome: RuleOutcome | None = rule(latest_observation.facts_payload)

        if confidence is None or outcome is None:
            return self._build(
                decision,
                latest_observation,
                status=RecommendationStatus.INSUFFICIENT_CONTEXT,
                primary_action=None,
                supporting_checks=(),
                confidence=confidence,
            )

        return self._build(
            decision,
            latest_observation,
            status=RecommendationStatus.AVAILABLE,
            primary_action=outcome.primary,
            supporting_checks=outcome.supporting[:MAX_SUPPORTING_CHECKS],
            confidence=confidence,
        )

    @staticmethod
    def _build(
        decision: Decision,
        latest_observation: DecisionObservation,
        *,
        status: RecommendationStatus,
        primary_action: Action | None,
        supporting_checks: tuple[Action, ...],
        confidence: str | None,
    ) -> RecommendationResult:
        fingerprint = recommendation_fingerprint(
            recommendation_version=RECOMMENDATION_ENGINE_VERSION,
            decision_type=decision.decision_type,
            identity_version=decision.identity_version,
            identity_key=decision.identity_key,
            source_evaluation_fingerprint=latest_observation.source_evaluation_fingerprint,
            status=status,
            primary_action=primary_action,
            supporting_checks=supporting_checks,
            confidence=confidence,
        )
        return RecommendationResult(
            decision_id=decision.id,
            decision_type=decision.decision_type,
            recommendation_version=RECOMMENDATION_ENGINE_VERSION,
            status=status,
            primary_action=primary_action,
            supporting_checks=supporting_checks,
            generated_from_observation_id=latest_observation.id,
            generated_from_evaluation_fingerprint=latest_observation.source_evaluation_fingerprint,
            reason_codes=tuple(latest_observation.source_reason_codes),
            confidence=confidence,
            fingerprint=fingerprint,
        )


__all__ = ["RecommendationEngine"]

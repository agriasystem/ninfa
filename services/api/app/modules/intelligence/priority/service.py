"""PriorityService: SIGNALS -> ORDER. Zero database, zero detector execution, zero writes.

    DATA -> DETECTOR SERVICES -> TRIGGERED EVALUATIONS -> PriorityService -> RANKED CANDIDATES

`rank()` receives evaluations ALREADY computed by Gate 5/7/8/9's own services, of ANY status; it
never calls a `BookingRepository`, an `InvoiceRepository`, a detector or the database, and it
never recomputes a detector's own facts (separation of concerns: detectors turn DATA into SIGNAL,
this engine turns SIGNAL into ORDER). This is what makes it independently testable without a
database session, and is why `PriorityService` takes no `Session` and no `TenantContext`: the
`PriorityContext` it is given already carries the only tenant scope it needs.
"""

from collections.abc import Iterable
from typing import Any

from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.priority.actionability import (
    actionability_policy_name,
    actionability_score,
)
from app.modules.intelligence.priority.adapters import AdaptedSignal, adapt_evaluation
from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.fingerprint import (
    candidate_fingerprint,
    ranking_fingerprint,
)
from app.modules.intelligence.priority.precision import for_display
from app.modules.intelligence.priority.ranking import (
    deduplicate_and_check_conflicts,
    rank_candidates,
)
from app.modules.intelligence.priority.scoring import priority_score_display, priority_score_exact
from app.modules.intelligence.priority.types import (
    PRIORITY_RULES_VERSION,
    PriorityCandidate,
    PriorityContext,
    PriorityRankingResult,
)
from app.modules.intelligence.revenue.types import EvaluationStatus, RevenueDecisionEvaluation

_TENANT_MISMATCH = PriorityErrorCode.PRIORITY_TENANT_MISMATCH
_PROPERTY_MISMATCH = PriorityErrorCode.PRIORITY_PROPERTY_MISMATCH
_INVALID = PriorityErrorCode.PRIORITY_INVALID_SOURCE_EVALUATION

_KNOWN_EVALUATION_TYPES = (
    RevenueDecisionEvaluation,
    OtaDependencyEvaluation,
    CostDecisionEvaluation,
    LaborDecisionEvaluation,
)

SourceEvaluation = (
    RevenueDecisionEvaluation
    | OtaDependencyEvaluation
    | CostDecisionEvaluation
    | LaborDecisionEvaluation
)


class PriorityService:
    """Pure and stateless: no `Session`, no `TenantContext`, no repository, no clock."""

    def rank(
        self, context: PriorityContext, evaluations: Iterable[SourceEvaluation]
    ) -> PriorityRankingResult:
        """One property-scoped ranking run at `context.as_of_local_date`.

        Every evaluation must belong to `context.workspace_id`/`context.property_id` (a mismatch
        REJECTS the whole run: `PriorityError` is raised, nothing partial is returned). Only
        `TRIGGERED` evaluations become candidates; every other status is excluded and counted.
        """
        clear_count = 0
        insufficient_count = 0
        not_applicable_count = 0
        suppressed_count = 0
        triggered: list[Any] = []

        for evaluation in evaluations:
            if not isinstance(evaluation, _KNOWN_EVALUATION_TYPES):
                raise PriorityError(
                    _INVALID, f"unrecognised source evaluation type {type(evaluation)!r}"
                )
            if evaluation.workspace_id != context.workspace_id:
                raise PriorityError(
                    _TENANT_MISMATCH,
                    f"evaluation workspace {evaluation.workspace_id} != "
                    f"context workspace {context.workspace_id}",
                )
            if evaluation.property_id != context.property_id:
                raise PriorityError(
                    _PROPERTY_MISMATCH,
                    f"evaluation property {evaluation.property_id} != "
                    f"context property {context.property_id}",
                )

            status = evaluation.status
            if status == EvaluationStatus.TRIGGERED:
                triggered.append(evaluation)
            elif status == EvaluationStatus.CLEAR:
                clear_count += 1
            elif status == EvaluationStatus.INSUFFICIENT_DATA:
                insufficient_count += 1
            elif status == EvaluationStatus.NOT_APPLICABLE:
                not_applicable_count += 1
            elif status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE:
                suppressed_count += 1
            else:  # pragma: no cover - defensive: the five statuses are the whole StrEnum
                raise PriorityError(_INVALID, f"unrecognised evaluation status {status!r}")

        signals: list[AdaptedSignal] = [
            adapt_evaluation(context, evaluation) for evaluation in triggered
        ]
        kept_signals, duplicate_input_count = deduplicate_and_check_conflicts(signals)

        candidates = [self._build_candidate(context, signal) for signal in kept_signals]
        ranked_candidates = rank_candidates(candidates)

        result_fingerprint = ranking_fingerprint(
            workspace_id=context.workspace_id,
            property_id=context.property_id,
            as_of_local_date=context.as_of_local_date,
            ranked_candidates=ranked_candidates,
            excluded_clear_count=clear_count,
            excluded_insufficient_count=insufficient_count,
            excluded_not_applicable_count=not_applicable_count,
            excluded_suppressed_count=suppressed_count,
            duplicate_input_count=duplicate_input_count,
            priority_version=PRIORITY_RULES_VERSION,
        )

        return PriorityRankingResult(
            workspace_id=context.workspace_id,
            property_id=context.property_id,
            as_of_local_date=context.as_of_local_date,
            candidate_count=len(ranked_candidates),
            excluded_clear_count=clear_count,
            excluded_insufficient_count=insufficient_count,
            excluded_not_applicable_count=not_applicable_count,
            excluded_suppressed_count=suppressed_count,
            duplicate_input_count=duplicate_input_count,
            ranked_candidates=ranked_candidates,
            priority_version=PRIORITY_RULES_VERSION,
            calculation_fingerprint=result_fingerprint,
        )

    @staticmethod
    def _build_candidate(context: PriorityContext, signal: AdaptedSignal) -> PriorityCandidate:
        actionability = actionability_score(signal.decision_type)
        exact = priority_score_exact(
            impact_score=signal.impact_score_exact,
            urgency_score=signal.urgency_score,
            confidence_score=signal.confidence_score,
            actionability_score=actionability,
        )
        fingerprint = candidate_fingerprint(
            decision_type=signal.decision_type,
            workspace_id=signal.workspace_id,
            property_id=signal.property_id,
            priority_as_of_date=context.as_of_local_date,
            source_evaluation_fingerprint=signal.source_evaluation_fingerprint,
            source_target_key=signal.source_target_key,
            impact_score_exact=signal.impact_score_exact,
            urgency_score=signal.urgency_score,
            confidence_score=signal.confidence_score,
            actionability_score=actionability,
            priority_score_exact=exact,
            impact_basis=signal.impact_basis,
            urgency_basis=signal.urgency_basis,
            source_reason_codes=signal.source_reason_codes,
            priority_version=PRIORITY_RULES_VERSION,
        )
        return PriorityCandidate(
            decision_type=signal.decision_type,
            workspace_id=signal.workspace_id,
            property_id=signal.property_id,
            priority_as_of_date=context.as_of_local_date,
            source_evaluation_fingerprint=signal.source_evaluation_fingerprint,
            source_target_key=signal.source_target_key,
            impact_score_exact=signal.impact_score_exact,
            impact_score_display=for_display(signal.impact_score_exact),
            urgency_score=signal.urgency_score,
            confidence_score=signal.confidence_score,
            actionability_score=actionability,
            priority_score_exact=exact,
            priority_score_display=priority_score_display(exact),
            impact_basis=signal.impact_basis,
            urgency_basis=signal.urgency_basis,
            actionability_policy=actionability_policy_name(),
            economic_proxy_exact=signal.economic_proxy_exact,
            economic_proxy_currency=signal.economic_proxy_currency,
            economic_proxy_label=signal.economic_proxy_label,
            source_reason_codes=signal.source_reason_codes,
            priority_version=PRIORITY_RULES_VERSION,
            calculation_fingerprint=fingerprint,
        )

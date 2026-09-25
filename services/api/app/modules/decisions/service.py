"""DecisionService: ORDERED SIGNALS -> DECISION IDENTITY -> PERSISTENCE -> LIFECYCLE -> MEMORY.

    PriorityContext + PriorityRankingResult + source evaluations -> DecisionService.sync()
    -> DecisionSyncResult

`sync()` is the ONLY write path of the Decision Layer, and it is ALL OR NOTHING: validate input,
create or reuse the `DecisionRun`, load the existing Decisions of the touched identities
(set-based), apply the lifecycle rules, insert the Observations, update the Decision rows - one
transaction, one commit, or a full rollback. It never re-derives a detector's own status and never
recomputes a Priority score: both are read, once, and persisted exactly as they arrived.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_decision_layer
from app.modules.decisions.errors import DecisionError, DecisionErrorCode
from app.modules.decisions.fingerprint import observation_fingerprint, run_input_fingerprint
from app.modules.decisions.identity import (
    DecisionIdentity,
    SourceEvaluation,
    build_identity,
    raw_target_key,
    verify_identity,
)
from app.modules.decisions.lifecycle import apply_lifecycle
from app.modules.decisions.models import Decision
from app.modules.decisions.repository import DecisionRepository
from app.modules.decisions.serialization import reason_codes_of, serialize_facts
from app.modules.decisions.types import (
    DECISION_IDENTITY_VERSION,
    DECISION_MEMORY_VERSION,
    DecisionStatus,
    DecisionSyncResult,
    LifecycleTransition,
    SourceStatus,
)
from app.modules.intelligence.priority.types import (
    PriorityContext,
    PriorityDecisionType,
    PriorityRankingResult,
    RankedPriorityCandidate,
)

logger = logging.getLogger(__name__)

_INPUT_MISMATCH = DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH
_CONFLICT = DecisionErrorCode.DECISION_CONFLICTING_SOURCE_EVALUATION
_OUT_OF_ORDER = DecisionErrorCode.DECISION_OUT_OF_ORDER_RUN

_STATUS_FIELD = {
    SourceStatus.CLEAR: "clear_count",
    SourceStatus.INSUFFICIENT_DATA: "insufficient_count",
    SourceStatus.NOT_APPLICABLE: "not_applicable_count",
    SourceStatus.SUPPRESSED_LOW_CONFIDENCE: "suppressed_count",
}


@dataclass(frozen=True, slots=True)
class _Kept:
    """One logical evaluation this run will act on, AFTER duplicate/conflict resolution."""

    identity: DecisionIdentity
    evaluation: SourceEvaluation


class DecisionService:
    """Owns the transaction: pass a session with no uncommitted work, this call commits it (or
    rolls it back whole on any failure)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Decision service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._repo = DecisionRepository(session, tenant)

    def sync(
        self,
        context: PriorityContext,
        ranking_result: PriorityRankingResult,
        evaluations: Iterable[SourceEvaluation],
    ) -> DecisionSyncResult:
        try:
            return self._sync(context, ranking_result, list(evaluations))
        except Exception:
            self._session.rollback()
            raise

    # --- the whole sync, inside one transaction ------------------------------------------------

    def _sync(
        self,
        context: PriorityContext,
        ranking_result: PriorityRankingResult,
        evaluations: list[SourceEvaluation],
    ) -> DecisionSyncResult:
        if context.workspace_id != self._tenant.workspace_id:
            raise DecisionError(
                _INPUT_MISMATCH, "PriorityContext.workspace_id does not match this TenantContext"
            )
        self._validate_ranking_context(context, ranking_result)
        for evaluation in evaluations:
            self._validate_evaluation_scope(context, evaluation)

        kept, duplicate_input_count = self._deduplicate(evaluations)
        counts = self._tally(kept)
        self._validate_against_ranking(kept, counts, ranking_result)
        candidates_by_fingerprint = self._candidates_by_fingerprint(kept, ranking_result)

        input_fingerprint = run_input_fingerprint(
            workspace_id=context.workspace_id,
            property_id=context.property_id,
            as_of_local_date=context.as_of_local_date,
            source_evaluation_fingerprints=(
                item.evaluation.calculation_fingerprint for item in kept
            ),
            priority_ranking_fingerprint=ranking_result.calculation_fingerprint,
            evaluation_count=len(kept),
            triggered_count=counts[SourceStatus.TRIGGERED],
            clear_count=counts[SourceStatus.CLEAR],
            insufficient_count=counts[SourceStatus.INSUFFICIENT_DATA],
            not_applicable_count=counts[SourceStatus.NOT_APPLICABLE],
            suppressed_count=counts[SourceStatus.SUPPRESSED_LOW_CONFIDENCE],
            duplicate_input_count=duplicate_input_count,
        )

        lock_decision_layer(self._session, context.workspace_id, context.property_id)

        existing_run = self._repo.find_run(
            context.property_id, context.as_of_local_date, input_fingerprint
        )
        if existing_run is not None:
            open_after = self._count_open(context.property_id)
            self._session.commit()  # release the advisory lock; nothing was written
            return DecisionSyncResult(
                decision_run_id=existing_run.id,
                as_of_local_date=context.as_of_local_date,
                input_fingerprint=input_fingerprint,
                is_idempotent_replay=True,
                created_decision_count=0,
                observed_open_count=0,
                resolved_count=0,
                reopened_count=0,
                no_state_change_count=0,
                observation_count=0,
                touched_decision_ids=(),
                open_decision_count_after_sync=open_after,
            )

        existing_decisions = self._repo.existing_by_identities(
            context.property_id, (item.identity for item in kept)
        )
        for item in kept:
            key = (item.identity.decision_type, item.identity.identity_key)
            decision = existing_decisions.get(key)
            if decision is not None:
                verify_identity(decision.identity_payload, item.identity)
                if context.as_of_local_date < decision.last_evaluated_local_date:
                    raise DecisionError(
                        _OUT_OF_ORDER,
                        "this run's as-of date is before the Decision's own last_evaluated_"
                        "local_date: history is never rewritten",
                        details={
                            "decision_identity_key": item.identity.identity_key,
                            "as_of_local_date": context.as_of_local_date.isoformat(),
                            "last_evaluated_local_date": (
                                decision.last_evaluated_local_date.isoformat()
                            ),
                        },
                    )

        run = self._repo.insert_run(
            {
                "property_id": context.property_id,
                "as_of_local_date": context.as_of_local_date,
                "input_fingerprint": input_fingerprint,
                "priority_ranking_fingerprint": ranking_result.calculation_fingerprint,
                "evaluation_count": len(kept),
                "triggered_count": counts[SourceStatus.TRIGGERED],
                "clear_count": counts[SourceStatus.CLEAR],
                "insufficient_count": counts[SourceStatus.INSUFFICIENT_DATA],
                "not_applicable_count": counts[SourceStatus.NOT_APPLICABLE],
                "suppressed_count": counts[SourceStatus.SUPPRESSED_LOW_CONFIDENCE],
                "duplicate_input_count": duplicate_input_count,
            }
        )

        created_count = observed_count = resolved_count = reopened_count = 0
        no_state_change_count = 0
        touched_ids: list[UUID] = []
        observation_rows: list[dict[str, object]] = []

        for item in sorted(kept, key=lambda item: item.identity.identity_key):
            identity = item.identity
            evaluation = item.evaluation
            key = (identity.decision_type, identity.identity_key)
            decision = existing_decisions.get(key)
            outcome = apply_lifecycle(
                source_status=evaluation.status,
                as_of_local_date=context.as_of_local_date,
                existing_status=None if decision is None else decision.status,
            )
            if not outcome.applies:
                continue  # a non-TRIGGERED evaluation with no existing Decision: remember nothing

            if decision is None:
                decision = self._repo.insert_decision(
                    {
                        "property_id": context.property_id,
                        "decision_type": identity.decision_type,
                        "identity_version": DECISION_IDENTITY_VERSION,
                        "identity_key": identity.identity_key,
                        "identity_payload": identity.identity_payload,
                        "status": outcome.status,
                        "first_seen_local_date": outcome.first_seen_local_date,
                        "last_seen_local_date": outcome.last_seen_local_date,
                        "last_evaluated_local_date": outcome.last_evaluated_local_date,
                        "resolved_local_date": outcome.resolved_local_date,
                        "episode_count": outcome.episode_count_delta,
                        "triggered_observation_count": outcome.triggered_observation_count_delta,
                    }
                )
            else:
                decision.status = outcome.status
                if outcome.last_seen_local_date is not None:
                    decision.last_seen_local_date = outcome.last_seen_local_date
                if outcome.last_evaluated_local_date is not None:
                    decision.last_evaluated_local_date = outcome.last_evaluated_local_date
                if outcome.transition == LifecycleTransition.RESOLVED:
                    decision.resolved_local_date = outcome.resolved_local_date
                elif outcome.transition == LifecycleTransition.REOPENED:
                    decision.resolved_local_date = None
                decision.episode_count += outcome.episode_count_delta
                decision.triggered_observation_count += outcome.triggered_observation_count_delta

            if outcome.transition == LifecycleTransition.OPENED:
                created_count += 1
            elif outcome.transition == LifecycleTransition.OBSERVED:
                observed_count += 1
            elif outcome.transition == LifecycleTransition.RESOLVED:
                resolved_count += 1
            elif outcome.transition == LifecycleTransition.REOPENED:
                reopened_count += 1
            else:
                no_state_change_count += 1
            touched_ids.append(decision.id)

            observation_rows.append(
                self._observation_row(
                    decision=decision,
                    run_id=run.id,
                    context=context,
                    identity=identity,
                    evaluation=evaluation,
                    transition=outcome.transition,
                    input_fingerprint=input_fingerprint,
                    candidate=candidates_by_fingerprint.get(evaluation.calculation_fingerprint),
                )
            )

        self._repo.insert_observations(observation_rows)
        self._session.flush()
        open_after = self._count_open(context.property_id)
        self._session.commit()

        logger.info(
            "decision sync workspace_id=%s property_id=%s as_of=%s run_id=%s created=%d "
            "observed=%d resolved=%d reopened=%d no_state_change=%d",
            context.workspace_id,
            context.property_id,
            context.as_of_local_date,
            run.id,
            created_count,
            observed_count,
            resolved_count,
            reopened_count,
            no_state_change_count,
        )

        return DecisionSyncResult(
            decision_run_id=run.id,
            as_of_local_date=context.as_of_local_date,
            input_fingerprint=input_fingerprint,
            is_idempotent_replay=False,
            created_decision_count=created_count,
            observed_open_count=observed_count,
            resolved_count=resolved_count,
            reopened_count=reopened_count,
            no_state_change_count=no_state_change_count,
            observation_count=len(observation_rows),
            touched_decision_ids=tuple(touched_ids),
            open_decision_count_after_sync=open_after,
        )

    # --- validation --------------------------------------------------------------------------

    @staticmethod
    def _validate_ranking_context(
        context: PriorityContext, ranking_result: PriorityRankingResult
    ) -> None:
        if ranking_result.workspace_id != context.workspace_id:
            raise DecisionError(_INPUT_MISMATCH, "ranking workspace_id does not match the context")
        if ranking_result.property_id != context.property_id:
            raise DecisionError(_INPUT_MISMATCH, "ranking property_id does not match the context")
        if ranking_result.as_of_local_date != context.as_of_local_date:
            raise DecisionError(
                _INPUT_MISMATCH, "ranking as_of_local_date does not match the context"
            )

    @staticmethod
    def _validate_evaluation_scope(context: PriorityContext, evaluation: SourceEvaluation) -> None:
        if evaluation.workspace_id != context.workspace_id:
            raise DecisionError(_INPUT_MISMATCH, "a source evaluation's workspace_id mismatches")
        if evaluation.property_id != context.property_id:
            raise DecisionError(_INPUT_MISMATCH, "a source evaluation's property_id mismatches")

    @staticmethod
    def _deduplicate(evaluations: list[SourceEvaluation]) -> tuple[list[_Kept], int]:
        """Group by DECISION IDENTITY (not the source target key): the same fingerprint seen again
        under the same identity is a duplicate (counted, the first copy kept); a DIFFERENT
        fingerprint under the same identity is a conflict (rejected, never chosen arbitrarily) -
        Gate 10's own duplicate/conflict semantics, one level up (by identity, not target key)."""
        kept_by_key: dict[tuple[PriorityDecisionType, str], _Kept] = {}
        fingerprints_by_key: dict[tuple[PriorityDecisionType, str], set[str]] = {}
        for evaluation in evaluations:
            identity = build_identity(evaluation)
            key = (identity.decision_type, identity.identity_key)
            fingerprint = evaluation.calculation_fingerprint
            seen = fingerprints_by_key.setdefault(key, set())
            if seen and fingerprint not in seen:
                raise DecisionError(
                    _CONFLICT,
                    "two evaluations of the same Decision identity disagree in this run",
                    details={"decision_identity_key": identity.identity_key},
                )
            seen.add(fingerprint)
            kept_by_key.setdefault(key, _Kept(identity, evaluation))

        kept = list(kept_by_key.values())
        duplicate_input_count = len(evaluations) - len(kept)
        return kept, duplicate_input_count

    @staticmethod
    def _tally(kept: list[_Kept]) -> dict[SourceStatus, int]:
        counts = dict.fromkeys(SourceStatus, 0)
        for item in kept:
            counts[item.evaluation.status] += 1
        return counts

    @staticmethod
    def _validate_against_ranking(
        kept: list[_Kept], counts: dict[SourceStatus, int], ranking_result: PriorityRankingResult
    ) -> None:
        if counts[SourceStatus.TRIGGERED] != ranking_result.candidate_count:
            raise DecisionError(
                _INPUT_MISMATCH,
                "the ranking's candidate_count does not match the TRIGGERED evaluations given",
            )
        expected = {
            SourceStatus.CLEAR: ranking_result.excluded_clear_count,
            SourceStatus.INSUFFICIENT_DATA: ranking_result.excluded_insufficient_count,
            SourceStatus.NOT_APPLICABLE: ranking_result.excluded_not_applicable_count,
            SourceStatus.SUPPRESSED_LOW_CONFIDENCE: ranking_result.excluded_suppressed_count,
        }
        for status, field in _STATUS_FIELD.items():
            if counts[status] != expected[status]:
                raise DecisionError(
                    _INPUT_MISMATCH,
                    f"the ranking's {field} does not match the evaluations given",
                )

    @staticmethod
    def _candidates_by_fingerprint(
        kept: list[_Kept], ranking_result: PriorityRankingResult
    ) -> dict[str, RankedPriorityCandidate]:
        by_fingerprint = {
            ranked.candidate.source_evaluation_fingerprint: ranked
            for ranked in ranking_result.ranked_candidates
        }
        triggered_fingerprints = {
            item.evaluation.calculation_fingerprint
            for item in kept
            if item.evaluation.status == SourceStatus.TRIGGERED
        }
        for fingerprint in triggered_fingerprints:
            if fingerprint not in by_fingerprint:
                raise DecisionError(
                    _INPUT_MISMATCH,
                    "a TRIGGERED evaluation has no matching PriorityCandidate in this ranking",
                )
        for fingerprint in by_fingerprint:
            if fingerprint not in triggered_fingerprints:
                raise DecisionError(
                    _INPUT_MISMATCH,
                    "a PriorityCandidate has no matching TRIGGERED evaluation in this run",
                )
        return by_fingerprint

    # --- observation building ------------------------------------------------------------------

    @staticmethod
    def _observation_row(
        *,
        decision: Decision,
        run_id: UUID,
        context: PriorityContext,
        identity: DecisionIdentity,
        evaluation: SourceEvaluation,
        transition: LifecycleTransition,
        input_fingerprint: str,
        candidate: RankedPriorityCandidate | None,
    ) -> dict[str, object]:
        facts_payload, evidence_payload = serialize_facts(evaluation)
        reason_codes = reason_codes_of(evaluation)
        target_key = raw_target_key(evaluation)

        if evaluation.status == SourceStatus.TRIGGERED:
            if (
                candidate is None
            ):  # pragma: no cover - already validated in _candidates_by_fingerprint
                raise DecisionError(
                    _INPUT_MISMATCH, "a TRIGGERED evaluation is missing its candidate"
                )
            priority_rank = candidate.rank
            priority_candidate_fingerprint = candidate.candidate.calculation_fingerprint
            impact_score = candidate.candidate.impact_score_exact
            urgency_score = candidate.candidate.urgency_score
            confidence_score = candidate.candidate.confidence_score
            actionability_score = candidate.candidate.actionability_score
            priority_score = candidate.candidate.priority_score_exact
        else:
            priority_rank = None
            priority_candidate_fingerprint = None
            impact_score = None
            urgency_score = None
            confidence_score = evaluation.confidence_score
            actionability_score = None
            priority_score = None

        fingerprint = observation_fingerprint(
            decision_identity_key=identity.identity_key,
            run_input_fingerprint=input_fingerprint,
            as_of_local_date=context.as_of_local_date,
            source_status=evaluation.status,
            lifecycle_transition=transition,
            source_evaluation_fingerprint=evaluation.calculation_fingerprint,
            source_target_key=target_key,
            priority_candidate_fingerprint=priority_candidate_fingerprint,
            priority_rank=priority_rank,
            impact_score=impact_score,
            urgency_score=urgency_score,
            confidence_score=confidence_score,
            actionability_score=actionability_score,
            priority_score=priority_score,
            source_reason_codes=reason_codes,
            facts_payload=facts_payload,
            evidence_payload=evidence_payload,
        )

        return {
            "decision_id": decision.id,
            "decision_run_id": run_id,
            "property_id": context.property_id,
            "as_of_local_date": context.as_of_local_date,
            "source_status": evaluation.status,
            "lifecycle_transition": transition,
            "source_evaluation_fingerprint": evaluation.calculation_fingerprint,
            "source_target_key": target_key,
            "priority_candidate_fingerprint": priority_candidate_fingerprint,
            "priority_rank": priority_rank,
            "impact_score": impact_score,
            "urgency_score": urgency_score,
            "confidence_score": confidence_score,
            "actionability_score": actionability_score,
            "priority_score": priority_score,
            "source_reason_codes": list(reason_codes),
            "facts_payload": facts_payload,
            "evidence_payload": evidence_payload,
            "memory_version": DECISION_MEMORY_VERSION,
            "observation_fingerprint": fingerprint,
        }

    # --- small reads used by sync() itself ------------------------------------------------------

    def _count_open(self, property_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Decision)
            .where(
                Decision.workspace_id == self._tenant.workspace_id,
                Decision.property_id == property_id,
                Decision.status == DecisionStatus.OPEN,
            )
        )
        return int(self._session.scalar(stmt) or 0)


__all__ = ["DecisionService"]

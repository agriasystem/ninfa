"""The deterministic fingerprint of an evaluation, and the one place that builds it.

    SHA-256( canonical JSON of the logical input and result of the evaluation )

It covers the decision type, the rules and pattern versions, the target snapshot and baseline, the
input metrics, the historical pairs used (their snapshot ids and rooms), the thresholds, the
confidence, the reason codes, the reference ADR / proxy and the status. It never covers a
timestamp, a memory address, a row order, a log line or anything else that is not the calculation:
the same input gives the same fingerprint, on any machine, on any run.

Decimals are serialised by `precision.canonical_text`: normalised and NON-LOSSY (no digit is
dropped), never a float and never a two-decimal display value. Two inputs on opposite sides of
a threshold therefore never share a fingerprint, while the same logical input always does.
"""

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from app.modules.intelligence.revenue.impact import ReferenceAdr
from app.modules.intelligence.revenue.precision import canonical_text
from app.modules.intelligence.revenue.types import (
    PATTERN_VERSION,
    RULES_VERSION,
    EvaluationStatus,
    OccupancyFacts,
    PickupFacts,
    ReasonCode,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
    TargetContext,
)

_FINGERPRINT_FORMAT = 1


def calculation_fingerprint(
    *,
    decision_type: RevenueDecisionType,
    status: EvaluationStatus,
    target: TargetContext,
    confidence_score: Decimal,
    reason_codes: tuple[ReasonCode, ...],
    facts: PickupFacts | OccupancyFacts,
    evidence_snapshot_ids: tuple[UUID, ...],
    reference: ReferenceAdr,
    revenue_gap_proxy: Decimal | None,
) -> str:
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "decision_type": decision_type.value,
        "rules_version": RULES_VERSION,
        "pattern_version": PATTERN_VERSION,
        "target_snapshot_id": str(target.target_snapshot_id),
        "target_baseline_id": None if target.baseline_id is None else str(target.baseline_id),
        "snapshot_local_date": target.snapshot_local_date.isoformat(),
        "stay_date": target.stay_date.isoformat(),
        "lead_time_days": target.lead_time_days,
        "status": status.value,
        "confidence_score": canonical_text(confidence_score),
        "reason_codes": [code.value for code in reason_codes],
        "facts": facts.canonical_payload(),
        "evidence_snapshot_ids": [str(snapshot_id) for snapshot_id in evidence_snapshot_ids],
        "reference_adr": canonical_text(reference.value),
        "reference_adr_source": reference.source.value,
        "revenue_gap_proxy": canonical_text(revenue_gap_proxy),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def build_evaluation(
    *,
    decision_type: RevenueDecisionType,
    status: EvaluationStatus,
    target: TargetContext,
    confidence_score: Decimal,
    reason_codes: tuple[ReasonCode, ...],
    facts: PickupFacts | OccupancyFacts,
    evidence_snapshot_ids: tuple[UUID, ...],
    reference: ReferenceAdr,
    revenue_gap_proxy: Decimal | None,
) -> RevenueDecisionEvaluation:
    """Seal an evaluation: attach the fingerprint of everything it says."""
    return RevenueDecisionEvaluation(
        decision_type=decision_type,
        status=status,
        workspace_id=target.workspace_id,
        property_id=target.property_id,
        data_source_id=target.data_source_id,
        target_snapshot_id=target.target_snapshot_id,
        target_baseline_id=target.baseline_id,
        snapshot_local_date=target.snapshot_local_date,
        stay_date=target.stay_date,
        lead_time_days=target.lead_time_days,
        confidence_score=confidence_score,
        rules_version=RULES_VERSION,
        calculation_fingerprint=calculation_fingerprint(
            decision_type=decision_type,
            status=status,
            target=target,
            confidence_score=confidence_score,
            reason_codes=reason_codes,
            facts=facts,
            evidence_snapshot_ids=evidence_snapshot_ids,
            reference=reference,
            revenue_gap_proxy=revenue_gap_proxy,
        ),
        reason_codes=reason_codes,
        facts=facts,
        evidence_snapshot_ids=evidence_snapshot_ids,
        revenue_gap_proxy=revenue_gap_proxy,
        reference_adr=reference.value,
        reference_adr_source=reference.source,
    )

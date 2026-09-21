"""The deterministic fingerprint of a period metric and of an evaluation.

    SHA-256( canonical JSON of the logical input and result )

A metric fingerprint covers the target dimensions, the policies (invoice-date attribution and the
lead-time-0 proxy), every exact cost and occupancy figure, the counts, the status and the reasons.
An evaluation fingerprint covers the rules / metric / expected-method versions, the target
dimensions, the target metric, the historical comparable months (their exact CPORs and quality),
the statistics, the conditions, the quality and confidence scores, the thresholds, the status and
the reason codes. It never covers a display-only figure, a timestamp, a query order that is not
part of the calculation, a memory address or a log line: the same logical input gives the same
fingerprint on any machine, on any run.

Decimals are serialised by `precision.canonical_text`: normalised and NON-LOSSY (no digit is
dropped), never a float and never a two-decimal display value. Two inputs on opposite sides of a
threshold therefore never share a fingerprint, while `10.00` and `10` always do.
"""

import hashlib
import json
from dataclasses import replace
from typing import Any

from app.modules.intelligence.costs.types import CostDecisionEvaluation, CostPeriodMetric

_FINGERPRINT_FORMAT = 1


def _digest(kind: str, body: dict[str, Any]) -> str:
    payload = {"v": _FINGERPRINT_FORMAT, "kind": kind, **body}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def metric_fingerprint(metric: CostPeriodMetric) -> str:
    return _digest("cost-period-metric", metric.canonical_payload())


def evaluation_fingerprint(evaluation: CostDecisionEvaluation) -> str:
    return _digest("cost-cpor-anomaly", evaluation.canonical_payload())


def seal(evaluation: CostDecisionEvaluation) -> CostDecisionEvaluation:
    """Attach the fingerprint of everything the evaluation says."""
    return replace(evaluation, calculation_fingerprint=evaluation_fingerprint(evaluation))

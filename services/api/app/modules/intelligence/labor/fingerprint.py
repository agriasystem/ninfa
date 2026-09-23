"""The deterministic fingerprint of a LABOR_OVERSTAFFING evaluation.

    SHA-256( canonical JSON of the logical input and result )

Covers the rules/expected-method versions, the target dimensions, the target booking/labor
snapshots, the demand forecast facts, the scheduled hours, the classification quality, the
comparable days, the historical hours, the statistics, the confidence, the thresholds, the status,
the reason codes and the cost proxy inputs. It never covers a display-only figure, a timestamp, a
query order that is not part of the calculation, or a memory address: the same logical input gives
the same fingerprint on any machine, on any run.

Decimals are serialised by `precision.canonical_text`: normalised and NON-LOSSY, never a float and
never a two-decimal display value.
"""

import hashlib
import json
from dataclasses import replace

from app.modules.intelligence.labor.types import LaborDecisionEvaluation

_FINGERPRINT_FORMAT = 1


def evaluation_fingerprint(evaluation: LaborDecisionEvaluation) -> str:
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "kind": "labor-overstaffing",
        **evaluation.canonical_payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def seal(evaluation: LaborDecisionEvaluation) -> LaborDecisionEvaluation:
    """Attach the fingerprint of everything the evaluation says."""
    return replace(evaluation, calculation_fingerprint=evaluation_fingerprint(evaluation))

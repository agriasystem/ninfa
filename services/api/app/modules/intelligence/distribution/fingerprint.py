"""The deterministic fingerprint of a REV_OTA_DEPENDENCY evaluation.

    SHA-256( canonical JSON of the logical input and result )

Covers the rules/metric/expected versions, the target dimensions, the 30-day window, the channel
mix, the classification coverage, the snapshot provenance, the historical periods actually used,
their OTA shares and provenance, the statistics, the confidence, the thresholds, the conditions,
the status and the reason codes. It never covers a display-only figure, a timestamp, a query
order that is not part of the calculation, or a memory address: the same logical input gives the
same fingerprint on any machine, on any run.

Decimals are serialised by `precision.canonical_text`: normalised and NON-LOSSY, never a float and
never a two-decimal display value.
"""

import hashlib
import json
from dataclasses import replace

from app.modules.intelligence.distribution.types import OtaDependencyEvaluation

_FINGERPRINT_FORMAT = 1


def evaluation_fingerprint(evaluation: OtaDependencyEvaluation) -> str:
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "kind": "ota-dependency",
        **evaluation.canonical_payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def seal(evaluation: OtaDependencyEvaluation) -> OtaDependencyEvaluation:
    """Attach the fingerprint of everything the evaluation says."""
    return replace(evaluation, calculation_fingerprint=evaluation_fingerprint(evaluation))

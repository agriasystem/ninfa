"""From a finished run to numbers: scores every case against the truth (read back from JSON) and
aggregates per kind of data and in total."""

import json
from dataclasses import asdict
from typing import Any

from tests.benchmarks.smart_import_v3.corpus import DOMAIN_NAMES, manifest, summary
from tests.benchmarks.smart_import_v3.metrics import TARGETS, aggregate
from tests.benchmarks.smart_import_v3.model import golden_from_json
from tests.benchmarks.smart_import_v3.runner import Run
from tests.benchmarks.smart_import_v3.score import CaseResult, score_case

BASELINE = "48a1a656edc98b15665153c0d7322411f1a46988"


def evaluate(run: Run) -> dict[str, Any]:
    entries = json.loads(json.dumps(manifest(run.docs)))  # the scorer only ever sees plain JSON
    results: list[CaseResult] = []
    for entry in entries:
        golden = golden_from_json(entry["golden"])
        doc_id = entry["id"]
        result = score_case(entry, golden, run.first[doc_id], run.dialogs.get(doc_id))
        results.append(result)

    wrong_card = {
        doc_id: {
            "automatic": observed.automatic,
            "domain_question": "DOMAIN" in observed.question_kinds,
            "level": observed.level,
        }
        for doc_id, observed in run.wrong_card.items()
    }
    egress: dict[str, Any] = {}
    truth = {e["id"]: golden_from_json(e["golden"]) for e in entries}
    for doc_id, probe in run.egress.items():
        values = [v.casefold() for v in truth[doc_id].pii_values]
        leaks = sum(1 for text in probe.evidence for v in values if v in text.casefold())
        egress[doc_id] = {"calls": probe.calls, "leaks": leaks}
    sizes = {e["id"]: e["bytes"] for e in entries}
    for result in results:
        known = egress.get(result.id)
        if known is not None:
            result.egress_calls = known["calls"]
            result.egress_leaks = known["leaks"]

    def group(selected: list[CaseResult]) -> dict[str, Any]:
        return aggregate(selected, run.timings_ms, run.peaks_kib, wrong_card, egress, sizes)

    metrics = {"total": group(results)}
    for card, name in DOMAIN_NAMES.items():
        metrics[name] = group([r for r in results if r.card == card])
    return {
        "benchmark": "smart-import-v3-intelligence-benchmark-v1",
        "baseline_main": BASELINE,
        "assistant": "IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called",
        "corpus": summary(run.docs),
        "targets": {k: {"op": op, "value": value} for k, (op, value) in TARGETS.items()},
        "metrics": metrics,
        "cases": [asdict(r) for r in results],
    }

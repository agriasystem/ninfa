"""From a finished run to the numbers of the Universal Understanding Benchmark V2.

The official scorer (`smart_import_v3.score`) judges every case; this module only groups the
verdicts the way V2 asks for them:

  * per kind of data and per difficulty, on the POSITIVE documents only (a refusal cannot hide a
    wrong mapping and a wrong mapping cannot hide a refusal);
  * the negatives and the unsupported files apart: for them only one question matters - did Smart
    Import stay out of the way (no automatic import, no exception);
  * accuracy figures in a STRICT form too: a document the engine could not read at all counts as a
    miss (the official figure only counts documents it answered about).
"""

import json
from collections import Counter
from dataclasses import asdict
from typing import Any

from tests.benchmarks.smart_import_v3.metrics import aggregate, ratio
from tests.benchmarks.smart_import_v3.model import CRITICAL_FIELDS, Golden, golden_from_json
from tests.benchmarks.smart_import_v3.observe import Observed
from tests.benchmarks.smart_import_v3.runner import Run
from tests.benchmarks.smart_import_v3.score import (
    CaseResult,
    _claims,
    _matches,
    _under_question,
    score_case,
)
from tests.benchmarks.universal_understanding_v2.corpus import (
    DOMAIN_NAMES,
    DOMAINS,
    manifest,
    summary,
)
from tests.benchmarks.universal_understanding_v2.stages import StageTimes, summarise

BENCHMARK = "universal-understanding-benchmark-v2"
DIFFICULTIES = ("EASY", "MEDIUM", "HARD", "ADVERSARIAL")

# What a refusal of an unreadable file looks like: nothing raised, nothing offered as automatic,
# and either a stated problem or a level that says "a person must look" (MANUAL / BLOCKED).
SAFE_LEVELS = {None, "MANUAL", "BLOCKED"}


def _difficulty(tags: list[str]) -> str | None:
    return next((t.upper() for t in tags if t.upper() in DIFFICULTIES), None)


def unsupported_case(entry: dict[str, Any], observed: Observed) -> dict[str, Any]:
    clean = (
        observed.error is None
        and not observed.automatic
        and observed.level in SAFE_LEVELS
        and not observed.claims
    )
    return {
        "id": entry["id"],
        "filename": entry["filename"],
        "clean": clean,
        "level": observed.level,
        "problem": observed.problem,
        "error": observed.error,
        "blockers": observed.blocker_codes,
        "claims": len(observed.claims),
    }


def _critical_wrong(results: list[CaseResult]) -> int:
    """Wrong readings of a fact a business decision rests on (wrong column, guessed, invented,
    taken from a column that must stay out)."""
    return sum(
        1
        for r in results
        for f in r.findings
        if f.category == "FIELD_WRONG" and f.field in CRITICAL_FIELDS.get(r.golden_domain, ())
    )


def committed_wrong(first: Observed, golden: Golden) -> int:
    """Certain readings (HIGH, no question on their column) of a fact a business decision rests
    on that the truth does not confirm, in the FIRST answer - what a person is shown before
    answering anything. (The official counters also look at the state AFTER the person's answers,
    where a column the person has just been asked about is certain by then.)"""
    critical = set(CRITICAL_FIELDS.get(golden.domain, ()))
    wrong = 0
    for name, claims in _claims(first).items():
        if name not in critical:
            continue
        source = golden.fields.get(name)
        for claim in claims:
            if claim.level != "HIGH" or _under_question(claim, first):
                continue
            if source is None or not _matches(source, claim, first):
                wrong += 1
    return wrong


def extras(
    results: list[CaseResult], truth: dict[str, Golden], first_wrong: dict[str, int]
) -> dict[str, Any]:
    """The figures V2 adds to the official aggregate, for one group of POSITIVE documents."""
    n = len(results)
    # (a document whose records are deliberately not read has no kind of data to find)
    with_domain = [r for r in results if truth[r.id].data_rows != 0]
    with_header = [r for r in results if truth[r.id].header_rows]
    with_table = [r for r in results if truth[r.id].first_row is not None and truth[r.id].data_rows]
    required = sum(r.required.claims for r in results)
    required_ok = sum(r.required.claims_correct for r in results)
    everything = sum(r.everything.claims for r in results)
    everything_ok = sum(r.everything.claims_correct for r in results)
    committed = sum(r.required.committed for r in results)
    committed_ok = sum(r.required.committed_correct for r in results)
    golden_all = sum(r.everything.golden for r in results)
    golden_required = sum(r.required.golden for r in results)
    return {
        "documents": n,
        # an unreadable document counts as a miss here (the official figure skips it)
        "domain_accuracy_strict": ratio(
            sum(1 for r in with_domain if r.domain_ok), len(with_domain)
        ),
        "header_accuracy_strict": ratio(
            sum(1 for r in with_header if r.header_scored and r.header_ok), len(with_header)
        ),
        "table_accuracy_strict": ratio(
            sum(1 for r in with_table if r.boundary_scored and r.boundary_ok), len(with_table)
        ),
        "required_recall_strict": ratio(sum(r.required.correct for r in results), golden_required),
        "optional_precision": ratio(everything_ok - required_ok, everything - required),
        "optional_recall": ratio(
            sum(r.everything.correct for r in results) - sum(r.required.correct for r in results),
            golden_all - golden_required,
        ),
        "critical_wrong_mapping": _critical_wrong(results),
        "required_committed_wrong": sum(first_wrong[r.id] for r in results),
        "required_committed_wrong_final_state": committed - committed_ok,
        "ready_documents": sum(1 for r in results if r.outcome == "READY"),
        "ready_automatic": sum(1 for r in results if r.outcome == "READY" and r.automatic),
        "cases_with_p0": sum(1 for r in results if any(f.severity == "P0" for f in r.findings)),
        "cases_with_p1": sum(1 for r in results if any(f.severity == "P1" for f in r.findings)),
        "cases_clean": sum(1 for r in results if not r.findings),
    }


def evaluate(run: Run, stages: dict[str, StageTimes] | None = None) -> dict[str, Any]:
    entries = json.loads(json.dumps(manifest(run.docs)))  # the scorer only ever sees plain JSON
    truth: dict[str, Golden] = {e["id"]: golden_from_json(e["golden"]) for e in entries}
    results: list[CaseResult] = []
    unsupported: list[dict[str, Any]] = []
    for entry in entries:
        doc_id = entry["id"]
        if "unsupported" in entry["tags"]:
            unsupported.append(unsupported_case(entry, run.first[doc_id]))
            continue
        results.append(score_case(entry, truth[doc_id], run.first[doc_id], run.dialogs.get(doc_id)))

    wrong_card = {
        doc_id: {
            "automatic": observed.automatic,
            "domain_question": "DOMAIN" in observed.question_kinds,
            "level": observed.level,
        }
        for doc_id, observed in run.wrong_card.items()
    }
    egress: dict[str, Any] = {}
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

    tags = {e["id"]: e["tags"] for e in entries}
    positives = [r for r in results if "negative" not in tags[r.id]]
    negatives = [r for r in results if "negative" in tags[r.id]]
    selections: dict[str, list[CaseResult]] = {
        "positives": positives,
        "negatives": negatives,
        "total": results,
    }
    for card in DOMAINS:
        selections[DOMAIN_NAMES[card]] = [r for r in positives if r.card == card]
    for difficulty in DIFFICULTIES:
        selections[difficulty] = [r for r in positives if _difficulty(tags[r.id]) == difficulty]

    metrics = {name: group(selected) for name, selected in selections.items()}
    committed = {
        r.id: committed_wrong(run.first[r.id], truth[r.id]) for r in results if r.error is None
    }
    committed.update({r.id: 0 for r in results if r.error is not None})
    detail = {
        name: extras(selected, truth, committed)
        for name, selected in selections.items()
        if name not in {"negatives", "total"}
    }
    clean_unsupported = sum(1 for u in unsupported if u["clean"])
    data: dict[str, Any] = {
        "benchmark": BENCHMARK,
        "assistant": "IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called",
        "corpus": summary(run.docs),
        "metrics": metrics,
        "v2": detail,
        "unsupported": {
            "documents": len(unsupported),
            "clean": ratio(clean_unsupported, len(unsupported)),
            "cases": unsupported,
        },
        "stages": summarise(stages) if stages else {},
        "cases": [asdict(r) for r in results],
    }
    data["targets"] = targets(data)
    data["findings_by_recipe"] = by_recipe(results, tags)
    return data


def by_recipe(results: list[CaseResult], tags: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    """Per recipe: documents and documents with a finding of P0/P1/P2 - where the work is."""
    out: dict[str, Counter[str]] = {}
    for r in results:
        recipe = next((t.split(":", 1)[1] for t in tags[r.id] if t.startswith("recipe:")), "?")
        bucket = out.setdefault(recipe, Counter())
        bucket["documents"] += 1
        if r.findings:
            bucket["with_findings"] += 1
        for severity in ("P0", "P1", "P2"):
            if any(f.severity == severity for f in r.findings):
                bucket[severity] += 1
    return {name: dict(counter) for name, counter in sorted(out.items())}


def _value(ratio_dict: dict[str, Any]) -> float | None:
    value = ratio_dict.get("value")
    return None if value is None else float(value)


def targets(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The V2 acceptance targets and where the run stands against them."""
    total = data["metrics"]["total"]
    positives = data["metrics"]["positives"]
    negatives = data["metrics"]["negatives"]
    v2 = data["v2"]["positives"]
    fallback_den = negatives["safe_fallback"]["den"] + data["unsupported"]["documents"]
    fallback_num = negatives["safe_fallback"]["num"] + data["unsupported"]["clean"]["num"]
    pii = (
        total["pii_value_leaks"]
        + total["egress_probe"]["pii_leaks"]
        + (total["pii_exclusion"]["den"] - total["pii_exclusion"]["num"])
    )
    rows: list[tuple[str, str, float, float | None]] = [
        ("false automation", "==", 0, total["false_automation_count"]),
        ("P0 findings", "==", 0, total["findings_by_severity"]["P0"]),
        # (a wrong reading that is only a LOW guess the person is asked about is a question, not a
        # mapping: `critical_wrong_mapping` counts those too and is reported beside it)
        ("critical wrong mapping (committed)", "==", 0, v2["required_committed_wrong"]),
        (
            "necessary-question recall",
            ">=",
            1.0,
            _value(positives["necessary_question_recall"]),
        ),
        ("safe fallback (negatives + unsupported)", ">=", 1.0, _ratio(fallback_num, fallback_den)),
        ("personal data leaked / not excluded", "==", 0, pii),
        ("domain accuracy (strict)", ">=", 0.99, _value(v2["domain_accuracy_strict"])),
        ("header accuracy (strict)", ">=", 0.99, _value(v2["header_accuracy_strict"])),
        ("table accuracy (strict)", ">=", 0.99, _value(v2["table_accuracy_strict"])),
        ("required precision", ">=", 0.995, _value(positives["required_precision"])),
        (
            "required precision, committed claims",
            ">=",
            0.995,
            _value(positives["required_precision_committed"]),
        ),
        ("required recall", ">=", 0.99, _value(v2["required_recall_strict"])),
    ]
    out = []
    for name, op, wanted, actual in rows:
        ok = actual is not None and (actual == wanted if op == "==" else actual >= wanted)
        out.append({"name": name, "op": op, "target": wanted, "actual": actual, "ok": ok})
    return out


def _ratio(num: int | float, den: int | float) -> float | None:
    return (num / den) if den else None

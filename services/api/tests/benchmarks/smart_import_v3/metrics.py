"""The numbers: per kind of data and in total, never one hiding the other."""

import statistics
from collections import Counter
from collections.abc import Sequence
from typing import Any

from tests.benchmarks.smart_import_v3.score import CATEGORIES, CaseResult

# Targets the benchmark was asked to compare against (not enforced anywhere).
TARGETS: dict[str, tuple[str, float]] = {
    "false_automation_rate": ("<=", 0.0),
    "zero_question_correctness": (">=", 1.0),
    "pii_exclusion": (">=", 1.0),
    "domain_accuracy": (">=", 0.98),
    "header_accuracy": (">=", 0.98),
    "required_precision": (">=", 0.99),
    "required_recall": (">=", 0.95),
    "safe_fallback": (">=", 1.0),
}


def ratio(num: int | float, den: int | float) -> dict[str, Any]:
    return {"num": num, "den": den, "value": (num / den) if den else None}


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def performance(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": statistics.fmean(values),
        "p50": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
    }


def aggregate(
    results: Sequence[CaseResult],
    timings: dict[str, float],
    peaks: dict[str, float],
    wrong_card: dict[str, Any],
    egress: dict[str, Any],
    sizes: dict[str, int],
) -> dict[str, Any]:
    n = len(results)
    ids = {r.id for r in results}
    scored = [r for r in results if r.error is None]
    automatic = [r for r in results if r.automatic]
    false_automation = [r for r in results if r.false_automation or _unsafe(r)]
    refusals = [r for r in results if r.outcome in {"REJECT", "NOT_AUTOMATIC", "WARN"}]
    hard_refusals = [r for r in results if r.outcome == "REJECT"]

    def total(attribute: str, field: str) -> int:
        return sum(getattr(getattr(r, attribute), field) for r in results)

    req_golden = total("required", "golden")
    conversations = [r for r in results if r.conversation]
    expected_questions = sum(len(r.questions_expected) for r in results)
    found_questions = sum(r.questions_necessary_found for r in results)
    asked_instances = sum(len(r.questions_asked) for r in results)
    unnecessary = sum(r.questions_unnecessary for r in results)
    findings = Counter(f.category for r in results for f in r.findings)
    cases_by_category = Counter(c for r in results for c in {f.category for f in r.findings})
    severities = Counter(f.severity for r in results for f in r.findings)
    worst = Counter(_worst(r) for r in results if r.findings)
    pii_columns = sum(r.pii_columns for r in results)
    pii_excluded = sum(r.pii_columns_excluded for r in results)

    egress_leaks = 0
    egress_calls = 0
    egress_docs = 0
    for doc_id, probe in egress.items():
        if doc_id not in ids:
            continue
        egress_calls += probe["calls"]
        egress_docs += 1 if probe["calls"] else 0
        egress_leaks += probe["leaks"]

    wc = [(doc_id, probe) for doc_id, probe in wrong_card.items() if doc_id in ids]
    metrics: dict[str, Any] = {
        "documents": n,
        "errors": sum(1 for r in results if r.error is not None),
        "domain_accuracy": ratio(
            sum(1 for r in results if r.domain_scored and r.domain_ok),
            sum(1 for r in results if r.domain_scored),
        ),
        "sheet_accuracy": ratio(
            sum(1 for r in results if r.sheet_scored and r.sheet_ok),
            sum(1 for r in results if r.sheet_scored),
        ),
        "header_accuracy": ratio(
            sum(1 for r in results if r.header_scored and r.header_ok),
            sum(1 for r in results if r.header_scored),
        ),
        "table_boundary_accuracy": ratio(
            sum(1 for r in results if r.boundary_scored and r.boundary_ok),
            sum(1 for r in results if r.boundary_scored),
        ),
        "required_precision": ratio(
            total("required", "claims_correct"), total("required", "claims")
        ),
        "required_precision_committed": ratio(
            total("required", "committed_correct"), total("required", "committed")
        ),
        "required_recall": ratio(total("required", "correct"), req_golden),
        "required_recall_incl_asked": ratio(
            total("required", "correct") + total("required", "asked"), req_golden
        ),
        "all_fields_precision": ratio(
            total("everything", "claims_correct"), total("everything", "claims")
        ),
        "all_fields_recall": ratio(total("everything", "correct"), total("everything", "golden")),
        "required_facts": {
            "expected": req_golden,
            "correct": total("required", "correct"),
            "wrong": total("required", "wrong"),
            "missed": total("required", "missed"),
            "asked": total("required", "asked"),
        },
        "pii_exclusion": ratio(pii_excluded, pii_columns),
        "pii_value_leaks": sum(r.pii_values_leaked for r in results),
        "pii_cases_with_leak": sum(1 for r in results if r.pii_values_leaked),
        "pii_values_checked": sum(r.pii_values for r in results),
        "junk_columns_mapped": sum(r.junk_mapped for r in results),
        "zero_question_coverage": ratio(len(automatic), n),
        "zero_question_correctness": ratio(
            sum(1 for r in automatic if r.fully_correct), len(automatic)
        ),
        "false_automation_count": len(false_automation),
        "false_automation_rate": ratio(len(false_automation), n),
        "false_automation_rate_of_automatic": ratio(len(false_automation), len(automatic)),
        "necessary_question_recall": ratio(found_questions, expected_questions),
        "questions_asked": asked_instances,
        "questions_unnecessary": unnecessary,
        "unnecessary_question_rate": ratio(unnecessary, asked_instances),
        "documents_with_unnecessary_question": sum(1 for r in results if r.questions_unnecessary),
        "department_words_asked_needlessly": sum(r.labels_asked_needlessly for r in results),
        "department_words_guessed_silently": sum(r.labels_guessed_silently for r in results),
        "department_words_wrong": sum(r.labels_wrong for r in results),
        "safe_fallback": ratio(sum(1 for r in refusals if r.safe_fallback), len(refusals)),
        "safe_fallback_strict": ratio(
            sum(1 for r in hard_refusals if r.strict_fallback), len(hard_refusals)
        ),
        "conversation_resolved": ratio(
            sum(1 for r in conversations if r.resolved), len(conversations)
        ),
        "conversation_correct": ratio(
            sum(1 for r in conversations if r.resolved_correct), len(conversations)
        ),
        "conversation_rounds_mean": (
            statistics.fmean(r.rounds for r in conversations) if conversations else 0.0
        ),
        "automatic_with_warning": sum(1 for r in results if r.warned),
        "wrong_card_probe": {
            "documents": len(wc),
            "automatic": sum(1 for _, o in wc if o["automatic"]),
            "asked_domain": sum(1 for _, o in wc if o["domain_question"]),
            "not_ready": sum(1 for _, o in wc if o["level"] != "READY"),
        },
        "egress_probe": {
            "documents": egress_docs,
            "calls": egress_calls,
            "pii_leaks": egress_leaks,
        },
        "findings_by_category": {c: findings.get(c, 0) for c in CATEGORIES},
        "cases_by_category": {c: cases_by_category.get(c, 0) for c in CATEGORIES},
        "findings_by_severity": {s: severities.get(s, 0) for s in ("P0", "P1", "P2", "P3")},
        "cases_by_worst_severity": {s: worst.get(s, 0) for s in ("P0", "P1", "P2", "P3")},
        "cases_clean": sum(1 for r in results if not r.findings),
        "levels": dict(Counter(r.level or "NONE" for r in results)),
        "performance_ms": performance([timings[r.id] for r in scored if r.id in timings]),
        "memory_kib": performance([peaks[r.id] for r in scored if r.id in peaks]),
        "bytes": performance([float(sizes[r.id]) for r in results if r.id in sizes]),
    }
    return metrics


def _unsafe(result: CaseResult) -> bool:
    """A refusal case that was offered as automatic is a false automation too: whatever the
    reading was, the document is not one to import without a person."""
    return result.automatic and result.outcome in {"REJECT", "NOT_AUTOMATIC", "ASK"}


def _worst(result: CaseResult) -> str:
    order = ("P0", "P1", "P2", "P3")
    return min((f.severity for f in result.findings), key=order.index)

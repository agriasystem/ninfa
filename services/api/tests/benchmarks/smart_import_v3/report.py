"""The console summary and the Markdown report.

Everything in the report is computed (`driver.evaluate`); the only hand-written part is the
interpretation (`interpretation.md`, next to this file), which is read as it is.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

INTERPRETATION = Path(__file__).with_name("interpretation.md")
DOMAIN_ORDER = ("Personale", "Prenotazioni", "Costi")
SEVERITY_ORDER = ("P0", "P1", "P2", "P3")
COMMAND = "python -m tests.benchmarks.smart_import_v3"


def pct(metric: dict[str, Any], digits: int = 1) -> str:
    value = metric["value"]
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}% ({metric['num']}/{metric['den']})"


def _short(metric: dict[str, Any]) -> str:
    value = metric["value"]
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _meets(metric: dict[str, Any], op: str, target: float) -> str:
    value = metric["value"]
    if value is None:
        return "n/a"
    ok = value >= target - 1e-12 if op == ">=" else value <= target + 1e-12
    return "met" if ok else "**missed**"


# --- console --------------------------------------------------------------------------------------


def console_summary(data: dict[str, Any]) -> str:
    lines = [f"Smart Import V3 benchmark - {data['corpus']['documents']} documents"]
    for name, m in data["metrics"].items():
        lines.append(f"\n== {name} ({m['documents']} documents)")
        for key in (
            "domain_accuracy",
            "sheet_accuracy",
            "header_accuracy",
            "table_boundary_accuracy",
            "required_precision",
            "required_precision_committed",
            "required_recall",
            "pii_exclusion",
            "zero_question_coverage",
            "zero_question_correctness",
            "false_automation_rate",
            "necessary_question_recall",
            "unnecessary_question_rate",
            "safe_fallback",
            "conversation_resolved",
            "conversation_correct",
        ):
            lines.append(f"  {key:32s} {pct(m[key])}")
        lines.append(f"  false automation cases          {m['false_automation_count']}")
        lines.append(f"  pii value leaks                 {m['pii_value_leaks']}")
        lines.append(f"  cases by worst severity         {m['cases_by_worst_severity']}")
        lines.append(f"  levels                          {m['levels']}")
        p = m["performance_ms"]
        lines.append(
            f"  ms/file mean {p['mean']:.0f} p50 {p['p50']:.0f} p95 {p['p95']:.0f} max "
            f"{p['max']:.0f}"
        )
    fa = [c for c in data["cases"] if c["false_automation"]]
    lines.append(f"\nFALSE AUTOMATION: {len(fa)} documents")
    for c in fa:
        lines.append(f"  {c['id']}: {'; '.join(c['false_automation_reasons'])}")
    return "\n".join(lines)


# --- markdown -------------------------------------------------------------------------------------


def _headline(data: dict[str, Any]) -> str:
    targets = data["targets"]
    rows = []
    labels = [
        ("false_automation_rate", "False automation rate"),
        ("zero_question_correctness", "Zero-question correctness"),
        ("pii_exclusion", "Personal columns left out"),
        ("domain_accuracy", "Domain accuracy"),
        ("header_accuracy", "Header accuracy"),
        ("required_precision", "Required-field precision"),
        ("required_recall", "Required-field recall"),
        ("safe_fallback", "Safe fallback (documents to refuse)"),
    ]
    for key, label in labels:
        op, value = targets[key]["op"], targets[key]["value"]
        row = [label, f"{op} {value * 100:.0f}%"]
        for name in ("total", *DOMAIN_ORDER):
            metric = data["metrics"][name][key]
            row.append(f"{_short(metric)} ({metric['num']}/{metric['den']})")
        row.append(_meets(data["metrics"]["total"][key], op, value))
        rows.append(row)
    return _table(["Metric", "Target", "Total", *DOMAIN_ORDER, "Total vs target"], rows)


def _full_metrics(data: dict[str, Any]) -> str:
    keys = [
        ("domain_accuracy", "Domain accuracy"),
        ("sheet_accuracy", "Sheet selection accuracy (multi-sheet documents)"),
        ("header_accuracy", "Header detection accuracy"),
        ("table_boundary_accuracy", "Table boundary accuracy (first record + number of records)"),
        ("required_precision", "Required-field precision (every claim)"),
        ("required_precision_committed", "Required-field precision (claims without a question)"),
        ("required_recall", "Required-field recall"),
        (
            "required_recall_incl_asked",
            "Required-field recall, counting columns the person is asked about",
        ),
        ("all_fields_precision", "All-fields precision"),
        ("all_fields_recall", "All-fields recall"),
        ("pii_exclusion", "Personal columns left out of the import"),
        ("zero_question_coverage", "Zero-question coverage"),
        ("zero_question_correctness", "Zero-question correctness"),
        ("false_automation_rate", "FALSE AUTOMATION RATE (of all documents)"),
        (
            "false_automation_rate_of_automatic",
            "False automation, of the documents offered as automatic",
        ),
        ("necessary_question_recall", "Necessary-question recall"),
        ("unnecessary_question_rate", "Unnecessary-question rate (of the questions asked)"),
        ("safe_fallback", "Safe fallback (not automatic)"),
        (
            "safe_fallback_strict",
            "Safe fallback, strict (refusal documents ending manual or blocked)",
        ),
        ("conversation_resolved", "Conversations that end in an automatic import"),
        ("conversation_correct", "...and end with the right reading"),
    ]
    rows = []
    for key, label in keys:
        rows.append([label, *[pct(data["metrics"][n][key]) for n in ("total", *DOMAIN_ORDER)]])
    extra: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Documents", lambda m: str(m["documents"])),
        ("Documents with a false automation", lambda m: str(m["false_automation_count"])),
        (
            "Personal values found in what is sent to the browser",
            lambda m: str(m["pii_value_leaks"]),
        ),
        ("Documents with such a leak", lambda m: str(m["pii_cases_with_leak"])),
        ("Junk columns that became a field", lambda m: str(m["junk_columns_mapped"])),
        (
            "Questions asked / unnecessary",
            lambda m: f"{m['questions_asked']} / {m['questions_unnecessary']}",
        ),
        (
            "Documents with at least one unnecessary question",
            lambda m: str(m["documents_with_unnecessary_question"]),
        ),
        (
            "Department words asked about that needed no question",
            lambda m: str(m["department_words_asked_needlessly"]),
        ),
        (
            "Department words decided silently",
            lambda m: str(m["department_words_guessed_silently"]),
        ),
        ("Department words read as the wrong category", lambda m: str(m["department_words_wrong"])),
        ("Automatic with a visible warning", lambda m: str(m["automatic_with_warning"])),
        ("Rounds of answers needed (mean)", lambda m: f"{m['conversation_rounds_mean']:.1f}"),
    ]
    for label, function in extra:
        rows.append([label, *[function(data["metrics"][n]) for n in ("total", *DOMAIN_ORDER)]])
    return _table(["Metric", "Total", *DOMAIN_ORDER], rows)


def _corpus(data: dict[str, Any]) -> str:
    c = data["corpus"]
    rows = [
        ["Documents", str(c["documents"])],
        *[[name, str(c["by_card"].get(name, 0))] for name in DOMAIN_ORDER],
        ["Excel / CSV", f"{c['xlsx']} / {c['csv']}"],
        [
            "Office-realistic (merged cells, colours, notes, odd headers...)",
            str(c["office_realistic"]),
        ],
        [
            "Negative (incomplete, ambiguous, malformed, out of domain, contradictory)",
            str(c["negative_refusals"]),
        ],
        [
            "Adversarial (instructions, formulas, HTML, long cells, hidden sheets...)",
            str(c["adversarial"]),
        ],
        ["With personal data", str(c["with_personal_data"])],
        ["More than one sheet", str(c["multi_sheet"])],
        ["Large (1,600 - 3,200 rows)", str(c["large"])],
        ["Distinct structure signatures", str(c["distinct_structures"])],
        ["Expected outcome", ", ".join(f"{k} {v}" for k, v in sorted(c["outcomes"].items()))],
        ["Corpus hash (sha256)", f"`{c['sha256'][:16]}...`"],
    ]
    return _table(["", ""], rows)


def _false_automation(data: dict[str, Any]) -> str:
    cases = [c for c in data["cases"] if c["false_automation"]]
    if not cases:
        return "No document was offered as automatic with a wrong reading."
    rows = []
    for c in cases:
        rows.append(
            [
                f"`{c['id']}`",
                c["card"],
                c["outcome"],
                "; ".join(c["false_automation_reasons"]),
                c["reason"],
            ]
        )
    return _table(["Document", "Card", "Truth says", "What differs", "What NINFA decided"], rows)


def _zero_question_audit(data: dict[str, Any]) -> str:
    automatic = [c for c in data["cases"] if c["automatic"]]
    rows = []
    for c in sorted(automatic, key=lambda c: (c["fully_correct"], c["id"])):
        problems = [
            f"{f['category']}: {f['detail']}"
            for f in c["findings"]
            if f["category"] not in {"QUESTION_UNNECESSARY"}
        ]
        verdict = "correct" if c["fully_correct"] else "**NOT correct**"
        if c["warned"] and c["outcome"] == "WARN":
            verdict += " (contradiction shown as a warning)"
        rows.append([f"`{c['id']}`", c["card"], verdict, "; ".join(problems) or "-"])
    return _table(["Document", "Card", "Totally correct?", "What was wrong"], rows)


def _missing_kinds(case: dict[str, Any]) -> str:
    return ", ".join(f["expected"] for f in case["findings"] if f["category"] == "QUESTION_MISSING")


def _questions(data: dict[str, Any]) -> str:
    cases = data["cases"]
    unnecessary: Counter[tuple[str, str]] = Counter()
    for c in cases:
        for f in c["findings"]:
            if f["category"] == "QUESTION_UNNECESSARY":
                observed = f["observed"]
                kind, _, rest = observed.partition(" ")
                unnecessary[(c["card"], kind + (" " + rest if rest else ""))] += 1
    by_kind: Counter[tuple[str, str]] = Counter()
    for (card, label), n in unnecessary.items():
        by_kind[(card, label.split(" ")[0])] += n
    rows = [
        [card, kind, str(n)] for (card, kind), n in sorted(by_kind.items(), key=lambda i: -i[1])
    ]
    top_columns = Counter(
        {(card, label): n for (card, label), n in unnecessary.items() if "(" in label}
    )
    rows2 = [[card, label, str(n)] for (card, label), n in top_columns.most_common(15)]
    missing = [
        f"`{c['id']}` ({_missing_kinds(c)})"
        for c in cases
        if any(f["category"] == "QUESTION_MISSING" for f in c["findings"])
    ]
    parts = [
        f"Necessary questions: asked {pct(data['metrics']['total']['necessary_question_recall'])}. "
        f"Missing: {', '.join(missing) if missing else 'none'}.",
        "",
        "Unnecessary questions by kind (every question the truth does not need or tolerate):",
        "",
        _table(["Card", "Kind", "Questions"], rows),
        "",
        "The most frequent single causes (kind and column):",
        "",
        _table(["Card", "Question", "Times"], rows2),
    ]
    return "\n".join(parts)


def _pii(data: dict[str, Any]) -> str:
    total = data["metrics"]["total"]
    egress = total["egress_probe"]
    leaks = [
        c
        for c in data["cases"]
        if c["pii_values_leaked"]
        or c["egress_leaks"]
        or any(f["category"] == "PII_LEAK" for f in c["findings"])
    ]
    rows = [
        [
            f"`{c['id']}`",
            str(c["pii_values_leaked"]),
            str(c["egress_leaks"]),
            "; ".join(f["detail"] for f in c["findings"] if f["category"] == "PII_LEAK") or "-",
        ]
        for c in leaks
    ]
    lines = [
        f"Personal columns left out of the import: {pct(total['pii_exclusion'])}.",
        "Personal values that appear in what the API sends to the browser: "
        f"{total['pii_value_leaks']} "
        f"(in {total['pii_cases_with_leak']} documents, out of {total['pii_values_checked']} "
        "values checked).",
        f"What would be shown to a language model, if one were configured: {egress['documents']} "
        "documents "
        f"would reach it ({egress['calls']} calls recorded, nothing sent anywhere); "
        f"personal values in that evidence: {egress['pii_leaks']}.",
        "",
    ]
    if rows:
        lines.append(
            _table(
                [
                    "Document",
                    "Values in the browser answer",
                    "Values in the model evidence",
                    "What happened",
                ],
                rows,
            )
        )
    return "\n".join(lines)


def _per_domain(data: dict[str, Any]) -> str:
    out = []
    for name in DOMAIN_ORDER:
        m = data["metrics"][name]
        out.append(f"### {name}\n")
        out.append(
            f"{m['documents']} documents; levels {m['levels']}; findings by worst severity "
            f"{m['cases_by_worst_severity']}; clean documents {m['cases_clean']}.\n"
        )
        out.append(
            _table(
                ["Metric", "Value"],
                [
                    ["Domain accuracy", pct(m["domain_accuracy"])],
                    ["Header accuracy", pct(m["header_accuracy"])],
                    ["Table boundary accuracy", pct(m["table_boundary_accuracy"])],
                    [
                        "Required precision / recall",
                        f"{pct(m['required_precision'])} / {pct(m['required_recall'])}",
                    ],
                    [
                        "Zero-question coverage / correctness",
                        f"{pct(m['zero_question_coverage'])} / "
                        f"{pct(m['zero_question_correctness'])}",
                    ],
                    [
                        "False automation",
                        f"{m['false_automation_count']} ({pct(m['false_automation_rate'])})",
                    ],
                    ["Necessary-question recall", pct(m["necessary_question_recall"])],
                    ["Unnecessary-question rate", pct(m["unnecessary_question_rate"])],
                    ["Safe fallback", pct(m["safe_fallback"])],
                    [
                        "Wrong-card probe (uploaded on another card)",
                        f"{m['wrong_card_probe']['documents']} documents: automatic "
                        f"{m['wrong_card_probe']['automatic']}, asked 'what kind of data' "
                        f"{m['wrong_card_probe']['asked_domain']}",
                    ],
                ],
            )
        )
        out.append("")
    return "\n".join(out)


def _performance(data: dict[str, Any]) -> str:
    rows = []
    for name in ("total", *DOMAIN_ORDER):
        m = data["metrics"][name]
        p, mem, size = m["performance_ms"], m["memory_kib"], m["bytes"]
        rows.append(
            [
                name,
                f"{p['mean']:.0f}",
                f"{p['p50']:.0f}",
                f"{p['p95']:.0f}",
                f"{p['max']:.0f}",
                f"{mem['p50'] / 1024:.1f} / {mem['max'] / 1024:.1f}",
                f"{size['p50'] / 1024:.1f} / {size['max'] / 1024:.0f}",
            ]
        )
    return _table(
        [
            "",
            "mean ms",
            "p50 ms",
            "p95 ms",
            "max ms",
            "peak Python memory MiB (p50 / max)",
            "file KiB (p50 / max)",
        ],
        rows,
    )


def failure_modes(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for c in cases:
        for f in c["findings"]:
            if f["category"] == "QUESTION_UNNECESSARY":
                kind = f["observed"].split(" ")[0]
                key = (f["category"], kind)
            elif f["category"] in {"FIELD_MISSED", "FIELD_WRONG"}:
                key = (f["category"], f["field"] or "")
            else:
                key = (f["category"], "")
            group = groups.setdefault(key, {"cases": set(), "severity": "P3", "examples": []})
            group["cases"].add(c["id"])
            if SEVERITY_ORDER.index(f["severity"]) < SEVERITY_ORDER.index(group["severity"]):
                group["severity"] = f["severity"]
            if len(group["examples"]) < 3 and c["id"] not in group["examples"]:
                group["examples"].append(c["id"])
    modes = [
        {
            "category": k[0],
            "what": k[1],
            "cases": len(v["cases"]),
            "severity": v["severity"],
            "examples": v["examples"],
        }
        for k, v in groups.items()
    ]
    return sorted(modes, key=lambda m: (SEVERITY_ORDER.index(m["severity"]), -m["cases"]))


def _confusion(data: dict[str, Any]) -> str:
    """How many findings (and documents) of each category, per kind of data."""
    from tests.benchmarks.smart_import_v3.score import CATEGORIES

    rows = []
    for category in CATEGORIES:
        row = [category]
        for name in ("total", *DOMAIN_ORDER):
            m = data["metrics"][name]
            row.append(
                f"{m['findings_by_category'][category]} ({m['cases_by_category'][category]})"
            )
        rows.append(row)
    return _table(["Category", "Total", *DOMAIN_ORDER], rows)


def _failure_modes(data: dict[str, Any]) -> str:
    modes = failure_modes(data["cases"])[:30]
    rows = [
        [
            m["severity"],
            m["category"],
            m["what"] or "-",
            str(m["cases"]),
            ", ".join(f"`{e}`" for e in m["examples"]),
        ]
        for m in modes
    ]
    return _table(["Worst severity", "Category", "Field / kind", "Documents", "Examples"], rows)


def _missed_headers(data: dict[str, Any]) -> str:
    seen: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for c in data["cases"]:
        for f in c["findings"]:
            if f["category"] == "FIELD_MISSED" and f["expected"].startswith("column"):
                seen[(c["card"], f["field"] or "", f["expected"])].append(c["id"])
    rows = [
        [card, field, expected.replace("column ", ""), ", ".join(f"`{i}`" for i in ids[:2])]
        for (card, field, expected), ids in sorted(seen.items())
    ]
    return _table(["Card", "Field", "Header not recognised", "Documents"], rows)


def _appendix_errors(data: dict[str, Any]) -> str:
    blocks = []
    for c in data["cases"]:
        real = [f for f in c["findings"]]
        if not real:
            continue
        categories = ", ".join(sorted({f["category"] for f in real}))
        worst = min((f["severity"] for f in real), key=SEVERITY_ORDER.index)
        asked = ", ".join(c["questions_asked"]) or "none"
        expected_q = ", ".join(c["questions_expected"]) or "none"
        lines = [
            f"**`{c['id']}`** - {categories} ({worst})",
            f"- card: {c['card']} - truth says: {c['outcome']} - NINFA: {c['level']}"
            f"{' (automatic)' if c['automatic'] else ''}",
            f"- kind of data: expected {c['golden_domain']}, detected {c['observed_domain']} "
            f"({c['detection_level'] or '-'})",
            f"- mapping expected: {_dict(c['expected_mapping'])}",
            f"- mapping observed: {_dict(c['observed_mapping'])}",
            f"- questions expected: {expected_q} - asked: {asked}",
            f"- confidence: {c['confidence']}",
            f"- why: {c['reason']}",
        ]
        for f in real:
            lines.append(f"  - {f['category']} [{f['severity']}]: {f['detail']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _dict(mapping: dict[str, str]) -> str:
    return "; ".join(f"{k} <- {v}" for k, v in mapping.items()) or "-"


def _appendix_corpus(data: dict[str, Any]) -> str:
    rows = [
        [
            f"`{c['id']}`",
            c["card"],
            c["outcome"],
            c["level"] or "-",
            ", ".join(t for t in c["tags"] if t not in {"xlsx", "csv"}) or "-",
        ]
        for c in data["cases"]
    ]
    return _table(["Document", "Card", "Truth says", "NINFA", "Tags"], rows)


def markdown_report(data: dict[str, Any], date: str = "") -> str:
    interpretation = INTERPRETATION.read_text(encoding="utf-8") if INTERPRETATION.exists() else ""
    total = data["metrics"]["total"]
    p = total["performance_ms"]
    sections = [
        "# Smart Import V3 - Intelligence Benchmark V1",
        "",
        f"Baseline: `main` = `{data['baseline_main']}` (Smart Import V3.0, merged). "
        f"Assistant: **off** - {data['assistant']}. "
        f"Run on {total['documents']} synthetic documents" + (f", {date}" if date else "") + ".",
        "",
        f"Rerun with one command, from `services/api`: `{COMMAND}` "
        "(console summary + JSON in `tests/benchmarks/results/` + this report). "
        "Nothing is read from or written to a database, nothing leaves the process, no model is "
        "called.",
        "",
        "## 1. Result",
        "",
        "Targets are the ones the benchmark was asked to compare against; nothing was changed to "
        "reach them.",
        "",
        _headline(data),
        "",
        f"**False automation: {total['false_automation_count']} of {total['documents']} documents "
        f"({_short(total['false_automation_rate'])})** - offered as automatic (a summary and one "
        "button) "
        "while the reading differs from the truth in a business-critical field, or while the "
        "document should "
        "never have been automatic. They are listed in section 3.",
        "",
        "## 2. Corpus",
        "",
        _corpus(data),
        "",
        "## 3. False automation",
        "",
        _false_automation(data),
        "",
        "## 4. Zero-question audit",
        "",
        f"{total['levels'].get('READY', 0)} documents ended READY; "
        f"{sum(1 for c in data['cases'] if c['automatic'])} of them with no question and no "
        "blocker (automatic). "
        "Every one is listed.",
        "",
        _zero_question_audit(data),
        "",
        "## 5. All metrics",
        "",
        _full_metrics(data),
        "",
        "## 6. Questions",
        "",
        _questions(data),
        "",
        "## 7. Personal data",
        "",
        _pii(data),
        "",
        "## 8. Results by kind of data",
        "",
        _per_domain(data),
        "## 9. Performance",
        "",
        "Baseline only, nothing optimised. Timing is the median of 3 calls per document after a "
        "warm-up; "
        f"memory is the peak of Python allocations (`tracemalloc`) of one call. "
        f"Mean {p['mean']:.0f} ms, p50 {p['p50']:.0f} ms, p95 {p['p95']:.0f} ms, max "
        f"{p['max']:.0f} ms per document.",
        "",
        _performance(data),
        "",
        "## 10. Confusion report and failure modes",
        "",
        "Findings by category - the figure in brackets is the number of documents. "
        "Every finding of every document is in Appendix A.",
        "",
        _confusion(data),
        "",
        "Failure modes: findings grouped by category and field (or question kind), worst "
        "severity first. "
        "P0 = silent wrong data, P1 = blocks a valid file, P2 = needless friction, P3 = edge case.",
        "",
        _failure_modes(data),
        "",
        "Headers the truth says are a business field and NINFA did not recognise:",
        "",
        _missed_headers(data),
        "",
        interpretation,
        "",
        "## Appendix A - every document with a finding",
        "",
        _appendix_errors(data),
        "",
        "## Appendix B - the corpus",
        "",
        _appendix_corpus(data),
        "",
    ]
    return "\n".join(sections)

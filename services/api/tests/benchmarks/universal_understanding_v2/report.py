"""The console summary and the Markdown report of the Universal Understanding Benchmark V2."""

from typing import Any


def pct(ratio: dict[str, Any] | float | None, digits: int = 1) -> str:
    value = ratio.get("value") if isinstance(ratio, dict) else ratio
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def frac(ratio: dict[str, Any]) -> str:
    return f"{ratio['num']}/{ratio['den']}"


def _ms(value: float) -> str:
    return f"{value:.1f}"


GROUP_ORDER = ("Prenotazioni", "Personale", "Costi", "EASY", "MEDIUM", "HARD", "ADVERSARIAL")


def _row(name: str, data: dict[str, Any], extra: dict[str, Any]) -> list[str]:
    return [
        name,
        str(data["documents"]),
        pct(extra["domain_accuracy_strict"]),
        pct(extra["header_accuracy_strict"]),
        pct(extra["table_accuracy_strict"]),
        pct(data["required_precision"], 2),
        pct(data["required_recall"]),
        pct(extra["optional_precision"]),
        str(data["false_automation_count"]),
        str(extra["required_committed_wrong"]),
        pct(data["zero_question_rate_valid"]),
        pct(data["necessary_question_recall"]),
        str(data["questions_unnecessary"]),
        str(data["pii_value_leaks"]),
        str(data["findings_by_severity"]["P0"]),
        str(data["findings_by_severity"]["P1"]),
    ]


HEADER = [
    "Group",
    "Docs",
    "Domain",
    "Header",
    "Table",
    "Req. prec.",
    "Req. recall",
    "Opt. prec.",
    "FA",
    "Crit. wrong (committed)",
    "Zero-question",
    "Necessary Q",
    "Unneeded Q",
    "PII",
    "P0",
    "P1",
]


def rows(data: dict[str, Any]) -> list[list[str]]:
    out = []
    for name in ("positives", *GROUP_ORDER):
        metrics = data["metrics"][name]
        extra = data["v2"][name]
        out.append(_row("All positives" if name == "positives" else name, metrics, extra))
    return out


def console_summary(data: dict[str, Any]) -> str:
    lines = [f"{data['benchmark']}  ({data['corpus']['documents']} documents)", ""]
    table = [HEADER, *rows(data)]
    widths = [max(len(r[i]) for r in table) for i in range(len(HEADER))]
    for r in table:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)))
    negatives = data["metrics"]["negatives"]
    lines += [
        "",
        f"negatives   safe fallback {frac(negatives['safe_fallback'])}   "
        f"automatic {negatives['false_automation_count']}",
        f"unsupported clean refusal {frac(data['unsupported']['clean'])}",
        "",
        "targets",
    ]
    for t in data["targets"]:
        actual = "n/a" if t["actual"] is None else (f"{t['actual']:.4g}")
        lines.append(
            f"  [{'ok' if t['ok'] else '!!'}] {t['name']:<44} {t['op']} {t['target']}   {actual}"
        )
    stages = data.get("stages") or {}
    if stages:
        lines.append("")
        for key in ("scan_ms", "understanding_ms", "mapping_ms", "total_ms"):
            s = stages[key]
            lines.append(
                f"{key:<18} mean {_ms(s['mean'])}  p50 {_ms(s['p50'])}  "
                f"p95 {_ms(s['p95'])}  max {_ms(s['max'])}"
            )
    return "\n".join(lines)


def _table(header: list[str], body: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return out


def markdown_report(data: dict[str, Any], today: str, title: str | None = None) -> str:
    corpus = data["corpus"]
    metrics = data["metrics"]
    lines = [
        f"# {title or 'NINFA Smart Import — Universal Understanding Benchmark V2'}",
        "",
        f"Generated {today}. {data['assistant']}.",
        "",
        "Unseen documents, generated from recipes (none is in the official 240-document corpus), "
        "with the truth written next to each file and never read from Smart Import. First "
        "upload of each file: no learned profile.",
        "",
        "## Corpus",
        "",
        f"- **{corpus['documents']}** documents: {corpus['positives']} positives "
        f"({', '.join(f'{k} {v}' for k, v in corpus['by_domain'].items())}), "
        f"{corpus['negatives']} negatives, {corpus['unsupported']} unsupported files.",
        "- Difficulty of the positives: "
        + ", ".join(f"{k} {v}" for k, v in corpus["by_difficulty"].items())
        + ".",
        f"- {corpus['xlsx']} xlsx / {corpus['csv']} csv, {corpus['multi_sheet']} with several "
        f"sheets, {corpus['with_personal_data']} with personal data, "
        f"{corpus['distinct_structures']} distinct structures.",
        f"- sha256 `{corpus['sha256']}`",
        "",
        "## Targets",
        "",
        *_table(
            ["Target", "Wanted", "Actual", "Met"],
            [
                [
                    t["name"],
                    f"{t['op']} {t['target']}",
                    "n/a" if t["actual"] is None else f"{t['actual']:.4g}",
                    "yes" if t["ok"] else "**NO**",
                ]
                for t in data["targets"]
            ],
        ),
        "",
        "## Results by group (positive documents)",
        "",
        "Domain / header / table are STRICT: a document the engine could not read counts as a "
        "miss. FA = false automation. Crit. wrong = a CERTAIN wrong reading of a fact a "
        "business decision rests on. Necessary Q = recall of the questions a person must be "
        "asked.",
        "",
        *_table(HEADER, rows(data)),
        "",
        "## Negatives and unsupported files",
        "",
        f"- Negative office documents ({metrics['negatives']['documents']}): safe fallback "
        f"{frac(metrics['negatives']['safe_fallback'])}, offered as automatic "
        f"{metrics['negatives']['false_automation_count']}.",
        f"- Unsupported files ({data['unsupported']['documents']}): clean refusal "
        f"{frac(data['unsupported']['clean'])}.",
    ]
    bad = [u for u in data["unsupported"]["cases"] if not u["clean"]]
    for u in bad:
        lines.append(
            f"  - not clean: `{u['id']}` level {u['level']}, problem {u['problem']}, "
            f"error {u['error']}"
        )
    lines += [
        "",
        "Wrong readings of a critical fact at ANY level (a LOW guess the person is asked about "
        f"counts too): {data['v2']['positives']['critical_wrong_mapping']}; "
        "committed (certain and not asked): "
        f"{data['v2']['positives']['required_committed_wrong']}.",
    ]
    lines += ["", "## Findings", ""]
    total = metrics["total"]
    lines += _table(
        ["Severity", "Findings", "Documents (worst)"],
        [
            [
                s,
                str(total["findings_by_severity"][s]),
                str(total["cases_by_worst_severity"][s]),
            ]
            for s in ("P0", "P1", "P2", "P3")
        ],
    )
    lines += [""]
    lines += _table(
        ["Category", "Findings", "Documents"],
        [
            [c, str(n), str(total["cases_by_category"][c])]
            for c, n in total["findings_by_category"].items()
            if n
        ],
    )
    lines += ["", "## By recipe", ""]
    lines += _table(
        ["Recipe", "Docs", "With findings", "P0", "P1", "P2"],
        [
            [
                name,
                str(c.get("documents", 0)),
                str(c.get("with_findings", 0)),
                str(c.get("P0", 0)),
                str(c.get("P1", 0)),
                str(c.get("P2", 0)),
            ]
            for name, c in data["findings_by_recipe"].items()
        ],
    )
    stages = data.get("stages") or {}
    if stages:
        lines += ["", "## Performance (ms per file)", ""]
        lines += _table(
            ["Stage", "mean", "p50", "p95", "max"],
            [
                [
                    key.removesuffix("_ms"),
                    _ms(s["mean"]),
                    _ms(s["p50"]),
                    _ms(s["p95"]),
                    _ms(s["max"]),
                ]
                for key, s in stages.items()
            ],
        )
    levels = total["levels"]
    lines += [
        "",
        "## Reading levels (first answer)",
        "",
        ", ".join(f"{k} {v}" for k, v in sorted(levels.items())),
        "",
    ]
    return "\n".join(lines)

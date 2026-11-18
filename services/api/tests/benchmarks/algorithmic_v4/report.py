"""python -m tests.benchmarks.algorithmic_v4.report RESULTS.json [--out docs/benchmarks/....md]

Turns the numbers `python -m tests.benchmarks.algorithmic_v4 --json RESULTS.json` measured into the
comparison tables of the report. Nothing is typed in by hand: every figure is read from the JSON.

    1. the headline table, current (v3) against V4, over every document of every population
    2. the ablation, one row per configuration: what each part is worth
    3. every population apart, because an aggregate hides where a change helps and where it hurts
    4. the problem corpus by kind of header (camel, glued, typo, ...)
    5. the documents that moved: better, worse, and the safety invariants
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

SAFETY = (
    "unsafe_ready",
    "wrong_domain_ready",
    "scope_violations",
    "pii_values_in_the_browser_answer",
)
LABELS = {
    "v3": "current (V3)",
    "v4-header": "V4 header only",
    "v4": "V4 (header + value semantics)",
    "v4-assign": "V4 + global assignment (SciPy)",
    "v4-margin": "V4 + assignment + margin demotion",
}
RANK = {"READY": 0, "ASK": 1, "MANUAL": 2, "BLOCKED": 3, None: 4}


def aggregate(populations: Mapping[str, Any], engine: str, names: Sequence[str]) -> dict[str, Any]:
    total: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    weighted_ms = 0.0
    worst_p95 = 0.0
    documents = 0
    for name in names:
        population = populations[name]
        data = population["engines"][engine]
        documents += population["documents"]
        for record in data["per_document"].values():
            levels[str(record["level"])] += 1
            total["golden"] += record["golden"]
            total["correct"] += record["correct"]
            total["wrong"] += record["wrong"]
            total["missed"] += record["missed"]
            total["questions"] += record["questions"]
            total["unnecessary"] += record["unnecessary"]
            total["false_automation"] += 1 if record["false_automation"] else 0
        for key in SAFETY:
            total[key] += data["metrics"][key]
        total["errors"] += data["errors"]
        lat = data["latency"]
        weighted_ms += lat.get("mean_ms", 0.0) * population["documents"]
        worst_p95 = max(worst_p95, lat.get("p95_ms", 0.0))
    return {
        "documents": documents,
        "levels": levels,
        "totals": total,
        "recall": total["correct"] / total["golden"] if total["golden"] else 0.0,
        "mean_ms": weighted_ms / documents if documents else 0.0,
        "p95_ms": worst_p95,
    }


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def headline(
    populations: Mapping[str, Any], engines: Sequence[str], names: Sequence[str]
) -> list[str]:
    aggregated = {e: aggregate(populations, e, names) for e in engines}
    base = aggregated[engines[0]]
    rows: list[tuple[str, Callable[[dict[str, Any]], float], bool]] = [
        ("documents", lambda a: a["documents"], False),
        ("mapping recall (% of facts read right)", lambda a: 100 * a["recall"], True),
        ("READY (no question)", lambda a: a["levels"]["READY"], False),
        ("ASK (one or two questions)", lambda a: a["levels"]["ASK"], False),
        (
            "manual matching (MANUAL + BLOCKED)",
            lambda a: a["levels"]["MANUAL"] + a["levels"]["BLOCKED"],
            False,
        ),
        ("questions asked", lambda a: a["totals"]["questions"], False),
        ("unnecessary questions", lambda a: a["totals"]["unnecessary"], False),
        ("wrong claims (a fact read as another)", lambda a: a["totals"]["wrong"], False),
        ("missed facts", lambda a: a["totals"]["missed"], False),
        ("unsafe READY", lambda a: a["totals"]["unsafe_ready"], False),
        ("false automation", lambda a: a["totals"]["false_automation"], False),
        ("wrong-domain READY", lambda a: a["totals"]["wrong_domain_ready"], False),
        ("scope violations", lambda a: a["totals"]["scope_violations"], False),
        (
            "personal values in the browser answer",
            lambda a: a["totals"]["pii_values_in_the_browser_answer"],
            False,
        ),
        ("engine errors", lambda a: a["totals"]["errors"], False),
        ("understanding latency, mean ms", lambda a: a["mean_ms"], True),
        ("understanding latency, worst p95 ms", lambda a: a["p95_ms"], True),
    ]
    lines = [
        "| metric | "
        + " | ".join(LABELS.get(e, e) for e in engines)
        + " | delta (last vs current) |",
        "|---|" + "---:|" * (len(engines) + 1),
    ]
    for label, pick, decimal in rows:
        values = [pick(aggregated[e]) for e in engines]
        shown = [fmt(v, 1 if decimal else 0) for v in values]
        delta = values[-1] - values[0]
        lines.append(f"| {label} | " + " | ".join(shown) + f" | {delta:+.{1 if decimal else 0}f} |")
    del base
    return lines


def per_population(populations: Mapping[str, Any], engines: Sequence[str]) -> list[str]:
    lines: list[str] = []
    for name, population in populations.items():
        lines += [f"### {name} ({population['documents']} documents)", ""]
        lines += [
            "| metric | " + " | ".join(LABELS.get(e, e) for e in engines) + " |",
            "|---|" + "---:|" * len(engines),
        ]
        picks: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
            (
                "mapping recall",
                lambda d: (
                    f"{d['metrics']['mapping_recall']:.4f}"
                    if d["metrics"]["mapping_recall"] is not None
                    else "-"
                ),
            ),
            (
                "claims precision",
                lambda d: (
                    f"{d['metrics']['claims_precision']:.4f}"
                    if d["metrics"]["claims_precision"] is not None
                    else "-"
                ),
            ),
            ("READY", lambda d: str(d["ready"])),
            ("ASK", lambda d: str(d["metrics"]["asking"])),
            ("manual matching", lambda d: str(d["metrics"]["manual_matching"])),
            (
                "questions / unnecessary",
                lambda d: (
                    f"{d['metrics']['questions_asked']} / {d['metrics']['questions_unnecessary']}"
                ),
            ),
            ("unsafe READY", lambda d: str(d["metrics"]["unsafe_ready"])),
            ("false automation", lambda d: str(d["metrics"]["false_automation"])),
            (
                "latency mean / p95 ms",
                lambda d: (
                    f"{d['latency'].get('mean_ms', 0):.0f} / {d['latency'].get('p95_ms', 0):.0f}"
                ),
            ),
        )
        for label, pick in picks:
            lines.append(
                f"| {label} | " + " | ".join(pick(population["engines"][e]) for e in engines) + " |"
            )
        lines.append("")
    return lines


def kinds(population: Mapping[str, Any], engines: Sequence[str]) -> list[str]:
    counts: dict[str, dict[str, Counter[str]]] = {}
    for engine in engines:
        for record in population["engines"][engine]["per_document"].values():
            counts.setdefault(record["kind"] or "other", {}).setdefault(engine, Counter())[
                str(record["level"])
            ] += 1
    lines = ["| kind of header | engine | READY | ASK | manual |", "|---|---|---:|---:|---:|"]
    for kind in sorted(counts):
        for engine in engines:
            c = counts[kind].get(engine, Counter())
            lines.append(
                f"| {kind} | {LABELS.get(engine, engine)} | {c['READY']} | {c['ASK']} "
                f"| {c['MANUAL'] + c['BLOCKED']} |"
            )
    return lines


def movement(
    populations: Mapping[str, Any], base: str, engine: str
) -> tuple[list[str], dict[str, int]]:
    better: list[str] = []
    worse: list[str] = []
    for name, population in populations.items():
        before = population["engines"][base]["per_document"]
        after = population["engines"][engine]["per_document"]
        for doc_id, record in after.items():
            old = before[doc_id]
            if (record["level"], record["questions"]) == (old["level"], old["questions"]) and (
                record["correct"],
                record["wrong"],
            ) == (old["correct"], old["wrong"]):
                continue
            score_new = (
                RANK[record["level"]],
                record["wrong"] + record["missed"],
                record["unnecessary"],
            )
            score_old = (RANK[old["level"]], old["wrong"] + old["missed"], old["unnecessary"])
            line = (
                f"`{doc_id}` ({name}): {old['level']}/{old['questions']}q -> "
                f"{record['level']}/{record['questions']}q"
                f", wrong {old['wrong']}->{record['wrong']}"
                f", missed {old['missed']}->{record['missed']}"
            )
            (
                better if score_new < score_old else worse if score_new > score_old else better
            ).append(line)
    lines = [
        f"**{len(better)} documents read better (or as well, differently), {len(worse)} worse.**",
        "",
    ]
    lines += ["Worse:", *(f"- {x}" for x in worse), ""] if worse else ["Worse: none.", ""]
    return lines, {"better": len(better), "worse": len(worse)}


def build(data: Mapping[str, Any], names: Sequence[str] | None = None) -> str:
    engines = data["engines"]
    populations = data["populations"]
    chosen = list(names or populations)
    lines = ["# Smart Import V4.1 - algorithmic understanding: measured results", ""]
    lines += [
        "Generated by `python -m tests.benchmarks.algorithmic_v4.report`; nothing typed by hand.",
        "",
    ]
    lines += ["## All populations together", "", *headline(populations, engines, chosen), ""]
    lines += ["## One population at a time", "", *per_population(populations, engines)]
    if "problem" in populations:
        lines += [
            "## Problem corpus, by kind of header",
            "",
            *kinds(populations["problem"], engines),
            "",
        ]
    best = engines[-1]
    moved, _counts = movement(populations, engines[0], best)
    lines += [
        f"## Documents that moved ({LABELS.get(engines[0], engines[0])} -> "
        f"{LABELS.get(best, best)})",
        "",
        *moved,
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.algorithmic_v4.report")
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--populations", default=None, help="comma separated subset")
    args = parser.parse_args(argv)
    data = json.loads(args.results.read_text(encoding="utf-8"))
    names = args.populations.split(",") if args.populations else None
    text = build(data, names)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

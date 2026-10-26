"""The written report of the Source Learning benchmark."""

from collections.abc import Mapping, Sequence
from typing import Any


def pct(rate: Mapping[str, Any]) -> str:
    if not rate["den"]:
        return "n/a"
    return f"{100 * rate['value']:.1f}% ({rate['num']}/{rate['den']})"


def table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def markdown(data: Mapping[str, Any], today: str) -> str:
    out: list[str] = []
    add = out.append
    add("# Source Learning - Benchmark V1\n")
    add(
        f"Run {today}. {data['families']} sources ({data['trusted_families']} the person has to "
        f"teach, {data['control_families']} the engine reads alone), {data['versions_per_family']} "
        f"versions each = **{data['document_versions']} documents**, each understood twice: by the "
        "property that taught the source (with a memory of what a person confirmed) and by another "
        "property that has never seen it (no memory). No model, no embedding, no external service; "
        "the 240-document benchmark is not touched.\n"
    )
    add(
        "> **How to read it.** V1 is the first file: the person answers (or matches the columns by "
        "hand), the server recomputes READY, the explicit import writes and remembers. V2..V8 are "
        "the same source later: other data (V2), columns moved (V3), a junk column (V4), cosmetic "
        "headers (V5), a new column (V6), a known column gone (V7), a column that changed meaning "
        "(V8). The "
        "two control sources are read by the engine alone: nothing should be learned from them.\n"
    )

    add("## Result\n")
    saved = data["questions_saved"]
    eff = data["learning_effectiveness"]
    add(
        table(
            ["Measure", "Target", "Measured"],
            [
                [
                    "Exact reuse (V2, V3, V5: the same source, nothing asked again)",
                    "100%",
                    pct(data["exact_reuse_rate"]),
                ],
                [
                    "Compatible reuse (V4, V6: something added, nothing asked again)",
                    "100%",
                    pct(data["compatible_reuse_rate"]),
                ],
                [
                    "Repeated mapping questions on an unchanged source",
                    "0",
                    data["repeated_mapping_questions_on_unchanged_source"],
                ],
                [
                    "Wrong reuse (a reused column read as something it is not)",
                    "0%",
                    pct(data["wrong_reuse_rate"]),
                ],
                [
                    "Readings automatic with a WRONG field (false automation with memory)",
                    "0",
                    data["false_automation_with_memory"],
                ],
                ["Cross-property contamination", "0", data["cross_property_contamination"]],
                ["Cross-domain contamination", "0", data["cross_domain_contamination"]],
                ["Conflict detection recall (V8)", "100%", pct(data["conflict_detection_recall"])],
                [
                    "Missing-column detection recall (V7)",
                    "100%",
                    pct(data["missing_detection_recall"]),
                ],
                [
                    "Every version behaves as expected",
                    "100%",
                    pct(data["all_versions_as_expected"]),
                ],
            ],
        )
        + "\n"
    )

    add("## What learning saves\n")
    add(
        table(
            ["", "Without memory", "With memory"],
            [
                [
                    "Asks to answer or to match by hand, V2..V8 of the 10 taught sources",
                    saved["asks_without_memory"],
                    saved["asks_with_memory"],
                ],
                [
                    "Versions Smart Import reads with nothing to ask",
                    saved["versions_asking_nothing_without_memory"],
                    saved["versions_asking_nothing_with_memory"],
                ],
            ],
        )
        + "\n"
    )
    add(
        f"**{saved['saved']} asks saved**, of which {saved['manual_matchings_avoided']} manual "
        "matchings of the columns avoided. First import against next import (V1 vs V2): "
        f"{eff['first_import_effort']} asks the first time, {eff['next_import_effort']} the next "
        f"({pct(eff['effort_removed'])} removed).\n"
    )

    add("## By source\n")
    rows = []
    for fam in data["per_family"]:
        first = fam["first"]
        rows.append(
            [
                fam["family"],
                fam["domain"],
                "control (engine alone)" if fam["control"] else first["how"],
                len(first["asked"]) if first["asked"] else "-",
                pct(fam["exact"]),
                pct(fam["compatible"]),
                fam["questions_saved"],
                fam["wrong_reuse"],
                "-" if fam["control"] else ("yes" if fam["conflict_detected"] else "NO"),
                "yes" if fam["all_as_expected"] else "NO",
            ]
        )
    add(
        table(
            [
                "Source",
                "Domain",
                "First time",
                "Questions",
                "Exact reuse",
                "Compatible reuse",
                "Asks saved",
                "Wrong reuse",
                "Conflict detected",
                "All as expected",
            ],
            rows,
        )
        + "\n"
    )

    add("## Time\n")
    perf = data["performance_ms"]
    add(
        table(
            ["Milliseconds", "mean", "p50", "p95", "max"],
            [
                [
                    "Matching a file with the memory (`match_source`)",
                    *perf["match_source"].values(),
                ],
                ["Understanding a file, with a memory", *perf["understand_with_memory"].values()],
                ["Understanding a file, without", *perf["understand_without_memory"].values()],
            ],
        )
        + "\n"
    )

    add("## Every version\n")
    rows = []
    for version in data["versions"]:
        mem = version["with_memory"]
        rows.append(
            [
                version["family"],
                version["version"],
                version["title"],
                mem["structure"] or "-",
                mem["drift"] or "-",
                mem["level"],
                len(mem["questions"]),
                len(mem["reused"]),
                version["without_memory"]["level"],
                len(version["without_memory"]["questions"]),
                "ok" if version["ok"] else f"NOT OK: {version['why']}",
            ]
        )
    add(
        table(
            [
                "Source",
                "V",
                "What changed",
                "Match",
                "Drift",
                "Level (memory)",
                "Questions",
                "Reused",
                "Level (none)",
                "Questions (none)",
                "Result",
            ],
            rows,
        )
        + "\n"
    )
    if data["failures"]:
        add("## Where it did not behave as expected\n")
        for failure in data["failures"]:
            add(f"* {failure['family']} {failure['version']}: {failure['why']}")
        add("")
    return "\n".join(out) + "\n"

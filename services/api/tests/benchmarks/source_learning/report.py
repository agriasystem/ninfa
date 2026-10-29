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
    if data.get("multi_family"):
        add(multi_markdown(data["multi_family"]))
    if data.get("format_family"):
        add(formats_markdown(data["format_family"]))
    return "\n".join(out) + "\n"


EVENTS = {
    "teach": "taught",
    "see": "a later file",
    "undecidable": "could be either twin",
    "import": "imported from memory",
    "correct": "corrected by hand",
}


def multi_markdown(multi: Mapping[str, Any]) -> str:
    """The multi-source extension: several recurring families in ONE property and kind of data."""
    out: list[str] = []
    add = out.append
    saved = multi["questions_saved"]
    add("## Several sources in one property (multi-source extension)\n")
    add(
        f"{multi['properties']} properties (bookings, staff, costs), each with "
        f"**{multi['families_per_property']} recurring families in the same kind of data**: "
        f"{multi['families']} families, {multi['documents']} documents in "
        f"{multi['timeline_steps']} timeline steps. A property is taught one family at a time and "
        "a later file of any of them arrives, as it would over months: A -> A, A -> B, B -> A, "
        "A -> B -> C -> A -> C -> B, a drifted A after B and C, a twin of A taught later, an "
        "import "
        "from memory, a correction by hand. The twin of A has the same columns plus a different "
        "optional one (the engine reads the two as different fields), so the two can only be told "
        "apart by what the file contains; five files per property are the twins' common part, with "
        "and without the column of each: they could be either, and the right answer is to reuse "
        "nothing. No model, no embedding, no external service.\n"
    )
    add("### Result\n")
    add(
        table(
            ["Measure", "Target", "Measured"],
            [
                [
                    "Returning-family recognition (a family seen again after another one, "
                    "unchanged or harmlessly changed: recognised, nothing asked)",
                    "100%",
                    pct(multi["returning_family_recognition"]),
                ],
                [
                    "The right family, in every file that has one (incl. a column gone or a "
                    "contradicted one)",
                    "100%",
                    pct(multi["right_family_every_expected_step"]),
                ],
                [
                    "Cross-family wrong reuse (a file read as another family, or a reused "
                    "column read as something it is not)",
                    "0",
                    multi["cross_family_wrong_reuse"],
                ],
                [
                    "Family-collision false match (a file that could be either twin: one is "
                    "chosen, or anything is reused)",
                    "0",
                    pct(multi["family_collision_false_match"]),
                ],
                ["A twin taken for its sibling", "0", multi["twin_confusions"]],
                [
                    "Repeated questions after a returning source, unchanged",
                    "0",
                    multi["repeated_questions_after_returning_source"],
                ],
                [
                    "Correct family after cosmetic / additive drift (columns moved, a junk column, "
                    "cosmetic headers, a new column)",
                    "100%",
                    pct(multi["correct_family_after_cosmetic_or_additive_drift"]),
                ],
                [
                    "Other families untouched by an import from memory or a correction by hand",
                    "100%",
                    pct(multi["store_intact_after_import_or_correction"]),
                ],
                ["Cross-property contamination", "0", multi["cross_property_contamination"]],
                ["Cross-domain contamination", "0", multi["cross_domain_contamination"]],
                ["Every step behaves as expected", "100%", pct(multi["every_step_as_expected"])],
            ],
        )
        + "\n"
    )
    add(
        f"**{saved['saved']} asks saved** ({saved['asks_without_memory']} without a memory, "
        f"{saved['asks_with_memory']} with); {saved['documents_asking_nothing_with_memory']} "
        "documents are read with nothing to ask, "
        f"{saved['documents_asking_nothing_without_memory']} without it.\n"
    )
    add("### By property\n")
    add(
        table(
            ["Property", "Kind of data", "Families", "Remembered", "Revisions"],
            [
                [
                    f"{info['site']}: {info['title']}",
                    info["domain"],
                    ", ".join(info["families"]),
                    info["families_in_memory"],
                    ", ".join(f"{k}: {v}" for k, v in info["revisions"].items()),
                ]
                for info in multi["per_site"]
            ],
        )
        + "\n"
    )
    if multi["failures"]:
        add("### Where it did not behave as expected\n")
        for failure in multi["failures"]:
            add(
                f"* {failure['site']} step {failure['n']} {failure['family']} "
                f"{failure['version']}: {failure['why']}"
            )
        add("")
    add("### Every step\n")
    rows = []
    for step in multi["steps"]:
        rows.append(
            [
                step["site"],
                step["n"],
                EVENTS.get(step["kind"], step["kind"]),
                step["family"],
                step["version"] or "-",
                "-" if "family_chosen" not in step else (step["family_chosen"] or "none"),
                "yes" if step.get("ambiguous") else "-",
                step.get("structure") or "-",
                step.get("drift") or "-",
                step.get("level", "-"),
                step.get("questions", "-"),
                step.get("reused", "-"),
                "ok" if step["ok"] else f"NOT OK: {step['why']}",
            ]
        )
    add(
        table(
            [
                "Property",
                "#",
                "Event",
                "Family",
                "V",
                "Chosen",
                "Ambiguous",
                "Match",
                "Drift",
                "Level",
                "Questions",
                "Reused",
                "Result",
            ],
            rows,
        )
        + "\n"
    )
    return "\n".join(out)


FORMAT_EVENTS = {
    "teach": "taught",
    "see": "a later file",
    "either": "could be either lookalike",
    "import": "imported from memory",
}


def formats_markdown(data: Mapping[str, Any]) -> str:
    """The multi-format extension: how each family is READ, with several formats in one source."""
    out: list[str] = []
    add = out.append
    saved = data["questions_saved"]
    add("## Several formats in one source (multi-format extension)\n")
    add(
        f"{data['properties']} properties, {data['formats']} formats, {data['documents']} "
        f"documents in {data['timeline_steps']} timeline steps: a property is taught one family at "
        "a time and files of all of them keep coming, as they would over months - an xlsx whose "
        "table sits under "
        "a title, another xlsx on another sheet with the table lower down, a csv, a people x days "
        "grid, a document whose department is only in its title, an ordinary table in xlsx and in "
        "csv. A -> B -> A, A -> B -> A -> B, A -> C -> A -> C, A -> B -> C -> A -> B, SPECIAL -> "
        "NORMAL -> SPECIAL. Two lookalike exports need different sheets, and files that could be "
        "either of them must be read with NEITHER's. A file is read the way it was taught, "
        "whichever family was imported in between. No model, no embedding, no external service.\n"
    )
    add("### Result\n")
    add(
        table(
            ["Measure", "Target", "Measured"],
            [
                ["Correct family", "100%", pct(data["correct_family"])],
                [
                    "Correct layout (sheet, grid hours, origin of the department)",
                    "100%",
                    pct(data["correct_family_layout"]),
                ],
                [
                    "Wrong layout reuse (a layout of another family, or one applied to a file "
                    "that is not that family's)",
                    "0",
                    data["wrong_layout_reuse"],
                ],
                [
                    "Cross-family layout contamination",
                    "0",
                    data["cross_family_layout_contamination"],
                ],
                [
                    "Documents that could not be read because of another family's layout",
                    "0",
                    data["documents_that_could_not_be_read"],
                ],
                [
                    "Repeated mapping questions on a returning family, unchanged",
                    "0",
                    data["repeated_mapping_questions_on_returning_unchanged"],
                ],
                ["Returning-family recognition", "100%", pct(data["returning_family_recognition"])],
                [
                    "Recognised and read the same after a harmless drift (a column nobody "
                    "asked for)",
                    "100%",
                    pct(data["recognised_after_harmless_drift"]),
                ],
                [
                    "A file that could be either of two families gets a layout of one",
                    "0",
                    data["ambiguous_layout_reuse"],
                ],
                [
                    "A file that could be either of two families reuses one of them",
                    "0",
                    data["ambiguous_family_reuse"],
                ],
                [
                    "Other families untouched by an import from memory",
                    "100%",
                    pct(data["store_intact_after_import"]),
                ],
                ["Every step behaves as expected", "100%", pct(data["every_step_as_expected"])],
            ],
        )
        + "\n"
    )
    add(
        f"**{saved['saved']} asks saved** ({saved['asks_without_memory']} without a memory, "
        f"{saved['asks_with_memory']} with); {saved['documents_asking_nothing_with_memory']} "
        "documents are read with nothing to ask, "
        f"{saved['documents_asking_nothing_without_memory']} without it.\n"
    )
    add("### By property\n")
    add(
        table(
            ["Property", "Kind of data", "Formats", "Families remembered", "Read as"],
            [
                [
                    f"{info['site']}: {info['title']}",
                    info["domain"],
                    ", ".join(info["formats"]),
                    info["families_in_memory"],
                    "; ".join(
                        f"{name}: {layout or 'its table'}" for name, layout in info["layouts"]
                    ),
                ]
                for info in data["per_site"]
            ],
        )
        + "\n"
    )
    if data["failures"]:
        add("### Where it did not behave as expected\n")
        for failure in data["failures"]:
            add(
                f"* {failure['site']} step {failure['n']} {failure['format']} "
                f"{failure['variant']}: {failure['why']}"
            )
        add("")
    add("### Every step\n")
    rows = []
    for step in data["steps"]:
        rows.append(
            [
                step["site"],
                step["n"],
                FORMAT_EVENTS.get(step["kind"], step["kind"]),
                step["format"],
                step["variant"] or "-",
                "-" if "family_chosen" not in step else (step["family_chosen"] or "none"),
                "yes" if step.get("ambiguous") else "-",
                "-" if "read_as" not in step else (step["read_as"] or "its table"),
                step.get("level", "-"),
                step.get("questions", "-"),
                "ok" if step["ok"] else f"NOT OK: {step['why']}",
            ]
        )
    add(
        table(
            [
                "Property",
                "#",
                "Event",
                "Format",
                "Variant",
                "Chosen",
                "Ambiguous",
                "Read as",
                "Level",
                "Questions",
                "Result",
            ],
            rows,
        )
        + "\n"
    )
    return "\n".join(out)

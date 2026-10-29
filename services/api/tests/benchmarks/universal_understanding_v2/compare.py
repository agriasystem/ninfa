"""python -m tests.benchmarks.universal_understanding_v2.compare BEFORE.json AFTER.json

Case by case: what changed between two runs of a benchmark (the official 240 or V2 - both write the
same `cases` records). A case is IMPROVED when its worst finding got less severe or disappeared, or
it became automatic while correct; WORSE when the opposite; CHANGED when only the reading moved.
Every case that is not identical is listed - none is hidden in an aggregate.
"""

import json
import sys
from pathlib import Path
from typing import Any

SEVERITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _worst(case: dict[str, Any]) -> int:
    findings = case["findings"]
    return min((SEVERITY[f["severity"]] for f in findings), default=9)


def _signature(case: dict[str, Any]) -> tuple[Any, ...]:
    return (
        case["level"],
        case["automatic"],
        tuple(sorted(case["observed_mapping"].items())),
        tuple(case["questions_asked"]),
        tuple(sorted((f["severity"], f["category"], f["detail"]) for f in case["findings"])),
    )


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old = {c["id"]: c for c in before["cases"]}
    out: list[dict[str, Any]] = []
    for case in after["cases"]:
        previous = old.get(case["id"])
        if previous is None:
            out.append({"id": case["id"], "verdict": "NEW", "case": case})
            continue
        if _signature(previous) == _signature(case):
            continue
        worse = _worst(case) < _worst(previous)
        better = _worst(case) > _worst(previous)
        if not better and not worse:
            better = len(case["findings"]) < len(previous["findings"])
            worse = len(case["findings"]) > len(previous["findings"])
        if case["automatic"] and not previous["automatic"] and not case["findings"]:
            better = True
        if case["automatic"] and case["findings"] and not previous["automatic"]:
            worse = True
        verdict = (
            "WORSE" if worse and not better else "IMPROVED" if better and not worse else "CHANGED"
        )
        out.append({"id": case["id"], "verdict": verdict, "before": previous, "after": case})
    return out


def describe(entry: dict[str, Any]) -> str:
    if entry["verdict"] == "NEW":
        return f"{entry['id']}: NEW"
    before, after = entry["before"], entry["after"]
    was = f"{before['level']}{'*' if before['automatic'] else ''}"
    now = f"{after['level']}{'*' if after['automatic'] else ''}"
    lines = [f"{entry['id']}  [{entry['verdict']}]  {was} -> {now}"]
    removed = sorted(
        set(before["observed_mapping"].items()) - set(after["observed_mapping"].items())
    )
    added = sorted(set(after["observed_mapping"].items()) - set(before["observed_mapping"].items()))
    for field, text in removed:
        lines.append(f"    - {field}: {text}")
    for field, text in added:
        lines.append(f"    + {field}: {text}")
    if before["questions_asked"] != after["questions_asked"]:
        lines.append(f"    questions {before['questions_asked']} -> {after['questions_asked']}")
    lost = {(f["severity"], f["category"], f["detail"]) for f in before["findings"]} - {
        (f["severity"], f["category"], f["detail"]) for f in after["findings"]
    }
    new = {(f["severity"], f["category"], f["detail"]) for f in after["findings"]} - {
        (f["severity"], f["category"], f["detail"]) for f in before["findings"]
    }
    for severity, category, detail in sorted(lost):
        lines.append(f"    fixed   {severity} {category}: {detail[:90]}")
    for severity, category, detail in sorted(new):
        lines.append(f"    NEW     {severity} {category}: {detail[:90]}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    before = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    after = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    entries = compare(before, after)
    total = len(after["cases"])
    counts = {
        v: sum(1 for e in entries if e["verdict"] == v)
        for v in ("IMPROVED", "WORSE", "CHANGED", "NEW")
    }
    print(
        f"{total} cases: identical {total - len(entries)}, "
        + ", ".join(f"{k} {v}" for k, v in counts.items())
    )
    for entry in sorted(
        entries, key=lambda e: ("WORSE", "CHANGED", "IMPROVED", "NEW").index(e["verdict"])
    ):
        print()
        print(describe(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

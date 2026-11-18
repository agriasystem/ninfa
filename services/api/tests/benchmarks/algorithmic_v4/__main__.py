"""python -m tests.benchmarks.algorithmic_v4   (from services/api; a few minutes, no network)

Smart Import V4.1: is the algorithmic reader better than the one in production, and no less safe?

The SAME documents are read by each engine - `v3` (the greedy reader in production), and V4 with
more and more of its parts (`v4-header`: vocabulary + RapidFuzz; `v4-values`: + value proof,
negative
evidence and relations; `v4`: + the global assignment) - through the real understanding service,
with
no database, no model, nothing leaving the process. Every number is computed by the benchmark's own
scorer (`score_case`) from truth written next to each file; none of it is read from the engine.

Populations:

    official     the 240 documents Smart Import V3 was hardened on (the regression guard)
    unseen       the 360 positive documents of the Universal Understanding benchmark (`dev` was
                 looked at while V3 improved, `holdout` was not: reported apart)
    challenge    the official READY workbooks with one or two headers replaced by a word the rules
                 do not know (the held-out vocabulary) - where reading WORDS can add value
    adversarial  hand-built hostile files: wrong card, prompt injection, personal data in a header
    problem      the V4 problem corpus (`problem_corpus.py`): plausible headers that are no
                 importer's own name (reservation_code, BookingStatus, checkindate, Arival Date...)

Hard requirements (a failure of any is a blocker, whatever the recall): unsafe READY = 0, wrong-
domain
READY = 0, scope violations = 0, no engine exception, no personal value in what the browser is sent.
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.modules.data_sources.algorithmic.selector import ENGINES, use_engine
from tests.benchmarks.algorithmic_v4.problem_corpus import (
    build_problem_corpus,
    build_single_typo_corpus,
)
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.openai_intelligence import (
    Outcome,
    adversarial_docs,
    challenge_docs,
    measure,
    run_config,
    score_all,
)
from tests.benchmarks.smart_import_v3.score import CaseResult
from tests.benchmarks.universal_understanding_v2 import corpus as uu2

POPULATIONS = ("official", "unseen_dev", "unseen_holdout", "challenge", "adversarial", "problem")
# measured separately, added after the first V4 results (see problem_corpus.SINGLE_TYPOS)
EXTRA_POPULATIONS = ("single_typo",)
SAFETY = (
    "unsafe_ready",
    "wrong_domain_ready",
    "scope_violations",
    "false_automation",
    "certain_and_wrong",
    "pii_values_in_the_browser_answer",
    "p0_findings",
)


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def documents(name: str, cache: dict[str, list[Doc]]) -> list[Doc]:
    if name in cache:
        return cache[name]
    if name == "official":
        docs = build_corpus()
    elif name in {"unseen_dev", "unseen_holdout"}:
        wanted = "dev" if name.endswith("dev") else "holdout"
        docs = [d for d in uu2.build_corpus() if uu2.is_positive(d) and uu2.split_of(d) == wanted]
    elif name == "challenge":
        docs = challenge_docs(documents("official", cache), 2)
    elif name == "adversarial":
        docs = adversarial_docs()
    elif name == "problem":
        docs = build_problem_corpus()
    elif name == "single_typo":
        docs = build_single_typo_corpus()
    else:
        raise SystemExit(f"unknown population {name}")
    cache[name] = docs
    return docs


def timed(docs: Sequence[Doc], engine: str) -> tuple[dict[str, Outcome], list[float]]:
    """Read every document with one engine (each document alone, so each has its own time)."""
    outcomes: dict[str, Outcome] = {}
    seconds: list[float] = []
    with use_engine(engine):
        for doc in docs:
            started = time.perf_counter()
            outcomes.update(run_config([doc], "deterministic"))
            seconds.append(time.perf_counter() - started)
    return outcomes, seconds


def per_document(
    docs: Sequence[Doc], outcomes: dict[str, Outcome], scored: dict[str, CaseResult]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for doc in docs:
        case, observed = scored[doc.id], outcomes[doc.id].observed
        out[doc.id] = {
            "level": case.level,
            "questions": len(case.questions_asked),
            "unnecessary": case.questions_unnecessary,
            "correct": case.everything.correct,
            "wrong": case.everything.wrong,
            "missed": case.everything.missed,
            "golden": case.everything.golden,
            "false_automation": bool(case.false_automation),
            "error": observed.error,
            "kind": next((t for t in doc.tags if t in KINDS), None),
        }
    return out


KINDS = ("plain", "camel", "glued", "typo", "qualifier", "unnamed", "personal")


def latency(seconds: Sequence[float]) -> dict[str, float]:
    ms = sorted(s * 1000 for s in seconds)
    if not ms:
        return {}
    return {
        "mean_ms": round(statistics.mean(ms), 1),
        "p50_ms": round(ms[len(ms) // 2], 1),
        "p95_ms": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1),
        "max_ms": round(ms[-1], 1),
    }


def run_population(
    name: str, engines: Sequence[str], cache: dict[str, list[Doc]]
) -> dict[str, Any]:
    docs = documents(name, cache)
    say(f"{name}: {len(docs)} documents")
    runs: dict[str, tuple[dict[str, Outcome], dict[str, CaseResult], list[float]]] = {}
    for engine in engines:
        say(f"  engine {engine}")
        outcomes, seconds = timed(docs, engine)
        runs[engine] = (outcomes, score_all(docs, outcomes), seconds)
    base_outcomes, base_scored, _ = runs[engines[0]]
    result: dict[str, Any] = {"documents": len(docs), "engines": {}}
    for engine in engines:
        outcomes, scored, seconds = runs[engine]
        metrics = measure(docs, outcomes, scored, base_outcomes, base_scored)
        errors = sum(1 for d in docs if outcomes[d.id].observed.error)
        by_doc = per_document(docs, outcomes, scored)
        result["engines"][engine] = {
            "metrics": metrics,
            "errors": errors,
            "latency": latency(seconds),
            "ready": metrics["levels"].get("READY", 0),
            "per_document": by_doc,
            "unsafe_ready_ids": [
                d.id
                for d in docs
                if scored[d.id].level == "READY"
                and (
                    scored[d.id].false_automation
                    or scored[d.id].everything.wrong
                    or scored[d.id].junk_mapped
                )
            ],
        }
    return result


def table(population: dict[str, Any], engines: Sequence[str]) -> list[str]:
    rows: tuple[tuple[str, Callable[[Any], Any]], ...] = (
        ("documents", lambda e: population["documents"]),
        ("mapping recall", lambda e: e["metrics"]["mapping_recall"]),
        ("claims precision", lambda e: e["metrics"]["claims_precision"]),
        ("READY", lambda e: e["ready"]),
        ("asking (ASK)", lambda e: e["metrics"]["asking"]),
        ("manual matching", lambda e: e["metrics"]["manual_matching"]),
        ("questions asked", lambda e: e["metrics"]["questions_asked"]),
        ("unnecessary questions", lambda e: e["metrics"]["questions_unnecessary"]),
        ("unsafe READY", lambda e: e["metrics"]["unsafe_ready"]),
        ("wrong-domain READY", lambda e: e["metrics"]["wrong_domain_ready"]),
        ("scope violations", lambda e: e["metrics"]["scope_violations"]),
        ("false automation", lambda e: e["metrics"]["false_automation"]),
        ("certain and wrong", lambda e: e["metrics"]["certain_and_wrong"]),
        ("PII in browser answer", lambda e: e["metrics"]["pii_values_in_the_browser_answer"]),
        ("engine errors", lambda e: e["errors"]),
        ("latency mean ms", lambda e: e["latency"].get("mean_ms")),
        ("latency p95 ms", lambda e: e["latency"].get("p95_ms")),
    )
    lines = ["| metric | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for label, pick in rows:
        cells = []
        for engine in engines:
            data = population["engines"][engine]
            value = pick(population) if label == "documents" else pick(data)
            cells.append(
                "-"
                if value is None
                else (f"{value:.4f}" if isinstance(value, float) and value < 1.5 else str(value))
            )
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def kinds_table(population: dict[str, Any], engines: Sequence[str]) -> list[str]:
    counts: dict[str, dict[str, Counter[str]]] = {}
    for engine in engines:
        for record in population["engines"][engine]["per_document"].values():
            kind = record["kind"] or "other"
            counts.setdefault(kind, {}).setdefault(engine, Counter())[str(record["level"])] += 1
    lines = ["| kind | engine | READY | ASK | MANUAL | BLOCKED |", "|---|---|---|---|---|---|"]
    for kind in sorted(counts):
        for engine in engines:
            c = counts[kind].get(engine, Counter())
            lines.append(
                f"| {kind} | {engine} | {c['READY']} | {c['ASK']} | {c['MANUAL']} "
                f"| {c['BLOCKED']} |"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.algorithmic_v4")
    parser.add_argument("--populations", default=",".join(POPULATIONS))
    parser.add_argument("--engines", default=",".join(ENGINES))
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    names = [p.strip() for p in args.populations.split(",") if p.strip()]
    cache: dict[str, list[Doc]] = {}
    report: dict[str, Any] = {"engines": engines, "populations": {}}
    for name in names:
        report["populations"][name] = run_population(name, engines, cache)
    for name, population in report["populations"].items():
        print(f"\n## {name}\n")
        print("\n".join(table(population, engines)))
        if name == "problem":
            print("\n" + "\n".join(kinds_table(population, engines)))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    broken = [
        (name, engine)
        for name, population in report["populations"].items()
        for engine, data in population["engines"].items()
        if engine != "v3"
        and any(
            data["metrics"][key]
            for key in ("unsafe_ready", "wrong_domain_ready", "scope_violations")
        )
    ]
    if broken:
        say(f"SAFETY BLOCKER: {broken}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

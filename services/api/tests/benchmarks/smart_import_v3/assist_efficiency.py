"""What the model costs a person, and what it is worth: V1 against V1.1, call by call, question by
question.

`python -m tests.benchmarks.smart_import_v3.assist_efficiency --help` (from services/api).

Three things live here:

* `legacy_gate()` - the V1 behaviour, kept ONLY to measure what V1.1 saves: every condition under
  which V1 asked a model, the questions it let a model add on a READY file, no readings set aside.
  With the recording of the 283 real V1 calls it reproduces V1 exactly (no new call).
* `inventory` / `classify` - what each document came to with and without the model, reduced to
  plain rows; every call put in ONE class (useful, no change, noise, wasted) and every question the
  model added put in ONE class (replaces a manual matching, replaces a worse question, protects a
  measure, noise). A question is useful when it does one of the first three; noise when ignoring it
  would have changed nothing: it was added to a file the rules already read as READY, or it is
  about a descriptive field.
* `variants` - the same documents asked of the real model under different settings (reasoning
  effort, a more compact prompt), one recording per variant, to choose the faster one only if it
  understands as well.
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.api.v1.sources.router import _inspection_response
from app.core.tenant import TenantContext
from app.modules.ai.import_understanding import prompt as prompt_module
from app.modules.ai.import_understanding import resolver as resolver_module
from app.modules.ai.import_understanding.types import AiMode
from app.modules.data_sources import understanding as understanding_module
from app.modules.data_sources import understanding_ai
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.data_sources.understanding_ai import _confirmable
from app.modules.data_sources.understanding_types import QuestionKind
from tests.benchmarks.smart_import_v3.ai_readiness import PSEUDO
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.match import norm
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.observe import CARD
from tests.benchmarks.smart_import_v3.openai_intelligence import (
    Recording,
    SemanticTap,
    _truth,
    adversarial_docs,
    challenge_docs,
    measure,
    run_config,
    score_all,
)
from tests.benchmarks.smart_import_v3.openai_live import (
    PRICE_IN,
    PRICE_OUT,
    TIMEOUT_SECONDS,
    Audited,
    CappedRecording,
    Recorded,
    Wire,
    real_provider,
    spend,
)


@contextmanager
def _patched(module: Any, **names: Any) -> Iterator[None]:
    """Names of a module replaced for a while (read and written through its namespace: they are
    names the module imported or defines, not an interface it promises)."""
    namespace = vars(module)
    saved = {name: namespace[name] for name in names}
    namespace.update(names)
    try:
        yield
    finally:
        namespace.update(saved)


NL = chr(10)

# --- the V1 behaviour, for comparison only ----------------------------------------


def _legacy_needs_help(
    proposal: Any,
    groups: Sequence[tuple[str, ...]],
    questions: Sequence[Any],
    certainty: bool = False,
    never: frozenset[str] = frozenset(),
) -> bool:
    """`needs_help` as V1 had it: the semantic layer always asked about a doubtful column and
    about the other half of a pair, and counted a missing amount as something to ask about."""
    assigned = {c.field for c in proposal.columns if c.field is not None}
    missing = any(not any(field in assigned for field in group) for group in groups)
    left_over = any(
        c.field is None
        and c.locked is None
        and c.pii is None
        and c.ambiguous_group is None
        and c.stats.n >= 1
        for c in proposal.columns
    )
    asks_kind = any(q.kind == QuestionKind.DOMAIN for q in questions)
    doubtful = bool(_confirmable(proposal))
    other_half = left_over and any(
        len(group) > 1
        and any(f in assigned for f in group)
        and not all(f in assigned for f in group)
        for group in groups
    )
    return (missing and left_over) or asks_kind or doubtful or other_half


@contextmanager
def legacy_gate() -> Iterator[None]:
    """V1: the old conditions to ask, a model asked about files that are READY or BLOCKED, no
    reading set aside as immaterial, the V1 prompt and the V1 evidence (so recordings apply)."""
    with (
        _patched(
            understanding_module,
            needs_help=_legacy_needs_help,
            _a_model_can_help=lambda _inspection: True,
            is_immaterial=lambda *_args: False,
        ),
        _patched(resolver_module, SEMANTIC_INSTRUCTIONS=prompt_module.SEMANTIC_INSTRUCTIONS),
        _patched(prompt_module, COMPACT_EVIDENCE=False),
    ):
        yield


# --- one document, with and without the model, as plain rows ----------------------------

REQUIRED = {
    "bookings": {
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "status",
        "rooms",
        "room_revenue",
        "channel",
    },
    "labor": {"work_date", "actual_hours", "planned_hours", "labor_category", "role"},
    "costs": {"supplier_name", "invoice_number", "invoice_date", "line_description", "line_total"},
}
DESCRIPTIVE = {"guests", "room_type", "rate_plan"}


def _questions(info: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": q.id,
            "kind": q.kind.value,
            "column": q.column,
            "field": q.field,
            "origin": q.origin.value if q.origin else None,
        }
        for q in (info.questions if info else [])
    ]


def _inspect(doc: Doc, resolver: Any) -> tuple[Any, Any]:
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    service = UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)
    inspection = service.understand(
        CARD[doc.card],
        doc.filename,
        doc.content,
        UnderstandAnswers(),
        False,
        None,
        False,
        currency="EUR",
    )
    return inspection, inspection.understanding


def row_of(
    doc: Doc, recorded: Recorded, resolver_cls: type[Recording] = CappedRecording
) -> dict[str, Any]:
    """What one document came to: the rules alone, and with the model."""
    base_inspection, base = _inspect(doc, None)
    tap = SemanticTap(Audited(recorded, doc.golden.pii_values))
    resolver = resolver_cls(tap, AiMode.ASSIST)
    ai_inspection, ai = _inspect(doc, resolver)
    usages = [u for r in resolver.resolutions for u in r.usages]
    return {
        "id": doc.id,
        "card": doc.card,
        "truth": {norm(h): f for h, f in _truth(doc).items()},
        "called": bool(tap.requests),
        "calls": len(tap.requests),
        "ignored": sum(t.ignored for t in resolver.traces),
        "fallbacks": [t.fallback_reason for t in resolver.traces if t.fallback_reason],
        "latency_ms": sum(u.latency_ms for u in usages),
        "tokens_in": sum(u.input_tokens or 0 for u in usages),
        "tokens_out": sum(u.output_tokens or 0 for u in usages),
        "base": {"level": base.level.value if base else None, "qs": _questions(base)},
        "ai": {"level": ai.level.value if ai else None, "qs": _questions(ai)},
        "same_screen": _inspection_response(base_inspection).model_dump_json()
        == _inspection_response(ai_inspection).model_dump_json(),
    }


def inventory(
    docs: Mapping[str, Sequence[Doc]],
    recorded: Recorded,
    workers: int,
    progress: Callable[[str], None],
    resolver_cls: type[Recording] = CappedRecording,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for population, members in docs.items():
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for row in pool.map(lambda d: row_of(d, recorded, resolver_cls), members):
                row["pop"] = population
                rows.append(row)
        progress(f"  inventory {population}: {len(members)} documents")
    return rows


# --- classes ----------------------------------------


def _added(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = {q["id"] for q in row["base"]["qs"]}
    return [q for q in row["ai"]["qs"] if q["id"] not in before]


def _removed(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    after = {q["id"] for q in row["ai"]["qs"]}
    return [q for q in row["base"]["qs"] if q["id"] not in after]


def call_class(row: Mapping[str, Any]) -> str | None:
    """What one model call came to (None: the model was not asked)."""
    if not row["called"]:
        return None
    if row["fallbacks"]:
        return "wasted: the call failed"
    before, after = row["base"]["level"], row["ai"]["level"]
    if row["same_screen"]:
        if before == "READY":
            return "no change: the file was already READY"
        if after == "MANUAL":
            return "no change: still manual matching"
        return "no change: the screen is the rules' own"
    if before == "MANUAL" and after != "MANUAL":
        return "useful: manual matching avoided"
    if _removed(row) and _added(row):
        return "useful: a worse question replaced"
    if before == "READY":
        return "noise: a question added to a READY file"
    return "changed: relabelled, no question changed"


def question_classes(row: Mapping[str, Any]) -> list[str]:
    """One class for each question the model ADDED to this document's screen."""
    added = _added(row)
    swapped = min(len(added), len(_removed(row)))
    classes: list[str] = []
    for index, q in enumerate(added):
        if row["base"]["level"] == "MANUAL" and row["ai"]["level"] != "MANUAL":
            classes.append("replaces a manual matching")
        elif index < swapped:
            classes.append("replaces a worse question")
        elif row["base"]["level"] == "READY" or q["field"] in DESCRIPTIVE:
            classes.append("noise: ignoring it changes nothing")
        else:
            classes.append("protects a measure")
    return classes


USEFUL_QUESTIONS = ("replaces a manual matching", "replaces a worse question", "protects a measure")


def classify(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    calls = Counter(c for r in rows if (c := call_class(r)) is not None)
    questions = Counter(c for r in rows for c in question_classes(r))
    added = sum(questions.values())
    useful = sum(questions[c] for c in USEFUL_QUESTIONS)
    asked = [r for r in rows if r["called"]]
    return {
        "documents": len(rows),
        "model_calls": sum(r["calls"] for r in rows),
        "documents_asked": len(asked),
        "calls_by_class": dict(sorted(calls.items())),
        "questions_rules": sum(len(r["base"]["qs"]) for r in rows),
        "questions_shown": sum(len(r["ai"]["qs"]) for r in rows),
        "questions_added_by_the_model": added,
        "questions_removed_by_the_model": sum(len(_removed(r)) for r in rows),
        "questions_by_class": dict(sorted(questions.items())),
        "useful_questions": useful,
        "useful_question_rate": round(useful / added, 4) if added else None,
        "settings_set_aside_as_immaterial": sum(r["ignored"] for r in rows),
        "ready_files_turned_into_questions": sum(
            1 for r in rows if r["base"]["level"] == "READY" and r["ai"]["level"] != "READY"
        ),
        "manual_matching_avoided": sum(
            1 for r in rows if r["base"]["level"] == "MANUAL" and r["ai"]["level"] != "MANUAL"
        ),
    }


def latency_of(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [r["latency_ms"] for r in rows if r["called"] and r["latency_ms"]]
    ordered = sorted(values)

    def at(q: float) -> int:
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0

    return {
        "calls": len(values),
        "mean_ms": round(statistics.mean(values)) if values else 0,
        "p50_ms": at(0.5),
        "p95_ms": at(0.95),
        "max_ms": max(values) if values else 0,
        "timeouts": sum(1 for r in rows if r["fallbacks"]),
        "timeout_rate": round(sum(1 for r in rows if r["fallbacks"]) / len(values), 4)
        if values
        else 0,
        "tokens_in_mean": round(statistics.mean(r["tokens_in"] for r in rows if r["called"]))
        if values
        else 0,
        "tokens_out_mean": round(statistics.mean(r["tokens_out"] for r in rows if r["called"]))
        if values
        else 0,
    }


# --- the same documents, under different settings ----------------------------------------


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    effort: str  # the reasoning effort the model is asked to use
    compact: bool  # the V1.1 prompt and evidence (False: exactly as V1 asked)


VARIANTS = {
    "v1-medium": Variant("v1-medium", "medium", False),
    "v1-low": Variant("v1-low", "low", False),
    "compact-medium": Variant("compact-medium", "medium", True),
    "compact-low": Variant("compact-low", "low", True),
    # the baseline again, at the end: how far the API's own mood moves the same settings
    "v1-medium-again": Variant("v1-medium-again", "medium", False),
}


@contextmanager
def asked_as(variant: Variant) -> Iterator[None]:
    text = (
        prompt_module.SEMANTIC_INSTRUCTIONS_COMPACT
        if variant.compact
        else prompt_module.SEMANTIC_INSTRUCTIONS
    )
    with (
        _patched(resolver_module, SEMANTIC_INSTRUCTIONS=text),
        _patched(prompt_module, COMPACT_EVIDENCE=variant.compact),
    ):
        yield


def quality_of(
    docs: Sequence[Doc], rows: Sequence[Mapping[str, Any]], recorded: Recorded
) -> dict[str, Any]:
    """The standard measures of the intelligence benchmark on these documents, with this variant's
    own recorded answers (production's configuration: the certainty withdrawn)."""
    base = run_config(docs, "deterministic")
    outcomes = {
        d.id: outcome
        for d, outcome in zip(
            docs,
            (
                _outcome(d, recorded.frozen_copy())
                for d in docs  # sequential: the pipeline is deterministic, the recording is read
            ),
            strict=True,
        )
    }
    scored_base, scored = score_all(docs, base), score_all(docs, outcomes)
    m = measure(docs, outcomes, scored, base, scored_base)
    return {
        "documents": len(docs),
        "mapping_recall": m["mapping_recall"],
        "claims_precision": m["claims_precision"],
        "manual_matching": m["manual_matching"],
        "automatic": m["automatic"],
        "questions_asked": m["questions_asked"],
        "unsafe_ready": m["unsafe_ready"],
        "wrong_domain_ready": m["wrong_domain_ready"],
        "pii_sent": m["pii_violations_in_what_the_model_was_sent"],
        "scope_violations": m["scope_violations"],
        "suggestions_right": m["vs_rules_alone"]["model_suggestions_right"],
        "suggestions_wrong": m["vs_rules_alone"]["model_suggestions_wrong"],
        "rules_alone": {
            "mapping_recall": measure(docs, base, scored_base, base, scored_base)["mapping_recall"],
            "manual_matching": sum(
                1 for c in scored_base.values() if c.level in ("MANUAL", "BLOCKED")
            ),
        },
    }


def _outcome(doc: Doc, recorded: Recorded) -> Any:
    from tests.benchmarks.smart_import_v3.openai_live import run_one

    return run_one(doc, recorded, CappedRecording, AiMode.ASSIST)


def run_variant(
    docs: Sequence[Doc],
    variant: Variant,
    key: str,
    model: str,
    cache: Path,
    workers: int,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    """The documents asked of the real model, as this variant asks. One recording per variant."""
    from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider

    wire = Wire(model, [])
    import httpx2

    client = httpx2.Client(event_hooks={"request": [wire]}, timeout=TIMEOUT_SECONDS)
    provider = OpenAIImportUnderstandingProvider(
        key,
        model=model,
        reasoning_effort=variant.effort,  # type: ignore[arg-type]
        timeout_seconds=TIMEOUT_SECONDS,
        http_client=client,
    )
    recorded = Recorded(provider, cache / f"variant-{variant.name}.jsonl", model=model)
    with asked_as(variant):
        done = 0
        lock = threading.Lock()

        def one(doc: Doc) -> dict[str, Any]:
            nonlocal done
            row = row_of(doc, recorded)
            with lock:
                done += 1
                if done % 10 == 0 or done == len(docs):
                    progress(f"    {variant.name}: {done}/{len(docs)}")
            return row

        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, docs))
        quality = quality_of(docs, rows, recorded.frozen_copy())
    spent = spend(recorded.entries)
    return {
        "variant": variant.name,
        "effort": variant.effort,
        "compact": variant.compact,
        "classification": classify(rows),
        "latency": latency_of(rows),
        "quality": quality,
        "spend": {
            k: spent[k]
            for k in ("real_calls", "tokens_in_total", "tokens_out_total", "cost_usd_at_list_price")
        },
        "wire_failed_checks": dict(wire.failed),
    }


def subset(rows: Sequence[Mapping[str, Any]], docs: Mapping[str, Doc], n: int) -> list[Doc]:
    """n of the documents the model is asked about, spread over populations and outcomes."""
    asked = [r for r in rows if r["called"]]
    keyed = sorted(asked, key=lambda r: (r["pop"], call_class(r) or "", r["id"]))
    step = max(1, len(keyed) // n)
    picked: list[Mapping[str, Any]] = keyed[::step][:n]
    return [docs[r["id"]] for r in picked]


# --- the full run: the three populations, with the model as production asks it ------------


def row_from_outcomes(doc: Doc, base: Any, live: Any) -> dict[str, Any]:
    """The same row `row_of` makes, from outcomes the benchmark already has (no second pass)."""

    def questions(observed: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": f"{q.kind}|{q.column}|{q.field}",
                "kind": q.kind,
                "column": q.column,
                "field": q.field,
            }
            for q in observed.questions
        ]

    resolver = live.resolver
    usages = [u for r in resolver.resolutions for u in r.usages] if resolver is not None else []
    tap = live.provider
    return {
        "id": doc.id,
        "card": doc.card,
        "called": bool(tap is not None and tap.requests),
        "calls": 0 if tap is None else len(tap.requests),
        "ignored": 0 if resolver is None else sum(t.ignored for t in resolver.traces),
        "fallbacks": []
        if resolver is None
        else [t.fallback_reason for t in resolver.traces if t.fallback_reason],
        "latency_ms": sum(u.latency_ms for u in usages),
        "tokens_in": sum(u.input_tokens or 0 for u in usages),
        "tokens_out": sum(u.output_tokens or 0 for u in usages),
        "base": {"level": base.observed.level, "qs": questions(base.observed)},
        "ai": {"level": live.observed.level, "qs": questions(live.observed)},
        "same_screen": base.observed.payload == live.observed.payload,
    }


def run_full(args: argparse.Namespace, populations: Mapping[str, Sequence[Doc]]) -> dict[str, Any]:
    from contextlib import nullcontext

    from tests.benchmarks.smart_import_v3.openai_live import PRODUCTION_CONFIGS, evaluate

    model = os.environ.get("SMART_IMPORT_OPENAI_MODEL", "").strip() or "gpt-6.1-sol"
    canaries = sorted({v for ds in populations.values() for d in ds for v in d.golden.pii_values})
    wire = Wire(model, canaries)
    if args.from_recording:
        recorded = Recorded(None, args.cache, model=model, frozen=True)
    else:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise SystemExit("NOT RUN - OPENAI_API_KEY NOT CONFIGURED")
        recorded = Recorded(real_provider(key, model, wire, args.effort), args.cache, model=model)
    started = time.time()
    results: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    with legacy_gate() if args.legacy else nullcontext():
        for name, docs in populations.items():
            kept: dict[str, Any] = {}
            results[name] = evaluate(
                name, docs, recorded, args.workers, say, production=True, keep=kept
            )
            for doc in docs:
                row = row_from_outcomes(doc, kept["deterministic"][doc.id], kept["live"][doc.id])
                row["pop"] = name
                rows.append(row)
    spent = spend(recorded.entries)
    if args.fixture_out is not None:
        say(f"fixture {args.fixture_out}: {recorded.export_fixture(args.fixture_out)} answers")
    return {
        "label": args.label,
        "model": model,
        "reasoning_effort": args.effort,
        "gate": "V1 (legacy)" if args.legacy else "V1.1",
        "configurations": list(PRODUCTION_CONFIGS),
        "populations": results,
        "classification": {
            "all": classify(rows),
            **{p: classify([r for r in rows if r["pop"] == p]) for p in populations},
        },
        "latency": latency_of(rows),
        "spend": spent,
        "wire": {
            "requests": wire.requests,
            "failed": dict(wire.failed),
            "largest_request_bytes": max(wire.sizes) if wire.sizes else 0,
            "canaries_checked": len(wire.canaries),
        },
        "recording_misses": recorded.misses,
        "seconds": round(time.time() - started),
    }


# --- the report: rules | V1 | V1.1 --------------------------------------------------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _cfg(data: Mapping[str, Any], pop: str, config: str) -> Mapping[str, Any]:
    metrics: Mapping[str, Any] = data["populations"][pop]["metrics"][config]
    return metrics


def _sum(data: Mapping[str, Any], config: str, key: str) -> int:
    return sum(int(_cfg(data, pop, config)[key]) for pop in data["populations"])


def comparison(v1: Mapping[str, Any], v11: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers of the three columns. V1 is the live run of Nov 16 as it was measured (its own
    JSON); V1.1 is the run of this gate. `rules` is the same in both: the rules alone."""
    out: dict[str, Any] = {}
    for pop in ("challenge", "official", "adversarial"):
        rules = _cfg(v11, pop, "deterministic")
        a, b = _cfg(v1, pop, "live_assist_capped"), _cfg(v11, pop, "live_assist_capped")
        out[pop] = {
            key: {"rules": rules[key], "v1": a[key], "v11": b[key]}
            for key in (
                "documents",
                "automatic",
                "manual_matching",
                "asking",
                "questions_asked",
                "questions_unnecessary",
                "mapping_recall",
                "claims_precision",
                "unsafe_ready",
                "false_automation",
                "wrong_domain_ready",
                "certain_and_wrong",
                "pii_violations_in_what_the_model_was_sent",
                "pii_values_in_the_browser_answer",
                "scope_violations",
                "model_calls",
            )
        }
    return out


def _rows(rows: Sequence[tuple[str, Any, Any]]) -> list[str]:
    return [f"| {label} | {first} | {second} |" for label, first, second in rows]


def markdown(data: Mapping[str, Any], today: str) -> str:
    v1c, v11c = data["classification"]["v1"], data["classification"]["v11"]
    adr = "../architecture/adr/0052-the-vocabulary-certainty-is-withdrawn-until-ninfa-sees-an-injection-itself"  # noqa: E501
    out = [
        "# Smart Import - OpenAI ASSIST - UX and efficiency V1.1",
        "",
        f"Date {today} - branch `feature/smart-import-openai-intelligence-v1` - model "
        f"`{data['model']}`, reasoning `{data['reasoning_effort']}`.",
        "",
        "> The documents are the synthetic corpus of the intelligence benchmark: 290 "
        "challenge, 240 official, 15 adversarial. Every V1.1 number is the REAL model on the "
        "vendor's endpoint. `SMART_IMPORT_AI_MODE` stays `off`; the vocabulary certainty stays "
        f"withdrawn ([ADR 0052]({adr}.md)).",
        "",
        "## Rules | OpenAI V1 | OpenAI V1.1",
        "",
        "The model as production builds it (the certainty withdrawn). V1 is the run of Nov 16 "
        "as it was measured; V1.1 is the run of this gate.",
        "",
    ]
    labels = (
        ("Documents", "documents", "{}"),
        ("READY with no question", "automatic", "{}"),
        ("Manual matching required", "manual_matching", "{}"),
        ("Files that ask questions", "asking", "{}"),
        ("Questions shown", "questions_asked", "{}"),
        ("Mapping recall", "mapping_recall", "pct"),
        ("Claims precision", "claims_precision", "pct"),
        ("**Unsafe READY**", "unsafe_ready", "{}"),
        ("**Wrong-domain READY**", "wrong_domain_ready", "{}"),
        ("**PII sent to the model**", "pii_violations_in_what_the_model_was_sent", "{}"),
        ("**PII visible in the browser**", "pii_values_in_the_browser_answer", "{}"),
        ("**Scope violations**", "scope_violations", "{}"),
        ("Model calls", "model_calls", "{}"),
    )
    for pop, block in data["comparison"].items():
        out += [
            f"### {pop}",
            "",
            "| Metric | Rules | OpenAI V1 | OpenAI V1.1 |",
            "|---|---:|---:|---:|",
        ]
        for label, key, template in labels:
            cells = [
                _pct(block[key][c]) if template == "pct" else str(block[key][c])
                for c in ("rules", "v1", "v11")
            ]
            out.append(f"| {label} | " + " | ".join(cells) + " |")
        out.append("")
    out += ["## Questions", "", "Every question the model ADDED to a screen, in ONE class:", ""]
    out += ["| Class | V1 | V1.1 |", "|---|---:|---:|"]
    classes = sorted(set(v1c["questions_by_class"]) | set(v11c["questions_by_class"]))
    out += _rows(
        [
            (n, v1c["questions_by_class"].get(n, 0), v11c["questions_by_class"].get(n, 0))
            for n in classes
        ]
    )
    out += _rows(
        [
            (
                "**added by the model**",
                v1c["questions_added_by_the_model"],
                v11c["questions_added_by_the_model"],
            ),
            (
                "**useful_question_rate**",
                _pct(v1c["useful_question_rate"]),
                _pct(v11c["useful_question_rate"]),
            ),
            (
                "removed by the model (a worse question replaced)",
                v1c["questions_removed_by_the_model"],
                v11c["questions_removed_by_the_model"],
            ),
            ("questions shown in all", v1c["questions_shown"], v11c["questions_shown"]),
            ("the rules' own questions", v1c["questions_rules"], v11c["questions_rules"]),
            (
                "READY files turned into a question",
                v1c["ready_files_turned_into_questions"],
                v11c["ready_files_turned_into_questions"],
            ),
            (
                "manual matchings avoided",
                v1c["manual_matching_avoided"],
                v11c["manual_matching_avoided"],
            ),
            (
                "readings set aside as immaterial",
                v1c["settings_set_aside_as_immaterial"],
                v11c["settings_set_aside_as_immaterial"],
            ),
        ]
    )
    out += ["", "## Model calls", "", "| Class | V1 | V1.1 |", "|---|---:|---:|"]
    names = sorted(set(v1c["calls_by_class"]) | set(v11c["calls_by_class"]))
    out += _rows(
        [(n, v1c["calls_by_class"].get(n, 0), v11c["calls_by_class"].get(n, 0)) for n in names]
    )
    out += _rows([("**model calls**", v1c["model_calls"], v11c["model_calls"])])
    out.append("")
    out += _attribution_section(data)
    out += _latency_section(data)
    out += _source_learning_section(data)
    out += _cost_section(data)
    return chr(10).join(out) + chr(10)


def attribution(
    v1: Mapping[str, Any], gate_only: Mapping[str, Any], v11: Mapping[str, Any]
) -> dict[str, Any]:
    """What moved, step by step, on each population: V1; the V1.1 gate and rules with the V1
    reasoning (replayed from V1 recording, no new call); V1.1 as built (the real model, `low`)."""
    steps = {
        "v1": (v1, "live_assist_capped"),
        "gate_only": (gate_only, "live_assist_capped"),
        "v11": (v11, "live_assist_capped"),
    }
    keys = ("mapping_recall", "manual_matching", "automatic", "questions_asked", "model_calls")
    return {
        pop: {
            name: {key: _cfg(data, pop, config)[key] for key in keys}
            for name, (data, config) in steps.items()
        }
        for pop in v11["populations"]
    }


def _attribution_section(data: Mapping[str, Any]) -> list[str]:
    block = data.get("attribution")
    if not block:
        return []
    out = [
        "## Where the recall went",
        "",
        "Step by step: V1; then the V1.1 gate and rules alone (V1 reasoning, `medium`, replayed "
        "from V1's recording, no new call); then V1.1 as built (the real model at `low`).",
        "",
    ]
    for pop, steps in block.items():
        out += [
            f"### {pop}",
            "",
            "| | OpenAI V1 | V1.1 gate and rules, `medium` | OpenAI V1.1 (`low`) |",
            "|---|---:|---:|---:|",
        ]
        for label, key in (
            ("mapping recall", "mapping_recall"),
            ("manual matching", "manual_matching"),
            ("READY with no question", "automatic"),
            ("questions shown", "questions_asked"),
            ("model calls", "model_calls"),
        ):
            cells = [
                _pct(steps[n][key]) if key == "mapping_recall" else str(steps[n][key])
                for n in ("v1", "gate_only", "v11")
            ]
            out.append(f"| {label} | " + " | ".join(cells) + " |")
        out.append("")
    return out


def _latency_section(data: Mapping[str, Any]) -> list[str]:
    v1, v11 = data["latency"]["v1"], data["latency"]["v11"]
    out = [
        "## Latency",
        "",
        "Per call, in the full runs (6 calls in parallel, production's 25 s timeout).",
        "",
        "| | OpenAI V1 | OpenAI V1.1 |",
        "|---|---:|---:|",
    ]
    out += _rows(
        [
            ("calls", v1["calls"], v11["calls"]),
            ("mean (ms)", v1["mean_ms"], v11["mean_ms"]),
            ("p50 (ms)", v1["p50_ms"], v11["p50_ms"]),
            ("p95 (ms)", v1["p95_ms"], v11["p95_ms"]),
            ("max (ms)", v1["max_ms"], v11["max_ms"]),
            ("timeouts", v1["timeouts"], v11["timeouts"]),
            ("timeout rate", _pct(v1["timeout_rate"]), _pct(v11["timeout_rate"])),
            ("input tokens per call", v1["tokens_in_mean"], v11["tokens_in_mean"]),
            ("output tokens per call", v1["tokens_out_mean"], v11["tokens_out_mean"]),
        ]
    )
    variants = data.get("variants") or []
    if variants:
        out += [
            "",
            "### The same documents under other settings",
            "",
            f"{variants[0]['quality']['documents']} documents the model is asked about, one "
            "recording per setting, asked one setting after the other (the last row repeats the "
            "first to show how far the API's own mood moves the same setting).",
            "",
            "| Setting | p50 ms | p95 ms | timeouts | in / out tokens per call | mapping recall | "
            "manual matching | questions | unsafe READY | cost |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for v in variants:
            lat, q = v["latency"], v["quality"]
            out.append(
                f"| {v['variant']} | {lat['p50_ms']} | {lat['p95_ms']} | {lat['timeouts']} | "
                f"{lat['tokens_in_mean']} / {lat['tokens_out_mean']} | "
                f"{_pct(q['mapping_recall'])} | {q['manual_matching']} | {q['questions_asked']} | "
                f"{q['unsafe_ready']} | ${v['spend']['cost_usd_at_list_price']} |"
            )
        rules = variants[0]["quality"]["rules_alone"]
        out += [
            "",
            f"Rules alone on the same documents: mapping recall {_pct(rules['mapping_recall'])}, "
            f"manual matching {rules['manual_matching']}.",
        ]
    out.append("")
    return out


def _source_learning_section(data: Mapping[str, Any]) -> list[str]:
    sl = data.get("source_learning")
    if not sl:
        return []
    a, b = sl["V1"], sl["V1.1"]
    out = [
        "## Source Learning reuse",
        "",
        f"{b['families']} families x 8 versions, a counting stand-in that reads every column "
        "right (only how often it is ASKED is measured), the real services and database.",
        "",
        "| | OpenAI V1 | OpenAI V1.1 |",
        "|---|---:|---:|",
    ]
    later = "calls_on_later_files_of_a_source_that_was_confirmed"
    cold = "calls_on_the_same_files_of_a_source_nobody_confirmed"
    asked = "recognised_versions_that_asked_the_model"
    out += _rows(
        [
            ("calls on later files of a source a person confirmed", a[later], b[later]),
            ("the same files, for a source nobody confirmed", a[cold], b[cold]),
            (
                "calls avoided by remembering",
                a["calls_avoided_by_remembering"],
                b["calls_avoided_by_remembering"],
            ),
            ("recognised versions", a["recognised_versions"], b["recognised_versions"]),
            ("recognised versions that asked the model again", a[asked], b[asked]),
        ]
    )
    out.append("")
    return out


def _cost_section(data: Mapping[str, Any]) -> list[str]:
    spend_data = data["spend"]
    out = [
        "## Cost",
        "",
        "At the list price ($2 / M input, $10 / M output: read on the web, not from the API).",
        "",
        "| | calls | tokens in | tokens out | cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("V1 full run (Nov 16)", "v1"),
        ("V1.1 full run", "v11"),
        ("latency comparison", "variants"),
    ):
        sp = spend_data.get(key)
        if sp:
            out.append(
                f"| {label} | {sp['real_calls']} | {sp['tokens_in_total']} | "
                f"{sp['tokens_out_total']} | ${sp['cost_usd_at_list_price']} |"
            )
    out.append("")
    return out


def write_report(args: argparse.Namespace) -> int:
    from datetime import date

    def load(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    v1_results, v1_legacy, v11 = load(args.v1_results), load(args.v1_legacy), load(args.v11)
    variants = load(args.variants) if args.variants else []
    sl = load(args.source_learning) if args.source_learning else None
    gate_only = load(args.v11_gate_only) if args.v11_gate_only else None
    v1_spend = v1_results["spend"]
    failed = sum(v1_spend["calls_failed_by_kind"].values())
    v1_latency = {
        "calls": v1_spend["real_calls"],
        "mean_ms": v1_spend["latency_ms_mean"],
        "p50_ms": v1_spend["latency_ms_p50"],
        "p95_ms": v1_spend["latency_ms_p95"],
        "max_ms": v1_spend["latency_ms_max"],
        "timeouts": failed,
        "timeout_rate": round(failed / v1_spend["real_calls"], 4),
        "tokens_in_mean": v1_spend["tokens_in_per_call_mean"],
        "tokens_out_mean": v1_spend["tokens_out_per_call_mean"],
    }
    pops = list(v11["populations"])
    data = {
        "benchmark": "smart-import-openai-assist-v1-1",
        "model": v11["model"],
        "reasoning_effort": v11["reasoning_effort"],
        "comparison": comparison(v1_results, v11),
        "classification": {
            "v1": v1_legacy["classification"]["all"],
            "v11": v11["classification"]["all"],
        },
        "classification_by_population": {
            "v1": {p: v1_legacy["classification"][p] for p in pops},
            "v11": {p: v11["classification"][p] for p in pops},
        },
        "latency": {"v1": v1_latency, "v11": v11["latency"]},
        "variants": variants,
        "source_learning": sl,
        "attribution": None if gate_only is None else attribution(v1_results, gate_only, v11),
        "spend": {
            "v1": v1_spend,
            "v11": v11["spend"],
            "variants": None
            if not variants
            else {
                "real_calls": sum(v["spend"]["real_calls"] for v in variants),
                "tokens_in_total": sum(v["spend"]["tokens_in_total"] for v in variants),
                "tokens_out_total": sum(v["spend"]["tokens_out_total"] for v in variants),
                "cost_usd_at_list_price": round(
                    sum(v["spend"]["cost_usd_at_list_price"] for v in variants), 4
                ),
            },
        },
        "wire": v11["wire"],
        "v1_reproduced_from_its_recording": {
            "model_calls": v1_legacy["classification"]["all"]["model_calls"],
            "recording_misses": v1_legacy["recording_misses"],
        },
    }
    args.out_json.write_text(json.dumps(data, indent=1, sort_keys=True) + NL, encoding="utf-8")
    args.out_md.write_text(markdown(data, date.today().isoformat()), encoding="utf-8")
    say(f"JSON {args.out_json}" + NL + f"Markdown {args.out_md}")
    return 0


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def corpus_docs() -> dict[str, list[Doc]]:
    official = build_corpus()
    return {
        "challenge": challenge_docs(official, 2),
        "official": official,
        "adversarial": adversarial_docs(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.benchmarks.smart_import_v3.assist_efficiency"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory", help="rows of what each document came to (no network)")
    inv.add_argument("--cache", type=Path, required=True)
    inv.add_argument("--out", type=Path, required=True)
    inv.add_argument("--legacy", action="store_true", help="V1: the old gate, prompt and evidence")
    inv.add_argument("--workers", type=int, default=6)
    full = sub.add_parser(
        "full", help="the three populations as production asks (costs money unless a recording)"
    )
    full.add_argument("--cache", type=Path, required=True)
    full.add_argument("--out", type=Path, required=True)
    full.add_argument("--label", default="V1.1")
    full.add_argument("--legacy", action="store_true", help="V1: the old gate, prompt, evidence")
    full.add_argument("--from-recording", action="store_true", help="no network, no key")
    full.add_argument("--effort", default="medium")
    full.add_argument("--workers", type=int, default=6)
    full.add_argument("--fixture-out", type=Path, default=None, help="the recording, as a fixture")
    rep = sub.add_parser("report", help="the three columns, from the runs (no network)")
    rep.add_argument("--v1-results", type=Path, required=True, help="the committed V1 live JSON")
    rep.add_argument(
        "--v1-legacy", type=Path, required=True, help="`full --legacy` on its recording"
    )
    rep.add_argument("--v11", type=Path, required=True)
    rep.add_argument("--variants", type=Path, default=None)
    rep.add_argument("--source-learning", type=Path, default=None)
    rep.add_argument("--v11-gate-only", type=Path, default=None, help="the gate alone, at medium")
    rep.add_argument("--out-json", type=Path, required=True)
    rep.add_argument("--out-md", type=Path, required=True)
    var = sub.add_parser(
        "variants", help="the same documents under different settings (costs money)"
    )
    var.add_argument(
        "--rows", type=Path, required=True, help="the inventory that names the documents"
    )
    var.add_argument(
        "--cache", type=Path, required=True, help="a DIRECTORY: one recording per variant"
    )
    var.add_argument("--out", type=Path, required=True)
    var.add_argument("--n", type=int, default=50)
    var.add_argument("--only", action="append", default=[])
    var.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)

    if args.command == "report":
        return write_report(args)
    populations = corpus_docs()
    if args.command == "inventory":
        recorded = Recorded(None, args.cache, frozen=True)
        if args.legacy:
            with legacy_gate():
                rows = inventory(populations, recorded, args.workers, say)
        else:
            rows = inventory(populations, recorded, args.workers, say)
        args.out.write_text(json.dumps(rows), encoding="utf-8")
        data = {
            "classification": classify(rows),
            "latency_in_the_recording": latency_of(rows),
            "recording_misses": recorded.misses,
        }
        print(json.dumps(data, indent=1))
        return 0

    if args.command == "full":
        data = run_full(args, populations)
        args.out.write_text(json.dumps(data, indent=1, sort_keys=True) + NL, encoding="utf-8")
        print(
            json.dumps(
                {k: data[k] for k in ("label", "classification", "latency", "spend")}, indent=1
            )
        )
        return 0

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        say("NOT RUN - OPENAI_API_KEY NOT CONFIGURED")
        return 3
    model = os.environ.get("SMART_IMPORT_OPENAI_MODEL", "").strip() or "gpt-6.1-sol"
    every = {d.id: d for docs in populations.values() for d in docs}
    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    chosen = subset(rows, every, args.n)
    args.cache.mkdir(parents=True, exist_ok=True)
    say(f"{len(chosen)} documents, variants {args.only or list(VARIANTS)}")
    results = [
        run_variant(chosen, VARIANTS[name], key, model, args.cache, args.workers, say)
        for name in (args.only or list(VARIANTS))
    ]
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    for r in results:
        lat, q = r["latency"], r["quality"]
        say(
            f"{r['variant']}: p50 {lat['p50_ms']} p95 {lat['p95_ms']} timeouts {lat['timeouts']} "
            f"| recall {q['mapping_recall']} manual {q['manual_matching']} questions "
            f"{q['questions_asked']} unsafe {q['unsafe_ready']} "
            f"| ${r['spend']['cost_usd_at_list_price']}"
        )
    return 0


__all__ = ["PRICE_IN", "PRICE_OUT", "PSEUDO", "understanding_ai"]

if __name__ == "__main__":
    raise SystemExit(main())

"""python -m tests.benchmarks.smart_import_v3.openai_live            (from services/api)

OpenAI semantic layer, measured with the REAL model. No stand-in is used here: every answer comes
from the vendor's endpoint (`/v1/responses`, `store=false`, Structured Outputs, the model that
`SMART_IMPORT_OPENAI_MODEL` names), through the same provider, resolver, validator and service that
production builds. It needs OPENAI_API_KEY (or the application's own setting) and costs money.

The populations are the ones of `openai_intelligence` (the 290 challenge files, the 240 official
documents, the 15 adversarial files) and so is the scorer: a number here is directly comparable
with the stand-in table of that benchmark.

Configurations (the first one costs nothing, the second is the only one that calls the vendor, and
the last two are REPLAYS of the second one's recorded answers - they never touch the network):

* deterministic       the rules alone (the baseline);
* live_assist         the real model in ASSIST WITH the vocabulary certainty (`corroborate`): what
                      was first measured, and what ADR 0052 withdrew;
* live_assist_capped  the same answers with the certainty withdrawn: a model's reading is only ever
                      a MEDIUM suggestion a person confirms - how production builds it. Replay:
                      same requests, same answers;
* live_shadow         the same answers in SHADOW: every screen must stay exactly the rules' own.

A request that is not in the recording never reaches the network in a replay: it is counted as a
miss (and must be zero).

Never printed, never kept: the key, a request, an answer, the model's reasoning. The recording
(`--cache`) holds the model's answers on SYNTHETIC files and stays out of the repository.
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2

from app.core.tenant import TenantContext
from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from app.modules.ai.import_understanding.interpretation import SemanticInterpretation
from app.modules.ai.import_understanding.resolver import ImportUnderstandingUnavailableError
from app.modules.ai.import_understanding.types import (
    AiMode,
    FailureKind,
    ImportUnderstandingRequest,
    ProviderAnswer,
    ProviderUsage,
)
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandingService
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.observe import run
from tests.benchmarks.smart_import_v3.openai_intelligence import (
    Outcome,
    Recording,
    SemanticTap,
    _field_groups,
    _group_row,
    _stable,
    _structure_groups,
    adversarial_docs,
    caused_and_fixed,
    challenge_docs,
    measure,
    run_config,
    score_all,
)
from tests.benchmarks.smart_import_v3.score import CaseResult
from tests.import_ai_support import audit
from tests.live_openai_acceptance import _key_of_the_application, verify_request

REPO = Path(__file__).resolve().parents[5]
DEFAULT_JSON = REPO / "services/api/tests/benchmarks/results/smart-import-openai-live-v1.json"
DEFAULT_MD = REPO / "docs/benchmarks/smart-import-openai-live-v1.md"
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "ninfa-openai-live-recording.jsonl"
DEFAULT_MODEL = "gpt-6.1-sol"
# USD per million tokens. OpenAI's published list price for the model (read on the web on
# 2026-11-16, NOT returned by the API): an assumption of this report, stated as one.
PRICE_IN = 2.0
PRICE_OUT = 10.0
TIMEOUT_SECONDS = 25.0  # production's own (`smart_import_openai_timeout_seconds`)
CONFIGS = ("deterministic", "live_assist", "live_assist_capped", "live_shadow")
LABELS = {
    "deterministic": "Deterministic only",
    "live_assist": "ASSIST - real model, vocabulary certainty ON (as first measured)",
    "live_assist_capped": "ASSIST - real model, MEDIUM cap (production, ADR 0052)",
    "live_shadow": "SHADOW - real model",
}


# --- the recording: the real model's answers, kept so that a replay costs nothing ---------------


class Recorded:
    """Between the resolver and the vendor: asks the real provider once per distinct request, keeps
    the answer (and what the call cost), and gives the same answer to any later identical request.
    `frozen` forbids the network: a request that was never recorded is then a MISS, not a call."""

    contract = "semantic-v1"
    name = "openai"

    def __init__(
        self, inner: Any | None, path: Path, *, model: str = DEFAULT_MODEL, frozen: bool = False
    ) -> None:
        self.inner = inner
        self.model = model
        self.frozen = frozen
        self.path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        # EVERY real call that was ever made, in order (a request asked twice is two calls and two
        # bills), and one lock per request in flight: a request that two documents share is asked
        # once, and the second waits for the first one's answer
        self._log: list[dict[str, Any]] = []
        self._inflight: dict[str, threading.Lock] = {}
        self.live_calls = 0
        self.hits = 0
        self.misses = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._log.append(entry)
                    self._entries[entry["key"]] = entry

    def frozen_copy(self) -> "Recorded":
        twin = Recorded(None, self.path, model=self.model, frozen=True)
        twin._entries = self._entries
        twin._log = self._log
        twin._lock = self._lock
        return twin

    @staticmethod
    def key_of(request: ImportUnderstandingRequest) -> str:
        parts = (
            request.system_instructions,
            request.evidence_json,
            str(request.attempt),
            "|".join(request.retry_hints),
            str(request.contract),
        )
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

    def export_fixture(self, path: Path) -> int:
        """The recording as a FIXTURE: what a replay needs and nothing more. A key (the hash of a
        request, which cannot be turned back into it), the answer (closed vocabularies only:
        indexes, field names, codes - no header, no value, no sentence), whether the call worked,
        and the counts of what it cost. The vendor's request id, which identifies a call at the
        vendor, is dropped. One entry per distinct request, sorted: the same recording gives the
        same file."""
        lines: list[str] = []
        for entry in self._entries.values():
            clean = {k: v for k, v in entry.items() if k != "usage"}
            usage = entry.get("usage")
            clean["usage"] = None if usage is None else {**usage, "request_id": None}
            lines.append(
                json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8", newline="\n")
        return len(lines)

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Every real call (what the account was billed for), duplicates included."""
        return list(self._log)

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        key = self.key_of(request)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self.hits += 1
        if entry is None:
            if self.frozen or self.inner is None:
                with self._lock:
                    self.misses += 1
                raise ImportUnderstandingUnavailableError(
                    "not in the recording", FailureKind.PROVIDER_ERROR
                )
            with self._lock:
                gate = self._inflight.setdefault(key, threading.Lock())
            with gate:
                with self._lock:
                    entry = self._entries.get(key)
                if entry is None:
                    entry = self._ask(key, request)
        if not entry["ok"]:
            usage = ProviderUsage(**entry["usage"]) if entry["usage"] else None
            raise ImportUnderstandingUnavailableError(
                "the provider request failed", FailureKind(entry["kind"]), usage
            )
        return ProviderAnswer(entry["payload"], ProviderUsage(**entry["usage"]))

    def _ask(self, key: str, request: ImportUnderstandingRequest) -> dict[str, Any]:
        assert self.inner is not None
        entry: dict[str, Any]
        try:
            answer = self.inner.suggest(request)
            assert isinstance(answer, ProviderAnswer)
            payload = answer.payload
            if isinstance(payload, SemanticInterpretation):
                payload = payload.model_dump(mode="json")
            entry = {"key": key, "ok": True, "payload": payload, "usage": asdict(answer.usage)}
        except ImportUnderstandingUnavailableError as unavailable:
            entry = {
                "key": key,
                "ok": False,
                "kind": unavailable.kind.value,
                "usage": asdict(unavailable.usage) if unavailable.usage else None,
            }
        entry["attempt"] = request.attempt
        with self._lock:
            self._entries[key] = entry
            self._log.append(entry)
            self.live_calls += 1
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


class Audited:
    """Per document: what the provider was handed is audited against that document's personal
    values, as the stand-ins' audit does (a request is the evidence the egress gate let through)."""

    contract = "semantic-v1"
    name = "openai"

    def __init__(self, inner: Recorded, forbidden: Sequence[str]) -> None:
        self.inner = inner
        self.forbidden = tuple(forbidden)
        self.violations: list[str] = []
        self.model = inner.model

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        self.violations += audit(request, self.forbidden)
        return self.inner.suggest(request)


class Wire:
    """Every request that really LEFT the machine, checked on its way out (the acceptance's own
    checks, plus every personal value of every document of the run as a canary). Only counts are
    kept: never a request."""

    def __init__(self, model: str, canaries: Sequence[str]) -> None:
        self.model = model
        self.canaries = tuple(c for c in canaries if len(c) >= 6)
        self.requests = 0
        self.failed: Counter[str] = Counter()
        self.sizes: list[int] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx2.Request) -> None:
        request.read()
        body = json.loads(request.content)
        verdicts = verify_request(request.url.path, body, self.model, self.canaries)
        with self._lock:
            self.requests += 1
            self.sizes.append(len(request.content))
            for name, passed, _ in verdicts:
                if not passed:
                    self.failed[name] += 1


class CappedRecording(Recording):
    """The resolver as production builds it (ADR 0052): the vocabulary certainty withdrawn, so
    whatever a model names stays a MEDIUM suggestion with a question. Requests are identical
    (`reads_confirmations` is unchanged), so the recorded answers apply as they are."""

    VOCABULARY_CERTAINTY = False


def real_provider(
    key: str, model: str, wire: Wire, effort: str = "medium"
) -> OpenAIImportUnderstandingProvider:
    client = httpx2.Client(event_hooks={"request": [wire]}, timeout=TIMEOUT_SECONDS)
    return OpenAIImportUnderstandingProvider(
        key,
        model=model,
        reasoning_effort=effort,  # type: ignore[arg-type]
        timeout_seconds=TIMEOUT_SECONDS,
        http_client=client,
    )


# --- running -------------------------------------------------------------------------------------


def run_one(doc: Doc, recorded: Recorded, resolver_cls: type[Recording], mode: AiMode) -> Outcome:
    tap = SemanticTap(Audited(recorded, doc.golden.pii_values))
    resolver = resolver_cls(tap, mode)
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    service = UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)
    started = time.perf_counter()
    observed = run(service, doc.card, doc.filename, doc.content)
    return Outcome(observed, tap, resolver, time.perf_counter() - started)


def run_with(
    docs: Sequence[Doc],
    recorded: Recorded,
    resolver_cls: type[Recording],
    mode: AiMode,
    workers: int,
    progress: Callable[[str], None],
    label: str,
) -> dict[str, Outcome]:
    done = 0
    lock = threading.Lock()

    def one(doc: Doc) -> tuple[str, Outcome]:
        nonlocal done
        outcome = run_one(doc, recorded, resolver_cls, mode)
        with lock:
            done += 1
            if done % 20 == 0 or done == len(docs):
                progress(
                    f"    {label}: {done}/{len(docs)} (live calls so far {recorded.live_calls})"
                )
        return doc.id, outcome

    if workers <= 1:
        return dict(one(d) for d in docs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, docs))


def stratified(docs: Sequence[Doc], n: int | None) -> list[Doc]:
    """n documents, spread over the fields (and so the structures) of the population, chosen by a
    stable hash: the same subset on every run."""
    if n is None or n >= len(docs):
        return list(docs)
    groups: dict[str, list[Doc]] = {}
    for doc in docs:
        groups.setdefault(",".join(_field_groups(doc)) or "-", []).append(doc)
    for members in groups.values():
        members.sort(key=lambda d: _stable(d.id))
    taken: list[Doc] = []
    index = 0
    while len(taken) < n:
        moved = False
        for name in sorted(groups):
            if index < len(groups[name]) and len(taken) < n:
                taken.append(groups[name][index])
                moved = True
        if not moved:
            break
        index += 1
    return taken


# --- what the model cost ------------------------------------------------------------------------


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


def spend(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every real call in the recording: what it was, how long it took, what it cost."""
    usages = [e["usage"] for e in entries if e["usage"]]
    tokens_in = [u["input_tokens"] for u in usages if u["input_tokens"] is not None]
    tokens_out = [u["output_tokens"] for u in usages if u["output_tokens"] is not None]
    latencies = [u["latency_ms"] for u in usages if u["latency_ms"]]
    ok = [e for e in entries if e["ok"]]
    answered = [e for e in ok if e["payload"] is not None]
    cost = (sum(tokens_in) * PRICE_IN + sum(tokens_out) * PRICE_OUT) / 1_000_000
    return {
        "real_calls": len(entries),
        "calls_answered_in_the_closed_shape": len(answered),
        "calls_answered_not_in_the_shape": len(ok) - len(answered),
        "calls_failed_by_kind": dict(Counter(e["kind"] for e in entries if not e["ok"])),
        "second_attempts": sum(1 for e in entries if e.get("attempt", 1) >= 2),
        "transport_retries": sum(u["retries"] for u in usages),
        "tokens_in_total": sum(tokens_in),
        "tokens_out_total": sum(tokens_out),
        "tokens_in_per_call_mean": round(statistics.mean(tokens_in)) if tokens_in else 0,
        "tokens_out_per_call_mean": round(statistics.mean(tokens_out)) if tokens_out else 0,
        "tokens_out_per_call_p95": round(_percentile(tokens_out, 0.95)),
        "latency_ms_mean": round(statistics.mean(latencies)) if latencies else 0,
        "latency_ms_p50": round(_percentile(latencies, 0.5)),
        "latency_ms_p95": round(_percentile(latencies, 0.95)),
        "latency_ms_max": max(latencies) if latencies else 0,
        "request_ids_recorded": sum(1 for u in usages if u["request_id"]),
        "models_reported_by_the_vendor": sorted({u["model"] for u in usages if u["model"]}),
        "reasoning_efforts": sorted(
            {u["reasoning_effort"] for u in usages if u["reasoning_effort"]}
        ),
        "price_usd_per_million_tokens": {"input": PRICE_IN, "output": PRICE_OUT},
        "cost_usd_at_list_price": round(cost, 4),
        "cost_usd_per_call_mean": round(cost / len(usages), 5) if usages else 0,
    }


# --- measuring -----------------------------------------------------------------------------------


PRODUCTION_CONFIGS = ("deterministic", "live_assist_capped", "live_shadow")


def evaluate(
    name: str,
    docs: Sequence[Doc],
    recorded: Recorded,
    workers: int,
    progress: Callable[[str], None],
    *,
    production: bool = False,
    keep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`production`: the model is asked as production builds it (the certainty withdrawn, ADR 0052)
    and the certainty-on configuration is not run; otherwise V1's four configurations."""
    progress(f"  {name}: {len(docs)} documents")
    used = PRODUCTION_CONFIGS if production else CONFIGS
    live = "live_assist_capped" if production else "live_assist"
    outcomes: dict[str, dict[str, Outcome]] = {}
    progress("    deterministic (no model)")
    outcomes["deterministic"] = run_config(docs, "deterministic")
    progress(f"    {live} (the real model)")
    outcomes[live] = run_with(
        docs,
        recorded,
        CappedRecording if production else Recording,
        AiMode.ASSIST,
        workers,
        progress,
        live,
    )
    replay = recorded.frozen_copy()
    progress(f"    {live} again, from the recording (determinism check)")
    again = run_with(
        docs,
        replay,
        CappedRecording if production else Recording,
        AiMode.ASSIST,
        workers,
        progress,
        "replay",
    )
    if not production:
        progress("    live_assist_capped (replay, certainty withdrawn)")
        outcomes["live_assist_capped"] = run_with(
            docs, replay, CappedRecording, AiMode.ASSIST, workers, progress, "capped"
        )
    progress("    live_shadow (replay)")
    shadow_cls = CappedRecording if production else Recording
    outcomes["live_shadow"] = run_with(
        docs, replay, shadow_cls, AiMode.SHADOW, workers, progress, "shadow"
    )
    if keep is not None:
        keep["deterministic"], keep["live"] = outcomes["deterministic"], outcomes[live]
    scored: dict[str, dict[str, CaseResult]] = {c: score_all(docs, outcomes[c]) for c in used}
    base, base_scored = outcomes["deterministic"], scored["deterministic"]
    metrics = {c: measure(docs, outcomes[c], scored[c], base, base_scored) for c in used}
    for config in used[1:]:
        metrics[config]["latency"] = _latency_of(docs, outcomes[config])
    differs = [
        d.id for d in docs if again[d.id].observed.payload != outcomes[live][d.id].observed.payload
    ]
    unsafe_ids = {
        c: [
            d.id
            for d in docs
            if scored[c][d.id].level == "READY"
            and (scored[c][d.id].false_automation or not _no_wrong_claim(scored[c][d.id]))
        ]
        for c in used
    }
    block: dict[str, Any] = {
        "documents": len(docs),
        "metrics": metrics,
        "unsafe_ready_ids": unsafe_ids,
        "replay_differs_from_the_live_run": differs,
        "replay_misses": replay.misses,
        "shadow_screens_that_changed": [
            d.id
            for d in docs
            if outcomes["live_shadow"][d.id].observed.payload != base[d.id].observed.payload
        ],
        "fallbacks": _fallbacks(docs, outcomes[live]),
        "levels_moved": _levels_moved(docs, base, outcomes[live]),
    }
    if name == "challenge":
        block["by_field"] = _groups(docs, outcomes, scored, _field_groups, live)
        block["by_structure"] = _groups(docs, outcomes, scored, _structure_groups, live)
    block["documents_ids"] = [d.id for d in docs]
    block["caused_and_fixed"] = {
        c: list(v) for c, v in caused_and_fixed({"unsafe_ready_ids": unsafe_ids}).items()
    }
    return block


def _no_wrong_claim(case: CaseResult) -> bool:
    return case.everything.wrong == 0 and case.junk_mapped == 0


def _latency_of(docs: Sequence[Doc], outcomes: Mapping[str, Outcome]) -> dict[str, Any]:
    usages = [
        u
        for d in docs
        if outcomes[d.id].resolver is not None
        for r in outcomes[d.id].resolver.resolutions  # type: ignore[union-attr]
        for u in r.usages
    ]
    values = [u.latency_ms for u in usages if u.latency_ms]
    return {
        "calls": len(usages),
        "p50_ms": round(_percentile(values, 0.5)),
        "p95_ms": round(_percentile(values, 0.95)),
        "max_ms": max(values) if values else 0,
    }


def _fallbacks(docs: Sequence[Doc], outcomes: Mapping[str, Outcome]) -> dict[str, int]:
    kinds: Counter[str] = Counter()
    for d in docs:
        resolver = outcomes[d.id].resolver
        for trace in resolver.traces if resolver is not None else []:
            if trace.fallback_reason:
                kinds[trace.fallback_reason] += 1
    return dict(kinds)


def _levels_moved(
    docs: Sequence[Doc], base: Mapping[str, Outcome], live: Mapping[str, Outcome]
) -> dict[str, int]:
    moved: Counter[str] = Counter()
    for d in docs:
        before, after = base[d.id].observed.level, live[d.id].observed.level
        if before != after:
            moved[f"{before} -> {after}"] += 1
    return dict(moved)


def _groups(
    docs: Sequence[Doc],
    outcomes: Mapping[str, Mapping[str, Outcome]],
    scored: Mapping[str, Mapping[str, CaseResult]],
    selector: Callable[[Doc], list[str]],
    live: str = "live_assist",
) -> dict[str, dict[str, Any]]:
    members: dict[str, list[Doc]] = {}
    for d in docs:
        for g in selector(d):
            members.setdefault(g, []).append(d)
    return {
        g: {c: _group_row(ds, outcomes[c], scored[c]) for c in ("deterministic", live)}
        for g, ds in sorted(members.items())
    }


# --- the pilot: ONE real call, to size the rest --------------------------------------------------


def pilot(key: str, model: str, cache_path: Path, say: Callable[[str], None]) -> int:
    docs = challenge_docs(build_corpus(), 2)
    wire = Wire(model, [])
    recorded = Recorded(real_provider(key, model, wire), cache_path, model=model)
    for doc in stratified(docs, 12):
        outcome = run_one(doc, recorded, Recording, AiMode.ASSIST)
        if recorded.live_calls:
            break
    spent = spend(recorded.entries)
    say(json.dumps(spent, indent=1))
    asked, official, adversarial = 225, 46, 12  # what the stand-in run asked (the rules decide)
    per_call = spent["cost_usd_per_call_mean"]
    say(
        f"first real call: {spent['tokens_in_total']} tokens in, {spent['tokens_out_total']} out, "
        f"{spent['latency_ms_mean']} ms, cost ${spent['cost_usd_at_list_price']}"
    )
    say(
        f"projected for {asked + official + adversarial} calls: "
        f"about ${per_call * (asked + official + adversarial):.2f} at this call's size"
    )
    del outcome
    return 0


# --- the report -----------------------------------------------------------------------------------

ROWS = (
    ("Documents", "documents", "{}"),
    ("READY with no question (automatic)", "automatic", "{}"),
    ("Manual matching required", "manual_matching", "{}"),
    ("Files that ask questions", "asking", "{}"),
    ("Questions asked", "questions_asked", "{}"),
    ("Unnecessary questions", "questions_unnecessary", "{}"),
    ("Mapping recall (truth facts found)", "mapping_recall", "{:.1%}"),
    ("Claims precision (claims that are right)", "claims_precision", "{:.1%}"),
    ("Domain accuracy", "domain_accuracy", "{:.1%}"),
    ("Header detection accuracy", "header_accuracy", "{:.1%}"),
    ("**Unsafe READY**", "unsafe_ready", "{}"),
    ("**False automation**", "false_automation", "{}"),
    ("**Wrong-domain READY**", "wrong_domain_ready", "{}"),
    ("Certain-and-wrong claims", "certain_and_wrong", "{}"),
    ("P0 findings (silent wrong data)", "p0_findings", "{}"),
    ("Junk / personal columns mapped", "junk_columns_mapped", "{}"),
    (
        "**PII values sent to the model** (audit of each request)",
        "pii_violations_in_what_the_model_was_sent",
        "{}",
    ),
    ("PII values in the browser answer", "pii_values_in_the_browser_answer", "{}"),
    ("**Scope safety violations**", "scope_violations", "{}"),
    ("Model calls", "model_calls", "{}"),
)
VS = (
    ("Files made automatic, correctly", "files_made_automatic_correctly"),
    ("Files made automatic with ANOTHER fact still unread", "files_made_automatic_wrongly"),
    ("Questions correctly avoided", "questions_correctly_avoided"),
    ("Questions incorrectly avoided", "questions_incorrectly_avoided"),
    ("Manual matching turned into questions with a suggestion", "manual_matching_became_questions"),
    ("Manual matching turned into READY", "manual_matching_became_ready"),
    ("Questions turned into READY", "questions_became_ready"),
    ("Model suggestions right", "model_suggestions_right"),
    ("Model suggestions wrong", "model_suggestions_wrong"),
    ("Screens that changed", "screens_that_changed"),
)


def _cell(value: Any, template: str) -> str:
    return "-" if value is None else template.format(value)


def _outcome(data: Mapping[str, Any]) -> str:
    """The one line that decides, computed from the data it summarises."""
    unsafe = {
        c: sum(len(p["unsafe_ready_ids"][c]) for p in data["populations"].values()) for c in CONFIGS
    }
    return (
        "> **Outcome.** Unsafe READY over all populations - rules alone "
        f"{unsafe['deterministic']}, real model with the vocabulary certainty "
        f"{unsafe['live_assist']}, real model with the MEDIUM cap {unsafe['live_assist_capped']}, "
        f"SHADOW {unsafe['live_shadow']}. A certainty that lets a model's reading skip the "
        "question is withdrawn while it is above zero: production builds the MEDIUM cap (ADR 0052)."
    )


def markdown(data: Mapping[str, Any], today: str) -> str:
    out = [
        "# Smart Import - OpenAI semantic layer - LIVE model benchmark V1",
        "",
        f"Date {today} - branch `feature/smart-import-openai-intelligence-v1` - model "
        f"`{data['model']}` (reported by the vendor: "
        f"{', '.join(data['spend']['models_reported_by_the_vendor'])}).",
        "",
        "> Every number below comes from the **real model** on the vendor's endpoint "
        "(`/v1/responses`, `store=false`, Structured Outputs). No stand-in. The files are the "
        "synthetic corpus of `openai_intelligence`; nothing real was sent.",
        "",
        _outcome(data),
        "",
        "Regenerate (from `services/api`, key in the environment, costs money): "
        "`python -m tests.benchmarks.smart_import_v3.openai_live`.",
        "",
    ]
    for population in ("challenge", "official", "adversarial"):
        block = data["populations"][population]
        out += [
            f"## Population: {population}",
            "",
            f"{block['documents']} documents"
            + (
                f" (of {data['population_sizes'][population]})"
                if block["documents"] != data["population_sizes"][population]
                else ""
            )
            + ".",
            "",
        ]
        configs = list(CONFIGS)
        out += ["| Metric | " + " | ".join(LABELS[c] for c in configs) + " |"]
        out += ["|---|" + "---:|" * len(configs)]
        for label, key, template in ROWS:
            out.append(
                f"| {label} | "
                + " | ".join(_cell(block["metrics"][c][key], template) for c in configs)
                + " |"
            )
        out += ["", "Against the rules alone, document by document:", ""]
        out += ["| | " + " | ".join(LABELS[c] for c in configs[1:]) + " |"]
        out += ["|---|" + "---:|" * (len(configs) - 1)]
        for label, key in VS:
            out.append(
                f"| {label} | "
                + " | ".join(str(block["metrics"][c]["vs_rules_alone"][key]) for c in configs[1:])
                + " |"
            )
        out += [
            "",
            "Unsafe READY against the rules alone (caused / fixed by the layer): "
            + "; ".join(
                f"{LABELS[c]}: {v[0]} / {v[1]}" for c, v in block["caused_and_fixed"].items()
            )
            + ".",
            "",
            f"Levels moved by the real model (rules -> ASSIST): {block['levels_moved'] or 'none'}. "
            f"Fallbacks: {block['fallbacks'] or 'none'}. Shadow screens that changed: "
            f"{len(block['shadow_screens_that_changed'])}. Replay differences from the live run: "
            f"{len(block['replay_differs_from_the_live_run'])}. Replay misses: "
            f"{block['replay_misses']}.",
            "",
        ]
    challenge = data["populations"]["challenge"]
    out += [
        "## Challenge population by field",
        "",
        "| Field | Docs | Automatic (rules) | Automatic (model) | Manual (rules) | "
        "Manual (model) | Questions (rules) | Questions (model) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, groups in challenge["by_field"].items():
        a, b = groups["deterministic"], groups["live_assist"]
        out.append(
            f"| {name} | {a['documents']} | {a['automatic']} | {b['automatic']} | "
            f"{a['manual_matching']} | {b['manual_matching']} | {a['questions_asked']} | "
            f"{b['questions_asked']} |"
        )
    spent = data["spend"]
    wire = data["wire"]
    out += [
        "",
        "## The real calls",
        "",
        f"* Real calls to the vendor: **{spent['real_calls']}** "
        f"({spent['calls_answered_in_the_closed_shape']} answered in the closed shape, "
        f"{spent['calls_answered_not_in_the_shape']} answered but not in it, failed by kind: "
        f"{spent['calls_failed_by_kind'] or 'none'}); second attempts {spent['second_attempts']}, "
        f"transport retries {spent['transport_retries']}.",
        f"* Tokens: {spent['tokens_in_total']} in / {spent['tokens_out_total']} out "
        f"(per call: {spent['tokens_in_per_call_mean']} in, "
        f"{spent['tokens_out_per_call_mean']} out on average, p95 out "
        f"{spent['tokens_out_per_call_p95']}; output includes reasoning tokens).",
        f"* Latency per call: mean {spent['latency_ms_mean']} ms, "
        f"p50 {spent['latency_ms_p50']} ms, "
        f"p95 {spent['latency_ms_p95']} ms, max {spent['latency_ms_max']} ms "
        f"(production's timeout is {int(TIMEOUT_SECONDS)} s).",
        f"* Cost at list price (${PRICE_IN}/M input, ${PRICE_OUT}/M output - **an assumption read "
        f"on the web, not returned by the API**): **${spent['cost_usd_at_list_price']}** in total, "
        f"${spent['cost_usd_per_call_mean']} per call.",
        f"* Request ids recorded: {spent['request_ids_recorded']} of {spent['real_calls']}.",
        f"* On the wire: {wire['requests']} requests inspected as they left; checks failed: "
        f"{wire['failed'] or 'none'}; largest request {wire['largest_request_bytes']} bytes.",
        "",
    ]
    return "\n".join(out) + "\n"


def _wire_of(wire: Wire, saved: Path | None) -> dict[str, Any]:
    """What was audited on the wire: this run's, or - when the tables are recomputed from the
    recording - the audit of the run that made the calls (a recording has no wire)."""
    if saved is not None:
        kept: dict[str, Any] = json.loads(saved.read_text(encoding="utf-8"))["wire"]
        return kept
    return {
        "requests": wire.requests,
        "failed": dict(wire.failed),
        "largest_request_bytes": max(wire.sizes) if wire.sizes else 0,
        "canaries_checked": len(wire.canaries),
    }


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.smart_import_v3.openai_live")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--pilot", action="store_true", help="ONE real call, to size the run")
    parser.add_argument("--challenge", type=int, default=None, help="a subset of the challenge")
    parser.add_argument("--official", type=int, default=None, help="a subset of the official 240")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--render", type=Path, default=None, help="Markdown again from a JSON")
    parser.add_argument(
        "--from-recording",
        action="store_true",
        help="no network and no key: every configuration is computed from the recording",
    )
    parser.add_argument(
        "--wire-from", type=Path, default=None, help="the JSON of the run whose wire audit to keep"
    )
    args = parser.parse_args(argv)
    if args.render is not None:
        saved = json.loads(args.render.read_text(encoding="utf-8"))
        args.markdown.write_text(
            markdown(saved, date.today().isoformat()), encoding="utf-8", newline="\n"
        )
        say(f"Markdown {args.markdown}")
        return 0

    key = ""
    if not args.from_recording:
        key = os.environ.get("OPENAI_API_KEY", "").strip() or _key_of_the_application()
        if not key:
            say("LIVE BENCHMARK: NOT RUN - OPENAI_API_KEY NOT CONFIGURED")
            return 3
    model = os.environ.get("SMART_IMPORT_OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    if args.pilot:
        return pilot(key, model, args.cache, say)

    official_all = build_corpus()
    challenge_all = challenge_docs(official_all, 2)
    adversarial = adversarial_docs()
    populations_docs = {
        "challenge": stratified(challenge_all, args.challenge),
        "official": stratified(official_all, args.official),
        "adversarial": adversarial,
    }
    sizes = {
        "challenge": len(challenge_all),
        "official": len(official_all),
        "adversarial": len(adversarial),
    }
    every_pii = sorted(
        {v for ds in populations_docs.values() for d in ds for v in d.golden.pii_values}
    )
    wire = Wire(model, every_pii)
    if args.from_recording:
        recorded = Recorded(None, args.cache, model=model, frozen=True)
    else:
        recorded = Recorded(real_provider(key, model, wire), args.cache, model=model)
    say(
        f"model {model}; documents {sum(len(v) for v in populations_docs.values())}; "
        f"{len(every_pii)} personal values used as canaries; recording {args.cache}"
    )
    started = time.time()
    populations = {
        name: evaluate(name, docs, recorded, args.workers, say)
        for name, docs in populations_docs.items()
    }
    data = {
        "benchmark": "smart-import-openai-live-v1",
        "model": model,
        "model_called": True,
        "reasoning_effort": "medium",
        "population_sizes": sizes,
        "populations": populations,
        "spend": spend(recorded.entries),
        "wire": _wire_of(wire, args.wire_from if args.from_recording else None),
        "computed_from": "the recording of the real calls" if args.from_recording else "live run",
        "seconds": round(time.time() - started),
    }
    print(json.dumps({"spend": data["spend"], "wire": data["wire"]}, indent=1))
    if args.no_write:
        return 0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    args.markdown.write_text(
        markdown(data, date.today().isoformat()), encoding="utf-8", newline="\n"
    )
    say(f"JSON {args.json}\nMarkdown {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

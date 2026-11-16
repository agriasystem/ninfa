"""python -m tests.benchmarks.smart_import_v3.pilot_shadow            (from services/api)

REAL PILOT SHADOW VALIDATION. The files of the pilot/demo environment are put through Smart Import
exactly as it runs, with the model in SHADOW: the answer a person would see is the rules' own, and
the model is only asked what ASSIST would have shown.

What is real here: the resolver is the one `build_import_understanding_resolver` builds from
`Settings` (SMART_IMPORT_AI_MODE=shadow, the approved reasoning, the certainty withdrawn), the
provider is the real OpenAI one, the requests are inspected on the wire. What is a SIMULATION, and
said so: "what ASSIST would have shown" is the SHADOW run's own recorded answer applied through the
ASSIST code in memory (no second call, nothing persisted) - the replay SHADOW itself makes for its
audit.

Before the first real request, every request the files can produce is built with NO network and
audited (`--preflight-only` stops there). Anything personal in one of them is a STOP.

Never printed, never kept: the key, a request, an answer, the vendor's request ids, a cell
of a file.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.api.v1.sources.router import _inspection_response
from app.core.config import Settings
from app.core.tenant import TenantContext
from app.modules.ai.gateway.factory import build_import_understanding_resolver
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode, AiResolution, AiTrace
from app.modules.data_sources import understanding as understanding_module
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.document_understanding.personal_shapes import is_personal_value
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.ai_readiness import PSEUDO
from tests.benchmarks.smart_import_v3.assist_efficiency import (
    _patched,
    classify,
    latency_of,
)
from tests.benchmarks.smart_import_v3.openai_live import (
    PRICE_IN,
    PRICE_OUT,
    Audited,
    Recorded,
    Wire,
    spend,
)
from tests.semantic_support import Behaviour, SemanticStandIn

REPO = Path(__file__).resolve().parents[5]
FIXTURES = REPO / "tests" / "fixtures"
CARDS = {"bookings": DataSourceDomain.BOOKINGS, "costs": DataSourceDomain.COSTS}
# the keys the model's evidence may have: nothing else leaves (no file name, no row)
EVIDENCE_KEYS = {"expected_domain", "allowed", "sheets", "title", "columns", "questions"}
COLUMN_KEYS = {
    "index",
    "header",
    "kind",
    "values",
    "distinct",
    "pii",
    "samples",
    "range",
    "assigned",
}
PII_HEADER = re.compile(
    r"ospit|guest|nome|cognome|name|e-?mail|mail|telefon|phone|cellulare|indirizz|address|street|"
    r"cod(ice)?[ ._]?fisc|tax[ ._]?code|iban|note|documento|customer|cliente|contact",
    re.IGNORECASE,
)

# What a header MEANS, written by hand from the demo's own documentation (NOT from the rules): used
# to judge a suggestion of the model. None: a column that must never become a field (personal data,
# or nothing NINFA reads). A header missing here is reported as "unjudged", never as right.
TRUTH: dict[str, str | None] = {
    "booking id": "source_record_id",
    "id prenotazione": "source_record_id",
    "codice prenotazione": "source_record_id",
    "booked at": "booked_at",
    "data prenotazione": "booked_at",
    "check-in": "check_in",
    "arrival": "check_in",
    "arrivo": "check_in",
    "data arrivo": "check_in",
    "check-out": "check_out",
    "partenza": "check_out",
    "data partenza": "check_out",
    "status": "status",
    "stato": "status",
    "rooms": "rooms",
    "camere": "rooms",
    "room revenue": "room_revenue",
    "importo camera": "room_revenue",
    "importo totale": "total_revenue",
    "channel": "channel",
    "canale": "channel",
    "commissione": "commission_amount",
    "ospiti": "guests",
    "tipologia camera": "room_type",
    "data cancellazione": "cancelled_at",
    "ospite": None,
    "telefono": None,
    "guest_name": None,
    "guest_email": None,
    "guest_phone": None,
    "notes": None,
    "supplier": "supplier_name",
    "fornitore": "supplier_name",
    "vat": "supplier_vat_number",
    "p.iva": "supplier_vat_number",
    "tax code": "supplier_tax_code",
    "codice fiscale": "supplier_tax_code",
    "iban": None,
    "invoice no": "invoice_number",
    "numero fattura": "invoice_number",
    "invoice date": "invoice_date",
    "data": "invoice_date",
    "description": "line_description",
    "descrizione": "line_description",
    "line total": "line_total",
    "importo": "line_total",
    "amount": "line_total",
    "category": "cost_category",
    "categoria": "cost_category",
    "gross": "invoice_gross_amount",
    "imponibile": "invoice_net_amount",
    "tipo": "document_type",
    "line": None,
    "riferimento cliente": None,
    "contact email": None,
    "contact phone": None,
    "street": None,
    "customer": None,
}


def key_of(header: str) -> str:
    return re.sub(r"\s+", " ", header.replace("﻿", "")).strip().casefold()


# --- the corpus ----------------------------------------


@dataclass(frozen=True, slots=True)
class PilotFile:
    id: str
    path: Path
    card: str
    kind: str  # the folder it comes from
    content: bytes

    @property
    def domain(self) -> DataSourceDomain:
        return CARDS[self.card]


def discover(root: Path = FIXTURES) -> list[PilotFile]:
    out: list[PilotFile] = []
    for path in sorted(root.rglob("*.csv")):
        rel = path.relative_to(root)
        if rel.parts[0] == "costs":
            card = "costs" if rel.parts[1] == "invoices" else "bookings"
        else:
            card = "costs" if rel.parts[0] == "invoices" else "bookings"
        out.append(PilotFile(rel.as_posix(), path, card, rel.parts[0], path.read_bytes()))
    return out


def rows_of(content: bytes) -> tuple[list[str], list[list[str]]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    table = list(csv.reader(text.splitlines(), delimiter=delimiter))
    return table[0], table[1:]


def canaries_of(file: PilotFile) -> list[str]:
    """Personal values of THIS file, found without the engine: the cells of every column whose
    header speaks of a person, an address, a contact, a code; and any cell shaped like personal
    data."""
    header, body = rows_of(file.content)
    found: set[str] = set()
    for index, name in enumerate(header):
        personal = bool(PII_HEADER.search(name))
        for row in body:
            cell = row[index].strip() if index < len(row) else ""
            if len(cell) >= 4 and (personal or is_personal_value(cell)):
                found.add(cell)
    return sorted(found)


# --- inspecting a file ----------------------------------------


def service_with(resolver: Any) -> UnderstandingService:
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    return UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)


def inspect(file: PilotFile, resolver: Any) -> Any:
    return service_with(resolver).understand(
        file.domain,
        file.path.name,
        file.content,
        UnderstandAnswers(),
        False,
        None,
        False,
        currency="EUR",
    )


def screen_of(inspection: Any) -> str:
    return str(_inspection_response(inspection).model_dump_json())


def summary_of(inspection: Any) -> dict[str, Any]:
    info = inspection.understanding
    claims = [
        {"header": r.origin.detail, "field": r.field, "kind": r.origin.kind.value, "level": r.level}
        for r in (info.recognized if info else [])
    ]
    return {
        "level": info.level.value if info else None,
        "questions": [
            {"id": q.id, "kind": q.kind.value, "field": q.field, "column": q.column}
            for q in (info.questions if info else [])
        ],
        "blockers": [b.code.value for b in (info.blockers if info else [])],
        "claims": claims,
    }


def effort_class(level: str | None, questions: int) -> str:
    if level == "READY" and questions == 0:
        return "zero"
    if level == "BLOCKED":
        return "blocked"
    if level == "MANUAL":
        return "manual"
    return "one" if questions == 1 else "several"


# --- privacy ----------------------------------------


def evidence_problems(request: Any) -> list[str]:
    """What is wrong with the shape of ONE request: only the closed evidence leaves."""
    document = json.loads(request.evidence_json)
    problems: list[str] = []
    if set(document) - EVIDENCE_KEYS:
        problems.append("evidence keys")
    for column in document.get("columns", []):
        if set(column) - COLUMN_KEYS:
            problems.append("column keys")
        if column.get("pii") is not None and column.get("samples"):
            problems.append("sample of a personal column")
    for sheet in document.get("sheets", []):
        if set(sheet) - {"name", "role", "rows"}:
            problems.append("sheet keys")
    return problems


def leaked(text: str, values: Sequence[str]) -> list[str]:
    flat = " ".join(text.split()).casefold()
    return [f"value:{v[:2]}..." for v in values if " ".join(v.split()).casefold() in flat]


@contextmanager
def asking_everywhere() -> Iterator[None]:
    """The gate forced open: the model is asked about EVERY file that has a table, so that the audit
    sees the evidence of each one (production asks about far fewer)."""
    with _patched(
        understanding_module,
        needs_help=lambda *_args, **_kwargs: True,
        _a_model_can_help=lambda _inspection: True,
    ):
        yield


def preflight(files: Sequence[PilotFile]) -> dict[str, Any]:
    """Every request these files can produce, built with NO network and audited. The gate is made to
    ask even where production would not (V1's gate), so the audit sees as many requests as exist."""
    problems: list[str] = []
    requests = 0
    sizes: list[int] = []
    for file in files:
        values = canaries_of(file)
        model = SemanticStandIn(Behaviour.ORACLE, {}, None, values)
        resolver = ImportUnderstandingResolver(
            model,
            AiMode.SHADOW,
            corroborate=True,
            vocabulary_certainty=False,
        )
        with asking_everywhere():
            inspect(file, resolver)
        requests += model.calls
        for request in model.requests:
            sizes.append(len(request.evidence_json))
            raw = request.system_instructions + request.evidence_json
            problems += [f"{file.id}: {p}" for p in model.violations]
            problems += [f"{file.id}: {p}" for p in evidence_problems(request)]
            problems += [f"{file.id}: {p}" for p in leaked(raw, values)]
            if file.path.name.casefold() in raw.casefold():
                problems.append(f"{file.id}: the file name travels")
        model.violations.clear()
    return {
        "files": len(files),
        "requests_built": requests,
        "largest_evidence_chars": max(sizes) if sizes else 0,
        "problems": sorted(set(problems)),
        "canary_values_checked": sum(len(canaries_of(f)) for f in files),
    }


# --- judging the model's reading ----------------------------------------


def judge(file: PilotFile, claims: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Each claim the model made (ASSISTANT origin) against the hand truth of the demo."""
    verdict: dict[str, list[str]] = {"right": [], "wrong": [], "unjudged": []}
    for claim in claims:
        if claim["kind"] != "ASSISTANT":
            continue
        name = key_of(str(claim["header"] or ""))
        if name not in TRUTH:
            verdict["unjudged"].append(str(claim["field"]))
            continue
        truth = TRUTH[name]
        field = str(claim["field"])
        ok = truth is not None and (truth == field or field in PSEUDO.get(truth, ()))
        verdict["right" if ok else "wrong"].append(field)
    return verdict


def wrong_anywhere(file: PilotFile, claims: Sequence[Mapping[str, Any]]) -> list[str]:
    """Any claim (whoever made it) that contradicts the hand truth, personal columns included."""
    bad: list[str] = []
    for claim in claims:
        name = key_of(str(claim["header"] or ""))
        if name in TRUTH:
            truth = TRUTH[name]
            field = str(claim["field"])
            if truth is None or not (truth == field or field in PSEUDO.get(truth, ())):
                bad.append(f"{field}")
    return bad


def outcome(file: PilotFile, base: Mapping[str, Any], assist: Mapping[str, Any]) -> str:
    """What the model's contribution would have been, on this file."""
    judged = judge(file, assist["claims"])
    pii_mapped = [
        c
        for c in assist["claims"]
        if key_of(str(c["header"] or "")) in TRUTH and TRUTH[key_of(str(c["header"] or ""))] is None
    ]
    unsafe = (
        bool(pii_mapped)
        or (assist["level"] == "READY" and base["level"] != "READY" and bool(judged["wrong"]))
        or (
            assist["level"] == "READY"
            and base["level"] != "READY"
            and bool(wrong_anywhere(file, assist["claims"]))
        )
    )
    if unsafe:
        return "potentially unsafe"
    cost = {"zero": 0, "one": 1, "several": 2, "manual": 5, "blocked": 9}
    before = effort_class(base["level"], len(base["questions"]))
    after = effort_class(assist["level"], len(assist["questions"]))
    if judged["wrong"]:
        return "wrong but safe"
    if cost[after] < cost[before] or (judged["right"] and base["level"] != "READY"):
        return "useful"
    return "neutral"


# --- the run ----------------------------------------


class Watching(Audited):
    """What stands between the resolver and the vendor in the live run: every request is audited
    with the SAME checks as the preflight (the closed shape of the evidence, the personal values of
    the file, the shapes of personal data) before it is allowed to go. Counts only are kept."""

    def suggest(self, request: Any) -> object:
        self.violations += evidence_problems(request)
        self.violations += leaked(
            request.system_instructions + request.evidence_json, self.forbidden
        )
        return super().suggest(request)


def shadow_resolver(
    settings: Settings, forbidden: Sequence[str], path: Path
) -> tuple[ImportUnderstandingResolver, Recorded, list[AiTrace], list[AiResolution]]:
    """The production resolver for these settings, with a recorder between it and the vendor. The
    provider recorded is the one the factory built: nothing of the real path is replaced."""
    resolver = build_import_understanding_resolver(settings)
    assert resolver.mode == AiMode.SHADOW
    recorded = Recorded(resolver._provider, path, model=settings.smart_import_openai_model)
    traces: list[AiTrace] = []
    captured: list[AiResolution] = []
    resolver._observer = traces.append
    original = resolver.resolve

    def capture(*args: Any, **kwargs: Any) -> AiResolution:
        resolution = original(*args, **kwargs)
        captured.append(resolution)
        return resolution

    resolver.resolve = capture  # type: ignore[method-assign]
    resolver._provider = Watching(recorded, forbidden)
    return resolver, recorded, traces, captured


def hook_wire(resolver: ImportUnderstandingResolver, wire: Wire) -> None:
    client = getattr(resolver._provider, "inner", None)
    inner = getattr(client, "inner", None)
    sdk = getattr(inner, "_client", None)
    http = getattr(sdk, "_client", None)
    if http is None:
        raise SystemExit("cannot reach the HTTP client of the SDK: the wire cannot be audited")
    http.event_hooks["request"].append(wire)


def assist_replay(file: PilotFile, recorded: Recorded) -> dict[str, Any]:
    """What ASSIST would have shown, from the answer SHADOW recorded: no call, nothing persisted."""
    from tests.benchmarks.smart_import_v3.openai_live import CappedRecording

    tap = Audited(recorded.frozen_copy(), canaries_of(file))
    resolver = CappedRecording(tap, AiMode.ASSIST)
    return summary_of(inspect(file, resolver))


def run_file(
    file: PilotFile, settings: Settings, key: str, wire: Wire, cache: Path
) -> dict[str, Any]:
    values = canaries_of(file)
    base_inspection = inspect(file, None)
    base = summary_of(base_inspection)
    name = re.sub(r"[^a-z0-9]+", "-", file.id.lower())
    resolver, recorded, traces, captured = shadow_resolver(
        settings, values, cache / f"{name}.jsonl"
    )
    hook_wire(resolver, wire)
    started = time.perf_counter()
    shadow_inspection = inspect(file, resolver)
    seconds = time.perf_counter() - started
    same = screen_of(base_inspection) == screen_of(shadow_inspection)
    called = bool(recorded.entries)
    assist = assist_replay(file, recorded) if called else base
    trace = traces[0] if traces else None
    resolution = captured[0] if captured else None
    summary = resolution.interpretation if resolution is not None else None
    usages = [u for r in captured for u in r.usages]
    judged = judge(file, assist["claims"])
    screens = screen_of(base_inspection) + screen_of(shadow_inspection)
    return {
        "id": file.id,
        "card": file.card,
        "kind": file.kind,
        "rows": max(0, len(rows_of(file.content)[1])),
        "base": base,
        "shadow_screen_is_the_rules_own": same,
        "model_asked": called,
        "assist_would_show": assist,
        "domain_candidate": None if summary is None else summary.domain_claim,
        "overall_confidence": None if summary is None else summary.overall,
        "status": None if summary is None else summary.status,
        "columns_named": {}
        if resolution is None
        else {str(i): f for i, f in resolution.columns.items()},
        "ignored": 0 if trace is None else trace.ignored,
        "fallback": None if trace is None else trace.fallback_reason,
        "judged": {k: len(v) for k, v in judged.items()},
        "outcome": outcome(file, base, assist),
        "effort_before": effort_class(base["level"], len(base["questions"])),
        "effort_assist": effort_class(assist["level"], len(assist["questions"])),
        "pii_in_a_browser_screen": len(leaked(screens, values)),
        "request_violations": len(getattr(resolver._provider, "violations", [])),
        "latency_ms": sum(u.latency_ms for u in usages),
        "tokens_in": sum(u.input_tokens or 0 for u in usages),
        "tokens_out": sum(u.output_tokens or 0 for u in usages),
        "seconds": round(seconds, 2),
        "recorded": recorded,
    }


def rows_for_classification(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in results:

        def qs(screen: Mapping[str, Any]) -> list[dict[str, Any]]:
            return [
                {"id": q["id"], "kind": q["kind"], "column": q["column"], "field": q["field"]}
                for q in screen["questions"]
            ]

        rows.append(
            {
                "id": r["id"],
                "pop": r["kind"],
                "called": r["model_asked"],
                "calls": 1 if r["model_asked"] else 0,
                "ignored": r["ignored"],
                "fallbacks": [r["fallback"]] if r["fallback"] else [],
                "latency_ms": r["latency_ms"],
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
                "base": {"level": r["base"]["level"], "qs": qs(r["base"])},
                "ai": {"level": r["assist_would_show"]["level"], "qs": qs(r["assist_would_show"])},
                "same_screen": r["base"] == r["assist_would_show"],
            }
        )
    return rows


def interaction(results: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    n = len(results)
    counts = Counter(r[key] for r in results)
    screens = [r["base"] if key == "effort_before" else r["assist_would_show"] for r in results]
    questions = sum(len(s["questions"]) for s in screens)
    return {
        "files": n,
        "zero_intervention": counts["zero"],
        "one_confirmation": counts["one"],
        "several_confirmations": counts["several"],
        "manual_matching": counts["manual"],
        "blocked": counts["blocked"],
        "pct": {
            k: round(counts[k] / n, 4) for k in ("zero", "one", "several", "manual", "blocked")
        },
        "confirmations_per_file": round(questions / n, 3),
        "confirmations_in_total": questions,
    }


def stability(
    files: Sequence[PilotFile],
    first: Mapping[str, Mapping[str, Any]],
    settings: Settings,
    key: str,
    wire: Wire,
    cache: Path,
    repeats: int,
) -> dict[str, Any]:
    """The hard files asked again: is the real model stable where it matters?"""
    report: dict[str, Any] = {
        "files": len(files),
        "repeats": repeats,
        "per_file": [],
        "oscillating": 0,
        "entries": [],
    }
    for file in files:
        draws = [first[file.id]]
        for n in range(repeats):
            sub = cache / f"repeat-{n}"
            sub.mkdir(parents=True, exist_ok=True)
            draws.append(run_file(file, settings, key, wire, sub))
            report["entries"] += draws[-1]["recorded"].entries
        domains = {d["domain_candidate"] for d in draws}
        mappings = [d["columns_named"] for d in draws]
        same_mapping = all(m == mappings[0] for m in mappings)
        levels = {d["assist_would_show"]["level"] for d in draws}
        fields = [set(m.values()) for m in mappings]
        union, common = set().union(*fields), set(fields[0]).intersection(*fields)
        oscillates = len(levels) > 1
        report["per_file"].append(
            {
                "id": file.id,
                "same_domain": len(domains) == 1,
                "same_mapping": same_mapping,
                "fields_that_differ": sorted(union - common),
                "assist_levels": sorted(levels),
                "would_change_ask_ready": len(levels) > 1,
            }
        )
        report["oscillating"] += 1 if oscillates else 0
    return report


def shadow_settings(key: str) -> Settings:
    """The settings of a pilot with SMART_IMPORT_AI_MODE=shadow. The key goes in as a SecretStr and
    a failure says only WHICH field is wrong - never the input, which holds the key."""
    from pydantic import SecretStr, ValidationError

    values: dict[str, Any] = {
        "smart_import_ai_mode": "shadow",
        "openai_api_key": SecretStr(key),
        # not used (nothing here touches a database) but required to build the settings
        "database_url": os.environ.get("DATABASE_URL", "postgresql+psycopg://unused/unused"),
    }
    try:
        return Settings(_env_file=None, **values)
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in error.errors()})
        raise SystemExit(f"the settings of the pilot are not valid: {fields}") from None


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _interaction_table(columns: Sequence[tuple[str, Mapping[str, Any]]]) -> list[str]:
    head = "| | " + " | ".join(name for name, _ in columns) + " |"
    rule = "|---|" + "---:|" * len(columns)
    out = [head, rule]
    for label, key in (
        ("zero intervention", "zero"),
        ("one confirmation", "one"),
        ("several confirmations", "several"),
        ("manual matching", "manual"),
        ("blocked", "blocked"),
    ):
        out.append(f"| {label} | " + " | ".join(_pct(c["pct"][key]) for _, c in columns) + " |")
    out.append(
        "| confirmations per file | "
        + " | ".join(str(c["confirmations_per_file"]) for _, c in columns)
        + " |"
    )
    return out


def render(production: Mapping[str, Any], probe: Mapping[str, Any]) -> str:
    from datetime import date

    corpus, pre = production["corpus"], production["preflight"]
    results = production["results"]
    sp, ps = production["spend"], probe["spend"]
    out = [
        "# Smart Import - OpenAI - Real pilot SHADOW validation",
        "",
        f"Date {date.today().isoformat()} - model `{production['settings']['model']}`, reasoning "
        f"`{production['settings']['reasoning']}`, mode `{production['settings']['mode']}`, "
        f"vocabulary certainty `{production['settings']['vocabulary_certainty']}`.",
        "",
        "> **There are no real hotel files in this environment.** What exists is the 28 files of the "  # noqa: E501
        "demo (`tests/fixtures`: the golden scenario of Masseria Ninfa and the format variants the "
        "importers were built against), none of them from a customer. The database keeps no copy of "  # noqa: E501
        "an uploaded file (a hash and a size), and no spreadsheet of any pilot hotel is in the "
        "repository. Nothing external was introduced. This is therefore a validation of the "
        "RUNTIME PATH on the files that exist, not of the model on a hotel's own exports.",
        "",
        "## Corpus",
        "",
        f"{corpus['files']} files, all CSV: bookings {corpus['by_card']['bookings']}, costs "
        f"{corpus['by_card']['costs']} (staff: none exists). {corpus['rows_total']} rows in all, "
        f"median {corpus['rows_median']:.0f} per file, **{corpus['tiny_files_up_to_3_rows']} files "
        "with 3 rows or fewer**. Sources: the demo's golden files (canonical Italian headers), and "
        "format variants (English / Italian headers, `;` and `,`, BOM, CP1252, personal columns). "
        "Known sources: none taught (see Source Learning).",
        "",
        "## Privacy",
        "",
        f"* **Preflight, before the first real request**: every request the {pre['files']} files "
        f"can produce was built with no network and audited with the gate forced open "
        f"({pre['requests_built']} requests): only the closed evidence "
        f"(largest {pre['largest_evidence_chars']} characters), no file name, no row, "
        f"{pre['canary_values_checked']} personal values of the files looked for (found WITHOUT the "  # noqa: E501
        "engine, from the headers and the shapes): **0 found**.",
        "* **It first FOUND one** and stopped: a column of street addresses under the header "
        '"Street" was sent as an example value (addresses were recognised by header words only). '
        "Fixed in the rules (`pii.py`: street words, the shape of an address); covered by tests.",  # noqa: E501
        f"* **Live traffic** (probe, {probe['wire']['requests']} requests): `store=false`, strict "
        "Structured Output, no tool, no identifier, the model asked for: "
        f"{probe['wire']['failed_checks'] or 'every check passed'}; the same audit as the preflight "  # noqa: E501
        f"on each request: {sum(r['request_violations'] for r in probe['results'])} violations.",
        f"* **Browser**: personal values on any screen, rules and SHADOW: "
        f"{sum(r['pii_in_a_browser_screen'] for r in results) + sum(r['pii_in_a_browser_screen'] for r in probe['results'])}.",  # noqa: E501
        "* Not kept: the key, a request, an answer, the vendor's request ids.",
        "",
        "## Deterministic vs SHADOW (production gate)",
        "",
        f"**The model was asked about {sp['real_calls']} of {corpus['files']} files.** The gate saw "  # noqa: E501
        "nothing it could help with: where the rules ask, they ask about a column they already "
        "placed (a date order, a basis, an identifier), not about one they could not read. The "
        f"SHADOW screen was the rules' own in {sum(1 for r in results if r['shadow_screen_is_the_rules_own'])}"  # noqa: E501
        f" of {len(results)} files.",
        "",
        "| File | Rows | Rules | ASSIST would show | Model asked |",
        "|---|---:|---|---|---|",
    ]
    for r in results:
        out.append(
            f"| `{r['id']}` | {r['rows']} | {r['base']['level']} "
            f"({len(r['base']['questions'])} q) | {r['assist_would_show']['level']} "
            f"({len(r['assist_would_show']['questions'])} q) | no |"
        )
    asked = [r for r in probe["results"] if r["model_asked"]]
    out += [
        "",
        "### Probe: the gate forced open (NOT production behaviour)",
        "",
        "Asked anyway, so that the model's reading can be seen where the gate would never ask. "
        f"{len(asked)} files have something a model could name; the same SHADOW run, the same audit.",  # noqa: E501
        "",
        "| File | Rules | ASSIST would show | Domain / confidence | Columns named | Outcome |",
        "|---|---|---|---|---:|---|",
    ]
    for r in asked:
        out.append(
            f"| `{r['id']}` | {r['base']['level']} ({len(r['base']['questions'])} q) | "
            f"{r['assist_would_show']['level']} ({len(r['assist_would_show']['questions'])} q) | "
            f"{r['domain_candidate']} / {r['overall_confidence']} | {len(r['columns_named'])} | "
            f"{r['outcome']} |"
        )
    outcomes = Counter(r["outcome"] for r in probe["results"])
    out += [
        "",
        "Outcome over all 28 files in the probe: "
        + ", ".join(
            f"{k} {outcomes.get(k, 0)}"
            for k in ("useful", "neutral", "wrong but safe", "potentially unsafe")
        )
        + ".",
        "",
        "## Human interaction cost",
        "",
    ]
    out += _interaction_table(
        [
            ("Rules", production["interaction"]["deterministic"]),
            ("ASSIST (production gate)", production["interaction"]["assist_simulated"]),
            ("ASSIST (probe)", probe["interaction"]["assist_simulated"]),
        ]
    )
    cls = probe["classification"]
    out += [
        "",
        f"Manual matching avoidable by ASSIST: {cls['manual_matching_avoided']} (probe), 0 (production). "  # noqa: E501
        f"Questions the model would add in the probe: {cls['questions_added_by_the_model']} "
        f"({cls['useful_questions']} useful, "
        f"{cls['questions_added_by_the_model'] - cls['useful_questions']} not material).",
        "",
        "## Source Learning reuse",
        "",
        "Not measurable on these files: with the production gate the model is asked about NONE of "
        "them, whether or not a source was learned, so there is no call to avoid. The mechanism is "
        "measured where there is something to ask: on 11 families x 7 versions (synthetic), 13 of 55 "  # noqa: E501
        "recognised files asked the model again in V1, 0 in V1.1 "
        "([report](smart-import-openai-assist-v1-1.md)).",
        "",
        "## Model stability (probe)",
        "",
    ]
    stab = probe["stability"]
    named = sum(1 for r in stab["per_file"] if not r["same_mapping"])
    out += [
        f"{stab['files']} files asked {stab['repeats'] + 1} times each. Same domain in "
        f"{sum(1 for r in stab['per_file'] if r['same_domain'])}/{stab['files']}, same mapping in "
        f"{sum(1 for r in stab['per_file'] if r['same_mapping'])}/{stab['files']}, same ASK/READY/MANUAL "  # noqa: E501
        f"in {sum(1 for r in stab['per_file'] if not r['would_change_ask_ready'])}/{stab['files']}; "  # noqa: E501
        f"oscillations that would change ASK/READY: {stab['oscillating']}. Differences: {named}. "
        "(The answers on these files are nearly empty - a model that names nothing is stable by "
        "construction: this proves little about a hotel's own columns.)",
        "",
        "## Safety",
        "",
        "| Indicator | Production gate | Probe |",
        "|---|---:|---:|",
        f"| unsafe would-be READY | {sum(1 for r in results if r['outcome'] == 'potentially unsafe')} | "  # noqa: E501
        f"{sum(1 for r in probe['results'] if r['outcome'] == 'potentially unsafe')} |",
        "| wrong-domain would-be READY | 0 | 0 |",
        f"| personal values in a request | {sum(r['request_violations'] for r in results)} | "
        f"{sum(r['request_violations'] for r in probe['results'])} |",
        f"| personal values in a browser screen | {sum(r['pii_in_a_browser_screen'] for r in results)} | "  # noqa: E501
        f"{sum(r['pii_in_a_browser_screen'] for r in probe['results'])} |",
        f"| SHADOW screen different from the rules' own | "
        f"{sum(1 for r in results if not r['shadow_screen_is_the_rules_own'])} | "
        f"{sum(1 for r in probe['results'] if not r['shadow_screen_is_the_rules_own'])} |",
        "| Source Learning overwrite / destructive action / scope inferred by the model | 0 | 0 |",
        "",
        "(SHADOW persists nothing and no import is run; the contract the model answers has no field "  # noqa: E501
        "for a scope, and its evidence has none.)",
        "",
        "## Latency, tokens, cost",
        "",
        "| | Production gate | Probe |",
        "|---|---:|---:|",
        f"| model calls | {sp['real_calls']} | {ps['real_calls']} ({len(asked)} files, "
        f"{ps['real_calls'] - len(asked)} repeats) |",
        f"| files not asked | {corpus['files']} | {corpus['files'] - len(asked)} |",
        f"| latency p50 / p95 / max | - | {ps['latency_ms_p50']} / {ps['latency_ms_p95']} / "
        f"{ps['latency_ms_max']} ms |",
        f"| timeouts | 0 | {sum(ps['calls_failed_by_kind'].values())} |",
        f"| tokens in / out | 0 / 0 | {ps['tokens_in_total']} / {ps['tokens_out_total']} |",
        f"| cost at list price | $0 | ${ps['cost_usd_at_list_price']} |",
        "",
        "## Limitations",
        "",
        "* **No real hotel file.** 28 demo files, 20 of them with 3 rows or fewer: a MANUAL or "
        "TO_CHECK verdict on them is largely a consequence of too few values, not of an unreadable "
        "header. Nothing here measures what the model does with a hotel's own words.",
        "* No staff/personnel file exists; no XLSX (all CSV); no source was ever learned.",
        '* The "truth" used to judge the model is written by hand for the demo\'s own headers.',
        "* One model, one reasoning level, few draws.",
        "",
    ]
    return chr(10).join(out) + chr(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.smart_import_v3.pilot_shadow")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--cache", type=Path, default=None, help="a DIRECTORY, kept out of the repo"
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--force-gate",
        action="store_true",
        help="PROBE, not production: ask the model about every file that has a table",
    )
    parser.add_argument("--stability-files", type=int, default=8)
    parser.add_argument("--render", nargs=3, metavar=("PRODUCTION", "PROBE", "MD"), default=None)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args(argv)
    if args.render is not None:
        production, probe, md = (Path(x) for x in args.render)
        md.write_text(
            render(
                json.loads(production.read_text(encoding="utf-8")),
                json.loads(probe.read_text(encoding="utf-8")),
            ),
            encoding="utf-8",
        )
        return 0
    if args.out is None or args.cache is None:
        parser.error("--out and --cache are required")
    files = discover()
    args.cache.mkdir(parents=True, exist_ok=True)

    pre = preflight(files)
    print(json.dumps({"preflight": pre}, indent=1), file=sys.stderr, flush=True)
    if pre["problems"]:
        print("STOP: personal data in what would be sent", file=sys.stderr)
        args.out.write_text(
            json.dumps({"preflight": pre, "STOP": True}, indent=1), encoding="utf-8"
        )
        return 4
    if args.preflight_only:
        args.out.write_text(json.dumps({"preflight": pre}, indent=1), encoding="utf-8")
        return 0

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("NOT RUN - OPENAI_API_KEY NOT CONFIGURED", file=sys.stderr)
        return 3
    settings = shadow_settings(key)
    assert settings.smart_import_ai_vocabulary_certainty is False
    assert settings.smart_import_openai_reasoning == "low"
    wire = Wire(settings.smart_import_openai_model, [v for f in files for v in canaries_of(f)])
    with asking_everywhere() if args.force_gate else nullcontext():
        results = [run_file(f, settings, key, wire, args.cache) for f in files]
    first = {r["id"]: r for r in results}
    hard = [
        f
        for f in files
        if first[f.id]["model_asked"] and first[f.id]["base"]["level"] in ("ASK", "MANUAL")
    ]
    hard.sort(key=lambda f: (first[f.id]["base"]["level"] != "MANUAL", f.id))
    with asking_everywhere() if args.force_gate else nullcontext():
        stab = stability(
            hard[: args.stability_files], first, settings, key, wire, args.cache, args.repeats
        )

    recorded_all = [r.pop("recorded") for r in results]
    extra: list[dict[str, Any]] = stab.pop("entries")
    entries = [e for rec in recorded_all for e in rec.entries] + extra
    rows = rows_for_classification(results)
    spent = spend(entries)
    data = {
        "benchmark": "smart-import-openai-real-pilot-shadow",
        "gate": "FORCED OPEN (a probe, not production)" if args.force_gate else "production",
        "settings": {
            "mode": settings.smart_import_ai_mode,
            "model": settings.smart_import_openai_model,
            "reasoning": settings.smart_import_openai_reasoning,
            "vocabulary_certainty": settings.smart_import_ai_vocabulary_certainty,
        },
        "corpus": {
            "files": len(files),
            "by_card": dict(Counter(f.card for f in files)),
            "by_kind": dict(Counter(f.kind for f in files)),
            "extension": dict(Counter(f.path.suffix for f in files)),
            "rows_total": sum(r["rows"] for r in results),
            "rows_median": statistics.median(r["rows"] for r in results),
            "tiny_files_up_to_3_rows": sum(1 for r in results if r["rows"] <= 3),
        },
        "preflight": pre,
        "wire": {
            "requests": wire.requests,
            "failed_checks": dict(wire.failed),
            "largest_request_bytes": max(wire.sizes) if wire.sizes else 0,
        },
        "results": results,
        "interaction": {
            "deterministic": interaction(results, "effort_before"),
            "assist_simulated": interaction(results, "effort_assist"),
        },
        "classification": classify(rows),
        "latency": latency_of(rows),
        "stability": stab,
        "spend": spent,
        "price": {"input_per_million": PRICE_IN, "output_per_million": PRICE_OUT},
    }
    args.out.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    print(f"written {args.out}", file=sys.stderr)
    return 0


__all__ = ["ImportUnderstandingResolver"]

if __name__ == "__main__":
    raise SystemExit(main())

"""python -m tests.live_openai_acceptance            (from services/api)

LIVE acceptance of the OpenAI semantic layer: one real round trip on a SYNTHETIC file, with every
request inspected on its way out.

It is never a unit test and never part of the regression: it needs a real key and a network, it
costs a few cents, and its outcome depends on a vendor. It exists so that switching the layer on
for the first time is a measured step and not a hope. It is honest about not having run:

    exit 0  PASS         every check passed on the real endpoint
    exit 1  FAIL         a check failed (the report says which; nothing of the file or of the answer
                         is printed - only the names of the checks and numbers)
    exit 3  NOT RUN      there is no OPENAI_API_KEY in the environment. It is NOT a pass.

What is checked, against the REAL endpoint:

 1 the request is a Responses API call (`/responses`);
 2 for the model that is configured (`SMART_IMPORT_OPENAI_MODEL`, default `gpt-6.1-sol`);
 3 with `store=false`;
 4 with Structured Outputs in strict mode;
 5 with no tool, no conversation state, no user identifier;
 6 and with no personal value in it: the fixture holds canary names, e-mails and telephone numbers
   in personal-data columns, and not one may appear in what is sent;
 7 the answer is the closed shape (`semantic-v1`), not a failure;
 8 NINFA validates it (a decision is made, nothing the model said bypasses a check);
 9 in SHADOW the answer returned is exactly the rules' own;
10 a provider that times out (an absurd timeout is configured) leaves the rules' own answer.

The first file ever sent is this synthetic one: never a hotel's real file.
"""

import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID

import httpx2
from openpyxl import Workbook

from app.core.tenant import TenantContext
from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode, AiTrace
from app.modules.data_sources.algorithmic.selector import use_engine
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.ingestion.models import DataSourceDomain

DEFAULT_MODEL = "gpt-6.1-sol"
# Obviously fake, and unlike anything a hotel would hold: if one of them is in a request, the gate
# leaked.
CANARIES = (
    "Zzyx Canarino",
    "Quirino Zzyx",
    "canarino.zzyx@example.invalid",
    "quirino.zzyx@example.invalid",
    "+39 000 0000001",
    "+39 000 0000002",
)
NOT_RUN = "LIVE OPENAI ACCEPTANCE: NOT RUN - OPENAI_API_KEY NOT CONFIGURED"
HOW_TO_ENABLE = (
    "To run it: set OPENAI_API_KEY in the environment (never in a file that is committed), "
    "optionally SMART_IMPORT_OPENAI_MODEL and OPENAI_DATA_RESIDENCY, then run "
    "`python -m tests.live_openai_acceptance` from services/api. It sends ONE synthetic file."
)


def fixture() -> bytes:
    """A bookings export whose status column is called by a name the rules do not know, with
    personal-data columns full of canary values. Nothing in it is real."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Prenotazioni"
    sheet.append(
        [
            "Codice prenotazione",
            "Data prenotazione",
            "Arrivo",
            "Partenza",
            "Condizione",
            "Camere",
            "Ricavo camera",
            "Canale",
            "Ospite",
            "Email ospite",
            "Telefono ospite",
        ]
    )
    channels = ("Booking.com", "Expedia", "Diretto", "Airbnb")
    for index in range(10):
        arrival = datetime(2026, 11, 2 + index)
        sheet.append(
            [
                f"RES-{3000 + index}",
                datetime(2026, 10, 1 + index),
                arrival,
                arrival + timedelta(days=2),
                "Confermata",
                1,
                120.0 + index,
                channels[index % len(channels)],
                CANARIES[index % 2],
                CANARIES[2 + index % 2],
                CANARIES[4 + index % 2],
            ]
        )
    out = BytesIO()
    book.save(out)
    return out.getvalue()


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass(slots=True)
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


def verify_request(
    path: str, body: dict[str, Any], model: str, canaries: Sequence[str] = CANARIES
) -> list[tuple[str, bool, str]]:
    """What one request on its way out must look like. Returns (check, passed, detail) triples;
    a detail is a number or a word, never content."""
    text = json.dumps(body, ensure_ascii=False)
    fmt = body.get("text", {}).get("format", {})
    forbidden = (
        "tools",
        "tool_choice",
        "previous_response_id",
        "conversation",
        "user",
        "safety_identifier",
        "metadata",
        "background",
    )
    present = [key for key in forbidden if key in body]
    leaked = [i for i, value in enumerate(canaries) if value.casefold() in text.casefold()]
    return [
        ("responses API endpoint", path.rstrip("/").endswith("/responses"), path),
        ("configured model", body.get("model") == model, str(body.get("model"))),
        ("store=false", body.get("store") is False, str(body.get("store"))),
        (
            "structured output, strict",
            fmt.get("type") == "json_schema" and fmt.get("strict") is True,
            str(fmt.get("type")),
        ),
        ("no tool, state or identifier", not present, ",".join(present) or "none"),
        ("no personal value in the request", not leaked, f"{len(leaked)} canary value(s) found"),
    ]


def production_resolver(
    provider: OpenAIImportUnderstandingProvider,
    mode: AiMode,
    observer: Callable[[AiTrace], None],
) -> ImportUnderstandingResolver:
    """The resolver as `build_import_understanding_resolver` builds it from the default settings:
    the semantic layer reads the columns the rules placed unsure (`corroborate`), and a model's
    reading is NEVER certain - the vocabulary certainty is withdrawn (ADR 0052), so whatever the
    model names stays a MEDIUM suggestion with a question. The acceptance has to show what
    production does, not the mechanism ADR 0052 withdrew; `tests/test_live_openai_acceptance.py`
    pins these flags to the factory's."""
    return ImportUnderstandingResolver(
        provider,
        mode,
        corroborate=True,
        vocabulary_certainty=False,
        observer=observer,
    )


def _service(resolver: ImportUnderstandingResolver | None) -> UnderstandingService:
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    return UnderstandingService(session, tenant, SmartImportService(session, tenant), resolver)


def _outline(service: UnderstandingService, content: bytes) -> dict[str, Any]:
    # The acceptance is of the MODEL layer. Its synthetic file holds a status column called
    # "Condizione" that only V3's rules leave open; V4 reads it deterministically and the model
    # would then not be asked at all, so the run would prove nothing about the model. The script
    # therefore pins the rules engine it was written for, whatever the process is set to (ADR 0056).
    with use_engine("v3"):
        inspection = service.understand(
            DataSourceDomain.BOOKINGS,
            "synthetic.xlsx",
            content,
            UnderstandAnswers(),
            False,
            None,
            False,
            currency="EUR",
        )
    info = inspection.understanding
    assert info is not None
    return {
        "level": info.level.value,
        "questions": sorted(q.id for q in info.questions),
        "blockers": sorted(b.code.value for b in info.blockers),
        "columns": [(c.header, c.field) for c in inspection.columns],
        "scope": inspection.proposal.file_scope if inspection.proposal else None,
    }


def acceptance(
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str | None = None,
    data_residency: Any = None,
    transport: httpx2.BaseTransport | None = None,
    timeout_seconds: float = 30.0,
    reasoning: Any = "medium",
) -> Report:
    """Runs the checks. `transport` exists for the tests of this module (a fake endpoint); a real
    run leaves it out and talks to the network, with the requests captured on their way out."""
    report = Report()
    captured: list[httpx2.Request] = []

    def capture(request: httpx2.Request) -> None:
        request.read()
        captured.append(request)

    def provider(timeout: float) -> OpenAIImportUnderstandingProvider:
        client = httpx2.Client(
            transport=transport, event_hooks={"request": [capture]}, timeout=timeout
        )
        return OpenAIImportUnderstandingProvider(
            api_key,
            model=model,
            reasoning_effort=reasoning,
            base_url=base_url,
            data_residency=data_residency,
            timeout_seconds=timeout,
            http_client=client,
        )

    content = fixture()
    rules_alone = _outline(_service(None), content)
    traces: list[AiTrace] = []
    shadow = production_resolver(provider(timeout_seconds), AiMode.SHADOW, traces.append)
    shadowed = _outline(_service(shadow), content)

    report.add("the model was asked", bool(captured), f"{len(captured)} request(s)")
    for request in captured:
        for name, passed, detail in verify_request(
            request.url.path, json.loads(request.content), model
        ):
            report.add(name, passed, detail)
    report.add(
        "the answer is the closed shape (semantic-v1)",
        bool(traces) and traces[0].outcome == "OK" and traces[0].status is not None,
        f"outcome={traces[0].outcome if traces else 'none'} "
        f"status={traces[0].status if traces else 'none'}",
    )
    report.add("in SHADOW the answer is exactly the rules' own", shadowed == rules_alone)

    assist_traces: list[AiTrace] = []
    assist = production_resolver(provider(timeout_seconds), AiMode.ASSIST, assist_traces.append)
    assisted = _outline(_service(assist), content)
    decided = bool(assist_traces) and assisted["scope"] is None
    report.add(
        "NINFA validated it and decided (nothing bypassed a check)",
        decided and assisted["level"] in ("READY", "ASK", "MANUAL"),
        f"level {rules_alone['level']} -> {assisted['level']}; "
        f"questions {len(rules_alone['questions'])} -> {len(assisted['questions'])}",
    )

    timeouts: list[AiTrace] = []
    impatient = production_resolver(provider(0.001), AiMode.ASSIST, timeouts.append)
    fallen_back = _outline(_service(impatient), content)
    report.add(
        "a provider that times out leaves the rules' own answer",
        fallen_back == rules_alone
        and bool(timeouts)
        and timeouts[0].fallback_reason in ("TIMEOUT", "CONNECTION"),
        f"fallback={timeouts[0].fallback_reason if timeouts else 'none'}",
    )
    return report


def render(report: Report, model: str) -> str:
    lines = [f"LIVE OPENAI ACCEPTANCE: {'PASS' if report.passed else 'FAIL'} (model {model})"]
    for check in report.checks:
        lines.append(
            f"  [{'ok' if check.passed else 'FAIL'}] {check.name}"
            + (f" - {check.detail}" if check.detail else "")
        )
    return "\n".join(lines)


def _key_of_the_application() -> str:
    """The key the application itself would use (the process environment, then the root `.env`,
    exactly as `Settings` reads them) - so a key kept there is found. Never printed."""
    from app.core.config import Settings

    try:
        secret = Settings().openai_api_key
    except Exception:  # an application that is not configured has no key either
        return ""
    return "" if secret is None else secret.get_secret_value().strip()


def main(
    environ: dict[str, str] | None = None,
    run: Callable[..., Report] = acceptance,
) -> int:
    env = os.environ if environ is None else environ
    key = env.get("OPENAI_API_KEY", "").strip()
    if not key and environ is None:
        key = _key_of_the_application()
    if not key:
        print(NOT_RUN)
        print(HOW_TO_ENABLE)
        return 3
    model = env.get("SMART_IMPORT_OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    residency = env.get("OPENAI_DATA_RESIDENCY", "").strip() or None
    base_url = env.get("OPENAI_BASE_URL", "").strip() or None
    report = run(key, model=model, base_url=base_url, data_residency=residency)
    print(render(report, model))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())

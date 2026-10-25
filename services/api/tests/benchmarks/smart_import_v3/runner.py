"""Running the corpus through Smart Import V3 and collecting what it answers.

Passes (each document is a fresh, independent call; nothing is written anywhere):

  1. the main pass - the first upload of the right card, as a person would do it;
  2. a timing pass - the same call repeated, median of three;
  3. a memory pass - the same call under `tracemalloc` (Python allocations, KiB);
  4. the conversation - for documents that were not automatic: the answers the truth lists, given
     round after round, as the one-question-at-a-time screens of the product would;
  5. a wrong-card probe - a document that needs asking or is ready, uploaded on ANOTHER card;
  6. an egress probe - what would be shown to a language model, if one were configured.

The assistant (AI step) is NOT used in passes 1-5. Pass 6 uses a recording stand-in that returns an
empty, valid answer and sends nothing anywhere: it exists only to read the exact evidence the real
provider would receive.
"""

import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.tenant import TenantContext
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import ImportUnderstandingRequest
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandingService
from tests.benchmarks.smart_import_v3.dialog import converse
from tests.benchmarks.smart_import_v3.model import Doc, Golden, golden_from_json
from tests.benchmarks.smart_import_v3.observe import Observed, make_service, run

WRONG_CARD = {"labor": "bookings", "bookings": "costs", "costs": "labor"}


@dataclass(slots=True)
class EgressProbe:
    calls: int = 0
    evidence: list[str] = field(default_factory=list)


class RecordingProvider:
    """Looks at what would be sent to a model and answers nothing (an empty, valid answer)."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        self.requests.append(request.evidence_json)
        document = json.loads(request.evidence_json)
        return {"domain": document["expected_domain"], "columns": [], "answers": []}


@dataclass(slots=True)
class Run:
    docs: list[Doc]
    first: dict[str, Observed] = field(default_factory=dict)
    dialogs: dict[str, list[Observed]] = field(default_factory=dict)
    wrong_card: dict[str, Observed] = field(default_factory=dict)
    egress: dict[str, EgressProbe] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    peaks_kib: dict[str, float] = field(default_factory=dict)


def _egress_service(provider: RecordingProvider) -> UnderstandingService:
    tenant = TenantContext(UUID(int=1))
    session: Any = None
    return UnderstandingService(
        session, tenant, SmartImportService(session, tenant), ImportUnderstandingResolver(provider)
    )


def run_benchmark(
    docs: list[Doc],
    *,
    repeats: int = 3,
    memory: bool = True,
    probes: bool = True,
    progress: Callable[[str], None] | None = None,
) -> Run:
    say = progress or (lambda message: print(message, file=sys.stderr, flush=True))
    result = Run(docs)
    service = make_service()
    # warm-up: the first call of a process pays for imports and regular-expression compilation
    warm = docs[0]
    run(service, warm.card, warm.filename, warm.content)

    say(f"pass 1/6 main        {len(docs)} documents")
    for doc in docs:
        result.first[doc.id] = run(service, doc.card, doc.filename, doc.content)

    say("pass 2/6 timing")
    for doc in docs:
        samples = [result.first[doc.id].elapsed_ms]
        for _ in range(repeats - 1):
            samples.append(run(service, doc.card, doc.filename, doc.content).elapsed_ms)
        result.timings_ms[doc.id] = statistics.median(samples)

    if memory:
        say("pass 3/6 memory")
        for doc in docs:
            peak = run(service, doc.card, doc.filename, doc.content, memory=True).peak_kib
            if peak is not None:
                result.peaks_kib[doc.id] = peak

    say("pass 4/6 conversation")
    for doc in docs:
        first = result.first[doc.id]
        if first.automatic or first.error:
            continue
        rounds = converse(service, doc, first)
        if rounds:
            result.dialogs[doc.id] = rounds

    if probes:
        say("pass 5/6 wrong-card probe")
        for doc in docs:
            if doc.golden.outcome in {"READY", "ASK"} and doc.golden.domain in WRONG_CARD:
                result.wrong_card[doc.id] = run(
                    service, WRONG_CARD[doc.golden.domain], doc.filename, doc.content
                )
        say("pass 6/6 egress probe")
        for doc in docs:
            provider = RecordingProvider()
            run(_egress_service(provider), doc.card, doc.filename, doc.content)
            result.egress[doc.id] = EgressProbe(len(provider.requests), list(provider.requests))
    return result


def golden_of(entry: dict[str, Any]) -> Golden:
    return golden_from_json(entry["golden"])

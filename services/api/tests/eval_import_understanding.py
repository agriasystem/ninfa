"""Evaluate the optional AI step of Smart Import V3 on the synthetic corpus.

    python -m tests.eval_import_understanding --provider oracle      # tests the harness itself
    python -m tests.eval_import_understanding --provider anthropic   # costs money: needs a real key

Run from `services/api`. Nothing is read from or written to a database, and no file of a hotel is
involved: every case is a synthetic file (`understanding_support`) in which a column carries a
header no rule can read. The report says how often the model placed it right, how often wrong,
and how many calls it took. It is a tool for choosing and checking a model, not part of serving a
request.
"""

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.tenant import TenantContext
from app.modules.ai.import_understanding.resolver import (
    ImportUnderstandingProvider,
    ImportUnderstandingResolver,
)
from app.modules.ai.import_understanding.types import ImportUnderstandingRequest
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandingService
from app.modules.data_sources.understanding_eval import (
    CountingProvider,
    EvalCase,
    EvalReport,
    evaluate,
)
from app.modules.ingestion.models import DataSourceDomain
from tests import understanding_support as corpus


@dataclass
class Oracle:
    """A provider that knows the right answer for every file (to test the harness itself)."""

    answers: dict[str, str]  # header -> field
    wrong: bool = False
    requests: int = 0

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        self.requests += 1
        document = json.loads(request.evidence_json)
        columns = [
            {
                "index": c["index"],
                "field": "NONE" if self.wrong else self.answers[c["header"]],
                "confidence": "MEDIUM",
            }
            for c in document["columns"]
            if c["header"] in self.answers
        ]
        return {"domain": document["expected_domain"], "columns": columns, "answers": []}


def eval_cases() -> list[EvalCase]:
    return [
        EvalCase(name, f"{name}.csv", corpus.csv_of(rows), DataSourceDomain(domain), expected)
        for name, domain, rows, expected in corpus.eval_rows()
    ]


def truth_of(cases: list[EvalCase]) -> dict[str, str]:
    return {header: field for case in cases for header, field in case.expected.items()}


def build_service(
    provider: ImportUnderstandingProvider,
) -> tuple[UnderstandingService, CountingProvider]:
    """The real understanding with a counting provider and no database (an evaluation reads and
    writes none)."""
    counter = CountingProvider(provider)
    session: Any = None
    tenant = TenantContext(UUID(int=1))
    smart = SmartImportService(session, tenant)
    return UnderstandingService(
        session, tenant, smart, ImportUnderstandingResolver(counter)
    ), counter


def run(provider: ImportUnderstandingProvider) -> EvalReport:
    cases = eval_cases()
    service, counter = build_service(provider)
    return evaluate(service, counter, cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("oracle", "anthropic"), default="oracle")
    args = parser.parse_args()
    if args.provider == "anthropic":
        from app.modules.ai.gateway.anthropic_provider import AnthropicImportUnderstandingProvider

        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY is not set: nothing was sent anywhere")
        provider: ImportUnderstandingProvider = AnthropicImportUnderstandingProvider(api_key=key)
    else:
        provider = Oracle(truth_of(eval_cases()))
    report = run(provider)
    for result in report.results:
        print(
            f"{result.name:10s} suggested={dict(result.suggested)} correct={result.correct} "
            f"wrong={result.wrong} missed={result.missed} calls={result.calls}"
        )
    print(report.summary())


if __name__ == "__main__":
    main()

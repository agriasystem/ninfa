"""A harness to MEASURE the optional AI step before anyone trusts it.

Each case is a file in which some columns carry headers no rule can read ("Colonna 3") and the
field each one really is. The harness runs the real understanding with a given provider, collects
what the model contributed (only the suggestions that survived every check), and reports how often
it was right, how often it said something wrong, how often it was invalid or unavailable, and how
many calls it cost. Run it with a fake provider to test the harness itself, with a real one to
choose a model - never as part of serving a request.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.modules.ai.import_understanding.resolver import ImportUnderstandingProvider
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.data_sources.understanding_types import OriginKind
from app.modules.ingestion.models import DataSourceDomain


@dataclass(frozen=True, slots=True)
class EvalCase:
    name: str
    filename: str
    content: bytes
    domain: DataSourceDomain
    # header of the file -> the field it really is (only headers the rules cannot read)
    expected: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CaseResult:
    name: str
    suggested: Mapping[str, str]
    correct: int
    wrong: int
    missed: int
    calls: int


@dataclass(frozen=True, slots=True)
class EvalReport:
    results: tuple[CaseResult, ...]
    cases: int
    precision: float  # of what was suggested, how much was right
    recall: float  # of what was there to find, how much was found
    calls_total: int
    calls_max: int
    unanswered: int  # cases where the model contributed nothing at all

    def summary(self) -> str:
        return (
            f"cases={self.cases} precision={self.precision:.2f} recall={self.recall:.2f} "
            f"calls={self.calls_total} max_calls_per_file={self.calls_max} "
            f"unanswered={self.unanswered}"
        )


@dataclass
class CountingProvider:
    """Wraps a provider and counts what reaches it (never keeps the request)."""

    inner: ImportUnderstandingProvider
    calls: int = field(default=0)

    def suggest(self, request: object) -> object:
        self.calls += 1
        return self.inner.suggest(request)  # type: ignore[arg-type]


def run_case(
    service: UnderstandingService, counter: CountingProvider, case: EvalCase
) -> CaseResult:
    before = counter.calls
    inspection = service.understand(
        case.domain,
        case.filename,
        case.content,
        UnderstandAnswers(),
        True,
        None,
        False,
        currency="EUR",
    )
    suggested: dict[str, str] = {}
    if inspection.understanding is not None:
        for item in inspection.understanding.recognized:
            if item.origin.kind == OriginKind.ASSISTANT and item.origin.detail is not None:
                suggested[item.origin.detail] = item.field
    correct = sum(1 for header, f in suggested.items() if case.expected.get(header) == f)
    wrong = len(suggested) - correct
    missed = sum(1 for header in case.expected if header not in suggested)
    return CaseResult(case.name, suggested, correct, wrong, missed, counter.calls - before)


def evaluate(
    service: UnderstandingService, counter: CountingProvider, cases: Sequence[EvalCase]
) -> EvalReport:
    results = tuple(run_case(service, counter, case) for case in cases)
    suggested = sum(r.correct + r.wrong for r in results)
    right = sum(r.correct for r in results)
    expected = sum(r.correct + r.missed for r in results)
    return EvalReport(
        results=results,
        cases=len(results),
        precision=right / suggested if suggested else 1.0,
        recall=right / expected if expected else 1.0,
        calls_total=sum(r.calls for r in results),
        calls_max=max((r.calls for r in results), default=0),
        unanswered=sum(1 for r in results if not r.suggested),
    )


__all__ = ["CaseResult", "CountingProvider", "EvalCase", "EvalReport", "evaluate", "run_case"]

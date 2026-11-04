"""python -m tests.benchmarks.aurora_like            (from services/api)

Files shaped like a real hotel's export, against a truth written before running them: which ones may
be read alone, and which words must be asked about. Nothing is read from or written to a database.
"""

import json
import sys
from dataclasses import asdict, dataclass, field

from tests.benchmarks.aurora_like.corpus import PERSONAL_VALUES, Case, build_corpus
from tests.benchmarks.smart_import_v3.observe import Observed, make_service, run


@dataclass(slots=True)
class Result:
    id: str
    outcome: str
    level: str | None
    questions: list[str] = field(default_factory=list)
    asked_words: list[str] = field(default_factory=list)
    pii_leaked: bool = False
    claim_on_extra_column: str | None = None
    false_automation: bool = False
    needless_question: bool = False
    missed_question: bool = False


def judge(case: Case, observed: Observed) -> Result:
    words = [label for q in observed.questions if q.kind == "VALUE_LABELS" for label in q.labels]
    claimed = next(
        (claim.field for claim in observed.claims if claim.header == case.extra_column), None
    )
    result = Result(
        id=case.id,
        outcome=case.outcome,
        level=observed.level,
        questions=observed.question_kinds,
        asked_words=words,
        pii_leaked=any(value in observed.payload for value in PERSONAL_VALUES),
        claim_on_extra_column=claimed,
    )
    if case.outcome == "asks":
        result.false_automation = observed.level == "READY"
        result.missed_question = set(words) != set(case.asked_words)
    else:
        result.needless_question = observed.level != "READY"
    return result


def main() -> int:
    service = make_service()
    results = [
        judge(case, run(service, "bookings", case.filename, case.content))
        for case in build_corpus()
    ]
    for result in results:
        print(json.dumps(asdict(result), ensure_ascii=False))
    print(
        json.dumps(
            {
                "documents": len(results),
                "false_automation": sum(result.false_automation for result in results),
                "missed_question": sum(result.missed_question for result in results),
                "needless_question": sum(result.needless_question for result in results),
                "pii_leaked": sum(result.pii_leaked for result in results),
                "claim_on_extra_column": sum(
                    result.claim_on_extra_column is not None for result in results
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

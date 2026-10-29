"""Running the Source Learning benchmark: every family through its eight versions, twice.

* LEARNED - the property that taught the source at V1 (the person decides, the server recomputes
  READY, the explicit import writes and remembers), then V2..V8 understood against that memory;
* COLD - another property of the same workspace, which has never seen the source: what Smart Import
  asks with NO memory. The difference is what learning saves.

Real services, a real database (the whole run is inside a transaction that is rolled back), real
`.xlsx` files. No model, no embedding, no external service.
"""

import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.data_sources import understanding as understanding_module
from app.modules.data_sources.mapping_types import (
    ColumnChoice,
    FileInspection,
    MappingInput,
)
from app.modules.data_sources.service import DataSourcesService, MappedImport
from app.modules.data_sources.source_learning import Drift, Structure, header_key, match_source
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.source_learning.families import FAMILIES, Expect, Family, Version, versions
from tests.source_learning_support import xlsx_of
from tests.support import BookingFactory

OTHER_DOMAIN = {
    DataSourceDomain.LABOR: DataSourceDomain.BOOKINGS,
    DataSourceDomain.BOOKINGS: DataSourceDomain.COSTS,
    DataSourceDomain.COSTS: DataSourceDomain.LABOR,
}
HARD = {"MANUAL", "BLOCKED"}  # the person has to build the matching by hand (or cannot)


@dataclass(slots=True)
class Reading:
    """What Smart Import said about one file, reduced to plain facts."""

    level: str
    questions: list[str]
    blockers: list[str]
    fields: dict[str, str]  # header -> the field it is read as
    reused: list[str]  # headers whose meaning came from the memory
    drift: str | None
    structure: str | None
    score: float | None
    explain: str | None
    trusted: bool
    ms: float
    # Which of the source's families the file was found to be (None: none, or it could not be told).
    family: str | None = None
    ambiguous: bool = False
    known: int = 0

    @property
    def automatic(self) -> bool:
        return self.level == "READY" and not self.questions and not self.blockers

    @property
    def effort(self) -> int:
        """What the person has to do: an answer per question, a matching if it is not readable."""
        return len(self.questions) + (1 if self.level in HARD else 0)


@dataclass(slots=True)
class Outcome:
    family: str
    domain: str
    version: str
    title: str
    expect: str
    learned: Reading
    cold: Reading
    wrong_reuse: list[str] = field(default_factory=list)
    wrong_in_ready: list[str] = field(default_factory=list)
    ok: bool = False
    why: str = ""


def _reading(inspection: FileInspection, elapsed_ms: float) -> Reading:
    info = inspection.understanding
    assert info is not None, "the file could not be understood"
    learning = inspection.learning
    match = None if learning is None else learning.match
    memory = None if learning is None else learning.memory
    proposal = inspection.proposal
    return Reading(
        level=info.level.value,
        questions=[q.id for q in info.questions],
        blockers=[b.code.value for b in info.blockers],
        fields={c.header: c.field for c in (proposal.columns if proposal else []) if c.field},
        reused=[] if learning is None else list(learning.reused),
        drift=None if match is None else match.drift.value,
        structure=None if match is None else match.structure.value,
        score=None if match is None else match.score,
        explain=None if match is None else match.explain(),
        trusted=memory is not None and memory.trust.value == "PERSON",
        ms=elapsed_ms,
        family=None if memory is None else memory.id,
        ambiguous=learning is not None and learning.ambiguous,
        known=0 if learning is None else learning.known,
    )


class Bench:
    def __init__(
        self, session: Session, progress: Callable[[str], None], workspace: str | None = None
    ) -> None:
        self.progress = progress
        self.factory = BookingFactory(session)
        self.workspace = self.factory.workspace(workspace)
        self.service = DataSourcesService(session, TenantContext(self.workspace.id))
        self.match_ms: list[float] = []

    # --- one file ---

    def understand(
        self,
        property_id: Any,
        family: Family,
        version: Version,
        *,
        domain: DataSourceDomain | None = None,
        answers: dict[str, Any] | None = None,
        month: int | None = None,
    ) -> Reading:
        content = xlsx_of(version.columns, rows=version.rows, month=month or version.month)
        started = time.perf_counter()
        inspection = self.service.understand_file(
            property_id,
            domain or family.domain,
            filename=f"{family.id}-{version.key}.xlsx",
            content=content,
            answers=UnderstandAnswers.model_validate(answers or {}),
        )
        return _reading(inspection, (time.perf_counter() - started) * 1000)

    # --- the first time: the person decides, the import remembers ---

    def teach(
        self,
        property_id: Any,
        family: Family,
        first: Version,
        month: int | None = None,
        snapshot: date | None = None,
    ) -> dict[str, Any]:
        content = xlsx_of(first.columns, rows=first.rows, month=month or first.month)
        name = f"{family.id}-V1.xlsx"
        if family.manual:
            decision = MappingInput(
                columns=[ColumnChoice(header=h, field=first.truth.get(h)) for h in first.columns]
            )
            how = "MANUAL"
            asked: list[str] = []
        else:
            before = self.service.understand_file(
                property_id,
                family.domain,
                filename=name,
                content=content,
                answers=UnderstandAnswers(),
            )
            assert before.understanding is not None
            asked = [q.id for q in before.understanding.questions]
            answers = UnderstandAnswers.model_validate(family.answers)
            answered = self.service.understand_file(
                property_id, family.domain, filename=name, content=content, answers=answers
            )
            assert answered.proposal is not None
            decision = answered.proposal
            how = "ANSWERS"
        outcome = self.service.import_file(
            property_id,
            family.domain,
            filename=name,
            content=content,
            snapshot_local_date=snapshot or date(2026, 10, 30),
            mapped=MappedImport(decision, save_configuration=True),
        )
        return {
            "how": how,
            "asked": asked,
            "imported": outcome.succeeded,
            "problem": None if outcome.problem is None else outcome.problem.value,
            "remembered": outcome.configuration_saved,
        }


def _score(family: Family, version: Version, learned: Reading, cold: Reading) -> Outcome:
    """Did Smart Import do the right thing for THIS version, given what the person had confirmed?"""
    out = Outcome(
        family.id,
        family.domain.value,
        version.key,
        version.title,
        version.expect.value,
        learned,
        cold,
    )
    # the truth: every header that was reused must be read as what it really is. (Headers are
    # compared as the reader sees them: case, spacing and punctuation do not matter.)
    truth = {header_key(h): f for h, f in version.truth.items()}
    fields = {header_key(h): f for h, f in learned.fields.items()}
    out.wrong_reuse = [
        h for h in learned.reused if fields.get(header_key(h)) != truth.get(header_key(h))
    ]
    if learned.automatic:
        out.wrong_in_ready = [
            h
            for h, f in learned.fields.items()
            if truth.get(header_key(h)) != f  # a column read as something it is not
        ]
    problems: list[str] = list(out.wrong_reuse)
    if family.control:
        # nothing was learned from a file the engine read alone: reading it is the engine's job
        if learned.reused:
            problems.append("a control family reused a memory")
        if learned.level != cold.level or learned.questions != cold.questions:
            problems.append("the memory changed what the engine reads alone")
    elif version.expect in (Expect.EXACT, Expect.COMPATIBLE):
        want = Structure.EXACT if version.expect == Expect.EXACT else Structure.COMPATIBLE
        if learned.structure != want.value:
            problems.append(f"structure {learned.structure} (wanted {want.value})")
        if not learned.automatic:
            problems.append(
                f"not automatic: {learned.level} {learned.questions} {learned.blockers}"
            )
        if len(learned.reused) == 0 and learned.questions:
            problems.append("nothing reused")
    elif version.expect == Expect.MISSING:
        if learned.drift != Drift.MISSING.value:
            problems.append(f"drift {learned.drift} (wanted MISSING)")
        gone = [h for h, f in learned.fields.items() if f in version.gone]
        if gone:
            problems.append(f"a column that is gone is still read: {gone}")
    elif version.expect == Expect.CONFLICT:
        if learned.drift != Drift.SEMANTIC_CONFLICT.value:
            problems.append(f"drift {learned.drift} (wanted SEMANTIC_CONFLICT)")
        reused_conflicted = [h for h in learned.reused if h in version.conflicted]
        if reused_conflicted:
            problems.append(f"the contradicted column was reused: {reused_conflicted}")
        if learned.automatic:
            problems.append("a contradiction became an automatic reading")
    if out.wrong_in_ready:
        problems.append(f"a READY reading with wrong fields: {out.wrong_in_ready}")
    out.ok = not problems
    out.why = "; ".join(problems)
    return out


def run_family(bench: Bench, family: Family) -> dict[str, Any]:
    plan = versions(family)
    taught_in = bench.factory.property(bench.workspace)  # the property that confirms
    cold_in = bench.factory.property(bench.workspace)  # another property that knows nothing
    first = bench.teach(taught_in.id, family, plan[0])
    outcomes: list[Outcome] = []
    contamination = 0
    cross_domain = 0
    for version in plan:
        learned = bench.understand(taught_in.id, family, version)
        cold = bench.understand(cold_in.id, family, version)
        outcome = _score(family, version, learned, cold)
        outcomes.append(outcome)
        if cold.reused or cold.drift is not None or cold.trusted:
            contamination += 1  # another property used the memory of this one
        other = bench.understand(taught_in.id, family, version, domain=OTHER_DOMAIN[family.domain])
        if other.reused or other.drift is not None or other.trusted:
            cross_domain += 1  # the memory of one kind of data was applied to another
        bench.progress(f"  {family.id} {version.key} {'ok' if outcome.ok else 'NOT OK'}")
    return {
        "family": family,
        "first": first,
        "outcomes": outcomes,
        "contamination": contamination,
        "cross_domain": cross_domain,
    }


def _rate(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "value": (num / den) if den else None}


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "mean": round(statistics.fmean(values), 3),
        "p50": round(statistics.median(values), 3),
        "p95": round(ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))], 3),
        "max": round(max(values), 3),
    }


def run_benchmark(
    session: Session,
    families: tuple[Family, ...] = FAMILIES,
    progress: Callable[[str], None] = lambda message: None,
) -> dict[str, Any]:
    bench = Bench(session, progress)
    timings: list[float] = []

    def timed(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return match_source(*args, **kwargs)
        finally:
            timings.append((time.perf_counter() - started) * 1000)

    with patch.object(understanding_module, "match_source", timed):
        results = [run_family(bench, family) for family in families]
    return summarise(results, timings)


# --- the numbers ---


def summarise(results: list[dict[str, Any]], match_ms: list[float]) -> dict[str, Any]:
    rows: list[Outcome] = [o for r in results for o in r["outcomes"]]
    trusted = [o for o in rows if not _family(results, o).control]
    exact = [o for o in trusted if o.expect == Expect.EXACT.value]
    compatible = [o for o in trusted if o.expect == Expect.COMPATIBLE.value]
    missing = [o for o in trusted if o.expect == Expect.MISSING.value]
    conflict = [o for o in trusted if o.expect == Expect.CONFLICT.value]
    reused = sum(len(o.learned.reused) for o in rows)
    wrong = sum(len(o.wrong_reuse) for o in rows)
    later = [o for o in trusted if o.version != "V1"]
    saved = sum(max(0, o.cold.effort - o.learned.effort) for o in later)
    manual_avoided = sum(1 for o in later if o.cold.level in HARD and o.learned.level not in HARD)
    first = {r["family"].id: r["first"] for r in results}
    return {
        "benchmark": "source-learning-benchmark-v1",
        "families": len(results),
        "trusted_families": sum(1 for r in results if not r["family"].control),
        "control_families": sum(1 for r in results if r["family"].control),
        "versions_per_family": 8,
        "document_versions": len(rows),
        "exact_reuse_rate": _rate(sum(1 for o in exact if o.ok), len(exact)),
        "compatible_reuse_rate": _rate(sum(1 for o in compatible if o.ok), len(compatible)),
        "questions_saved": {
            "asks_without_memory": sum(o.cold.effort for o in later),
            "asks_with_memory": sum(o.learned.effort for o in later),
            "saved": saved,
            "manual_matchings_avoided": manual_avoided,
            "versions_asking_nothing_with_memory": sum(1 for o in later if o.learned.automatic),
            "versions_asking_nothing_without_memory": sum(1 for o in later if o.cold.automatic),
        },
        "repeated_mapping_questions_on_unchanged_source": sum(
            len(o.learned.questions) for o in exact if o.version in {"V2", "V3", "V5"}
        ),
        "wrong_reuse_rate": _rate(wrong, reused),
        "false_automation_with_memory": sum(1 for o in rows if o.wrong_in_ready),
        "cross_property_contamination": sum(r["contamination"] for r in results),
        "cross_domain_contamination": sum(r["cross_domain"] for r in results),
        "conflict_detection_recall": _rate(
            sum(1 for o in conflict if o.learned.drift == Drift.SEMANTIC_CONFLICT.value),
            len(conflict),
        ),
        "missing_detection_recall": _rate(
            sum(1 for o in missing if o.learned.drift == Drift.MISSING.value), len(missing)
        ),
        "learning_effectiveness": _effectiveness(results),
        "performance_ms": {
            "match_source": _stats(match_ms),
            "understand_with_memory": _stats([o.learned.ms for o in rows]),
            "understand_without_memory": _stats([o.cold.ms for o in rows]),
        },
        "all_versions_as_expected": _rate(sum(1 for o in rows if o.ok), len(rows)),
        "failures": [
            {"family": o.family, "version": o.version, "why": o.why} for o in rows if not o.ok
        ],
        "first_confirmation": first,
        "per_family": [_family_row(r) for r in results],
        "versions": [_version_row(o) for o in rows],
    }


def _family(results: list[dict[str, Any]], outcome: Outcome) -> Family:
    family: Family = next(r["family"] for r in results if r["family"].id == outcome.family)
    return family


def _effectiveness(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for r in results:
        if r["family"].control:
            continue
        first_effort = next(o for o in r["outcomes"] if o.version == "V1").cold.effort
        second = next(o for o in r["outcomes"] if o.version == "V2").learned.effort
        rows.append({"family": r["family"].id, "first": first_effort, "next": second})
    total_first = sum(x["first"] for x in rows)
    total_next = sum(x["next"] for x in rows)
    return {
        "first_import_effort": total_first,
        "next_import_effort": total_next,
        "effort_removed": _rate(total_first - total_next, total_first),
        "per_family": rows,
    }


def _family_row(result: dict[str, Any]) -> dict[str, Any]:
    family: Family = result["family"]
    outcomes: list[Outcome] = result["outcomes"]
    later = [o for o in outcomes if o.version != "V1"]
    by = Counter(o.expect for o in outcomes)
    return {
        "family": family.id,
        "domain": family.domain.value,
        "control": family.control,
        "first": result["first"],
        "versions": len(outcomes),
        "exact": _rate(sum(1 for o in outcomes if o.expect == "EXACT" and o.ok), by["EXACT"]),
        "compatible": _rate(
            sum(1 for o in outcomes if o.expect == "COMPATIBLE" and o.ok), by["COMPATIBLE"]
        ),
        "questions_saved": sum(max(0, o.cold.effort - o.learned.effort) for o in later),
        "wrong_reuse": sum(len(o.wrong_reuse) for o in outcomes),
        "conflict_detected": next(
            (o.learned.drift == "SEMANTIC_CONFLICT" for o in outcomes if o.version == "V8"), False
        ),
        "all_as_expected": all(o.ok for o in outcomes),
    }


def _version_row(o: Outcome) -> dict[str, Any]:
    return {
        "family": o.family,
        "domain": o.domain,
        "version": o.version,
        "title": o.title,
        "expect": o.expect,
        "ok": o.ok,
        "why": o.why,
        "with_memory": {
            "level": o.learned.level,
            "questions": o.learned.questions,
            "blockers": o.learned.blockers,
            "reused": o.learned.reused,
            "drift": o.learned.drift,
            "structure": o.learned.structure,
            "score": o.learned.score,
            "explain": o.learned.explain,
        },
        "without_memory": {
            "level": o.cold.level,
            "questions": o.cold.questions,
            "blockers": o.cold.blockers,
        },
        "wrong_reuse": o.wrong_reuse,
    }

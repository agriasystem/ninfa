"""The multi-source extension of the Source Learning benchmark: several recurring files in ONE
property and kind of data.

A hotel does not bring a single file: the PMS export, an OTA export, an internal report - all
bookings, none of them the same structure. Three properties (bookings, staff, costs), each with FOUR
families that live side by side, and a script that is a real timeline: one is taught, another one
arrives, the first comes back, a third is taught, a drifted file of the first comes back... The twin
of the first family differs from it by one column, so a family can only be told apart by what the
file really contains.

Real services, a real database, real `.xlsx` files. No model, no embedding, no external service.
"""

import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.models import BookingMappingProfile
from app.modules.data_sources.mapping_types import ColumnChoice, MappingInput
from app.modules.data_sources.service import MappedImport
from app.modules.data_sources.source_learning import Learning, header_key, parse_learning
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from app.modules.invoices.models import InvoiceMappingProfile
from app.modules.labor.models import LaborMappingProfile
from tests.benchmarks.source_learning.families import (
    FAMILIES,
    JUNK,
    Expect,
    Family,
    Version,
    _cosmetic,
    versions,
)
from tests.benchmarks.source_learning.runner import OTHER_DOMAIN, Bench, Reading, _rate, _score
from tests.source_learning_support import xlsx_of

B, L, C = DataSourceDomain.BOOKINGS, DataSourceDomain.LABOR, DataSourceDomain.COSTS
BY_ID = {f.id: f for f in FAMILIES}
PROFILE: dict[DataSourceDomain, Any] = {
    B: BookingMappingProfile,
    L: LaborMappingProfile,
    C: InvoiceMappingProfile,
}
# The versions in which a file is the same source harmlessly changed: moved, a junk column, cosmetic
# headers, a new column.
DRIFT = ("V3", "V4", "V5", "V6")


def _twin(family: Family, was: str, now: str, new_id: str) -> Family:
    """The same source with ONE column called something else: a sibling that could be mistaken for
    it. The engine does not read either name, so the person decides it the same way."""

    def swap(table: Mapping[str, Any]) -> dict[str, Any]:
        return {(now if h == was else h): v for h, v in table.items()}

    return replace(
        family,
        id=new_id,
        columns=swap(family.columns),
        truth=swap(family.truth),
        answers={
            **family.answers,
            **(
                {"column_fields": swap(family.answers["column_fields"])}
                if "column_fields" in family.answers
                else {}
            ),
        },
        decided=tuple(now if h == was else h for h in family.decided),
    )


def _with(family: Family, new_id: str, header: str, kind: str, field: str) -> Family:
    """The same source with one more, optional, column: two of them (a different one each) are
    siblings that differ by a column the engine reads as two different fields."""
    return replace(
        family,
        id=new_id,
        columns={**family.columns, header: kind},
        truth={**family.truth, header: field},
    )


OTA = Family(
    "M1-ota",
    B,
    "bookings",
    {
        "Rif OTA": "ref",
        "Emessa": "booked",
        "Dal": "checkin",
        "Al": "checkout",
        "Stato OTA": "status",
        "Camere OTA": "rooms",
        "Netto": "revenue",
        "Provvigione": "net",
        "Portale": "channel",
    },
    {
        "Rif OTA": "source_record_id",
        "Emessa": "booked_at",
        "Dal": "check_in",
        "Al": "check_out",
        "Stato OTA": "status",
        "Camere OTA": "rooms",
        "Netto": "room_revenue",
        "Provvigione": "commission_amount",
        "Portale": "channel",
    },
    manual=True,
    decided=("Rif OTA", "Stato OTA", "Camere OTA", "Netto", "Provvigione"),
    drop="Provvigione",
    conflict="Netto",
)
# The PMS export with the number of guests, and its twin with the rate plan instead.
PMS = _with(BY_ID["B1-pratica"], "M1-pms", "Ospiti", "rooms", "guests")
PMS_TWIN = _with(BY_ID["B1-pratica"], "M1-pms-tariffa", "Tariffa", "channel", "rate_plan")
REPORT = replace(BY_ID["B2-cod"], id="M1-report")

SHIFTS = replace(BY_ID["L1-ore-a-b"], id="M2-turni", drop="Ore A", conflict="Ore A")
SHIFTS_TWIN = _twin(SHIFTS, "Ore B", "Ore C", "M2-turni-c")
SQUAD = replace(BY_ID["L2-ore-1-2"], id="M2-ore-1-2")
BASE = replace(BY_ID["L3-ore-base"], id="M2-ore-base")

# The supplier register with the due date, and its twin with the quantity instead.
SUPPLIERS = _with(BY_ID["C1-forn"], "M3-forn", "Scad.", "invdate", "due_date")
SUPPLIERS_TWIN = _with(BY_ID["C1-forn"], "M3-forn-qta", "Qta", "rooms", "quantity")
LEDGER = replace(BY_ID["C2-ragione"], id="M3-ragione")
CASH = replace(BY_ID["C3-chi"], id="M3-chi")


@dataclass(frozen=True, slots=True)
class Site:
    """A property with four families in one kind of data, and what a correction in the first is."""

    id: str
    title: str
    domain: DataSourceDomain
    families: tuple[Family, Family, Family, Family]  # A, B, C and A's twin D
    # the header that tells A from its twin, in A and in D: a file without it could be either
    apart: tuple[str, str]
    # the family a person corrects by hand and how: header -> the field they now say it is (None:
    # not imported). Columns the engine does not read by itself: correcting one it reads clearly
    # is a contradiction, and Smart Import asks about those every time (as it should).
    corrects: str = "A"
    correction: Mapping[str, str | None] = field(default_factory=dict)


SITES: tuple[Site, ...] = (
    Site(
        "bookings",
        "PMS, OTA, internal report and a PMS twin",
        B,
        (PMS, OTA, REPORT, PMS_TWIN),
        ("Ospiti", "Tariffa"),
        "B",
        {"Provvigione": None},
    ),
    Site(
        "labor",
        "three staff exports and a twin of the first",
        L,
        (SHIFTS, SQUAD, BASE, SHIFTS_TWIN),
        ("Ore B", "Ore C"),
        "A",
        {"Ore A": "actual_hours", "Ore B": "planned_hours"},
    ),
    Site(
        "costs",
        "supplier register, ledger, cash book and a twin of the first",
        C,
        (SUPPLIERS, LEDGER, CASH, SUPPLIERS_TWIN),
        ("Scad.", "Qta"),
        "A",
        {"Scad.": None},
    ),
)

# The timeline of one property, written with the letters of its families (A, B, C and D = A's twin).
#   teach X       the person confirms the first file of X (it is imported and remembered)
#   see X Vn      a later file of X, understood against everything the property remembers
#   undecidable   a file that could be A or D and is neither clearly: A without the column that
#                 tells it from D, in five ways (as it is, reordered, with a junk column, with
#                 cosmetic headers) and A with the column of D as well
#   import X Vn   a file of X read from memory is imported (the reuse is written down)
#   correct @     the person corrects by hand the matching of one family (the site's `corrects`)
SCRIPT: tuple[tuple[str, str, str], ...] = (
    ("teach", "A", ""),
    ("see", "A", "V2"),  # A -> A
    ("teach", "B", ""),
    ("see", "B", "V2"),  # A -> B
    ("see", "A", "V2"),  # B -> A: the first comes back
    ("see", "B", "V2"),  # A -> B again
    ("teach", "C", ""),
    ("see", "C", "V2"),
    ("see", "A", "V2"),  # A -> B -> C -> A
    ("see", "C", "V2"),  # ... -> C
    ("see", "B", "V2"),  # ... -> B
    ("see", "A", "V4"),  # A drifts (a junk column) after the others
    ("see", "B", "V3"),  # B drifts (columns moved)
    ("see", "C", "V5"),  # C drifts (cosmetic headers)
    ("teach", "D", ""),  # the twin of A arrives
    ("see", "A", "V2"),
    ("see", "D", "V2"),
    ("see", "A", "V3"),
    ("see", "D", "V3"),
    ("see", "A", "V4"),
    ("see", "D", "V4"),
    ("see", "A", "V5"),
    ("see", "D", "V5"),
    ("see", "A", "V6"),
    ("see", "D", "V6"),
    ("see", "B", "V6"),
    ("see", "C", "V4"),
    ("see", "A", "V7"),  # a column both share is gone
    ("see", "D", "V7"),
    ("see", "A", "V8"),  # a column both share changed meaning
    ("see", "D", "V8"),
    ("undecidable", "A", "base"),
    ("undecidable", "A", "reordered"),
    ("undecidable", "A", "junk"),
    ("undecidable", "A", "cosmetic"),
    ("undecidable", "A", "both"),
    ("import", "A", "V2"),  # A is imported from memory ...
    ("see", "B", "V2"),  # ... and nobody else is touched
    ("see", "C", "V2"),
    ("see", "D", "V2"),
    ("import", "C", "V2"),
    ("see", "A", "V2"),
    ("correct", "@", ""),  # one family is corrected by hand ...
    ("see", "A", "V2"),  # ... and the others are exactly as they were
    ("see", "B", "V2"),
    ("see", "C", "V2"),
    ("see", "D", "V2"),
)


@dataclass(slots=True)
class Step:
    site: str
    n: int
    kind: str  # see | undecidable | import | correct | teach
    family: str
    version: str
    expect: str
    learned: Reading | None = None
    cold: Reading | None = None
    returning: bool = False
    twin: bool = False  # the step is about a family that has a lookalike in the property
    wrong_family: bool = False
    false_match: bool = False
    wrong_reuse: list[str] = field(default_factory=list)
    contaminated: bool = False
    cross_domain: bool = False
    intact: bool | None = None
    ok: bool = False
    why: str = ""


def _store(bench: Bench, domain: DataSourceDomain, property_id: Any) -> Learning | None:
    model = PROFILE[domain]
    profile = bench.factory.session.scalars(
        select(model).where(
            model.workspace_id == bench.workspace.id, model.property_id == property_id
        )
    ).first()
    return None if profile is None else parse_learning(profile.format_options.get("learning"))


def _frozen(store: Learning | None) -> dict[str, tuple[Any, ...]]:
    """Everything a family holds except WHEN it was last used."""
    return {
        m.id: (
            m.revision,
            m.trust,
            tuple(sorted(m.mapped.items())),
            tuple(sorted(m.person.items())),
        )
        for m in (store.families if store else [])
    }


def run_site(
    bench: Bench,
    site: Site,
    progress: Callable[[str], None],
    script: tuple[tuple[str, str, str], ...] = SCRIPT,
) -> tuple[list[Step], dict[str, Any]]:
    letters = dict(zip("ABCD", site.families, strict=True))
    plans = {letter: versions(f) for letter, f in letters.items()}
    taught_in = bench.factory.property(bench.workspace)
    cold_in = bench.factory.property(bench.workspace)
    ids: dict[str, str] = {}  # letter -> the identity of the family in the property's memory
    steps: list[Step] = []
    last: str | None = None  # the family of the previous event
    seen: set[str] = set()
    # Each import is a month of its own, in order, with its own snapshot day: the staff days of two
    # families, or two snapshots of the same day, never collide.
    teach_month = {"A": 4, "B": 5, "C": 6, "D": 7}
    import_months = iter((8, 9, 10))
    corrected: set[str] = set()  # letters of the families a person corrected by hand

    base = {h: k for h, k in site.families[0].columns.items() if h != site.apart[0]}
    undecidable = {
        "base": base,
        "reordered": dict(reversed(base.items())),
        "junk": {**base, JUNK: "junk"},
        "cosmetic": {_cosmetic(h): k for h, k in base.items()},
        "both": {**base, site.apart[0]: site.families[0].columns[site.apart[0]],
                 site.apart[1]: site.families[3].columns[site.apart[1]]},
    }  # fmt: skip

    for n, (kind, letter, key) in enumerate(script, 1):
        letter = site.corrects if letter == "@" else letter
        family = letters[letter]
        twin = letter in ("A", "D")
        expect = Expect.AMBIGUOUS.value
        version: Version | None = None
        if kind in ("see", "import"):
            version = next(v for v in plans[letter] if v.key == key)
            expect = version.expect.value
        returning = letter in seen and last != letter
        step = Step(site.id, n, kind, family.id, key, expect, twin=twin, returning=returning)
        if kind == "teach":
            first = bench.teach(
                taught_in.id, family, plans[letter][0], teach_month[letter],
                date(2026, teach_month[letter], 28),
            )  # fmt: skip
            assert first["imported"] and first["remembered"], first
            store = _store(bench, site.domain, taught_in.id)
            assert store is not None
            ids[letter] = store.current
            step.ok = True
        elif kind == "undecidable":
            assert version is None
            file = Version(
                "X", f"could be either twin ({key})", Expect.AMBIGUOUS, undecidable[key], {}, 11, 16
            )
            reading = bench.understand(taught_in.id, site.families[0], file)
            step.learned = reading
            step.cold = bench.understand(cold_in.id, site.families[0], file)
            step.false_match = reading.family is not None or bool(reading.reused)
            step.ok = (
                reading.ambiguous and reading.family is None and not reading.reused
                and not reading.automatic
            )  # fmt: skip
            step.why = "" if step.ok else f"chose {reading.family} / reused {reading.reused}"
        elif kind == "see":
            assert version is not None
            learned = bench.understand(taught_in.id, family, version)
            cold = bench.understand(cold_in.id, family, version)
            other = bench.understand(
                taught_in.id, family, version, domain=OTHER_DOMAIN[site.domain]
            )
            step.learned, step.cold = learned, cold
            step.contaminated = bool(cold.reused or cold.drift is not None or cold.trusted)
            step.cross_domain = bool(other.reused or other.drift is not None or other.trusted)
            step.wrong_family = learned.family is not None and learned.family != ids[letter]
            if letter in corrected:
                # what the person corrected is the new truth of this family: it is judged on being
                # the right family, asking nothing, and reading the corrected columns as corrected
                problems = [] if learned.automatic else ["a corrected family asks again"]
                for header, wanted in site.correction.items():
                    if wanted is not None and learned.fields.get(header) != wanted:
                        problems.append(f"{header} is read as {learned.fields.get(header)}")
            else:
                outcome = _score(family, version, learned, cold)
                step.wrong_reuse = list(outcome.wrong_reuse)
                problems = [] if outcome.ok else [outcome.why]
            if learned.family != ids[letter]:
                problems.append(f"family {learned.family} (wanted {ids[letter]})")
            if learned.ambiguous:
                problems.append("could not tell the family")
            step.ok = not problems
            step.why = "; ".join(problems)
        elif kind == "import":
            assert version is not None
            before = _frozen(_store(bench, site.domain, taught_in.id))
            month = next(import_months)
            content = xlsx_of(version.columns, rows=version.rows, month=month)
            inspection = bench.service.understand_file(
                taught_in.id, family.domain, filename=f"{family.id}-{month}.xlsx",
                content=content, answers=UnderstandAnswers(),
            )  # fmt: skip
            info = inspection.understanding
            assert inspection.proposal is not None and info is not None
            if info.level.value != "READY" or info.questions or info.blockers:
                step.ok = False
                step.why = (
                    f"a file read from memory is not ready: {info.level.value} "
                    f"{[q.id for q in info.questions]} {[b.code.value for b in info.blockers]}"
                )
                steps.append(step)
                continue
            outcome_import = bench.service.import_file(
                taught_in.id, family.domain, filename=f"{family.id}-{month}.xlsx",
                content=content, snapshot_local_date=date(2026, month, 28),
                mapped=MappedImport(inspection.proposal, save_configuration=True),
            )  # fmt: skip
            after = _frozen(_store(bench, site.domain, taught_in.id))
            step.intact = after == before and outcome_import.succeeded
            step.ok = bool(step.intact)
            step.why = "" if step.ok else f"succeeded={outcome_import.succeeded}; store changed"
        elif kind == "correct":
            truth: dict[str, str | None] = {**family.truth, **site.correction}
            version = plans[letter][0]
            before = _frozen(_store(bench, site.domain, taught_in.id))
            decision = MappingInput(
                columns=[ColumnChoice(header=h, field=truth.get(h)) for h in version.columns]
            )
            month = next(import_months)
            outcome_import = bench.service.import_file(
                taught_in.id, family.domain, filename=f"{family.id}-corrected.xlsx",
                content=xlsx_of(version.columns, rows=version.rows, month=month),
                snapshot_local_date=date(2026, month, 28),
                mapped=MappedImport(decision, save_configuration=True),
            )  # fmt: skip
            store_after = _store(bench, site.domain, taught_in.id)
            after = _frozen(store_after)
            others = {i: v for i, v in before.items() if i != ids[letter]}
            mine = None if store_after is None else store_after.family(ids[letter])
            says_so = mine is not None and all(
                (mine.mapped.get(f) == header_key(h))
                if f
                else (header_key(h) not in mine.mapped.values())
                for h, f in site.correction.items()
            )  # the family now says what the person corrected
            step.intact = (
                outcome_import.succeeded
                and says_so
                and {i: v for i, v in after.items() if i != ids[letter]} == others
                and after[ids[letter]][0] == before[ids[letter]][0] + 1  # a new revision of it only
                and len(after) == len(before)
            )
            step.ok = bool(step.intact)
            step.why = (
                "" if step.ok else f"succeeded={outcome_import.succeeded}; {before} -> {after}"
            )
            corrected.add(letter)
        if kind in ("teach", "see", "import", "correct"):
            last = letter
            seen.add(letter)
        if kind == "undecidable":
            last = None
        steps.append(step)
        progress(f"  {site.id} {n:02d} {kind} {family.id} {key} {'ok' if step.ok else 'NOT OK'}")

    # After a correction A is no longer the family it was: its own next file is automatic, whatever
    # the truth of the first version said (the check above is on who changed, not on what it means).
    final_store = _store(bench, site.domain, taught_in.id)
    site_info = {
        "site": site.id,
        "title": site.title,
        "domain": site.domain.value,
        "families": [f.id for f in site.families],
        "families_in_memory": 0 if final_store is None else len(final_store.families),
        "revisions": {
            f.id: next(
                (
                    m.revision
                    for m in (final_store.families if final_store else [])
                    if m.id == ids.get(k)
                ),
                None,
            )
            for k, f in letters.items()
        },
    }
    return steps, site_info


def run_multi_family(
    session: Session,
    sites: tuple[Site, ...] = SITES,
    progress: Callable[[str], None] = lambda message: None,
    script: tuple[tuple[str, str, str], ...] = SCRIPT,
) -> dict[str, Any]:
    bench = Bench(session, progress, workspace="multi-source")  # (beside the other benchmark's)
    steps: list[Step] = []
    infos: list[dict[str, Any]] = []
    started = time.perf_counter()
    for site in sites:
        site_steps, info = run_site(bench, site, progress, script)
        steps.extend(site_steps)
        infos.append(info)
    return summarise_multi(steps, infos, time.perf_counter() - started)


# --- the numbers ---


def summarise_multi(
    steps: list[Step], infos: list[dict[str, Any]], seconds: float
) -> dict[str, Any]:
    see = [s for s in steps if s.kind == "see" and s.learned is not None and s.cold is not None]
    expected = [s for s in see if s.expect in {e.value for e in Expect if e != Expect.AMBIGUOUS}]
    clean = [s for s in see if s.expect in (Expect.EXACT.value, Expect.COMPATIBLE.value)]
    returning = [s for s in clean if s.returning]
    unchanged = [s for s in clean if s.expect == Expect.EXACT.value and s.returning]
    drift = [s for s in see if s.version in DRIFT]
    undecidable = [s for s in steps if s.kind == "undecidable"]
    imports = [s for s in steps if s.kind in ("import", "correct")]
    later = [s for s in see if s.learned is not None and s.cold is not None]

    def ok_family(s: Step) -> bool:
        return s.learned is not None and s.learned.family is not None and not s.wrong_family

    saved = sum(max(0, s.cold.effort - s.learned.effort) for s in later if s.cold and s.learned)
    wrong_family = sum(1 for s in see if s.wrong_family)
    wrong_columns = sum(len(s.wrong_reuse) for s in see)
    false_matches = sum(1 for s in undecidable if s.false_match)
    twin_steps = [s for s in see if s.twin]
    return {
        "benchmark": "source-learning-benchmark-v1/multi-source",
        "properties": len(infos),
        "families": sum(len(i["families"]) for i in infos),
        "families_per_property": min(len(i["families"]) for i in infos),
        "families_in_memory": [i["families_in_memory"] for i in infos],
        "documents": len(see) + len(undecidable),
        "timeline_steps": len(steps),
        "returning_family_recognition": _rate(
            sum(1 for s in returning if s.ok and s.learned and s.learned.automatic), len(returning)
        ),
        "right_family_every_expected_step": _rate(
            sum(1 for s in expected if ok_family(s)), len(expected)
        ),
        "cross_family_wrong_reuse": wrong_family + wrong_columns,
        "cross_family_wrong_family": wrong_family,
        "family_collision_false_match": _rate(false_matches, len(undecidable)),
        "twin_confusions": sum(1 for s in twin_steps if s.wrong_family),
        "repeated_questions_after_returning_source": sum(
            len(s.learned.questions) + len(s.learned.blockers) for s in unchanged if s.learned
        ),
        "correct_family_after_cosmetic_or_additive_drift": _rate(
            sum(1 for s in drift if s.ok and s.learned and s.learned.automatic), len(drift)
        ),
        "store_intact_after_import_or_correction": _rate(
            sum(1 for s in imports if s.intact), len(imports)
        ),
        "cross_property_contamination": sum(1 for s in see if s.contaminated),
        "cross_domain_contamination": sum(1 for s in see if s.cross_domain),
        "questions_saved": {
            "asks_without_memory": sum(s.cold.effort for s in later if s.cold),
            "asks_with_memory": sum(s.learned.effort for s in later if s.learned),
            "saved": saved,
            "documents_asking_nothing_with_memory": sum(
                1 for s in later if s.learned and s.learned.automatic
            ),
            "documents_asking_nothing_without_memory": sum(
                1 for s in later if s.cold and s.cold.automatic
            ),
        },
        "every_step_as_expected": _rate(sum(1 for s in steps if s.ok), len(steps)),
        "failures": [
            {
                "site": s.site,
                "n": s.n,
                "kind": s.kind,
                "family": s.family,
                "version": s.version,
                "why": s.why,
            }  # fmt: skip
            for s in steps
            if not s.ok
        ],
        "seconds": round(seconds, 1),
        "per_site": infos,
        "steps": [_step_row(s) for s in steps],
        "versions_seen": dict(Counter(s.version for s in see)),
    }


def _step_row(s: Step) -> dict[str, Any]:
    row: dict[str, Any] = {
        "site": s.site,
        "n": s.n,
        "kind": s.kind,
        "family": s.family,
        "version": s.version,
        "expect": s.expect,
        "returning": s.returning,
        "ok": s.ok,
        "why": s.why,
    }
    if s.learned is not None:
        row.update(
            level=s.learned.level,
            structure=s.learned.structure,
            drift=s.learned.drift,
            family_chosen=s.learned.family,
            ambiguous=s.learned.ambiguous,
            questions=len(s.learned.questions),
            reused=len(s.learned.reused),
            without_memory=None if s.cold is None else s.cold.level,
        )
    return row

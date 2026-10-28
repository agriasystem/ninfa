"""The multi-FORMAT extension of the Source Learning benchmark: how each family is READ.

A source (property + kind of data) brings back files that are not only different structures but
different SHAPES: an xlsx whose table sits under a title on one sheet, another xlsx on another
sheet with the table lower down, a csv, a people x days grid, a document whose department is only in
its title. How each is read - the sheet, the hours of a grid, where the department comes from - is
what a person decided about THAT structure, and it must not depend on which family was imported
last.

Three properties, a timeline each, real `.xlsx` and `.csv` bytes through the real services and
database:

* bookings: the PMS export (sheet "Prenotazioni", a title above the table), another export (sheet
  "Export", the table lower, a blank column) and a channel manager's csv;
* staff: a day grid, a document with the department in its title, an ordinary xlsx table and an
  ordinary csv table (the house's own words);
* two lookalike exports that need different sheets, and files that could be either.

No model, no embedding, no external service.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.service import MappedImport
from app.modules.data_sources.source_learning import Learning
from app.modules.data_sources.understanding import UnderstandAnswers
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.source_learning.multi import _frozen, _store
from tests.benchmarks.source_learning.runner import Bench, Reading, _rate, _reading
from tests.source_learning_layout_support import (
    reservations_csv,
    reservations_export,
    reservations_pms,
    staff_csv,
    staff_grid,
    staff_title_department,
)
from tests.source_learning_support import xlsx_of

B, L = DataSourceDomain.BOOKINGS, DataSourceDomain.LABOR
STAFF = {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"}
STAFF_CSV = {"Data": "day", "Ore 1": "planned", "Ore 2": "actual", "Area": "dept"}
EXTRA = {"Colonna extra": "junk"}


@dataclass(frozen=True, slots=True)
class Format:
    id: str
    domain: DataSourceDomain
    kind: str  # xlsx | csv | grid | title | table | table-csv
    month: int  # the month of its first file (each import is a month of its own)
    build: Callable[[int, bool], tuple[str, bytes]]  # (month, with a column nobody asked for)
    says: Mapping[str, Any]  # what the person answers the first time
    layout: Mapping[str, Any]  # how its files MUST be read (the layout of the decision)
    extra_ok: bool = True  # it can come with a column nobody asked for


FORMATS: dict[str, Format] = {
    f.id: f
    for f in (
        Format(
            "F-pms",
            B,
            "xlsx",
            3,
            lambda m, e: ("pms.xlsx", reservations_pms(m, extra=e)),
            {"sheet_name": "Prenotazioni"},
            {"sheets": ["Prenotazioni"]},
        ),
        Format(
            "F-export",
            B,
            "xlsx",
            4,
            lambda m, e: ("export.xlsx", reservations_export(m, extra=e)),
            {"sheet_name": "Export"},
            {"sheets": ["Export"]},
        ),
        Format(
            "F-csv",
            B,
            "csv",
            5,
            lambda m, e: ("gestionale.csv", reservations_csv(m, extra=e)),
            {"date_order": "DMY"},
            {},
        ),
        Format(
            "F-grid",
            L,
            "grid",
            3,
            lambda m, e: ("griglia.xlsx", staff_grid(m)),
            {"grid_hours": "planned_hours"},
            {"grid": {"hours_field": "planned_hours"}},
            extra_ok=False,
        ),
        Format(
            "F-table",
            L,
            "table",
            4,
            lambda m, e: ("turni.xlsx", xlsx_of({**STAFF, **(EXTRA if e else {})}, month=m)),
            {"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}},
            {},
        ),
        Format(
            "F-title",
            L,
            "title",
            5,
            lambda m, e: ("titolo.xlsx", staff_title_department(m)),
            {"department_from": "TITLE"},
            {"department": {"kind": "TITLE"}},
            extra_ok=False,
        ),
        Format(
            "F-table-csv",
            L,
            "table-csv",
            6,
            lambda m, e: ("turni.csv", staff_csv({**STAFF_CSV, **(EXTRA if e else {})}, month=m)),
            {
                "column_fields": {"Ore 1": "planned_hours", "Ore 2": "actual_hours"},
                "date_order": "DMY",
            },
            {},
        ),
        # two lookalikes: the same export plus a different optional column, each read through a
        # sheet of its own
        Format(
            "F-twin-guests",
            B,
            "xlsx",
            3,
            lambda m, e: ("pms-ospiti.xlsx", reservations_pms(m, extra=e, guests=True)),
            {"sheet_name": "Prenotazioni"},
            {"sheets": ["Prenotazioni"]},
        ),
        Format(
            "F-twin-plan",
            B,
            "xlsx",
            4,
            lambda m, e: (
                "pms-tariffe.xlsx",
                reservations_pms(m, extra=e, sheet_name="Elenco", rate_plan=True),
            ),
            {"sheet_name": "Elenco"},
            {"sheets": ["Elenco"]},
        ),
    )
}


@dataclass(frozen=True, slots=True)
class Site:
    id: str
    title: str
    domain: DataSourceDomain
    formats: tuple[str, ...]
    script: tuple[tuple[str, str, str], ...]


# teach F          the person answers, the import remembers
# see F next       a later file of F (another month)
# see F extra      the same with a column nobody asked for
# either X         a file of the lookalikes' common part, on a sheet neither names (it could be
#                  either, and the only right thing is to apply neither's sheet)
# import F next    a later file of F is imported from memory: nothing else is touched
BOOKINGS_SCRIPT: tuple[tuple[str, str, str], ...] = (
    ("teach", "F-pms", ""),
    ("see", "F-pms", "next"),
    ("teach", "F-export", ""),
    ("see", "F-export", "next"),
    ("see", "F-pms", "next"),  # A -> B -> A
    ("see", "F-export", "next"),  # A -> B -> A -> B
    ("teach", "F-csv", ""),
    ("see", "F-csv", "next"),
    ("see", "F-pms", "next"),
    ("see", "F-export", "next"),  # A -> B -> C -> A -> B
    ("see", "F-pms", "next"),
    ("see", "F-csv", "next"),
    ("see", "F-pms", "next"),
    ("see", "F-csv", "next"),  # A -> C -> A -> C
    ("see", "F-export", "next"),
    ("see", "F-pms", "extra"),
    ("see", "F-export", "extra"),
    ("see", "F-csv", "extra"),
    ("import", "F-pms", "next"),
    ("see", "F-export", "next"),
    ("see", "F-csv", "next"),
    ("see", "F-pms", "next"),
)
LABOR_SCRIPT: tuple[tuple[str, str, str], ...] = (
    ("teach", "F-grid", ""),
    ("see", "F-grid", "next"),
    ("teach", "F-table", ""),
    ("see", "F-table", "next"),
    ("see", "F-grid", "next"),  # SPECIAL -> NORMAL -> SPECIAL
    ("teach", "F-title", ""),
    ("see", "F-title", "next"),
    ("see", "F-table", "next"),
    ("see", "F-title", "next"),  # SPECIAL -> NORMAL -> SPECIAL
    ("teach", "F-table-csv", ""),
    ("see", "F-table-csv", "next"),
    ("see", "F-grid", "next"),
    ("see", "F-table-csv", "next"),
    ("see", "F-title", "next"),
    ("see", "F-table", "next"),
    ("see", "F-grid", "next"),
    ("see", "F-table", "extra"),
    ("see", "F-table-csv", "extra"),
    ("import", "F-grid", "next"),
    ("see", "F-table", "next"),
    ("see", "F-title", "next"),
    ("see", "F-grid", "next"),
)
TWINS_SCRIPT: tuple[tuple[str, str, str], ...] = (
    ("teach", "F-twin-guests", ""),
    ("see", "F-twin-guests", "next"),
    ("teach", "F-twin-plan", ""),
    ("see", "F-twin-plan", "next"),
    ("see", "F-twin-guests", "next"),
    ("either", "Altro", ""),
    ("see", "F-twin-plan", "next"),
    ("either", "Foglio1", ""),
    ("either", "Riepilogo", ""),
    ("see", "F-twin-guests", "next"),
    ("see", "F-twin-plan", "extra"),
    ("see", "F-twin-guests", "extra"),
)
SITES: tuple[Site, ...] = (
    Site(
        "bookings",
        "PMS xlsx, another xlsx on another sheet, a csv",
        B,
        ("F-pms", "F-export", "F-csv"),
        BOOKINGS_SCRIPT,
    ),
    Site(
        "labor",
        "a day grid, a department in the title, an xlsx table, a csv table",
        L,
        ("F-grid", "F-table", "F-title", "F-table-csv"),
        LABOR_SCRIPT,
    ),
    Site(
        "twins",
        "two lookalike exports that need other sheets",
        B,
        ("F-twin-guests", "F-twin-plan"),
        TWINS_SCRIPT,
    ),
)


@dataclass(slots=True)
class Step:
    site: str
    n: int
    kind: str
    format: str
    variant: str
    returning: bool = False
    learned: Reading | None = None
    cold: Reading | None = None
    read_as: dict[str, Any] | None = None
    applied: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    wrong_family: bool = False
    wrong_layout: bool = False
    contaminated: bool = False
    unreadable: bool = False
    intact: bool | None = None
    ok: bool = False
    why: str = ""
    problems: list[str] = field(default_factory=list)


def _layout_json(inspection: FileInspection) -> dict[str, Any]:
    layout = None if inspection.proposal is None else inspection.proposal.layout
    if layout is None:
        return {}
    return layout.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


def _applied_json(inspection: FileInspection) -> dict[str, Any] | None:
    info = inspection.learning
    if info is None or info.layout is None:
        return None
    return info.layout.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


def _belongs_to_another(actual: Mapping[str, Any], mine: Mapping[str, Any], domain: Any) -> bool:
    """Does a part of the layout this file was read with belong to ANOTHER format of the source?"""
    others = [f.layout for f in FORMATS.values() if f.domain == domain and f.layout != mine]
    for key, value in actual.items():
        if mine.get(key) != value and any(other.get(key) == value for other in others):
            return True
    return False


def run_site(
    bench: Bench, site: Site, progress: Callable[[str], None]
) -> tuple[list[Step], dict[str, Any]]:
    taught_in = bench.factory.property(bench.workspace)
    cold_in = bench.factory.property(bench.workspace)
    ids: dict[str, str] = {}
    seen: set[str] = set()
    last: str | None = None
    steps: list[Step] = []
    imports = iter((11, 12))

    def look(
        property_id: Any, domain: DataSourceDomain, name: str, content: bytes
    ) -> tuple[FileInspection, Reading]:
        started = time.perf_counter()
        inspection = bench.service.understand_file(
            property_id, domain, filename=name, content=content, answers=UnderstandAnswers()
        )
        return inspection, _reading(inspection, (time.perf_counter() - started) * 1000)

    for n, (kind, key, variant) in enumerate(site.script, 1):
        step = Step(site.id, n, kind, key, variant)
        fmt = None if kind == "either" else FORMATS[key]
        step.returning = fmt is not None and key in seen and last != key
        if kind == "teach":
            assert fmt is not None
            name, content = fmt.build(fmt.month, False)
            answered = bench.service.understand_file(
                taught_in.id,
                fmt.domain,
                filename=name,
                content=content,
                answers=UnderstandAnswers.model_validate(fmt.says),
            )
            info = answered.understanding
            if info is None or info.level.value != "READY" or answered.proposal is None:
                blockers = [] if info is None else [b.code.value for b in info.blockers]
                step.unreadable = "NO_TABLE" in blockers
                step.problems.append(f"could not be taught: {info and info.level} {blockers}")
            else:
                outcome = bench.service.import_file(
                    taught_in.id,
                    fmt.domain,
                    filename=name,
                    content=content,
                    snapshot_local_date=date(2026, fmt.month, 28),
                    mapped=MappedImport(answered.proposal, save_configuration=True),
                )
                stored = _store(bench, site.domain, taught_in.id)
                if not (outcome.succeeded and outcome.configuration_saved) or stored is None:
                    step.problems.append(f"the import did not remember it: {outcome}")
                else:
                    ids[key] = stored.current
            step.ok = not step.problems
        elif kind in ("see", "import") and fmt is not None and key not in ids:
            step.problems.append("its family was never taught")
            step.ok = False
        elif kind == "see":
            assert fmt is not None
            month = 7 + n % 4  # (files that are only understood: any month will do)
            name, content = fmt.build(month, variant == "extra")
            inspection, learned = look(taught_in.id, fmt.domain, name, content)
            _, cold = look(cold_in.id, fmt.domain, name, content)
            step.learned, step.cold = learned, cold
            step.read_as, step.applied = _layout_json(inspection), _applied_json(inspection)
            step.expected = dict(fmt.layout)
            step.unreadable = "NO_TABLE" in learned.blockers
            step.wrong_family = learned.family is not None and learned.family != ids[key]
            step.wrong_layout = (
                step.applied is not None and (step.applied != step.expected or step.wrong_family)
            ) or (step.read_as != step.expected and not step.unreadable)
            step.contaminated = step.read_as != step.expected and _belongs_to_another(
                step.read_as, step.expected, fmt.domain
            )
            if learned.family != ids[key]:
                step.problems.append(f"family {learned.family} (wanted {ids[key]})")
            if not learned.automatic:
                step.problems.append(
                    f"not automatic: {learned.level} {learned.questions} {learned.blockers}"
                )
            if step.read_as != step.expected:
                step.problems.append(f"read as {step.read_as} (wanted {step.expected})")
            step.ok = not step.problems
        elif kind == "either":
            sheet = key
            name, content = ("pms.xlsx", reservations_pms(7 + n % 4, sheet_name=sheet))
            inspection, learned = look(taught_in.id, B, name, content)
            _, cold = look(cold_in.id, B, name, content)
            step.learned, step.cold = learned, cold
            step.read_as, step.applied = _layout_json(inspection), _applied_json(inspection)
            step.expected = {}
            step.unreadable = "NO_TABLE" in learned.blockers
            step.wrong_family = learned.family is not None
            step.wrong_layout = step.applied is not None or step.unreadable
            step.contaminated = step.read_as != {}
            if not learned.ambiguous:
                step.problems.append("it could be either and was not seen as such")
            if learned.family is not None or learned.reused:
                step.problems.append(f"reused family {learned.family} {learned.reused}")
            if step.applied is not None or step.read_as != {}:
                step.problems.append(f"a sheet was applied: {step.applied} / {step.read_as}")
            if step.unreadable:
                step.problems.append("the document could not be read")
            step.ok = not step.problems
        elif kind == "import":
            assert fmt is not None
            month = next(imports)
            name, content = fmt.build(month, False)
            before = _frozen(_store(bench, site.domain, taught_in.id))
            inspection, _ = look(taught_in.id, fmt.domain, name, content)
            info = inspection.understanding
            if info is None or info.level.value != "READY" or info.questions or info.blockers:
                step.problems.append("a file read from memory was not ready")
            else:
                outcome = bench.service.import_file(
                    taught_in.id,
                    fmt.domain,
                    filename=name,
                    content=content,
                    snapshot_local_date=date(2026, month, 28),
                    mapped=MappedImport(inspection.proposal, save_configuration=True),
                )
                after = _frozen(_store(bench, site.domain, taught_in.id))
                step.intact = outcome.succeeded and after == before
                if not step.intact:
                    step.problems.append(f"the store changed: {before} -> {after}")
            step.ok = not step.problems
        step.why = "; ".join(step.problems)
        if kind in ("teach", "see", "import"):
            seen.add(key)
            last = key
        else:
            last = None
        steps.append(step)
        progress(f"  {site.id} {n:02d} {kind} {key} {variant} {'ok' if step.ok else 'NOT OK'}")
    final: Learning | None = _store(bench, site.domain, taught_in.id)
    return steps, {
        "site": site.id,
        "title": site.title,
        "domain": site.domain.value,
        "formats": list(site.formats),
        "families_in_memory": 0 if final is None else len(final.families),
        "layouts": sorted(
            {f: dict(FORMATS[f].layout) for f in site.formats}.items(), key=lambda item: item[0]
        ),
    }


def run_formats(
    session: Session,
    sites: tuple[Site, ...] = SITES,
    progress: Callable[[str], None] = lambda message: None,
) -> dict[str, Any]:
    bench = Bench(session, progress, workspace="multi-format")
    steps: list[Step] = []
    infos: list[dict[str, Any]] = []
    started = time.perf_counter()
    for site in sites:
        site_steps, info = run_site(bench, site, progress)
        steps.extend(site_steps)
        infos.append(info)
    return summarise_formats(steps, infos, time.perf_counter() - started)


def summarise_formats(
    steps: list[Step], infos: list[dict[str, Any]], seconds: float
) -> dict[str, Any]:
    see = [s for s in steps if s.kind == "see" and s.learned is not None]
    either = [s for s in steps if s.kind == "either"]
    imports = [s for s in steps if s.kind == "import"]
    returning = [s for s in see if s.returning and s.variant == "next"]
    unchanged = returning
    drifted = [s for s in see if s.variant == "extra"]
    saved = sum(
        max(0, s.cold.effort - s.learned.effort)
        for s in [*see, *either]
        if s.cold is not None and s.learned is not None
    )
    return {
        "benchmark": "source-learning-benchmark-v1/multi-format",
        "properties": len(infos),
        "formats": sum(len(i["formats"]) for i in infos),
        "documents": len(see) + len(either),
        "timeline_steps": len(steps),
        "correct_family": _rate(
            sum(
                1 for s in see if s.learned and s.learned.family is not None and not s.wrong_family
            ),
            len(see),
        ),
        "correct_family_layout": _rate(
            sum(1 for s in see if s.read_as == s.expected and not s.unreadable), len(see)
        ),
        "wrong_layout_reuse": sum(1 for s in [*see, *either] if s.wrong_layout),
        "cross_family_layout_contamination": sum(1 for s in [*see, *either] if s.contaminated),
        "documents_that_could_not_be_read": sum(1 for s in steps if s.unreadable),
        "returning_family_recognition": _rate(sum(1 for s in returning if s.ok), len(returning)),
        "repeated_mapping_questions_on_returning_unchanged": sum(
            len(s.learned.questions) + len(s.learned.blockers) for s in unchanged if s.learned
        ),
        "recognised_after_harmless_drift": _rate(sum(1 for s in drifted if s.ok), len(drifted)),
        "ambiguous_layout_reuse": sum(1 for s in either if s.applied is not None or s.read_as),
        "ambiguous_family_reuse": sum(
            1 for s in either if s.learned and (s.learned.family is not None or s.learned.reused)
        ),
        "store_intact_after_import": _rate(sum(1 for s in imports if s.intact), len(imports)),
        "questions_saved": {
            "asks_without_memory": sum(s.cold.effort for s in see if s.cold),
            "asks_with_memory": sum(s.learned.effort for s in see if s.learned),
            "saved": saved,
            "documents_asking_nothing_with_memory": sum(
                1 for s in see if s.learned and s.learned.automatic
            ),
            "documents_asking_nothing_without_memory": sum(
                1 for s in see if s.cold and s.cold.automatic
            ),
        },
        "every_step_as_expected": _rate(sum(1 for s in steps if s.ok), len(steps)),
        "failures": [
            {
                "site": s.site,
                "n": s.n,
                "kind": s.kind,
                "format": s.format,
                "variant": s.variant,
                "why": s.why,
            }  # fmt: skip
            for s in steps
            if not s.ok
        ],
        "seconds": round(seconds, 1),
        "per_site": infos,
        "steps": [_step_row(s) for s in steps],
    }


def _step_row(s: Step) -> dict[str, Any]:
    row: dict[str, Any] = {
        "site": s.site,
        "n": s.n,
        "kind": s.kind,
        "format": s.format,
        "variant": s.variant,
        "returning": s.returning,
        "ok": s.ok,
        "why": s.why,
    }
    if s.learned is not None:
        row.update(
            level=s.learned.level,
            questions=len(s.learned.questions),
            family_chosen=s.learned.family,
            ambiguous=s.learned.ambiguous,
            read_as=s.read_as,
            without_memory=None if s.cold is None else s.cold.level,
        )
    return row

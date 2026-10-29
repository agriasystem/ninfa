"""Staff files: where the DEPARTMENT of a row comes from, and what a grid of days needs.

A staff row belongs to a department. Most files say so in a column; some do not, and say it in a way
a person reads at a glance: a line of its own above the people ("RECEPTION"), the name of the sheet,
the title of the document. NINFA takes them in this order of trust and never asks "which department
are ALL these rows?" when the document already answers:

    1. a column                      (the importer reads it row by row)
    2. department lines              each line labels the rows under it
    3. one sheet per department      the sheet name labels its rows
    4. the name of the only sheet    ("Reception")
    5. the title                     ("TURNI HOUSEKEEPING - SETTIMANA 43") - one word, and
                                     the person CONFIRMS it: a title is the least certain
    6. nothing says it               ONE question

A word NINFA does not know ("HK", "Turno A") is never guessed: it is asked, once, and remembered.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.modules.bookings.text import normalize_key
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.mapping_types import MAX_LABEL_LENGTH
from app.modules.data_sources.proposal import Proposal
from app.modules.data_sources.semantics import Level
from app.modules.data_sources.understanding_types import (
    Blocker,
    BlockerCode,
    Choice,
    LabelCount,
    Origin,
    OriginKind,
    Question,
    QuestionKind,
)
from app.modules.document_understanding.days import hours_basis, resolve_days
from app.modules.document_understanding.document import DocumentUnderstanding, Selection
from app.modules.document_understanding.grid import SheetScan, WorkbookScan
from app.modules.document_understanding.layout import (
    DepartmentContext,
    GridLayout,
    LayoutSpec,
)
from app.modules.document_understanding.titles import department_words
from app.modules.document_understanding.values import CellKind, kind_of, text_of
from app.modules.labor.classification import classify_role, matching_categories
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod

MAX_LABELS_ASKED = 12
# How many rows of a grid are looked at to see whether its cells are hours.
_GRID_PROBE_ROWS = 60
DEPARTMENT_CHOICES: tuple[LaborCategory, ...] = tuple(LaborCategory)


def known_labels(*documents: Mapping[str, str]) -> dict[str, str]:
    """The words NINFA has been taught, by their comparison key (several documents merge, the
    last one wins)."""
    merged: dict[str, str] = {}
    for document in documents:
        merged.update({normalize_key(label): meaning for label, meaning in document.items()})
    return merged


# The words of a staff file that name a department or a job and nothing else - on top of the small
# dictionary the import itself classifies with (`labor.classification.RULES`). They are used only
# to READ a department column (or line, sheet, title): a word that is also in the import's rules, or
# that could be two departments, is not here. Whole words, by the comparison key. Codes ("HK",
# "FO", "REC") are deliberately NOT here: they are the hotel's own, asked once and remembered.
_LEXICON: Final[dict[LaborCategory, tuple[str, ...]]] = {
    LaborCategory.HOUSEKEEPING: (
        "governante",
        "governanti",
        "pulizie",
        "camerista",
        "cameriste",
        "addetta alle pulizie",
    ),
    LaborCategory.FRONT_OFFICE: (
        "ricevimento",
        "portineria",
        "portiere",
        "concierge",
        "front desk",
        "booking",
    ),
    LaborCategory.FOOD_BEVERAGE: (
        "ristorante",
        "ristorazione",
        "barista",
        "barman",
        "maitre",
        "banqueting",
        "colazioni",
        "f and b",  # ("F&B")
        "food and beverage",
        "restaurant",
    ),
    LaborCategory.KITCHEN: ("sous chef", "commis", "pizzaiolo", "lavapiatti"),
    LaborCategory.MAINTENANCE: ("manutentore", "manutentori", "engineering"),
    LaborCategory.MANAGEMENT: (
        "amministrazione",
        "direttore",
        "direttrice",
        "general manager",
        "ufficio amministrativo",
        "admin",
        "administration",
    ),
    LaborCategory.SPA_WELLNESS: ("centro benessere", "benessere", "estetista", "massaggiatrice"),
}


def _lexicon_matches(key: str) -> set[LaborCategory]:
    padded = f" {key} "
    return {
        category
        for category, phrases in _LEXICON.items()
        if any(f" {normalize_key(phrase)} " in padded for phrase in phrases)
    }


def _read_by_words(key: str, *, lexicon: bool) -> LaborCategory | None:
    """The one department the words of this label point at - by the import's own rules, and with
    NINFA's list on top when `lexicon` (not for a label too long to travel in the decision: the
    import would not know it) - or None when none does or two do."""
    with_list = lexicon and len(key) <= MAX_LABEL_LENGTH
    found = {*matching_categories(key), *(_lexicon_matches(key) if with_list else ())}
    return next(iter(found)) if len(found) == 1 else None


def names_a_department(label: str) -> bool:
    """Is this label a department by the import's own rules alone? The name of a SHEET is evidence
    of what kind of file it is only for these: "Booking" or "Amministrazione" also name sheets of
    reservation and cost files."""
    return classify_role(normalize_key(label)).method != LaborClassificationMethod.UNCLASSIFIED


def classifies(label: str, taught: Mapping[str, str], *, lexicon: bool = False) -> bool:
    """Does NINFA know which department this word is (the import's rules, or it was taught - and
    with `lexicon`, NINFA's own list too: what the understanding carries into the decision)?"""
    key = normalize_key(label)
    return key in taught or _read_by_words(key, lexicon=lexicon) is not None


def category_of(label: str, taught: Mapping[str, str], *, lexicon: bool = False) -> str | None:
    key = normalize_key(label)
    if key in taught:
        return taught[key]
    found = _read_by_words(key, lexicon=lexicon)
    return None if found is None else found.value


def lexicon_roles(labels: Sequence[tuple[str, int]], taught: Mapping[str, str]) -> dict[str, str]:
    """The words NINFA reads by its OWN list but that the import's rules alone would leave as
    "other": they travel in the decision so the import, which only reads its rules and confirmed
    words, files them under the same department."""
    found: dict[str, str] = {}
    for label, _count in labels:
        key = normalize_key(label)
        if key in taught or classify_role(key).method != LaborClassificationMethod.UNCLASSIFIED:
            continue
        category = _read_by_words(key, lexicon=True)
        if category is not None:
            found[label] = category.value
    return found


def department_choices() -> tuple[Choice, ...]:
    return tuple(Choice(category.value) for category in DEPARTMENT_CHOICES)


def label_question(
    labels: Sequence[tuple[str, int]],
    taught: Mapping[str, str],
    question_id: str = "LABELS:role_mapping",
    *,
    lexicon: bool = False,
) -> Question | None:
    """ONE question about the department words NINFA does not know (the most frequent first)."""
    unknown = [
        (label, count) for label, count in labels if not classifies(label, taught, lexicon=lexicon)
    ]
    if not unknown:
        return None
    unknown.sort(key=lambda item: (-item[1], item[0]))
    return Question(
        id=question_id,
        kind=QuestionKind.VALUE_LABELS,
        document="role_mapping",
        choices=department_choices(),
        labels=tuple(LabelCount(label, count) for label, count in unknown[:MAX_LABELS_ASKED]),
        total_labels=len(unknown),
    )


def column_labels(sample: ColumnSample) -> list[tuple[str, int]]:
    """The distinct words of a department column with how many rows each has."""
    counts: Counter[str] = Counter(
        text_of(value) for value in sample.values if kind_of(value) == CellKind.TEXT
    )
    return counts.most_common()


@dataclass(frozen=True, slots=True)
class LaborPlan:
    layout: LayoutSpec
    questions: tuple[Question, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    # Where the department comes from when it is not a column, and how sure that is.
    department_origin: Origin | None = None
    department_level: Level | None = None
    # The department words of lines, sheets or a title (a column's words are read from its cells).
    words: tuple[tuple[str, int], ...] = ()


def _sheet_scan(scan: WorkbookScan, name: str) -> SheetScan | None:
    return next((sheet for sheet in scan.sheets if sheet.name == name), None)


def _grid_is_hours(scan: WorkbookScan, selection: Selection) -> bool:
    """Are the cells under the day columns numbers? (Shift codes and time ranges are not hours.)"""
    grid = selection.day_grid
    table = selection.first
    sheet = _sheet_scan(scan, table.sheet)
    if grid is None or sheet is None:
        return False
    numeric = other = 0
    for number in range(
        table.first_row, min(table.last_row, table.first_row + _GRID_PROBE_ROWS) + 1
    ):
        cells = sheet.row(number) or []
        for day in grid.columns:
            cell = cells[day.index] if day.index < len(cells) else None
            kind = kind_of(cell)
            if kind == CellKind.EMPTY:
                continue
            if kind == CellKind.NUMBER:
                numeric += 1
            else:
                other += 1
    return numeric > 0 and numeric >= 0.9 * (numeric + other)


def plan_labor(
    *,
    scan: WorkbookScan,
    document: DocumentUnderstanding,
    selection: Selection,
    base: LayoutSpec,
    proposal: Proposal,
    taught: Mapping[str, str],
    asked_department: str | None,
    asked_department_from: str | None,
    asked_grid_hours: str | None,
    asked_period: bool,
) -> LaborPlan:
    """The layout a staff file needs, and the questions it still leaves open."""
    layout = base
    questions: list[Question] = []
    blockers: list[Blocker] = []
    origin: Origin | None = None
    level: Level | None = None

    # --- a grid of days ---------------------------------------------------------------------------
    grid = selection.day_grid
    if grid is not None:
        if selection.partition or len(grid.groups) > 1:
            blockers.append(Blocker(BlockerCode.GRID_NOT_SUPPORTED))
        elif not _grid_is_hours(scan, selection):
            blockers.append(Blocker(BlockerCode.GRID_NOT_HOURS))
        else:
            # what the person said, else what this file says, else how this source's grids were read
            basis = (
                asked_grid_hours
                or hours_basis(
                    grid, selection.title or "", selection.first.sheet, " ".join(selection.preamble)
                )
                or (base.grid.hours_field if base.grid is not None else None)
            )
            if basis is None:
                questions.append(
                    Question(
                        id="GRID_HOURS",
                        kind=QuestionKind.GRID_HOURS,
                        choices=(Choice("planned_hours"), Choice("actual_hours")),
                    )
                )
            else:
                layout = layout.model_copy(update={"grid": GridLayout(hours_field=basis)})
                days = resolve_days(
                    grid,
                    title_start=selection.period.start if selection.period else None,
                    person_start=layout.period_start,
                )
                if days is None and not asked_period:
                    questions.append(Question(id="PERIOD", kind=QuestionKind.PERIOD))

    # --- the department ---------------------------------------------------------------------------
    assigned = proposal.assigned()
    if "role" in assigned or "labor_category" in assigned or asked_department:
        return LaborPlan(layout, tuple(questions), tuple(blockers))

    table = selection.first
    sections = [label for _, label in table.sections]
    sheets = [t.sheet for t in selection.tables if t.sheet]
    kind: str | None = None
    labels: list[tuple[str, int]] = []
    if sections:
        kind, labels = "SECTION", [(label, 1) for label in dict.fromkeys(sections)]
        origin, level = Origin(OriginKind.SECTION), Level.HIGH
    elif selection.partition and sheets:
        kind, labels = "SHEET", [(name, 1) for name in sheets]
        origin, level = Origin(OriginKind.SHEET), Level.HIGH
    elif len(sheets) == 1 and classifies(sheets[0], taught, lexicon=True):
        kind, labels = "SHEET", [(sheets[0], 1)]
        origin, level = Origin(OriginKind.SHEET, sheets[0]), Level.HIGH
    else:
        words = department_words(selection.preamble)
        if len(words) == 1 and classifies(words[0], taught, lexicon=True):
            if asked_department_from == "TITLE":
                kind, labels = "TITLE", [(words[0], 1)]
                origin, level = Origin(OriginKind.TITLE, words[0]), Level.HIGH
            else:
                questions.append(
                    Question(
                        id="DEPARTMENT_CONFIRM",
                        kind=QuestionKind.DEPARTMENT_CONFIRM,
                        field="role",
                        candidate=category_of(words[0], taught, lexicon=True),
                        origin=OriginKind.TITLE,
                        choices=department_choices(),
                        labels=(LabelCount(words[0], 1),),
                    )
                )
        if kind is None and not questions:
            questions.append(
                Question(
                    id="DEPARTMENT_ROWS",
                    kind=QuestionKind.DEPARTMENT_ROWS,
                    field="labor_category",
                    choices=department_choices(),
                )
            )
    if kind is not None:
        layout = layout.model_copy(update={"department": DepartmentContext(kind=kind)})
        pending = label_question(labels, taught, lexicon=True)
        if pending is not None:
            questions.append(pending)
    del document
    return LaborPlan(layout, tuple(questions), tuple(blockers), origin, level, tuple(labels))


__all__ = [
    "DEPARTMENT_CHOICES",
    "LaborPlan",
    "category_of",
    "classifies",
    "column_labels",
    "department_choices",
    "known_labels",
    "label_question",
    "names_a_department",
    "lexicon_roles",
    "plan_labor",
]

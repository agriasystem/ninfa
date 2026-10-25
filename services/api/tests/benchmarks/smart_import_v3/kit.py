"""Small helpers every corpus module uses: a registry of cases, the facts of a drawn table, the
personal-data lists, and the shape ("structure") of a document, worked out from what was drawn."""

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from tests.benchmarks.smart_import_v3.draw import Sheet, TableRef
from tests.benchmarks.smart_import_v3.model import Doc, Golden
from tests.benchmarks.smart_import_v3.pool import seeded


@dataclass(slots=True)
class Built:
    filename: str
    content: bytes
    golden: Golden
    sheets: Sequence[Sheet] = ()
    card: str | None = None  # the kind of data chosen when uploading, when it is not the real one


CaseFunction = Callable[[random.Random], Built]


class Registry:
    """The cases of one domain, in order. A case id is `<prefix><nn>_<slug>`."""

    def __init__(self, prefix: str, domain: str) -> None:
        self.prefix = prefix
        self.domain = domain
        self._cases: list[tuple[str, tuple[str, ...], CaseFunction]] = []

    def case(self, slug: str, *tags: str) -> Callable[[CaseFunction], CaseFunction]:
        def register(function: CaseFunction) -> CaseFunction:
            number = len(self._cases) + 1
            self._cases.append((f"{self.prefix}{number:02d}_{slug}", tags, function))
            return function

        return register

    def build(self) -> list[Doc]:
        docs: list[Doc] = []
        for case_id, tags, function in self._cases:
            built = function(seeded(case_id))
            card = built.card or self.domain
            docs.append(
                Doc(
                    id=case_id,
                    card=card,
                    filename=built.filename,
                    content=built.content,
                    golden=built.golden,
                    tags=(*tags, "csv" if built.filename.endswith(".csv") else "xlsx"),
                    structure=structure_of(built),
                    sheet_count=max(1, len(built.sheets)),
                )
            )
        return docs


def facts(
    ref: TableRef, *, csv: bool = False, sheets: Sequence[str] | None = None
) -> dict[str, Any]:
    """The table part of a golden, from where the table was drawn."""
    return {
        "sheets": () if csv else tuple(sheets) if sheets is not None else (ref.sheet,),
        "header_rows": ref.header_rows,
        "first_row": ref.first_row,
        "data_rows": ref.data_rows,
        "skipped": dict(ref.skipped),
    }


def pii(columns: Iterable[Sequence[str]], values: Iterable[str]) -> dict[str, Any]:
    """The personal-data part of a golden: the columns, and every distinct value they hold."""
    return {
        "pii_columns": tuple(tuple(column) for column in columns),
        "pii_values": tuple(sorted({value for value in values if len(value) >= 5})),
    }


def structure_of(built: Built) -> tuple[str, ...]:
    """The shape of a document as tags (how many sheets, what surrounds the table, where the
    department comes from...), worked out from what was drawn and what the truth says."""
    golden = built.golden
    tags = ["csv" if built.filename.endswith(".csv") else "xlsx"]
    count = len(built.sheets)
    tags.append(f"sheets:{min(count, 4)}")
    if any(sheet.hidden for sheet in built.sheets):
        tags.append("hidden-sheet")
    if any(sheet.merges for sheet in built.sheets):
        tags.append("merged-cells")
    if any(sheet.left for sheet in built.sheets):
        tags.append("indented")
    if golden.header_rows:
        before = golden.header_rows[0] - 1
        tags.append("preamble:" + ("0" if before == 0 else "1-3" if before <= 3 else "4+"))
        if len(golden.header_rows) > 1:
            tags.append("two-level-header")
    for kind in ("totals", "notes", "sections"):
        if golden.skipped.get(kind):
            tags.append(kind)
    for name, source in golden.fields.items():
        if source.kind in {"SECTION", "SHEET", "TITLE", "GRID"}:
            tags.append(f"{name}-from-{source.kind.lower()}")
    if golden.outcome in {"REJECT", "NOT_AUTOMATIC"}:
        tags.append("refusal")
    return tuple(tags)

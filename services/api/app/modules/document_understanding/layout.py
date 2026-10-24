"""The few choices that make the reading of a file REPEATABLE: `LayoutSpec`.

The structure of a document (where the header is, what is a total) is re-detected,
deterministically, on every file - so it needs no row numbers saved. What cannot be re-derived
from the file alone is what the person (or a rule) decided: where the department of a row comes
from when there is no department column, which hours a day grid holds, which sheets to read.
Those travel in this small model, saved inside the mapping profile (`format_options.layout`) and
sent with a request.

A date NEVER lives in a saved profile: `period_start` is per file (the week this file is about).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SHEET_NAMES = 40
MAX_SHEET_NAME_LENGTH = 200

DepartmentKind = Literal["SECTION", "SHEET", "TITLE"]
HoursField = Literal["planned_hours", "actual_hours"]


class DepartmentContext(BaseModel):
    """Where the department of a row comes from when no column says it: a line of its own above
    the people (SECTION), the name of the sheet (SHEET) or the title of the document (TITLE)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DepartmentKind


class GridLayout(BaseModel):
    """A persons x days grid is read as one row per person per day; these are the hours in it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hours_field: HoursField


class LayoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    # Sheets to read, by name, when the person chose; empty = NINFA picks the data sheet(s).
    sheets: list[str] = Field(default_factory=list, max_length=MAX_SHEET_NAMES)
    # Which candidate table, when the document has more than one and the person chose.
    table_key: str | None = Field(default=None, max_length=300)
    department: DepartmentContext | None = None
    grid: GridLayout | None = None
    # The first day of the period this FILE is about (a grid whose days are written Lun/Mar/...).
    # Per file: never saved in a profile.
    period_start: date | None = None

    def for_profile(self) -> "LayoutSpec | None":
        """What is worth remembering for the next file: everything except this file's own dates."""
        kept = self.model_copy(update={"period_start": None})
        empty = not (kept.sheets or kept.table_key or kept.department or kept.grid)
        return None if empty else kept


__all__ = ["DepartmentContext", "DepartmentKind", "GridLayout", "HoursField", "LayoutSpec"]

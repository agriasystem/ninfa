"""What the lines above a table say: the period the file is about, and a department in its title.

Only what is written is read. A period is accepted when the text states ONE, completely ("dal
26/10/2026 al 01/11/2026", "26 ottobre - 1 novembre 2026", "settimana 43 2026"); anything vaguer is
no period at all and the person is asked. A week number without a year is not a date.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.document_understanding.lexicon import MONTHS, SECTION_WORDS
from app.modules.document_understanding.text import fold, stem

_SEP = r"\s*(?:-|–|—|/|al|a|to|fino al)\s*"
_DATE = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))

_FULL_RANGE = re.compile(rf"{_DATE}{_SEP}{_DATE}", re.IGNORECASE)
_SHORT_START = re.compile(rf"(\d{{1,2}})[/.\-](\d{{1,2}}){_SEP}{_DATE}", re.IGNORECASE)
_WORD_RANGE = re.compile(
    rf"(?:dal\s+)?(\d{{1,2}})\s+({_MONTH_NAMES})(?:\s+(\d{{4}}))?{_SEP}(\d{{1,2}})\s+({_MONTH_NAMES})(?:\s+(\d{{4}}))?",
    re.IGNORECASE,
)
_WEEK_START = re.compile(
    rf"(?:dal|settimana del|week of|from|settimana dal)\s+{_DATE}", re.IGNORECASE
)
_WEEK_NUMBER = re.compile(
    r"\b(?:settimana|sett\.?|week|wk)\s*(?:n\.?\s*)?(\d{1,2})\b", re.IGNORECASE
)
_YEAR = re.compile(r"\b(20\d{2})\b")


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    # None when the text gives only where the period starts.
    end: date | None
    text: str


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _range(start: date | None, end: date | None, text: str) -> DateRange | None:
    if start is None or end is None or end < start or (end - start).days > 400:
        return None
    return DateRange(start, end, text)


def _found(line: str) -> list[DateRange]:
    found: list[DateRange] = []
    for match in _FULL_RANGE.finditer(line):
        d1, m1, y1, d2, m2, y2 = (int(g) for g in match.groups())
        item = _range(_make(y1, m1, d1), _make(y2, m2, d2), match.group(0))
        if item:
            found.append(item)
    for match in _SHORT_START.finditer(line):
        d1, m1, d2, m2, y2 = (int(g) for g in match.groups())
        end = _make(y2, m2, d2)
        start = _make(y2 if m1 <= m2 else y2 - 1, m1, d1)
        item = _range(start, end, match.group(0))
        if item and not any(item.end == other.end for other in found):
            found.append(item)
    for match in _WORD_RANGE.finditer(line):
        first_day, first_month, first_year, last_day, last_month, last_year = match.groups()
        from_month, to_month = MONTHS[first_month.lower()], MONTHS[last_month.lower()]
        end_year = int(last_year) if last_year else (int(first_year) if first_year else None)
        if end_year is None:
            continue
        crosses_new_year = from_month > to_month
        start_year = int(first_year) if first_year else end_year - (1 if crosses_new_year else 0)
        item = _range(
            _make(start_year, from_month, int(first_day)),
            _make(end_year, to_month, int(last_day)),
            match.group(0),
        )
        if item and not any(item.end == other.end for other in found):
            found.append(item)
    for match in _WEEK_START.finditer(line):
        d1, m1, y1 = (int(g) for g in match.groups())
        start = _make(y1, m1, d1)
        if start is not None and not any(start == other.start for other in found):
            found.append(DateRange(start, None, match.group(0)))
    week = _WEEK_NUMBER.search(line)
    year = _YEAR.search(line)
    if week and year and not found:
        try:
            monday = date.fromisocalendar(int(year.group(1)), int(week.group(1)), 1)
        except ValueError:
            return found
        found.append(
            DateRange(monday, monday + timedelta(days=6), f"{week.group(0)} {year.group(0)}")
        )
    return found


def parse_period(lines: Iterable[str]) -> DateRange | None:
    """The one period the lines state, or None (nothing stated, or two different ones)."""
    candidates: list[DateRange] = []
    for line in lines:
        candidates.extend(_found(line))
    if not candidates:
        return None
    first = candidates[0]
    if any(item.start != first.start for item in candidates[1:]):
        return None  # two different periods: do not pick one
    best = next((item for item in candidates if item.end is not None), first)
    return best


def department_words(lines: Iterable[str]) -> list[str]:
    """The department words a title or a line contains, as written ("TURNI HOUSEKEEPING" ->
    ["HOUSEKEEPING"]). Words only: the meaning of each one is the domain's business."""
    seen: dict[str, str] = {}
    for line in lines:
        for raw in re.findall(r"[A-Za-zÀ-ÿ]+", line):
            if (
                len(raw) >= 3
                and stem(fold(raw)) in SECTION_WORDS
                and fold(raw) not in {"reparto", "area", "settore", "team"}
            ):
                seen.setdefault(fold(raw), raw)
    return list(seen.values())


__all__ = ["DateRange", "department_words", "parse_period"]

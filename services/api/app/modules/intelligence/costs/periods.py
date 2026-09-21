"""The calendar month of Cost CPOR V1 and its arithmetic (pure).

V1 evaluates CALENDAR MONTHS only: `period_start` is the first day, `period_end` the last. No
rolling window, week or quarter. A month is an immutable value; nothing here reads a clock.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True, order=True)
class CalendarMonth:
    year: int
    month: int

    def __post_init__(self) -> None:
        for value in (self.year, self.month):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("year and month must be integers")
        if not 1 <= self.month <= 12:
            raise ValueError("month must be between 1 and 12")
        if not 1 <= self.year <= 9999:
            raise ValueError("year must be between 1 and 9999")

    @property
    def index(self) -> int:
        """A running month number: consecutive months differ by exactly one."""
        return self.year * 12 + (self.month - 1)

    @property
    def start(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def days(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    def day_list(self) -> list[date]:
        first = self.start
        return [first + timedelta(days=offset) for offset in range(self.days)]

    def shifted(self, months: int) -> "CalendarMonth":
        index = self.index + months
        return CalendarMonth(index // 12, index % 12 + 1)

    def months_before(self, other: "CalendarMonth") -> int:
        """How many months this one is before `other` (negative when it is after)."""
        return other.index - self.index

    @classmethod
    def of(cls, day: date) -> "CalendarMonth":
        return cls(day.year, day.month)


def circular_month_distance(first: int, second: int) -> int:
    """Distance between two months of the year on the 12-month circle (January-December is 1)."""
    gap = abs(first - second) % 12
    return min(gap, 12 - gap)

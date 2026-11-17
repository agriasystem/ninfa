"""Small, shared helpers for turning NINFA's typed values into what an `Observation` may carry.

An observation is JSON for a model, and the numeric grounding guard reads its numbers literally, so
a figure keeps the form NINFA stores (`"62.50"`, `1100`) and never a rounded or localised one; the
model writes the Italian form (`62,50`) and the guard matches the two. A missing value is `None`.
"""

from datetime import date, datetime
from decimal import Decimal

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def dec(value: Decimal | int | None) -> str | None:
    """A decimal as the plain string NINFA stores ("62.50"); `None` stays `None` (never "0")."""
    if value is None:
        return None
    return format(value, "f")


def day(value: date | None) -> str | None:
    """An ISO date with its weekday, the form the model's calendar uses: "2026-11-20, venerdì"."""
    if value is None:
        return None
    return f"{value.isoformat()}, {_WEEKDAYS[value.weekday()]}"


def iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def moment(value: datetime | None) -> str | None:
    """An instant as ISO 8601; the caller says in `notes` which time zone reading applies."""
    return None if value is None else value.isoformat()


def window_label(start: date | None, end: date | None) -> str | None:
    if start is None or end is None:
        return None
    return f"dal {start.isoformat()} al {end.isoformat()}"


__all__ = ["dec", "day", "iso", "moment", "window_label"]

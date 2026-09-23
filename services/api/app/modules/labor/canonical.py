"""The canonical labor entry: values, minutes, fingerprint and their staged (JSON) form.

Everything here is deterministic and free of I/O and float. Hours are `Decimal` from the first
character to the conversion into MINUTES (never a float, never a silent round): a fraction of a
minute is rejected by the caller, never rounded away, so aggregations never drift.

Privacy: a CanonicalEntry carries no employee identity. `role_raw` is the free-text label the
source used for a SHIFT/ROW (e.g. "Reception AM"), never a person's name; V1 does not require it
and a mapping may omit it entirely when `labor_category` is explicit.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.labor.roles import LaborCategory, LaborClassificationMethod

_FINGERPRINT_FORMAT = 1
_SIXTY = Decimal(60)


def plain(value: Decimal | None) -> str | None:
    """Canonical text of a Decimal: equal numbers give equal text (`1.50` and `1.5` alike)."""
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def money_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, ".2f")


def hours_to_minutes(hours: Decimal) -> int:
    """`hours * 60` as an EXACT integer number of minutes.

    Raises ValueError when the value is not a whole number of minutes (a fraction of a minute is
    rejected, never rounded silently: rounding here would drift every later aggregation).
    """
    minutes = hours * _SIXTY
    integral = minutes.to_integral_value()
    if minutes != integral:
        raise ValueError("hours do not convert to a whole number of minutes")
    return int(integral)


@dataclass(frozen=True, slots=True)
class CanonicalEntry:
    """One canonical labor entry: a work date, a category and its hours/cost (no employee)."""

    source_row_number: int
    work_date: date
    role_raw: str | None
    role_normalized: str | None
    labor_category: LaborCategory
    planned_minutes: int | None
    actual_minutes: int | None
    planned_cost: Decimal | None
    actual_cost: Decimal | None
    currency: str | None
    classification_method: LaborClassificationMethod
    classification_confidence: Decimal

    def canonical_payload(self) -> dict[str, Any]:
        """The logical content of the entry: no row number, no import metadata."""
        return {
            "work_date": self.work_date.isoformat(),
            "role_normalized": self.role_normalized,
            "labor_category": self.labor_category.value,
            "planned_minutes": self.planned_minutes,
            "actual_minutes": self.actual_minutes,
            "planned_cost": money_text(self.planned_cost),
            "actual_cost": money_text(self.actual_cost),
            "currency": self.currency,
            "classification_method": self.classification_method.value,
            "classification_confidence": plain(self.classification_confidence),
        }


def snapshot_fingerprint(
    *,
    snapshot_local_date: date,
    property_id: str,
    data_source_id: str,
    entries: list[CanonicalEntry],
) -> str:
    """SHA-256 of the CANONICAL business content of a labor snapshot, and of nothing technical.

    It covers the snapshot date, the property, the data source and every canonical entry
    (work date, normalised role, category, minutes, cost, currency, classification provenance).
    It excludes the file name, the import job id, `created_at` and any runtime timestamp: two
    source files (CSV or XLSX) that state the same canonical content give the same fingerprint,
    whatever order their rows were in.
    """
    payloads = [entry.canonical_payload() for entry in entries]
    # A total, deterministic order that does not depend on the input row order: entries that
    # differ in any field sort differently; entries that are identical are indistinguishable, so
    # swapping them changes nothing about the hashed content.
    ordered = sorted(payloads, key=lambda item: json.dumps(item, sort_keys=True))
    document = {
        "v": _FINGERPRINT_FORMAT,
        "snapshot_local_date": snapshot_local_date.isoformat(),
        "property_id": property_id,
        "data_source_id": data_source_id,
        "entries": ordered,
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_payload(entry: CanonicalEntry) -> dict[str, Any]:
    """The JSON staged for one VALID row (data minimisation: only canonical fields)."""
    return {
        "source_row_number": entry.source_row_number,
        "work_date": entry.work_date.isoformat(),
        "role_raw": entry.role_raw,
        "role_normalized": entry.role_normalized,
        "labor_category": entry.labor_category.value,
        "planned_minutes": entry.planned_minutes,
        "actual_minutes": entry.actual_minutes,
        "planned_cost": plain(entry.planned_cost),
        "actual_cost": plain(entry.actual_cost),
        "currency": entry.currency,
        "classification_method": entry.classification_method.value,
        "classification_confidence": plain(entry.classification_confidence),
    }


def entry_from_payload(payload: dict[str, Any]) -> CanonicalEntry:
    def opt_decimal(key: str) -> Decimal | None:
        return None if payload[key] is None else Decimal(payload[key])

    return CanonicalEntry(
        source_row_number=payload["source_row_number"],
        work_date=date.fromisoformat(payload["work_date"]),
        role_raw=payload["role_raw"],
        role_normalized=payload["role_normalized"],
        labor_category=LaborCategory(payload["labor_category"]),
        planned_minutes=payload["planned_minutes"],
        actual_minutes=payload["actual_minutes"],
        planned_cost=opt_decimal("planned_cost"),
        actual_cost=opt_decimal("actual_cost"),
        currency=payload["currency"],
        classification_method=LaborClassificationMethod(payload["classification_method"]),
        classification_confidence=Decimal(payload["classification_confidence"]),
    )

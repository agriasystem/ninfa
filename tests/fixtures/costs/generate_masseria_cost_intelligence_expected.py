"""Independent calculation of the Gate 7 golden scenario ("MASSERIA NINFA DEMO — COST DATA V1",
extended with the cost intelligence of COST_CPOR_ANOMALY).

Standard library only (csv, fractions, calendar, datetime, json, importlib). It shares NO code with
the application: not the month arithmetic, not the occupancy denominator, not the cost
aggregation, not the comparable selection, not the statistics, not the confidence, not the rule.
Exact arithmetic (`fractions.Fraction`) is used everywhere; the application uses `Decimal`. The
only thing it borrows is the FatturaPA / CSV *file writers* of the Gate 6 fixture generator (which
is itself standard-library only), to write the invoice files the Gate 6 import service reads.

It (re)writes, next to itself:

  masseria_ninfa_cost_bookings_v1.csv            one booking per day (rooms per day by design)
  invoices/*.xml, invoices/software.csv          the cost files, imported by the Gate 6 service
  masseria_ninfa_cost_intelligence_v1.expected.json
                                                 the world, the occupancy of every month, and for
                                                 every case the metric, the comparables, the
                                                 statistics, the confidence and the evaluation

The expected result is what the WORLD below says, computed from the specification
(docs/architecture/cost-cpor-anomaly-v1.md) with its own code, never by calling the application:

* occupancy: the lead-time-0 rooms of every day of a month; a missing day or an uncertain snapshot
  makes the month incomplete (never zero); observed / reconstructed day counts and provenance;
* cost: the signed line totals of the invoices dated in the month, by currency and category;
  classification coverage and weighted confidence over the classified (not OTHER) lines;
* comparables: strictly earlier months, at most 36 back, circular season distance <= 2, READY only,
  observed-first, 5..12, most recent first; median / P25 / P75 / IQR / fence by linear
  interpolation; the four trigger conditions (AND); baseline confidence, caps, target quality,
  final minimum, the gate of 55.

Run it from anywhere:  python generate_masseria_cost_intelligence_expected.py
"""

import calendar
import csv
import importlib.util
import io
import json
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
INVOICE_DIR = HERE / "invoices"
BOOKINGS = HERE / "masseria_ninfa_cost_bookings_v1.csv"
EXPECTED = HERE / "masseria_ninfa_cost_intelligence_v1.expected.json"

_spec = importlib.util.spec_from_file_location(
    "gate6_invoice_generator", HERE.parent / "invoices" / "generate_cost_fixtures.py"
)
assert _spec is not None and _spec.loader is not None
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

RULES_VERSION = "cost-cpor-anomaly-v1"
METRIC_VERSION = "cost-period-metric-v1"
EXPECTED_METHOD = "cost-cpor-expected-v1"
FRACTION_ZERO = Fraction(0)


def F(value: str | int) -> Fraction:
    return Fraction(value)


def q2(value: Fraction) -> Fraction:
    """Round half away from zero to two decimals."""
    return inv.half_up_2(value)


# --- the world: rooms per day, how each month is known, the costs --------------------------------

# month -> (base rooms per day, how the lead-time-0 snapshots exist)
#   R = reconstructed (a Gate 3 reconstruction, always approximate)
#   O = observed day by day (the Gate 3 observed service, one run per day)
MONTHS: dict[str, tuple[int, str]] = {
    "2024-05": (9, "R"),
    "2024-06": (10, "R"),
    "2024-07": (11, "R"),
    "2024-08": (12, "R"),
    "2024-09": (10, "R"),
    "2024-10": (8, "R"),
    "2025-05": (9, "R"),
    "2025-06": (10, "R"),
    "2025-07": (12, "R"),
    "2025-08": (13, "R"),
    "2025-09": (10, "R"),  # one day is uncertain (a cancellation without a date)
    "2025-10": (8, "R"),
    "2026-05": (10, "O"),  # one day has no snapshot at all
    "2026-06": (11, "O"),
    "2026-07": (12, "O"),
    "2026-08": (13, "O"),
    "2026-10": (0, "O"),  # a closed month: every day observed, zero rooms
}
MISSING_DAYS = {"2026-05": [17]}
UNCERTAIN_DAYS = {"2025-09": [12]}


def parse_month(text: str) -> tuple[int, int]:
    year, month = text.split("-")
    return int(year), int(month)


def month_days(text: str) -> list[date]:
    year, month = parse_month(text)
    return [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def rooms_on(day: date, base: int) -> int:
    """Rooms on the books for a stay night: `base`, plus one room on days 7, 14, 21 and 28."""
    return 0 if base == 0 else base + (1 if day.day % 7 == 0 else 0)


def month_index(text: str) -> int:
    year, month = parse_month(text)
    return year * 12 + month - 1


def month_text(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


# CPOR by design (what each month was made to cost per occupied room). The invoice is
# round(cpor * occupied room nights, 2): the golden checks the pipeline, not the design.
LAUNDRY_CPOR = {
    "2024-05": "3.00", "2024-06": "3.10", "2024-07": "3.20", "2024-08": "3.30",
    "2024-09": "3.10", "2024-10": "3.00", "2025-05": "3.20", "2025-06": "3.30",
    "2025-07": "3.40", "2025-08": "3.50", "2025-09": "3.30", "2025-10": "3.20",
    "2026-05": "3.30", "2026-06": "3.40", "2026-07": "3.50",
    "2026-08": "6.00",  # A: the anomalous month
}
UTILITIES_CPOR = {  # C: a volatile history, so a high delta is not above the robust fence
    "2026-07": "2.0", "2025-10": "1.0", "2025-08": "3.5", "2025-07": "3.0", "2025-06": "2.0",
    "2024-10": "0.8", "2024-09": "1.5", "2024-08": "4.0", "2024-07": "3.5", "2024-06": "2.5",
    "2026-08": "3.6",
}
SOFTWARE_CPOR = {  # D: a tight history, +33 % but a gap of about 40 currency units
    **{m: "0.30" for m in ("2026-07", "2025-06", "2025-07", "2025-08", "2025-10",
                            "2024-06", "2024-07", "2024-08", "2024-09", "2024-10")},
    "2026-08": "0.40",
}
CLEANING_CPOR = {  # E: five reconstructed months of wild values, a very high target
    "2025-06": "1.0", "2025-07": "1.0", "2025-08": "2.0", "2025-10": "6.0", "2024-06": "8.0",
    "2026-08": "15.0",
}
MAINTENANCE_CPOR = {"2025-06": "1.0", "2025-07": "1.0", "2025-08": "1.0", "2026-08": "2.0"}
OTHER_AMOUNT = {m: F("50.00") for m in MONTHS if m != "2026-10"}
OTHER_AMOUNT["2026-06"] = F("900.00")  # G: too much of June 2026 is OTHER
OTA_MONTHS = ("2025-06", "2025-07", "2025-08", "2025-10", "2024-06")  # K: credit notes win
USD_LAUNDRY = {"2025-08": F("700.00"), "2026-08": F("5000.00")}  # O: another currency
LAUNDRY_CLOSED_MONTH = F("300.00")  # J: an invoice in a month with no guest


# --- occupancy: the lead-time-0 denominator of a month -------------------------------------------


def occupancy(month: str) -> dict:
    """What the lead-time-0 snapshots of a month say (independently of the application)."""
    base, kind = MONTHS[month]
    days = month_days(month)
    missing = set(MISSING_DAYS.get(month, []))
    uncertain = set(UNCERTAIN_DAYS.get(month, []))
    observed = reconstructed = missing_count = uncertain_count = rooms = 0
    for day in days:
        if day.day in missing:
            missing_count += 1
        elif day.day in uncertain:
            uncertain_count += 1
        else:
            rooms += rooms_on(day, base)
            if kind == "O":
                observed += 1
            else:
                reconstructed += 1
    complete = missing_count == 0 and uncertain_count == 0
    return {
        "days": len(days),
        "observed": observed,
        "reconstructed": reconstructed,
        "missing": missing_count,
        "uncertain": uncertain_count,
        "complete": complete,
        "room_nights": rooms if complete else None,
        "provenance": (
            Fraction(observed * 100 + reconstructed * 60, len(days)) if complete else None
        ),
    }


def room_nights(month: str) -> int:
    """The rooms the month was DESIGNED to have (the invoices are sized on it), whatever the
    snapshots later say: a missing or uncertain day still had its rooms in the design."""
    base, _kind = MONTHS[month]
    return sum(rooms_on(day, base) for day in month_days(month))


# --- costs: the invoices, as documents ---------------------------------------------------------


class Doc:
    """One invoice document of the world (a FatturaPA body or a CSV invoice)."""

    def __init__(self, category, month, day, currency, kind, lines, number, supplier):
        self.category, self.month, self.day = category, month, day
        self.currency, self.kind, self.number, self.supplier = currency, kind, number, supplier
        self.lines = lines  # [(description, amount as written in the source, confidence)]

    @property
    def sign(self) -> int:
        return -1 if self.kind == "CREDIT_NOTE" else 1


DOCS: list[Doc] = []
CONF_RULE, CONF_EXPLICIT = F(80), F(100)


def add_doc(category, month, day, currency, kind, lines, supplier, tag):
    DOCS.append(Doc(category, month, day, currency, kind, lines, f"{tag}-{month}-{len(DOCS)}", supplier))


def build_docs() -> None:
    DOCS.clear()
    for month, cpor in LAUNDRY_CPOR.items():
        net = q2(F(cpor) * room_nights(month))
        first = q2(net * F("0.8"))
        lines_ = [("Servizio lavanderia biancheria camere", first, CONF_RULE),
                  ("Noleggio biancheria ospiti", net - first, CONF_RULE)]
        if month == "2026-07":
            # the invoice is dated on the last day of July (INVOICE_DATE_ATTRIBUTION); a credit note
            # written with POSITIVE amounts (TD04) takes 184.00 off it: the month nets to `net`
            credit = F("184.00")
            gross = net + credit
            first = q2(gross * F("0.8"))
            add_doc("LAUNDRY", month, date(2026, 7, 31), "EUR", "INVOICE",
                    [("Servizio lavanderia biancheria camere", first, CONF_RULE),
                     ("Noleggio biancheria ospiti", gross - first, CONF_RULE)], "LAV", "L")
            add_doc("LAUNDRY", month, date(2026, 7, 20), "EUR", "CREDIT_NOTE",
                    [("Storno lavanderia biancheria camere (reclamo)", credit, CONF_RULE)],
                    "LAV", "LNC")
        else:
            year, number = parse_month(month)
            add_doc("LAUNDRY", month, date(year, number, 10), "EUR", "INVOICE", lines_, "LAV", "L")
    add_doc("LAUNDRY", "2026-10", date(2026, 10, 12), "EUR", "INVOICE",
            [("Servizio lavanderia biancheria camere", LAUNDRY_CLOSED_MONTH, CONF_RULE)],
            "LAV", "L")
    for month, amount in USD_LAUNDRY.items():
        year, number = parse_month(month)
        add_doc("LAUNDRY", month, date(year, number, 11), "USD", "INVOICE",
                [("Servizio lavanderia biancheria camere", amount, CONF_RULE)], "LAV", "LU")
    for month, cpor in UTILITIES_CPOR.items():
        year, number = parse_month(month)
        add_doc("UTILITIES", month, date(year, number, 10), "EUR", "INVOICE",
                [("Fornitura energia elettrica", q2(F(cpor) * room_nights(month)), CONF_RULE)],
                "ENE", "E")
    for month, cpor in CLEANING_CPOR.items():
        year, number = parse_month(month)
        add_doc("CLEANING", month, date(year, number, 10), "EUR", "INVOICE",
                [("Servizio di pulizia camere", q2(F(cpor) * room_nights(month)), CONF_RULE)],
                "PUL", "P")
    for month, cpor in MAINTENANCE_CPOR.items():
        year, number = parse_month(month)
        amount = F("800.00") if month == "2026-08" else q2(F(cpor) * room_nights(month))
        add_doc("MAINTENANCE", month, date(year, number, 10), "EUR", "INVOICE",
                [("Manutenzione impianti", amount, CONF_RULE)], "MAN", "M")
    for month in OTA_MONTHS:
        year, number = parse_month(month)
        add_doc("OTA_COMMISSIONS", month, date(year, number, 10), "EUR", "INVOICE",
                [("Commissioni Booking", F("100.00"), CONF_RULE)], "OTA", "O")
        add_doc("OTA_COMMISSIONS", month, date(year, number, 20), "EUR", "CREDIT_NOTE",
                [("Storno commissioni Booking", F("250.00"), CONF_RULE)], "OTA", "ONC")
    add_doc("OTA_COMMISSIONS", "2026-08", date(2026, 8, 10), "EUR", "INVOICE",
            [("Commissioni Booking", F("500.00"), CONF_RULE)], "OTA", "O")
    for month, amount in OTHER_AMOUNT.items():
        year, number = parse_month(month)
        add_doc("OTHER", month, date(year, number, 15), "EUR", "INVOICE",
                [("Materiale vario", amount, F(0))], "VAR", "V")
    for month, cpor in SOFTWARE_CPOR.items():
        year, number = parse_month(month)
        add_doc("SOFTWARE", month, date(year, number, 10), "EUR", "INVOICE",
                [("Canone software gestionale", q2(F(cpor) * room_nights(month)), CONF_EXPLICIT)],
                "SOF", "S")


def cost_index() -> dict[tuple[str, str, str], dict]:
    """(month, currency, category) -> the sums of the signed lines of that cell."""
    index: dict[tuple[str, str, str], dict] = {}
    for doc in DOCS:
        cell = index.setdefault(
            (doc.month, doc.currency, doc.category),
            {"net": FRACTION_ZERO, "absolute": FRACTION_ZERO, "weighted": FRACTION_ZERO,
             "invoices": set(), "lines": 0, "credit_lines": 0, "credit_cost": FRACTION_ZERO},
        )
        for _description, amount, confidence in doc.lines:
            signed = doc.sign * amount
            cell["net"] += signed
            cell["absolute"] += abs(signed)
            cell["weighted"] += abs(signed) * confidence
            cell["invoices"].add(doc.number)
            cell["lines"] += 1
            if doc.kind == "CREDIT_NOTE":
                cell["credit_lines"] += 1
                cell["credit_cost"] += signed
    return index


# --- the period metric (independent implementation) ------------------------------------------------


def frac_text(value: Fraction | None) -> str | None:
    return None if value is None else f"{value.numerator}/{value.denominator}"


def metric(month: str, category: str, currency: str, index: dict) -> dict:
    """The metric of one (month, category, currency), as a dict of Fractions and integers."""
    occ = occupancy(month) if month in MONTHS else None
    if occ is None:  # a month with no snapshot at all
        days = len(month_days(month))
        occ = {"days": days, "observed": 0, "reconstructed": 0, "missing": days,
               "uncertain": 0, "complete": False, "room_nights": None, "provenance": None}
    cells = {c: v for (m, cur, c), v in index.items() if m == month and cur == currency}
    own = cells.get(category)
    total = sum((v["absolute"] for v in cells.values()), FRACTION_ZERO) if cells else None
    classified = (
        sum((v["absolute"] for c, v in cells.items() if c != "OTHER"), FRACTION_ZERO)
        if cells else None
    )
    weighted_numerator = sum(
        (v["weighted"] for c, v in cells.items() if c != "OTHER"), FRACTION_ZERO
    )
    coverage = classified * 100 / total if cells and total and total > 0 else None
    weighted_conf = weighted_numerator / classified if cells and classified and classified > 0 else None
    cpor = None
    reasons: list[str]
    if not cells:
        status, reasons = "NO_COST_DATA", ["COST_CURRENCY_NOT_PRESENT"]
    elif own is None:
        status, reasons = "NO_COST_DATA", ["COST_CATEGORY_NOT_PRESENT"]
    elif not occ["complete"]:
        status, reasons = "INCOMPLETE", ["OCCUPANCY_PERIOD_INCOMPLETE"]
    elif occ["room_nights"] == 0:
        status, reasons = "ZERO_OCCUPANCY", ["ZERO_OCCUPIED_ROOM_NIGHTS"]
    elif coverage is None:
        status, reasons = "LOW_CLASSIFICATION_COVERAGE", ["COST_CLASSIFICATION_COVERAGE_UNDEFINED"]
    elif coverage < 70:
        status, reasons = "LOW_CLASSIFICATION_COVERAGE", ["COST_CLASSIFICATION_COVERAGE_LOW"]
    else:
        status, reasons = "READY", []
        cpor = own["net"] / occ["room_nights"]
    return {
        "month": month,
        "category": category,
        "currency": currency,
        "net_cost": None if own is None else own["net"],
        "absolute_category_cost": None if own is None else own["absolute"],
        "total_absolute_cost": total,
        "classified_absolute_cost": classified,
        "classification_coverage_pct": coverage,
        "weighted_classification_confidence": weighted_conf,
        "occupied_room_nights": occ["room_nights"],
        "observed_day_count": occ["observed"],
        "reconstructed_day_count": occ["reconstructed"],
        "missing_day_count": occ["missing"],
        "uncertain_day_count": occ["uncertain"],
        "occupancy_provenance_score": occ["provenance"],
        "invoice_count": 0 if own is None else len(own["invoices"]),
        "line_count": 0 if own is None else own["lines"],
        "credit_note_line_count": 0 if own is None else own["credit_lines"],
        "credit_note_cost": None if own is None else own["credit_cost"],
        "cpor": cpor,
        "status": status,
        "reason_codes": reasons,
    }


def metric_payload(m: dict) -> dict:
    """The canonical payload of a metric, without the run-time ids (the test adds them back)."""
    first = date(*parse_month(m["month"]), 1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    payload = {
        "period_start": first.isoformat(),
        "period_end": last.isoformat(),
        "cost_category": m["category"],
        "currency": m["currency"],
        "cost_attribution": "INVOICE_DATE_ATTRIBUTION",
        "occupancy_proxy": "LEAD_TIME_0_ROOMS_ON_BOOKS_PROXY",
        "net_cost": frac_text(m["net_cost"]),
        "absolute_category_cost": frac_text(m["absolute_category_cost"]),
        "total_absolute_cost": frac_text(m["total_absolute_cost"]),
        "classified_absolute_cost": frac_text(m["classified_absolute_cost"]),
        "classification_coverage_pct": frac_text(m["classification_coverage_pct"]),
        "weighted_classification_confidence": frac_text(m["weighted_classification_confidence"]),
        "occupied_room_nights": m["occupied_room_nights"],
        "observed_day_count": m["observed_day_count"],
        "reconstructed_day_count": m["reconstructed_day_count"],
        "missing_day_count": m["missing_day_count"],
        "uncertain_day_count": m["uncertain_day_count"],
        "occupancy_provenance_score": frac_text(m["occupancy_provenance_score"]),
        "invoice_count": m["invoice_count"],
        "line_count": m["line_count"],
        "credit_note_line_count": m["credit_note_line_count"],
        "credit_note_cost": frac_text(m["credit_note_cost"]),
        "cpor": frac_text(m["cpor"]),
        "status": m["status"],
        "reason_codes": m["reason_codes"],
        "calculation_version": METRIC_VERSION,
    }
    return payload


# --- comparables, statistics, confidence, the rule ----------------------------------------------


def circular_distance(a: int, b: int) -> int:
    gap = abs(a - b) % 12
    return min(gap, 12 - gap)


def candidates(target: str) -> list[str]:
    """Months strictly before the target, at most 36 back, within 2 months of its season."""
    t = month_index(target)
    found = []
    for back in range(1, 37):
        month = month_text(t - back)
        if circular_distance(parse_month(month)[1], parse_month(target)[1]) <= 2:
            found.append(month)
    return found


def percentile(values: list[Fraction], p: Fraction) -> Fraction:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = position.numerator // position.denominator
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def median(values: list[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def select(target: str, category: str, currency: str, index: dict) -> dict:
    eligible, counts = [], {"no_cost": 0, "low": 0, "incomplete": 0, "zero": 0}
    for month in candidates(target):
        m = metric(month, category, currency, index)
        if m["status"] == "READY":
            eligible.append(m)
        elif m["status"] == "NO_COST_DATA":
            counts["no_cost"] += 1
        elif m["status"] == "LOW_CLASSIFICATION_COVERAGE":
            counts["low"] += 1
        elif m["status"] == "INCOMPLETE":
            counts["incomplete"] += 1
        else:
            counts["zero"] += 1
    observed = [m for m in eligible if m["reconstructed_day_count"] == 0]
    if len(observed) >= 5:
        used = observed[:12]
    else:
        approximate = [m for m in eligible if m["reconstructed_day_count"] > 0]
        used = sorted(observed + approximate[: max(0, 12 - len(observed))],
                      key=lambda m: month_index(m["month"]), reverse=True)
    return {"used": used, "candidates": len(candidates(target)), "eligible": len(eligible), **counts}


def evaluate(target_month: str, category: str, currency: str, index: dict) -> dict:
    """One evaluation, as a dict shaped like the application's canonical payload (Fractions as text)."""
    target = metric(target_month, category, currency, index)
    thresholds = {
        "relative_percent": "20/1", "absolute_gap": "100/1", "iqr_multiplier": "3/2",
        "min_confidence": "55/1", "min_classification_coverage": "70/1",
        "min_comparables": 5, "max_comparables": 12, "lookback_months": 36,
        "season_window_months": 2,
    }
    body: dict = {
        "decision_type": "COST_CPOR_ANOMALY",
        "target_period_start": metric_payload(target)["period_start"],
        "target_period_end": metric_payload(target)["period_end"],
        "cost_category": category,
        "currency": currency,
        "target_metric": metric_payload(target),
        "expected_cpor": None, "p25": None, "p75": None, "iqr": None, "upper_fence": None,
        "delta_cpor": None, "delta_percent": None, "expected_cost_for_target_volume": None,
        "cost_gap_proxy": None,
        "above_expected_condition": None, "relative_condition": None,
        "upper_fence_condition": None, "gap_condition": None,
        "sample_count": 0, "observed_period_count": 0, "approximate_period_count": 0,
        "candidate_month_count": 0, "rejected_no_cost_data_count": 0,
        "rejected_low_classification_count": 0, "rejected_incomplete_occupancy_count": 0,
        "rejected_zero_occupancy_count": 0,
        "baseline_confidence": None, "sample_score": None, "provenance_score": None,
        "classification_score": None, "stability_score": None, "confidence_cap": None,
        "target_quality": None, "confidence_score": "0/1",
        "thresholds": thresholds, "comparable_periods": [],
        "rules_version": RULES_VERSION, "metric_version": METRIC_VERSION,
        "expected_method": EXPECTED_METHOD,
    }

    def done(status: str, reasons: list[str]) -> dict:
        body["status"], body["reason_codes"] = status, reasons
        return body

    if category == "OTHER":
        return done("NOT_APPLICABLE", ["COST_CATEGORY_OTHER_NOT_ACTIONABLE"])
    if target["status"] != "READY":
        status = {"NO_COST_DATA": "NOT_APPLICABLE", "INCOMPLETE": "INSUFFICIENT_DATA",
                  "ZERO_OCCUPANCY": "NOT_APPLICABLE",
                  "LOW_CLASSIFICATION_COVERAGE": "INSUFFICIENT_DATA"}[target["status"]]
        return done(status, target["reason_codes"])

    chosen = select(target_month, category, currency, index)
    used = chosen["used"]
    observed_used = sum(1 for m in used if m["reconstructed_day_count"] == 0)
    body.update(
        sample_count=len(used), observed_period_count=observed_used,
        approximate_period_count=len(used) - observed_used, candidate_month_count=chosen["candidates"],
        rejected_no_cost_data_count=chosen["no_cost"], rejected_low_classification_count=chosen["low"],
        rejected_incomplete_occupancy_count=chosen["incomplete"],
        rejected_zero_occupancy_count=chosen["zero"],
    )
    if len(used) < 5:
        return done("INSUFFICIENT_DATA", ["COMPARABLE_SAMPLE_INSUFFICIENT"])

    body["comparable_periods"] = [
        {
            "period_start": metric_payload(m)["period_start"],
            "period_end": metric_payload(m)["period_end"],
            "cpor": frac_text(m["cpor"]),
            "net_cost": frac_text(m["net_cost"]),
            "absolute_category_cost": frac_text(m["absolute_category_cost"]),
            "occupied_room_nights": m["occupied_room_nights"],
            "observed_day_count": m["observed_day_count"],
            "reconstructed_day_count": m["reconstructed_day_count"],
            "occupancy_provenance_score": frac_text(m["occupancy_provenance_score"]),
            "classification_coverage_pct": frac_text(m["classification_coverage_pct"]),
            "weighted_classification_confidence": frac_text(m["weighted_classification_confidence"]),
            "invoice_count": m["invoice_count"],
            "line_count": m["line_count"],
        }
        for m in used
    ]
    values = [m["cpor"] for m in used]
    expected = median(values)
    p25, p75 = percentile(values, Fraction(1, 4)), percentile(values, Fraction(3, 4))
    iqr = p75 - p25
    fence = p75 + Fraction(3, 2) * iqr
    body.update(expected_cpor=frac_text(expected), p25=frac_text(p25), p75=frac_text(p75),
                iqr=frac_text(iqr), upper_fence=frac_text(fence))
    if expected <= 0:
        return done("NOT_APPLICABLE", ["EXPECTED_CPOR_NON_POSITIVE"])

    actual = target["cpor"]
    delta = actual - expected
    delta_percent = delta * 100 / expected
    expected_cost = expected * target["occupied_room_nights"]
    gap = max(FRACTION_ZERO, target["net_cost"] - expected_cost)
    above, relative = actual > expected, delta_percent >= 20
    on_fence, material = actual >= fence, gap >= 100
    numeric = above and relative and on_fence and material

    sample_score = min(Fraction(100), Fraction(len(used) * 100, 8))
    provenance = sum((m["occupancy_provenance_score"] for m in used), FRACTION_ZERO) / len(used)
    weights = [m["absolute_category_cost"] for m in used]
    confidences = [m["weighted_classification_confidence"] or FRACTION_ZERO for m in used]
    if sum(weights, FRACTION_ZERO) > 0:
        classification = sum((c * w for c, w in zip(confidences, weights)), FRACTION_ZERO) / sum(weights, FRACTION_ZERO)
    else:
        classification = sum(confidences, FRACTION_ZERO) / len(confidences)
    stability = max(FRACTION_ZERO, 100 - 50 * iqr / max(abs(expected), Fraction(1, 100)))
    raw = (Fraction(35, 100) * sample_score + Fraction(25, 100) * provenance
           + Fraction(20, 100) * classification + Fraction(20, 100) * stability)
    baseline = q2(raw)
    caps = []
    if any(m["reconstructed_day_count"] > 0 for m in used):
        caps.append(Fraction(85))
    if not any(m["reconstructed_day_count"] == 0 for m in used):
        caps.append(Fraction(65))
    cap = min(caps) if caps else None
    if cap is not None:
        baseline = min(baseline, cap)
    quality = q2(Fraction(1, 2) * target["occupancy_provenance_score"]
                 + Fraction(1, 2) * target["weighted_classification_confidence"])
    confidence = min(baseline, quality)
    body.update(
        delta_cpor=frac_text(delta), delta_percent=frac_text(delta_percent),
        expected_cost_for_target_volume=frac_text(expected_cost), cost_gap_proxy=frac_text(gap),
        above_expected_condition=above, relative_condition=relative,
        upper_fence_condition=on_fence, gap_condition=material,
        baseline_confidence=frac_text(baseline), sample_score=frac_text(sample_score),
        provenance_score=frac_text(provenance), classification_score=frac_text(classification),
        stability_score=frac_text(stability), confidence_cap=frac_text(cap),
        target_quality=frac_text(quality), confidence_score=frac_text(confidence),
    )
    if numeric and confidence >= 55:
        return done("TRIGGERED", ["TRIGGER_CPOR_ANOMALY"])
    if numeric:
        return done("SUPPRESSED_LOW_CONFIDENCE", ["LOW_CONFIDENCE"])
    return done("CLEAR", ["CLEAR_WITHIN_EXPECTED_RANGE"])


# The cases of the specification (A-O) and two more that pin down the "no cost" answers.
CASES = [
    ("A", "2026-08", "LAUNDRY", "EUR", "TRIGGERED"),
    ("B", "2026-07", "LAUNDRY", "EUR", "CLEAR"),
    ("C", "2026-08", "UTILITIES", "EUR", "CLEAR"),
    ("D", "2026-08", "SOFTWARE", "EUR", "CLEAR"),
    ("E", "2026-08", "CLEANING", "EUR", "SUPPRESSED_LOW_CONFIDENCE"),
    ("F", "2026-08", "MAINTENANCE", "EUR", "INSUFFICIENT_DATA"),
    ("G", "2026-06", "LAUNDRY", "EUR", "INSUFFICIENT_DATA"),
    ("H", "2026-08", "OTHER", "EUR", "NOT_APPLICABLE"),
    ("I", "2026-05", "LAUNDRY", "EUR", "INSUFFICIENT_DATA"),
    ("J", "2026-10", "LAUNDRY", "EUR", "NOT_APPLICABLE"),
    ("K", "2026-08", "OTA_COMMISSIONS", "EUR", "NOT_APPLICABLE"),
    ("O", "2026-08", "LAUNDRY", "USD", "INSUFFICIENT_DATA"),
    ("P", "2026-08", "TRANSPORT", "EUR", "NOT_APPLICABLE"),
    ("Q", "2026-09", "LAUNDRY", "EUR", "NOT_APPLICABLE"),
]


# --- the files -------------------------------------------------------------------------------------


def booking_rows() -> list[list[str]]:
    header = ["Codice Prenotazione", "Data Prenotazione", "Arrivo", "Partenza", "Stato", "Camere",
              "Ospiti", "Importo Camera", "Importo Totale", "Canale", "Commissione",
              "Tipologia Camera", "Data Cancellazione", "Ospite", "Telefono"]
    rows = [header]
    number = 0
    for month, (base, _kind) in MONTHS.items():
        for day in month_days(month):
            rooms = rooms_on(day, base)
            if rooms == 0:
                continue
            number += 1
            made = day - timedelta(days=10)
            amount = inv.it_number(F(rooms * 100))
            rows.append([
                f"CI-{number:04d}", f"{made:%d/%m/%Y} 09:30", f"{day:%d/%m/%Y}",
                f"{day + timedelta(days=1):%d/%m/%Y}", "Confermato", str(rooms), str(rooms * 2),
                amount, amount, "Booking.com", "", "Camera Doppia", "",
                f"Ospite Costi {number:04d}", f"+39 000 7{number:06d}",
            ])
            if month in UNCERTAIN_DAYS and day.day in UNCERTAIN_DAYS[month]:
                number += 1  # a booking cancelled WITHOUT a cancellation date: uncertain rooms
                rows.append([
                    f"CI-{number:04d}", f"{made:%d/%m/%Y} 10:30", f"{day:%d/%m/%Y}",
                    f"{day + timedelta(days=1):%d/%m/%Y}", "Annullato", "1", "2", "100,00",
                    "100,00", "Booking.com", "", "Camera Doppia", "",
                    f"Ospite Costi {number:04d}", f"+39 000 7{number:06d}",
                ])
    return rows


SUPPLIERS = {
    "LAV": {"name": "Lavanderia Salentina S.r.l.", "vat": "03111111111"},
    "ENE": {"name": "Energia Puglia S.p.A.", "vat": "03222222222"},
    "PUL": {"name": "Pulizie Masseria S.r.l.", "vat": "03333333333"},
    "MAN": {"name": "Manutenzioni Murgia S.n.c.", "vat": "03444444444"},
    "OTA": {"name": "Booking Servizi S.r.l.", "vat": "03555555555"},
    "VAR": {"name": "Fornitore Vario S.r.l.", "vat": "03666666666"},
    "SOF": {"name": "Software Salento S.r.l.", "vat": "03777777777"},
}
XML_FILES = {  # file name -> (supplier, currency)
    "lavanderia_eur.xml": ("LAV", "EUR"),
    "lavanderia_usd.xml": ("LAV", "USD"),
    "energia.xml": ("ENE", "EUR"),
    "pulizie.xml": ("PUL", "EUR"),
    "manutenzione.xml": ("MAN", "EUR"),
    "commissioni.xml": ("OTA", "EUR"),
    "vari.xml": ("VAR", "EUR"),
}


def xml_file(supplier: str, currency: str) -> str:
    bodies = []
    for doc in DOCS:
        if doc.supplier != supplier or doc.currency != currency:
            continue
        bodies.append({
            "type": "TD04" if doc.kind == "CREDIT_NOTE" else "TD01",
            "date": doc.day.isoformat(),
            "number": doc.number,
            "currency": currency,
            "gross": False,
            "lines": [
                (n, description, None, None, None, amount, "22.00")
                for n, (description, amount, _conf) in enumerate(doc.lines, start=1)
            ],
        })
    return inv.fattura({"name": SUPPLIERS[supplier]["name"], "vat": SUPPLIERS[supplier]["vat"]}, bodies)


def software_csv() -> str:
    rows = [["Fornitore", "P.IVA", "Numero Fattura", "Data", "Descrizione", "Importo", "Categoria"]]
    for doc in DOCS:
        if doc.supplier != "SOF":
            continue
        for description, amount, _conf in doc.lines:
            rows.append([SUPPLIERS["SOF"]["name"], SUPPLIERS["SOF"]["vat"], doc.number,
                         f"{doc.day:%d/%m/%Y}", description, inv.it_number(amount), "Software"])
    return inv.csv_text(rows, ";")


def build() -> dict:
    build_docs()
    index = cost_index()
    occupancy_of_months = {}
    for month in MONTHS:
        occ = occupancy(month)
        occupancy_of_months[month] = {
            "kind": MONTHS[month][1],
            "days": occ["days"],
            "observed_days": occ["observed"],
            "reconstructed_days": occ["reconstructed"],
            "missing_days": occ["missing"],
            "uncertain_days": occ["uncertain"],
            "occupied_room_nights": occ["room_nights"],
            "provenance": frac_text(occ["provenance"]),
        }
    cases = {}
    for name, month, category, currency, status in CASES:
        evaluation = evaluate(month, category, currency, index)
        assert evaluation["status"] == status, (name, evaluation["status"], evaluation["reason_codes"])
        cases[name] = {"month": month, "category": category, "currency": currency,
                       "evaluation": evaluation}
    return {
        "world": "MASSERIA NINFA DEMO — COST DATA V1 (cost intelligence)",
        "note": "Computed independently of the application (see the generator's docstring).",
        "rules_version": RULES_VERSION,
        "metric_version": METRIC_VERSION,
        "expected_method": EXPECTED_METHOD,
        "reconstruction_clock": "2026-11-20T12:00:00+00:00",
        "observation_clock_hour_utc": 12,
        "reconstructed_months": [m for m, (_b, k) in MONTHS.items() if k == "R"],
        "observed_months": [m for m, (_b, k) in MONTHS.items() if k == "O"],
        "missing_days": {m: [f"{m}-{d:02d}" for d in days] for m, days in MISSING_DAYS.items()},
        "months": occupancy_of_months,
        "counts": {
            "bookings": len(booking_rows()) - 1,
            "invoice_documents": len(DOCS),
            "invoice_lines": sum(len(d.lines) for d in DOCS),
        },
        "xml_files": {name: {"supplier": s, "currency": c} for name, (s, c) in XML_FILES.items()},
        "cases": cases,
        "evaluate_month_2026_08_eur": {
            "categories": [c for c in cases_of_month(cases, "2026-08", "EUR")],
        },
    }


def cases_of_month(cases: dict, month: str, currency: str) -> list[str]:
    return [c["category"] for c in cases.values() if c["month"] == month and c["currency"] == currency]


def csv_of(rows: list[list[str]]) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, delimiter=";", lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def main() -> None:
    result = build()
    inv.write(BOOKINGS, csv_of(booking_rows()))
    for name, (supplier, currency) in XML_FILES.items():
        inv.write(INVOICE_DIR / name, xml_file(supplier, currency))
    inv.write(INVOICE_DIR / "software.csv", software_csv())
    inv.write(EXPECTED, json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    statuses = {name: case["evaluation"]["status"] for name, case in result["cases"].items()}
    print(f"cases={len(statuses)} docs={result['counts']['invoice_documents']} "
          f"bookings={result['counts']['bookings']}")
    print(statuses)


if __name__ == "__main__":
    main()

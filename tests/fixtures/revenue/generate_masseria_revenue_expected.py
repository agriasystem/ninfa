"""Independent calculation of the Gate 5 golden revenue evaluations ("MASSERIA NINFA DEMO").

Standard library only (csv, fractions, datetime, hashlib, json). It shares NO code with the
application: not the pairing, not the statistics, not the confidence, not the thresholds. Exact
arithmetic (`fractions.Fraction`) is used everywhere, the application uses `Decimal`. It imports
the two earlier golden generators (also standard library only) for what they already own: the
Gate 3 snapshot cell and the Gate 4 calendar / percentile helpers.

It (re)writes, next to itself:

  masseria_ninfa_bookings_revenue_v1.csv       synthetic bookings of the revenue stays (fictional
                                               guests), in their FINAL state
  masseria_ninfa_revenue_v1.expected.json      the snapshots to materialise, the inventory, the
                                               independently computed Expected baselines and the
                                               expected REV_PICKUP_LOW / REV_OCCUPANCY_RISK results

Run it from anywhere:  python generate_masseria_revenue_expected.py

Golden world: the Gate 2/3/4 bookings (golden + addendum + history) plus the bookings written
here. Seven targets, one per weekday of the week of Monday 2026-10-05, each seen 7 days before
(lead 7), each with six same-weekday comparable stay dates in the six weeks before it:

  A  Mon  observed history, dated cancellations; pickup TRIGGERED, occupancy TRIGGERED (gap only,
          exactly on the 10-point boundary), a cancellation-driven negative remaining pickup
  B  Tue  3 observed + 3 reconstructed comparables; pickup CLEAR, occupancy CLEAR
  C  Wed  very dispersed reconstructed history and an empty target: SUPPRESSED_LOW_CONFIDENCE
          for both (the reference ADR is the historical median: the target has no ADR)
  D  Thu  a NO_SHOW makes one final snapshot uncertain: occupancy INSUFFICIENT_DATA; pickup CLEAR
  E  Fri  19 of 20 rooms: pickup NOT_APPLICABLE (near sold out); occupancy CLEAR
  F  Sat  weekly pickups <= 0: pickup NOT_APPLICABLE; occupancy TRIGGERED by the rooms only
  G  Sun  no historical prior snapshots, no inventory: pickup INSUFFICIENT_DATA, occupancy
          NOT_APPLICABLE (inventory unknown); the Sundays of the Gate 4 world (target B of
          Gate 4 was a Sunday seen 7 days before) are extra comparables: the worlds really merge

Stay dates are never shared between families (a snapshot value is a function of the date's
bookings). An OBSERVED snapshot reads the bookings as they are at the observation instant, so the
observed stays are imported day by day (the test harness replays the timeline); a RECONSTRUCTED
one is a function of the final bookings. Both are computed here from the final bookings alone.

Rules re-implemented here from the written specification (docs/architecture/revenue-decisions-v1.md):

* anchors = the Expected comparables (same weekday, same lead time, seasonal window <= 42 days,
  <= 730 days, before the target on stay date and snapshot day, no uncertainty; >= 5 observed ->
  observed only, else observed + clean reconstructed; newest first, at most 24);
* pickup pair   = (the snapshot 7 days before the anchor, the anchor) of the SAME stay date;
  remaining pair = (the anchor, the final snapshot taken ON the stay date) of the SAME stay date;
  an endpoint must be strictly before the target's snapshot day; a pair with an uncertain endpoint
  is dropped; OBSERVED_PAIR only if both are observed; >= 5 observed pairs -> observed only, else
  completed with approximate pairs, newest first, at most 24; fewer than 5 -> insufficient;
* median / P25 / P75 by linear interpolation at (n-1)p, IQR = P75 - P25;
* pattern confidence = 0.40 sample + 0.35 provenance + 0.25 stability with |median| (caps 85 / 65);
  final confidence = min(baseline confidence, pattern confidence);
* REV_PICKUP_LOW: -20 % and 2 rooms, confidence >= 50; REV_OCCUPANCY_RISK: 10 points or 3 rooms,
  confidence >= 55; near sold out / closed / inventory rules as documented;
* thresholds are compared on the EXACT fractions (a pickup of -19.995 % is displayed as -20.00
  but is not -20 % or worse); the two-decimal figures written to the file are display only, and
  the decision values are written next to them as exact fractions (`*_exact`).
"""

import csv
import hashlib
import importlib.util
import json
import math
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent
BOOKING_FILES = [
    FIXTURES / "bookings" / "masseria_ninfa_bookings_v1.csv",
    FIXTURES / "snapshots" / "masseria_ninfa_bookings_addendum_v1.csv",
    FIXTURES / "expected" / "masseria_ninfa_bookings_history_v1.csv",
    HERE / "masseria_ninfa_bookings_revenue_v1.csv",
]
REVENUE_CSV = HERE / "masseria_ninfa_bookings_revenue_v1.csv"
OUTPUT = HERE / "masseria_ninfa_revenue_v1.expected.json"


def _load(name: str, path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate3 = _load("gate3_generator", FIXTURES / "snapshots" / "generate_masseria_snapshots_expected.py")
gate4 = _load("gate4_generator", FIXTURES / "expected" / "generate_masseria_expected_expected.py")

RECONSTRUCTION_CLOCK = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
OBSERVATION_CLOCK_HOUR = 21  # UTC: after every booking (10:00) and cancellation (15:00) of the day
LEAD = 7
MIN_PAIRS, MAX_PAIRS, MIN_SAMPLE, MAX_SAMPLE = 5, 24, 5, 24

TARGETS = {  # name: (stay date, rooms available or None)
    "A": (date(2026, 10, 5), 20),
    "B": (date(2026, 10, 6), 24),
    "C": (date(2026, 10, 7), 20),
    "D": (date(2026, 10, 8), 20),
    "E": (date(2026, 10, 9), 20),
    "F": (date(2026, 10, 10), 60),
    "G": (date(2026, 10, 11), None),
}
NOTES = {
    "A": "observed history; pickup TRIGGERED; occupancy TRIGGERED by the 10-point gap alone "
    "(exactly on the boundary); one comparable lost rooms after the anchor",
    "B": "3 observed + 3 reconstructed comparables: mixed provenance; pickup and occupancy CLEAR",
    "C": "very dispersed reconstructed history, empty target: both SUPPRESSED_LOW_CONFIDENCE",
    "D": "a NO_SHOW makes one final snapshot uncertain: occupancy INSUFFICIENT_DATA",
    "E": "19 rooms of 20: pickup NOT_APPLICABLE near sold out; occupancy CLEAR",
    "F": "history that loses rooms in the week: pickup NOT_APPLICABLE; occupancy by rooms alone",
    "G": "no historical prior snapshot, no inventory: pickup INSUFFICIENT_DATA, occupancy N/A "
    "(its 6 comparables are joined by 4 Sundays of the Gate 4 world)",
}
# Which comparables (j = 1 the week before the target ... 6) are OBSERVED (the rest reconstructed).
OBSERVED_COMPARABLES = {
    "A": (1, 2, 3, 4, 5, 6),
    "B": (1, 2, 3),
    "F": (1, 2, 3),
}
# Comparables whose PRIOR snapshot (14 days before the stay) is not materialised at all.
NO_PRIOR = {"G": (1, 2, 3, 4, 5, 6)}

# Per stay: (rooms on the books 14 days before, rooms made in the week after, rooms cancelled in
# that week, rooms made in the last week, rooms cancelled in the last week).
TARGET_CURVE = {
    "A": (8, 7, 0),
    "B": (9, 9, 0),
    "C": (0, 0, 0),
    "D": (8, 8, 0),
    "E": (12, 7, 0),
    "F": (21, 0, 1),
    "G": (8, 8, 0),
}
CURVES = {
    "A": [(8, 10, 0, 12, 0), (7, 10, 0, 2, 0), (7, 11, 0, 1, 0), (6, 9, 0, 1, 3), (7, 10, 0, 2, 0), (8, 10, 0, 3, 0)],
    "B": [(9, 9, 0, 3, 0), (8, 10, 0, 3, 0), (9, 8, 0, 4, 0), (9, 9, 0, 3, 0), (8, 10, 0, 2, 0), (9, 9, 0, 3, 0)],
    "C": [(1, 1, 0, 0, 0), (2, 16, 0, 3, 0), (1, 3, 0, 0, 1), (2, 16, 0, 5, 0), (1, 2, 0, 2, 0), (2, 20, 0, 4, 0)],
    "D": [(8, 8, 0, 3, 0), (8, 9, 0, 2, 0), (8, 8, 0, 2, 0), (8, 8, 0, 3, 0), (9, 7, 0, 2, 0), (7, 9, 0, 3, 0)],
    "E": [(12, 7, 0, 1, 0), (11, 8, 0, 1, 0), (11, 7, 0, 1, 0), (12, 7, 0, 1, 0), (12, 7, 0, 1, 0), (12, 7, 0, 2, 0)],
    "F": [(23, 0, 1, 18, 0), (23, 0, 0, 8, 0), (24, 0, 2, 8, 0), (23, 0, 1, 9, 0), (25, 0, 0, 7, 0), (25, 0, 2, 8, 0)],
    "G": [(8, 8, 0, 3, 0)] * 6,
}
D_NO_SHOW_COMPARABLE = 3  # D's third comparable has one extra room that never showed up
RATES = {"base": 120, "week1": 140, "week2": 130}  # per room and night, in euros

# Decoys: stay dates that carry a curve but must never be used by any target.
OUT_OF_SEASON_MONDAY = date(2026, 2, 2)  # same weekday and lead, 245 days from the season
FUTURE_MONDAY = date(2026, 10, 12)  # the week AFTER target A
WRONG_LEADS = (6, 8)  # extra snapshots of A's second comparable at lead 6 and 8


def comparable_stay(name: str, j: int) -> date:
    return TARGETS[name][0] - timedelta(days=7 * j)


# ---------------------------------------------------------------------------------------------
# bookings
# ---------------------------------------------------------------------------------------------


def build_bookings() -> list[dict]:
    """Final-state bookings of every revenue stay (one night each)."""
    bookings: list[dict] = []

    def add(stay, rooms, days_before, rate, *, status="Confermato", cancelled_before=None):
        bookings.append(
            {
                "stay": stay,
                "rooms": rooms,
                "booked_at": datetime.combine(stay - timedelta(days=days_before), datetime.min.time()).replace(hour=10),
                "cancelled_at": None
                if cancelled_before is None
                else datetime.combine(stay - timedelta(days=cancelled_before), datetime.min.time()).replace(hour=15),
                "status": status,
                "price": rooms * rate,
            }
        )

    def stay_curve(stay, r14, w1, c1, w2, c2):
        kept = r14 - c1 - c2
        assert kept >= 0
        if kept:
            add(stay, kept, 20, RATES["base"])
        if c1:
            add(stay, c1, 20, RATES["base"], status="Annullato", cancelled_before=10)
        if c2:
            add(stay, c2, 20, RATES["base"], status="Annullato", cancelled_before=3)
        if w1:
            add(stay, w1, 10, RATES["week1"])
        if w2:
            add(stay, w2, 3, RATES["week2"])

    for name, (stay, _capacity) in TARGETS.items():
        r14, w1, c1 = TARGET_CURVE[name]
        stay_curve(stay, r14, w1, c1, 0, 0)
        for j, curve in enumerate(CURVES[name], start=1):
            comparable = comparable_stay(name, j)
            stay_curve(comparable, *curve)
            if name == "D" and j == D_NO_SHOW_COMPARABLE:
                add(comparable, 1, 20, RATES["base"], status="No-Show")
    add(OUT_OF_SEASON_MONDAY, 30, 60, RATES["base"])
    add(FUTURE_MONDAY, 25, 60, RATES["base"])
    bookings.sort(key=lambda b: (b["stay"], b["booked_at"], b["rooms"]))
    for number, booking in enumerate(bookings, start=1):
        booking["id"] = f"RV-{number:04d}"
        booking["number"] = number
    return bookings


def write_bookings(bookings: list[dict]) -> None:
    header = [
        "Codice Prenotazione", "Data Prenotazione", "Arrivo", "Partenza", "Stato", "Camere",
        "Ospiti", "Importo Camera", "Importo Totale", "Canale", "Commissione", "Tipologia Camera",
        "Data Cancellazione", "Ospite", "Telefono",
    ]
    lines = [";".join(header)]
    for b in bookings:
        amount = f"{b['price']},00"
        lines.append(
            ";".join(
                [
                    b["id"],
                    b["booked_at"].strftime("%d/%m/%Y %H:%M"),
                    b["stay"].strftime("%d/%m/%Y"),
                    (b["stay"] + timedelta(days=1)).strftime("%d/%m/%Y"),
                    b["status"],
                    str(b["rooms"]),
                    str(2 * b["rooms"]),
                    amount,
                    amount,
                    ("Diretto", "Booking.com", "Airbnb")[b["number"] % 3],
                    "",
                    "Camera Doppia",
                    "" if b["cancelled_at"] is None else b["cancelled_at"].strftime("%d/%m/%Y %H:%M"),
                    f"Ospite Ricavi {b['number']:04d}",
                    f"+39 000 {8000000 + b['number']:07d}",
                ]
            )
        )
    with REVENUE_CSV.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------------------------
# the snapshots to materialise
# ---------------------------------------------------------------------------------------------


def build_specs() -> tuple[dict[tuple[date, date], str], list[date]]:
    """{(snapshot day, stay date): OBSERVED | RECONSTRUCTED} and the observed stay dates."""
    specs: dict[tuple[date, date], str] = {}
    observed_stays: list[date] = []

    def spec(snapshot_day: date, stay: date, kind: str) -> None:
        assert (snapshot_day, stay) not in specs
        specs[(snapshot_day, stay)] = kind

    for name, (stay, _capacity) in TARGETS.items():
        observed_stays.append(stay)
        spec(stay - timedelta(days=LEAD + 7), stay, "OBSERVED")  # the target's own prior
        spec(stay - timedelta(days=LEAD), stay, "OBSERVED")  # the target
        for j in range(1, 7):
            comparable = comparable_stay(name, j)
            kind = "OBSERVED" if j in OBSERVED_COMPARABLES.get(name, ()) else "RECONSTRUCTED"
            if kind == "OBSERVED":
                observed_stays.append(comparable)
            spec(comparable - timedelta(days=LEAD), comparable, kind)  # the anchor
            spec(comparable, comparable, kind)  # the final snapshot (lead time 0)
            if j not in NO_PRIOR.get(name, ()):
                spec(comparable - timedelta(days=LEAD + 7), comparable, kind)  # the anchor's prior
    # decoys
    spec(OUT_OF_SEASON_MONDAY - timedelta(days=LEAD), OUT_OF_SEASON_MONDAY, "RECONSTRUCTED")
    spec(OUT_OF_SEASON_MONDAY - timedelta(days=LEAD + 7), OUT_OF_SEASON_MONDAY, "RECONSTRUCTED")
    spec(OUT_OF_SEASON_MONDAY, OUT_OF_SEASON_MONDAY, "RECONSTRUCTED")
    spec(FUTURE_MONDAY - timedelta(days=LEAD), FUTURE_MONDAY, "RECONSTRUCTED")
    second = comparable_stay("A", 2)
    for wrong in WRONG_LEADS:
        spec(second - timedelta(days=wrong), second, "RECONSTRUCTED")
    return specs, sorted(set(observed_stays))


# ---------------------------------------------------------------------------------------------
# snapshot values (independent: the Gate 3 brute-force cell, plus an as-of view for observations)
# ---------------------------------------------------------------------------------------------


def read_all_bookings() -> list[dict]:
    rows = []
    for path in BOOKING_FILES:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                rows.append(
                    {
                        "id": row["Codice Prenotazione"],
                        "booked_at": gate3.local_to_utc(row["Data Prenotazione"]),
                        "check_in": gate3.parse_date(row["Arrivo"]),
                        "check_out": gate3.parse_date(row["Partenza"]),
                        "status": gate3.STATUSES[row["Stato"].strip().lower()],
                        "rooms": int(row["Camere"]),
                        "cents": gate3.money_to_cents(row["Importo Camera"]),
                        "cancelled_at": (
                            gate3.local_to_utc(row["Data Cancellazione"]) if row["Data Cancellazione"] else None
                        ),
                    }
                )
    return rows


def as_of(bookings: list[dict], day: date) -> list[dict]:
    """The bookings as the application knew them at the end of the local day `day`: made by then,
    and still CANCELLED only if the cancellation had already happened."""
    view = []
    for b in bookings:
        if b["booked_at"] >= gate3.cutoff_of(day):
            continue
        copy = dict(b)
        if b["status"] == "CANCELLED" and b["cancelled_at"] is not None and b["cancelled_at"] >= gate3.cutoff_of(day):
            copy["status"] = "CONFIRMED"
            copy["cancelled_at"] = None
        view.append(copy)
    return view


def snapshot_cell(kind: str, snapshot_day: date, stay: date, bookings: list[dict]) -> dict:
    if kind == "OBSERVED":
        return gate3.cell(snapshot_day, stay, True, as_of(bookings, snapshot_day))
    return gate3.cell(snapshot_day, stay, False, bookings)


# ---------------------------------------------------------------------------------------------
# arithmetic helpers (exact)
# ---------------------------------------------------------------------------------------------


def half_up(value: Fraction, places: int = 2) -> Fraction:
    """Round half AWAY from zero to `places` decimals (the application's ROUND_HALF_UP)."""
    scale = 10**places
    scaled = abs(value) * scale
    rounded = math.floor(scaled + Fraction(1, 2))
    return Fraction(rounded if value >= 0 else -rounded, scale)


def text(value: Fraction | None) -> str | None:
    if value is None:
        return None
    cents = half_up(value) * 100
    assert cents.denominator == 1
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def median_of(values: list[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def percentile(values: list[Fraction], p: Fraction) -> Fraction:
    ordered = sorted(values)
    at = (len(ordered) - 1) * p
    low = math.floor(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (at - low) * (ordered[high] - ordered[low])


def summarise(values: list[int]) -> dict:
    sample = [Fraction(v) for v in values]
    median = half_up(median_of(sample))
    lower, upper = half_up(percentile(sample, Fraction(1, 4))), half_up(percentile(sample, Fraction(3, 4)))
    return {"median": median, "p25": lower, "p75": upper, "iqr": upper - lower}


def confidence(observed: int, other: int, iqr: Fraction, median: Fraction) -> dict:
    n = observed + other
    sample = min(Fraction(100), Fraction(n * 100, 12))
    provenance = Fraction(observed * 100 + other * 60, n)
    stability = max(Fraction(0), Fraction(100) - 50 * (iqr / max(abs(median), Fraction(1))))
    raw = Fraction(40, 100) * sample + Fraction(35, 100) * provenance + Fraction(25, 100) * stability
    score = half_up(raw)
    if other > 0:
        score = min(score, Fraction(85))
    if observed == 0:
        score = min(score, Fraction(65))
    return {"score": score, "sample": sample, "provenance": provenance, "stability": stability}


# ---------------------------------------------------------------------------------------------
# the Expected baseline of a target (Gate 4 rules)
# ---------------------------------------------------------------------------------------------


def baseline_of(stay: date, snapshots: dict[tuple[date, date], dict]) -> dict:
    snapshot_day = stay - timedelta(days=LEAD)
    observed, reconstructed, rejected = [], [], 0
    for (snap, day), row in snapshots.items():
        if not (day < stay and snap < snapshot_day and (day - snap).days == LEAD):
            continue
        if not ((stay - day).days <= gate4.HORIZON and day.weekday() == stay.weekday()):
            continue
        if gate4.season_distance(day, stay) > gate4.WINDOW:
            continue
        if row["uncertain_rooms"] > 0:
            rejected += 1
        elif row["origin"] == "OBSERVED":
            observed.append((day, snap, row))
        else:
            reconstructed.append((day, snap, row))
    observed.sort(key=lambda item: item[0], reverse=True)
    reconstructed.sort(key=lambda item: item[0], reverse=True)
    chosen = observed[:MAX_SAMPLE] if len(observed) >= MIN_SAMPLE else observed + reconstructed[: MAX_SAMPLE - len(observed)]
    chosen.sort(key=lambda item: item[0], reverse=True)
    n_obs = sum(1 for _, _, row in chosen if row["origin"] == "OBSERVED")
    result = {
        "sample_size": len(chosen),
        "observed_sample_size": n_obs,
        "reconstructed_sample_size": len(chosen) - n_obs,
        "rejected_uncertain_count": rejected,
        "anchors": [(day, snap, row) for day, snap, row in chosen],
        "comparables": [
            {
                "rank": rank,
                "stay_date": day.isoformat(),
                "snapshot_date": snap.isoformat(),
                "origin": row["origin"],
                "rooms_on_books": row["rooms_on_books"],
            }
            for rank, (day, snap, row) in enumerate(chosen, start=1)
        ],
    }
    if len(chosen) < MIN_SAMPLE:
        return result | {"status": "INSUFFICIENT_DATA", "confidence": Fraction(0)}
    stats = summarise([row["rooms_on_books"] for _, _, row in chosen])
    score = confidence(n_obs, len(chosen) - n_obs, stats["iqr"], stats["median"])["score"]
    return result | {
        "status": "READY",
        "expected": stats["median"],
        "lower": stats["p25"],
        "upper": stats["p75"],
        "iqr": stats["iqr"],
        "confidence": score,
    }


# ---------------------------------------------------------------------------------------------
# curve pairs and the two detectors
# ---------------------------------------------------------------------------------------------


def curve_pairs(target_day: date, anchors: list, snapshots: dict, kind: str) -> dict:
    observed, approximate, uncertain, missing, future = [], [], 0, 0, 0
    for day, snap, row in anchors:
        other_key = (snap - timedelta(days=7), day) if kind == "pickup" else (day, day)
        other = snapshots.get(other_key)
        if other is None:
            missing += 1
            continue
        if not (snap < target_day and other_key[0] < target_day):
            future += 1
            continue
        if row["uncertain_rooms"] > 0 or other["uncertain_rooms"] > 0:
            uncertain += 1
            continue
        delta = row["rooms_on_books"] - other["rooms_on_books"] if kind == "pickup" else other["rooms_on_books"] - row["rooms_on_books"]
        pair = {
            "stay_date": day,
            "delta": delta,
            "anchor_rooms": row["rooms_on_books"],
            "other_rooms": other["rooms_on_books"],
            "observed": row["origin"] == "OBSERVED" and other["origin"] == "OBSERVED",
        }
        (observed if pair["observed"] else approximate).append(pair)
    observed.sort(key=lambda p: p["stay_date"], reverse=True)
    approximate.sort(key=lambda p: p["stay_date"], reverse=True)
    chosen = observed[:MAX_PAIRS] if len(observed) >= MIN_PAIRS else observed + approximate[: MAX_PAIRS - len(observed)]
    chosen.sort(key=lambda p: p["stay_date"], reverse=True)
    n_obs = sum(1 for p in chosen if p["observed"])
    return {
        "pairs": chosen,
        "observed": n_obs,
        "approximate": len(chosen) - n_obs,
        "rejected_uncertain": uncertain,
        "missing_endpoint": missing,
        "excluded_future": future,
    }


def pattern_of(selection: dict) -> dict:
    facts = {
        "pair_count": len(selection["pairs"]),
        "observed_pair_count": selection["observed"],
        "approximate_pair_count": selection["approximate"],
        "rejected_uncertain_count": selection["rejected_uncertain"],
        "missing_endpoint_count": selection["missing_endpoint"],
        "excluded_future_count": selection["excluded_future"],
    }
    if len(selection["pairs"]) < MIN_PAIRS:
        return facts | {"median": None}
    stats = summarise([p["delta"] for p in selection["pairs"]])
    conf = confidence(selection["observed"], selection["approximate"], stats["iqr"], stats["median"])
    return facts | {
        "median": stats["median"],
        "p25": stats["p25"],
        "p75": stats["p75"],
        "iqr": stats["iqr"],
        "pattern_confidence": conf["score"],
        "stay_dates": [p["stay_date"].isoformat() for p in selection["pairs"]],
    }


def reference_adr(target_row: dict, anchors: list) -> tuple[Fraction | None, str]:
    adr = target_row["adr_on_books"]
    if adr is not None and Fraction(adr) > 0:
        return Fraction(adr), "CURRENT_ON_BOOKS_ADR"
    usable = [Fraction(row["adr_on_books"]) for _, _, row in anchors if row["adr_on_books"] is not None and Fraction(row["adr_on_books"]) > 0]
    if usable:
        return half_up(median_of(usable)), "HISTORICAL_COMPARABLE_MEDIAN_ADR"
    return None, "UNAVAILABLE"


def evaluate(name: str, snapshots: dict) -> dict:
    stay, capacity = TARGETS[name]
    snapshot_day = stay - timedelta(days=LEAD)
    target = snapshots[(snapshot_day, stay)]
    prior = snapshots[(snapshot_day - timedelta(days=7), stay)]
    baseline = baseline_of(stay, snapshots)
    rooms = target["rooms_on_books"]
    adr, adr_source = reference_adr(target, baseline["anchors"])
    ready = baseline["status"] == "READY"
    pickup_pairs = curve_pairs(snapshot_day, baseline["anchors"], snapshots, "pickup") if ready else None
    remaining_pairs = curve_pairs(snapshot_day, baseline["anchors"], snapshots, "remaining") if ready else None
    return {
        "baseline": baseline,
        "reference_adr": adr,
        "reference_adr_source": adr_source,
        "pickup": pickup_of(rooms, capacity, prior, baseline, pickup_pairs, adr),
        "occupancy": occupancy_of(rooms, capacity, baseline, remaining_pairs, adr),
        "target_adr": target["adr_on_books"],
        "target_rooms": rooms,
        "prior_rooms": prior["rooms_on_books"],
    }


def pickup_of(rooms, capacity, prior, baseline, pairs, adr) -> dict:
    out = {"decision_type": "REV_PICKUP_LOW", "confidence": Fraction(0), "proxy": None}

    def done(status, reasons, **extra):
        return out | {"status": status, "reasons": reasons} | extra

    remaining = None if capacity is None else capacity - rooms
    out["remaining_capacity"] = remaining
    if capacity == 0:
        return done("NOT_APPLICABLE", ["PROPERTY_CLOSED_FOR_STAY_DATE"])
    if remaining is not None and remaining <= 1:
        return done("NOT_APPLICABLE", ["PICKUP_NEAR_SOLD_OUT"])
    if baseline["status"] != "READY":
        return done("INSUFFICIENT_DATA", ["EXPECTED_BASELINE_INSUFFICIENT"])
    if prior["origin"] != "OBSERVED":
        return done("INSUFFICIENT_DATA", ["PICKUP_PRIOR_OBSERVATION_MISSING"])
    pattern = pattern_of(pairs)
    if pattern["pair_count"] < MIN_PAIRS:
        return done("INSUFFICIENT_DATA", ["PAIR_SAMPLE_INSUFFICIENT"], pattern=pattern)
    final = min(baseline["confidence"], pattern["pattern_confidence"])
    actual = rooms - prior["rooms_on_books"]
    expected = pattern["median"]
    delta_rooms = actual - expected
    missing = max(Fraction(0), expected - actual)
    facts = {
        "actual_pickup": actual,
        "expected_pickup": expected,
        "delta_rooms": delta_rooms,
        "missing_rooms": missing,
        "pattern": pattern,
        "confidence": final,
    }
    if expected <= 0:
        return done("NOT_APPLICABLE", ["PICKUP_EXPECTATION_NON_POSITIVE"], **facts)
    # the DECISION value is the exact fraction; the displayed one is rounded AFTER the comparison
    delta_percent_exact = delta_rooms / expected * 100
    facts["delta_percent"] = half_up(delta_percent_exact)
    facts["delta_percent_exact"] = delta_percent_exact
    numeric = delta_percent_exact <= -20 and missing >= 2
    if not numeric:
        return done("CLEAR", ["CLEAR_WITHIN_EXPECTED_RANGE"], **facts)
    facts["proxy"] = None if adr is None else half_up(missing * adr)
    if final < 50:
        return done("SUPPRESSED_LOW_CONFIDENCE", ["LOW_CONFIDENCE"], **facts)
    return done("TRIGGERED", ["TRIGGER_PICKUP_SHORTFALL"], **facts)


def occupancy_of(rooms, capacity, baseline, pairs, adr) -> dict:
    out = {"decision_type": "REV_OCCUPANCY_RISK", "confidence": Fraction(0), "proxy": None}

    def done(status, reasons, **extra):
        return out | {"status": status, "reasons": reasons} | extra

    if capacity is None:
        return done("NOT_APPLICABLE", ["OCCUPANCY_INVENTORY_UNKNOWN"])
    if capacity == 0:
        return done("NOT_APPLICABLE", ["PROPERTY_CLOSED_FOR_STAY_DATE"])
    if rooms >= capacity:
        return done("NOT_APPLICABLE", ["OCCUPANCY_ALREADY_SOLD_OUT"])
    if baseline["status"] != "READY":
        return done("INSUFFICIENT_DATA", ["EXPECTED_BASELINE_INSUFFICIENT"])
    pattern = pattern_of(pairs)
    if pattern["pair_count"] < MIN_PAIRS:
        return done("INSUFFICIENT_DATA", ["PAIR_SAMPLE_INSUFFICIENT"], pattern=pattern)
    final = min(baseline["confidence"], pattern["pattern_confidence"])
    remaining_median = pattern["median"]
    raw = rooms + remaining_median
    forecast = max(Fraction(0), raw)
    expected_final = half_up(median_of([Fraction(p["other_rooms"]) for p in pairs["pairs"]]))
    forecast_occ_exact = forecast * 100 / capacity
    final_occ_exact = expected_final * 100 / capacity
    shortfall = max(Fraction(0), expected_final - forecast)
    # max(0, final occupancy - forecast occupancy), exact: the same number as shortfall * 100 / capacity
    gap_exact = max(Fraction(0), final_occ_exact - forecast_occ_exact)
    assert gap_exact == shortfall * 100 / capacity
    facts = {
        "expected_remaining_net_pickup": remaining_median,
        "raw_forecast_rooms": raw,
        "forecast_rooms": forecast,
        "expected_final_rooms": expected_final,
        "forecast_occupancy": half_up(forecast_occ_exact),
        "forecast_occupancy_exact": forecast_occ_exact,
        "expected_final_occupancy": half_up(final_occ_exact),
        "expected_final_occupancy_exact": final_occ_exact,
        "occupancy_gap_pp": half_up(gap_exact),
        "occupancy_gap_pp_exact": gap_exact,
        "room_shortfall": shortfall,
        "pattern": pattern,
        "confidence": final,
    }
    by_gap, by_rooms = gap_exact >= 10, shortfall >= 3
    if not (by_gap or by_rooms):
        return done("CLEAR", ["CLEAR_WITHIN_EXPECTED_RANGE"], **facts)
    facts["proxy"] = None if adr is None else half_up(shortfall * adr)
    if final < 55:
        return done("SUPPRESSED_LOW_CONFIDENCE", ["LOW_CONFIDENCE"], **facts)
    reason = (
        "TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL" if by_gap and by_rooms
        else "TRIGGER_OCCUPANCY_GAP" if by_gap else "TRIGGER_ROOM_SHORTFALL"
    )
    return done("TRIGGERED", [reason], **facts)


# ---------------------------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------------------------


def jsonable(value):  # type: ignore[no-untyped-def]
    if isinstance(value, Fraction):
        return text(value)
    if isinstance(value, dict):
        # a decision value is written as the exact fraction "numerator/denominator" (a repeating
        # decimal has no finite text); everything else as the two-decimal figure
        return {
            k: (
                f"{v.numerator}/{v.denominator}"
                if k.endswith("_exact") and isinstance(v, Fraction)
                else jsonable(v)
            )
            for k, v in value.items()
            if k not in ("anchors",)
        }
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def main() -> None:
    bookings = build_bookings()
    write_bookings(bookings)
    specs, observed_stays = build_specs()
    all_bookings = read_all_bookings()

    snapshots: dict[tuple[date, date], dict] = {}
    for (snapshot_day, stay), kind in sorted(specs.items()):
        cell = snapshot_cell(kind, snapshot_day, stay, all_bookings)
        snapshots[(snapshot_day, stay)] = cell | {"origin": "OBSERVED" if kind == "OBSERVED" else "RECONSTRUCTED_APPROXIMATE"}
    grid = sorted(
        f"{snap}|{day}|{row['origin']}|{row['rooms_on_books']}|{row['uncertain_rooms']}"
        for (snap, day), row in snapshots.items()
    )
    # The extended world also holds the snapshots of the Gate 4 world: they are candidates too
    # (a Sunday comparable of Gate 4's target B is a valid comparable of target G).
    world = dict(snapshots)
    _, gate4_specs = gate4.build_plan()
    for spec in gate4_specs:
        observed = spec["kind"] == "OBSERVED"
        cell = gate3.cell(spec["snapshot_date"], spec["stay_date"], observed, all_bookings)
        world.setdefault((spec["snapshot_date"], spec["stay_date"]), cell)
    targets = []
    for name, (stay, capacity) in TARGETS.items():
        result = evaluate(name, world)
        targets.append(
            {
                "name": name,
                "note": NOTES[name],
                "stay_date": stay.isoformat(),
                "snapshot_date": (stay - timedelta(days=LEAD)).isoformat(),
                "lead_time_days": LEAD,
                "rooms_available": capacity,
                **jsonable(result),
            }
        )
    payload = {
        "description": (
            "Golden revenue decision evaluations of MASSERIA NINFA DEMO: the Gate 2/3/4 bookings "
            "plus synthetic revenue bookings (masseria_ninfa_bookings_revenue_v1.csv). Computed "
            "independently of the application code (generate_masseria_revenue_expected.py, "
            "standard library only, exact fractions). BOOKINGS -> SNAPSHOTS -> EXPECTED "
            "BASELINES -> REVENUE EVALUATIONS: nothing else; no decision is stored."
        ),
        "property": {"timezone": "Europe/Rome", "currency": "EUR"},
        "reconstruction_clock": RECONSTRUCTION_CLOCK.isoformat(),
        "observation_clock_hour_utc": OBSERVATION_CLOCK_HOUR,
        "rules_version": "revenue-decisions-v1",
        "pattern_version": "revenue-curve-pattern-v1",
        "inventory": {stay.isoformat(): capacity for _, (stay, capacity) in TARGETS.items() if capacity is not None},
        "observed_stays": [d.isoformat() for d in observed_stays],
        "snapshots": [
            {"kind": kind, "snapshot_date": k[0].isoformat(), "stay_date": k[1].isoformat()}
            for k, kind in sorted(specs.items())
        ],
        "counts": {
            "revenue_bookings": len(bookings),
            "snapshots": len(specs),
            "observed_snapshots": sum(kind == "OBSERVED" for kind in specs.values()),
            "reconstructed_snapshots": sum(kind == "RECONSTRUCTED" for kind in specs.values()),
        },
        "snapshot_grid_sha256": hashlib.sha256("\n".join(grid).encode("ascii")).hexdigest(),
        "targets": targets,
    }
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    print(f"wrote {REVENUE_CSV.name}: {len(bookings)} bookings; {OUTPUT.name}: {len(specs)} snapshots, {len(targets)} targets")
    for t in targets:
        p, o = t["pickup"], t["occupancy"]
        print(t["name"], t["baseline"]["status"], t["baseline"].get("expected"), t["baseline"]["confidence"],
              "| pickup", p["status"], p["reasons"], p.get("actual_pickup"), p.get("expected_pickup"), p.get("delta_percent"), p.get("confidence"), p.get("proxy"),
              "| occ", o["status"], o["reasons"], o.get("forecast_rooms"), o.get("expected_final_rooms"), o.get("room_shortfall"), o.get("occupancy_gap_pp"), o.get("confidence"), o.get("proxy"))


if __name__ == "__main__":
    main()

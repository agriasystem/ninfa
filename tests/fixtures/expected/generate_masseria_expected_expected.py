"""Independent calculation of the Gate 4 golden Expected baselines ("MASSERIA NINFA DEMO").

Standard library only (csv, fractions, zoneinfo, datetime, hashlib, json). It shares NO code
with the application: not the calendar rules, not the statistics, not the confidence formula.
Exact arithmetic (`fractions.Fraction`) is used everywhere, the application uses `Decimal`.

It (re)writes, next to itself:

  masseria_ninfa_bookings_history_v1.csv         synthetic booking history (fictional guests)
  masseria_ninfa_expected_v1.expected.json       the snapshots to materialise, their independently
                                                 computed values and the expected baselines

Run it from anywhere:  python generate_masseria_expected_expected.py

Golden world: the Gate 2/3 bookings (golden + addendum) plus the history written here. NINFA
"started observing" on OBSERVATION_START: snapshots of earlier days can only be RECONSTRUCTED,
the ones from that day on are OBSERVED. Six targets, each on its own weekday so that no stay
date is shared between families (a snapshot value is a function of the date's bookings):

  A  Sat 2026-08-15  lead 14   observed only, low dispersion; distractors of every kind
  B  Sun 2026-08-16  lead  7   observed only, high dispersion
  C  Sat 2026-05-09  lead 14   3 observed + reconstructions, uncertain reconstructions rejected
  D  Tue 2026-07-07  lead 21   INSUFFICIENT_DATA (only 4 comparables exist)
  E  Fri 2026-04-24  lead 10   24 comparables, 12 of them with zero rooms: median 0.50
  F  Thu 2026-05-21  lead 50   reconstructed only (confidence capped at 65)

Rules re-implemented here from the written specification (docs/architecture/expected-engine-v1.md):

* comparable: stay < D, snapshot day < S, (stay - snapshot day) == lead, D - 730 <= stay,
  same weekday, seasonal distance <= 42 (the smaller circular distance of the month/days on a
  365-day and a 366-day calendar; a pair with 29 February only on the 366-day one), and no
  uncertainty;
* >= 5 observed -> observed only; else all observed + clean reconstructed, newest first; at most 24;
* EXPECTED = median, range = P25/P75 (linear interpolation at (n-1)p), IQR = P75 - P25;
* confidence = 0.40 sample + 0.35 provenance + 0.25 stability (half up, 2 dp), caps 85 / 65,
  bands HIGH >= 80, MEDIUM >= 60, else LOW; fewer than 5 comparables -> INSUFFICIENT_DATA.
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
SNAPSHOTS_DIR = HERE.parent / "snapshots"
BOOKING_FILES = [
    HERE.parent / "bookings" / "masseria_ninfa_bookings_v1.csv",
    SNAPSHOTS_DIR / "masseria_ninfa_bookings_addendum_v1.csv",
    HERE / "masseria_ninfa_bookings_history_v1.csv",
]
HISTORY_CSV = HERE / "masseria_ninfa_bookings_history_v1.csv"
OUTPUT = HERE / "masseria_ninfa_expected_v1.expected.json"

# The Gate 3 generator (also standard library only) supplies the independent snapshot cell.
_spec = importlib.util.spec_from_file_location(
    "gate3_generator", SNAPSHOTS_DIR / "generate_masseria_snapshots_expected.py"
)
assert _spec and _spec.loader
gate3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate3)

OBSERVATION_START = date(2026, 4, 1)
RECONSTRUCTION_CLOCK = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
MIN_SAMPLE, MAX_SAMPLE, HORIZON, WINDOW = 5, 24, 730, 42

# ---------------------------------------------------------------------------------------------
# calendar (independent implementation)
# ---------------------------------------------------------------------------------------------

_COMMON_MONTHS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_LEAP_MONTHS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def position(day: date, months: list[int]) -> int:
    """1-based position of the month/day in a year whose month lengths are `months`."""
    return sum(months[: day.month - 1]) + day.day


def circular(a: int, b: int, length: int) -> int:
    gap = abs(a - b)
    return min(gap, length - gap)


def season_distance(a: date, b: date) -> int:
    """Smaller circular distance of the two month/days on a leap and on a common calendar."""
    best = circular(position(a, _LEAP_MONTHS), position(b, _LEAP_MONTHS), 366)
    if (a.month, a.day) != (2, 29) and (b.month, b.day) != (2, 29):
        best = min(best, circular(position(a, _COMMON_MONTHS), position(b, _COMMON_MONTHS), 365))
    return best


def eligible_dates(target: date) -> list[date]:
    found = []
    day = target - timedelta(days=7)
    while (target - day).days <= HORIZON:
        if season_distance(day, target) <= WINDOW:
            found.append(day)
        day -= timedelta(days=7)
    return found  # newest first


# ---------------------------------------------------------------------------------------------
# the world: families of targets, and what is materialised for each
# ---------------------------------------------------------------------------------------------

# main rooms of the history dates, newest comparable first (indexed by position in eligible list)
VALUES = {
    "A": [11, 12, 11, 12, 12, 11, 10, 12, 11, 10, 12, 11, 10, 9, 11, 10, 12, 11, 10, 11, 9, 10, 11, 10],
    "B": [0, 26, 1, 30, 2, 24, 5, 19, 8, 23, 6, 14, 10, 20, 3, 18, 11, 22, 7, 15, 9, 13, 12, 16],
    "C": [6, 7, 5, 6, 8, 5, 7, 6, 6, 8, 5, 7, 6, 5, 7, 6, 8, 5, 6, 7, 6, 5, 7, 6],
    "D": [5, 6, 4, 5, 6, 4, 5, 6, 5, 4, 6, 5, 4, 5, 6, 4, 5, 6, 5, 4, 6, 5, 4, 5],
    "E": [1, 0, 0, 0, 2, 0, 1, 0, 0, 1, 0, 0, 2, 0, 0, 1, 0, 1, 0, 2, 0, 1, 0, 0],
    "F": [7, 6, 8, 7, 6, 8, 7, 6, 7, 8, 6, 7, 8, 6, 7, 7, 8, 6, 7, 8, 6, 7, 8, 7],
}
# rooms booked shortly before arrival (reconstructed-era dates only): they are NOT on the books
# at the target's lead time, so they show the reconstruction dropping late demand
LATE = {"A": 2, "B": 1, "C": 2, "D": 1, "E": 1, "F": 0}
# how many days before arrival the two "main" bookings were made (must be >= the lead time)
BOOKED_DAYS = {"A": (75, 45), "B": (70, 40), "C": (75, 45), "D": (70, 45), "E": (70, 40), "F": (90, 65)}
TARGETS = {  # name: (stay date, lead time)
    "A": (date(2026, 8, 15), 14),
    "B": (date(2026, 8, 16), 7),
    "C": (date(2026, 5, 9), 14),
    "D": (date(2026, 7, 7), 21),
    "E": (date(2026, 4, 24), 10),
    "F": (date(2026, 5, 21), 50),
}
NOTES = {
    "A": "observed only (6 observed comparables, reconstructions ignored), low dispersion",
    "B": "observed only (6 observed comparables), high dispersion: a LOW confidence baseline",
    "C": "3 observed + clean reconstructions; 2 uncertain reconstructions rejected",
    "D": "only 4 comparables exist: INSUFFICIENT_DATA, no number",
    "E": "24 comparables of which 12 have zero rooms (they count): the median is 0.50",
    "F": "reconstructed only: confidence capped at 65",
}
# only the first few comparables of D exist (4 of its 24 eligible dates are materialised)
D_MATERIALISED = 4
# cases of C: (index in the eligible list, kind)
C_UNCERTAIN = (5, 12)  # a CANCELLED booking without a date: reconstructed snapshot is uncertain
C_CANCELLED_EARLY = 9  # cancelled long before the lead time: not on the books at lead 14
C_CANCELLED_LATE = 14  # cancelled after the lead time: still on the books at lead 14


def is_observed(snapshot_day: date) -> bool:
    return snapshot_day >= OBSERVATION_START


def build_plan() -> tuple[list[dict], list[dict]]:
    """(booking rows of the history file, snapshot specs to materialise)."""
    bookings: list[dict] = []
    specs: dict[tuple[date, date], str] = {}
    counter = 0

    def add_booking(stay: date, rooms: int, days_before: int, status: str = "Confermato",
                    cancelled_days_before: int | None = None) -> None:
        nonlocal counter
        counter += 1
        bookings.append(
            {
                "id": f"HS-{counter:04d}",
                "booked_at": datetime.combine(stay - timedelta(days=days_before), datetime.min.time())
                .replace(hour=10),
                "check_in": stay,
                "check_out": stay + timedelta(days=1),
                "status": status,
                "rooms": rooms,
                "price": 120 + 15 * rooms,
                "channel": ("Diretto", "Booking.com", "Airbnb")[counter % 3],
                "cancelled_at": None
                if cancelled_days_before is None
                else datetime.combine(stay - timedelta(days=cancelled_days_before), datetime.min.time())
                .replace(hour=15),
            }
        )

    def spec(snapshot_day: date, stay: date) -> None:
        specs[(snapshot_day, stay)] = "OBSERVED" if is_observed(snapshot_day) else "RECONSTRUCTED"

    for name, (stay, lead) in TARGETS.items():
        pool = eligible_dates(stay)
        used = pool[:D_MATERIALISED] if name == "D" else pool
        for index, day in enumerate(used):
            main = VALUES[name][index % len(VALUES[name])]
            first, second = BOOKED_DAYS[name]
            if main > 0:
                if main <= 3:
                    add_booking(day, main, first)
                else:
                    add_booking(day, main - main // 3, first)
                    add_booking(day, main // 3, second)
            if not is_observed(day - timedelta(days=lead)) and LATE[name] and index % 3 == 0:
                add_booking(day, LATE[name], 6)  # made after the lead time
            if name == "C":
                if index in C_UNCERTAIN:
                    add_booking(day, 2, 60, "Annullato")  # no cancellation date
                if index == C_CANCELLED_EARLY:
                    add_booking(day, 2, 60, "Annullato", cancelled_days_before=40)
                if index == C_CANCELLED_LATE:
                    add_booking(day, 2, 60, "Annullato", cancelled_days_before=5)
            spec(day - timedelta(days=lead), day)
        # the target itself: an OBSERVED snapshot of (S, D), with some bookings of its own
        add_booking(stay, 9, 60)
        specs[(stay - timedelta(days=lead), stay)] = "OBSERVED"

    # --- distractors around A: every reason a snapshot must NOT be used ----------------------------
    a_stay, a_lead = TARGETS["A"]
    a_pool = eligible_dates(a_stay)
    for day in a_pool[:6]:  # right dates, wrong lead times (13 and 15): no interpolation
        for wrong in (13, 15):
            spec(day - timedelta(days=wrong), day)
    for day in (date(2026, 1, 10), date(2026, 2, 14), date(2025, 11, 15), date(2025, 12, 13)):
        add_booking(day, 25, 70)  # same weekday, out of season, a huge value if it were used
        spec(day - timedelta(days=a_lead), day)
    for day in (date(2026, 7, 31), date(2026, 8, 7), date(2026, 7, 24), date(2025, 8, 15),
                date(2025, 8, 8), date(2025, 8, 1)):
        add_booking(day, 22, 70)  # Fridays: same season, wrong weekday
        spec(day - timedelta(days=a_lead), day)
    add_booking(date(2026, 8, 22), 30, 70)  # the FUTURE: a stay date after the target ...
    spec(date(2026, 8, 22) - timedelta(days=a_lead), date(2026, 8, 22))  # ... seen after S
    add_booking(date(2024, 8, 10), 28, 70)  # a Saturday older than the 730-day horizon
    spec(date(2024, 8, 10) - timedelta(days=a_lead), date(2024, 8, 10))
    return bookings, [
        {"kind": kind, "snapshot_date": k[0], "stay_date": k[1]} for k, kind in sorted(specs.items())
    ]


def write_history(bookings: list[dict]) -> None:
    header = [
        "Codice Prenotazione", "Data Prenotazione", "Arrivo", "Partenza", "Stato", "Camere",
        "Ospiti", "Importo Camera", "Importo Totale", "Canale", "Commissione", "Tipologia Camera",
        "Data Cancellazione", "Ospite", "Telefono",
    ]
    lines = [";".join(header)]
    for n, b in enumerate(bookings, start=1):
        amount = f"{b['price']},00"
        lines.append(
            ";".join(
                [
                    b["id"],
                    b["booked_at"].strftime("%d/%m/%Y %H:%M"),
                    b["check_in"].strftime("%d/%m/%Y"),
                    b["check_out"].strftime("%d/%m/%Y"),
                    b["status"],
                    str(b["rooms"]),
                    str(2 * b["rooms"]),
                    amount,
                    amount,
                    b["channel"],
                    "",
                    "Camera Doppia",
                    "" if b["cancelled_at"] is None else b["cancelled_at"].strftime("%d/%m/%Y %H:%M"),
                    f"Ospite Storico {n:04d}",
                    f"+39 000 {9000000 + n:07d}",
                ]
            )
        )
    with HISTORY_CSV.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------------------------
# snapshots (independent: Gate 3 generator's brute-force cell)
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
                            gate3.local_to_utc(row["Data Cancellazione"])
                            if row["Data Cancellazione"]
                            else None
                        ),
                    }
                )
    return rows


# ---------------------------------------------------------------------------------------------
# expected (exact arithmetic)
# ---------------------------------------------------------------------------------------------


def half_up_2dp(value: Fraction) -> str:
    cents = math.floor(value * 100 + Fraction(1, 2))
    return f"{cents // 100}.{cents % 100:02d}"


def percentile(sample: list[int], p: Fraction) -> Fraction:
    ordered = sorted(sample)
    at = (len(ordered) - 1) * p
    low = math.floor(at)
    high = min(low + 1, len(ordered) - 1)
    return Fraction(ordered[low]) + (at - low) * (ordered[high] - ordered[low])


def compute_target(name: str, snapshots: dict[tuple[date, date], dict]) -> dict:
    stay, lead = TARGETS[name]
    snapshot_day = stay - timedelta(days=lead)
    observed, reconstructed, rejected = [], [], 0
    for (snap, day), row in snapshots.items():
        if not (day < stay and snap < snapshot_day and (day - snap).days == lead):
            continue
        if not ((stay - day).days <= HORIZON and day.weekday() == stay.weekday()):
            continue
        if season_distance(day, stay) > WINDOW:
            continue
        if row["uncertain_rooms"] > 0:
            rejected += 1
        elif row["origin"] == "OBSERVED":
            observed.append((day, snap, row))
        else:
            reconstructed.append((day, snap, row))
    observed.sort(key=lambda item: item[0], reverse=True)
    reconstructed.sort(key=lambda item: item[0], reverse=True)
    if len(observed) >= MIN_SAMPLE:
        chosen = observed[:MAX_SAMPLE]
    else:
        chosen = observed + reconstructed[: MAX_SAMPLE - len(observed)]
    chosen.sort(key=lambda item: item[0], reverse=True)
    n_obs = sum(1 for _, _, row in chosen if row["origin"] == "OBSERVED")
    n_rec = len(chosen) - n_obs
    result = {
        "name": name,
        "note": NOTES[name],
        "snapshot_date": snapshot_day.isoformat(),
        "stay_date": stay.isoformat(),
        "lead_time_days": lead,
        "sample_size": len(chosen),
        "observed_sample_size": n_obs,
        "reconstructed_sample_size": n_rec,
        "rejected_uncertain_count": rejected,
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
        result |= {
            "status": "INSUFFICIENT_DATA",
            "expected": None, "lower": None, "upper": None, "iqr": None,
            "confidence_score": "0.00", "confidence_band": None,
        }
        return result
    sample = [row["rooms_on_books"] for _, _, row in chosen]
    ordered = sorted(sample)
    middle = len(ordered) // 2
    median = Fraction(ordered[middle]) if len(ordered) % 2 else Fraction(ordered[middle - 1] + ordered[middle], 2)
    lower, upper = percentile(sample, Fraction(1, 4)), percentile(sample, Fraction(3, 4))
    iqr = upper - lower
    n = len(sample)
    sample_score = min(Fraction(100), Fraction(n * 100, 12))
    provenance = Fraction(n_obs * 100 + n_rec * 60, n)
    stability = max(Fraction(0), Fraction(100) - 50 * (iqr / max(median, Fraction(1))))
    raw = Fraction(40, 100) * sample_score + Fraction(35, 100) * provenance + Fraction(25, 100) * stability
    score = Fraction(half_up_2dp(raw))
    if n_rec > 0:
        score = min(score, Fraction(85))
    if n_obs == 0:
        score = min(score, Fraction(65))
    band = "HIGH" if score >= 80 else "MEDIUM" if score >= 60 else "LOW"
    result |= {
        "status": "READY",
        "expected": half_up_2dp(median),
        "lower": half_up_2dp(lower),
        "upper": half_up_2dp(upper),
        "iqr": half_up_2dp(iqr),
        "confidence_score": half_up_2dp(score),
        "confidence_band": band,
    }
    return result


def main() -> None:
    bookings, specs = build_plan()
    write_history(bookings)
    all_bookings = read_all_bookings()

    snapshots: dict[tuple[date, date], dict] = {}
    for spec in specs:
        observed = spec["kind"] == "OBSERVED"
        cell = gate3.cell(spec["snapshot_date"], spec["stay_date"], observed, all_bookings)
        snapshots[(spec["snapshot_date"], spec["stay_date"])] = {
            "origin": "OBSERVED" if observed else "RECONSTRUCTED_APPROXIMATE",
            "rooms_on_books": cell["rooms_on_books"],
            "uncertain_rooms": cell["uncertain_rooms"],
        }
    grid = sorted(
        f"{snap}|{day}|{row['origin']}|{row['rooms_on_books']}|{row['uncertain_rooms']}"
        for (snap, day), row in snapshots.items()
    )
    targets = [compute_target(name, snapshots) for name in TARGETS]
    payload = {
        "description": (
            "Golden Expected baselines of MASSERIA NINFA DEMO: the Gate 2/3 bookings plus a "
            "synthetic history (masseria_ninfa_bookings_history_v1.csv). Computed independently "
            "of the application code (generate_masseria_expected_expected.py, standard library "
            "only, exact fractions). BOOKINGS -> SNAPSHOTS -> EXPECTED BASELINES: nothing else."
        ),
        "property": {"timezone": "Europe/Rome", "currency": "EUR"},
        "observation_start": OBSERVATION_START.isoformat(),
        "reconstruction_clock": RECONSTRUCTION_CLOCK.isoformat(),
        "method": "MEDIAN_SAME_DOW_SEASONAL_WINDOW",
        "calculation_version": "booking-expected-v1",
        "snapshots": [
            {"kind": s["kind"], "snapshot_date": s["snapshot_date"].isoformat(),
             "stay_date": s["stay_date"].isoformat()}
            for s in specs
        ],
        "counts": {
            "history_bookings": len(bookings),
            "snapshots": len(specs),
            "observed_snapshots": sum(s["kind"] == "OBSERVED" for s in specs),
            "reconstructed_snapshots": sum(s["kind"] == "RECONSTRUCTED" for s in specs),
        },
        "snapshot_grid_sha256": hashlib.sha256("\n".join(grid).encode("ascii")).hexdigest(),
        "targets": targets,
    }
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    print(f"wrote {HISTORY_CSV.name}: {len(bookings)} bookings; {OUTPUT.name}: "
          f"{len(specs)} snapshots, {len(targets)} targets")


if __name__ == "__main__":
    main()

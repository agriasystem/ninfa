"""Independent calculation of the Gate 3 golden snapshots ("MASSERIA NINFA DEMO").

Standard library only (csv, decimal, zoneinfo, datetime, hashlib, json): it shares NO code with
the application. It reads the two synthetic booking files and the inventory declared below, and
brute-forces every (snapshot day, stay night) cell with the plainest possible loops, then writes
`masseria_ninfa_snapshots_v1.expected.json` next to itself.

Run it from anywhere:  python generate_masseria_snapshots_expected.py

Rules re-implemented here from the written specification (docs/architecture/booking-snapshots-v1.md),
not from the application code:

* stay night: check_in <= D < check_out; revenue of a stay is spread over its nights in whole
  cents, the remainder (one cent each) going to the earliest nights;
* OBSERVED (the present): CONFIRMED / CHECKED_IN / CHECKED_OUT count, CANCELLED / NO_SHOW do not;
* RECONSTRUCTED at the end of property-local day S (cutoff = start of S+1, excluded):
    made before the cutoff  AND  ( CONFIRMED / CHECKED_IN / CHECKED_OUT: on the books
                                   CANCELLED with a date: on the books while cutoff <= cancelled_at
                                   CANCELLED without a date: UNCERTAIN
                                   NO_SHOW: on the books while S < check_in, UNCERTAIN afterwards )
* occupancy = rooms_on_books * 100 / rooms_available (2 decimals, half up, not clamped), only
  when the capacity is known and positive; ADR = revenue / rooms_on_books (2 decimals, half up),
  only when there are rooms on the books.
"""

import csv
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
BOOKING_FILES = [
    HERE.parent / "bookings" / "masseria_ninfa_bookings_v1.csv",
    HERE / "masseria_ninfa_bookings_addendum_v1.csv",
]
OUTPUT = HERE / "masseria_ninfa_snapshots_v1.expected.json"
ROME = ZoneInfo("Europe/Rome")

OBSERVED_AT = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)  # 12:00 in Rome
RECONSTRUCTED_AT = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
STAY_FIRST, STAY_LAST = date(2026, 3, 20), date(2026, 7, 21)
SNAPSHOT_FIRST, SNAPSHOT_LAST = date(2026, 1, 1), date(2026, 7, 26)

# Room inventory of the (fictional) property. A night that no range covers has NO row: unknown.
INVENTORY = [
    ("2026-03-20", "2026-04-26", 12, 0),
    ("2026-04-27", "2026-04-29", 0, 0),  # closed for works: capacity is 0, not unknown
    ("2026-04-30", "2026-04-30", 12, 0),
    # 2026-05-01 .. 2026-05-03: no row at all (capacity unknown)
    ("2026-05-04", "2026-05-31", 12, 1),
    ("2026-06-01", "2026-06-14", 14, 0),
    ("2026-06-15", "2026-06-18", 2, 0),  # a wing is closed: fewer rooms than a group has booked
    ("2026-06-19", "2026-07-21", 14, 0),
]

STATUSES = {
    "confermato": "CONFIRMED",
    "checked in": "CHECKED_IN",
    "checked out": "CHECKED_OUT",
    "annullato": "CANCELLED",
    "cancellato": "CANCELLED",
    "no-show": "NO_SHOW",
}
COUNTED = {"CONFIRMED", "CHECKED_IN", "CHECKED_OUT"}

# Cells worth reading by hand: (snapshot day, stay night, why).
PROBES = [
    ("2026-03-10", "2026-03-24", "a stay night without any booking: a row with zeros, ADR unknown"),
    ("2026-01-04", "2026-03-20", "before the first booking exists: nothing on the books"),
    ("2026-01-05", "2026-03-20", "MN-0001 made at 10:15 Rome on the 5th: on the books that day"),
    ("2026-02-25", "2026-03-20", "MN-0001 (180.00/night) and MN-0104 (180.00/night) are made"),
    ("2026-03-10", "2026-03-20", "MN-0103 arrives: 2 rooms, 1000.00 over 3 nights = 333.34/333.33/333.33"),
    ("2026-03-10", "2026-03-21", "night 2 of MN-0103 = 333.33; ADR 693.33/4 rooms = 173.3325 -> 173.33"),
    ("2026-03-10", "2026-03-22", "night 3 of MN-0103; MN-0104 is over (2 nights)"),
    ("2026-03-27", "2026-03-28", "NO_SHOW MN-0105 is still a normal booking before its arrival day"),
    ("2026-03-28", "2026-03-28", "from its arrival day the NO_SHOW is UNCERTAIN, not counted"),
    ("2026-03-28", "2026-03-29", "the same booking, second night"),
    ("2026-03-28", "2026-05-15", "MN-0009 was made on 29/03 03:30 Rome: not yet there on the 28th"),
    ("2026-03-29", "2026-05-15", "...and on the books at the end of the 29th (23-hour local day)"),
    ("2026-02-14", "2026-04-10", "MN-0003 (later CANCELLED, cancelled 15/02 16:20) is still on the books"),
    ("2026-02-15", "2026-04-10", "cancelled during the 15th: gone at the end of that day"),
    ("2026-03-06", "2026-04-10", "MN-0102 (200.01 over 2 nights) made on 05/03: 100.01 on night 1"),
    ("2026-03-06", "2026-04-11", "night 2 of MN-0102 = 100.00"),
    ("2026-03-01", "2026-04-03", "MN-0004 (2 rooms, 420.00/night) + MN-0101 (100.00 over 3 nights)"),
    ("2026-03-01", "2026-04-04", "MN-0101 night 2 = 33.33"),
    ("2026-03-14", "2026-05-01", "MN-0006 counts; MN-0007 (CANCELLED, no date) is not yet made"),
    ("2026-03-15", "2026-05-01", "MN-0007 made at 23:10 Rome on the 15th: UNCERTAIN, and capacity unknown"),
    ("2026-06-30", "2026-05-02", "still uncertain months later; capacity unknown gives no occupancy"),
    ("2026-04-01", "2026-04-27", "closed night: capacity 0 (not unknown), occupancy undefined"),
    ("2026-04-10", "2026-04-28", "a booking on a closed night: rooms on the books, occupancy undefined"),
    ("2026-06-01", "2026-06-12", "MN-0011: 3 rooms, 4725.00 over 7 nights = 675.00/night"),
    ("2026-06-01", "2026-06-15", "capacity 2 with 3 rooms booked: occupancy 150.00, not clamped"),
    ("2026-04-14", "2026-06-13", "MN-0106 (CANCELLED, no date, 2 rooms) made on 15/04: not yet"),
    ("2026-04-15", "2026-06-13", "MN-0106 now uncertain; 700.00 over 3 nights would be 233.34/233.33/233.33"),
    ("2026-06-19", "2026-06-26", "MN-0013 (later CANCELLED) is still on the books on the 19th"),
    ("2026-06-20", "2026-06-26", "cancelled on the 20th at 09:00 Rome: gone at the end of that day"),
    ("2026-07-04", "2026-07-17", "MN-0016 not made yet"),
    ("2026-07-05", "2026-07-17", "MN-0016: 1234.56 over 4 nights = 308.64/night"),
    ("2026-07-25", "2026-03-20", "OBSERVED today: MN-0001, MN-0103, MN-0104 (NO_SHOW/CANCELLED excluded)"),
    ("2026-07-25", "2026-03-24", "OBSERVED today: a night without bookings"),
    ("2026-07-25", "2026-03-28", "OBSERVED today: the NO_SHOW is excluded, MN-0002 counts"),
    ("2026-07-25", "2026-05-01", "OBSERVED today: MN-0007 is CANCELLED: excluded, no uncertainty"),
    ("2026-07-25", "2026-06-15", "OBSERVED today: 3 rooms on a night with capacity 2"),
    ("2026-07-25", "2026-04-04", "OBSERVED today: MN-0004 + MN-0101 (both counted)"),
    ("2026-07-24", "2026-04-04", "the day before the observation is only a reconstruction"),
    ("2026-07-26", "2026-07-17", "the last reconstructed day"),
]


def read_bookings() -> list[dict[str, object]]:
    bookings = []
    for path in BOOKING_FILES:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                bookings.append(
                    {
                        "id": row["Codice Prenotazione"],
                        "booked_at": local_to_utc(row["Data Prenotazione"]),
                        "check_in": parse_date(row["Arrivo"]),
                        "check_out": parse_date(row["Partenza"]),
                        "status": STATUSES[row["Stato"].strip().lower()],
                        "rooms": int(row["Camere"]),
                        "cents": money_to_cents(row["Importo Camera"]),
                        "cancelled_at": (
                            local_to_utc(row["Data Cancellazione"])
                            if row["Data Cancellazione"]
                            else None
                        ),
                    }
                )
    return bookings


def parse_date(text: str) -> date:
    day, month, year = text.split("/")
    return date(int(year), int(month), int(day))


def local_to_utc(text: str) -> datetime:
    day_part, time_part = text.split(" ")
    hour, minute = time_part.split(":")
    local = datetime.combine(parse_date(day_part), time(int(hour), int(minute)), tzinfo=ROME)
    return local.astimezone(UTC)


def money_to_cents(text: str) -> int:
    value = Decimal(text.replace(".", "").replace(",", "."))
    return int(value * 100)


def night_cents(booking: dict[str, object], night: date) -> int:
    check_in, check_out = booking["check_in"], booking["check_out"]
    assert isinstance(check_in, date) and isinstance(check_out, date)
    total = booking["cents"]
    assert isinstance(total, int)
    nights = (check_out - check_in).days
    index = (night - check_in).days
    base, extra = total // nights, total % nights
    return base + (1 if index < extra else 0)


def cutoff_of(day: date) -> datetime:
    """Start of the next local day (excluded), in UTC."""
    return datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=ROME).astimezone(UTC)


def capacity_of(night: date) -> int | None:
    for first, last, rooms, _out_of_order in INVENTORY:
        if date.fromisoformat(first) <= night <= date.fromisoformat(last):
            return rooms
    return None


def cell(snapshot_day: date, night: date, observed: bool, bookings: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    count = rooms = cents = ucount = urooms = 0
    cutoff = cutoff_of(snapshot_day)
    for b in bookings:
        assert isinstance(b["check_in"], date) and isinstance(b["check_out"], date)
        if not (b["check_in"] <= night < b["check_out"]):
            continue
        status = b["status"]
        certain = uncertain = False
        if observed:
            certain = status in COUNTED
        else:
            assert isinstance(b["booked_at"], datetime)
            if b["booked_at"] < cutoff:
                if status in COUNTED:
                    certain = True
                elif status == "CANCELLED":
                    cancelled_at = b["cancelled_at"]
                    if cancelled_at is None or cancelled_at < b["booked_at"]:
                        uncertain = True
                    else:
                        assert isinstance(cancelled_at, datetime)
                        certain = cutoff <= cancelled_at
                elif status == "NO_SHOW":
                    if snapshot_day < b["check_in"]:
                        certain = True
                    else:
                        uncertain = True
        assert isinstance(b["rooms"], int)
        if certain:
            count += 1
            rooms += b["rooms"]
            cents += night_cents(b, night)
        if uncertain:
            ucount += 1
            urooms += b["rooms"]
    capacity = capacity_of(night)
    occupancy = adr = None
    if capacity is not None and capacity > 0:
        occupancy = (Decimal(rooms) * 100 / Decimal(capacity)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    if rooms > 0:
        adr = (Decimal(cents) / 100 / Decimal(rooms)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return {
        "snapshot_date": snapshot_day.isoformat(),
        "stay_date": night.isoformat(),
        "origin": "OBSERVED" if observed else "RECONSTRUCTED_APPROXIMATE",
        "booking_count_on_books": count,
        "rooms_on_books": rooms,
        "allocated_room_revenue_on_books": format(Decimal(cents) / 100, ".2f"),
        "rooms_available": capacity,
        "occupancy_on_books": None if occupancy is None else format(occupancy, ".2f"),
        "adr_on_books": None if adr is None else format(adr, ".2f"),
        "uncertain_booking_count": ucount,
        "uncertain_rooms": urooms,
    }


def line(c: dict[str, object]) -> str:
    return "|".join("-" if v is None else str(v) for v in c.values())


def main() -> None:
    bookings = read_bookings()
    nights = [STAY_FIRST + timedelta(days=i) for i in range((STAY_LAST - STAY_FIRST).days + 1)]
    observed_day = OBSERVED_AT.astimezone(ROME).date()
    lines = []
    cells = {}
    for offset in range((SNAPSHOT_LAST - SNAPSHOT_FIRST).days + 1):
        snapshot_day = SNAPSHOT_FIRST + timedelta(days=offset)
        for night in nights:
            observed = snapshot_day == observed_day
            c = cell(snapshot_day, night, observed, bookings)
            cells[(c["snapshot_date"], c["stay_date"])] = c
            lines.append(line(c))
    lines.sort()
    digest = hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()
    probes = []
    for snapshot_day, stay_day, note in PROBES:
        probes.append({**cells[(snapshot_day, stay_day)], "note": note})
    payload = {
        "description": (
            "Snapshots of the golden world (masseria_ninfa_bookings_v1.csv + "
            "masseria_ninfa_bookings_addendum_v1.csv + the inventory below). Computed "
            "independently of the application code (generate_masseria_snapshots_expected.py, "
            "standard library only). BOOKINGS + INVENTORY -> SNAPSHOTS: nothing else is derived."
        ),
        "property": {"timezone": "Europe/Rome", "currency": "EUR"},
        "observed_at": OBSERVED_AT.isoformat(),
        "reconstructed_at": RECONSTRUCTED_AT.isoformat(),
        "stay_dates": {"first": STAY_FIRST.isoformat(), "last": STAY_LAST.isoformat()},
        "reconstruction_snapshot_dates": {
            "first": SNAPSHOT_FIRST.isoformat(),
            "last": SNAPSHOT_LAST.isoformat(),
        },
        "inventory": [
            {"first": a, "last": b, "rooms_available": r, "rooms_out_of_order": o}
            for a, b, r, o in INVENTORY
        ],
        "counts": {
            "stay_nights": len(nights),
            "observed": len(nights),
            "reconstructed_created": (len(nights) * ((SNAPSHOT_LAST - SNAPSHOT_FIRST).days + 1))
            - len(nights),
            "reconstructed_skipped_observed": len(nights),
        },
        "grid_sha256": digest,
        "probes": probes,
    }
    # newline="\n": the same bytes on every platform (the fixtures are stored as they are)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    print(f"wrote {OUTPUT.name}: {len(lines)} cells, {len(probes)} probes, sha256 {digest}")


if __name__ == "__main__":
    main()

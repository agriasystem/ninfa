"""python -m tests.benchmarks.algorithmic_v4.perf   (from services/api; a minute, no network)

What V4 costs per upload, on files the size a hotel really sends.

Realistic bookings exports of 100, 1,000, 10,000 and 40,000 rows (a CSV and an .xlsx each) are
understood end to end by V3 and by V4, repeated, and the median is reported with its stages:

    scan       reading the file into bounded grids (V3's reader; identical for both engines)
    mapping    `propose`: which column is which field - the step V4 replaces. Profiling, header
               matching, value evidence, relations, scoring and the assignment all happen here
    total      `UnderstandingService.understand`, the call the upload route makes

Only the first `SCAN_ROWS` (2,000) rows are ever profiled, whatever the file's length, so the
mapping time does not grow with a bigger file; the scan and the import's own validation are V3's.
Run it on a quiet machine: it measures time.
"""

import argparse
import json
import random
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.modules.bookings.parsers import open_table
from app.modules.data_sources.algorithmic.selector import propose, use_engine
from app.modules.data_sources.column_profile import ColumnSample, sample_columns
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.document_understanding.grid import scan_workbook
from tests.benchmarks.smart_import_v3.draw import Sheet, csv_bytes, write_table, xlsx_bytes
from tests.benchmarks.smart_import_v3.observe import make_service, run
from tests.benchmarks.universal_understanding_v2.common import date_cell, money_cell
from tests.benchmarks.universal_understanding_v2.gen_bookings import stays

SIZES = (100, 1_000, 10_000, 40_000)
HEADERS = (
    "Reservation Code",
    "Booking Date",
    "Check in",
    "Check out",
    "Status",
    "Rooms",
    "Room Revenue",
    "Channel",
    "Guest name",
)


def rows_of(count: int) -> list[list[Any]]:
    rng = random.Random(count)
    return [
        [
            s.ref,
            date_cell(s.booked.date(), "iso"),
            date_cell(s.arrival, "iso"),
            date_cell(s.departure, "iso"),
            s.status_label("en"),
            s.rooms,
            money_cell(s.revenue, "point"),
            s.channel_label("en"),
            f"Guest {s.guest}",
        ]
        for s in stays(rng, count, statuses=("CONFIRMED", "CANCELLED", "NO_SHOW"))
    ]


def files(count: int) -> dict[str, bytes]:
    body = rows_of(count)
    sheet = Sheet("Prenotazioni")
    write_table(sheet, list(HEADERS), body)
    return {
        "csv": csv_bytes([list(HEADERS), *body], delimiter=",", decimal=".", dates="iso"),
        "xlsx": xlsx_bytes([sheet]),
    }


def median_ms(function: Callable[[], object], repeats: int) -> float:
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        values.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(values), 1)


def samples_of(content: bytes, name: str) -> list[ColumnSample]:
    return sample_columns(open_table(content, name))


def measure(count: int, kind: str, content: bytes, repeats: int) -> dict[str, Any]:
    name = f"export.{kind}"
    samples = samples_of(content, name)
    out: dict[str, Any] = {"rows": count, "kind": kind, "bytes": len(content)}
    out["scan_ms"] = median_ms(lambda: scan_workbook(content, name), repeats)
    for engine in ("v3", "v4"):
        with use_engine(engine):
            out[f"mapping_{engine}_ms"] = median_ms(lambda: propose(BOOKINGS, samples), repeats * 3)
            out[f"total_{engine}_ms"] = median_ms(
                lambda: run(make_service(), "bookings", name, content), repeats
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.algorithmic_v4.perf")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--sizes", default=",".join(str(s) for s in SIZES))
    args = parser.parse_args(argv)
    results = []
    print("| rows | kind | scan | mapping V3 | mapping V4 | total V3 | total V4 | V4 - V3 |")
    print("|---:|---|---:|---:|---:|---:|---:|---:|")
    for size in (int(s) for s in args.sizes.split(",")):
        for kind, content in files(size).items():
            r = measure(size, kind, content, args.repeats)
            results.append(r)
            delta = r["total_v4_ms"] - r["total_v3_ms"]
            print(
                f"| {size} | {kind} | {r['scan_ms']} | {r['mapping_v3_ms']} | {r['mapping_v4_ms']} "
                f"| {r['total_v3_ms']} | {r['total_v4_ms']} | {delta:+.1f} ms |"
            )
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

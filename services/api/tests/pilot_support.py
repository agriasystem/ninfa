"""Shared file-writing helpers for the Gate 21B pilot CLI tests (`test_pilot_*.py`).

These build REAL files on disk in the ONE canonical pilot format `app/cli/imports.py` documents
(headers = the import services' own canonical field names) - tests then hand them to the real
`run_import_*` functions, exactly as an operator would with `--file`. Nothing here constructs a
`NormalizedBooking`/`CanonicalEntry` or any other already-parsed record directly: every fixture
here is bytes a real file reader has to parse.
"""

from datetime import date, timedelta
from pathlib import Path


def booking_csv(tmp_path: Path, *, stay_dates: list[date], filename: str = "bookings.csv") -> Path:
    """One CONFIRMED, 1-room booking per stay date, booked comfortably in the past."""
    booked_at = (min(stay_dates) - timedelta(days=21)).isoformat()
    lines = ["source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel"]
    for index, stay_date in enumerate(stay_dates, start=1):
        check_out = stay_date + timedelta(days=1)
        lines.append(
            f"PILOT-{index:04d},{booked_at},{stay_date.isoformat()},{check_out.isoformat()},"
            f"confirmed,1,150.00,Direct"
        )
    path = tmp_path / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def malformed_booking_csv(tmp_path: Path, *, filename: str = "bookings_malformed.csv") -> Path:
    """A row with a non-positive `rooms` value: real content, meant to fail row validation."""
    lines = [
        "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel",
        "PILOT-BAD-0001,2026-09-01,2026-10-05,2026-10-07,confirmed,0,150.00,Direct",
    ]
    path = tmp_path / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def labor_csv(tmp_path: Path, *, work_dates: list[date], filename: str = "labor.csv") -> Path:
    lines = ["work_date,labor_category,planned_hours,planned_cost,currency"]
    for work_date in work_dates:
        lines.append(f"{work_date.isoformat()},HOUSEKEEPING,8,120.00,EUR")
    path = tmp_path / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

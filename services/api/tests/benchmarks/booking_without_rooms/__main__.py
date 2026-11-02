"""python -m tests.benchmarks.booking_without_rooms            (from services/api)

An export that does not count rooms, measured on documents nobody looked at to write the rule: every
bookings document of the Universal Understanding V2 corpus (holdout split by default) that has a
column of rooms, read once as it is and once with that column taken out, by the real engine. The
files are the corpus's own and the transformation is mechanical: nothing here knows the rule.

What the two readings of a document must have in common is everything else: taking out the room
count must change no other field, turn no question into an automatic import, and leave no personal
value in the answer. Nothing is read from or written to a database and no model is called.
"""

import argparse
import csv
import io
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.benchmarks.smart_import_v3.observe import Observed, make_service, run
from tests.benchmarks.universal_understanding_v2.corpus import build_corpus, split_of

ROOMS = "rooms"
CRITICAL = ("source_record_id", "booked_at", "check_in", "check_out", "channel", "room_revenue")


def _delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:40])
    counts = {mark: sample.count(mark) for mark in (";", ",", "\t", "|")}
    return max(counts, key=lambda mark: counts[mark])


def _without_column_csv(content: bytes, header: str, header_row: int) -> bytes | None:
    # latin-1 reads any byte and writes it back: the file's own encoding and BOM stay as they are
    text = content.decode("latin-1")
    delimiter = _delimiter(text)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    if not 0 < header_row <= len(rows):
        return None
    cells = [cell.strip().lstrip("\xef\xbb\xbf") for cell in rows[header_row - 1]]
    if header not in cells:
        return None
    position = cells.index(header)
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    for row in rows:
        writer.writerow([cell for index, cell in enumerate(row) if index != position])
    return out.getvalue().encode("latin-1")


def _delete_column(sheet: Worksheet, column: int) -> None:
    """`delete_cols` leaves merged cells where they were: a two-level header would then name the
    wrong columns. So they are taken apart first, and made again where they now belong."""
    merged = [
        (item.min_row, item.max_row, item.min_col, item.max_col)
        for item in sheet.merged_cells.ranges
    ]
    for item in list(sheet.merged_cells.ranges):
        sheet.unmerge_cells(str(item))
    for min_row, _, min_col, max_col in merged:
        # a label on the column going away stays with the rest of its group
        if min_col == column and max_col > column:
            sheet.cell(min_row, column + 1).value = sheet.cell(min_row, column).value
    sheet.delete_cols(column)
    for min_row, max_row, min_col, max_col in merged:
        first = min_col - 1 if min_col > column else min_col
        last = max_col - 1 if max_col >= column else max_col
        if last > first or max_row > min_row:
            sheet.merge_cells(
                start_row=min_row, end_row=max_row, start_column=first, end_column=last
            )


def _without_column_xlsx(content: bytes, header: str, header_row: int) -> bytes | None:
    book = load_workbook(io.BytesIO(content))
    found = False
    for sheet in book.worksheets:
        if sheet.max_row < header_row:
            continue
        for cell in sheet[header_row]:
            if cell.value is not None and str(cell.value).strip() == header:
                _delete_column(sheet, cell.column)
                found = True
                break
    if not found:
        return None
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def without_rooms(filename: str, content: bytes, header: str, header_row: int) -> bytes | None:
    if filename.lower().endswith(".csv"):
        return _without_column_csv(content, header, header_row)
    if filename.lower().endswith(".xlsx"):
        return _without_column_xlsx(content, header, header_row)
    return None


def _fields_of(observed: Observed) -> dict[str, str]:
    return {column.field: column.header for column in observed.columns if column.field}


@dataclass
class Tally:
    documents: int = 0
    skipped: list[str] = field(default_factory=list)
    levels_before: Counter[str] = field(default_factory=Counter)
    levels_after: Counter[str] = field(default_factory=Counter)
    lost_ready: list[str] = field(default_factory=list)
    gained_ready: list[str] = field(default_factory=list)
    other_field_changed: list[str] = field(default_factory=list)
    room_constant_wrong: list[str] = field(default_factory=list)
    false_automation: list[str] = field(default_factory=list)
    critical_wrong: list[str] = field(default_factory=list)
    pii_leaks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def measure(split: str) -> Tally:
    service = make_service()
    tally = Tally()
    for doc in build_corpus():
        golden = doc.golden
        if golden.domain != "bookings" or (split != "all" and split_of(doc) != split):
            continue
        source = golden.fields.get(ROOMS)
        if source is None or source.kind != "COLUMN" or not golden.header_rows:
            continue
        content = without_rooms(
            doc.filename, doc.content, source.header[-1], golden.header_rows[-1]
        )
        if content is None:
            tally.skipped.append(doc.id)
            continue
        before = run(service, "bookings", doc.filename, doc.content)
        after = run(service, "bookings", doc.filename, content)
        tally.documents += 1
        if after.error is not None:
            tally.errors.append(doc.id)
            continue
        tally.levels_before[str(before.level)] += 1
        tally.levels_after[str(after.level)] += 1
        if before.automatic and not after.automatic:
            tally.lost_ready.append(doc.id)
        if after.automatic and not before.automatic:
            tally.gained_ready.append(doc.id)
        was, now = _fields_of(before), _fields_of(after)
        was.pop(ROOMS, None)
        if was != now:
            tally.other_field_changed.append(doc.id)
        if after.automatic and after.constants.get(ROOMS) != 1:
            tally.room_constant_wrong.append(doc.id)
        if after.automatic and golden.outcome not in ("READY", "WARN"):
            tally.false_automation.append(doc.id)
        if after.automatic:
            for name in CRITICAL:
                truth = golden.fields.get(name)
                # (a two-level header reads "upper level + column": the column's own name is in it)
                if (
                    truth is not None
                    and truth.kind == "COLUMN"
                    and truth.header[-1] not in now.get(name, "")
                ):
                    tally.critical_wrong.append(f"{doc.id}:{name}")
        if any(value and value in after.payload for value in golden.pii_values):
            tally.pii_leaks.append(doc.id)
    return tally


def report(tally: Tally, split: str) -> dict[str, object]:
    return {
        "split": split,
        "documents": tally.documents,
        "skipped_not_transformable": tally.skipped,
        "levels_with_the_column": dict(tally.levels_before),
        "levels_without_the_column": dict(tally.levels_after),
        "ready_lost": tally.lost_ready,
        "ready_gained": tally.gained_ready,
        "another_field_changed": tally.other_field_changed,
        "room_count_not_one": tally.room_constant_wrong,
        "false_automation": tally.false_automation,
        "critical_field_wrong": tally.critical_wrong,
        "pii_leaks": tally.pii_leaks,
        "errors": tally.errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.benchmarks.booking_without_rooms", description=__doc__
    )
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="holdout")
    parser.add_argument("--json", type=Path, help="also write the result here")
    args = parser.parse_args(argv)

    data = report(measure(args.split), args.split)
    text = json.dumps(data, indent=1, ensure_ascii=False)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8", newline="\n")
    clean = not (data["false_automation"] or data["critical_field_wrong"] or data["pii_leaks"])
    print("clean" if clean else "NOT CLEAN", file=sys.stderr)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())

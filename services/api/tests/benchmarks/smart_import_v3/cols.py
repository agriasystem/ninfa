"""Column-by-column documents: a table described as a list of `Col`, each knowing its header, how
to write its cell, and what it MEANS - so the file and the truth about it come from one place.

`Col.field` is the canonical field the column ought to become (or `None`: nothing applies, it must
stay unmapped). Writing the meaning next to the header it belongs to is what keeps the truth
independent of Smart Import: nothing is looked up, nothing is inferred.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from tests.benchmarks.smart_import_v3.draw import (
    Sheet,
    TableRef,
    csv_bytes,
    write_table,
    xlsx_bytes,
)
from tests.benchmarks.smart_import_v3.kit import Built, facts
from tests.benchmarks.smart_import_v3.model import Golden, Source, column


@dataclass(frozen=True, slots=True)
class Col:
    header: str
    cell: Callable[[Any], Any]
    field: str | None = None  # what the column means; None = nothing (must stay unmapped)
    pii: bool = False  # the column holds personal data
    ambiguous: bool = False  # `field` is what it would be IF the person confirmed; not claimable
    junk: bool = True  # with field None and pii False: must stay unmapped (asserted)


def headers(cols: Sequence[Col]) -> list[str]:
    return [c.header for c in cols]


def records(cols: Sequence[Col], items: Sequence[Any]) -> list[list[Any]]:
    return [[c.cell(item) for c in cols] for item in items]


def parts(cols: Sequence[Col], items: Sequence[Any]) -> dict[str, Any]:
    """The meaning part of a golden: where fields are, what stays unmapped, what is personal."""
    fields: dict[str, Source] = {}
    ambiguous: list[str] = []
    ambiguous_sources: dict[str, Source] = {}  # (what each would be if the person confirmed it)
    unmapped: list[tuple[str, ...]] = []
    pii_columns: list[tuple[str, ...]] = []
    pii_values: set[str] = set()
    seen: dict[str, int] = {}
    for col in cols:
        seen[col.header] = seen.get(col.header, 0) + 1
        source = column(col.header, n=seen[col.header])
        if col.pii:
            pii_columns.append((col.header,))
            pii_values.update(str(col.cell(item)) for item in items)
        elif col.field is not None and col.ambiguous:
            ambiguous.append(col.field)
            ambiguous_sources[col.field] = source
        elif col.field is not None:
            fields[col.field] = source
        elif col.junk:
            unmapped.append((col.header,))
    return {
        "fields": fields,
        "ambiguous": tuple(ambiguous),
        "ambiguous_sources": ambiguous_sources,
        "unmapped": tuple(unmapped),
        "pii_columns": tuple(pii_columns),
        "pii_values": tuple(sorted(v for v in pii_values if len(v) >= 5)),
    }


def flat_document(
    domain: str,
    filename: str,
    cols: Sequence[Col],
    items: Sequence[Any],
    *,
    outcome: str = "READY",
    sheet_title: str = "Prenotazioni",
    preamble: Sequence[Any] = (),
    blank_after_preamble: bool = True,
    wrap: Callable[[list[list[Any]]], list[Any]] | None = None,
    after: Callable[[Sheet], None] | None = None,
    upper: Sequence[str | None] | None = None,
    upper_merges: Sequence[tuple[int, int]] = (),
    csv: dict[str, Any] | None = None,
    left: int = 0,
    freeze: str | None = None,
    extra_fields: dict[str, Source] | None = None,
    drop_fields: Sequence[str] = (),
    questions: Sequence[str] = (),
    tolerated: Sequence[str] = (),
    answers: dict[str, Any] | None = None,
    labels: dict[str, dict[str, str]] | None = None,
    blockers: Sequence[str] = (),
    absent: Sequence[str] = (),
    unmapped_extra: Sequence[tuple[str, ...]] = (),
    period_start: str | None = None,
    date_order: str | None = None,
    decimal: str | None = None,
    note: str = "",
    sheets_before: Sequence[Sheet] = (),
    sheets_after: Sequence[Sheet] = (),
    header_style: str | None = "header",
) -> Built:
    """One flat table, optionally surrounded, written as .xlsx or (with `csv`) as a CSV."""
    sheet = Sheet(sheet_title, left=left, freeze=freeze)
    for line in preamble:
        if isinstance(line, tuple):
            sheet.add(list(line[1:]), style=line[0])
        else:
            sheet.add([line])
    if preamble and blank_after_preamble:
        sheet.blank()
    body = records(cols, items)
    ref: TableRef = write_table(
        sheet,
        headers(cols),
        wrap(body) if wrap else body,
        upper=upper,
        upper_merges=upper_merges,
        header_style=header_style,
    )
    if after:
        after(sheet)
    meaning = parts(cols, items)
    absent = list(absent)
    answers = dict(answers or {})
    amount = meaning["ambiguous_sources"].get("net_amount")
    if answers.get("amount_basis") == "NET" and amount is not None:
        # the column the person's answer turns into the net (the scorer reads it back)
        answers["amount_column"] = {"header": list(amount.header), "occurrence": amount.occurrence}
    if domain == "bookings" and outcome == "READY":
        # The importer needs a status and a number of rooms for every booking: from a column, or
        # from a value the person chooses. Without either, V3.0 cannot be automatic (and has no
        # question to ask for it): the person has to match the columns.
        have = {c.field for c in cols if c.field is not None and not c.pii}
        lacking = [name for name in ("status", "rooms") if name not in have]
        if lacking:
            outcome = "NOT_AUTOMATIC"
            absent.extend(lacking)
            note = (note + " " if note else "") + (
                f"No {' / '.join(lacking)} column: a fixed value must be chosen by the person."
            )
    fields = {k: v for k, v in meaning["fields"].items() if k not in drop_fields}
    fields.update(extra_fields or {})
    golden = Golden(
        domain,
        outcome,
        **facts(ref, csv=csv is not None),
        fields=fields,
        ambiguous=meaning["ambiguous"],
        unmapped=(*meaning["unmapped"], *unmapped_extra),
        pii_columns=meaning["pii_columns"],
        pii_values=meaning["pii_values"],
        questions=tuple(questions),
        tolerated=tuple(tolerated),
        answers=answers,
        labels=labels or {},
        blockers=tuple(blockers),
        absent=tuple(absent),
        period_start=period_start,
        date_order=date_order,
        decimal=decimal,
        note=note,
    )
    every = [*sheets_before, sheet, *sheets_after]
    if csv is not None:
        from tests.benchmarks.smart_import_v3.draw import sheet_csv

        return Built(filename, sheet_csv(sheet, **csv), golden, every)
    return Built(filename, xlsx_bytes(every), golden, every)


__all__ = ["Col", "flat_document", "headers", "parts", "records", "csv_bytes"]

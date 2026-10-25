"""The two records of the benchmark: a DOCUMENT and the TRUTH about it.

The truth (`Golden`) is written by hand next to the file it describes, from what was put into the
file: the row a header was written on, the columns that are personal data, the questions a person
would really have to answer. It is never derived from what Smart Import answers, and the
scoring code only ever sees it as plain JSON (`to_json` / `from_json`), so the two sides cannot
lean on each other.

Vocabulary used by the golden:

* ``domain``  - what the document IS: ``labor`` | ``bookings`` | ``costs`` | ``other``.
* ``outcome`` - what V3.0 ought to do with it:
    ``READY``          import it with no question at all;
    ``ASK``            import it, but only after the questions listed in ``questions``;
    ``NOT_AUTOMATIC``  never silently (any question, manual matching or refusal is fine);
    ``WARN``           the document contradicts itself (totals that do not add up): a block or a
                       question is right, and so is going on WITH the contradiction shown to the
                       person as a warning - never without it;
    ``REJECT``         refuse it (manual matching or a blocker), the V3.0 limits say so.
* ``fields`` - canonical field -> where it is in the document (``Source``). Two pseudo fields exist
  because the importers accept two spellings of one business fact: ``department`` (``role`` or
  ``labor_category``) and ``net_amount`` (``line_total`` or ``invoice_net_amount``).
"""

from dataclasses import asdict, dataclass, field
from typing import Any

DOMAINS = ("labor", "bookings", "costs")
OUTCOMES = ("READY", "ASK", "REJECT", "NOT_AUTOMATIC", "WARN")

# Facts a business decision rests on (the *false automation* metric looks at these only).
CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "labor": ("work_date", "department", "planned_hours", "actual_hours"),
    "bookings": (
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "channel",
        "room_revenue",
    ),
    "costs": ("invoice_date", "invoice_number", "supplier_name", "net_amount"),
}

# What each importer cannot run without (one entry per business fact; a tuple is "any of").
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "labor": ("work_date", "department", "hours"),
    "bookings": (
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "channel",
        "room_revenue",
    ),
    "costs": ("supplier_name", "invoice_number", "invoice_date", "line_description", "net_amount"),
}


@dataclass(frozen=True, slots=True)
class Source:
    """Where a value comes from in the document.

    ``COLUMN`` carries the header cell(s) as written, upper level first (``("Personale", "Ore")``);
    ``occurrence`` picks the n-th column of that name when a header is repeated. The other kinds are
    a department written as a line of its own (``SECTION``), as the name of the sheet (``SHEET``) or
    in the title (``TITLE``), and the days of a grid (``GRID``)."""

    kind: str
    header: tuple[str, ...] = ()
    occurrence: int = 1


@dataclass(slots=True)
class Golden:
    domain: str
    outcome: str
    # --- the table --------------------------------------------------------------------------------
    sheets: tuple[str, ...] = ()  # the sheet(s) holding the records (empty: a CSV)
    header_rows: tuple[int, ...] = ()  # 1-based, upper level first
    first_row: int | None = None  # the first record
    data_rows: int | None = None  # how many records, nothing else counted
    # lines of the table zone that are NOT records: {"totals": 1, "notes": 2, "sections": 0}
    skipped: dict[str, int] = field(default_factory=dict)
    # --- the meaning ------------------------------------------------------------------------------
    fields: dict[str, Source] = field(default_factory=dict)
    ambiguous: tuple[str, ...] = ()  # facts that must not be decided without asking
    absent: tuple[str, ...] = ()  # facts the document does not hold: claiming one is an error
    unmapped: tuple[tuple[str, ...], ...] = ()  # columns that must NOT become a field (junk, rates)
    # --- personal data ----------------------------------------------------------------------------
    pii_columns: tuple[tuple[str, ...], ...] = ()
    pii_values: tuple[str, ...] = ()  # every distinct personal value of the document
    # --- questions --------------------------------------------------------------------------------
    questions: tuple[str, ...] = ()  # necessary kinds
    tolerated: tuple[str, ...] = ()  # fine to ask, not required
    # {"role_mapping": {"HK": "HOUSEKEEPING", "MAN": "?"}}; "?" = the person must say
    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()  # blocker codes a refusal is expected to carry (optional)
    period_start: str | None = None  # the week/period of the document (ISO), when it states one
    # how the TEXT dates / amounts are written (a real Excel date or number needs no choice):
    date_order: str | None = None  # "DMY" | "MDY" | "YMD"
    decimal: str | None = None  # "," | "."
    # what a person would answer to the necessary questions (UnderstandAnswers as a dict)
    answers: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(slots=True)
class Doc:
    id: str
    card: str  # the kind of data the person chose when uploading (labor | bookings | costs)
    filename: str
    content: bytes
    golden: Golden
    tags: tuple[str, ...] = ()
    structure: tuple[str, ...] = ()  # the shape of the document, as tags
    sheet_count: int = 1


# --- JSON ----------------------------------------------------------------------------------------


def golden_to_json(golden: Golden) -> dict[str, Any]:
    data = asdict(golden)
    data["fields"] = {name: asdict(source) for name, source in golden.fields.items()}
    return data


def golden_from_json(data: dict[str, Any]) -> Golden:
    return Golden(
        domain=data["domain"],
        outcome=data["outcome"],
        sheets=tuple(data["sheets"]),
        header_rows=tuple(data["header_rows"]),
        first_row=data["first_row"],
        data_rows=data["data_rows"],
        skipped=dict(data["skipped"]),
        fields={
            name: Source(s["kind"], tuple(s["header"]), s["occurrence"])
            for name, s in data["fields"].items()
        },
        ambiguous=tuple(data["ambiguous"]),
        absent=tuple(data["absent"]),
        unmapped=tuple(tuple(h) for h in data["unmapped"]),
        pii_columns=tuple(tuple(h) for h in data["pii_columns"]),
        pii_values=tuple(data["pii_values"]),
        questions=tuple(data["questions"]),
        tolerated=tuple(data["tolerated"]),
        labels={doc: dict(words) for doc, words in data["labels"].items()},
        blockers=tuple(data["blockers"]),
        period_start=data["period_start"],
        date_order=data["date_order"],
        decimal=data["decimal"],
        answers=dict(data["answers"]),
        note=data["note"],
    )


def column(*header: str, n: int = 1) -> Source:
    """A column of the document, by the header cell(s) as written."""
    return Source("COLUMN", tuple(header), n)


SECTION = Source("SECTION")
SHEET = Source("SHEET")
TITLE = Source("TITLE")
GRID = Source("GRID")

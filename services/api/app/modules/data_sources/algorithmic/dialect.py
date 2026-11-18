"""What a CSV file IS, physically: its delimiter, quoting, columns, types and malformed rows.

V3 reads the delimiter with a counting rule (`grid.detect_delimiter`): the one that splits most of
the
first lines into the same number of fields. It is simple and right for the files a hotel exports.
This
module asks a second, independent reader and only lets it overrule the first when it splits the
sample MORE CONSISTENTLY - so the result is never a delimiter the counting rule would have found
worse.

    DuckDB     the primary reader. Its CSV sniffer finds delimiter, quote, escape, whether
    there is a
               header, the type of each column and how dates are written. The file is handed to it
               IN MEMORY (an fsspec memory file, removed at once): customer data
               never touches the disk.
    CleverCSV  the fallback, used ONLY when DuckDB cannot read the file or leaves it ambiguous (the
               columns it finds are too few, or the lines do not agree on a width). It is built for
               messy files - odd quotes, escape characters, inconsistent rows - and is NOT run on a
               file DuckDB read well, so a normal upload pays for one reader.

THE LIMIT THAT STAYS. NINFA's importers read `;`, `,` and a tab - a closed set that is part of the
product's contract (a pipe-delimited file is an unsupported file, not a guess). A sniffer that finds
another delimiter reports it (`Dialect.supported` is False) and the file is handled exactly as
before: this module widens what NINFA UNDERSTANDS about a file, never what it silently imports.

Deterministic, bounded (a sample of the first `SAMPLE_CHARS` characters) and free of side effects.
It
never raises: a file neither reader understands is `None`, and V3's own rule decides.
"""

import contextlib
import csv
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

SUPPORTED = (";", ",", "\t")
SAMPLE_CHARS = 262_144
SAMPLE_LINES = 400
# the lines of a sample that must agree on a width for a delimiter to be trusted
CONSISTENT = 0.85
# a sniffer overrules the counting rule only when it splits the sample this much more consistently
BETTER_BY = 0.10
_CANDIDATES = (";", ",", "\t", "|")


@dataclass(frozen=True, slots=True)
class Dialect:
    delimiter: str
    quote: str | None
    escape: str | None
    header: bool | None
    columns: int
    types: tuple[str, ...]  # a DuckDB type per column ("DATE", "DOUBLE", "VARCHAR", ...)
    date_format: str | None
    timestamp_format: str | None
    engine: str  # "duckdb" | "clevercsv"
    consistency: float  # the share of sampled lines that have the commonest width
    malformed_rows: int  # sampled lines whose width is not the commonest one

    @property
    def supported(self) -> bool:
        return self.delimiter in SUPPORTED


def sample_of(text: str) -> str:
    """The head of a file, cut at a line boundary, bounded in characters and lines."""
    head = text[:SAMPLE_CHARS]
    if len(text) > SAMPLE_CHARS and "\n" in head:
        head = head[: head.rindex("\n") + 1]
    return head


def widths(text: str, delimiter: str) -> list[int]:
    """The number of fields of the first lines, a blank line skipped."""
    out: list[int] = []
    lines = [line for line in text.splitlines() if line.strip()][:SAMPLE_LINES]
    for line in lines:
        try:
            out.append(len(next(csv.reader([line], delimiter=delimiter), [])))
        except csv.Error:
            out.append(1)
    return out


def consistency(text: str, delimiter: str) -> tuple[float, int, int]:
    """(share of lines at the commonest width of 2+ fields, that width, lines off it)."""
    counted = widths(text, delimiter)
    wide = [w for w in counted if w >= 2]
    if not wide or not counted:
        return 0.0, 0, 0
    width, frequency = Counter(wide).most_common(1)[0]
    return frequency / len(counted), width, len(counted) - frequency


# --- the two readers ------------------------------------------------------------------------------


def _duckdb(sample: str) -> dict[str, Any] | None:
    try:
        import duckdb
        import fsspec
    except ImportError:  # the readers are optional at run time: V3's rule stands
        return None
    memory = fsspec.filesystem("memory")
    key = f"/ninfa-sniff/{uuid.uuid4().hex}.csv"
    connection = None
    try:
        memory.pipe_file(key, sample.encode("utf-8"))
        connection = duckdb.connect(":memory:", config={"threads": 1})
        connection.register_filesystem(memory)
        cursor = connection.execute("SELECT * FROM sniff_csv(?)", [f"memory://{key}"])
        row = cursor.fetchone()
        if row is None:
            return None
        names = [column[0] for column in cursor.description]
        return dict(zip(names, row, strict=True))
    except Exception:  # noqa: BLE001 - any failure of the reader is "no opinion", never an error
        return None
    finally:
        if connection is not None:
            connection.close()
        with contextlib.suppress(FileNotFoundError, OSError):
            memory.rm(key)


def _clevercsv(sample: str) -> dict[str, Any] | None:
    try:
        import clevercsv
    except ImportError:
        return None
    try:
        found = clevercsv.Detector().detect(sample, delimiters=list(_CANDIDATES))
    except Exception:  # noqa: BLE001 - "no opinion"
        return None
    if found is None or not found.delimiter:
        return None
    return {
        "Delimiter": found.delimiter,
        "Quote": found.quotechar or None,
        "Escape": found.escapechar or None,
    }


def _clean(value: object) -> str | None:
    text = str(value) if value is not None else ""
    return None if text in {"", "(empty)", "None"} else text


def _dialect(raw: dict[str, Any], sample: str, engine: str) -> Dialect | None:
    delimiter = raw.get("Delimiter")
    if not isinstance(delimiter, str) or not delimiter:
        return None
    share, width, off = consistency(sample, delimiter)
    columns = raw.get("Columns") or []
    types = tuple(str(c.get("type", "")) for c in columns if isinstance(c, dict))
    return Dialect(
        delimiter=delimiter,
        quote=_clean(raw.get("Quote")),
        escape=_clean(raw.get("Escape")),
        header=raw.get("HasHeader") if isinstance(raw.get("HasHeader"), bool) else None,
        columns=len(columns) or width,
        types=types,
        date_format=_clean(raw.get("DateFormat")),
        timestamp_format=_clean(raw.get("TimestampFormat")),
        engine=engine,
        consistency=share,
        malformed_rows=off,
    )


def _ambiguous(dialect: Dialect | None) -> bool:
    return dialect is None or dialect.columns < 2 or dialect.consistency < CONSISTENT


def sniff(text: str) -> Dialect | None:
    """The dialect of a CSV text: DuckDB's reading or, when that is missing or ambiguous,
    CleverCSV's. None when neither reader finds one."""
    sample = sample_of(text)
    if not sample.strip():
        return None
    primary = _dialect(raw, sample, "duckdb") if (raw := _duckdb(sample)) else None
    if not _ambiguous(primary):
        return primary
    fallback = _dialect(raw, sample, "clevercsv") if (raw := _clevercsv(sample)) else None
    if fallback is None:
        return primary
    if primary is None or fallback.consistency > primary.consistency:
        return fallback
    return primary


def choose_delimiter(text: str, counted: str) -> tuple[str, Dialect | None]:
    """The delimiter to read `text` with: V3's counted one, unless a sniffer found a SUPPORTED one
    that splits the sample clearly more consistently. Returns it with what the sniffer saw."""
    dialect = sniff(text)
    if dialect is None or not dialect.supported or dialect.delimiter == counted:
        return counted, dialect
    sample = sample_of(text)
    mine = consistency(sample, counted)[0]
    if dialect.consistency >= mine + BETTER_BY:
        return dialect.delimiter, dialect
    return counted, dialect


def types_of(dialect: Dialect | None) -> Sequence[str]:
    return dialect.types if dialect is not None else ()


__all__ = [
    "BETTER_BY",
    "CONSISTENT",
    "SUPPORTED",
    "Dialect",
    "choose_delimiter",
    "consistency",
    "sample_of",
    "sniff",
    "widths",
]

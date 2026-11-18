"""python -m tests.benchmarks.algorithmic_v4.dialect_stress   (from services/api; seconds)

Does a CSV sniffer find a delimiter the counting rule of V3 does not?

Nineteen files whose delimiter is KNOWN (written by this script, so the truth is never read from a
reader): clean files, decimal commas, quoted text, titles above the table, a trailing delimiter,
ragged lines, two-column files, a `sep=` hint, a pipe-delimited file (a delimiter NINFA's importers
do
not read) and a file with one column. For each: the delimiter V3 counts, the one DuckDB finds, the
one
CleverCSV finds, and the one `choose_delimiter` would read the file with.

The result, and why the benchmark report says what it says about DuckDB and CleverCSV, is the
`correct` line at the bottom: over the files whose delimiter NINFA reads, the counting rule is
already right every time, DuckDB is wrong on files whose text is full of the other delimiter, and
CleverCSV agrees with the counting rule. A sniffer here adds time and no accuracy.
"""

import random
import time
from collections.abc import Callable

from app.modules.data_sources.algorithmic import dialect
from app.modules.document_understanding.grid import detect_delimiter

SUPPORTED = (";", ",", "\t")


def _rows(count: int, columns: int) -> list[list[str]]:
    return [[f"c{r}x{c}" if c else f"R{r:04d}" for c in range(columns)] for r in range(count)]


def _text(delimiter: str, table: list[list[str]], quote: str = '"') -> str:
    lines = []
    for row in table:
        cells = [
            f"{quote}{cell.replace(quote, quote * 2)}{quote}"
            if delimiter in cell or quote in cell
            else cell
            for cell in row
        ]
        lines.append(delimiter.join(cells))
    return "\n".join(lines) + "\n"


def cases() -> dict[str, tuple[str, str]]:
    """name -> (the delimiter the file really uses, its text)."""
    rng = random.Random(11)
    out: dict[str, tuple[str, str]] = {}
    base = _rows(30, 6)
    out["clean_semicolon"] = (";", _text(";", base))
    out["clean_comma"] = (",", _text(",", base))
    out["clean_tab"] = ("\t", _text("\t", base))
    out["pipe"] = ("|", _text("|", base))
    comma_decimals = [["id", "amount", "note"]] + [
        [f"A{i}", f"{rng.randint(10, 999)},{rng.randint(10, 99)}", "ok"] for i in range(25)
    ]
    out["semicolon_comma_decimals"] = (";", _text(";", comma_decimals))
    point_decimals = [["id", "amount", "note"]] + [
        [f"A{i}", f"{rng.randint(10, 999)}.{rng.randint(10, 99)}", "ok"] for i in range(25)
    ]
    out["comma_point_decimals"] = (",", _text(",", point_decimals))
    thousands = [["id", "amount"]] + [
        [f"A{i}", f"{rng.randint(1, 9)},{rng.randint(100, 999)}.50"] for i in range(25)
    ]
    out["comma_quoted_thousands"] = (",", _text(",", thousands))
    notes = [["id", "guest", "note", "total"]] + [
        [
            f"B{i}",
            f"Rossi, Mario {i}",
            "camera tranquilla, vista mare; late check-in",
            f"{100 + i}.50",
        ]
        for i in range(25)
    ]
    out["comma_text_with_semicolons"] = (",", _text(",", notes))
    commas = [["id", "guest", "note", "total"]] + [
        [
            f"B{i}",
            f"Rossi, Mario {i}",
            "camera tranquilla, vista mare, late check-in, 23:00",
            f"{100 + i},50",
        ]
        for i in range(25)
    ]
    out["semicolon_text_full_of_commas"] = (";", _text(";", commas))
    title = "Report prenotazioni;;;;\nHotel Belvedere - ottobre;;;;\n\n" + _text(";", _rows(25, 5))
    out["title_above_semicolon"] = (";", title)
    out["title_above_comma"] = (
        ",",
        "Report prenotazioni\nHotel Belvedere\n\n" + _text(",", _rows(25, 5)),
    )
    out["trailing_delimiter"] = (";", "\n".join(";".join(r) + ";" for r in _rows(25, 5)) + "\n")
    ragged = _text(";", _rows(40, 5)).splitlines()
    ragged[7] += ";extra"
    ragged[19] = ragged[19].replace("c19x2", "c19;x2")
    out["ragged_semicolon"] = (";", "\n".join(ragged) + "\n")
    two = [["codice", "importo"]] + [[f"A{i}", f"{i * 10},50"] for i in range(30)]
    out["two_columns_semicolon"] = (";", _text(";", two))
    out["two_columns_comma"] = (
        ",",
        _text(",", [["codice", "totale"]] + [[f"A{i}", str(i * 10)] for i in range(30)]),
    )
    quoted = "\n".join(",".join(f"'{c}'" for c in row) for row in _rows(25, 4)) + "\n"
    out["single_quote_quoting"] = (",", quoted)
    out["sep_hint"] = (";", "sep=;\n" + _text(";", _rows(20, 4)))
    sparse = [[("" if (r + c) % 3 else f"v{r}{c}") for c in range(6)] for r in range(30)]
    out["sparse_semicolon"] = (";", "\n".join(";".join(r) for r in sparse) + "\n")
    out["single_column"] = ("?", "\n".join(f"R{i}" for i in range(20)) + "\n")
    return out


def main() -> int:
    rows: list[tuple[str, str, str, str | None, str | None, str, float, float]] = []
    for name, (truth, text) in cases().items():
        counted = detect_delimiter(text.splitlines())
        sample = dialect.sample_of(text)
        started = time.perf_counter()
        duck = dialect._duckdb(sample)
        duck_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        clever = dialect._clevercsv(sample)
        clever_ms = (time.perf_counter() - started) * 1000
        chosen, _report = dialect.choose_delimiter(text, counted)
        rows.append(
            (
                name,
                truth,
                counted,
                duck.get("Delimiter") if duck else None,
                clever.get("Delimiter") if clever else None,
                chosen,
                duck_ms,
                clever_ms,
            )
        )
    print("| file | truth | counting rule | DuckDB | CleverCSV | chosen |")
    print("|---|---|---|---|---|---|")
    for name, truth, counted, duck_d, clever_d, chosen, _d, _c in rows:
        print(f"| {name} | {truth!r} | {counted!r} | {duck_d!r} | {clever_d!r} | {chosen!r} |")
    ours = [r for r in rows if r[1] in SUPPORTED]
    reads: dict[
        str, Callable[[tuple[str, str, str, str | None, str | None, str, float, float]], str | None]
    ] = {
        "counting rule (V3)": lambda r: r[2],
        "DuckDB": lambda r: r[3],
        "CleverCSV": lambda r: r[4],
        "chosen (rule + guard)": lambda r: r[5],
    }
    print()
    print(f"Over the {len(ours)} files whose delimiter NINFA reads (of {len(rows)}):")
    for label, pick in reads.items():
        right = sum(1 for r in ours if pick(r) == r[1])
        print(f"- {label}: {right} / {len(ours)} right")
    print(
        f"- time over {len(rows)} files: DuckDB {sum(r[6] for r in rows):.0f} ms, "
        f"CleverCSV {sum(r[7] for r in rows):.0f} ms, counting rule: microseconds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

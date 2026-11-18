"""Smart Import V4: the CSV dialect reader (DuckDB primary, CleverCSV only when DuckDB is unsure).

What these tests pin, and what the measurements behind them say:

* DuckDB reads delimiter, quoting, header, column types and date format from a file held IN MEMORY
  (nothing is written to disk) and CleverCSV is consulted only for a file DuckDB leaves ambiguous;
* NINFA's importers read `;`, `,` and a tab. A sniffer that finds another delimiter REPORTS it
  (`supported` is False); it never makes the product import a file it does not support;
* a sniffer may overrule V3's counting rule only when it splits the sample clearly more
  consistently. DuckDB is sometimes wrong on a file whose text is full of the other delimiter; the
  counting rule is right there, and the guard keeps it.
"""

import pytest

duckdb = pytest.importorskip("duckdb")
fsspec = pytest.importorskip("fsspec")
pytest.importorskip("clevercsv")

from app.modules.data_sources.algorithmic import dialect  # noqa: E402
from app.modules.document_understanding.grid import detect_delimiter  # noqa: E402


def _rows(n: int = 30, cols: int = 6) -> list[list[str]]:
    return [[f"c{r}x{c}" if c else f"R{r:04d}" for c in range(cols)] for r in range(n)]


def _text(delimiter: str, table: list[list[str]], quote: str = '"') -> str:
    lines = []
    for row in table:
        cells = [
            f"{quote}{c.replace(quote, quote * 2)}{quote}" if delimiter in c or quote in c else c
            for c in row
        ]
        lines.append(delimiter.join(cells))
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("delimiter", "supported"), [(";", True), (",", True), ("\t", True), ("|", False)]
)
def test_the_delimiter_is_found_and_only_supported_ones_are_flagged_so(
    delimiter: str, supported: bool
) -> None:
    found = dialect.sniff(_text(delimiter, _rows()))

    assert found is not None
    assert found.delimiter == delimiter
    assert found.supported is supported
    assert found.columns == 6
    assert found.consistency == 1.0


def test_quoted_values_with_the_delimiter_inside_are_one_cell() -> None:
    table = [["id", "guest", "note"]] + [
        [f"B{i}", f"Rossi, Mario {i}", "vista mare, late"] for i in range(20)
    ]

    found = dialect.sniff(_text(",", table))

    assert found is not None and found.delimiter == "," and found.quote == '"'
    assert found.columns == 3


def test_the_types_and_the_date_format_are_read() -> None:
    text = "code;arrival;amount\n" + "\n".join(
        f"A{i};{(i % 27) + 1:02d}/11/2026;{i}" for i in range(20)
    )

    found = dialect.sniff(text + "\n")

    assert found is not None
    assert found.types == ("VARCHAR", "DATE", "BIGINT")
    assert found.date_format == "%d/%m/%Y"
    assert found.header is True


def test_the_order_of_the_columns_does_not_change_what_each_one_is() -> None:
    table = [["code", "arrival", "amount"]] + [
        [f"A{i}", f"2026-11-{(i % 27) + 1:02d}", str(i)] for i in range(20)
    ]
    swapped = [[row[2], row[0], row[1]] for row in table]

    first, second = dialect.sniff(_text(";", table)), dialect.sniff(_text(";", swapped))

    assert first is not None and second is not None
    assert first.types == ("VARCHAR", "DATE", "BIGINT")
    assert second.types == ("BIGINT", "VARCHAR", "DATE")


def test_a_few_malformed_rows_are_counted_and_the_delimiter_is_still_right() -> None:
    lines = _text(";", _rows(40, 5)).splitlines()
    lines[7] += ";extra"
    lines[19] = lines[19].replace("c19x2", "c19;x2")

    found = dialect.sniff("\n".join(lines) + "\n")

    assert found is not None and found.delimiter == ";"
    assert found.malformed_rows == 2


def test_clevercsv_is_the_fallback_only_for_a_file_duckdb_leaves_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real = dialect._clevercsv

    def spy(sample: str):  # type: ignore[no-untyped-def]
        calls.append("clevercsv")
        return real(sample)

    monkeypatch.setattr(dialect, "_clevercsv", spy)

    dialect.sniff(_text(";", _rows()))  # a clean file: DuckDB is enough
    assert calls == []

    lines = _text(";", _rows(40, 5)).splitlines()
    lines[7] += ";extra"
    lines[19] = lines[19].replace("c19x2", "c19;x2")
    found = dialect.sniff("\n".join(lines) + "\n")  # DuckDB reads this one as comma-separated

    assert calls == ["clevercsv"]
    assert found is not None and found.engine == "clevercsv" and found.delimiter == ";"


def test_duckdb_can_be_wrong_and_the_counting_rule_then_stands() -> None:
    table = [["id", "guest", "note", "total"]] + [
        [
            f"B{i}",
            f"Rossi, Mario {i}",
            "camera tranquilla, vista mare, late check-in, 23:00",
            f"{100 + i},50",
        ]
        for i in range(25)
    ]
    text = _text(";", table)
    counted = detect_delimiter(text.splitlines())

    seen = dialect.sniff(text)
    chosen, _report = dialect.choose_delimiter(text, counted)

    assert counted == ";"
    assert seen is not None and seen.delimiter == ","  # DuckDB's answer on this file
    assert chosen == ";"  # not taken: it splits the sample less consistently


def test_a_pipe_file_is_reported_and_never_chosen() -> None:
    text = _text("|", _rows())
    counted = detect_delimiter(text.splitlines())

    chosen, report = dialect.choose_delimiter(text, counted)

    assert report is not None and report.delimiter == "|" and not report.supported
    assert chosen == counted


def test_a_sniffer_overrules_the_counting_rule_only_when_clearly_better() -> None:
    text = _text(";", _rows())

    chosen, _ = dialect.choose_delimiter(text, ",")  # a wrong "counted" delimiter

    assert chosen == ";"


def test_nothing_is_written_to_disk_and_nothing_is_left_in_memory() -> None:
    memory = fsspec.filesystem("memory")
    before = set(memory.find("/"))

    dialect.sniff(_text(";", _rows()))

    assert set(memory.find("/")) == before


@pytest.mark.parametrize(
    "text", ["", "   \n  \n", "\x00\x01\x02" * 50, "a" * 5000, "just one line"]
)
def test_an_unreadable_file_is_no_opinion_never_an_error(text: str) -> None:
    dialect.sniff(text)  # must not raise


def test_only_a_bounded_sample_is_read() -> None:
    big = _text(";", _rows(60_000, 8))

    assert len(dialect.sample_of(big)) <= dialect.SAMPLE_CHARS
    assert dialect.sample_of(big).endswith("\n")
    assert dialect.sniff(big) is not None


def test_a_missing_reader_is_no_opinion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "duckdb", None)
    monkeypatch.setitem(__import__("sys").modules, "clevercsv", None)

    assert dialect.sniff(_text(";", _rows())) is None


# --- how the reader uses it -----------------------------------------------------------------------


def _ragged() -> str:
    """Lines that disagree on a width: the counting rule is unsure of this file."""
    return "\n".join(";".join(["a", "b", "c", "d"][: 2 + (i % 3)]) for i in range(30))


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = dialect.sniff

    def spy(text: str) -> dialect.Dialect | None:
        calls.append("sniff")
        return real(text)

    monkeypatch.setattr(dialect, "sniff", spy)
    return calls


def test_the_second_opinion_is_not_asked_when_the_first_lines_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.data_sources.algorithmic import selector
    from app.modules.document_understanding import grid

    calls = _spy(monkeypatch)

    with selector.use_engine("v4"):
        assert grid._csv_delimiter(_text(";", _rows()), None, None) == ";"

    assert calls == []  # a normal upload pays for nothing


def test_the_second_opinion_is_never_asked_with_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.data_sources.algorithmic import selector
    from app.modules.document_understanding import grid

    calls = _spy(monkeypatch)

    with selector.use_engine("v3"):
        grid._csv_delimiter(_ragged(), None, None)

    assert calls == []


def test_the_second_opinion_is_asked_when_the_counting_rule_is_unsure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.data_sources.algorithmic import selector
    from app.modules.document_understanding import grid

    calls = _spy(monkeypatch)

    with selector.use_engine("v4"):
        delimiter = grid._csv_delimiter(_ragged(), None, None)

    assert calls == ["sniff"]
    assert delimiter == ";"  # and the answer is still a supported one


def test_a_delimiter_the_file_itself_names_is_never_second_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.data_sources.algorithmic import selector
    from app.modules.document_understanding import grid

    calls = _spy(monkeypatch)

    with selector.use_engine("v4"):
        assert grid._csv_delimiter("a;b\n1;2\n", ",", None) == ","
        assert grid._csv_delimiter("a;b\n1;2\n", None, "\t") == "\t"

    assert calls == []

"""The AI readiness benchmark is an official, reproducible runner - so it is tested like one.

`python -m tests.benchmarks.smart_import_v3.ai_readiness` runs the corpus and its variants through
the real Smart Import with stand-in models and writes a JSON result and a Markdown report. These
tests run it on a handful of real documents: it ends well (exit code 0), writes both files, never
overwrites the official result from a subset, and its report renders for every set of modes - in
particular with the `no_model` reference entry, which once crashed the renderer.

No live model, no network.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.smart_import_v3 import ai_readiness
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.benchmarks.smart_import_v3.model import Doc

SUBSET = ("L12_", "BO05_", "B41_")


@pytest.fixture(scope="module")
def subset() -> list[Doc]:
    return [d for d in build_corpus() if d.id.startswith(SUBSET)]


@pytest.fixture(scope="module")
def data(subset: list[Doc]) -> dict[str, Any]:
    return ai_readiness.run_benchmark(subset, progress=lambda _message: None)


def test_every_mode_ran_on_both_populations_with_the_no_model_reference(
    data: dict[str, Any],
) -> None:
    for population in ("corpus", "variants"):
        modes = data["modes"][population]
        assert set(modes) == {*ai_readiness.MODES, "no_model"}
        assert {"questions_asked", "automatic"} <= set(modes["no_model"])
    assert data["corpus"]["documents"] == 3 and data["variants"]["documents"] == 2


def test_the_report_renders_with_the_reference_run_among_the_modes(data: dict[str, Any]) -> None:
    report = ai_readiness.markdown(data, "2026-10-26")

    assert report.startswith("# Smart Import V3 - AI readiness benchmark")
    assert "FIRST SCREEN ONLY" in report and "NOT comparable" in report
    for heading in (
        "## Safety with a model that is wrong",
        "## A wrong model: what it changes",
        "## Cost and egress",
        "## What a perfect model would be worth",
        "questions that remain on the corpus",
    ):
        assert heading in report
    assert "| no_model |" not in report  # the reference run is not a model


@pytest.mark.parametrize(
    "keep",
    [
        ("no_model", "oracle", "plausible_wrong", "wrong"),
        ("no_model", "oracle"),
        ("oracle", "wrong"),
    ],
)
def test_the_report_renders_for_any_set_of_modes(
    data: dict[str, Any], keep: tuple[str, ...]
) -> None:
    thinned = json.loads(json.dumps(data))
    for population in ("corpus", "variants"):
        thinned["modes"][population] = {
            mode: row for mode, row in thinned["modes"][population].items() if mode in keep
        }

    report = ai_readiness.markdown(thinned, "2026-10-26")

    assert "## Safety with a model that is wrong" in report


def test_the_result_says_what_it_measures_and_what_it_is_not_comparable_with(
    data: dict[str, Any],
) -> None:
    assert data["scope"].startswith("FIRST SCREEN ONLY")
    assert "NOT comparable" in data["scope"]


def test_the_stand_ins_never_cause_a_false_automation_or_a_ready_file_on_the_subset(
    data: dict[str, Any],
) -> None:
    for population in ("corpus", "variants"):
        summary = data["summary"][population]
        assert summary["ai_caused_false_automation"] == 0
        assert summary["newly_automatic"] == 0
        assert summary["raised_to_ready_by_a_wrong_model"] == 0
        assert summary["oracle_raised_to_ready"] == 0
        assert summary["model_payload_violations"] == 0


def test_main_exits_zero_and_writes_the_json_and_the_markdown(tmp_path: Path) -> None:
    json_path, markdown_path = tmp_path / "result.json", tmp_path / "report.md"

    code = ai_readiness.main(
        [
            "--only",
            "L12_",
            "--only",
            "BO05_",
            "--json",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )

    assert code == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["benchmark"] == (
        "smart-import-v3-ai-readiness-v1"
    )
    assert markdown_path.read_text(encoding="utf-8").startswith("# Smart Import V3 - AI readiness")
    assert "\r" not in markdown_path.read_text(encoding="utf-8")  # LF on every platform


def test_a_subset_never_overwrites_the_official_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    official_json, official_markdown = tmp_path / "official.json", tmp_path / "official.md"
    monkeypatch.setattr(ai_readiness, "DEFAULT_JSON", official_json)
    monkeypatch.setattr(ai_readiness, "DEFAULT_MD", official_markdown)

    code = ai_readiness.main(["--only", "L12_"])

    assert code == 0 and not official_json.exists() and not official_markdown.exists()

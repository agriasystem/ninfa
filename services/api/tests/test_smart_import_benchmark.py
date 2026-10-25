"""The Smart Import intelligence benchmark checks ITSELF here - not Smart Import.

Nothing in this file asserts how well Smart Import performs (that is a measurement, reported by
`python -m tests.benchmarks.smart_import_v3`, not a gate). It asserts that the corpus is what the
benchmark says it is, that its truth matches its files, and that the scorer reaches the verdicts it
is meant to reach on hand-made observations.
"""

from typing import Any

import pytest

from tests.benchmarks.smart_import_v3.corpus import (
    build_corpus,
    corpus_hash,
    manifest,
    summary,
    validate,
)
from tests.benchmarks.smart_import_v3.driver import evaluate
from tests.benchmarks.smart_import_v3.match import header_matches
from tests.benchmarks.smart_import_v3.model import (
    Golden,
    Source,
    column,
    golden_from_json,
    golden_to_json,
)
from tests.benchmarks.smart_import_v3.observe import (
    Observed,
    OClaim,
    OColumn,
    OQuestion,
    make_service,
)
from tests.benchmarks.smart_import_v3.runner import run_benchmark
from tests.benchmarks.smart_import_v3.score import score_case


@pytest.fixture(scope="module")
def docs() -> list[Any]:
    return build_corpus()


# --- the corpus --------------------------------------------------------------------------------


def test_the_corpus_is_as_large_and_varied_as_promised(docs: list[Any]) -> None:
    counts = summary(docs)
    assert counts["documents"] >= 120
    for card in ("Personale", "Prenotazioni", "Costi"):
        assert counts["by_card"][card] >= 40
    assert counts["office_realistic"] >= 50
    assert counts["negative_refusals"] >= 15
    assert counts["adversarial"] >= 10
    assert counts["with_personal_data"] >= 30
    assert counts["multi_sheet"] >= 10
    assert counts["xlsx"] > 0 and counts["csv"] > 0
    assert counts["distinct_structures"] >= 25


def test_every_document_has_a_unique_id_and_a_valid_truth(docs: list[Any]) -> None:
    assert len({d.id for d in docs}) == len(docs)
    for doc in docs:
        assert doc.golden.outcome in {"READY", "ASK", "REJECT", "NOT_AUTOMATIC", "WARN"}
        assert doc.card in {"labor", "bookings", "costs"}
        if doc.golden.outcome == "ASK":
            assert doc.golden.questions, doc.id


def test_the_truth_matches_the_files_it_describes(docs: list[Any]) -> None:
    # reopens every file with openpyxl / csv - never with Smart Import's readers
    assert validate(docs) == []


def test_the_corpus_is_deterministic(docs: list[Any]) -> None:
    assert corpus_hash(build_corpus()) == corpus_hash(docs)


def test_the_truth_survives_a_round_trip_through_json(docs: list[Any]) -> None:
    for doc in docs:
        assert golden_from_json(golden_to_json(doc.golden)) == doc.golden, doc.id
    assert len(manifest(docs)) == len(docs)


def test_personal_values_are_synthetic(docs: list[Any]) -> None:
    for doc in docs:
        for value in doc.golden.pii_values:
            if "@" in value:
                assert value.endswith("@example.org"), doc.id
            if value.startswith("+39"):
                assert " 000" in value, doc.id


# --- the scorer --------------------------------------------------------------------------------


def _entry(doc_id: str = "X01") -> dict[str, Any]:
    return {"id": doc_id, "card": "labor", "filename": "x.xlsx", "tags": [], "sheets": 1}


def _labor_golden(**overrides: Any) -> Golden:
    base: dict[str, Any] = {
        "domain": "labor",
        "outcome": "READY",
        "sheets": ("Turni",),
        "header_rows": (1,),
        "first_row": 2,
        "data_rows": 5,
        "fields": {
            "work_date": column("Data"),
            "department": column("Reparto"),
            "planned_hours": column("Ore previste"),
        },
        "pii_columns": (("Dipendente",),),
        "pii_values": ("Giulia Ferretti",),
    }
    base.update(overrides)
    return Golden(**base)


def _columns() -> list[OColumn]:
    return [
        OColumn(0, "Data", "work_date", "RECOGNIZED", None, ()),
        OColumn(1, "Dipendente", None, None, "PERSON", ()),
        OColumn(2, "Reparto", "role", "RECOGNIZED", None, ()),
        OColumn(3, "Ore previste", "planned_hours", "RECOGNIZED", None, ()),
    ]


def _perfect() -> Observed:
    return Observed(
        level="READY",
        detection_domain="LABOR",
        detection_level="HIGH",
        header_rows=(1,),
        first_row=2,
        last_row=6,
        data_rows=5,
        table_sheets=("Turni",),
        columns=_columns(),
        claims=[
            OClaim("work_date", "COLUMN", "Data", "HIGH"),
            OClaim("role", "COLUMN", "Reparto", "HIGH"),
            OClaim("planned_hours", "COLUMN", "Ore previste", "HIGH"),
        ],
        payload="{}",
    )


def test_a_perfect_reading_has_no_findings() -> None:
    result = score_case(_entry(), _labor_golden(), _perfect())
    assert result.findings == []
    assert result.automatic and result.fully_correct and not result.false_automation
    assert result.required.correct == 3 and result.required.wrong == 0


def test_an_automatic_reading_with_a_wrong_hours_column_is_a_false_automation() -> None:
    observed = _perfect()
    observed.claims[2] = OClaim("actual_hours", "COLUMN", "Ore previste", "HIGH")
    result = score_case(_entry(), _labor_golden(absent=("actual_hours",)), observed)
    assert result.false_automation
    categories = {f.category for f in result.findings}
    assert {"FIELD_WRONG", "FIELD_MISSED", "FALSE_ZERO_QUESTION"} <= categories
    assert all(f.severity == "P0" for f in result.findings if f.category == "FALSE_ZERO_QUESTION")


def test_a_missed_required_field_while_automatic_is_a_false_automation() -> None:
    observed = _perfect()
    del observed.claims[2]
    result = score_case(_entry(), _labor_golden(), observed)
    assert result.false_automation
    assert "planned_hours missed" in result.false_automation_reasons


def test_a_table_that_ends_early_is_a_boundary_error_and_severe() -> None:
    observed = _perfect()
    observed.data_rows = 2
    result = score_case(_entry(), _labor_golden(), observed)
    boundary = [f for f in result.findings if f.category == "TABLE_BOUNDARY_WRONG"]
    assert boundary and boundary[0].severity == "P0"
    assert result.false_automation


def test_going_automatic_on_a_document_to_refuse_is_an_unsafe_import() -> None:
    golden = _labor_golden(outcome="REJECT", blockers=("MISSING_REQUIRED",))
    result = score_case(_entry(), golden, _perfect())
    assert any(f.category == "UNSAFE_IMPORT" for f in result.findings)
    assert result.safe_fallback is False


def test_refusing_a_document_to_refuse_is_a_safe_fallback() -> None:
    observed = _perfect()
    observed.level = "BLOCKED"
    observed.blockers = [("MISSING_REQUIRED", ())]
    golden = _labor_golden(outcome="REJECT", blockers=("MISSING_REQUIRED",))
    result = score_case(_entry(), golden, observed)
    assert result.safe_fallback is True and result.strict_fallback is True
    assert not any(f.category == "UNSAFE_IMPORT" for f in result.findings)


def test_a_question_the_truth_does_not_need_is_unnecessary_but_not_a_false_automation() -> None:
    observed = _perfect()
    observed.level = "ASK"
    observed.questions = [OQuestion("COLUMN_MEANING", "Ore previste", None, None, None, (), ())]
    result = score_case(_entry(), _labor_golden(), observed)
    assert [f.category for f in result.findings] == ["QUESTION_UNNECESSARY"]
    assert not result.false_automation and not result.automatic
    assert result.questions_unnecessary == 1


def test_a_tolerated_question_is_not_unnecessary() -> None:
    observed = _perfect()
    observed.level = "ASK"
    observed.questions = [
        OQuestion("DEPARTMENT_CONFIRM", None, "role", None, "FRONT_OFFICE", (), ())
    ]
    golden = _labor_golden(tolerated=("DEPARTMENT_CONFIRM",))
    assert score_case(_entry(), golden, observed).questions_unnecessary == 0


def test_a_missing_necessary_question_is_reported() -> None:
    golden = _labor_golden(outcome="ASK", questions=("GRID_HOURS",))
    result = score_case(_entry(), golden, _perfect())
    categories = {f.category for f in result.findings}
    assert {"QUESTION_MISSING", "FALSE_ZERO_QUESTION"} <= categories
    assert result.questions_necessary_found == 0


def test_a_personal_column_that_becomes_a_field_is_a_leak() -> None:
    observed = _perfect()
    observed.columns[1] = OColumn(1, "Dipendente", "role", "TO_CHECK", None, ())
    observed.claims.append(OClaim("role", "COLUMN", "Dipendente", "MEDIUM"))
    result = score_case(_entry(), _labor_golden(), observed)
    assert result.pii_columns_excluded == 0
    assert any(f.category == "PII_LEAK" and f.severity == "P0" for f in result.findings)


def test_a_personal_value_in_the_browser_payload_is_a_leak() -> None:
    observed = _perfect()
    observed.payload = '{"examples": ["Giulia Ferretti"]}'
    result = score_case(_entry(), _labor_golden(), observed)
    assert result.pii_values_leaked == 1
    assert any(f.category == "PII_LEAK" for f in result.findings)


def test_deciding_an_ambiguous_field_without_asking_is_a_guess() -> None:
    golden = _labor_golden(ambiguous=("actual_hours",))
    observed = _perfect()
    observed.claims.append(OClaim("actual_hours", "COLUMN", "Ore previste", "HIGH"))
    result = score_case(_entry(), golden, observed)
    assert "actual_hours guessed" in result.false_automation_reasons


def test_a_warning_is_enough_for_a_document_that_contradicts_itself() -> None:
    golden = _labor_golden(outcome="WARN")
    shown = _perfect()
    shown.totals_state = "MISMATCH"
    assert not score_case(_entry(), golden, shown).false_automation
    hidden = score_case(_entry(), golden, _perfect())
    assert hidden.false_automation
    assert any(f.category == "UNSAFE_IMPORT" for f in hidden.findings)


def test_the_period_of_a_day_grid_is_read_from_the_dates_the_importer_would_find() -> None:
    golden = _labor_golden(
        fields={"work_date": Source("GRID"), "department": column("Reparto")},
        period_start="2026-10-19",
    )
    observed = _perfect()
    observed.day_grid = True
    observed.virtual_dates = ("2026-10-19", "2026-10-20")
    assert score_case(_entry(), golden, observed).period_ok is True
    observed.virtual_dates = ("2026-10-26", "2026-10-27")
    wrong = score_case(_entry(), golden, observed)
    assert wrong.period_ok is False and wrong.false_automation


@pytest.mark.parametrize(
    ("parts", "observed", "expected"),
    [
        (("Reparto",), "reparto", True),
        (("Re​parto",), "Reparto", True),  # zero-width space
        (("Ore", "Previste"), "Ore - Previste", True),  # two levels joined
        (("Ore", "Previste"), "Previste", True),  # lower level alone
        (("Ore",), "Ore (2)", True),  # a repeated header, renamed
        (("Ore prog.",), "Ore previste", False),
        (("Data\n(gg/mm/aaaa)",), "Data (gg/mm/aaaa)", True),
    ],
)
def test_header_matching(parts: tuple[str, ...], observed: str, expected: bool) -> None:
    assert header_matches(parts, observed) is expected


# --- the run -----------------------------------------------------------------------------------


def test_a_small_run_works_end_to_end_without_an_assistant(docs: list[Any]) -> None:
    assert make_service()._resolver is None  # the optional assistant is off
    sample = [d for d in docs if d.id.startswith(("L01_", "B01_", "C01_"))]
    assert len(sample) == 3
    run = run_benchmark(sample, repeats=1, memory=False, probes=False, progress=lambda _: None)
    data = evaluate(run)
    assert data["metrics"]["total"]["documents"] == 3
    assert all(case["error"] is None for case in data["cases"])
    assert set(data["metrics"]) == {"total", "Personale", "Prenotazioni", "Costi"}

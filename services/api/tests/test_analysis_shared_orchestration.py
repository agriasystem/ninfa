"""Gate 25B: the shared analysis orchestration (`app/modules/analysis`) and the proof that the
operator CLI, now a thin adapter over it, prints the SAME output and keeps the SAME exit semantics.

The CLI output assertions pin the exact line shapes of Gates 21B-23B (booking-only run, skipped
cost/labor, idempotent replay, provenance, coverage); the shared-function tests prove the typed
result carries what the CLI prints and that the CLI and the shared function agree run-for-run.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.cli._support import run_cli
from app.cli.analysis import run_analysis
from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.analysis import AnalysisInputError, AnalysisRunRequest, run_property_analysis
from app.modules.decisions.coverage import CoverageSummary
from tests.test_pilot_analysis_cli import _bootstrap_with_bookings

_SNAPSHOT = re.compile(
    r"^  \[1/6\] observed snapshots: snapshot_local_date=\d{4}-\d{2}-\d{2} "
    r"created=\d+ unchanged=\d+$"
)
_EXPECTED = re.compile(
    r"^  \[2/6\] expected baselines: created=\d+ unchanged=\d+ ready=\d+ insufficient=\d+$"
)
_COMPLETE = re.compile(
    r"^Analysis complete: as_of_local_date=\d{4}-\d{2}-\d{2} evaluations=\d+ triggered=\d+ "
    r"clear=\d+ insufficient_data=\d+ not_applicable=\d+ suppressed=\d+ "
    r"decision_run_id=[0-9a-f-]{36} is_idempotent_replay=(True|False) decisions_created=\d+ "
    r"decisions_resolved=\d+ decisions_reopened=\d+ open_decisions_after_sync=\d+ "
    r"coverage=\w+ skipped_domains=\[.*\]$"
)


def _run(db_session: Session, slug: str, source: object, day: date, **extra: object) -> int:
    return run_analysis(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        booking_data_source_id=source,  # type: ignore[arg-type]
        stay_date_start=day,
        stay_date_end=day,
        labor_data_source_id=extra.get("labor"),  # type: ignore[arg-type]
        cost_year=extra.get("year"),  # type: ignore[arg-type]
        cost_month=extra.get("month"),  # type: ignore[arg-type]
        currency=None,
    )


def test_01_booking_only_cli_output_keeps_its_exact_line_shapes(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day = date.today() + timedelta(days=14)
    _, _, source = _bootstrap_with_bookings(db_session, "shared-01", tmp_path, stay_dates=[day])
    capsys.readouterr()

    assert _run(db_session, "shared-01", source, day) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Analysis run: workspace=shared-01 property=shared-01"
    assert _SNAPSHOT.match(lines[1])
    assert _EXPECTED.match(lines[2])
    assert re.fullmatch(r"  \[3/6\] revenue signals: targets=1", lines[3])
    assert re.fullmatch(r"  \[4/6\] ota dependency: status=\w+", lines[4])
    assert lines[5] == "  [5/6] cost cpor anomaly: skipped (no --cost-year/--cost-month given)"
    assert lines[6] == "  [6/6] labor overstaffing: skipped (no --labor-data-source-id given)"
    assert lines[7] == (
        f"  [provenance] bookings: data_source_id={source} "
        f"last_successful_import_finished_at={lines[7].split('finished_at=')[1]}"
    )
    assert "None" not in lines[7]  # the bootstrap import succeeded: provenance is KNOWN
    assert _COMPLETE.match(lines[8])
    assert lines[8].endswith("coverage=PARTIAL skipped_domains=['COSTS', 'LABOR']")
    assert len(lines) == 9


def test_02_cost_and_labor_lines_keep_their_included_shape(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day = date.today() + timedelta(days=14)
    _, _, source = _bootstrap_with_bookings(db_session, "shared-02", tmp_path, stay_dates=[day])
    capsys.readouterr()

    assert _run(db_session, "shared-02", source, day, year=2026, month=9) == 0
    out = capsys.readouterr().out
    assert re.search(
        r"^  \[5/6\] cost cpor anomaly: year=2026 month=9 currency=EUR categories=\d+$",
        out,
        re.MULTILINE,
    )
    assert "  [6/6] labor overstaffing: skipped (no --labor-data-source-id given)" in out
    assert "skipped_domains=['LABOR']" in out


def test_03_an_idempotent_rerun_keeps_its_replay_output(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day = date.today() + timedelta(days=14)
    _, _, source = _bootstrap_with_bookings(db_session, "shared-03", tmp_path, stay_dates=[day])
    capsys.readouterr()
    assert _run(db_session, "shared-03", source, day) == 0
    first = capsys.readouterr().out.splitlines()[-1]
    assert _run(db_session, "shared-03", source, day) == 0
    second = capsys.readouterr().out.splitlines()[-1]

    run_id = re.search(r"decision_run_id=(\S+)", first)
    assert run_id is not None
    replay = f"decision_run_id={run_id.group(1)} is_idempotent_replay=True decisions_created=0"
    assert replay in second


def test_04_the_shared_function_returns_what_the_cli_prints(
    db_session: Session, tmp_path: Path
) -> None:
    day = date.today() + timedelta(days=14)
    tenant, prop, source = _bootstrap_with_bookings(
        db_session, "shared-04", tmp_path, stay_dates=[day]
    )

    result = run_property_analysis(
        db_session,
        AnalysisRunRequest(
            workspace_id=tenant.workspace_id,
            property_id=prop.id,
            booking_data_source_id=source,
            stay_date_start=day,
            stay_date_end=day,
        ),
    )

    assert result.property_id == prop.id
    assert result.as_of_local_date is not None
    assert result.is_idempotent_replay is False
    assert result.coverage.summary is CoverageSummary.PARTIAL
    assert result.cost_category_count is None and result.labor_evaluation_count is None
    assert result.provenance.bookings.data_source_id == source
    assert result.provenance.bookings.import_job_id is not None
    assert result.evaluation_count == (
        result.triggered_count
        + result.clear_count
        + result.insufficient_count
        + result.not_applicable_count
        + result.suppressed_count
    )

    again = run_property_analysis(
        db_session,
        AnalysisRunRequest(tenant.workspace_id, prop.id, source, day, day),
    )
    assert again.is_idempotent_replay is True
    assert again.decision_run_id == result.decision_run_id


def test_05_an_inconsistent_cost_pair_is_one_typed_error_and_the_cli_maps_it_to_exit_1(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    day = date.today() + timedelta(days=14)
    _, _, source = _bootstrap_with_bookings(db_session, "shared-05", tmp_path, stay_dates=[day])
    capsys.readouterr()

    with pytest.raises(AnalysisInputError):
        _run(db_session, "shared-05", source, day, year=2026)

    # The CLI's own error mapping (`run_cli`, unchanged since Gate 21B) turns it into the usual
    # single `Error:` line and exit code 1.
    assert run_cli(lambda: _run(db_session, "shared-05", source, day, month=9)) == 1
    assert (
        capsys.readouterr().err.strip() == "Error: cost_year and cost_month must be given together"
    )


def test_06_unknown_property_is_a_not_found_error_from_the_shared_function(
    db_session: Session,
) -> None:
    with pytest.raises(NotFoundError):
        run_property_analysis(
            db_session,
            AnalysisRunRequest(
                workspace_id=TenantContext(workspace_id=uuid4()).workspace_id,
                property_id=uuid4(),
                booking_data_source_id=uuid4(),
                stay_date_start=date.today(),
                stay_date_end=date.today(),
            ),
        )

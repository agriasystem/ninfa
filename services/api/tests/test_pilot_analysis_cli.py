"""Gate 21B: `app/cli/analysis.py` is the ONE production entrypoint that composes Expected
calculation, all four detectors, priority ranking and decision persistence for one property -
closing the Gate 21A finding that this composition existed nowhere outside tests.

`test_01` is the END-TO-END PILOT ACCEPTANCE SCENARIO the Gate 21B spec asks for: it goes
bootstrap -> import -> analysis using ONLY the real `app/cli/*` entry points (never a test
factory for the business data itself) and asserts the result is readable through the SAME
`DecisionMemoryService.get_feed()` the real Oggi API route reads.
"""

from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.cli.analysis import run_analysis
from app.cli.imports import run_import_bookings
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.exceptions import AppError, NotFoundError
from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import WorkspaceRepository
from tests.pilot_support import booking_csv


def _bootstrap_with_bookings(
    db_session: Session, slug: str, tmp_path: Path, *, stay_dates: list[date]
) -> tuple[TenantContext, Property, UUID]:
    run_create_workspace(db_session, name="Hotel Aurora", slug=slug)
    run_create_property(
        db_session,
        workspace_slug=slug,
        name="Hotel Aurora",
        slug=slug,
        timezone="Europe/Rome",
        currency="EUR",
    )
    workspace = WorkspaceRepository(db_session).get_by_slug(slug)
    assert workspace is not None
    tenant = TenantContext(workspace_id=workspace.id)
    prop = PropertyRepository(db_session, tenant).get_by_slug(slug)
    assert prop is not None

    run_create_data_source(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        domain=DataSourceDomain.BOOKINGS,
        name="Bookings",
    )
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]

    file = booking_csv(tmp_path, stay_dates=stay_dates)
    exit_code = run_import_bookings(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        data_source_id=data_source.id,
        file=file,
    )
    assert exit_code == 0
    return tenant, prop, data_source.id


def test_01_end_to_end_pilot_acceptance_reaches_persisted_decision_state(
    db_session: Session, tmp_path: Path
) -> None:
    stay_dates = [date.today() + timedelta(days=14), date.today() + timedelta(days=15)]
    tenant, prop, data_source_id = _bootstrap_with_bookings(
        db_session, "aurora-analysis-01", tmp_path, stay_dates=stay_dates
    )

    feed_before = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed_before.state == FeedState.NOT_PROCESSED
    assert feed_before.run is None

    exit_code = run_analysis(
        db_session,
        workspace_slug="aurora-analysis-01",
        property_slug="aurora-analysis-01",
        booking_data_source_id=data_source_id,
        stay_date_start=min(stay_dates),
        stay_date_end=max(stay_dates),
        labor_data_source_id=None,
        cost_year=None,
        cost_month=None,
        currency=None,
    )
    assert exit_code == 0

    feed_after = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed_after.state != FeedState.NOT_PROCESSED
    assert feed_after.run is not None
    # Cold start (one file, no history yet): every detector legitimately reports
    # INSUFFICIENT_DATA, never a fabricated trigger - see the module's "Cold Start" contract.
    assert feed_after.run.insufficient_count > 0
    assert feed_after.run.triggered_count == 0


def test_02_unknown_property_rejected(db_session: Session) -> None:
    run_create_workspace(db_session, name="Hotel Aurora", slug="aurora-analysis-02")
    with pytest.raises(NotFoundError):
        run_analysis(
            db_session,
            workspace_slug="aurora-analysis-02",
            property_slug="does-not-exist",
            booking_data_source_id=uuid4(),
            stay_date_start=date.today(),
            stay_date_end=date.today() + timedelta(days=1),
            labor_data_source_id=None,
            cost_year=None,
            cost_month=None,
            currency=None,
        )


def test_03_idempotent_rerun_is_a_replay_and_creates_nothing_new(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stay_dates = [date.today() + timedelta(days=20)]
    tenant, prop, data_source_id = _bootstrap_with_bookings(
        db_session, "aurora-analysis-03", tmp_path, stay_dates=stay_dates
    )

    def run_once() -> int:
        return run_analysis(
            db_session,
            workspace_slug="aurora-analysis-03",
            property_slug="aurora-analysis-03",
            booking_data_source_id=data_source_id,
            stay_date_start=stay_dates[0],
            stay_date_end=stay_dates[0],
            labor_data_source_id=None,
            cost_year=None,
            cost_month=None,
            currency=None,
        )

    assert run_once() == 0
    first_out = capsys.readouterr().out
    assert "is_idempotent_replay=False" in first_out

    assert run_once() == 0
    second_out = capsys.readouterr().out
    assert "is_idempotent_replay=True" in second_out
    assert "decisions_created=0" in second_out


def test_04_labor_evaluation_failure_never_persists_a_false_all_clear(
    db_session: Session, tmp_path: Path
) -> None:
    """Simulate a real mid-pipeline crash (a labor data source of the WRONG domain) and prove
    the Gate 21A false-all-clear gap is closed: DecisionService.sync() must never be reached,
    so the Oggi feed must stay NOT_PROCESSED - never silently become an all-clear state."""
    stay_dates = [date.today() + timedelta(days=21)]
    tenant, prop, data_source_id = _bootstrap_with_bookings(
        db_session, "aurora-analysis-04", tmp_path, stay_dates=stay_dates
    )
    run_create_data_source(
        db_session,
        workspace_slug="aurora-analysis-04",
        property_slug="aurora-analysis-04",
        domain=DataSourceDomain.COSTS,  # deliberately the WRONG domain for a labor source
        name="Wrong domain source",
    )
    wrong_domain_source = [
        source
        for source in DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)
        if source.domain == DataSourceDomain.COSTS
    ][0]

    with pytest.raises(AppError):
        run_analysis(
            db_session,
            workspace_slug="aurora-analysis-04",
            property_slug="aurora-analysis-04",
            booking_data_source_id=data_source_id,
            stay_date_start=stay_dates[0],
            stay_date_end=stay_dates[0],
            labor_data_source_id=wrong_domain_source.id,
            cost_year=None,
            cost_month=None,
            currency=None,
        )

    feed = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed.state == FeedState.NOT_PROCESSED
    assert feed.run is None


def test_05_cost_and_labor_flags_degrade_gracefully_with_no_history(
    db_session: Session, tmp_path: Path
) -> None:
    """Cold start must never crash: with a real (correctly-domained) labor source and an
    explicit target month but zero labor/cost history, every extra evaluation legitimately
    resolves to INSUFFICIENT_DATA/NOT_APPLICABLE rather than raising."""
    stay_dates = [date.today() + timedelta(days=22)]
    tenant, prop, data_source_id = _bootstrap_with_bookings(
        db_session, "aurora-analysis-05", tmp_path, stay_dates=stay_dates
    )
    run_create_data_source(
        db_session,
        workspace_slug="aurora-analysis-05",
        property_slug="aurora-analysis-05",
        domain=DataSourceDomain.LABOR,
        name="Labor",
    )
    labor_source = [
        source
        for source in DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)
        if source.domain == DataSourceDomain.LABOR
    ][0]

    today = date.today()
    exit_code = run_analysis(
        db_session,
        workspace_slug="aurora-analysis-05",
        property_slug="aurora-analysis-05",
        booking_data_source_id=data_source_id,
        stay_date_start=stay_dates[0],
        stay_date_end=stay_dates[0],
        labor_data_source_id=labor_source.id,
        cost_year=today.year,
        cost_month=today.month,
        currency=None,
    )
    assert exit_code == 0
    feed = DecisionMemoryService(db_session, tenant).get_feed(prop.id, today)
    assert feed.state != FeedState.NOT_PROCESSED
    assert feed.run is not None
    assert feed.run.triggered_count == 0

"""Gate 23B: `app/cli/analysis.py`'s booking provenance resolution - the ONE production caller
that must resolve the latest SUCCEEDED `ImportJob` for the EXACT `booking_data_source_id` it was
given, and persist it with the run. Coverage/orchestration itself is `test_pilot_analysis_cli.py`'s
own concern; this file is additive to it.
"""

from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.cli.analysis import run_analysis
from app.cli.imports import run_import_bookings
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import WorkspaceRepository
from tests.pilot_support import booking_csv


def _bootstrap(db_session: Session, slug: str) -> tuple[TenantContext, Property]:
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
    return tenant, prop


def _booking_source(
    db_session: Session, tenant: TenantContext, prop: Property, slug: str, *, name: str
) -> UUID:
    run_create_data_source(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        domain=DataSourceDomain.BOOKINGS,
        name=name,
    )
    sources = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)
    return [s for s in sources if s.name == name][0].id


def _import_bookings(
    db_session: Session, slug: str, tmp_path: Path, data_source_id: UUID, *, filename: str
) -> None:
    stay_dates = [date.today() + timedelta(days=30)]
    file = booking_csv(tmp_path, stay_dates=stay_dates, filename=filename)
    exit_code = run_import_bookings(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        data_source_id=data_source_id,
        file=file,
    )
    assert exit_code == 0


def test_01_the_production_cli_resolves_and_persists_the_exact_sources_own_provenance(
    db_session: Session, tmp_path: Path
) -> None:
    """Mandatory per the gate's own spec: booking_data_source_id X -> latest SUCCEEDED import for
    X resolved -> provenance passed to DecisionService -> persisted on the run."""
    slug = "aurora-provenance-01"
    tenant, prop = _bootstrap(db_session, slug)
    source_id = _booking_source(db_session, tenant, prop, slug, name="Bookings")
    _import_bookings(db_session, slug, tmp_path, source_id, filename="bookings.csv")

    expected_import = ImportJobRepository(db_session, tenant).latest_succeeded_for_data_source(
        source_id
    )
    assert expected_import is not None

    stay_dates = [date.today() + timedelta(days=30)]
    exit_code = run_analysis(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        booking_data_source_id=source_id,
        stay_date_start=min(stay_dates),
        stay_date_end=max(stay_dates),
        labor_data_source_id=None,
        cost_year=None,
        cost_month=None,
        currency=None,
    )
    assert exit_code == 0

    feed = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed.run is not None
    assert feed.run.input_provenance is not None
    provenance = RunInputProvenance.from_json(feed.run.input_provenance)
    assert provenance.bookings.data_source_id == source_id
    assert provenance.bookings.import_job_id == expected_import.id
    assert provenance.bookings.last_successful_import_finished_at == expected_import.finished_at


def test_02_multi_source_run_persists_the_used_sources_own_provenance_not_the_other_sources(
    db_session: Session, tmp_path: Path
) -> None:
    """Mandatory per the gate's own spec: source A imported first (older), source B imported
    second (newer) - a run explicitly using A must persist A's OWN (older) provenance, never B's
    newer timestamp, proving no property-wide/domain-wide MAX is ever used."""
    slug = "aurora-provenance-02"
    tenant, prop = _bootstrap(db_session, slug)
    source_a = _booking_source(db_session, tenant, prop, slug, name="Source A")
    _import_bookings(db_session, slug, tmp_path, source_a, filename="a.csv")

    source_b = _booking_source(db_session, tenant, prop, slug, name="Source B")
    _import_bookings(db_session, slug, tmp_path, source_b, filename="b.csv")

    import_a = ImportJobRepository(db_session, tenant).latest_succeeded_for_data_source(source_a)
    import_b = ImportJobRepository(db_session, tenant).latest_succeeded_for_data_source(source_b)
    assert import_a is not None and import_b is not None
    assert import_a.finished_at is not None and import_b.finished_at is not None
    # B was imported strictly after A (real wall-clock import calls, one after the other).
    assert import_b.finished_at >= import_a.finished_at

    stay_dates = [date.today() + timedelta(days=30)]
    exit_code = run_analysis(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        booking_data_source_id=source_a,  # explicitly the OLDER source
        stay_date_start=min(stay_dates),
        stay_date_end=max(stay_dates),
        labor_data_source_id=None,
        cost_year=None,
        cost_month=None,
        currency=None,
    )
    assert exit_code == 0

    feed = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed.run is not None
    assert feed.run.input_provenance is not None
    provenance = RunInputProvenance.from_json(feed.run.input_provenance)
    assert provenance.bookings.data_source_id == source_a
    assert provenance.bookings.import_job_id == import_a.id
    assert provenance.bookings.last_successful_import_finished_at == import_a.finished_at
    # the critical negative assertion: B's own (newer) timestamp must never leak into A's run
    assert provenance.bookings.last_successful_import_finished_at != import_b.finished_at


def test_03_no_successful_import_yet_persists_unknown_freshness_not_a_crash(
    db_session: Session, tmp_path: Path
) -> None:
    """A booking data source that exists but has never had a successful import: the run must
    still succeed (cold start is a legitimate state everywhere else in this pipeline), and the
    persisted provenance must report UNKNOWN freshness, never a fabricated timestamp."""
    slug = "aurora-provenance-03"
    tenant, prop = _bootstrap(db_session, slug)
    source_id = _booking_source(db_session, tenant, prop, slug, name="Bookings")
    # Deliberately no import at all for this source: ObservedSnapshotService.take_snapshot still
    # succeeds with zero bookings (a pre-existing, unrelated cold-start behaviour).

    stay_dates = [date.today() + timedelta(days=30)]
    exit_code = run_analysis(
        db_session,
        workspace_slug=slug,
        property_slug=slug,
        booking_data_source_id=source_id,
        stay_date_start=min(stay_dates),
        stay_date_end=max(stay_dates),
        labor_data_source_id=None,
        cost_year=None,
        cost_month=None,
        currency=None,
    )
    assert exit_code == 0

    feed = DecisionMemoryService(db_session, tenant).get_feed(prop.id, date.today())
    assert feed.run is not None
    assert feed.run.input_provenance is not None
    provenance = RunInputProvenance.from_json(feed.run.input_provenance)
    assert provenance.bookings.data_source_id == source_id
    assert provenance.bookings.import_job_id is None
    assert provenance.bookings.last_successful_import_finished_at is None

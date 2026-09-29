"""Gate 21B: the data import CLI (`app/cli/imports.py`) is the ONLY supported way to load real
booking/labor/invoice files - these tests hand it REAL files on disk (see `tests/pilot_support.py`)
and read the outcome back through the same production repositories a real caller would use.
"""

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.cli.imports import run_import_bookings, run_import_invoices, run_import_labor
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.bookings.repository import BookingRepository
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.invoices.repository import InvoiceRepository
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import WorkspaceRepository
from tests.invoice_support import fattura_xml
from tests.pilot_support import booking_csv, labor_csv, malformed_booking_csv


def _bootstrap(db_session: Session, slug: str) -> tuple[TenantContext, PropertyRepository]:
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
    return tenant, PropertyRepository(db_session, tenant)


def test_01_booking_import_happy_path(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, properties = _bootstrap(db_session, "aurora-import-01")
    prop = properties.get_by_slug("aurora-import-01")
    assert prop is not None
    run_create_data_source(
        db_session,
        workspace_slug="aurora-import-01",
        property_slug="aurora-import-01",
        domain=DataSourceDomain.BOOKINGS,
        name="Bookings",
    )
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]

    stay_dates = [date.today() + timedelta(days=14), date.today() + timedelta(days=15)]
    file = booking_csv(tmp_path, stay_dates=stay_dates)

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-import-01",
        property_slug="aurora-import-01",
        data_source_id=data_source.id,
        file=file,
    )
    assert exit_code == 0
    assert "status=SUCCEEDED" in capsys.readouterr().out

    bookings = BookingRepository(db_session, tenant).list_for_property(prop.id)
    assert len(bookings) == 2
    assert {b.source_record_id for b in bookings} == {"PILOT-0001", "PILOT-0002"}


def test_02_booking_import_malformed_file_fails_closed_and_imports_nothing(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, properties = _bootstrap(db_session, "aurora-import-02")
    prop = properties.get_by_slug("aurora-import-02")
    assert prop is not None
    run_create_data_source(
        db_session,
        workspace_slug="aurora-import-02",
        property_slug="aurora-import-02",
        domain=DataSourceDomain.BOOKINGS,
        name="Bookings",
    )
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]

    file = malformed_booking_csv(tmp_path)
    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-import-02",
        property_slug="aurora-import-02",
        data_source_id=data_source.id,
        file=file,
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "status=FAILED" in out
    assert "error_code=BOOKING_VALIDATION_FAILED" in out
    assert BookingRepository(db_session, tenant).list_for_property(prop.id) == []


def test_03_booking_import_unknown_data_source_raises(db_session: Session, tmp_path: Path) -> None:
    _bootstrap(db_session, "aurora-import-03")
    file = booking_csv(tmp_path, stay_dates=[date.today() + timedelta(days=10)])
    with pytest.raises(AppError):
        run_import_bookings(
            db_session,
            workspace_slug="aurora-import-03",
            property_slug="aurora-import-03",
            data_source_id=uuid4(),
            file=file,
        )


def test_04_labor_import_happy_path(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, properties = _bootstrap(db_session, "aurora-import-04")
    prop = properties.get_by_slug("aurora-import-04")
    assert prop is not None
    run_create_data_source(
        db_session,
        workspace_slug="aurora-import-04",
        property_slug="aurora-import-04",
        domain=DataSourceDomain.LABOR,
        name="Labor",
    )
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]

    work_date = date.today() + timedelta(days=14)
    file = labor_csv(tmp_path, work_dates=[work_date])

    exit_code = run_import_labor(
        db_session,
        workspace_slug="aurora-import-04",
        property_slug="aurora-import-04",
        data_source_id=data_source.id,
        file=file,
        snapshot_local_date=date.today(),
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "status=SUCCEEDED" in out
    assert "entries_created=1" in out


def test_05_invoice_import_fatturapa_happy_path(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, properties = _bootstrap(db_session, "aurora-import-05")
    prop = properties.get_by_slug("aurora-import-05")
    assert prop is not None
    run_create_data_source(
        db_session,
        workspace_slug="aurora-import-05",
        property_slug="aurora-import-05",
        domain=DataSourceDomain.COSTS,
        name="Invoices",
    )
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]

    content = fattura_xml()
    file = tmp_path / "invoice.xml"
    file.write_bytes(content)

    exit_code = run_import_invoices(
        db_session,
        workspace_slug="aurora-import-05",
        property_slug="aurora-import-05",
        data_source_id=data_source.id,
        file=file,
    )
    assert exit_code == 0
    assert "status=SUCCEEDED" in capsys.readouterr().out
    assert len(InvoiceRepository(db_session, tenant).list_for_property(prop.id)) == 1

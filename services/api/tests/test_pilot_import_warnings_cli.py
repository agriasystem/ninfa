"""Gate 24B: the `WARNING unrecognized_columns=...` line `app/cli/imports.py` prints for
bookings/labor CSV imports - never for FatturaPA XML invoices, which have no header/mapping
concept at all. No fuzzy matching exists anywhere in this path (by design): a typo of an
optional canonical field and a genuinely irrelevant extra column are indistinguishable, and the
warning never claims otherwise. Required-field validation is untouched and still fails closed.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.cli.imports import run_import_bookings, run_import_invoices, run_import_labor
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.tenant import TenantContext
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.repository import BookingRepository
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.labor.errors import LaborErrorCode, LaborImportError
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import WorkspaceRepository
from tests.invoice_support import fattura_xml

STAY_IN = date.today() + timedelta(days=30)
STAY_OUT = STAY_IN + timedelta(days=2)
WORK_DATE = date.today() + timedelta(days=30)


def _bootstrap(
    db_session: Session, slug: str, *, domain: DataSourceDomain, source_name: str
) -> tuple[TenantContext, DataSource]:
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
    run_create_data_source(
        db_session, workspace_slug=slug, property_slug=slug, domain=domain, name=source_name
    )
    prop = PropertyRepository(db_session, tenant).get_by_slug(slug)
    assert prop is not None
    data_source = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)[0]
    return tenant, data_source


def _write_csv(tmp_path: Path, filename: str, lines: list[str]) -> Path:
    path = tmp_path / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# =================================================================================================
# BOOKINGS
# =================================================================================================


def _booking_bootstrap(db_session: Session, slug: str) -> tuple[TenantContext, DataSource]:
    return _bootstrap(db_session, slug, domain=DataSourceDomain.BOOKINGS, source_name="Bookings")


def test_bookings_01_all_canonical_headers_emit_no_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b01")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct",
        ],
    )

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-warn-b01",
        property_slug="aurora-warn-b01",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SUCCEEDED" in out
    assert "WARNING" not in out


def test_bookings_02_unknown_extra_header_emits_a_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b02")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel,"
            "notes_extra",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct,irrelevant",
        ],
    )

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-warn-b02",
        property_slug="aurora-warn-b02",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0  # test 7: a warning never changes a successful exit code
    assert "status=SUCCEEDED" in out
    assert "WARNING unrecognized_columns=notes_extra" in out
    prop = PropertyRepository(db_session, tenant).get_by_slug("aurora-warn-b02")
    assert prop is not None
    bookings = BookingRepository(db_session, tenant).list_for_property(prop.id)
    assert len(bookings) == 1  # the import genuinely succeeded, not just printed SUCCEEDED


def test_bookings_03_typo_like_optional_header_emits_a_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`room_type` is OPTIONAL - a typo of it ("room_tpye") must be reported, never silently
    treated as "invalid" or "a typo" in the warning's own wording."""
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b03")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel,"
            "room_tpye",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct,Suite",
        ],
    )

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-warn-b03",
        property_slug="aurora-warn-b03",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    warning_line = next(line for line in out.splitlines() if line.startswith("WARNING"))
    assert warning_line == "WARNING unrecognized_columns=room_tpye"
    assert "invalid" not in warning_line.lower()
    assert "typo" not in warning_line.lower()


def test_bookings_04_a_misspelled_required_header_still_fails_closed(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check_in` is REQUIRED. A typo of it ("chek_in") is reported in the warning like any
    other unrecognized header, but the import must still fail exactly as before - the warning
    never weakens `MappingConfig`'s own required-field validation."""
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b04")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "source_record_id,booked_at,chek_in,check_out,status,rooms,room_revenue,channel",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct",
        ],
    )

    with pytest.raises(BookingImportError) as exc_info:
        run_import_bookings(
            db_session,
            workspace_slug="aurora-warn-b04",
            property_slug="aurora-warn-b04",
            data_source_id=data_source.id,
            file=file,
        )
    assert exc_info.value.code == BookingErrorCode.INVALID_MAPPING
    out = capsys.readouterr().out
    assert "WARNING unrecognized_columns=chek_in" in out  # printed before the failure
    prop = PropertyRepository(db_session, tenant).get_by_slug("aurora-warn-b04")
    assert prop is not None
    assert BookingRepository(db_session, tenant).list_for_property(prop.id) == []


def test_bookings_05_a_recognized_header_variant_emits_no_false_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Capitalisation/punctuation/spacing that `normalize_header` already treats as the same
    canonical field must never be reported as unrecognized."""
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b05")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "Source Record Id,Booked At,Check-In,Check-Out,Status,Rooms,Room Revenue,Channel",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct",
        ],
    )

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-warn-b05",
        property_slug="aurora-warn-b05",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SUCCEEDED" in out
    assert "WARNING" not in out


def test_bookings_06_multiple_unknown_headers_are_reported_in_deterministic_file_order(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, data_source = _booking_bootstrap(db_session, "aurora-warn-b06")
    file = _write_csv(
        tmp_path,
        "bookings.csv",
        [
            "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel,"
            "zzz_col,aaa_col",
            f"PILOT-0001,{date.today().isoformat()},{STAY_IN.isoformat()},"
            f"{STAY_OUT.isoformat()},confirmed,1,150.00,Direct,z,a",
        ],
    )

    exit_code = run_import_bookings(
        db_session,
        workspace_slug="aurora-warn-b06",
        property_slug="aurora-warn-b06",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    # first-occurrence-in-the-file order, never alphabetically sorted, never reordered run to run.
    assert "WARNING unrecognized_columns=zzz_col,aaa_col" in out


# =================================================================================================
# LABOR
# =================================================================================================


def _labor_bootstrap(db_session: Session, slug: str) -> tuple[TenantContext, DataSource]:
    return _bootstrap(db_session, slug, domain=DataSourceDomain.LABOR, source_name="Labor")


def test_labor_01_unrecognized_optional_currency_header_emits_a_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No `planned_cost`/`actual_cost` in this file on purpose: a cost value WITHOUT a
    recognized currency is a real, separate row-validation failure
    (`LaborErrorCode.CURRENCY_REQUIRED`) - unrelated to this test's own point, which is only
    that an unrecognized optional header is warned about, never silently required."""
    tenant, data_source = _labor_bootstrap(db_session, "aurora-warn-l01")
    file = _write_csv(
        tmp_path,
        "labor.csv",
        [
            "work_date,labor_category,planned_hours,currancy",
            f"{WORK_DATE.isoformat()},HOUSEKEEPING,8,EUR",
        ],
    )

    exit_code = run_import_labor(
        db_session,
        workspace_slug="aurora-warn-l01",
        property_slug="aurora-warn-l01",
        data_source_id=data_source.id,
        file=file,
        snapshot_local_date=date.today(),
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SUCCEEDED" in out
    assert "WARNING unrecognized_columns=currancy" in out


def test_labor_02_conditional_group_with_one_recognized_member_succeeds_with_a_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`planned_hours` alone satisfies the "at least one hours field" rule; `actul_hours` (a
    typo of `actual_hours`) is reported but does not block the import."""
    tenant, data_source = _labor_bootstrap(db_session, "aurora-warn-l02")
    file = _write_csv(
        tmp_path,
        "labor.csv",
        [
            "work_date,labor_category,planned_hours,actul_hours",
            f"{WORK_DATE.isoformat()},HOUSEKEEPING,8,6",
        ],
    )

    exit_code = run_import_labor(
        db_session,
        workspace_slug="aurora-warn-l02",
        property_slug="aurora-warn-l02",
        data_source_id=data_source.id,
        file=file,
        snapshot_local_date=date.today(),
    )
    out = capsys.readouterr().out
    assert exit_code == 0  # test 5: a warning never alters the exit code
    assert "status=SUCCEEDED" in out
    assert "WARNING unrecognized_columns=actul_hours" in out


def test_labor_03_conditional_group_with_no_recognized_member_still_fails_closed(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither `planned_hours` nor `actual_hours` is recognized ("palnned_hours" is a typo) -
    the existing "at least one hours field" failure must be preserved exactly."""
    tenant, data_source = _labor_bootstrap(db_session, "aurora-warn-l03")
    file = _write_csv(
        tmp_path,
        "labor.csv",
        [
            "work_date,labor_category,palnned_hours",
            f"{WORK_DATE.isoformat()},HOUSEKEEPING,8",
        ],
    )

    with pytest.raises(LaborImportError) as exc_info:
        run_import_labor(
            db_session,
            workspace_slug="aurora-warn-l03",
            property_slug="aurora-warn-l03",
            data_source_id=data_source.id,
            file=file,
            snapshot_local_date=date.today(),
        )
    assert exc_info.value.code == LaborErrorCode.INVALID_MAPPING
    out = capsys.readouterr().out
    assert "WARNING unrecognized_columns=palnned_hours" in out


def test_labor_04_a_recognized_header_variant_emits_no_false_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, data_source = _labor_bootstrap(db_session, "aurora-warn-l04")
    file = _write_csv(
        tmp_path,
        "labor.csv",
        [
            "Work Date,Labor Category,Planned Hours,Planned Cost,Currency",
            f"{WORK_DATE.isoformat()},HOUSEKEEPING,8,120.00,EUR",
        ],
    )

    exit_code = run_import_labor(
        db_session,
        workspace_slug="aurora-warn-l04",
        property_slug="aurora-warn-l04",
        data_source_id=data_source.id,
        file=file,
        snapshot_local_date=date.today(),
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SUCCEEDED" in out
    assert "WARNING" not in out


# =================================================================================================
# INVOICES - the CSV warning path must never run for FatturaPA XML
# =================================================================================================


def test_invoice_xml_path_never_emits_a_csv_style_warning(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, data_source = _bootstrap(
        db_session, "aurora-warn-inv01", domain=DataSourceDomain.COSTS, source_name="Invoices"
    )
    content = fattura_xml()
    file = tmp_path / "invoice.xml"
    file.write_bytes(content)

    exit_code = run_import_invoices(
        db_session,
        workspace_slug="aurora-warn-inv01",
        property_slug="aurora-warn-inv01",
        data_source_id=data_source.id,
        file=file,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SUCCEEDED" in out
    assert "WARNING" not in out

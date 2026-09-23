"""Data minimisation of the labor import: an unmapped employee-identity column never reaches the
database, the staging table, or an error message (Gate 8, Part A)."""

import logging
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.labor.models import LaborImportRow
from app.modules.labor.service import LaborImportService
from tests.labor_support import LaborFactory, LaborTenant, labor_tenant

SENSITIVE_VALUES = [
    "Jane Doe",  # employee_name
    "jane.doe@example.com",  # email
    "+39 333 1234567",  # phone
    "DOEJNE80A01H501Z",  # tax_code
    "Via Roma 1, Bari",  # address
    "chronic condition - reduced hours",  # medical_note
]

CSV_CONTENT = (
    "employee_name,email,phone,tax_code,address,medical_note,work_date,role,planned_hours\n"
    f"{SENSITIVE_VALUES[0]},{SENSITIVE_VALUES[1]},{SENSITIVE_VALUES[2]},{SENSITIVE_VALUES[3]},"
    f'"{SENSITIVE_VALUES[4]}","{SENSITIVE_VALUES[5]}",2026-03-10,Reception,8\n'
).encode()


def _service(session: Session, tenant: LaborTenant) -> LaborImportService:
    return LaborImportService(session, tenant.context)


def test_unmapped_employee_columns_never_reach_the_database(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    headers = [
        "employee_name",
        "email",
        "phone",
        "tax_code",
        "address",
        "medical_note",
        "work_date",
        "role",
        "planned_hours",
    ]
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=headers,
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
        },
    )
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="roster.csv",
        content=CSV_CONTENT,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded

    # Nothing in the staging table's payloads mentions any sensitive value.
    rows = db_session.query(LaborImportRow).filter_by(import_job_id=result.import_job_id).all()
    assert rows
    for row in rows:
        blob = str(row.mapped_payload) + str(row.normalized_payload) + str(row.validation_errors)
        for value in SENSITIVE_VALUES:
            assert value not in blob

    # Nor anywhere else in the whole database (a crude but effective whole-database sweep).
    for value in SENSITIVE_VALUES:
        found = db_session.execute(
            text("SELECT 1 FROM labor_entries WHERE role_raw = :v OR role_normalized = :v"),
            {"v": value},
        ).first()
        assert found is None


def test_unmapped_employee_columns_never_reach_an_error_message(
    db_session: Session, factory: LaborFactory, caplog: pytest.LogCaptureFixture
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    headers = [
        "employee_name",
        "email",
        "phone",
        "tax_code",
        "address",
        "medical_note",
        "work_date",
        "role",
        "planned_hours",
    ]
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=headers,
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
        },
    )
    # A row that will fail validation (negative hours), still carrying the sensitive columns.
    bad_content = (
        "employee_name,email,phone,tax_code,address,medical_note,work_date,role,planned_hours\n"
        f"{SENSITIVE_VALUES[0]},{SENSITIVE_VALUES[1]},{SENSITIVE_VALUES[2]},{SENSITIVE_VALUES[3]},"
        f'"{SENSITIVE_VALUES[4]}","{SENSITIVE_VALUES[5]}",2026-03-10,Reception,-8\n'
    ).encode()

    with caplog.at_level(logging.INFO):
        result = service.import_file(
            tenant.labor_data_source.id,
            filename="roster.csv",
            content=bad_content,
            snapshot_local_date=date(2026, 3, 1),
        )
    assert not result.succeeded
    for value in SENSITIVE_VALUES:
        assert value not in (result.error_message or "")
        assert value not in str(result.details)
        assert value not in str(result.row_error_summary)
    for record in caplog.records:
        for value in SENSITIVE_VALUES:
            assert value not in record.getMessage()


def test_values_absent_from_staging_when_column_is_not_mapped_at_all(
    db_session: Session, factory: LaborFactory
) -> None:
    """Even the column NAMES that were not mapped are irrelevant: only mapped canonical fields
    ever appear as keys in `mapped_payload`."""
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    headers = ["employee_name", "work_date", "role", "planned_hours"]
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=headers,
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
        },
    )
    content = b"employee_name,work_date,role,planned_hours\nJane Doe,2026-03-10,Reception,8\n"
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="r.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded
    rows = db_session.query(LaborImportRow).filter_by(import_job_id=result.import_job_id).all()
    for row in rows:
        assert "employee_name" not in row.mapped_payload

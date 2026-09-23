"""LaborImportService: mapping, import, atomicity, idempotency (Gate 8, Part A)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.modules.ingestion.models import ImportJobStatus
from app.modules.labor.errors import LaborErrorCode, LaborImportError
from app.modules.labor.models import LaborEntry, LaborImportRow, LaborSnapshot
from app.modules.labor.repository import LaborEntryRepository
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from app.modules.labor.service import LaborImportService
from tests.labor_support import LaborFactory, LaborTenant, csv_of, csv_row, labor_tenant


@pytest.fixture
def tenant(factory: LaborFactory) -> LaborTenant:
    return labor_tenant(factory)


def _service(session: Session, tenant: LaborTenant) -> LaborImportService:
    return LaborImportService(session, tenant.context)


def _confirm_default_mapping(
    service: LaborImportService, tenant: LaborTenant, headers: list[str]
) -> None:
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=headers,
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
            "actual_hours": {"column": "actual_hours"},
            "planned_cost": {"column": "planned_cost"},
            "actual_cost": {"column": "actual_cost"},
            "currency": {"column": "currency"},
        },
    )


HEADERS = [
    "work_date",
    "role",
    "planned_hours",
    "actual_hours",
    "planned_cost",
    "actual_cost",
    "currency",
]


def test_a_valid_file_imports_successfully_with_correct_minutes(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of(
        [
            csv_row("2026-03-10", "Reception AM", planned_hours="7.5"),
            csv_row("2026-03-10", "Housekeeping", planned_hours="8"),
        ]
    )
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )

    assert result.succeeded
    assert result.status == ImportJobStatus.SUCCEEDED
    assert result.rows_valid == 2
    assert result.rows_invalid == 0
    assert result.entries_created == 2
    assert result.labor_snapshot_id is not None

    entries = LaborEntryRepository(db_session, tenant.context).list_for_snapshot(
        result.labor_snapshot_id
    )
    minutes = {e.role_raw: e.planned_minutes for e in entries}
    assert minutes["Reception AM"] == 450  # 7.5h
    assert minutes["Housekeeping"] == 480  # 8h
    categories = {e.role_raw: e.labor_category for e in entries}
    assert categories["Reception AM"] == LaborCategory.FRONT_OFFICE
    assert categories["Housekeeping"] == LaborCategory.HOUSEKEEPING


def test_fractional_minutes_are_rejected_not_rounded(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="7.501")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == LaborErrorCode.VALIDATION_FAILED
    assert LaborErrorCode.FRACTIONAL_MINUTES.value in result.row_error_summary


def test_missing_both_planned_and_actual_hours_is_rejected(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of([csv_row("2026-03-10", "Reception")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert LaborErrorCode.HOURS_MISSING.value in result.row_error_summary


def test_negative_hours_are_rejected(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="-1")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert LaborErrorCode.NEGATIVE_VALUE.value in result.row_error_summary


def test_cost_without_currency_is_rejected(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8", planned_cost="100")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert LaborErrorCode.CURRENCY_REQUIRED.value in result.row_error_summary


def test_cost_with_currency_is_accepted_and_stored(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of(
        [
            csv_row(
                "2026-03-10", "Reception", planned_hours="8", planned_cost="120.00", currency="EUR"
            )
        ]
    )
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded
    assert result.labor_snapshot_id is not None
    entries = LaborEntryRepository(db_session, tenant.context).list_for_snapshot(
        result.labor_snapshot_id
    )
    assert entries[0].planned_cost == Decimal("120.00")
    assert entries[0].currency == "EUR"


def test_an_invalid_row_fails_the_whole_job_and_creates_zero_canonical_rows(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of(
        [
            csv_row("2026-03-10", "Reception", planned_hours="8"),
            csv_row("2026-03-11", "Housekeeping", planned_hours="-1"),
        ]
    )
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert result.rows_valid == 1
    assert result.rows_invalid == 1

    assert db_session.query(LaborSnapshot).count() == 0
    assert db_session.query(LaborEntry).count() == 0
    # staging remains, for diagnostics
    assert (
        db_session.query(LaborImportRow).filter_by(import_job_id=result.import_job_id).count() == 2
    )


def test_same_snapshot_date_same_content_is_a_no_op_reusing_the_snapshot(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8")])
    first = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    second = service.import_file(
        tenant.labor_data_source.id,
        filename="week-again.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert first.succeeded and second.succeeded
    assert second.labor_snapshot_id == first.labor_snapshot_id
    assert second.snapshot_reused is True
    assert second.entries_created == 0
    assert db_session.query(LaborSnapshot).count() == 1


def test_same_snapshot_date_different_content_is_a_conflict(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    first_content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8")])
    service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=first_content,
        snapshot_local_date=date(2026, 3, 1),
    )
    second_content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="9")])
    second = service.import_file(
        tenant.labor_data_source.id,
        filename="week-2.csv",
        content=second_content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert second.status == ImportJobStatus.FAILED
    assert second.error_code == LaborErrorCode.SNAPSHOT_CONFLICT
    assert db_session.query(LaborSnapshot).count() == 1


def test_the_same_content_in_a_different_row_order_is_still_recognised_as_a_no_op(
    db_session: Session, factory: LaborFactory
) -> None:
    """The fingerprint does not depend on row order: a re-export with shuffled rows is a no-op."""
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)

    content_a = csv_of(
        [
            csv_row("2026-03-10", "Reception", planned_hours="8"),
            csv_row("2026-03-11", "Housekeeping", planned_hours="7"),
        ]
    )
    content_b = csv_of(  # same two rows, reversed order
        [
            csv_row("2026-03-11", "Housekeeping", planned_hours="7"),
            csv_row("2026-03-10", "Reception", planned_hours="8"),
        ]
    )
    first = service.import_file(
        tenant.labor_data_source.id,
        filename="a.csv",
        content=content_a,
        snapshot_local_date=date(2026, 3, 1),
    )
    second = service.import_file(
        tenant.labor_data_source.id,
        filename="b.csv",
        content=content_b,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert first.succeeded and second.succeeded
    assert second.snapshot_reused is True
    assert second.labor_snapshot_id == first.labor_snapshot_id
    assert db_session.query(LaborSnapshot).count() == 1


def test_no_mapping_confirmed_requires_mapping(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == LaborErrorCode.MAPPING_REQUIRED


def test_snapshot_date_must_be_an_explicit_date_not_a_datetime_or_none(
    db_session: Session, factory: LaborFactory
) -> None:
    from datetime import datetime

    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)
    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8")])
    with pytest.raises(LaborImportError) as info:
        service.import_file(
            tenant.labor_data_source.id,
            filename="week.csv",
            content=content,
            snapshot_local_date=datetime(2026, 3, 1, 10, 0),
        )
    assert info.value.error_code == LaborErrorCode.SNAPSHOT_DATE_REQUIRED


def test_source_domain_must_be_labor(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    content = csv_of([csv_row("2026-03-10", "Reception", planned_hours="8")])
    # _load_source raises before a job is even created: nothing is created for the wrong domain.
    with pytest.raises(LaborImportError) as info:
        service.import_file(
            tenant.booking_data_source.id,  # wrong domain
            filename="week.csv",
            content=content,
            snapshot_local_date=date(2026, 3, 1),
        )
    assert info.value.error_code == LaborErrorCode.INVALID_DATA_SOURCE


def test_ambiguous_role_stays_other(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    _confirm_default_mapping(service, tenant, HEADERS)
    # "bar" (F&B) also could match nothing else here; use a role matching two categories instead
    content = csv_of([csv_row("2026-03-10", "reception bar", planned_hours="8")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded
    assert result.labor_snapshot_id is not None
    entries = LaborEntryRepository(db_session, tenant.context).list_for_snapshot(
        result.labor_snapshot_id
    )
    assert entries[0].labor_category == LaborCategory.OTHER
    assert entries[0].classification_method == LaborClassificationMethod.UNCLASSIFIED
    assert entries[0].classification_confidence == Decimal("0.00")


def test_role_mapping_takes_priority_over_the_deterministic_dictionary(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=HEADERS,
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
        },
        role_mapping={"night auditor": "MANAGEMENT"},
    )
    content = csv_of([csv_row("2026-03-10", "Night Auditor", planned_hours="8")])
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded
    assert result.labor_snapshot_id is not None
    entries = LaborEntryRepository(db_session, tenant.context).list_for_snapshot(
        result.labor_snapshot_id
    )
    assert entries[0].labor_category == LaborCategory.MANAGEMENT
    assert entries[0].classification_method == LaborClassificationMethod.ROLE_MAPPING
    assert entries[0].classification_confidence == Decimal("95.00")


def test_explicit_category_column_wins_over_role(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    service = _service(db_session, tenant)
    service.save_mapping(
        tenant.labor_data_source.id,
        headers=[*HEADERS, "labor_category"],
        column_mapping={
            "work_date": {"column": "work_date"},
            "role": {"column": "role"},
            "planned_hours": {"column": "planned_hours"},
            "labor_category": {"column": "labor_category"},
        },
    )
    content = (
        b"work_date,role,planned_hours,actual_hours,planned_cost,actual_cost,currency,labor_category\n"
        b"2026-03-10,Housekeeping,8,,,,,SPA_WELLNESS"
    )
    result = service.import_file(
        tenant.labor_data_source.id,
        filename="week.csv",
        content=content,
        snapshot_local_date=date(2026, 3, 1),
    )
    assert result.succeeded
    assert result.labor_snapshot_id is not None
    entries = LaborEntryRepository(db_session, tenant.context).list_for_snapshot(
        result.labor_snapshot_id
    )
    assert entries[0].labor_category == LaborCategory.SPA_WELLNESS
    assert entries[0].classification_method == LaborClassificationMethod.EXPLICIT_SOURCE
    assert entries[0].classification_confidence == Decimal("100.00")

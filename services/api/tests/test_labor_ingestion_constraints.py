"""DB-level constraints of the labor canonical tables (Gate 8, Part A)."""

from datetime import date
from decimal import Decimal

import psycopg
import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session

from app.modules.labor.models import LaborEntry, LaborSnapshot
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from tests.labor_support import (
    LaborFactory,
    LaborTenant,
    labor_entry,
    labor_entry_values,
    labor_snapshot,
    labor_snapshot_values,
    labor_tenant,
)
from tests.support import Rejects


@pytest.fixture
def tenant(factory: LaborFactory) -> LaborTenant:
    return labor_tenant(factory)


def _snapshot(factory: LaborFactory, tenant: LaborTenant, **overrides):  # type: ignore[no-untyped-def]
    return labor_snapshot(
        factory,
        tenant.labor_data_source,
        tenant.labor_import_job,
        factory.import_file(tenant.labor_import_job),
        **overrides,
    )


# --- LaborSnapshot ------------------------------------------------------------------------------


def test_snapshot_identity_is_unique_per_data_source_and_date(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    _snapshot(factory, tenant, snapshot_local_date=date(2026, 3, 1))
    with rejects(
        psycopg.errors.UniqueViolation, "uq_labor_snapshots_data_source_id_snapshot_local_date"
    ):
        db_session.execute(
            insert(LaborSnapshot),
            labor_snapshot_values(
                tenant.labor_data_source,
                tenant.labor_import_job,
                factory.import_file(tenant.labor_import_job),
                snapshot_local_date=date(2026, 3, 1),
            ),
        )


def test_two_different_dates_are_both_allowed(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    _snapshot(factory, tenant, snapshot_local_date=date(2026, 3, 1))
    _snapshot(factory, tenant, snapshot_local_date=date(2026, 3, 2))
    assert db_session.query(LaborSnapshot).count() == 2


def test_snapshot_update_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.IntegrityConstraintViolation):
        db_session.execute(
            update(LaborSnapshot)
            .where(LaborSnapshot.id == snapshot.id)
            .values(source_fingerprint="b" * 64)
        )


def test_source_fingerprint_must_be_64_hex_chars(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    with rejects(psycopg.errors.CheckViolation, "ck_labor_snapshots_source_fingerprint_format"):
        db_session.execute(
            insert(LaborSnapshot),
            labor_snapshot_values(
                tenant.labor_data_source,
                tenant.labor_import_job,
                factory.import_file(tenant.labor_import_job),
                source_fingerprint="not-hex",
            ),
        )


# --- LaborEntry ---------------------------------------------------------------------------------


def test_planned_only_is_valid(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot, planned_minutes=480, actual_minutes=None)
    assert entry.planned_minutes == 480


def test_actual_only_is_valid(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot, planned_minutes=None, actual_minutes=460)
    assert entry.actual_minutes == 460


def test_both_planned_and_actual_is_valid(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot, planned_minutes=480, actual_minutes=460)
    assert entry.planned_minutes == 480 and entry.actual_minutes == 460


def test_both_null_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(
        psycopg.errors.CheckViolation, "ck_labor_entries_planned_or_actual_minutes_present"
    ):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(snapshot, planned_minutes=None, actual_minutes=None),
        )


def test_negative_planned_minutes_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_planned_minutes_non_negative"):
        db_session.execute(insert(LaborEntry), labor_entry_values(snapshot, planned_minutes=-1))


def test_negative_actual_minutes_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_actual_minutes_non_negative"):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(snapshot, planned_minutes=None, actual_minutes=-1),
        )


def test_entry_update_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot)
    with rejects(psycopg.errors.IntegrityConstraintViolation):
        db_session.execute(
            update(LaborEntry).where(LaborEntry.id == entry.id).values(planned_minutes=999)
        )


def test_work_date_is_persisted_exactly(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot, work_date=date(2026, 4, 5))
    stored = db_session.scalar(select(LaborEntry).where(LaborEntry.id == entry.id))
    assert stored is not None and stored.work_date == date(2026, 4, 5)


# --- cost -----------------------------------------------------------------------------------


def test_planned_cost_is_optional(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant
) -> None:
    snapshot = _snapshot(factory, tenant)
    entry = labor_entry(factory, snapshot, planned_cost=None, actual_cost=None, currency=None)
    assert entry.planned_cost is None


def test_cost_requires_currency(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_cost_requires_currency"):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(snapshot, planned_cost=Decimal("100.00"), currency=None),
        )


def test_negative_cost_is_rejected(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_planned_cost_non_negative"):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(snapshot, planned_cost=Decimal("-1.00"), currency="EUR"),
        )


def test_currency_must_be_three_upper_case_letters(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_currency_format"):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(snapshot, planned_cost=Decimal("10.00"), currency="eur"),
        )


# --- classification ---------------------------------------------------------------------------


def test_labor_category_must_be_one_of_the_eight_canonical_values(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    """Raw SQL: the ORM's `Enum` column type would otherwise reject the bad value client-side,
    before the database's own CHECK constraint (the real invariant under test) ever saw it."""
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_labor_category_valid"):
        db_session.execute(
            text(
                "INSERT INTO labor_entries (workspace_id, labor_snapshot_id, source_row_number,"
                " work_date, labor_category, planned_minutes, classification_method,"
                " classification_confidence)"
                " VALUES (:workspace_id, :labor_snapshot_id, 1, :work_date, 'NOT_A_CATEGORY', 480,"
                " 'DETERMINISTIC_RULE', 80.00)"
            ),
            {
                "workspace_id": snapshot.workspace_id,
                "labor_snapshot_id": snapshot.id,
                "work_date": date(2026, 3, 10),
            },
        )


def test_unclassified_requires_zero_confidence_and_other_category(
    db_session: Session, factory: LaborFactory, tenant: LaborTenant, rejects: Rejects
) -> None:
    snapshot = _snapshot(factory, tenant)
    with rejects(psycopg.errors.CheckViolation, "ck_labor_entries_classification_consistent"):
        db_session.execute(
            insert(LaborEntry),
            labor_entry_values(
                snapshot,
                labor_category=LaborCategory.HOUSEKEEPING,
                classification_method=LaborClassificationMethod.UNCLASSIFIED,
                classification_confidence=Decimal("0.00"),
            ),
        )

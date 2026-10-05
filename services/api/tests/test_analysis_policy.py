"""Gate 26B: the durable automatic-analysis policy and its fail-closed enablement.

Absence of a row and `enabled = false` both mean "not automated". Enabling needs an EXACT primary
BOOKINGS source and refuses on any configuration problem with a typed reason; the database also
refuses a policy whose source belongs to another property/workspace or that is enabled without a
source.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg.errors as pg
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.analysis import (
    AnalysisPolicyError,
    AnalysisPolicyService,
    AutomaticSkipReason,
    PropertyAnalysisPolicy,
    list_enabled_policies,
)
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSourceDomain
from app.modules.tenancy.repository import WorkspaceRepository
from tests.analysis_policy_support import enable
from tests.support import BookingFactory, Rejects


def _service(session: Session, tenant: TenantContext) -> AnalysisPolicyService:
    return AnalysisPolicyService(session, tenant)


def _refused(
    session: Session, tenant_ctx: TenantContext, prop_id: UUID, source_id: UUID
) -> AutomaticSkipReason:
    with pytest.raises(AnalysisPolicyError) as info:
        _service(session, tenant_ctx).enable(prop_id, source_id)
    return info.value.reason


def test_01_absence_of_a_policy_means_disabled(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    assert _service(db_session, tenant.context).get(tenant.property.id) is None
    assert tenant.property.id not in {p.property_id for p in list_enabled_policies(db_session)}


def test_02_enable_stores_the_exact_source_and_triggers_no_run(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    policy = enable(db_session, tenant)

    assert policy.enabled is True
    assert policy.booking_data_source_id == tenant.data_source.id
    assert policy.workspace_id == tenant.workspace.id
    assert [p.property_id for p in list_enabled_policies(db_session)] == [tenant.property.id]
    # Enabling never runs anything (changes apply to future opportunities only).
    assert db_session.scalars(select(DecisionRun)).all() == []


def test_03_a_source_of_another_workspace_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    mine, other = factory.tenant(), factory.tenant()

    reason = _refused(db_session, mine.context, mine.property.id, other.data_source.id)

    assert reason is AutomaticSkipReason.INVALID_BOOKING_SOURCE
    assert _service(db_session, mine.context).get(mine.property.id) is None


def test_04_a_source_of_another_property_of_the_same_workspace_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    second_property = factory.property(tenant.workspace)
    foreign_source = factory.data_source(second_property)

    reason = _refused(db_session, tenant.context, tenant.property.id, foreign_source.id)

    assert reason is AutomaticSkipReason.INVALID_BOOKING_SOURCE


@pytest.mark.parametrize("domain", [DataSourceDomain.COSTS, DataSourceDomain.LABOR])
def test_05_a_non_bookings_source_is_rejected(
    db_session: Session, factory: BookingFactory, domain: DataSourceDomain
) -> None:
    tenant = factory.tenant()
    source = factory.data_source(tenant.property, domain)

    assert (
        _refused(db_session, tenant.context, tenant.property.id, source.id)
        is AutomaticSkipReason.INVALID_BOOKING_SOURCE
    )


def test_06_an_inactive_source_is_rejected(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    tenant.data_source.is_active = False
    db_session.flush()

    assert (
        _refused(db_session, tenant.context, tenant.property.id, tenant.data_source.id)
        is AutomaticSkipReason.BOOKING_SOURCE_INACTIVE
    )


def test_07_an_inactive_or_archived_property_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    inactive = factory.tenant()
    inactive.property.is_active = False
    archived = factory.tenant()
    archived.property.is_active = False
    archived.property.archived_at = datetime.now(UTC)
    db_session.flush()

    for tenant in (inactive, archived):
        assert (
            _refused(db_session, tenant.context, tenant.property.id, tenant.data_source.id)
            is AutomaticSkipReason.PROPERTY_INACTIVE
        )


def test_08_an_inactive_or_archived_workspace_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    inactive = factory.tenant()
    inactive.workspace.is_active = False
    archived = factory.tenant()
    WorkspaceRepository(db_session).archive(archived.workspace.id)
    db_session.flush()

    for tenant in (inactive, archived):
        assert (
            _refused(db_session, tenant.context, tenant.property.id, tenant.data_source.id)
            is AutomaticSkipReason.WORKSPACE_INACTIVE
        )


def test_09_an_invalid_property_timezone_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant.property.timezone = "Mars/Olympus_Mons"
    db_session.flush()

    assert (
        _refused(db_session, tenant.context, tenant.property.id, tenant.data_source.id)
        is AutomaticSkipReason.INVALID_TIMEZONE
    )


def test_10_a_refused_enable_never_changes_an_existing_policy(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = enable(db_session, tenant)
    other_source = factory.data_source(tenant.property, DataSourceDomain.LABOR)

    assert (
        _refused(db_session, tenant.context, tenant.property.id, other_source.id)
        is AutomaticSkipReason.INVALID_BOOKING_SOURCE
    )

    db_session.refresh(policy)
    assert policy.enabled is True and policy.booking_data_source_id == tenant.data_source.id


def test_11_unknown_or_foreign_properties_are_not_found(
    db_session: Session, factory: BookingFactory
) -> None:
    mine, other = factory.tenant(), factory.tenant()

    with pytest.raises(NotFoundError):
        _service(db_session, mine.context).enable(uuid4(), mine.data_source.id)
    with pytest.raises(NotFoundError):
        _service(db_session, mine.context).enable(other.property.id, other.data_source.id)
    with pytest.raises(NotFoundError):
        _service(db_session, mine.context).disable(other.property.id)


def test_12_disable_keeps_the_history_and_a_never_configured_property_gets_no_row(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, untouched = factory.tenant(), factory.tenant()
    enable(db_session, tenant)

    disabled = _service(db_session, tenant.context).disable(tenant.property.id)

    assert disabled is not None
    assert disabled.enabled is False
    assert disabled.booking_data_source_id == tenant.data_source.id  # kept as history
    assert list_enabled_policies(db_session) == []
    assert _service(db_session, untouched.context).disable(untouched.property.id) is None
    assert _service(db_session, untouched.context).get(untouched.property.id) is None


def test_13_enabling_again_updates_the_one_row_and_can_switch_the_source(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    first = enable(db_session, tenant)
    second_source = factory.data_source(tenant.property)

    again = _service(db_session, tenant.context).enable(tenant.property.id, second_source.id)

    assert again.id == first.id
    assert again.booking_data_source_id == second_source.id
    rows = db_session.scalars(select(PropertyAnalysisPolicy)).all()
    assert len(rows) == 1


def test_14_the_dispatcher_listing_spans_workspaces_deterministically(
    db_session: Session, factory: BookingFactory
) -> None:
    tenants = [factory.tenant() for _ in range(3)]
    for tenant in tenants:
        enable(db_session, tenant)
    _service(db_session, tenants[1].context).disable(tenants[1].property.id)

    listed = list_enabled_policies(db_session)

    expected = sorted((t.workspace.id, t.property.id) for t in (tenants[0], tenants[2]))
    assert [(p.workspace_id, p.property_id) for p in listed] == expected


# --- database integrity -------------------------------------------------------------------------


def _insert(session: Session, **values: object) -> None:
    session.add(PropertyAnalysisPolicy(**values))
    session.flush()


def test_15_one_policy_per_property_is_enforced_by_the_database(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant = factory.tenant()
    _insert(db_session, workspace_id=tenant.workspace.id, property_id=tenant.property.id)

    with rejects(pg.UniqueViolation, "uq_property_analysis_policies_property_id"):
        _insert(db_session, workspace_id=tenant.workspace.id, property_id=tenant.property.id)


def test_16_an_enabled_policy_requires_a_source(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant = factory.tenant()

    with rejects(pg.CheckViolation, "ck_property_analysis_policies_enabled_requires_source"):
        _insert(
            db_session,
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            enabled=True,
        )


def test_17_a_disabled_policy_may_have_no_source_and_defaults_to_disabled(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _insert(db_session, workspace_id=tenant.workspace.id, property_id=tenant.property.id)

    policy = db_session.scalars(select(PropertyAnalysisPolicy)).one()
    assert policy.enabled is False and policy.booking_data_source_id is None


def test_18_the_foreign_keys_refuse_an_invalid_tenancy(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    same_workspace_other_property = factory.data_source(factory.property(tenant.workspace))

    with rejects(pg.ForeignKeyViolation, "fk_property_analysis_policies_workspace_id_data_sources"):
        _insert(
            db_session,
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            enabled=True,
            booking_data_source_id=other.data_source.id,  # another workspace
        )
    with rejects(pg.ForeignKeyViolation, "fk_property_analysis_policies_workspace_id_data_sources"):
        _insert(
            db_session,
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            enabled=True,
            booking_data_source_id=same_workspace_other_property.id,  # another property
        )
    with rejects(pg.ForeignKeyViolation, "fk_property_analysis_policies_workspace_id_properties"):
        _insert(
            db_session, workspace_id=other.workspace.id, property_id=tenant.property.id
        )  # a property of another workspace

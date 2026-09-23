"""Part B: the target of the evaluation (property/booking source validation, explicit as-of)."""

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.distribution.errors import OtaDependencyError, OtaDependencyErrorCode
from app.modules.intelligence.distribution.service import OtaDependencyService
from tests.distribution_support import DistributionFactory

AS_OF = date(2026, 9, 5)


def test_a_valid_bookings_source_is_accepted(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    service = OtaDependencyService(db_session, tenant.context)
    # A valid source with no data at all is still a valid REQUEST: it answers INSUFFICIENT_DATA,
    # never an error.
    evaluation = service.evaluate(
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=AS_OF,
    )
    assert evaluation is not None


def test_a_costs_data_source_is_rejected(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    costs_source = factory.data_source(tenant.property, domain=DataSourceDomain.COSTS)
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=costs_source.id,
            as_of_local_date=AS_OF,
        )
    assert exc.value.error_code == OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_a_labor_data_source_is_rejected(db_session: Session, factory: DistributionFactory) -> None:
    tenant = factory.tenant()
    labor_source = factory.data_source(tenant.property, domain=DataSourceDomain.LABOR)
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=labor_source.id,
            as_of_local_date=AS_OF,
        )
    assert exc.value.error_code == OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_an_inactive_booking_source_is_rejected(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    tenant.data_source.is_active = False
    db_session.flush()
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=AS_OF,
        )
    assert exc.value.error_code == OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_a_source_of_another_property_is_rejected(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    other_property = factory.property(tenant.workspace)
    other_source = factory.data_source(other_property)
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=other_source.id,
            as_of_local_date=AS_OF,
        )
    assert exc.value.error_code == OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_a_source_of_another_workspace_is_rejected(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    other = factory.tenant()
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=other.data_source.id,
            as_of_local_date=AS_OF,
        )
    # An id of another workspace does not exist for this tenant: same code as "not found".
    assert exc.value.error_code == OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_as_of_local_date_is_required_explicitly(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            as_of_local_date=None,  # type: ignore[arg-type]
        )
    assert exc.value.error_code == OtaDependencyErrorCode.INVALID_AS_OF_DATE


def test_a_datetime_is_rejected_never_silently_truncated(
    db_session: Session, factory: DistributionFactory
) -> None:
    tenant = factory.tenant()
    service = OtaDependencyService(db_session, tenant.context)
    with pytest.raises(OtaDependencyError) as exc:
        service.evaluate(
            property_id=tenant.property.id,
            booking_data_source_id=tenant.data_source.id,
            # a datetime IS a date; the service still refuses it
            as_of_local_date=datetime(2026, 9, 5, 10, 0),
        )
    assert exc.value.error_code == OtaDependencyErrorCode.INVALID_AS_OF_DATE


def test_the_service_never_calls_a_clock() -> None:
    """No `datetime.now()` / `date.today()` CALL anywhere in the service or the pure modules
    below it: `as_of_local_date` is the only source of "when". Checked on the AST (a call node),
    never a text search, so a docstring that merely explains the rule cannot trip a false
    positive."""
    import ast
    import inspect

    from app.modules.intelligence.distribution import detector, metrics, selection, service

    for module in (service, detector, selection, metrics):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ("now", "today"), (module.__name__, node.func.attr)

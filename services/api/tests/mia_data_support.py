"""Worlds and helpers for the tests of Mia's data tools.

The tools read the Dati overview, so the worlds are the ones the Dati tests already build (real
snapshots, a real persisted run, real invoices, real labor entries); this module only adds what is
Mia-side: a `MiaWorld` around ANY tenant, a runtime whose OTA evaluation a test can choose, and the
recording stand-in for that evaluation.
"""

from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.ai.mia.tools.base import ToolRuntime
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import DataOverview
from app.modules.intelligence.distribution.types import (
    EvaluationStatus,
    OtaDependencyEvaluation,
)
from app.modules.tenancy.models import MembershipRole
from tests.data_overview_support import AS_OF
from tests.decision_api_support import AuthedTenant
from tests.decision_support import ota_evaluation
from tests.mia_support import MiaWorld
from tests.support import BookingFactory, Tenant


class Evaluator:
    """A recording stand-in for the live OTA evaluation: returns (or raises) what a test decides."""

    def __init__(self, result: OtaDependencyEvaluation | Exception) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID, date]] = []

    def __call__(self, property_id: UUID, source_id: UUID, as_of: date) -> OtaDependencyEvaluation:
        self.calls.append((property_id, source_id, as_of))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def evaluation(
    tenant: Tenant, status: EvaluationStatus, **overrides: Any
) -> OtaDependencyEvaluation:
    base = ota_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=AS_OF,
        status=status,
    )
    return replace(base, **overrides) if overrides else base


def mia_for(
    factory: BookingFactory, session: Session, tenant: Tenant, *, as_of: date = AS_OF
) -> MiaWorld:
    """A `MiaWorld` around an existing tenant: a real member user of its workspace."""
    user = factory.user()
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    return MiaWorld(session, AuthedTenant(tenant, user), as_of=as_of)


def runtime_with(world: MiaWorld, evaluator: Evaluator | None = None, **kwargs: Any) -> ToolRuntime:
    """A runtime of the world whose live OTA evaluation is the test's own stand-in."""
    runtime = world.runtime(**kwargs)
    if evaluator is not None:
        runtime._overview_service = DataOverviewService(  # the one private seam the tests need
            world.session, runtime.tenant, ota_evaluator=evaluator
        )
    return runtime


def overview_for(
    world: MiaWorld, period: int = 30, evaluator: Evaluator | None = None
) -> DataOverview:
    """What the Dati page would show for the same property, date and period."""
    return DataOverviewService(
        world.session, runtime_tenant(world), ota_evaluator=evaluator
    ).overview(world.at.tenant.property.id, world.as_of, period)


def runtime_tenant(world: MiaWorld) -> Any:
    return world.runtime().tenant


__all__ = ["Evaluator", "evaluation", "mia_for", "overview_for", "runtime_tenant", "runtime_with"]

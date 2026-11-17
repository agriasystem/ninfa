"""Helpers for the tests of Mia's context and decision tools.

Worlds are REAL: a tenant, a member, snapshots, a run persisted by `DecisionService.sync()` and read
back through `DecisionMemoryService`, exactly as production does. Nothing hand-builds a feed.
"""

import json
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai.mia.access import AccessDomain, UserContext
from app.modules.ai.mia.tools.base import ToolDefinition
from app.modules.decisions.coverage import AnalysisCoverage
from app.modules.decisions.models import Decision
from app.modules.intelligence.priority.types import PriorityDecisionType
from tests.ask_home_support import STAY, five_triggered_evaluations
from tests.data_overview_support import AS_OF, full_coverage, seed_run, uniform_nights
from tests.decision_api_support import AuthedTenant
from tests.decision_support import CLEAR, INSUFFICIENT, Evaluation, revenue_evaluation
from tests.mia_support import MiaWorld
from tests.support import BookingFactory, Tenant

__all__ = [
    "AS_OF",
    "HideAreas",
    "clear_evaluations",
    "decision_of_type",
    "definition",
    "decisions_of",
    "insufficient_evaluations",
    "json_text",
    "spoken_text",
    "other_property_of",
    "seed_five_decisions",
    "world_for",
]


class HideAreas:
    """An access policy that hides some data areas from everybody (what a per-area permission would
    do): the seam `DomainAccessPolicy` exists for."""

    def __init__(self, *hidden: AccessDomain) -> None:
        self._hidden = frozenset(hidden)

    def allows(self, user: UserContext, domain: AccessDomain) -> bool:
        return domain not in self._hidden


def world_for(
    factory: BookingFactory,
    db_session: Session,
    tenant: Tenant,
    *,
    display_name: str | None = "Luisa Rossi",
) -> MiaWorld:
    """A `MiaWorld` around an existing tenant: one member user with a display name."""
    user = factory.user()
    user.display_name = display_name
    db_session.flush()
    factory.membership(tenant.workspace, user)
    return MiaWorld(db_session, AuthedTenant(tenant, user))


def other_property_of(factory: BookingFactory, tenant: Tenant) -> Tenant:
    """A second property of the SAME workspace, with its own booking source and import."""
    prop = factory.property(tenant.workspace)
    source = factory.data_source(prop)
    return Tenant(tenant.workspace, prop, source, factory.import_job(source))


def seed_five_decisions(
    factory: BookingFactory,
    db_session: Session,
    tenant: Tenant,
    *,
    as_of: date = AS_OF,
    coverage: AnalysisCoverage | None = None,
    nights: int = 20,
) -> None:
    """A persisted run of `as_of` with one TRIGGERED decision of every type, in the engine's order:
    pickup, occupancy risk, OTA dependency, cost per room, labor hours."""
    seed_run(
        db_session,
        tenant,
        as_of=as_of,
        nights=uniform_nights(as_of, 20, days=nights),
        evaluations=five_triggered_evaluations(factory, tenant, as_of=as_of),
        coverage=coverage or full_coverage(),
    )


def clear_evaluations(tenant: Tenant, *, as_of: date = AS_OF) -> list[Evaluation]:
    return [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY,
            snapshot_local_date=as_of,
            status=CLEAR,
        )
    ]


def insufficient_evaluations(tenant: Tenant, *, as_of: date = AS_OF) -> list[Evaluation]:
    return [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=STAY,
            snapshot_local_date=as_of,
            status=INSUFFICIENT,
        )
    ]


def decisions_of(session: Session, property_id: UUID) -> Sequence[Decision]:
    return session.scalars(select(Decision).where(Decision.property_id == property_id)).all()


def decision_of_type(
    session: Session, property_id: UUID, decision_type: PriorityDecisionType
) -> Decision:
    return session.scalars(
        select(Decision).where(
            Decision.property_id == property_id, Decision.decision_type == decision_type
        )
    ).one()


def json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def spoken_text(payload: dict[str, Any]) -> str:
    """What an observation SAYS: everything except the envelope's own `strumento` (the tool's name,
    which the model already has as its function name and which is snake_case by nature)."""
    return json_text({key: value for key, value in payload.items() if key != "strumento"})


def definition(world: MiaWorld, name: str) -> ToolDefinition:
    found = world.catalog.get(name)
    assert found is not None, f"{name} is not in the catalog"
    return found

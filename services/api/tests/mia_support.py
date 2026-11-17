"""Shared helpers for the Mia tests.

Builds on the helpers the earlier gates ship (`tests.decision_api_support`, `tests.support`,
`tests.data_overview_support`, `tests.ask_home_support`): a REAL tenant, a REAL member user, REAL
persisted runs and snapshots - the tools are exercised against the real repositories and the real
`DataOverviewService`, never a hand-built feed. `ScriptedToolProvider` is the ONE fake
`ToolCallingProvider`: it plays a scripted sequence of model steps and records every request, so a
test can assert what the orchestrator sent (instructions, context, history, tool outputs) and what
it refused to execute.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.ai.gateway.tool_protocol import ToolCall, ToolTurnRequest, ToolTurnStep
from app.modules.ai.mia.access import (
    AccessDomain,
    DomainAccessPolicy,
    MembershipAccessPolicy,
    UserContext,
)
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry, default_registry
from app.modules.ai.mia.knowledge.types import Anchor, AnchorKind, EntryKind, KnowledgeEntry
from app.modules.ai.mia.tools.base import (
    ToolCatalog,
    ToolDefinition,
    ToolExecution,
    ToolExecutor,
    ToolRuntime,
)
from app.modules.ai.mia.tools.catalog import build_tool_catalog
from app.modules.ai.mia.types import Observation
from app.modules.ai.mia.ui_context import PageContext
from app.modules.tenancy.models import MembershipRole
from tests.decision_api_support import AuthedTenant
from tests.support import BookingFactory

AS_OF = date(2026, 8, 1)  # the business date every Mia world is anchored on (a Saturday)


@dataclass
class MiaWorld:
    """One tenant + one member + helpers to run tools exactly as the orchestrator would."""

    session: Session
    at: AuthedTenant
    as_of: date = AS_OF
    catalog: ToolCatalog = field(default_factory=build_tool_catalog)
    registry: KnowledgeRegistry = field(default_factory=default_registry)

    def runtime(
        self,
        *,
        access: DomainAccessPolicy | None = None,
        role: MembershipRole = MembershipRole.MEMBER,
        as_of: date | None = None,
        page: PageContext | None = None,
    ) -> ToolRuntime:
        prop = self.at.tenant.property
        return ToolRuntime(
            session=self.session,
            tenant=TenantContext(self.at.tenant.workspace.id),
            property_id=prop.id,
            property_name=prop.name,
            timezone=ZoneInfo(prop.timezone),
            currency=prop.currency,
            as_of=as_of or self.as_of,
            user=UserContext(self.at.user.id, role, "Luisa"),
            access=access or MembershipAccessPolicy(),
            registry=self.registry,
            page=page,
        )

    def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        runtime: ToolRuntime | None = None,
    ) -> ToolExecution:
        executor = ToolExecutor(self.catalog, runtime or self.runtime())
        return executor.execute(ToolCall(call_id="call-1", name=name, arguments=arguments or {}))

    def ok(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        runtime: ToolRuntime | None = None,
    ) -> dict[str, Any]:
        """The observation of a call that must succeed, as the model would read it."""
        execution = self.call(name, arguments, runtime=runtime)
        assert not execution.outcome.is_error, execution.outcome.content
        payload: dict[str, Any] = json.loads(execution.outcome.content)
        return payload


def mia_world(factory: BookingFactory, db_session: Session) -> MiaWorld:
    tenant = factory.tenant()
    user = factory.user()
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    return MiaWorld(db_session, AuthedTenant(tenant, user))


def answer(
    text: str = "Risposta di prova.",
    *,
    refs: tuple[str, ...] = ("knowledge:general",),
    status: ModelAnswerStatus = ModelAnswerStatus.ANSWERED,
    limitations: tuple[str, ...] = (),
) -> ToolTurnStep:
    return ToolTurnStep(
        answer=LanguageModelAnswer(
            status=status, answer=text, grounding_refs=refs, limitations=limitations
        )
    )


def tools(*calls: tuple[str, dict[str, Any]]) -> ToolTurnStep:
    return ToolTurnStep(
        tool_calls=tuple(
            ToolCall(call_id=f"toolu_{index}", name=name, arguments=arguments)
            for index, (name, arguments) in enumerate(calls, start=1)
        )
    )


@dataclass
class ScriptedToolProvider:
    """Plays `script` step by step. An entry may be a `ToolTurnStep`, an exception to raise, or a
    callable receiving the request (to build a step from what the orchestrator really sent)."""

    script: Sequence[ToolTurnStep | Exception | Callable[[ToolTurnRequest], ToolTurnStep]]
    requests: list[ToolTurnRequest] = field(default_factory=list)
    # True once the orchestrator asked for a step the script did not contain: a test that expects a
    # failure for a REASON must also assert this is False, or it passes by script exhaustion.
    ran_out: bool = False

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self.script):
            self.ran_out = True
            raise LanguageModelUnavailableError("scripted provider ran out of steps")
        entry = self.script[index]
        if isinstance(entry, Exception):
            raise entry
        if callable(entry):
            return entry(request)
        return entry

    @property
    def last_request(self) -> ToolTurnRequest:
        return self.requests[-1]


# --- a small FAKE catalog: the loop and the API are tested without depending on the real tools ---


class WindowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: Literal[7, 30] = 30


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallCounter:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1


def fake_tool_catalog(counter: CallCounter) -> ToolCatalog:
    def occupancy(runtime: ToolRuntime, args: WindowArgs) -> Observation:
        counter.hit("get_occupancy_revenue")
        return Observation(
            tool="get_occupancy_revenue",
            refs=("dati:occupazione",),
            data={"occupazione_percentuale": "62.50", "camere_prenotate": 25},
            coverage={"notti_richieste": 30, "notti_con_dati": 7, "completa": False},
            freshness={"ultimo_import": "2026-07-31T07:15:00+00:00"},
            not_available=(),
            notes=("sulle prenotazioni attuali",),
            resolved={"window": args.window},
        )

    def costs(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("get_cost_metrics")
        return Observation("get_cost_metrics", ("dati:costi",), {"costo_netto": "8100.00"})

    def labor(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("get_staff_metrics")
        return Observation("get_staff_metrics", ("dati:personale",), {"ore_pianificate": "320.00"})

    def distribution(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("get_distribution")
        return Observation("get_distribution", ("dati:distribuzione",), {"quota_ota": "41.00"})

    def help_(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("get_page_help")
        return Observation(
            "get_page_help", ("knowledge:ninfa:nav.dati",), {"titolo": "Dati"}, kind="product"
        )

    def status(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("get_data_status")
        return Observation("get_data_status", ("stato:analisi",), {"stato": "analisi parziale"})

    def boom(runtime: ToolRuntime, args: NoArgs) -> Observation:
        counter.hit("explode")
        raise RuntimeError("SECRET-TEXT-FROM-A-FAILING-READ")

    return ToolCatalog(
        [
            ToolDefinition(
                "get_occupancy_revenue", "occ", AccessDomain.REVENUE, WindowArgs, occupancy
            ),
            ToolDefinition("get_cost_metrics", "costs", AccessDomain.COSTS, NoArgs, costs),
            ToolDefinition("get_staff_metrics", "labor", AccessDomain.LABOR, NoArgs, labor),
            ToolDefinition(
                "get_distribution", "dist", AccessDomain.DISTRIBUTION, NoArgs, distribution
            ),
            ToolDefinition("get_page_help", "help", AccessDomain.PRODUCT, NoArgs, help_),
            ToolDefinition("get_data_status", "status", None, NoArgs, status),
            ToolDefinition("explode", "boom", AccessDomain.COMPANY, NoArgs, boom),
        ]
    )


def small_registry() -> KnowledgeRegistry:
    """A tiny registry of known routes and one metric, so tests of the page context do not depend on
    the content of the real one."""

    def entry(entry_id: str, kind: EntryKind, title: str, **kwargs: Any) -> KnowledgeEntry:
        anchor = Anchor(AnchorKind.DOC, "docs/architecture/architecture-v1.md")
        return KnowledgeEntry(entry_id, kind, title, title, (anchor,), **kwargs)

    return KnowledgeRegistry(
        [
            entry("nav.oggi", EntryKind.SECTION, "Oggi", route="/oggi"),
            entry("nav.dati", EntryKind.SECTION, "Dati", route="/dati"),
            entry(
                "dati.costs", EntryKind.SUBSECTION, "Costi", route="/dati", query={"tab": "costs"}
            ),
            entry(
                "nav.decision_detail",
                EntryKind.SECTION,
                "Dettaglio della Decision",
                route="/oggi/decisioni/[decisionId]",
            ),
            entry("metric.occupancy", EntryKind.METRIC, "Occupazione"),
        ]
    )


def new_user_context(role: MembershipRole = MembershipRole.MEMBER) -> UserContext:
    return UserContext(uuid4(), role, None)


__all__ = [
    "AS_OF",
    "CallCounter",
    "MiaWorld",
    "ScriptedToolProvider",
    "answer",
    "fake_tool_catalog",
    "mia_world",
    "small_registry",
    "new_user_context",
    "tools",
]

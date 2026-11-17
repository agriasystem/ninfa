"""What Mia is told about the SCREEN the person is looking at: a structured, bounded HINT.

The browser sends a small, closed object (the route, the section/tab, the period, the metric, a
decision or an import the person selected). Never a DOM, never HTML, never free text beyond a few
bounded identifiers. The server then VALIDATES it - every id is looked up in the authenticated
person's own workspace and property, every route and metric against the Product Knowledge Registry -
and drops whatever does not check out, silently and without saying which part was wrong (a foreign
decision id and a missing one are the same thing). What survives becomes a `PageContext`, written to
the model as DATA in its own block.

It is a hint and nothing more: "the person is on Dati > Personale and writes 'why is it so high?'"
tells Mia which figure the person probably means; the figure itself still comes from the tools.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.semantic_labels import decision_label_of, decision_status_label_of
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry
from app.modules.ai.mia.labels import data_domain_label, import_status_label
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository

_SAFE_ID = r"^[A-Za-z0-9_.:\-]+$"

ENTITY_KINDS = frozenset({"night", "data_source", "cost_category", "labor_category", "channel"})
PERIOD_DAYS = frozenset({7, 30})


class UiContext(BaseModel):
    """What the browser may say about the screen. Unknown keys are ignored (a newer frontend must
    not break an older backend); every value is bounded; nothing here is trusted."""

    model_config = ConfigDict(extra="ignore")

    route: str | None = Field(default=None, max_length=80)
    section: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_\-]+$")
    period_days: int | None = Field(default=None, ge=1, le=366)
    date_from: date | None = None
    date_to: date | None = None
    selected_metric: str | None = Field(default=None, max_length=60, pattern=_SAFE_ID)
    decision_id: UUID | None = None
    import_id: UUID | None = None
    entity_kind: str | None = Field(default=None, max_length=24, pattern=r"^[a-z_]+$")
    entity_id: str | None = Field(default=None, max_length=64, pattern=_SAFE_ID)


@dataclass(frozen=True, slots=True)
class DecisionHint:
    decision_id: str
    title: str
    status: str
    first_seen: str
    last_evaluated: str


@dataclass(frozen=True, slots=True)
class ImportHint:
    import_id: str
    status: str
    kind_of_data: str
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class PageContext:
    """The validated screen of the person. Every field is something the server verified."""

    route: str | None = None
    page_title: str | None = None
    section: str | None = None
    section_title: str | None = None
    period_days: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    metric_id: str | None = None
    metric_title: str | None = None
    decision: DecisionHint | None = None
    import_hint: ImportHint | None = None
    entity_kind: str | None = None
    entity_id: str | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            getattr(self, name) is None
            for name in (
                "route",
                "section",
                "period_days",
                "date_from",
                "metric_id",
                "decision",
                "import_hint",
                "entity_kind",
            )
        )

    def to_json(self) -> str:
        data: dict[str, object] = {}
        if self.page_title is not None:
            data["pagina"] = self.page_title
        if self.route is not None:
            data["percorso"] = self.route
        if self.section_title is not None:
            data["sezione"] = self.section_title
        elif self.section is not None:
            data["sezione"] = self.section
        if self.period_days is not None:
            data["periodo_giorni"] = self.period_days
        if self.date_from is not None:
            data["dal"] = self.date_from.isoformat()
        if self.date_to is not None:
            data["al"] = self.date_to.isoformat()
        if self.metric_id is not None:
            data["metrica_selezionata"] = {"id": self.metric_id, "nome": self.metric_title}
        if self.decision is not None:
            data["decisione_selezionata"] = {
                "id": self.decision.decision_id,
                "titolo": self.decision.title,
                "stato": self.decision.status,
                "vista_la_prima_volta": self.decision.first_seen,
                "valutata_l_ultima_volta": self.decision.last_evaluated,
            }
        if self.import_hint is not None:
            data["import_selezionato"] = {
                "id": self.import_hint.import_id,
                "stato": self.import_hint.status,
                "tipo_di_dati": self.import_hint.kind_of_data,
                "terminato": self.import_hint.finished_at,
            }
        if self.entity_kind is not None:
            data["elemento_selezionato"] = {"tipo": self.entity_kind, "id": self.entity_id}
        return json.dumps(data, ensure_ascii=False, sort_keys=True)


_ROUTE_TEMPLATE = re.compile(r"^/oggi/decisioni/[^/]+$")


def _canonical_route(route: str | None) -> str | None:
    """The route as the registry knows it: a decision detail path of any id is the template."""
    if route is None:
        return None
    path = route.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
    if _ROUTE_TEMPLATE.match(path):
        return "/oggi/decisioni/[decisionId]"
    return path


def build_page_context(
    session: Session,
    tenant: TenantContext,
    property_id: UUID,
    ui: UiContext | None,
    registry: KnowledgeRegistry,
) -> PageContext:
    """The validated `PageContext` of a request. Never raises for bad input: it drops it."""
    if ui is None:
        return PageContext()

    route = _canonical_route(ui.route)
    page = registry.for_page(route) if route is not None else None
    if page is None:
        route = None

    # A section only means something inside a page the registry knows, and only if the registry has
    # that block of the page: anything else is dropped (never kept as the raw string the browser
    # sent).
    section: str | None = None
    section_entry = None
    if route is not None and ui.section is not None:
        found = registry.for_page(route, _section_query(route, ui.section))
        if found is not None and found.query:
            section, section_entry = ui.section, found

    metric = registry.get(ui.selected_metric) if ui.selected_metric else None
    if metric is not None and metric.id not in registry.metric_ids():
        metric = None

    period = ui.period_days if ui.period_days in PERIOD_DAYS else None
    date_from, date_to = ui.date_from, ui.date_to
    if date_from is not None and date_to is not None and date_to < date_from:
        date_from = date_to = None

    decision_hint = _decision_hint(session, tenant, property_id, ui.decision_id)
    import_hint = _import_hint(session, tenant, property_id, ui.import_id)
    entity_kind = ui.entity_kind if ui.entity_kind in ENTITY_KINDS else None

    return PageContext(
        route=route,
        page_title=None if page is None else page.title,
        section=section,
        section_title=None if section_entry is None else section_entry.title,
        period_days=period,
        date_from=date_from,
        date_to=date_to,
        metric_id=None if metric is None else metric.id,
        metric_title=None if metric is None else metric.title,
        decision=decision_hint,
        import_hint=import_hint,
        entity_kind=entity_kind,
        entity_id=ui.entity_id if entity_kind is not None else None,
    )


def _section_query(route: str, section: str) -> Mapping[str, str]:
    """A section id is a Dati tab (`?tab=`) on /dati; elsewhere it is matched by the registry's own
    `query` of the same name."""
    return {"tab": section} if route == "/dati" else {"section": section}


def _decision_hint(
    session: Session, tenant: TenantContext, property_id: UUID, decision_id: UUID | None
) -> DecisionHint | None:
    if decision_id is None:
        return None
    decision = DecisionMemoryService(session, tenant).get_decision(decision_id)
    if decision is None or decision.property_id != property_id:
        return None
    return DecisionHint(
        decision_id=str(decision.id),
        title=decision_label_of(decision.decision_type),
        status=decision_status_label_of(decision.status),
        first_seen=decision.first_seen_local_date.isoformat(),
        last_evaluated=decision.last_evaluated_local_date.isoformat(),
    )


def _import_hint(
    session: Session, tenant: TenantContext, property_id: UUID, import_id: UUID | None
) -> ImportHint | None:
    if import_id is None:
        return None
    job = ImportJobRepository(session, tenant).get(import_id)
    if job is None or job.property_id != property_id:
        return None
    source = DataSourceRepository(session, tenant).get(job.data_source_id)
    return ImportHint(
        import_id=str(job.id),
        status=import_status_label(job.status),
        kind_of_data=data_domain_label(source.domain) if source is not None else "non noto",
        finished_at=None if job.finished_at is None else job.finished_at.isoformat(),
    )


__all__ = [
    "DecisionHint",
    "ImportHint",
    "PageContext",
    "UiContext",
    "build_page_context",
]

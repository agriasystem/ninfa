"""The page context: what the browser may say about the screen, and what the server keeps of it.

The browser's hint is bounded and untrusted: every id is looked up in the person's OWN workspace and
property, every route and metric is checked against the Product Knowledge Registry, and whatever
does not check out is dropped - silently, so a foreign id and a missing one are the same thing. What
survives is written to the model as data in its own block; it is a hint about what the person means,
never a source of facts."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry
from app.modules.ai.mia.knowledge.types import (
    Anchor,
    AnchorKind,
    EntryKind,
    KnowledgeEntry,
)
from app.modules.ai.mia.ui_context import PageContext, UiContext, build_page_context
from app.modules.decision_memory.service import DecisionMemoryService
from tests.ask_home_support import D1, five_triggered_evaluations, sync_feed
from tests.support import BookingFactory


def _entry(entry_id: str, kind: EntryKind, title: str, **kwargs: object) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=entry_id,
        kind=kind,
        title=title,
        summary=title,
        anchors=(Anchor(AnchorKind.DOC, "docs/architecture/architecture-v1.md"),),
        **kwargs,  # type: ignore[arg-type]
    )


REGISTRY = KnowledgeRegistry(
    [
        _entry("nav.oggi", EntryKind.SECTION, "Oggi", route="/oggi"),
        _entry("nav.dati", EntryKind.SECTION, "Dati", route="/dati"),
        _entry("dati.costs", EntryKind.SUBSECTION, "Costi", route="/dati", query={"tab": "costs"}),
        _entry(
            "dati.labor", EntryKind.SUBSECTION, "Personale", route="/dati", query={"tab": "labor"}
        ),
        _entry(
            "nav.decision_detail",
            EntryKind.SECTION,
            "Dettaglio della Decision",
            route="/oggi/decisioni/[decisionId]",
        ),
        _entry("nav.importa", EntryKind.SECTION, "Importa file", route="/importa-file"),
        _entry("metric.occupancy", EntryKind.METRIC, "Occupazione"),
    ]
)


def _build(
    session: Session, tenant_ctx: TenantContext, property_id: object, ui: UiContext | None
) -> PageContext:
    return build_page_context(session, tenant_ctx, property_id, ui, REGISTRY)  # type: ignore[arg-type]


def test_the_browsers_object_is_lenient_about_what_it_ignores_and_strict_about_size() -> None:
    parsed = UiContext.model_validate({"route": "/dati", "a_field_from_the_future": {"x": 1}})
    assert parsed.route == "/dati"

    with pytest.raises(ValidationError):
        UiContext.model_validate({"route": "/" + "x" * 200})
    with pytest.raises(ValidationError):
        UiContext.model_validate({"section": "has space"})
    with pytest.raises(ValidationError):
        UiContext.model_validate({"selected_metric": "<script>"})
    with pytest.raises(ValidationError):
        UiContext.model_validate({"decision_id": "not-a-uuid"})
    with pytest.raises(ValidationError):
        UiContext.model_validate({"entity_id": "a" * 100})


def test_no_context_is_an_empty_one(factory: BookingFactory, db_session: Session) -> None:
    tenant = factory.tenant()

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, None)

    assert page.is_empty and page.to_json() == "{}"


def test_a_valid_screen_survives_with_the_names_the_person_sees(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate(
        {
            "route": "/dati",
            "section": "costs",
            "period_days": 7,
            "date_from": "2026-08-01",
            "date_to": "2026-08-07",
            "selected_metric": "metric.occupancy",
        }
    )

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert not page.is_empty
    assert (page.page_title, page.section_title) == ("Dati", "Costi")
    assert page.period_days == 7
    assert page.metric_title == "Occupazione"
    data = json.loads(page.to_json())
    assert data["pagina"] == "Dati" and data["sezione"] == "Costi"
    assert data["metrica_selezionata"] == {"id": "metric.occupancy", "nome": "Occupazione"}
    assert data["dal"] == "2026-08-01" and data["al"] == "2026-08-07"


def test_what_does_not_check_out_is_dropped_without_saying_what(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate(
        {
            "route": "/pagina-che-non-esiste",
            "section": "costs",  # a section of a page that does not exist
            "period_days": 14,  # only 7 and 30 exist
            "date_from": "2026-08-07",
            "date_to": "2026-08-01",  # backwards
            "selected_metric": "metric.invented",
            "entity_kind": "dragon",
        }
    )

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert page.is_empty
    assert page.date_from is None and page.date_to is None


def test_a_section_the_page_does_not_have_is_dropped_but_the_page_stays(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate({"route": "/dati", "section": "weather"})

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert page.page_title == "Dati" and page.section is None


def test_a_selected_metric_must_be_a_metric_not_any_entry(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate({"route": "/dati", "selected_metric": "nav.dati"})

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert page.metric_id is None


def test_a_decision_detail_path_of_any_id_is_the_decision_page(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate({"route": f"/oggi/decisioni/{uuid4()}?property=x#why"})

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert page.route == "/oggi/decisioni/[decisionId]"
    assert page.page_title == "Dettaglio della Decision"


def test_a_decision_of_this_property_is_a_hint_in_plain_italian(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = TenantContext(tenant.workspace.id)
    feed = DecisionMemoryService(db_session, context).get_feed(tenant.property.id, D1)
    decision = feed.items[0].decision
    ui = UiContext.model_validate({"decision_id": str(decision.id)})

    page = _build(db_session, context, tenant.property.id, ui)

    assert page.decision is not None
    assert page.decision.decision_id == str(decision.id)
    assert page.decision.title and page.decision.title.upper() != page.decision.title
    text = page.to_json()
    # no internal vocabulary reaches the model through the hint
    for code in ("OPEN", "RESOLVED", decision.decision_type.value):
        assert code not in text


def test_a_decision_of_another_workspace_or_property_or_nowhere_is_the_same_nothing(
    factory: BookingFactory, db_session: Session
) -> None:
    mine, other = factory.tenant(), factory.tenant()
    sync_feed(db_session, other, five_triggered_evaluations(factory, other))
    sync_feed(db_session, mine, five_triggered_evaluations(factory, mine))
    foreign = (
        DecisionMemoryService(db_session, TenantContext(other.workspace.id))
        .get_feed(other.property.id, D1)
        .items[0]
        .decision
    )
    # a second property of the SAME workspace
    sibling = factory.property(mine.workspace)
    sibling_tenant = TenantContext(mine.workspace.id)

    for decision_id in (foreign.id, uuid4()):
        ui = UiContext.model_validate({"decision_id": str(decision_id)})
        page = _build(db_session, TenantContext(mine.workspace.id), mine.property.id, ui)
        assert page.decision is None

    own = (
        DecisionMemoryService(db_session, sibling_tenant)
        .get_feed(mine.property.id, D1)
        .items[0]
        .decision
    )
    ui = UiContext.model_validate({"decision_id": str(own.id)})
    assert _build(db_session, sibling_tenant, sibling.id, ui).decision is None


def test_an_import_of_this_property_is_a_hint_and_a_foreign_one_is_nothing(
    factory: BookingFactory, db_session: Session
) -> None:
    mine, other = factory.tenant(), factory.tenant()
    context = TenantContext(mine.workspace.id)

    own = _build(
        db_session,
        context,
        mine.property.id,
        UiContext.model_validate({"import_id": str(mine.import_job.id)}),
    )
    foreign = _build(
        db_session,
        context,
        mine.property.id,
        UiContext.model_validate({"import_id": str(other.import_job.id)}),
    )

    assert own.import_hint is not None
    assert own.import_hint.kind_of_data == "prenotazioni"
    assert own.import_hint.status in {"in attesa", "in corso", "completato", "non riuscito"}
    assert foreign.import_hint is None
    assert "BOOKINGS" not in own.to_json() and "PENDING" not in own.to_json()


def test_an_import_of_a_sibling_property_is_nothing_too(
    factory: BookingFactory, db_session: Session
) -> None:
    mine = factory.tenant()
    sibling = factory.property(mine.workspace)
    context = TenantContext(mine.workspace.id)

    page = _build(
        db_session,
        context,
        sibling.id,
        UiContext.model_validate({"import_id": str(mine.import_job.id)}),
    )

    assert page.import_hint is None


def test_an_entity_of_a_known_kind_is_kept_as_a_hint(
    factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    ui = UiContext.model_validate({"entity_kind": "night", "entity_id": "2026-08-07"})

    page = _build(db_session, TenantContext(tenant.workspace.id), tenant.property.id, ui)

    assert json.loads(page.to_json())["elemento_selezionato"] == {
        "tipo": "night",
        "id": "2026-08-07",
    }

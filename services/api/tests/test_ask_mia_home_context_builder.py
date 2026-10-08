"""Mia Home (Home UI V1, ADR 0028): the context is built ONLY from
`DecisionMemoryService.get_feed()` - real persisted runs read back through the real service,
never a hand-built feed shape.
"""

import json
import re
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.home_context_builder import (
    DOMAIN_OF_DECISION_TYPE,
    AskHomeContextBuilder,
)
from app.modules.ai.ask_ninfa.home_serialization import home_context_to_dict, serialize_home_context
from app.modules.ai.ask_ninfa.home_types import MAX_HOME_DECISIONS, AskHomeContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.intelligence.priority.types import PriorityDecisionType
from tests.ask_home_support import (
    D1,
    booking_only_coverage,
    five_triggered_evaluations,
    full_coverage,
    known_provenance,
    sync_feed,
    unknown_provenance,
    utc,
)
from tests.decision_support import CLEAR, INSUFFICIENT, Evaluation, revenue_evaluation
from tests.support import BookingFactory, Tenant

ROME = ZoneInfo("Europe/Rome")


def _context(
    db_session: Session, tenant: Tenant, as_of: date = D1, zone: ZoneInfo = ROME
) -> AskHomeContext:
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    feed = memory.get_feed(tenant.property.id, as_of)
    return AskHomeContextBuilder().build(feed, zone)


def _feed_order(db_session: Session, tenant: Tenant) -> list[PriorityDecisionType]:
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    return [item.decision.decision_type for item in memory.get_feed(tenant.property.id, D1).items]


# --- the type -> area mapping is exhaustive -------------------------------------------------------


def test_every_decision_type_belongs_to_exactly_one_area() -> None:
    assert set(DOMAIN_OF_DECISION_TYPE) == set(PriorityDecisionType)


# --- decisions: engine order, ordinals, areas --------------------------------------------------


def test_decisions_keep_the_engine_order_and_are_named_by_ordinal_word(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    expected_order = _feed_order(db_session, tenant)
    assert context.decisions_total == 5
    assert context.decisions_omitted == 0
    assert len(context.decisions) == 5
    assert [item.position for item in context.decisions] == [
        "prima",
        "seconda",
        "terza",
        "quarta",
        "quinta",
    ]
    # Same order as the feed itself: the labels are the Decision Ask's own semantic titles.
    from app.modules.ai.ask_ninfa.semantic_labels import decision_label_of

    assert [item.decision_label for item in context.decisions] == [
        decision_label_of(decision_type) for decision_type in expected_order
    ]


def test_each_decision_carries_its_user_facing_area(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    areas = sorted({item.area for item in context.decisions})
    assert areas == ["Costi", "Distribuzione", "Personale", "Ricavi"]


def test_more_than_the_cap_are_cut_and_the_omission_is_stated(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluations: list[Evaluation] = [
        revenue_evaluation(
            workspace_id=tenant.workspace.id,
            property_id=tenant.property.id,
            data_source_id=tenant.data_source.id,
            stay_date=date(2026, 8, 10 + offset),
            snapshot_local_date=D1,
        )
        for offset in range(MAX_HOME_DECISIONS + 2)
    ]
    sync_feed(db_session, tenant, evaluations)
    context = _context(db_session, tenant)

    assert context.decisions_total == MAX_HOME_DECISIONS + 2
    assert len(context.decisions) == MAX_HOME_DECISIONS
    assert context.decisions_omitted == 2
    payload = home_context_to_dict(context)
    assert payload["numero di decisioni che richiedono attenzione"] == MAX_HOME_DECISIONS + 2
    assert payload["decisioni non mostrate"] == 2


# --- economic impact: only what the engine already recorded -------------------------------------


def test_economic_impact_is_only_what_the_engine_recorded_and_always_indicative(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    by_label = {item.decision_label: item for item in context.decisions}
    cost = by_label["Costo per camera anomalo"]
    [cost_impact] = cost.economic_impact
    assert cost_impact.unit == "euro"  # a real currency the engine recorded
    assert "stima indicativa" in cost_impact.label

    pickup = by_label["Pickup sotto le attese"]
    [pickup_impact] = pickup.economic_impact
    assert pickup_impact.unit is None  # revenue proxies carry no currency - none is invented
    assert "stima indicativa" in pickup_impact.label

    for item in context.decisions:
        for impact in item.economic_impact:
            assert "stima indicativa" in impact.label


# --- no internal identifier, no raw payload, no null-as-text ------------------------------

_FORBIDDEN_MARKERS = (
    "decision_id",
    "workspace_id",
    "property_id",
    "data_source_id",
    "fingerprint",
    "observation_id",
    "REV_PICKUP_LOW",
    "REV_OCCUPANCY_RISK",
    "REV_OTA_DEPENDENCY",
    "COST_CPOR_ANOMALY",
    "LABOR_OVERSTAFFING",
    "SKIPPED",
    "EVALUATED",
    "NOT_REQUESTED",
    "ACTION_REQUIRED",
    "feed_state",
    "priority_rank",
    "priority_score",
    "reason_codes",
    "HOUSEKEEPING",
    "LAUNDRY",
)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def test_the_serialized_context_never_leaks_an_internal_identifier(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        five_triggered_evaluations(factory, tenant),
        coverage=booking_only_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),
    )
    serialized = serialize_home_context(_context(db_session, tenant))

    for marker in _FORBIDDEN_MARKERS:
        assert marker not in serialized, marker
    assert not _UUID.search(serialized)
    assert str(tenant.property.id) not in serialized
    assert "None" not in serialized  # a null fact must never surface as the literal word


def test_no_snake_case_key_can_be_echoed_by_the_model(
    db_session: Session, factory: BookingFactory
) -> None:
    """The keys are plain Italian phrases: the technical-leak check (which fails closed on any
    snake_case word) must never have a context-derived reason to fire."""
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    keys: set[str] = set()

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                keys.add(key)
                _collect(value)
        elif isinstance(node, list):
            for value in node:
                _collect(value)

    _collect(json.loads(serialize_home_context(_context(db_session, tenant))))
    assert keys
    assert not [key for key in keys if "_" in key]


def test_the_serialization_is_deterministic(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    first = serialize_home_context(_context(db_session, tenant))
    second = serialize_home_context(_context(db_session, tenant))
    assert first == second


# --- coverage ------------------------------------------------------------------------------------


def test_partial_coverage_names_the_skipped_areas(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        five_triggered_evaluations(factory, tenant)[:3],
        coverage=booking_only_coverage(),
    )
    coverage = _context(db_session, tenant).coverage
    assert coverage is not None
    assert coverage.summary_label == "alcune aree non sono state analizzate"
    assert {(item.area, item.status_label) for item in coverage.areas} == {
        ("Ricavi", "analizzata"),
        ("Distribuzione", "analizzata"),
        ("Costi", "non analizzata"),
        ("Personale", "non analizzata"),
    }


def test_full_coverage_summary(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session, tenant, five_triggered_evaluations(factory, tenant), coverage=full_coverage()
    )
    coverage = _context(db_session, tenant).coverage
    assert coverage is not None
    assert coverage.summary_label == "tutte le aree sono state analizzate"
    assert all(item.status_label == "analizzata" for item in coverage.areas)


def test_a_run_without_recorded_coverage_is_unknown_never_inferred(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))  # coverage=None
    coverage = _context(db_session, tenant).coverage
    assert coverage is not None
    assert "non disponibile" in coverage.summary_label
    assert coverage.areas == ()


# --- freshness: a plain fact, in the PROPERTY's timezone ------------------------------


def test_an_import_of_the_same_local_day_is_oggi_in_property_time(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    # 22:30 UTC on 31 July is 00:30 on 1 August in Rome (UTC+2): the UTC date is the PREVIOUS day.
    sync_feed(
        db_session,
        tenant,
        five_triggered_evaluations(factory, tenant)[:1],
        provenance=known_provenance(utc(2026, 7, 31, 22, 30)),
    )
    freshness = _context(db_session, tenant).freshness
    assert freshness is not None and freshness.known
    assert freshness.local_date == "2026-08-01"
    assert freshness.local_time == "00:30"
    assert freshness.relative_day == "oggi"


def test_an_import_of_the_previous_local_day_is_ieri(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        five_triggered_evaluations(factory, tenant)[:1],
        provenance=known_provenance(utc(2026, 7, 31, 20, 15)),  # 22:15 in Rome
    )
    freshness = _context(db_session, tenant).freshness
    assert freshness is not None
    assert (freshness.local_date, freshness.local_time, freshness.relative_day) == (
        "2026-07-31",
        "22:15",
        "ieri",
    )


def test_an_older_import_has_no_relative_day(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        five_triggered_evaluations(factory, tenant)[:1],
        provenance=known_provenance(utc(2026, 7, 20, 9, 0)),
    )
    freshness = _context(db_session, tenant).freshness
    assert freshness is not None and freshness.known
    assert freshness.relative_day is None
    assert freshness.local_date == "2026-07-20"


def test_unknown_freshness_never_invents_an_instant(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    for provenance in (None, unknown_provenance()):
        other = factory.tenant()
        sync_feed(
            db_session, other, five_triggered_evaluations(factory, other)[:1], provenance=provenance
        )
        freshness = _context(db_session, other).freshness
        assert freshness is not None
        assert not freshness.known
        assert (freshness.local_date, freshness.local_time, freshness.relative_day) == (
            None,
            None,
            None,
        )
    serialized = serialize_home_context(_context(db_session, other))
    assert "non disponibile per questa analisi" in serialized
    del tenant


# --- feed states ------------------------------------------------------------


def test_not_processed_has_no_decisions_no_coverage_and_no_freshness(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    context = _context(db_session, tenant)  # no run at all
    assert context.analysis_state == "L'analisi di oggi non è ancora disponibile"
    assert context.decisions == ()
    assert context.coverage is None and context.freshness is None
    assert context.insufficient_checks is None and context.low_confidence_checks is None
    assert context.last_successful_analysis_date is None
    payload = home_context_to_dict(context)
    assert payload["copertura dell'analisi"] is None
    assert payload["dati usati dall'analisi"] is None


def test_not_processed_after_an_earlier_run_names_its_business_date(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant)[:1], as_of=D1)
    context = _context(db_session, tenant, as_of=date(2026, 8, 3))  # no run for 3 August
    assert context.analysis_state == "L'analisi di oggi non è ancora disponibile"
    assert context.last_successful_analysis_date == "2026-08-01"
    assert context.coverage is None and context.freshness is None


def test_no_action_required_is_the_only_state_that_says_nothing_requires_attention(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=date(2026, 8, 15),
                snapshot_local_date=D1,
                status=CLEAR,
            )
        ],
    )
    context = _context(db_session, tenant)
    assert context.analysis_state == "Nessuna decisione richiede attenzione in questo momento"
    assert context.decisions == () and context.decisions_total == 0


def test_data_quality_limited_reports_check_counts_and_never_all_clear(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=date(2026, 8, 15),
                snapshot_local_date=D1,
                status=INSUFFICIENT,
            )
        ],
    )
    context = _context(db_session, tenant)
    assert context.analysis_state.startswith("Analisi parziale")
    assert "Nessuna decisione richiede attenzione" not in context.analysis_state
    assert context.decisions == ()
    assert context.insufficient_checks == 1
    assert context.low_confidence_checks == 0


def test_the_target_uses_plain_italian_keys_never_the_engines_own_identifiers(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    by_label = {item.decision_label: item for item in context.decisions}
    assert by_label["Pickup sotto le attese"].target == {"data del soggiorno": "2026-08-15"}
    assert set(by_label["Costo per camera anomalo"].target) == {
        "inizio del periodo",
        "categoria di costo",
    }
    assert by_label["Costo per camera anomalo"].target["categoria di costo"] == "Lavanderia"
    assert set(by_label["Ore di personale sopra l'atteso"].target) == {
        "giorno di lavoro",
        "reparto",
    }
    assert by_label["Dipendenza OTA"].target == {}


# --- v2: what Mia needs to answer concretely - a description and the KIND of each estimate ------


def test_every_decision_type_has_a_plain_description_and_an_impact_kind() -> None:
    from app.modules.ai.ask_ninfa.home_context_builder import _IMPACT_KINDS
    from app.modules.ai.ask_ninfa.semantic_labels import DECISION_TYPE_DESCRIPTIONS

    assert set(DECISION_TYPE_DESCRIPTIONS) == set(PriorityDecisionType)
    assert set(_IMPACT_KINDS) == set(PriorityDecisionType)
    for description in DECISION_TYPE_DESCRIPTIONS.values():
        assert description.endswith(".")
        assert not any(character.isdigit() for character in description)  # no number to misquote
        assert "_" not in description  # no technical token a model could echo
        assert description == description.strip()


def test_the_descriptions_state_no_recommendation_and_no_judgement_beyond_the_engines() -> None:
    from app.modules.ai.ask_ninfa.semantic_labels import DECISION_TYPE_DESCRIPTIONS

    for description in DECISION_TYPE_DESCRIPTIONS.values():
        lowered = description.lower()
        for forbidden in ("dovresti", "abbassa", "alza", "consigl", "urgente", "perdita", "grave"):
            assert forbidden not in lowered, (description, forbidden)
        assert "atteso" in lowered  # only the Engine's own "below/above the expected level"


def test_each_decision_carries_its_description_in_the_context(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    by_label = {item.decision_label: item for item in context.decisions}
    assert by_label["Pickup sotto le attese"].description == (
        "Le prenotazioni per il giorno di soggiorno indicato stanno arrivando "
        "sotto il ritmo atteso."
    )
    assert by_label["Dipendenza OTA"].description == (
        "La quota di prenotazioni da OTA è sopra il livello atteso."
    )
    assert len({item.description for item in context.decisions}) == 5
    serialized = json.loads(serialize_home_context(context))
    for payload in serialized["decisioni in ordine di priorità"]:
        assert payload["descrizione"]


def test_the_kind_of_an_estimate_is_named_only_where_an_estimate_exists(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    context = _context(db_session, tenant)

    by_label = {item.decision_label: item for item in context.decisions}
    # Revenue and cost estimates are recorded for these fixtures; the OTA and labour fixtures record
    # none, and a decision without an estimate claims no kind of estimate either.
    assert by_label["Pickup sotto le attese"].impact_kind == "ricavi"
    assert by_label["Rischio occupazione"].impact_kind == "ricavi"
    assert by_label["Costo per camera anomalo"].impact_kind == "costi"
    for item in context.decisions:
        assert (item.impact_kind is None) == (item.economic_impact == ())


def test_revenue_cost_and_ota_estimates_are_of_three_different_kinds() -> None:
    from app.modules.ai.ask_ninfa.home_context_builder import _IMPACT_KINDS

    assert (
        _IMPACT_KINDS[PriorityDecisionType.REV_PICKUP_LOW]
        == (_IMPACT_KINDS[PriorityDecisionType.REV_OCCUPANCY_RISK])
    )
    assert (
        _IMPACT_KINDS[PriorityDecisionType.COST_CPOR_ANOMALY]
        == (_IMPACT_KINDS[PriorityDecisionType.LABOR_OVERSTAFFING])
    )
    assert len(set(_IMPACT_KINDS.values())) == 3  # ricavi / ricavo esposto su OTA / costi


def test_the_new_keys_are_plain_italian_and_serialized_per_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(db_session, tenant, five_triggered_evaluations(factory, tenant))
    decisions = json.loads(serialize_home_context(_context(db_session, tenant)))[
        "decisioni in ordine di priorità"
    ]
    for decision in decisions:
        assert "descrizione" in decision
        assert "tipo di impatto economico" in decision
        # an estimate list and its kind are always present together or absent together
        assert (decision["tipo di impatto economico"] is None) == (
            decision["impatto economico"] == []
        )

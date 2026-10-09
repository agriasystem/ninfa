"""Mia V2 safe semantic data layer (`HomeDataService`): deterministic facts, read from stored
snapshots / existing services, scoped to the tenant and to the analysis the feed belongs to.

ENGINE CALCULATES. MIA EXPLAINS. Nothing here is computed by a model, and nothing leaves the service
but small labelled sections: no booking row, no id, no SQL. Real persisted runs and snapshots are
read back through the real repositories, exactly like production.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.home_context_builder import AskHomeContextBuilder
from app.modules.ai.ask_ninfa.home_data_service import HomeDataService, OtaEvaluator
from app.modules.ai.ask_ninfa.home_facts import OperationalContext, OperationalSection
from app.modules.ai.ask_ninfa.home_intents import resolve_question
from app.modules.ai.ask_ninfa.home_serialization import serialize_home_context
from app.modules.ai.ask_ninfa.home_types import grounding_vocabulary
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.intelligence.distribution.types import (
    EvaluationStatus,
    OtaDependencyEvaluation,
    ReasonCode,
)
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation
from tests.ask_home_support import (
    D1,
    booking_only_coverage,
    distribution_skipped_coverage,
    full_coverage,
    provenance_for,
    seed_night_snapshots,
    sync_feed,
    utc,
)
from tests.decision_support import (
    CLEAR,
    INSUFFICIENT,
    SUPPRESSED,
    TRIGGERED,
    Evaluation,
    ota_evaluation,
    revenue_evaluation,
)
from tests.distribution_support import ChannelType, DistributionWorld
from tests.support import BookingFactory, Tenant

ROME = ZoneInfo("Europe/Rome")
# 2026-08-01 is a Saturday
NIGHT_1 = D1


def _section(context: OperationalContext, ref: str) -> OperationalSection:
    [section] = [item for item in context.sections if item.ref == ref]
    return section


def _values(section: OperationalSection) -> dict[str, str]:
    return {point.label: point.value for point in section.data}


class _Evaluator:
    """A recording stand-in for the live OTA evaluation: returns what a test decides."""

    def __init__(self, evaluation: OtaDependencyEvaluation | Exception) -> None:
        self.evaluation = evaluation
        self.calls: list[tuple[UUID, UUID, date]] = []

    def __call__(self, property_id: UUID, source_id: UUID, as_of: date) -> OtaDependencyEvaluation:
        self.calls.append((property_id, source_id, as_of))
        if isinstance(self.evaluation, Exception):
            raise self.evaluation
        return self.evaluation


def _collect(
    db_session: Session,
    tenant: Tenant,
    question: str,
    *,
    as_of: date = D1,
    history: tuple[tuple[str, str], ...] = (),
    evaluator: OtaEvaluator | None = None,
    service_tenant: TenantContext | None = None,
) -> OperationalContext:
    from app.modules.ai.ask_ninfa.home_history import HistoryRole, HomeHistoryTurn

    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, as_of)
    turns = tuple(HomeHistoryTurn(HistoryRole(role), text) for role, text in history)
    resolution = resolve_question(question, turns, as_of)
    service = HomeDataService(db_session, service_tenant or tenant.context, ota_evaluator=evaluator)
    return service.collect(
        resolution,
        feed,
        property_id=tenant.property.id,
        timezone=ROME,
        currency=tenant.property.currency,
    )


def _revenue(tenant: Tenant, **kwargs: Any) -> RevenueDecisionEvaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=D1,
        stay_date=D1 + timedelta(days=14),
        **kwargs,
    )


def _ota(tenant: Tenant, status: EvaluationStatus = CLEAR) -> OtaDependencyEvaluation:
    return ota_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        as_of_local_date=D1,
        status=status,
    )


def _run(
    db_session: Session,
    tenant: Tenant,
    evaluations: Sequence[Evaluation] | None = None,
    *,
    coverage: AnalysisCoverage | None = None,
    with_provenance: bool = True,
) -> None:
    sync_feed(
        db_session,
        tenant,
        list(evaluations) if evaluations is not None else [_ota(tenant)],
        coverage=coverage if coverage is not None else full_coverage(),
        provenance=provenance_for(tenant, utc(2026, 8, 1, 7, 31)) if with_provenance else None,
    )


def _week(rooms: list[int], available: int | None = 40) -> dict[date, tuple[int, int | None]]:
    return {
        NIGHT_1 + timedelta(days=index): (value, available) for index, value in enumerate(rooms)
    }


# --- occupancy / bookings / revenue, from the stored snapshots ---------------------------------


def test_occupancy_of_the_next_seven_days_is_a_deterministic_ratio_of_stored_numbers(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 20, 30, 40, 0, 20, 20]))

    context = _collect(db_session, tenant, "Qual è l'occupazione dei prossimi 7 giorni?")

    section = _section(context, "metric:occupancy:2026-08-01:2026-08-07")
    assert section.period == "i prossimi 7 giorni (dal 1 agosto al 7 agosto)"
    values = _values(section)
    # (10+20+30+40+0+20+20) = 140 rooms on the books over 7 x 40 = 280 available -> 50.00 %
    assert values["Occupazione sulle prenotazioni attuali"] == "50.00"
    assert values["Camere prenotate (notti con capienza nota)"] == "140"
    assert values["Camere disponibili (notti con capienza nota)"] == "280"
    assert values["Notti con dati"] == "7 su 7"
    assert [point.unit for point in section.data if point.label.startswith("Occupazione")] == ["%"]
    assert "non l'occupazione finale né una previsione" in (section.note or "")
    assert context.topics == ("occupazione",)


def test_nights_with_an_unknown_capacity_are_left_out_of_the_ratio_and_counted(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    nights = _week([20, 20, 20])
    nights[NIGHT_1 + timedelta(days=2)] = (20, None)  # capacity not recorded for that night
    seed_night_snapshots(db_session, tenant, D1, nights)

    context = _collect(db_session, tenant, "Occupazione dei prossimi 3 giorni")

    values = _values(_section(context, "metric:occupancy:2026-08-01:2026-08-03"))
    assert values["Occupazione sulle prenotazioni attuali"] == "50.00"  # 40 / 80, not 60 / 80
    assert values["Notti con capienza nota"] == "2 su 3"
    assert values["Notti con dati"] == "3 su 3"


def test_no_recorded_capacity_means_no_occupancy_figure_never_a_zero(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10], available=None))

    context = _collect(db_session, tenant, "Occupazione dei prossimi 2 giorni")

    value = _values(_section(context, "metric:occupancy:2026-08-01:2026-08-02"))[
        "Occupazione sulle prenotazioni attuali"
    ]
    assert value.startswith("non disponibile")


def test_one_night_gives_bookings_and_rooms_for_that_night(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, {date(2026, 8, 8): (12, 40), D1: (5, 40)})

    # as_of is Saturday 1 August: "sabato" is today, "sabato prossimo" is not parsed - use a date
    context = _collect(db_session, tenant, "Quante prenotazioni ho l'8 agosto?")

    section = _section(context, "metric:bookings:2026-08-08:2026-08-08")
    values = _values(section)
    assert (
        values["Prenotazioni attive quella notte"] == "6"
    )  # the snapshot's own count (rooms // 2)
    assert values["Camere prenotate quella notte"] == "12"
    assert values["Notti con dati"] == "1 su 1"
    assert section.period == "sabato 8 agosto"


def test_a_multi_night_period_gives_room_nights_never_a_summed_booking_count(
    db_session: Session, factory: BookingFactory
) -> None:
    """`booking_count_on_books` is per NIGHT: summing it over several nights would count a multi-
    night booking once per night. Only room-nights are given for a period."""
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10, 10]))

    context = _collect(db_session, tenant, "Come vanno le prenotazioni dei prossimi 3 giorni?")

    labels = _values(_section(context, "metric:bookings:2026-08-01:2026-08-03"))
    assert labels["Camere-notte prenotate nel periodo"] == "30"
    assert "Prenotazioni attive quella notte" not in labels


def test_revenue_on_the_books_has_a_currency_an_adr_and_is_explicitly_not_fatturato(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(
        db_session, tenant, D1, _week([10, 20]), revenue_per_room=Decimal("120.00")
    )

    context = _collect(db_session, tenant, "Quanti ricavi nei prossimi 2 giorni?")

    section = _section(context, "metric:revenue:2026-08-01:2026-08-02")
    by_label = {point.label: point for point in section.data}
    revenue = by_label["Ricavi camera sulle prenotazioni attuali"]
    assert (revenue.value, revenue.unit) == ("3600.00", "euro")  # 30 rooms x 120
    adr = by_label["Tariffa media per camera-notte sulle prenotazioni attuali"]
    assert (adr.value, adr.unit) == ("120.00", "euro")
    assert "non sono fatturato né incassi" in (section.note or "")


def test_fatturato_is_answered_with_what_exists_and_what_does_not(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(
        db_session, tenant, D1, {D1 + timedelta(days=i): (10, 40) for i in range(0, 31)}
    )

    context = _collect(db_session, tenant, "Quanto ho fatturato questo mese?")

    assert any("NINFA non ha un dato di fatturato" in note for note in context.not_available)
    # the supported part is still given: room revenue on the books from today to the end of month
    assert _section(context, "metric:revenue:2026-08-01:2026-08-31")
    assert not any(section.ref.endswith("revenue-gap") for section in context.sections)


def test_the_weakest_nights_are_listed_lowest_occupancy_first_with_ties_by_date(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([30, 8, 40, 8, 20, 4, 16]))

    context = _collect(db_session, tenant, "Quali giorni sono più deboli nei prossimi 7 giorni?")

    section = _section(context, "metric:weakest-nights:2026-08-01:2026-08-07")
    assert [dict(row)["giorno"] for row in section.rows] == [
        "giovedì 6 agosto",  # 4 rooms -> 10.00 %
        "domenica 2 agosto",  # 8 rooms -> 20.00 %, the earlier of the two ties
        "martedì 4 agosto",  # 8 rooms -> 20.00 %
        "venerdì 7 agosto",  # 16 rooms -> 40.00 %
        "mercoledì 5 agosto",  # 20 rooms -> 50.00 %
    ]
    assert "ordinamento descrittivo" in (section.note or "")


def test_the_nightly_detail_is_a_table_of_stored_values_for_short_periods_only(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(
        db_session, tenant, D1, {D1 + timedelta(days=i): (10, 40) for i in range(0, 30)}
    )

    short = _collect(db_session, tenant, "Occupazione dei prossimi 7 giorni")
    detail = _section(short, "metric:nightly:2026-08-01:2026-08-07")
    assert len(detail.rows) == 7
    assert dict(detail.rows[0]) == {
        "giorno": "sabato 1 agosto",
        "camere prenotate": "10",
        "camere disponibili": "40",
        "occupazione %": "25.00",
    }
    long = _collect(db_session, tenant, "Occupazione dei prossimi 30 giorni")
    assert not [s for s in long.sections if s.ref.startswith("metric:nightly:")]  # too long a table


def test_without_a_named_period_the_next_seven_and_thirty_days_are_given(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(
        db_session, tenant, D1, {D1 + timedelta(days=i): (10, 40) for i in range(0, 30)}
    )

    context = _collect(db_session, tenant, "Come stanno andando le prenotazioni?")

    assert (_section(context, "metric:bookings:2026-08-01:2026-08-07").period or "").startswith(
        "i prossimi 7 giorni"
    )
    assert (_section(context, "metric:bookings:2026-08-01:2026-08-30").period or "").startswith(
        "i prossimi 30 giorni"
    )


def test_a_period_with_no_stored_nights_is_reported_as_missing_not_as_zero(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10]))

    context = _collect(db_session, tenant, "Occupazione del prossimo mese")  # September: no data

    assert not context.sections or all(
        not s.ref.startswith("metric:occupancy:") for s in context.sections
    )
    assert any(
        "nessun dato di prenotazione per il prossimo mese" in n for n in context.not_available
    )


def test_nights_before_the_analysis_day_are_not_described(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10]))

    context = _collect(db_session, tenant, "Com'era l'occupazione ieri?")

    assert any("precedenti al 1 agosto" in note for note in context.not_available)
    assert not any(s.ref.startswith("metric:occupancy:") for s in context.sections)


def test_snapshots_of_another_day_or_origin_are_never_mixed_in(
    db_session: Session, factory: BookingFactory
) -> None:
    from app.modules.snapshots.models import SnapshotOrigin
    from tests.expected_support import add_snapshots, snapshot_row

    tenant = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10]))
    # a snapshot taken the day BEFORE (other as-of) and a reconstructed one for the same night
    other_day = snapshot_row(tenant, D1 - timedelta(days=1), D1, rooms=39)
    reconstructed = snapshot_row(
        tenant,
        D1 + timedelta(days=1),
        D1,
        rooms=38,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
    )
    add_snapshots(db_session, tenant, [other_day, reconstructed])

    context = _collect(db_session, tenant, "Prenotazioni di oggi")

    values = _values(_section(context, "metric:bookings:2026-08-01:2026-08-01"))
    assert values["Camere prenotate quella notte"] == "10"


# --- availability of the analysis itself -------------------------------------------------------


def test_without_a_run_there_are_no_booking_facts_and_the_reason_is_stated(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()  # no analysis at all

    context = _collect(db_session, tenant, "Qual è l'occupazione dei prossimi 7 giorni?")

    assert not any(s.ref.startswith("metric:") for s in context.sections)
    assert any("analisi di oggi non è ancora disponibile" in n for n in context.not_available)


def test_a_run_that_predates_provenance_cannot_name_a_booking_source(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, with_provenance=False)
    seed_night_snapshots(db_session, tenant, D1, _week([10]))

    context = _collect(db_session, tenant, "Prenotazioni di oggi")

    assert not any(s.ref.startswith("metric:") for s in context.sections)
    assert any(
        "origine dei dati di prenotazione non è registrata" in n for n in context.not_available
    )


def test_the_booking_source_is_the_one_the_run_recorded_never_another(
    db_session: Session, factory: BookingFactory
) -> None:
    """Snapshots of a DIFFERENT data source of the same property are never read: the source comes
    from the run's own provenance."""
    tenant = factory.tenant()
    other_source = factory.data_source(tenant.property)
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10]))
    from tests.expected_support import add_snapshots, snapshot_row

    add_snapshots(
        db_session,
        tenant,
        [
            snapshot_row(
                tenant, D1, D1 + timedelta(days=3), rooms=99, data_source_id=other_source.id
            )
        ],
    )

    context = _collect(db_session, tenant, "Prenotazioni dei prossimi 7 giorni")

    values = _values(_section(context, "metric:bookings:2026-08-01:2026-08-07"))
    assert values["Notti con dati"] == "1 su 7"
    assert values["Camere-notte prenotate nel periodo"] == "10"


# --- tenant isolation --------------------------------------------------------------------------


def test_another_tenants_service_cannot_read_this_tenants_snapshots(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    stranger = factory.tenant()
    _run(db_session, tenant)
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10, 10]))

    # The run (and so the source id) belong to `tenant`; the SERVICE is scoped to `stranger`.
    context = _collect(
        db_session,
        tenant,
        "Prenotazioni dei prossimi 3 giorni",
        service_tenant=stranger.context,
    )

    assert not any(s.ref.startswith("metric:bookings") for s in context.sections)
    assert any("nessun dato di prenotazione" in n for n in context.not_available)


def test_another_tenants_service_cannot_read_this_tenants_channels(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    stranger = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    booking = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(booking, D1, D1 + timedelta(days=10), rooms=5)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    ok = _collect(db_session, tenant, "Quanto pesa Booking?", evaluator=_Evaluator(_ota(tenant)))
    assert _section(ok, "metric:channel-mix:2026-08-01")

    foreign = _collect(
        db_session,
        tenant,
        "Quanto pesa Booking?",
        evaluator=_Evaluator(_ota(tenant)),
        service_tenant=stranger.context,
    )
    assert not [s for s in foreign.sections if s.ref.startswith("metric:channel-mix")]


# --- distribution: the four cases of "Gli OTA sono a posto?" -----------------------------------


def test_case_a_a_decision_exists_and_no_live_evaluation_is_needed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, TRIGGERED)])
    evaluator = _Evaluator(_ota(tenant, CLEAR))

    context = _collect(db_session, tenant, "Gli OTA sono a posto?", evaluator=evaluator)

    area = _section(context, "coverage:distribution")
    values = _values(area)
    assert values["Area analizzata oggi"] == "analizzata"
    assert values["Decisioni sulla dipendenza OTA"] == "1"
    assert "almeno una decisione" in values["Esito"]
    assert evaluator.calls == []  # the persisted decision (and its facts) are the authority
    assert not any(s.ref.startswith("metric:ota-share") for s in context.sections)


def test_case_b_evaluated_without_a_decision_gives_the_observed_share_and_a_careful_outcome(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    evaluator = _Evaluator(_ota(tenant, CLEAR))

    context = _collect(db_session, tenant, "Gli OTA sono a posto?", evaluator=evaluator)

    assert evaluator.calls == [(tenant.property.id, tenant.data_source.id, D1)]
    values = _values(_section(context, "coverage:distribution"))
    assert values["Decisioni sulla dipendenza OTA"] == "0"
    assert values["Esito"] == (
        "per quanto analizzato oggi, NINFA non rileva una criticità actionable sulla dipendenza OTA"
    )
    share = _section(context, "metric:ota-share:2026-08-01")
    metrics = _values(share)
    assert metrics["Quota OTA sul totale OTA + diretto"] == "40.00"
    assert metrics["Quota diretta sul totale OTA + diretto"] == "60.00"
    assert metrics["Quota OTA di riferimento (livello atteso)"] == "50.00"
    window = "i prossimi 30 giorni, dal 1 agosto al 30 agosto"
    assert metrics["Periodo considerato"] == window
    assert share.period == window
    assert "perfetta" in (_section(context, "coverage:distribution").note or "")


def test_case_c_an_area_that_was_not_analysed_is_never_judged(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    skipped = AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, DomainCoverageStatus.EVALUATED),
            DomainCoverage(
                AnalysisDomain.DISTRIBUTION,
                DomainCoverageStatus.SKIPPED,
                DomainSkipReason.NOT_REQUESTED,
            ),
            DomainCoverage(
                AnalysisDomain.COSTS, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
            DomainCoverage(
                AnalysisDomain.LABOR, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
        )
    )
    _run(db_session, tenant, [_revenue(tenant)], coverage=skipped)
    evaluator = _Evaluator(_ota(tenant, CLEAR))

    context = _collect(db_session, tenant, "Gli OTA sono a posto?", evaluator=evaluator)

    values = _values(_section(context, "coverage:distribution"))
    assert values["Area analizzata oggi"] == "non analizzata"
    assert "non può dire che vada tutto bene" in values["Esito"]
    assert evaluator.calls == []  # an area that was not analysed is not evaluated live either
    assert not any(s.ref.startswith("metric:ota-share") for s in context.sections)


def test_case_c_an_unknown_coverage_is_not_assessable_never_assumed_fine(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    sync_feed(
        db_session,
        tenant,
        [_ota(tenant, CLEAR)],
        coverage=None,  # a run recorded before Gate 22: coverage UNKNOWN
        provenance=provenance_for(tenant, utc(2026, 8, 1, 7, 31)),
    )

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(_ota(tenant))
    )

    values = _values(_section(context, "coverage:distribution"))
    assert values["Area analizzata oggi"] == "non disponibile"
    assert "copertura dell'analisi non è registrata" in values["Esito"]


def test_case_c_without_an_analysis_the_area_is_not_assessable(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(_ota(tenant))
    )

    values = _values(_section(context, "coverage:distribution"))
    assert values["Area analizzata oggi"] == "non disponibile"
    assert "analisi di oggi non è ancora disponibile" in values["Esito"]


def test_case_d_insufficient_data_is_never_reported_as_all_clear(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    insufficient = replace(
        _ota(tenant, INSUFFICIENT),
        reason_codes=(ReasonCode.OTA_BOOKING_VOLUME_LOW,),
        ota_share_exact=None,
        direct_share_exact=None,
        expected_ota_share_exact=None,
    )

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(insufficient)
    )

    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert "i dati non bastavano per giudicare la dipendenza OTA" in outcome
    assert "troppo poche" in outcome  # the plain-Italian reason
    assert "non può dire che vada tutto bene" in outcome
    assert "non rileva una criticità" not in outcome
    assert not any(s.ref.startswith("metric:ota-share") for s in context.sections)  # no share


def test_case_d_a_low_confidence_share_is_shown_but_no_judgement_is_made(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Gli OTA sono a posto?",
        evaluator=_Evaluator(_ota(tenant, SUPPRESSED)),
    )

    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert "non abbastanza affidabile" in outcome and "nessun giudizio" in outcome
    assert _section(context, "metric:ota-share:2026-08-01")  # the figure itself is still a fact


def test_a_live_evaluation_that_disagrees_with_the_persisted_run_asserts_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    """The run is the authority: if the bookings changed since and the live evaluation would now
    trigger while the run produced no decision, Mia states neither 'all clear' nor a problem."""
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Gli OTA sono a posto?",
        evaluator=_Evaluator(_ota(tenant, TRIGGERED)),
    )

    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert "i dati di prenotazione sono cambiati dopo l'analisi di oggi" in outcome
    assert "non rileva una criticità" not in outcome
    assert not any(s.ref.startswith("metric:ota-share") for s in context.sections)


def test_a_failing_live_evaluation_degrades_to_not_available(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Gli OTA sono a posto?",
        evaluator=_Evaluator(RuntimeError("boom: secret detail")),
    )

    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert outcome == "la quota OTA non è al momento calcolabile"
    assert "secret detail" not in json.dumps([s.data for s in context.sections], default=str)


def test_the_real_ota_service_runs_end_to_end_for_a_clear_window(
    db_session: Session, factory: BookingFactory
) -> None:
    """No injected evaluator: the real `OtaDependencyService`, read-only, over real bookings and
    snapshots - the CLEAR window of Gate 9's own smoke test."""
    from tests.distribution_support import DistributionWorld

    as_of = date(2026, 9, 5)
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    ota = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    historical = [as_of - timedelta(weeks=k) for k in range(1, 7)]
    world.uniform_bookings(min(historical), as_of + timedelta(days=29), [(ota, 20), (direct, 10)])
    for day in [as_of, *historical]:
        world.snapshot_window(day, day, day + timedelta(days=29), 30)
    sync_feed(
        db_session,
        tenant,
        [
            ota_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                booking_data_source_id=tenant.data_source.id,
                as_of_local_date=as_of,
                status=CLEAR,
            )
        ],
        as_of=as_of,
        coverage=full_coverage(),
        provenance=provenance_for(tenant, utc(2026, 9, 5, 7, 0)),
    )

    context = _collect(db_session, tenant, "Gli OTA sono a posto?", as_of=as_of)

    metrics = _values(_section(context, "metric:ota-share:2026-09-05"))
    assert metrics["Quota OTA sul totale OTA + diretto"] == "66.67"
    assert metrics["Quota diretta sul totale OTA + diretto"] == "33.33"
    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert outcome.startswith("per quanto analizzato oggi")


# --- channel weights ("Quanto pesa Booking?") --------------------------------------------------


def _channel_world(db_session: Session, factory: BookingFactory) -> Tenant:
    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    booking = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    expedia = world.channel("Expedia", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    end = D1 + timedelta(days=10)
    world.booking(booking, D1, end, rooms=6)  # 6 rooms x 10 nights = 60 room-nights
    world.booking(expedia, D1, end, rooms=2)  # 20
    world.booking(direct, D1, end, rooms=2)  # 20
    return tenant


def test_the_weight_of_a_named_channel_is_a_share_of_all_certain_room_nights(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Quanto pesa Booking?",
        evaluator=_Evaluator(_ota(tenant)),
    )

    mix = _section(context, "metric:channel-mix:2026-08-01")
    values = _values(mix)
    assert mix.period == "i prossimi 30 giorni, dal 1 agosto al 30 agosto"
    assert values["Camere-notte prenotate nei prossimi 30 giorni (tutti i canali)"] == "100"
    assert values["Peso di Booking.com sul totale delle camere-notte prenotate"] == "60.00"
    rows = [dict(row) for row in mix.rows]
    assert [row["canale"] for row in rows] == ["Booking.com", "Direct", "Expedia"]
    assert rows[0]["tipo"] == "OTA" and rows[1]["tipo"] == "diretto"
    assert rows[0]["camere-notte prenotate"] == "60"
    assert "non coincide con la quota OTA" in (mix.note or "")


def test_a_channel_the_property_does_not_have_is_stated_not_invented(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Quanto pesa Airbnb?",
        evaluator=_Evaluator(_ota(tenant)),
    )

    values = _values(_section(context, "metric:channel-mix:2026-08-01"))
    assert values["Canale richiesto: airbnb"] == "non compare tra i canali di questa struttura"


def test_uncertain_and_cancelled_bookings_are_not_counted_in_the_channel_weight(
    db_session: Session, factory: BookingFactory
) -> None:
    from app.modules.bookings.models import BookingStatus

    tenant = factory.tenant()
    world = DistributionWorld(db_session, tenant, factory)
    booking = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct = world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    end = D1 + timedelta(days=5)
    world.booking(booking, D1, end, rooms=1)  # 5 certain room-nights
    world.booking(
        booking, D1, end, rooms=9, status=BookingStatus.CANCELLED, cancelled_at=utc(2026, 7, 1, 8)
    )
    world.booking(direct, D1, end, rooms=1)  # 5
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Quanto pesa Booking?",
        evaluator=_Evaluator(_ota(tenant)),
    )

    values = _values(_section(context, "metric:channel-mix:2026-08-01"))
    assert values["Camere-notte prenotate nei prossimi 30 giorni (tutti i canali)"] == "10"
    assert values["Peso di Booking.com sul totale delle camere-notte prenotate"] == "50.00"


# --- the OTA / channel window is the NEXT 30 nights, never a look-back ---------------------------


def _every_text_of(context: OperationalContext) -> list[str]:
    """Every string a section hands to the model, plus the not-determinable notes."""
    texts: list[str] = list(context.not_available)
    for section in context.sections:
        texts += [section.title, section.period or "", section.note or ""]
        for point in section.data:
            texts += [point.label, point.value]
        for row in section.rows:
            texts += [label for label, _ in row] + [value for _, value in row]
    return texts


def test_no_generated_section_describes_the_forward_window_as_the_last_30_days(
    db_session: Session, factory: BookingFactory
) -> None:
    """The real model once read '30 notti dall'analisi' as 'ultimi 30 giorni' in 4 of 14 answers:
    the OTA share and the channel mix are bookings for the NEXT 30 nights, said in words."""
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    for question in ("Gli OTA sono a posto?", "Quanto pesa Booking?", "Come vanno i canali?"):
        context = _collect(db_session, tenant, question, evaluator=_Evaluator(_ota(tenant, CLEAR)))
        texts = _every_text_of(context)
        assert any("i prossimi 30 giorni, dal 1 agosto al 30 agosto" in text for text in texts)
        blob = " ".join(texts).lower()
        for look_back in ("ultimi 30", "ultimi trenta", "scorsi", "negli ultimi", "dall'analisi"):
            assert look_back not in blob, (question, look_back)


def test_the_insufficient_data_reasons_also_speak_of_the_next_30_days(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    insufficient = replace(
        _ota(tenant, INSUFFICIENT),
        reason_codes=(
            ReasonCode.OTA_NO_ON_BOOKS_DEMAND,
            ReasonCode.OTA_SNAPSHOT_WINDOW_INCOMPLETE,
        ),
        ota_share_exact=None,
        direct_share_exact=None,
        expected_ota_share_exact=None,
    )

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(insufficient)
    )

    outcome = _values(_section(context, "coverage:distribution"))["Esito"]
    assert "nei prossimi 30 giorni non ci sono prenotazioni" in outcome
    assert "dei prossimi 30 giorni sono incompleti" in outcome
    assert "osservati" not in outcome


# --- the channel-mix probe only supports a judgement NINFA made -----------------------------------


def _refs(context: OperationalContext) -> list[str]:
    return [section.ref for section in context.sections]


def test_a_skipped_distribution_area_gets_the_coverage_limit_and_no_channel_mix(
    db_session: Session, factory: BookingFactory
) -> None:
    """'Gli OTA sono a posto?' with Distribution skipped: the coverage limitation ONLY - no channel
    weights, no 'no certain bookings' note (an irrelevant second explanation)."""
    tenant = _channel_world(db_session, factory)  # the bookings exist: a mix COULD be built
    _run(db_session, tenant, [_revenue(tenant)], coverage=distribution_skipped_coverage())
    evaluator = _Evaluator(_ota(tenant, CLEAR))

    context = _collect(db_session, tenant, "Gli OTA sono a posto?", evaluator=evaluator)

    assert _refs(context) == ["coverage:distribution"]
    assert _values(_section(context, "coverage:distribution"))["Area analizzata oggi"] == (
        "non analizzata"
    )
    assert context.not_available == ()
    assert evaluator.calls == []


def test_an_unknown_coverage_gets_the_coverage_limit_and_no_channel_mix(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)
    sync_feed(
        db_session,
        tenant,
        [_ota(tenant, CLEAR)],
        coverage=None,
        provenance=provenance_for(tenant, utc(2026, 8, 1, 7, 31)),
    )

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(_ota(tenant))
    )

    assert _refs(context) == ["coverage:distribution"]
    assert context.not_available == ()


def test_no_analysis_for_today_gets_the_coverage_limit_and_no_channel_mix(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)

    context = _collect(
        db_session, tenant, "Gli OTA sono a posto?", evaluator=_Evaluator(_ota(tenant))
    )

    assert _refs(context) == ["coverage:distribution"]
    assert context.not_available == ()


@pytest.mark.parametrize("status", [INSUFFICIENT, SUPPRESSED])
def test_a_distribution_check_that_could_not_judge_gets_no_channel_mix(
    db_session: Session, factory: BookingFactory, status: EvaluationStatus
) -> None:
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session,
        tenant,
        "Gli OTA sono a posto?",
        evaluator=_Evaluator(_ota(tenant, status)),
    )

    assert not [ref for ref in _refs(context) if ref.startswith("metric:channel-mix")]


def test_a_judged_distribution_still_backs_the_judgement_with_the_channel_mix(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)

    _run(db_session, tenant, [_ota(tenant, TRIGGERED)])
    with_decision = _collect(db_session, tenant, "Gli OTA sono a posto?")
    assert "metric:channel-mix:2026-08-01" in _refs(with_decision)

    clear = factory.tenant()
    world = DistributionWorld(db_session, clear, factory)
    booking = world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    world.booking(booking, D1, D1 + timedelta(days=4), rooms=2)
    _run(db_session, clear, [_ota(clear, CLEAR)])
    evaluated = _collect(
        db_session, clear, "Gli OTA sono a posto?", evaluator=_Evaluator(_ota(clear, CLEAR))
    )
    assert "metric:channel-mix:2026-08-01" in _refs(evaluated)


def test_a_channel_the_question_names_is_an_independent_metric_even_without_a_judgement(
    db_session: Session, factory: BookingFactory
) -> None:
    """'Quanto pesa Booking?' asks for a channel weight of the stored bookings, which does not
    depend on whether the Distribution area was analysed."""
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_revenue(tenant)], coverage=distribution_skipped_coverage())

    context = _collect(db_session, tenant, "Quanto pesa Booking?")

    values = _values(_section(context, "metric:channel-mix:2026-08-01"))
    assert values["Peso di Booking.com sul totale delle camere-notte prenotate"] == "60.00"
    assert _values(_section(context, "coverage:distribution"))["Area analizzata oggi"] == (
        "non analizzata"
    )


def test_a_named_channel_with_no_certain_bookings_says_so_in_the_next_30_days(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])

    context = _collect(
        db_session, tenant, "Quanto pesa Booking?", evaluator=_Evaluator(_ota(tenant))
    )

    assert context.not_available == (
        "nei prossimi 30 giorni non ci sono prenotazioni certe da cui ricavare il peso dei canali",
    )


# --- costs / labour / areas: state and decisions only ------------------------------------------


def test_costs_without_a_decision_say_so_only_when_the_area_was_analysed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)], coverage=booking_only_coverage())

    context = _collect(db_session, tenant, "Come stanno andando i costi?")

    values = _values(_section(context, "coverage:costs"))
    assert values["Area analizzata oggi"] == "non analizzata"
    assert "non può dire che vada tutto bene" in values["Esito"]


def test_an_analysed_area_without_a_decision_is_hedged_when_checks_lacked_data(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, INSUFFICIENT)], coverage=full_coverage())

    context = _collect(db_session, tenant, "Il personale è sovradimensionato?")

    values = _values(_section(context, "coverage:labor"))
    assert values["Area analizzata oggi"] == "analizzata"
    assert "non si può escludere" in values["Esito"]  # run-level insufficient checks, domain-blind


def test_a_clean_analysed_area_is_reported_as_no_decision_for_what_was_analysed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)], coverage=full_coverage())

    context = _collect(db_session, tenant, "Come stanno andando i costi?")

    values = _values(_section(context, "coverage:costs"))
    assert (
        values["Esito"]
        == "per quanto analizzato oggi, NINFA non ha prodotto decisioni in quest'area"
    )
    # and no cost FIGURE is invented: only the area status exists
    assert not [s for s in context.sections if s.ref.startswith("metric:")]
    assert not context.not_available


def test_the_area_comparison_reports_the_area_of_ninfas_first_decision(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(
        db_session,
        tenant,
        [_revenue(tenant), _ota(tenant, TRIGGERED)],
        coverage=booking_only_coverage(),
    )

    context = _collect(db_session, tenant, "Quale area è più critica?")

    summary = _section(context, "summary:areas")
    rows = {dict(row)["area"]: dict(row) for row in summary.rows}
    assert set(rows) == {"Ricavi", "Distribuzione", "Costi", "Personale"}
    assert rows["Costi"]["analizzata oggi"] == "non analizzata"
    firsts = [
        area
        for area, row in rows.items()
        if row["contiene la prima decisione nell'ordine di NINFA"] == "sì"
    ]
    assert len(firsts) == 1
    assert "non esiste un'altra graduatoria" in (summary.note or "")


# --- unsupported concepts and unplaced questions -----------------------------------------------


def test_unsupported_concepts_are_listed_with_fixed_plain_sentences(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)

    for question, fragment in [
        ("Qual è il revpar?", "NINFA non calcola il RevPAR"),
        ("Quante cancellazioni abbiamo?", "non calcola un indicatore su cancellazioni"),
        ("E rispetto ai concorrenti?", "non ha dati su mercato o concorrenti"),
        ("Quanto pago di commissioni a Booking?", "non calcola l'importo delle commissioni"),
        ("Quanto pesa il personale?", "non definisce un'incidenza"),
        ("Che occupazione prevedi a fine mese?", "non fornisce previsioni"),
        ("Come va il weekend?", "'weekend' non è un periodo che NINFA definisca"),
    ]:
        context = _collect(db_session, tenant, question, evaluator=_Evaluator(_ota(tenant)))
        assert any(fragment in note for note in context.not_available), question


def test_an_unplaced_question_hands_over_what_mia_can_explain(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)

    context = _collect(db_session, tenant, "Che tempo fa domani?")

    assert context.topics == ()
    assert context.sections == ()
    assert context.supported_topics  # so Mia says what NINFA CAN do, not a generic fallback


def test_without_an_analysis_for_today_no_list_of_things_mia_can_explain_is_handed_over(
    db_session: Session, factory: BookingFactory
) -> None:
    """NOT_PROCESSED: there are no decisions, OTA status, coverage or import to explain. The
    generic list ('decisioni di oggi', 'distribuzione', 'ultimo import'...) made the real model
    OFFER exactly those, and then say the details were unavailable."""
    from app.modules.decision_memory.types import FeedState

    tenant = factory.tenant()  # no analysis run exists for the day
    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, D1)
    assert feed.state is FeedState.NOT_PROCESSED

    for question in ("Come sta andando l'hotel oggi?", "Che tempo fa domani?"):
        context = _collect(db_session, tenant, question)
        assert context.topics == ()
        assert context.supported_topics == (), question
        assert context.sections == ()


def test_a_placed_question_without_an_analysis_names_only_what_is_not_available(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    context = _collect(db_session, tenant, "Come stanno andando le prenotazioni?")

    assert context.supported_topics == ()
    assert any("analisi di oggi non è ancora disponibile" in n for n in context.not_available)


def test_a_bare_follow_up_without_history_is_flagged_not_guessed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant)

    context = _collect(db_session, tenant, "Perché?")

    assert any("richiama una conversazione precedente" in n for n in context.not_available)
    assert not context.from_previous_question


def test_a_follow_up_with_history_fetches_the_facts_of_the_previous_topic(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    evaluator = _Evaluator(_ota(tenant, CLEAR))

    context = _collect(
        db_session,
        tenant,
        "Perché?",
        history=(
            ("user", "Come stanno andando gli OTA?"),
            ("assistant", "Per quanto analizzato..."),
        ),
        evaluator=evaluator,
    )

    assert context.from_previous_question
    assert _section(context, "coverage:distribution")
    assert evaluator.calls  # the facts of the PREVIOUS topic were fetched fresh


# --- privacy: labelled facts only, never raw records -------------------------------------------


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def test_the_serialized_context_holds_no_identifier_and_no_raw_record(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = _channel_world(db_session, factory)
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    seed_night_snapshots(db_session, tenant, D1, _week([10, 20, 30, 0, 5, 5, 5]))
    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, D1)
    question = "Booking pesa troppo? E l'occupazione dei prossimi 7 giorni?"
    resolution = resolve_question(question, (), D1)
    operational = HomeDataService(
        db_session,
        tenant.context,
        ota_evaluator=_Evaluator(_ota(tenant)),
    ).collect(resolution, feed, property_id=tenant.property.id, timezone=ROME, currency="EUR")
    context = replace(AskHomeContextBuilder().build(feed, ROME), operational=operational)

    serialized = serialize_home_context(context)

    assert not _UUID.search(serialized)
    for forbidden in (
        str(tenant.property.id),
        str(tenant.workspace.id),
        str(tenant.data_source.id),
        "source_record_id",
        "BK-",
        "guest",
        "ospite",
        "booked_at",
        "channel_id",
        "SELECT ",
    ):
        assert forbidden not in serialized, forbidden
    payload = json.loads(serialized)
    assert set(payload["dati operativi richiesti"]) >= {"sezioni", "cosa NINFA non può determinare"}
    # no snake_case key anywhere in the new part (the technical-leak check must never fire on it)
    keys: set[str] = set()

    def _collect_keys(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                keys.add(key)
                _collect_keys(value)
        elif isinstance(node, list):
            for item in node:
                _collect_keys(item)

    _collect_keys(payload)
    assert not [key for key in keys if "_" in key]


def test_every_ref_in_the_context_is_in_the_per_request_vocabulary_and_nothing_else_is(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    _run(
        db_session,
        tenant,
        [_revenue(tenant), _ota(tenant, CLEAR)],
        coverage=booking_only_coverage(),
    )
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10, 10]))
    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, D1)
    operational = HomeDataService(
        db_session,
        tenant.context,
        ota_evaluator=_Evaluator(_ota(tenant)),
    ).collect(
        resolve_question("Gli OTA sono a posto? E l'occupazione di oggi?", (), D1),
        feed,
        property_id=tenant.property.id,
        timezone=ROME,
        currency="EUR",
    )
    context = replace(AskHomeContextBuilder().build(feed, ROME), operational=operational)

    vocabulary = grounding_vocabulary(context)

    for base in (
        "ANALYSIS_STATE",
        "DECISIONS",
        "ECONOMIC_IMPACT",
        "COVERAGE",
        "FRESHNESS",
        "LAST_ANALYSIS",
    ):
        assert base in vocabulary
    assert "coverage:distribution" in vocabulary and "freshness:bookings" in vocabulary
    assert "metric:ota-share:2026-08-01" in vocabulary
    assert any(ref.startswith("decision:pickup:") for ref in vocabulary) or any(
        ref.startswith("decision:occupancy-risk:") for ref in vocabulary
    )
    assert len(vocabulary) == len(set(vocabulary))
    assert not any(
        "_" in ref
        for ref in vocabulary
        if ref not in {"ANALYSIS_STATE", "ECONOMIC_IMPACT", "LAST_ANALYSIS"}
    )
    payload = json.loads(serialize_home_context(context))
    in_context = {item["riferimento"] for item in payload["decisioni in ordine di priorità"]} | {
        section["riferimento"] for section in payload["dati operativi richiesti"]["sezioni"]
    }
    assert in_context <= set(vocabulary)


@pytest.mark.parametrize(
    "question", ["Gli OTA sono a posto?", "Occupazione di oggi", "Come vanno i costi?"]
)
def test_the_data_service_never_writes(
    db_session: Session, factory: BookingFactory, question: str
) -> None:
    """Read-only: the row counts of the tables it touches are identical before and after."""
    from sqlalchemy import func, select

    from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
    from app.modules.snapshots.models import BookingSnapshot

    tenant = factory.tenant()
    _run(db_session, tenant, [_ota(tenant, CLEAR)])
    seed_night_snapshots(db_session, tenant, D1, _week([10, 10]))

    def counts() -> tuple[int, ...]:
        return tuple(
            db_session.scalar(select(func.count()).select_from(model)) or 0
            for model in (DecisionRun, Decision, DecisionObservation, BookingSnapshot)
        )

    before = counts()
    _collect(db_session, tenant, question, evaluator=_Evaluator(_ota(tenant)))
    assert counts() == before

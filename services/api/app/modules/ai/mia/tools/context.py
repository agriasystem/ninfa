"""Mia tools: what Mia is looking at - the structure, the screen, and the state of the data.

    get_current_property_context   the structure, the business date, who asks, the open page
    get_data_status                the analysis of the day, area by area, and the data origin

`get_data_status` is the tool behind "perché oggi non ho decisioni?", "perché vedo Analisi
parziale?", "quali dati ti mancano?" and "da dove arrivano questi dati?". It states FACTS about
the run and the imports (how many checks could not conclude, which areas were not analysed, when
each kind of data was last imported, whether the latest booking delivery changed anything) and
passes NO judgement of "current" or "stale": NINFA has no freshness threshold, and it does not
record WHY a check could not conclude, so no cause is ever offered.

Observation keys are plain Italian with spaces (never snake_case); ids never reach the model as raw
UUIDs (see `decisions.py`).
"""

import logging
import re
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from app.modules.ai.ask_ninfa import semantic_labels
from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.labels import area_label
from app.modules.ai.mia.tools.base import ToolDefinition, ToolRuntime
from app.modules.ai.mia.tools.decisions import (
    area_outcome,
    coverage_of,
    coverage_status_of,
    coverage_text,
    feed_state_text,
    ref_token,
    visible_areas,
)
from app.modules.ai.mia.tools.format import day, iso
from app.modules.ai.mia.types import Observation
from app.modules.ai.mia.ui_context import PageContext
from app.modules.analysis.observation import booking_observation_freshness
from app.modules.data_overview.types import (
    Availability,
    DomainFreshness,
    DomainState,
    FreshnessReason,
    OtaInsufficiency,
    OtaOutcome,
    UnavailableReason,
)
from app.modules.decisions.coverage import AnalysisDomain, DomainCoverageStatus
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.repository import RoomInventoryRepository
from app.modules.tenancy.models import MembershipRole

logger = logging.getLogger(__name__)

_ROLE_LABELS: dict[MembershipRole, str] = {
    MembershipRole.OWNER: "titolare dell'account",
    MembershipRole.ADMIN: "amministratore",
    MembershipRole.MEMBER: "membro del team",
}

# The SAME sentences the Dati screen ships for a block with no figure (apps/web/lib/data/copy.ts).
_UNAVAILABLE_REASONS: dict[UnavailableReason, str] = {
    UnavailableReason.NO_ANALYSIS: "L'analisi di oggi non è ancora disponibile.",
    UnavailableReason.NO_BOOKING_SOURCE: (
        "L'origine dei dati di prenotazione non è registrata per questa analisi."
    ),
    UnavailableReason.NO_BOOKING_DATA: "Non ci sono prenotazioni registrate per questo periodo.",
    UnavailableReason.COVERAGE_UNKNOWN: (
        "La copertura dell'analisi non è registrata per questa analisi."
    ),
    UnavailableReason.NOT_ANALYZED: "Quest'area non è stata analizzata.",
    UnavailableReason.EVALUATION_FAILED: (
        "In questo momento non è stato possibile calcolare questo valore."
    ),
    UnavailableReason.NO_DATA: "Non ci sono dati sufficienti per questo periodo.",
    UnavailableReason.NO_OCCUPANCY: "Mancano i dati di occupazione necessari.",
    UnavailableReason.NO_SOURCE: "Nessuna origine dati disponibile.",
    UnavailableReason.SEVERAL_SOURCES: "Ci sono più origini dati: NINFA non ne sceglie una.",
}

# The SAME sentences as the Dati screen's OTA outcome copy: never "va tutto bene".
_OTA_OUTCOMES: dict[OtaOutcome, str] = {
    OtaOutcome.DECISION: "NINFA ha prodotto una decisione sulla dipendenza OTA.",
    OtaOutcome.CLEAR: (
        "Per quanto analizzato oggi, NINFA non rileva criticità sulla dipendenza OTA."
    ),
    OtaOutcome.INSUFFICIENT_DATA: "I dati non bastano per valutare la dipendenza OTA.",
    OtaOutcome.SUPPRESSED: "Il valore non è abbastanza affidabile per una valutazione.",
    OtaOutcome.NOT_APPLICABLE: (
        "Il controllo sulla dipendenza OTA non è applicabile ai dati di oggi."
    ),
    OtaOutcome.CHANGED_AFTER_ANALYSIS: (
        "I dati di prenotazione sono cambiati dopo l'analisi di oggi: NINFA non mostra la quota "
        "finché l'analisi non viene rifatta."
    ),
}

# Why the OTA check could not give a verdict, keyed by the engine's reason code (read from the
# overview, never shown): the Dati screen's own wording.
_OTA_INSUFFICIENT_REASONS: dict[str, str] = {
    "OTA_NO_ON_BOOKS_DEMAND": "nei prossimi 30 giorni non ci sono prenotazioni",
    "OTA_BOOKING_VOLUME_LOW": "le prenotazioni classificate come OTA o dirette sono troppo poche",
    "OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW": (
        "troppe prenotazioni sono su canali che NINFA non sa classificare come OTA o diretti"
    ),
    "OTA_SNAPSHOT_WINDOW_INCOMPLETE": (
        "i dati di prenotazione dei prossimi 30 giorni sono incompleti"
    ),
    "OTA_SNAPSHOT_WINDOW_UNCERTAIN": "alcune prenotazioni del periodo hanno uno stato incerto",
    "OTA_CHANNEL_MIX_RECONCILIATION_FAILED": (
        "la composizione per canale non coincide con le prenotazioni registrate"
    ),
    "OTA_COMPARABLE_SAMPLE_INSUFFICIENT": (
        "mancano periodi storici confrontabili per stabilire il livello atteso"
    ),
    "LOW_CONFIDENCE": "l'affidabilità del confronto è troppo bassa",
}

_FRESHNESS_UNKNOWN: dict[FreshnessReason, str] = {
    FreshnessReason.NO_SOURCE: "nessuna origine dati configurata",
    FreshnessReason.SEVERAL_SOURCES: "più origini dati: non confrontabili",
    FreshnessReason.NO_IMPORT: "nessun import completato",
}

_DOMAIN_STATE_TEXT: dict[DomainState, str] = {
    DomainState.ANALYZED: "analizzata",
    DomainState.PARTIAL: "analisi parziale",
    DomainState.NOT_ANALYZED: "non analizzata",
    DomainState.UNKNOWN: "non disponibile",
}

_WHITESPACE = re.compile(r"\s+")


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- small helpers


def _first_name(display_name: str | None) -> str | None:
    """The first name only, never anything that looks like an address."""
    if not display_name or "@" in display_name:
        return None
    cleaned = _WHITESPACE.sub(" ", display_name).strip()
    first = cleaned.split(" ", 1)[0][:40]
    return first or None


def _plain(text: str) -> str:
    """An untrusted identifier with no underscore: it can be echoed without tripping the check on
    technical words."""
    return text.replace("_", " ")


def _entity_label(kind: str, entity_id: str | None) -> str | None:
    """The selected element's name. A category arrives as the product's own code: it is turned into
    the Italian word the screen shows (an unknown code is dropped, never passed on raw)."""
    if entity_id is None:
        return None
    try:
        if kind == "cost_category":
            return semantic_labels.cost_category_label_of(CostCategory(entity_id))
        if kind == "labor_category":
            return semantic_labels.labor_category_label_of(LaborCategory(entity_id))
    except ValueError:
        return None
    return _plain(entity_id)


def _when(instant: datetime, timezone: ZoneInfo, as_of: date) -> tuple[str, int]:
    """(how to say it, days before the business date), in the property's own time zone."""
    local = instant.astimezone(timezone)
    clock = local.strftime("%H:%M")
    gap = (as_of - local.date()).days
    if gap == 0:
        return f"oggi alle {clock}", 0
    if gap == 1:
        return f"ieri alle {clock}", 1
    return f"il {local.date().isoformat()} alle {clock}", gap


def _freshness_of(
    domain_freshness: DomainFreshness, timezone: ZoneInfo, as_of: date
) -> dict[str, Any]:
    if not domain_freshness.known or domain_freshness.finished_at is None:
        reason = domain_freshness.reason
        return {
            "ultimo import": None,
            "motivo": _FRESHNESS_UNKNOWN.get(reason, "non disponibile") if reason else "non noto",
        }
    text, gap = _when(domain_freshness.finished_at, timezone, as_of)
    return {"ultimo import": text, "giorni dall'ultimo import": gap}


def _page_hint(page: PageContext) -> dict[str, Any] | None:
    """What the person is looking at, as the model may read it: a HINT, validated by the server
    (a decision or an import of another property is already gone). No import id is passed on (the
    import tools read the page themselves); a decision goes as the same token `explain_decision`
    accepts."""
    if page.is_empty:
        return None
    hint: dict[str, Any] = {}
    if page.page_title is not None:
        hint["pagina"] = page.page_title
    if page.section_title is not None:
        hint["sezione"] = page.section_title
    elif page.section is not None:
        hint["sezione"] = _plain(page.section)
    if page.period_days is not None:
        hint["periodo in giorni"] = page.period_days
    if page.date_from is not None:
        hint["dal"] = page.date_from.isoformat()
    if page.date_to is not None:
        hint["al"] = page.date_to.isoformat()
    if page.metric_title is not None:
        hint["metrica selezionata"] = page.metric_title
    if page.decision is not None:
        try:
            reference = ref_token(UUID(page.decision.decision_id))
        except ValueError:
            reference = None
        if reference is not None:
            hint["decisione selezionata"] = {
                "riferimento": reference,
                "titolo": page.decision.title,
                "stato": page.decision.status,
                "vista la prima volta": page.decision.first_seen,
                "ultima valutazione": page.decision.last_evaluated,
            }
    if page.import_hint is not None:
        hint["import selezionato"] = {
            "stato": page.import_hint.status,
            "tipo di dati": page.import_hint.kind_of_data,
            "terminato": page.import_hint.finished_at,
        }
    if page.entity_kind is not None:
        hint["elemento selezionato"] = {
            "tipo": _plain(page.entity_kind),
            "identificativo": _entity_label(page.entity_kind, page.entity_id),
        }
    return hint or None


# --- tool 1: get_current_property_context


def _property_context(runtime: ToolRuntime, _: _NoArgs) -> Observation:
    inventory = RoomInventoryRepository(runtime.session, runtime.tenant).get_for_date(
        runtime.property_id, runtime.as_of
    )
    not_available: list[str] = []
    capacity: dict[str, Any]
    if inventory is None:
        capacity = {"camere vendibili nella data di riferimento": None}
        not_available.append(
            "il numero di camere vendibili per la data di riferimento non è registrato "
            "nell'inventario camere della struttura (senza, l'occupazione non si può calcolare)"
        )
    else:
        capacity = {
            "camere vendibili nella data di riferimento": inventory.rooms_available,
            "camere fuori servizio (solo informativo)": inventory.rooms_out_of_order,
        }
    data: dict[str, Any] = {
        "struttura": runtime.property_name,
        "fuso orario": str(runtime.timezone),
        "valuta": runtime.currency,
        "data di riferimento": day(runtime.as_of),
        **capacity,
        "utente": {
            "nome": _first_name(runtime.user.display_name),
            "ruolo": _ROLE_LABELS.get(runtime.user.role, "membro del team"),
        },
    }
    hint = _page_hint(runtime.page)
    refs = ["contesto:struttura"]
    if hint is not None:
        data["cosa sta guardando l'utente (solo un suggerimento, non un dato)"] = hint
        refs.append("contesto:pagina")
    return Observation(
        tool="get_current_property_context",
        refs=tuple(refs),
        data=data,
        not_available=tuple(not_available),
        notes=(
            "La data di riferimento è il giorno di analisi che l'utente sta guardando, nel fuso "
            "orario della struttura: non è un orologio del server.",
            "Ciò che l'utente sta guardando serve solo a capire a cosa si riferisce la domanda: i "
            "dati veri vengono sempre dagli altri strumenti.",
        ),
        resolved={},
    )


# --- tool 2: get_data_status


def _delivery_is_new(runtime: ToolRuntime, run: Any) -> bool | None:
    """Did the latest booking import change what the previous analysed day had seen (ADR 0045)?
    `None` when the run does not say enough to tell - never a guess."""
    if run is None or run.input_provenance is None:
        return None
    try:
        bookings = RunInputProvenance.from_json(run.input_provenance).bookings
    except (KeyError, ValueError, TypeError):
        return None
    if bookings.import_job_id is None:
        return None
    try:
        result = booking_observation_freshness(
            runtime.session,
            runtime.tenant,
            property_id=runtime.property_id,
            data_source_id=bookings.data_source_id,
            as_of_local_date=run.as_of_local_date,
            import_job_id=bookings.import_job_id,
        )
    except Exception as error:  # a read failing must not stop the rest of the status
        logger.warning("mia delivery freshness failed error_type=%s", type(error).__name__)
        return None
    return result.fresh


def _blocks(
    runtime: ToolRuntime, areas: frozenset[AnalysisDomain]
) -> tuple[list[dict[str, Any]], list[str]]:
    overview = runtime.overview(30)
    rows: list[dict[str, Any]] = []
    missing: list[str] = []

    def reason_text(reason: UnavailableReason | None) -> str | None:
        return None if reason is None else _UNAVAILABLE_REASONS.get(reason, "dato non disponibile")

    def add(name: str, state: Availability, reason: UnavailableReason | None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "blocco": name,
            "disponibile": state is Availability.AVAILABLE,
            "motivo": reason_text(reason),
        }
        rows.append(row)
        if state is not Availability.AVAILABLE:
            missing.append(f"{name}: {reason_text(reason) or 'dato non disponibile'}")
        return row

    if AnalysisDomain.REVENUE in areas:
        add(
            "Prenotazioni e occupazione",
            overview.occupancy.state,
            overview.occupancy.reason,
        )
    if AnalysisDomain.DISTRIBUTION in areas:
        distribution = overview.distribution
        row = add("Distribuzione (OTA e canali)", distribution.state, distribution.reason)
        if distribution.outcome is not None:
            row["esito del controllo OTA"] = _OTA_OUTCOMES.get(distribution.outcome)
        if distribution.insufficient_reasons:
            row["perché il controllo OTA non ha dato un verdetto"] = [
                _OTA_INSUFFICIENT_REASONS.get(code, "dati insufficienti")
                for code in distribution.insufficient_reasons
            ]
        if distribution.insufficiency is OtaInsufficiency.HISTORY:
            row["natura del problema"] = (
                "i dati attuali sono leggibili: mancano solo periodi passati da confrontare, che "
                "arrivano da soli con le analisi successive"
            )
            row["periodi confrontabili disponibili"] = distribution.comparable_periods_available
            row["periodi confrontabili richiesti"] = distribution.comparable_periods_required
        elif distribution.insufficiency is OtaInsufficiency.DATA_QUALITY:
            row["natura del problema"] = (
                "i dati attuali non sono leggibili con sicurezza (date, stati o canali): c'è "
                "qualcosa da controllare nei dati"
            )
    if AnalysisDomain.COSTS in areas:
        add("Costi", overview.costs.state, overview.costs.reason)
    if AnalysisDomain.LABOR in areas:
        add("Personale", overview.labor.state, overview.labor.reason)
    return rows, missing


def _data_status(runtime: ToolRuntime, _: _NoArgs) -> Observation:
    overview = runtime.overview(30)
    feed = runtime.feed()
    run = feed.run
    coverage = coverage_of(feed)
    areas = visible_areas(runtime)
    hidden = len(areas) < len(AnalysisDomain)

    area_rows: list[dict[str, Any]] = []
    analysed: list[str] = []
    not_analysed: list[str] = []
    for domain in AnalysisDomain:
        if domain not in areas:
            continue
        _analysis, count, outcome = area_outcome(domain, feed, coverage)
        area_rows.append(
            {
                "area": area_label(domain),
                "stato": _DOMAIN_STATE_TEXT[overview.domain_states[domain]],
                "decisioni": count,
                "esito": outcome,
            }
        )
        status = coverage_status_of(coverage, domain)
        if status is DomainCoverageStatus.EVALUATED:
            analysed.append(area_label(domain))
        elif status is DomainCoverageStatus.SKIPPED:
            not_analysed.append(area_label(domain))

    blocks, missing = _blocks(runtime, areas)
    data: dict[str, Any] = {
        "giorno analizzato": day(runtime.as_of),
        "stato dell'analisi": feed_state_text(feed, areas),
        "aree": area_rows,
        "blocchi di dati": blocks,
    }
    last = feed.last_successful_analysis
    if last is not None:
        data["ultima analisi completata"] = iso(last.as_of_local_date)
    if run is not None and not hidden:
        # domain-blind counts: withheld whenever an area is hidden
        data["controlli rimasti senza conclusione per dati insufficienti"] = run.insufficient_count
        data["controlli non mostrati perché poco affidabili"] = run.suppressed_count

    delivery = (
        _delivery_is_new(runtime, run)
        if {
            AnalysisDomain.REVENUE,
            AnalysisDomain.DISTRIBUTION,
        }
        & areas
        else None
    )
    notes = [
        "Sono fatti sull'analisi e sugli import, non un giudizio: NINFA non stabilisce se un dato "
        "sia aggiornato o vecchio.",
        "NINFA non registra il motivo per cui un controllo non ha concluso: non ipotizzarne uno.",
        "Gli orari sono nel fuso orario della struttura.",
    ]
    if delivery is True:
        data["nuovi dati di prenotazione rispetto all'analisi precedente"] = True
        notes.append(
            "L'ultimo import di prenotazioni ha cambiato i dati rispetto all'analisi precedente "
            "(oppure è la prima analisi con dati noti)."
        )
    elif delivery is False:
        data["nuovi dati di prenotazione rispetto all'analisi precedente"] = False
        notes.append(
            "Nessun nuovo dato di prenotazione rispetto all'analisi precedente: NINFA non sa "
            "quante prenotazioni siano arrivate nel frattempo (il pickup non è noto, non è zero) "
            "e per questo non produce nuove decisioni sul ritmo delle prenotazioni."
        )
    else:
        data["nuovi dati di prenotazione rispetto all'analisi precedente"] = None
        if run is not None and {AnalysisDomain.REVENUE, AnalysisDomain.DISTRIBUTION} & areas:
            missing.append(
                "non è possibile dire se l'ultimo import di prenotazioni abbia portato dati nuovi: "
                "l'analisi non registra abbastanza"
            )
    if hidden:
        notes.append("Alcune aree non sono consentite a questo utente e non sono incluse.")

    freshness: dict[str, Any] = {}
    fresh = overview.freshness
    if {AnalysisDomain.REVENUE, AnalysisDomain.DISTRIBUTION} & areas:
        freshness["prenotazioni"] = _freshness_of(fresh.bookings, runtime.timezone, runtime.as_of)
    if AnalysisDomain.COSTS in areas:
        freshness["costi"] = _freshness_of(fresh.costs, runtime.timezone, runtime.as_of)
    if AnalysisDomain.LABOR in areas:
        freshness["personale"] = _freshness_of(fresh.labor, runtime.timezone, runtime.as_of)

    coverage_data: dict[str, Any] = {
        "copertura dell'analisi": coverage_text(coverage, run is not None),
        "aree analizzate": analysed,
        "aree non analizzate": not_analysed,
    }
    if not_analysed:
        coverage_data["perché non analizzate"] = (
            "non fanno parte dell'analisi automatica di questa struttura"
        )
    if run is None:
        missing.append("l'analisi del giorno non è ancora disponibile")
    return Observation(
        tool="get_data_status",
        refs=("stato:analisi", "stato:dati"),
        data=data,
        coverage=coverage_data,
        freshness=freshness,
        not_available=tuple(dict.fromkeys(missing)),
        notes=tuple(notes),
        resolved={},
    )


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="get_current_property_context",
        description=(
            "Chi è la struttura e cosa sta guardando l'utente: nome, fuso orario, valuta, data di "
            "riferimento, camere vendibili, ruolo dell'utente e la pagina aperta (solo un "
            "suggerimento). Usalo per 'cosa sai di questa struttura?' e per capire a cosa si "
            "riferisce 'questo' o 'perché è così alto?'. Nessun argomento."
        ),
        domain=AccessDomain.COMPANY,
        args_model=_NoArgs,
        handler=_property_context,
    ),
    ToolDefinition(
        name="get_data_status",
        description=(
            "Stato dei dati e dell'analisi del giorno: quali aree sono state analizzate, quali no, "
            "quali blocchi di dati mancano e perché, quando è stato fatto l'ultimo import per "
            "prenotazioni, costi e personale, se l'ultimo import ha portato dati nuovi. Usalo per "
            "'perché oggi non ho decisioni?', 'perché vedo Analisi parziale?', 'quali dati ti "
            "mancano?', 'da dove arrivano questi dati?'. Nessun argomento."
        ),
        domain=None,
        args_model=_NoArgs,
        handler=_data_status,
    ),
)

__all__ = ["TOOLS"]

"""Mia tools: the structure (the property itself) - profile, room inventory, connected sources.

    get_property_profile   what NINFA holds about the property, and the automatic analysis setup
    get_room_inventory     how many rooms the property can sell (the number occupancy rests on)
    get_connected_sources  the data sources the property receives data from, as Struttura shows them

Read-only, through the services the Struttura screens already use (`RoomInventoryService.state`,
`AnalysisPolicyService.get`, `DataSourcesService.overview`, the repositories). Honesty about what
the page shows matters here more than anywhere: the Struttura profile block shows only the name and
the time zone as known facts and says "Non configurata" for the rest, because no real data says
otherwise
(apps/web/lib/structure/overview.ts); the demonstration dataset of that page is NEVER a source for
Mia. What NINFA does not hold goes in `not_available`, never as a guess and never as an example.
"""

from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.labels import data_domain_label
from app.modules.ai.mia.tools.base import ToolDefinition, ToolRuntime
from app.modules.ai.mia.tools.format import iso, moment
from app.modules.ai.mia.tools.imports import NOT_SHOWN_NOTE, safe_user_text
from app.modules.ai.mia.types import Observation
from app.modules.analysis.automatic import DAILY_ANALYSIS_LOCAL_TIME
from app.modules.analysis.policy import AnalysisPolicyService
from app.modules.analysis.room_inventory import RoomInventoryService
from app.modules.data_overview.types import CapacityState
from app.modules.data_sources.service import DataSourcesService
from app.modules.data_sources.types import SourceCard, SourceState
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository, ImportJobRepository

MAX_SOURCES_SHOWN = 10
MAX_CHANNELS_SHOWN = 8

# `strutturaCopy` (apps/web/lib/structure/copy.ts): the blocks of the page, by their own titles.
PROFILE_BLOCK = "1. Profilo struttura"
ROOMS_BLOCK = "2. Inventario camere"
SOURCES_BLOCK = "4. Fonti dati"

# What the Struttura profile block would show if it had it, and NINFA does not hold: the page reads
# "Non configurata" for each. (A seasonal calendar, a star category and a location are not facts the
# analysis uses, so nothing stores them.)
_PROFILE_NOT_HELD = (
    "la tipologia della struttura (hotel, agriturismo...)",
    "la categoria (le stelle)",
    "la località",
    "la stagionalità principale e l'alta stagione",
    "il periodo di apertura e l'eventuale chiusura annuale",
    "la capacità massima in ospiti",
    "le tipologie di camera (NINFA conosce solo il numero totale di camere vendibili)",
)

# `sourcesCopy` (apps/web/lib/sources/copy.ts): the five cards and their states, by their own words.
_CARD_LABELS = {
    SourceCard.PMS: "PMS",
    SourceCard.CHANNEL_MANAGER: "Channel Manager",
    SourceCard.OTA: "OTA",
    SourceCard.ACCOUNTING: "Contabilità",
    SourceCard.STAFF: "Personale",
}
_STATE_LABELS = {
    SourceState.NOT_CONFIGURED: "Non configurato",
    SourceState.CONFIGURED_FILE: "Configurato",
    SourceState.CONNECTED: "Connesso",
    SourceState.DERIVED: "Già ricevuto",
}


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- get_property_profile ------------------------------------------------------------------------


def _get_property_profile(runtime: ToolRuntime, args: NoArgs) -> Observation:
    policy = AnalysisPolicyService(runtime.session, runtime.tenant).get(runtime.property_id)
    booking_source = None
    if policy is not None and policy.booking_data_source_id is not None:
        source = DataSourceRepository(runtime.session, runtime.tenant).get(
            policy.booking_data_source_id
        )
        if source is not None and source.property_id == runtime.property_id:
            booking_source = {
                "tipo_di_dati": data_domain_label(DataSourceDomain.BOOKINGS),
                "nome_fonte_come_dato": safe_user_text(source.name),
                "attiva": source.is_active,
            }

    if policy is None:
        automatic = {
            "configurata_esplicitamente": False,
            "spiegazione": (
                "Nessuno ha configurato nulla: una struttura con una sola fonte di prenotazioni "
                "e almeno un import riuscito viene inclusa da sola nell'analisi giornaliera."
            ),
        }
    else:
        automatic = {
            "configurata_esplicitamente": True,
            "attiva": policy.enabled,
            "fonte_prenotazioni": booking_source,
            "spiegazione": (
                "L'analisi giornaliera è attiva per questa struttura."
                if policy.enabled
                else "L'analisi giornaliera è stata spenta da un operatore e resta spenta."
            ),
        }
    automatic["quando"] = (
        f"una volta al giorno, dalle {DAILY_ANALYSIS_LOCAL_TIME:%H:%M} (ora locale della "
        "struttura), anche se quella mattina non è arrivato nessun file"
    )

    return Observation(
        tool="get_property_profile",
        refs=("struttura:profilo",),
        data={
            "profilo": {
                "nome": runtime.property_name,
                "fuso_orario": str(runtime.timezone),
                "valuta": runtime.currency,
            },
            "analisi_automatica": automatic,
            "dove_si_vede": (
                f"Struttura > «{PROFILE_BLOCK}» (la pagina mostra il nome e il fuso orario)"
            ),
        },
        not_available=tuple(f"NINFA non ha {item}" for item in _PROFILE_NOT_HELD),
        notes=(
            "La pagina Struttura mostra «Non configurata» per ciò che NINFA non tiene: non è un "
            "errore e non va compilato altrove.",
            "La valuta è un dato di NINFA (gli importi sono sempre in questa valuta, senza "
            "conversioni), anche se oggi il blocco del profilo non la mostra.",
            "Il numero di camere non è nel profilo: è l'inventario camere (blocco "
            f"«{ROOMS_BLOCK}»).",
            "Mia può solo leggere: non modifica il profilo né le impostazioni.",
        ),
    )


# --- get_room_inventory --------------------------------------------------------------------------

_CAPACITY_LINES: dict[CapacityState, str] = {
    CapacityState.KNOWN: (
        "ogni notte con prenotazioni ha la sua capacità: l'occupazione è calcolata"
    ),
    CapacityState.PARTIAL: (
        "solo alcune notti hanno la capacità: l'occupazione si basa su quelle soltanto"
    ),
    CapacityState.MISSING: "nessuna notte ha la capacità: l'occupazione non si può calcolare",
    CapacityState.AWAITING_ANALYSIS: (
        "l'inventario è stato impostato dopo l'ultima analisi: la prossima lo recepirà"
    ),
}


def _noon_of(day: date, runtime: ToolRuntime) -> datetime:
    """The instant `RoomInventoryService.state` reads its "today" from, set to the business date
    the person is looking at (the service otherwise reads the server's clock)."""
    return datetime.combine(day, time(12, 0), tzinfo=runtime.timezone)


def _get_room_inventory(runtime: ToolRuntime, args: NoArgs) -> Observation:
    state = RoomInventoryService(runtime.session, runtime.tenant).state(
        runtime.property_id, now=_noon_of(runtime.as_of, runtime)
    )
    not_available: list[str] = []
    data: dict[str, Any] = {
        "configurato": state.configured,
        "camere_vendibili": state.rooms_available,
        "il_numero_varia_nelle_prossime_notti": state.varies,
        "prima_notte": iso(state.first_night),
        "ultima_notte": iso(state.last_night),
        "valido_dal": iso(state.known_since),
        "oggi_per_la_struttura": iso(state.today),
    }
    if not state.configured:
        not_available.append(
            "L'inventario camere non è ancora configurato: senza il numero di camere vendibili "
            "NINFA non calcola l'occupazione (le prenotazioni, i ricavi e l'ADR restano)"
        )

    coverage: dict[str, Any] | None = None
    consistency: dict[str, Any] | None = None
    try:
        occupancy = runtime.overview(30).occupancy
    except Exception:
        occupancy = None
        not_available.append(
            "Non riesco a leggere ora come l'inventario si riflette sull'occupazione di Dati"
        )
    if occupancy is not None and occupancy.today is not None:
        period = occupancy.days_30
        if period is not None:
            coverage = {
                "notti_con_prenotazioni": period.nights_with_data,
                "notti_con_capacita_nota": period.nights_with_capacity,
                "notti_del_periodo": period.nights_requested,
                "stato_della_capacita": (
                    None if period.capacity is None else _CAPACITY_LINES[period.capacity]
                ),
            }
        over = occupancy.inventory_consistency
        consistency = {
            "notti_con_piu_camere_prenotate_di_quelle_in_inventario": over.over_capacity_nights,
            "prima_notte": iso(over.first_night),
            "cosa_significa": (
                "è una domanda sui dati, non un verdetto: l'inventario può essere troppo basso, "
                "la struttura può essere davvero in overbooking, o una prenotazione può essere "
                "sbagliata. NINFA non sa quale: non taglia né corregge nulla e mostra "
                "l'occupazione oltre il 100%."
                if over.over_capacity_nights > 0
                else "le prenotazioni non superano mai le camere in inventario"
            ),
        }
    elif occupancy is not None:
        not_available.append(
            "Per oggi non c'è ancora un'analisi con prenotazioni: non posso dire come "
            "l'inventario si riflette sull'occupazione"
        )
    data["coerenza_con_le_prenotazioni"] = consistency

    return Observation(
        tool="get_room_inventory",
        refs=("struttura:camere",),
        data={
            **data,
            "dove_si_cambia": (
                f"Struttura > «{ROOMS_BLOCK}» > «Modifica inventario» (o «Configura inventario» "
                "se non c'è ancora): il numero di camere e, se serve, «Valido dal»"
            ),
        },
        coverage=coverage,
        not_available=tuple(not_available),
        notes=(
            "L'inventario è UN numero di camere vendibili, scritto su ogni notte da una certa "
            "data in poi. Le analisi già fatte non cambiano: il nuovo numero vale per le "
            "prossime (e, con «Valido dal» nel passato, NINFA ne rifà una).",
            "La capacità non è mai dedotta dalle prenotazioni.",
            "Mia può solo leggere: non cambia l'inventario.",
        ),
    )


# --- get_connected_sources -----------------------------------------------------------------------

_SEVERAL = "più fonti attive per questi dati: NINFA non ne sceglie una da sola"
_ONLY_ONE_READ = " (in Dati i costi e il personale si leggono solo con una fonte sola)"


def _domain_situation(domain: DataSourceDomain, count: int, imported: bool) -> str:
    if count == 0:
        return "nessuna fonte attiva: NINFA non riceve questi dati"
    if count > 1:
        extra = _ONLY_ONE_READ if domain in (DataSourceDomain.COSTS, DataSourceDomain.LABOR) else ""
        return _SEVERAL + extra
    if not imported:
        return (
            "una fonte esiste ma non ha mai ricevuto un file: per la persona risulta «Non "
            "configurato»"
        )
    return "una fonte, che ha ricevuto almeno un file"


def _get_connected_sources(runtime: ToolRuntime, args: NoArgs) -> Observation:
    sources = list(
        DataSourceRepository(runtime.session, runtime.tenant).list_all(
            property_id=runtime.property_id
        )
    )
    jobs = ImportJobRepository(runtime.session, runtime.tenant)
    overview = DataSourcesService(runtime.session, runtime.tenant).overview(runtime.property_id)

    last_by_source = {
        source.id: jobs.latest_succeeded_for_data_source(source.id) for source in sources
    }
    shown = sources[:MAX_SOURCES_SHOWN]
    items = []
    for source in shown:
        job = last_by_source[source.id]
        finished = None if job is None else job.finished_at
        items.append(
            {
                "tipo_di_dati": data_domain_label(source.domain),
                "nome_come_dato": safe_user_text(source.name),
                "ultimo_import_riuscito": moment(finished),
                "mai_alimentata": finished is None,
            }
        )

    per_domain: dict[str, Any] = {}
    for domain in DataSourceDomain:
        of_domain = [source for source in sources if source.domain == domain]
        imported = any(last_by_source[source.id] is not None for source in of_domain)
        per_domain[data_domain_label(domain)] = {
            "fonti_attive": len(of_domain),
            "situazione": _domain_situation(domain, len(of_domain), imported),
        }

    cards = []
    for card in overview.cards:
        cards.append(
            {
                "scheda": _CARD_LABELS[card.card],
                "stato": _STATE_LABELS[card.state],
                "ultimo_aggiornamento": moment(card.last_update_at),
                "piu_fonti_attive": card.several_sources,
                "ricevuto_tramite": (
                    "i file di prenotazioni già importati"
                    if card.derived_from is not None
                    else None
                ),
                "canali_ricevuti_come_dato": [
                    safe_user_text(name, limit=40) for name in card.channels[:MAX_CHANNELS_SHOWN]
                ],
            }
        )

    return Observation(
        tool="get_connected_sources",
        refs=("struttura:fonti",),
        data={
            "schede_come_le_mostra_struttura": cards,
            "fonti_attive": items,
            "per_tipo_di_dati": per_domain,
            "integrazioni_automatiche_disponibili": list(overview.automatic_integrations),
            "dove_si_vede": f"Struttura > «{SOURCES_BLOCK}»",
        },
        coverage={
            "fonti_attive": len(sources),
            "fonti_mostrate": len(shown),
        },
        not_available=(
            "Nessun collegamento automatico con un PMS, un Channel Manager, un portale o un "
            "gestionale esiste oggi: i dati arrivano solo importando file (CSV o Excel; fatture "
            "XML per i costi)",
        ),
        notes=(
            "Le schede Channel Manager e OTA non sono un collegamento a parte: i canali "
            "arrivano dentro il file delle prenotazioni, quindi risultano «Già ricevuto».",
            "Una fonte conta come «Configurato» solo dopo il primo import riuscito.",
            NOT_SHOWN_NOTE,
        ),
    )


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="get_property_profile",
        description=(
            "Cosa NINFA sa della struttura: nome, fuso orario, valuta, e come è impostata "
            "l'analisi automatica giornaliera. Dice anche cosa NINFA NON tiene (tipologia, "
            "stelle, località, stagionalità...) e dove si vede il profilo. Usalo per: 'che cosa "
            "sai di questa struttura?', 'che fuso orario/valuta usa NINFA?', 'quando parte "
            "l'analisi?'."
        ),
        domain=AccessDomain.COMPANY,
        args_model=NoArgs,
        handler=_get_property_profile,
    ),
    ToolDefinition(
        name="get_room_inventory",
        description=(
            "L'inventario camere: quante camere vende la struttura (il numero su cui NINFA "
            "calcola l'occupazione), da quando vale, se varia, e se le prenotazioni lo superano "
            "(occupazione oltre il 100%). Dice dove si cambia. Usalo per: 'quante camere ha "
            "NINFA?', 'perché non vedo l'occupazione?', 'perché l'occupazione è sopra il 100%?', "
            "'come cambio il numero di camere?'."
        ),
        domain=AccessDomain.COMPANY,
        args_model=NoArgs,
        handler=_get_room_inventory,
    ),
    ToolDefinition(
        name="get_connected_sources",
        description=(
            "Le fonti dati collegate alla struttura, come le mostra Struttura > Fonti dati: per "
            "ogni tipo di dati (prenotazioni, costi, personale) quante fonti sono attive, quando "
            "è stato l'ultimo import riuscito, e le situazioni particolari (nessuna fonte, più "
            "fonti). Dice che oggi i dati arrivano solo da file. Usalo per: 'da dove arrivano "
            "questi dati?', 'quali fonti ho collegato?', 'perché NINFA non legge i costi?'."
        ),
        domain=AccessDomain.COMPANY,
        args_model=NoArgs,
        handler=_get_connected_sources,
    ),
)

__all__ = ["TOOLS", "NoArgs"]

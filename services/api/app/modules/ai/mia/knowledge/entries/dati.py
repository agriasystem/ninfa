"""Dati: the five tabs of the page and the blocks inside them, as the shipped copy names them."""

from app.modules.ai.mia.knowledge.entries._build import (
    FEATURE,
    SUBSECTION,
    api,
    copy,
    doc,
    entry,
    tab,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_DATI = "Barra laterale > Dati"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "dati.overview",
        SUBSECTION,
        "Dati > Panoramica",
        "La vista d'insieme: occupazione, ricavi camera, ADR, costi dell'ultimo mese concluso, "
        "dipendenza OTA e il dettaglio notte per notte.",
        tab("overview"),
        copy("Panoramica"),
        details=(
            "Occupazione con le schede Oggi, 7 giorni e 30 giorni.",
            "Indicatori del periodo: Ricavi camera, ADR, Camere-notte e Costi del mese.",
            "Grafico dell'occupazione per notte e tabella Dettaglio soggiorni.",
            "Un riquadro sulla Dipendenza OTA e la Copertura dell'analisi.",
        ),
        where=f"{_DATI}, scheda Panoramica",
        page="/dati",
        query={"tab": "overview"},
        related=(
            "dati.occupancy_card",
            "dati.occupancy_chart",
            "dati.nights_table",
            "dati.period_control",
        ),
        keywords=("panoramica", "riepilogo", "indicatori", "kpi", "vista d'insieme"),
    ),
    entry(
        "dati.bookings",
        SUBSECTION,
        "Dati > Prenotazioni",
        "Occupazione e ricavi camera per periodo (Oggi, 7 e 30 giorni), con il grafico e il "
        "dettaglio "
        "notte per notte.",
        tab("bookings"),
        copy("Riepilogo per periodo"),
        details=(
            "Per ogni periodo: occupazione, camere-notte, camere disponibili, ricavi camera, ADR e "
            "variazione rispetto a 7 giorni fa.",
            "La variazione compare solo quando ogni notte del periodo ha un dato sia oggi sia "
            "nell'osservazione di 7 giorni fa.",
            "La capienza disponibile conta solo le notti con capienza nota.",
        ),
        where=f"{_DATI}, scheda Prenotazioni",
        page="/dati",
        query={"tab": "bookings"},
        related=("dati.period_summary", "dati.nights_table", "metric.pickup", "metric.occupancy"),
        keywords=("prenotazioni", "occupazione per periodo", "ricavi camera", "camere-notte"),
        not_available=(
            "Non mostra cancellazioni o no-show come indicatori, né previsioni dell'occupazione "
            "finale.",
        ),
    ),
    entry(
        "dati.distribution",
        SUBSECTION,
        "Dati > Distribuzione",
        "La dipendenza dalle OTA: quanta parte delle camere-notte prenotate nei prossimi 30 giorni "
        "arriva da OTA rispetto al diretto, e il peso di ciascun canale.",
        tab("distribution"),
        copy("Peso dei canali"),
        details=(
            "Quota OTA e quota Diretto, con il Riferimento NINFA (il livello che NINFA si aspetta, "
            "non un obiettivo).",
            "Peso dei canali: le camere-notte di ogni canale sul totale di tutti i canali.",
            "Come leggere i numeri spiega la differenza tra quota OTA e peso di un canale.",
        ),
        where=f"{_DATI}, scheda Distribuzione",
        page="/dati",
        query={"tab": "distribution"},
        related=(
            "dati.distribution_card",
            "dati.channel_weights",
            "metric.ota_share",
            "metric.channel_weight",
            "decision.ota_dependency",
        ),
        keywords=(
            "distribuzione",
            "ota",
            "canali",
            "booking.com",
            "expedia",
            "diretto",
            "dipendenza",
        ),
        not_available=(
            "NINFA non calcola i ricavi per canale né le commissioni pagate a un canale: "
            "dice solo quanto pesano i canali sulle camere-notte prenotate.",
        ),
    ),
    entry(
        "dati.costs",
        SUBSECTION,
        "Dati > Costi",
        "I costi dell'ultimo mese concluso, per data fattura, con il costo netto, la variazione "
        "sul "
        "mese "
        "precedente e il costo per camera occupata di ogni categoria.",
        tab("costs"),
        copy("Costi per categoria"),
        details=(
            "Il mese in corso non è mostrato: conta solo l'ultimo mese concluso.",
            "Costo netto registrato, variazione rispetto al mese precedente e quota dei costi in "
            "una categoria riconosciuta.",
            "Tabella Costi per categoria con il Costo per camera occupata.",
            "Se il costo per camera non si può calcolare, la pagina dice quale giorno manca e "
            "perché.",
        ),
        where=f"{_DATI}, scheda Costi",
        page="/dati",
        query={"tab": "costs"},
        related=("dati.cost_categories", "dati.cpor_card", "metric.cpor", "decision.cpor_anomaly"),
        keywords=("costi", "spese", "fatture", "categorie", "cpor", "costo per camera"),
        not_available=(
            "NINFA non fa contabilità: non c'è margine, budget né ripartizione dei costi per "
            "competenza.",
            "I costi in un'altra valuta non sono inclusi nel totale.",
        ),
    ),
    entry(
        "dati.labor",
        SUBSECTION,
        "Dati > Personale",
        "Ore e costi del personale pianificati per i prossimi 7 giorni, dal piano più recente, con "
        "il "
        "dettaglio per ruolo e il rapporto con i ricavi on-books.",
        tab("labor"),
        copy("Ore e performance per ruolo"),
        details=(
            "Indicatori: Ore pianificate, Costo pianificato, Costo medio/ora, Incidenza sui ricavi "
            "on-books, "
            "Ricavo on-books per ora.",
            "Copertura del piano: dice per quanti giorni su 7 esiste un piano; le cifre riguardano "
            "solo quei giorni.",
            "Tabella per ruolo con ore, costo, costo medio/ora, quota del costo del personale e "
            "giorni con dati.",
            "In sintesi: una frase deterministica costruita con le cifre della pagina.",
        ),
        where=f"{_DATI}, scheda Personale",
        page="/dati",
        query={"tab": "labor"},
        related=(
            "dati.labor_coverage",
            "dati.labor_roles",
            "metric.labor_planned_hours",
            "metric.labor_incidence",
            "decision.labor_overstaffing",
        ),
        keywords=("personale", "ore", "turni", "reparti", "ruoli", "costo del personale", "staff"),
        not_available=(
            "NINFA non conosce i singoli dipendenti: lavora per reparto e per giorno.",
            "Il rapporto con i ricavi è sui ricavi on-books degli stessi giorni, non sul "
            "fatturato.",
        ),
    ),
    entry(
        "dati.period_control",
        FEATURE,
        "Periodo: 7 o 30 giorni",
        "Il selettore Periodo di Panoramica e Prenotazioni sceglie quante notti future guardare, a "
        "partire "
        "dal giorno dell'analisi: 7 oppure 30.",
        copy("7 giorni"),
        copy("30 giorni"),
        details=(
            "Sono finestre di notti future, non uno sguardo al passato.",
            "Il valore predefinito è 30 giorni; la scelta resta nell'indirizzo della pagina.",
        ),
        where=f"{_DATI}, in alto a destra nelle schede Panoramica e Prenotazioni",
        related=("dati.overview", "dati.bookings"),
        keywords=("periodo", "7 giorni", "30 giorni", "finestra", "prossimi giorni"),
        not_available=("Non si può scegliere un periodo passato né un intervallo personalizzato.",),
    ),
    entry(
        "dati.refresh",
        FEATURE,
        "Aggiorna dati",
        "Il pulsante Aggiorna dati di Dati rilegge i dati che NINFA ha già salvati; non importa "
        "file e "
        "non avvia una nuova analisi.",
        copy("Aggiorna dati"),
        related=("workflow.refresh_analysis", "nav.dati"),
        keywords=("aggiorna", "ricarica", "refresh", "rileggi"),
    ),
    entry(
        "dati.occupancy_card",
        FEATURE,
        "Riquadro Occupazione",
        "Mostra l'occupazione sulle prenotazioni attuali per Oggi, 7 giorni e 30 giorni, con le "
        "camere "
        "prenotate su quelle disponibili e per quante notti la capienza è nota.",
        copy("sulle prenotazioni attuali"),
        copy("Occupazione per periodo"),
        details=(
            "L'occupazione è sulle prenotazioni attuali: non è l'occupazione finale.",
            "Se manca l'inventario camere, le prenotazioni restano visibili ma l'occupazione non "
            "si calcola.",
        ),
        where=f"{_DATI}, Panoramica, in alto",
        related=(
            "metric.occupancy",
            "state.inventory_missing",
            "state.capacity_partial",
            "workflow.change_room_count",
        ),
        keywords=("occupazione", "camere prenotate", "capienza"),
    ),
    entry(
        "dati.occupancy_chart",
        FEATURE,
        "Grafico dell'occupazione",
        "Un grafico a barre dell'occupazione notte per notte nei prossimi giorni, con una tabella "
        "equivalente per chi non vede il grafico.",
        copy("Camere prenotate su camere disponibili, notte per notte"),
        details=(
            "Una notte che richiede attenzione è evidenziata.",
            "Una notte con capienza non nota non ha una barra di occupazione.",
            "Una notte sopra l'inventario mantiene l'altezza vera della barra e ha un segno "
            "distinto.",
        ),
        where=f"{_DATI}, Panoramica e Prenotazioni",
        related=("state.over_capacity", "state.night_status", "metric.occupancy"),
        keywords=("grafico", "barre", "occupazione per notte"),
    ),
    entry(
        "dati.nights_table",
        FEATURE,
        "Dettaglio soggiorni",
        "La tabella notte per notte: prenotazioni, camere prenotate e disponibili, occupazione, "
        "ricavi "
        "camera, ADR, il dato di 7 giorni fa, la variazione e lo stato.",
        copy("Dettaglio soggiorni"),
        copy("Solo attenzione"),
        details=(
            "Si può cercare per data e filtrare con Solo attenzione.",
            "Lo stato riflette solo le decisioni di NINFA per quella notte: non è un giudizio sui "
            "numeri.",
            "Una riga con una decisione ha il collegamento Apri la decisione.",
        ),
        where=f"{_DATI}, Panoramica e Prenotazioni",
        related=("state.night_status", "metric.pickup", "nav.decision_detail"),
        keywords=("dettaglio", "tabella", "notti", "soggiorni", "ricerca per data"),
    ),
    entry(
        "dati.period_summary",
        FEATURE,
        "Riepilogo per periodo",
        "La tabella della scheda Prenotazioni con una riga per Oggi, 7 e 30 giorni: occupazione, "
        "camere-notte, camere disponibili, ricavi camera, ADR e variazione rispetto a 7 giorni fa.",
        copy("Riepilogo per periodo"),
        copy("Variazione vs 7 giorni fa"),
        where=f"{_DATI}, scheda Prenotazioni",
        related=("dati.bookings", "metric.pickup"),
        keywords=("riepilogo", "per periodo", "variazione"),
    ),
    entry(
        "dati.distribution_card",
        FEATURE,
        "Riquadro Dipendenza OTA",
        "Mostra la quota OTA e la quota Diretto dei prossimi 30 giorni, il Riferimento NINFA e, se "
        "serve, "
        "perché NINFA non può valutare.",
        copy("Dipendenza OTA"),
        copy("Riferimento NINFA"),
        details=(
            "Se i dati non bastano, il riquadro dice perché (per esempio troppe prenotazioni su "
            "canali non classificati).",
            "Se mancano solo i periodi storici da confrontare, dice Storico ancora insufficiente: "
            "non c'è nulla da correggere.",
        ),
        where=f"{_DATI}, Panoramica e Distribuzione",
        related=(
            "metric.ota_share",
            "state.distribution_insufficient",
            "state.distribution_history",
            "decision.ota_dependency",
        ),
        keywords=("dipendenza ota", "quota ota", "riferimento ninfa"),
    ),
    entry(
        "dati.channel_weights",
        FEATURE,
        "Peso dei canali",
        "Per ogni canale, le camere-notte sul totale delle camere-notte prenotate di tutti i "
        "canali. "
        "È una misura diversa dalla quota OTA.",
        copy("Peso dei canali"),
        details=(
            "La pagina dice sempre su quante camere-notte sono calcolate le percentuali.",
            "Se le due misure non coincidono con le prenotazioni registrate, la composizione è "
            "indicativa.",
        ),
        where=f"{_DATI}, scheda Distribuzione",
        related=("metric.channel_weight", "metric.ota_share", "state.channel_mix_conflict"),
        keywords=("canali", "peso", "composizione", "mix"),
        not_available=("Non mostra ricavi né commissioni per canale.",),
    ),
    entry(
        "dati.cost_categories",
        FEATURE,
        "Costi per categoria",
        "La tabella dei costi dell'ultimo mese concluso per categoria (Personale, Lavanderia, "
        "Pulizie, "
        "Cibo, Utenze, Manutenzione, Marketing, Commissioni OTA e altre), con costo netto e costo "
        "per camera occupata.",
        copy("Costi per categoria"),
        copy("Commissioni OTA"),
        details=(
            "Una spesa senza categoria riconosciuta finisce in Non classificato.",
            "Le commissioni OTA compaiono solo come categoria di costo del mese, non per canale.",
        ),
        where=f"{_DATI}, scheda Costi",
        related=("metric.cpor", "term.cost_categories", "dati.costs"),
        keywords=("categorie", "lavanderia", "pulizie", "utenze", "commissioni ota"),
    ),
    entry(
        "dati.cpor_card",
        FEATURE,
        "Costo per camera occupata",
        "Il costo netto di una categoria diviso le camere occupate del mese. Quando non si può "
        "calcolare, la pagina spiega quale giorno manca e che cosa fare.",
        copy("Costo per camera occupata"),
        copy("Non calcolabile"),
        details=(
            "Le cause possibili: manca l'inventario camere per alcuni giorni, le prenotazioni "
            "importate "
            "non coprono il mese, qualche prenotazione cancellata o non presentata non ha data, "
            "oppure il "
            "calcolo si completa con la prossima analisi.",
            "Con l'inventario valido dal giorno giusto, NINFA ricostruisce da sola le camere "
            "occupate dei giorni mancanti.",
        ),
        where=f"{_DATI}, scheda Costi",
        related=(
            "metric.cpor",
            "state.cpor_not_computable",
            "workflow.set_inventory_valid_from",
            "term.reconstructed",
        ),
        keywords=("cpor", "costo per camera", "camera occupata", "non calcolabile"),
    ),
    entry(
        "dati.labor_coverage",
        FEATURE,
        "Copertura del piano",
        "Dice per quanti giorni dei 7 esiste un piano del personale: costo medio, incidenza e "
        "ricavo per "
        "ora sono calcolati solo su quei giorni.",
        copy("Copertura del piano"),
        copy("Piano disponibile per tutti i"),
        where=f"{_DATI}, scheda Personale",
        related=("state.labor_plan_partial", "metric.labor_incidence"),
        keywords=("copertura", "piano", "giorni coperti"),
    ),
    entry(
        "dati.labor_roles",
        FEATURE,
        "Ore e performance per ruolo",
        "La tabella del personale per reparto (Governanza, Ricevimento, Sala e bar, Cucina, "
        "Manutenzione, "
        "Direzione, Spa e benessere, Altro personale): ore, costo, costo medio/ora e quota sul "
        "costo totale.",
        copy("Ore e performance per ruolo"),
        copy("% costo personale"),
        details=("I giorni con dati sono contati e i giorni incompleti sono segnalati.",),
        where=f"{_DATI}, scheda Personale",
        related=("term.labor_departments", "metric.labor_cost_share"),
        keywords=("ruoli", "reparti", "governanza", "cucina", "ricevimento"),
    ),
    entry(
        "dati.freshness",
        FEATURE,
        "Ultimo import",
        "Dice quando NINFA ha finito l'ultimo import di prenotazioni, costi e personale. È un "
        "fatto, non "
        "un giudizio: non dice fino a quale data erano aggiornati i contenuti del file.",
        copy("Ultimo import prenotazioni"),
        copy("Ultimo import costi"),
        copy("Ultimo import personale"),
        doc("docs/architecture/booking-freshness-provenance-v1.md"),
        details=(
            "Se non c'è un import, dice perché: nessuna origine dati, più origini non "
            "confrontabili, oppure nessun import completato.",
        ),
        where=f"{_DATI}, in ogni scheda; anche nella pagina Oggi",
        related=("term.observed", "state.last_import_unknown"),
        keywords=(
            "freschezza",
            "aggiornamento",
            "ultimo import",
            "quando sono aggiornati",
            "dati aggiornati",
        ),
        not_available=(
            "NINFA non giudica se i dati sono aggiornati o vecchi: dice quando è finito l'import.",
        ),
    ),
    entry(
        "dati.analysis_coverage",
        FEATURE,
        "Copertura dell'analisi",
        "Dice quali aree sono state analizzate oggi (Ricavi, Distribuzione, Costi, Personale) e la "
        "data "
        "dell'ultima analisi completata.",
        copy("Copertura dell'analisi"),
        doc("docs/architecture/analysis-coverage-v1.md"),
        where=f"{_DATI}, in fondo alla Panoramica; riepilogo per area in Oggi",
        related=("state.partial_analysis", "state.not_analyzed", "decision.area_summary"),
        keywords=("copertura", "aree analizzate", "ultima analisi"),
    ),
    entry(
        "dati.data_origin",
        FEATURE,
        "Da dove arrivano i dati",
        "I dati di NINFA arrivano dai file importati (prenotazioni, costi, personale) e dalle "
        "analisi "
        "che NINFA ne ricava; le fonti collegate si vedono in Struttura > Fonti dati.",
        api("GET", "/data-sources"),
        copy("Fonti dati"),
        details=(
            "Ogni scheda di Dati dice quando è avvenuto l'ultimo import del suo tipo di dati.",
            "Le prenotazioni sono lette da un'unica fonte attiva: con più fonti NINFA non ne "
            "sceglie una.",
        ),
        where="Struttura > Fonti dati; Dati, riga Ultimo import",
        related=("struttura.sources", "dati.freshness", "state.several_sources"),
        keywords=("origine dei dati", "da dove arrivano", "fonte dati", "provenienza", "fonti"),
    ),
)

__all__ = ["ENTRIES"]

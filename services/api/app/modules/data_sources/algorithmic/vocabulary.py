"""NINFA's hospitality vocabulary: what a header can be called, per kind of data and field.

Versioned and data-only. It is NOT tied to one PMS or provider: it holds the words a hotel's
systems, its accountant and its own spreadsheets use, in Italian and English, written out,
abbreviated and the
way a database column is named (`reservation_code`, `CheckInDate`). It never decides anything: it is
the list of phrases the header matcher (`header.py`) compares a header with, and the list of phrases
that mean ANOTHER thing than the field they look like (`NOT_THE_FIELD`: a rate per night is not what
a stay cost).

Rules the entries follow, each one learned from a real collision:

* a phrase that names ONE field only. A bare "date", "data", "total", "importo", "price" says too
  little: those stay with the rules of `semantics_*.py` and the questions NINFA already asks about
  them. Nothing here turns a vague word into a certain one.
* a phrase is written the way a person reads it ("check in date"); the matcher folds case, accents,
  punctuation and camelCase, so one spelling is enough.
* an abbreviation is listed on its own and is only ever matched whole (never fuzzily).

`tests/test_algorithmic_vocabulary.py` checks the keys against the real field sets, that no phrase
is claimed by two fields of one kind of data, and that none of the phrases of the benchmark's
held-out list was copied in.
"""

from collections.abc import Mapping

from app.modules.ingestion.models import DataSourceDomain

VERSION = "hospitality-2026.11.1"

_SEPARATOR = "|"


def _phrases(block: str) -> tuple[str, ...]:
    return tuple(
        part.strip() for part in block.replace("\n", _SEPARATOR).split(_SEPARATOR) if part.strip()
    )


# --- bookings -------------------------------------------------------------------------------------

_BOOKINGS: dict[str, str] = {
    "source_record_id": """
        reservation id|reservation number|reservation no|reservation code|reservation ref|
        reservation reference|reservation key|booking id|booking number|booking no|booking code|
        booking ref|booking reference|confirmation number|confirmation no|confirmation code|
        confirmation id|conf no|conf number|conf code|res id|res no|res number|res code|res ref|
        resv id|resv no|resv number|rsv id|rsv no|rsv number|resa id|record locator|locator|pnr|
        itinerary number|itinerary id|folio number|folio no|file number|booking file|
        id prenotazione|numero prenotazione|n prenotazione|nr prenotazione|codice prenotazione|
        cod prenotazione|riferimento prenotazione|rif prenotazione|id pren|num pren|n pren|
        numero pratica|n pratica|nr pratica|codice pratica|numero conferma|codice conferma|
        n conferma|numero dossier|id soggiorno|numero soggiorno|codice soggiorno|id reserva
    """,
    "booked_at": """
        booking date|booked on|booked at|booked date|date booked|booking made on|booking created|
        booking timestamp|booking time|booking created at|booking created on|reservation date|
        reservation created|reservation created at|reservation created on|reservation timestamp|
        created at|created on|created date|creation date|date created|date of booking|
        date of reservation|insert date|inserted on|inserted at|insertion date|entry date|
        entered on|registered on|registration date|bkg date|bkd date|bkg created|res date|
        resv date|res created|data prenotazione|data di prenotazione|data della prenotazione|
        prenotata il|prenotato il|data creazione|data di creazione|creata il|creato il|
        data inserimento|data di inserimento|inserita il|inserito il|data pren|dt pren|
        data registrazione prenotazione|data acquisizione|data ricezione|acquisita il
    """,
    "check_in": """
        check in|checkin|check in date|checkin date|date check in|check in day|arrival|
        arrival date|arrival day|date of arrival|date arrival|arr|arr date|arrive|arrives|
        arrival on|stay from|stay start date|from date|date from|
        data check in|data checkin|data arrivo|arrivo|data di arrivo|giorno di arrivo|
        giorno arrivo|data ingresso|data di ingresso|ingresso|data entrata|inizio soggiorno|
        dal giorno|soggiorno dal|data inizio soggiorno|data di check in
    """,
    "check_out": """
        check out|checkout|check out date|checkout date|date check out|check out day|departure|
        departure date|departure day|date of departure|date departure|dep|dep date|depart|
        departs|departure on|stay to|stay until|stay end date|to date|date to|
        data check out|data checkout|data partenza|partenza|data di partenza|giorno di partenza|
        giorno partenza|data uscita|data di uscita|uscita|fine soggiorno|al giorno|soggiorno al|
        data fine soggiorno|data di check out|data di partenza prevista
    """,
    "status": """
        status|reservation status|booking status|res status|resv status|rsv status|
        reservation state|res state|booking status code|status code|status description|
        stato|stato prenotazione|stato della prenotazione|stato pren|stato reservation|
        stato conferma|stato soggiorno|stato pratica|stato della pratica
    """,
    "rooms": """
        rooms|number of rooms|no of rooms|num rooms|nr rooms|n rooms|room count|rooms booked|
        booked rooms|rooms reserved|count of rooms|rms|no rooms|numero camere|n camere|
        num camere|nr camere|camere|camere prenotate|numero di camere|numero stanze|n stanze|
        stanze|stanze prenotate|qta camere|quantita camere|totale camere
    """,
    "room_revenue": """
        room revenue|room total|room charges|room charge|room amount|room price|room cost|
        room rate total|accommodation revenue|accommodation total|accommodation amount|
        accommodation charges|lodging revenue|lodging total|lodging amount|net room revenue|
        room only revenue|rooms revenue|rev camere|rev camera|revenue camere|revenue camera|
        ricavo camera|ricavi camera|ricavo camere|ricavi camere|importo camera|importo camere|
        totale camera|totale camere importo|prezzo camera|prezzo camere|costo camera|
        costo camere|fatturato camere|fatturato camera|ricavo alloggio|ricavo pernottamento|
        importo alloggio|importo pernottamento|totale alloggio|totale pernottamento
    """,
    "total_revenue": """
        grand total|booking total|reservation total|total booking amount|
        total reservation amount|gross total|total gross|totale prenotazione|
        totale generale|totale lordo|importo totale prenotazione
    """,
    "channel": """
        channel|booking channel|reservation channel|sales channel|distribution channel|
        booking source|reservation source|source name|source code|source of business|
        channel name|channel code|ota|ota name|agency name|travel agency|booking origin|
        reservation origin|origin of booking|canale|canale di vendita|canale vendita|
        canale di prenotazione|canale prenotazione|provenienza|provenienza prenotazione|
        origine prenotazione|origine della prenotazione|fonte prenotazione|
        fonte della prenotazione|portale|portale di prenotazione|nome canale|codice canale|
        agenzia|nome agenzia|intermediario
    """,
    "guests": """
        guests|number of guests|no of guests|num guests|nr guests|n guests|guest count|
        pax|number of pax|no of pax|persons|number of persons|no of persons|people|
        number of people|occupants|occupancy|total guests|total pax|adults|number of adults|
        ospiti|numero ospiti|n ospiti|nr ospiti|num ospiti|numero di ospiti|persone|
        numero persone|n persone|nr persone|adulti|numero adulti|n adulti|occupanti|
        totale ospiti|totale persone
    """,
    "commission_amount": """
        commission|commission amount|commission total|commission value|commission eur|
        commission paid|ota commission|ota commission amount|channel commission|
        agency commission|comm amount|comm total|commissione|commissione importo|
        importo commissione|importo commissioni|commissioni|valore commissione|
        provvigione|provvigioni|importo provvigione|commissione ota|commissione canale|
        commissione agenzia|commissione pagata
    """,
    "commission_rate": """
        commission rate|commission percent|commission percentage|commission pct|
        commission %|comm rate|comm %|comm percent|ota commission rate|channel commission rate|
        % commission|percentuale commissione|percentuale commissioni|perc commissione|
        commissione percentuale|commissione %|% commissione|aliquota commissione|
        tasso commissione|percentuale provvigione|provvigione %
    """,
    "cancelled_at": """
        cancellation date|cancelled on|cancelled at|canceled on|canceled at|date cancelled|
        date canceled|cancel date|cancelation date|cancellation timestamp|cancelled date|
        date of cancellation|data cancellazione|data di cancellazione|cancellata il|
        cancellato il|annullata il|annullato il|data annullamento|data di annullamento|
        data storno|stornata il
    """,
    "room_type": """
        room type|room category|room class|room kind|room type name|room type code|
        accommodation type|unit type|type of room|category of room|tipo camera|tipo di camera|
        tipologia camera|tipologia di camera|categoria camera|categoria di camera|
        tipo stanza|tipologia stanza|categoria stanza|tipo alloggio|tipologia alloggio|
        tipo unita|tipo sistemazione|sistemazione
    """,
    "rate_plan": """
        rate plan|rate plan name|rate plan code|rate code|rate name|rate type|rate description|
        meal plan|board|board basis|board type|meal basis|treatment|package|package name|
        piano tariffario|piano tariffa|piano di tariffa|piano tariffe|tariffa applicata|
        codice tariffa|nome tariffa|tipo tariffa|trattamento|trattamento pensione|pensione|
        formula|formula soggiorno|piano pasti
    """,
}

# --- labor ----------------------------------------------------------------------------------------

_LABOR: dict[str, str] = {
    "work_date": """
        work date|working date|shift date|date worked|day worked|work day|workday|
        duty date|roster date|rota date|schedule date|date of work|data lavoro|data turno|
        data di lavoro|data del turno|giorno lavorato|giorno di lavoro|giornata lavorativa|
        data giornata|data servizio|data prestazione
    """,
    "role": """
        department|dept|department name|dept name|section|team|division|work department|
        job|job title|job role|job function|position|position title|role|staff role|
        reparto|reparto di appartenenza|nome reparto|dipartimento|settore|area di lavoro|
        squadra|divisione|mansione|ruolo|qualifica|funzione|posizione|ruolo lavorativo|
        servizio|unita operativa
    """,
    "planned_hours": """
        planned hours|scheduled hours|rostered hours|rota hours|budget hours|budgeted hours|
        hours planned|hours scheduled|hours rostered|hours budget|plan hours|planned time|
        scheduled time hours|contracted hours planned|ore previste|ore pianificate|
        ore programmate|ore a budget|ore budget|ore da contratto previste|ore in programma|
        ore di turno previste|ore turno previste|ore prev|h previste|h pianificate|
        h programmate|totale ore previste|tot ore previste|totale ore pianificate
    """,
    "actual_hours": """
        actual hours|worked hours|hours worked|clocked hours|hours clocked|punched hours|
        hours actual|actual time worked|real hours|payroll hours|timesheet hours|
        ore lavorate|ore effettive|ore effettuate|ore svolte|ore consuntivo|ore a consuntivo|
        ore reali|ore timbrate|ore rilevate|ore eff|h lavorate|h effettive|h svolte|
        totale ore lavorate|tot ore lavorate|totale ore effettive|tot ore effettive
    """,
    "planned_cost": """
        planned cost|planned labor cost|planned labour cost|scheduled cost|budget cost|
        budgeted cost|budgeted labor cost|rostered cost|planned payroll|labour budget|
        labor budget|costo previsto|costo pianificato|costo programmato|costo a budget|
        costo del lavoro previsto|costo lavoro previsto|costo personale previsto|
        costo personale pianificato|budget costo|budget personale
    """,
    "actual_cost": """
        actual cost|actual labor cost|actual labour cost|real cost|actual payroll|
        costo effettivo|costo consuntivo|costo a consuntivo|costo reale|
        costo del lavoro effettivo|costo lavoro effettivo|costo personale effettivo
    """,
    "currency": """
        currency|currency code|ccy|curr|valuta|codice valuta|divisa|moneta
    """,
}

# --- costs ----------------------------------------------------------------------------------------

_COSTS: dict[str, str] = {
    "supplier_name": """
        supplier|supplier name|vendor|vendor name|payee|payee name|creditor|creditor name|
        issuer name|biller|billed by|invoiced by|seller|company name|business name|
        fornitore|nome fornitore|denominazione fornitore|ragione sociale|
        ragione sociale fornitore|denominazione|emittente|nome emittente|cedente|
        cedente prestatore|creditore|nome creditore|venditore|ditta|ditta fornitrice|
        azienda fornitrice|intestatario fattura
    """,
    "supplier_vat_number": """
        vat number|vat no|vat id|vat code|supplier vat|supplier vat number|vendor vat|
        vat registration|vat reg no|tax id|tax number|partita iva|p iva|piva|p.iva|
        partita iva fornitore|piva fornitore|p iva fornitore|numero partita iva|
        codice partita iva|identificativo fiscale
    """,
    "supplier_tax_code": """
        tax code|fiscal code|supplier tax code|codice fiscale|cod fiscale|cf|
        codice fiscale fornitore|cf fornitore
    """,
    "invoice_number": """
        invoice number|invoice no|invoice nr|invoice num|invoice id|invoice ref|
        invoice reference|invoice code|inv no|inv number|inv nr|inv id|document number|
        document no|document nr|document id|document ref|doc id|
        bill number|bill no|bill id|voucher number|numero fattura|n fattura|nr fattura|
        num fattura|id fattura|codice fattura|riferimento fattura|rif fattura|
        numero documento|n documento|nr documento|num documento|id documento|
        protocollo|numero protocollo|n protocollo|fattura n|
        fattura numero|fattura nr|documento n|documento numero|numero registrazione
    """,
    "invoice_date": """
        invoice date|date of invoice|invoice issued|invoice issue date|invoicing date|
        billing date|bill date|document date|date of document|issue date|date of issue|
        issued date|inv date|doc date|data fattura|data della fattura|data di fattura|
        data documento|data del documento|data di emissione|data emissione|
        data emissione fattura|data emissione documento|fattura del|documento del|
        emissione|data fattura acquisto|data doc
    """,
    "due_date": """
        due date|payment due|payment due date|payment due on|due on|pay by|pay by date|
        payable by|payment deadline|payment date due|scadenza|data scadenza|
        data di scadenza|scadenza pagamento|data scadenza pagamento|scadenza fattura|
        pagabile entro|da pagare entro|entro il|termine di pagamento|termine pagamento
    """,
    "document_type": """
        document type|doc type|invoice type|type of document|document kind|document class|
        tipo documento|tipo doc|tipo fattura|tipologia documento|tipologia fattura|
        tipo di documento|classe documento|td|tipo documento sdi
    """,
    "currency": """
        currency|currency code|ccy|curr|valuta|codice valuta|divisa|moneta
    """,
    # (no `invoice_net_amount` here on purpose: a register's bare "Imponibile", "Netto" or
    # "Net amount" is a LINE amount in NINFA's costs model - `line_total`, the importer's own
    # names - and the document-level net is read by V3's word rules. A second reading of the same
    # words would change which field a register's net amount lands in.)
    "invoice_tax_amount": """
        vat amount|vat total|vat value|vat eur|tax amount|tax total|tax value|sales tax|
        iva|importo iva|totale iva|valore iva|imposta|importo imposta|totale imposta|
        iva importo|iva totale|iva euro|imposta iva
    """,
    "invoice_gross_amount": """
        gross amount|gross total|gross value|total incl vat|total including vat|
        total with vat|total inc vat|amount incl vat|amount including vat|amount with vat|
        grand total|invoice total|document total|total payable|
        totale fattura|totale documento|totale lordo|importo lordo|lordo|
        totale iva inclusa|importo iva inclusa|totale con iva|importo con iva|
        totale compresa iva|totale da pagare|importo totale fattura
    """,
    "line_description": """
        description|line description|item description|item|item name|details|detail|
        narrative|memo|line text|goods and services|descrizione|descrizione riga|
        descrizione articolo|descrizione voce|descrizione prestazione|dettaglio|
        dettagli|oggetto|oggetto fattura|voce|descrizione bene o servizio|
        bene o servizio|prestazione|descrizione del servizio|natura prestazione
    """,
    "quantity": """
        quantity|qty|quantity ordered|quantity invoiced|units|number of units|
        quantita|qta|q ta|q.ta|quantita fatturata|pezzi|
        numero pezzi|n pezzi
    """,
    "unit_price": """
        unit price|price per unit|unit cost|price each|cost per unit|unit rate|
        prezzo unitario|prezzo per unita|prezzo unit|costo unitario|p u|pu|
        prezzo cad|prezzo cadauno|importo unitario|prezzo al pezzo
    """,
    "line_total": """
        line total|line amount|line value|line net|line net amount|row total|row amount|
        totale riga|importo riga|valore riga|totale linea|importo linea|netto riga|
        imponibile riga|totale voce|importo voce|prezzo totale riga|totale prezzo
    """,
    "vat_rate": """
        vat rate|vat percent|vat percentage|vat pct|vat %|tax rate|tax percent|tax %|
        % vat|rate of vat|aliquota iva|aliquota|iva %|% iva|percentuale iva|perc iva|
        iva percentuale|aliquota imposta|aliq iva|aliquota %
    """,
    "cost_category": """
        category|expense category|cost category|cost type|expense type|type of expense|
        type of cost|expense class|cost class|cost group|expense group|account category|
        spending category|categoria|categoria spesa|categoria di spesa|categoria costo|
        categoria di costo|tipo spesa|tipo di spesa|tipo costo|tipo di costo|classe spesa|
        classe di spesa|gruppo spesa|gruppo costo|voce di costo|voce costo|natura costo|
        natura della spesa|conto economico|categoria merceologica
    """,
}

ALIASES: Mapping[DataSourceDomain, Mapping[str, tuple[str, ...]]] = {
    DataSourceDomain.BOOKINGS: {field: _phrases(block) for field, block in _BOOKINGS.items()},
    DataSourceDomain.LABOR: {field: _phrases(block) for field, block in _LABOR.items()},
    DataSourceDomain.COSTS: {field: _phrases(block) for field, block in _COSTS.items()},
}

# Phrases that look like a field and are ANOTHER thing. A header that IS one of these is never the
# field, however alike the words are: a rate per night is not what the stay cost, the number of room
# NIGHTS is not the number of rooms, the time of arrival is not the day.
NOT_THE_FIELD: Mapping[DataSourceDomain, Mapping[str, tuple[str, ...]]] = {
    DataSourceDomain.BOOKINGS: {
        "room_revenue": _phrases("""
            adr|average daily rate|avg daily rate|average rate|avg rate|revpar|rate per night|
            price per night|nightly rate|night rate|room rate|daily rate|tariffa media|
            tariffa notte|tariffa a notte|prezzo notte|prezzo a notte|prezzo medio|
            tariffa giornaliera|prezzo per notte|importo per notte|room nights|nights|notti
        """),
        "total_revenue": _phrases("""
            adr|average daily rate|rate per night|price per night|nightly rate|daily rate|
            tariffa notte|prezzo notte|prezzo per notte|tariffa giornaliera
        """),
        "rooms": _phrases("""
            room nights|room night|nights|number of nights|nr nights|notti|numero notti|
            n notti|room number|room no|numero camera|n camera|nr camera|room name
        """),
        "guests": _phrases("""
            children|number of children|numero bambini|bambini|infants|neonati|
            nights|notti|number of nights
        """),
        "check_in": _phrases("""
            check in time|arrival time|ora arrivo|ora check in|orario arrivo|eta arrival
        """),
        "check_out": _phrases("""
            check out time|departure time|ora partenza|ora check out|orario partenza
        """),
        "booked_at": _phrases("""
            arrival date|departure date|data arrivo|data partenza|check in date|check out date|
            cancellation date|data cancellazione|modified on|data modifica|updated at|
            last modified|ultima modifica
        """),
        "status": _phrases("""
            payment status|stato pagamento|stato del pagamento|stato civile|marital status|
            housekeeping status|stato pulizia|room status|stato camera
        """),
        "commission_amount": _phrases("""
            commission rate|commission percent|commission %|percentuale commissione|
            commissione %|net after commission|netto dopo commissione
        """),
    },
    DataSourceDomain.LABOR: {
        "planned_hours": _phrases("""
            overtime hours|ore straordinario|holiday hours|ore ferie|sick hours|ore malattia|
            contract hours|ore contratto|hourly rate|tariffa oraria|costo orario
        """),
        "actual_hours": _phrases("""
            overtime hours|ore straordinario|holiday hours|ore ferie|sick hours|ore malattia|
            contract hours|ore contratto|break hours|ore pausa|hourly rate|tariffa oraria|
            costo orario
        """),
        "planned_cost": _phrases("hourly cost|hourly rate|costo orario|tariffa oraria"),
        "actual_cost": _phrases("hourly cost|hourly rate|costo orario|tariffa oraria"),
    },
    DataSourceDomain.COSTS: {
        # (a REGISTRATION date is deliberately a fallback document date in V3: not blocked here)
        "invoice_date": _phrases("""
            due date|scadenza|data scadenza|payment date|data pagamento
        """),
        "invoice_net_amount": _phrases("""
            vat amount|importo iva|vat|iva|gross amount|totale lordo|totale fattura
        """),
        "invoice_gross_amount": _phrases("""
            net amount|imponibile|importo netto|netto|vat amount|importo iva
        """),
        "invoice_tax_amount": _phrases("""
            vat rate|aliquota iva|vat %|iva %|net amount|imponibile|gross amount|totale lordo
        """),
        "vat_rate": _phrases("vat amount|importo iva|totale iva|tax amount|importo imposta"),
    },
}

# Words that name the KIND of document a header sits in. They are not an extra word against a
# phrase ("Reservation - Arrival" is an arrival in a bookings file).
CONTEXT_WORDS: Mapping[DataSourceDomain, frozenset[str]] = {
    DataSourceDomain.BOOKINGS: frozenset(
        ("booking", "bookings", "reservation", "reservations", "prenotazione", "prenotazioni")
    ),
    DataSourceDomain.LABOR: frozenset(
        ("staff", "employee", "employees", "personale", "dipendente", "dipendenti", "shift")
    ),
    DataSourceDomain.COSTS: frozenset(
        ("invoice", "invoices", "fattura", "fatture", "supplier", "fornitore", "purchase")
    ),
}

# Pairs of words that are each other's opposite in a header: a header that differs from a phrase by
# one of these pairs (and by nothing else) is the OPPOSITE thing, however alike the letters are.
OPPOSITES: tuple[tuple[str, str], ...] = (
    ("in", "out"),
    ("arrival", "departure"),
    ("arrivo", "partenza"),
    ("arr", "dep"),
    ("entrata", "uscita"),
    ("ingresso", "uscita"),
    ("start", "end"),
    ("inizio", "fine"),
    ("from", "to"),
    ("dal", "al"),
    ("planned", "actual"),
    ("previste", "effettive"),
    ("previsto", "effettivo"),
    ("scheduled", "worked"),
    ("budget", "actual"),
    ("net", "gross"),
    ("netto", "lordo"),
    ("imponibile", "lordo"),
    ("excl", "incl"),
    ("excluding", "including"),
    ("esclusa", "inclusa"),
    ("senza", "con"),
    ("booked", "cancelled"),
    ("prenotata", "cancellata"),
    ("created", "cancelled"),
    ("room", "total"),
    ("camera", "totale"),
    ("camere", "totale"),
    ("rate", "amount"),
    ("percent", "amount"),
    ("perc", "importo"),
    ("hours", "cost"),
    ("ore", "costo"),
    ("invoice", "due"),
    ("fattura", "scadenza"),
    ("issue", "due"),
)


def aliases_of(domain: DataSourceDomain, field: str) -> tuple[str, ...]:
    return ALIASES.get(domain, {}).get(field, ())


def not_the_field(domain: DataSourceDomain, field: str) -> tuple[str, ...]:
    return NOT_THE_FIELD.get(domain, {}).get(field, ())


__all__ = [
    "ALIASES",
    "CONTEXT_WORDS",
    "NOT_THE_FIELD",
    "OPPOSITES",
    "VERSION",
    "aliases_of",
    "not_the_field",
]

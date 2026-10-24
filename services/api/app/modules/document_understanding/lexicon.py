"""The words a header row, a total row, a section row or a summary sheet are made of.

Deliberately small and generic (Italian and English): this vocabulary only helps FIND the table - it
does not say what a column means (that is `app.modules.data_sources`, domain by domain). A header
row is the row where many of these words appear and rows of values follow.
"""

from app.modules.document_understanding.text import stems

# Words that show up in the headers of bookings, staff and cost files.
HEADER_STEMS: frozenset[str] = stems(
    """
    data date giorno day nome cognome name dipendente persona persone reparto mansione ruolo
    qualifica
    area settore dipartimento department dept team squadra funzione posizione ore ora hours hour
    previste pianificate programmate effettive lavorate reali consuntivo planned scheduled actual
    worked
    costo costi cost importo totale total netto lordo imponibile iva vat tax valuta currency divisa
    prenotazione prenotazioni reservation booking codice id numero number arrivo partenza arrival
    departure checkin checkout check in out notti nights camere camera room rooms ospiti ospite
    guest guests pax canale channel provenienza source origine portale ota stato status tariffa rate
    ricavo revenue fornitore supplier vendor fattura invoice documento doc descrizione description
    categoria category scadenza due quantita quantity unita unit prezzo price commissione commission
    turno shift lun mar mer gio ven sab dom mon tue wed thu fri sat sun
    """
)

# A row whose first words are these is a total (a subtotal, a grand total...), not data.
TOTAL_WORDS: tuple[str, ...] = (
    "tot",
    "totale",
    "totali",
    "subtotale",
    "sub totale",
    "totale generale",
    "totale complessivo",
    "total",
    "subtotal",
    "grand total",
    "somma",
    "sum",
)

# A line that starts like this is a note, a legend or a footer, never a record.
NOTE_PREFIXES: tuple[str, ...] = (
    "nota",
    "note",
    "n b",
    "nb",
    "legenda",
    "fonte",
    "source",
    "generato",
    "stampato",
    "pagina",
    "page",
    "firma",
    "documento generato",
    "attenzione",
)

# Words of a SECTION line (a department, a team, a channel group) written alone on a row.
SECTION_WORDS: frozenset[str] = stems(
    """
    reception housekeeping piani cucina ristorante sala bar manutenzione spa wellness direzione
    amministrazione ricevimento lavanderia colazioni colazione front office kitchen maintenance
    management food beverage reparto area settore team
    """
)

# Sheet names that say "this is not the data".
SUMMARY_SHEET_WORDS: tuple[str, ...] = (
    "riepilogo",
    "riassunto",
    "sintesi",
    "summary",
    "totali",
    "dashboard",
    "grafico",
    "grafici",
    "chart",
    "note",
    "istruzioni",
    "legenda",
    "info",
    "indice",
    "copertina",
    "cover",
)

WEEKDAYS: dict[str, int] = {
    "lun": 0,
    "lunedi": 0,
    "mon": 0,
    "monday": 0,
    "mar": 1,
    "martedi": 1,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "mer": 2,
    "mercoledi": 2,
    "wed": 2,
    "wednesday": 2,
    "gio": 3,
    "giovedi": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "ven": 4,
    "venerdi": 4,
    "fri": 4,
    "friday": 4,
    "sab": 5,
    "sabato": 5,
    "sat": 5,
    "saturday": 5,
    "dom": 6,
    "domenica": 6,
    "sun": 6,
    "sunday": 6,
}

MONTHS: dict[str, int] = {
    "gennaio": 1,
    "gen": 1,
    "january": 1,
    "jan": 1,
    "febbraio": 2,
    "feb": 2,
    "february": 2,
    "marzo": 3,
    "mar": 3,
    "march": 3,
    "aprile": 4,
    "apr": 4,
    "april": 4,
    "maggio": 5,
    "mag": 5,
    "may": 5,
    "giugno": 6,
    "giu": 6,
    "june": 6,
    "jun": 6,
    "luglio": 7,
    "lug": 7,
    "july": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "august": 8,
    "aug": 8,
    "settembre": 9,
    "set": 9,
    "sett": 9,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "ottobre": 10,
    "ott": 10,
    "october": 10,
    "oct": 10,
    "novembre": 11,
    "nov": 11,
    "november": 11,
    "dicembre": 12,
    "dic": 12,
    "december": 12,
    "dec": 12,
}

__all__ = [
    "HEADER_STEMS",
    "MONTHS",
    "NOTE_PREFIXES",
    "SECTION_WORDS",
    "SUMMARY_SHEET_WORDS",
    "TOTAL_WORDS",
    "WEEKDAYS",
]

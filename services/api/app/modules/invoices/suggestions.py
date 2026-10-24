"""Deterministic invoice column suggestions for structured files (no AI, no learning).

The names a hotel's accountant gives the columns of a cost register, Italian and English. The
ranking is the shared one (`app.modules.ingestion.suggestions`). What is specific to invoices, and
deliberate:

* the amount NINFA works with is the NET one (before VAT): only names that SAY it ("Imponibile",
  "Netto") are suggested for the line total. A bare "Importo" is left to the person, because
  guessing would silently put VAT into a cost analysis;
* the totals WITH VAT ("Totale documento", "Lordo") are the document's gross amount, never a line.
"""

from collections.abc import Mapping

from app.modules.invoices.mapping import InvoiceField

F = InvoiceField

FIELD_ORDER: tuple[InvoiceField, ...] = tuple(InvoiceField)

FIELD_ALIASES: Mapping[InvoiceField, tuple[str, ...]] = {
    F.SUPPLIER_NAME: (
        "supplier",
        "supplier name",
        "vendor",
        "vendor name",
        "fornitore",
        "nome fornitore",
        "ragione sociale",
        "ragione sociale fornitore",
        "denominazione",
        "denominazione fornitore",
        "emittente",
        "cedente",
        "cedente prestatore",
    ),
    F.SUPPLIER_VAT_NUMBER: (
        "vat number",
        "vat",
        "vat id",
        "partita iva",
        "p iva",
        "p.iva",
        "piva",
        "partita iva fornitore",
        "p iva fornitore",
    ),
    F.SUPPLIER_TAX_CODE: (
        "tax code",
        "codice fiscale",
        "codice fiscale fornitore",
        "cod fiscale",
        "c.f.",
        "cf fornitore",
    ),
    F.SUPPLIER_IBAN: ("iban", "iban fornitore", "supplier iban"),
    F.INVOICE_NUMBER: (
        "invoice number",
        "invoice no",
        "invoice",
        "numero fattura",
        "n fattura",
        "n. fattura",
        "numero documento",
        "n documento",
        "n. documento",
        "nr documento",
        "numero doc",
        "n doc",
        "fattura n",
        "fattura numero",
        "documento",
        "protocollo",
    ),
    F.INVOICE_DATE: (
        "invoice date",
        "date",
        "data",
        "data fattura",
        "data documento",
        "data emissione",
        "data doc",
        "data registrazione",
        "emessa il",
    ),
    F.DUE_DATE: (
        "due date",
        "payment due date",
        "scadenza",
        "data scadenza",
        "scadenza pagamento",
        "data pagamento",
    ),
    F.DOCUMENT_TYPE: (
        "document type",
        "tipo documento",
        "tipo doc",
        "tipo fattura",
        "tipologia documento",
        "td",
    ),
    F.CURRENCY: ("currency", "valuta", "divisa", "moneta"),
    # The NET amount of the whole document. ("Imponibile" / "Totale imponibile" on a register that
    # has one row per invoice is the line total below: that row IS the whole document.)
    F.INVOICE_NET_AMOUNT: ("document net total", "imponibile documento", "netto documento"),
    F.INVOICE_TAX_AMOUNT: (
        "vat amount",
        "tax amount",
        "iva",
        "importo iva",
        "totale iva",
        "imposta",
        "importo imposta",
    ),
    F.INVOICE_GROSS_AMOUNT: (
        "gross total",
        "gross amount",
        "total with vat",
        "totale documento",
        "totale fattura",
        "totale lordo",
        "lordo",
        "importo lordo",
        "totale iva inclusa",
        "totale con iva",
    ),
    F.LINE_NUMBER: ("line number", "line", "numero riga", "n riga", "riga", "progressivo riga"),
    F.LINE_DESCRIPTION: (
        "description",
        "line description",
        "descrizione",
        "descrizione riga",
        "descrizione voce",
        "oggetto",
        "causale",
        "dettaglio",
        "voce",
        "articolo",
        "prodotto",
        "servizio",
    ),
    F.QUANTITY: ("quantity", "qty", "quantita", "qta", "q.ta"),
    F.UNIT: ("unit", "uom", "unita di misura", "u.m.", "um"),
    F.UNIT_PRICE: ("unit price", "price", "prezzo unitario", "prezzo", "importo unitario"),
    F.LINE_TOTAL: (
        "line total",
        "net",
        "net amount",
        "imponibile",
        "importo imponibile",
        "netto",
        "importo netto",
        "totale imponibile",
        "imponibile totale",
        "totale netto",
        "totale netto riga",
        "totale riga",
        "importo riga",
        "totale imponibile riga",
        "prezzo totale",
    ),
    F.VAT_RATE: ("vat rate", "tax rate", "aliquota", "aliquota iva", "iva %", "% iva"),
    F.COST_CATEGORY: (
        "cost category",
        "category",
        "categoria",
        "categoria costo",
        "categoria di costo",
        "tipo costo",
        "tipologia costo",
        "voce di costo",
        "centro di costo",
        "conto",
    ),
}


__all__ = ["FIELD_ALIASES", "FIELD_ORDER"]

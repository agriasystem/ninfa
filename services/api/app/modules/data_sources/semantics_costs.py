"""What the columns of a cost register mean, read by words and checked against their values.

A hotel's accountant exports "Numero fattura", "Data", "Fornitore", "Descrizione", "Imponibile",
"IVA", "Totale", often with a category. NINFA reads them into the SAME invoice model the FatturaPA
import fills (supplier, document, line, category): there is no second cost model.

The one thing a cost register must never be guessed about is the AMOUNT: NINFA's analysis works
with the net amount (before VAT). "Imponibile" and "Netto" say it; "Importo" and "Totale" do not,
and are asked about (`understanding_costs`).
"""

import re

from app.modules.data_sources.semantics import (
    DomainSem,
    FieldSem,
    fit_date,
    fit_identifier,
    fit_label,
    fit_money,
    fit_percentage,
    fit_text,
    fit_vocabulary,
    rule,
)
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import stems
from app.modules.ingestion.models import DataSourceDomain
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.mapping import InvoiceField
from app.modules.invoices.suggestions import FIELD_ALIASES

F = InvoiceField

# Words that say the amount is NET (before VAT) / GROSS (with VAT).
NET_WORDS = stems("imponibile netto net")
GROSS_WORDS = stems("lordo gross inclusa compresa")
_NOT_A_NUMBER_OF_THE_DOCUMENT = "iva imposta vat tax lordo gross inclusa compresa aliquota"
_VAT_NUMBER = re.compile(r"^[A-Za-z]{0,2}\s?\d{8,12}$")
_CATEGORY_NAMES = frozenset(category.value for category in CostCategory)


def _exact(field: InvoiceField) -> tuple[str, ...]:
    return (*FIELD_ALIASES.get(field, ()), field.value)


def _fit_vat_number(stats: ColumnStats) -> float:
    """Eleven digits, with or without the country letters: an Italian VAT number."""
    values = stats.strings or stats.texts
    if not values:
        return 0.0
    return sum(1 for text in values if _VAT_NUMBER.match(text.strip())) / len(values)


def _is_category_name(text: str) -> bool:
    return text.strip().upper() in _CATEGORY_NAMES


def _fit_tax_amount(stats: ColumnStats) -> float:
    """VAT amounts are money, not small percentages: a column of 22, 22, 10 is a RATE."""
    if not stats.n or stats.maximum is None:
        return 0.0
    base = fit_money(stats)
    only_rates = stats.integral == stats.numeric and stats.maximum <= 30
    return 0.3 * base if only_rates else base


COSTS = DomainSem(
    domain=DataSourceDomain.COSTS,
    fields={
        F.SUPPLIER_NAME.value: FieldSem(
            F.SUPPLIER_NAME.value,
            _exact(F.SUPPLIER_NAME),
            (
                rule("fornitore supplier vendor emittente cedente", weight=0.93),
                rule("ragione denominazione", "sociale fornitore societa", weight=0.9),
            ),
            fit_text,
        ),
        F.SUPPLIER_VAT_NUMBER.value: FieldSem(
            F.SUPPLIER_VAT_NUMBER.value,
            _exact(F.SUPPLIER_VAT_NUMBER),
            (
                rule("partita piva vat", "iva fornitore numero id", weight=0.9),
                rule("piva", weight=0.93),
                rule("vat", "number id", weight=0.9),
            ),
            _fit_vat_number,
        ),
        F.SUPPLIER_TAX_CODE.value: FieldSem(
            F.SUPPLIER_TAX_CODE.value,
            _exact(F.SUPPLIER_TAX_CODE),
            (rule("codice cod", "fiscale", weight=0.9),),
            fit_identifier,
        ),
        F.INVOICE_NUMBER.value: FieldSem(
            F.INVOICE_NUMBER.value,
            _exact(F.INVOICE_NUMBER),
            (
                rule("fattura invoice documento doc", "numero n num nr no id", weight=0.93),
                rule("numero n num nr", "fattura invoice documento doc", weight=0.93),
                rule("protocollo", weight=0.8),
            ),
            fit_identifier,
        ),
        F.INVOICE_DATE.value: FieldSem(
            F.INVOICE_DATE.value,
            _exact(F.INVOICE_DATE),
            (
                rule(
                    "data date",
                    "fattura invoice documento doc emissione registrazione",
                    none="scadenza due pagamento",
                    weight=0.93,
                ),
                rule("data date", none="scadenza due pagamento", weight=0.75),
            ),
            fit_date,
            value_only=True,
        ),
        F.DUE_DATE.value: FieldSem(
            F.DUE_DATE.value,
            _exact(F.DUE_DATE),
            (rule("scadenza due", weight=0.93),),
            fit_date,
        ),
        F.DOCUMENT_TYPE.value: FieldSem(
            F.DOCUMENT_TYPE.value,
            _exact(F.DOCUMENT_TYPE),
            (rule("tipo tipologia", "documento doc fattura", weight=0.93),),
            fit_label,
        ),
        F.CURRENCY.value: FieldSem(
            F.CURRENCY.value,
            _exact(F.CURRENCY),
            (rule("valuta currency divisa moneta", weight=0.9),),
            fit_label,
        ),
        F.INVOICE_NET_AMOUNT.value: FieldSem(
            F.INVOICE_NET_AMOUNT.value,
            _exact(F.INVOICE_NET_AMOUNT),
            (rule("imponibile netto net", "documento fattura invoice", weight=0.9),),
            fit_money,
        ),
        F.INVOICE_TAX_AMOUNT.value: FieldSem(
            F.INVOICE_TAX_AMOUNT.value,
            _exact(F.INVOICE_TAX_AMOUNT),
            (
                rule(
                    "iva vat imposta tax",
                    none="aliquota rate percentuale perc",
                    weight=0.92,
                ),
            ),
            _fit_tax_amount,
        ),
        F.INVOICE_GROSS_AMOUNT.value: FieldSem(
            F.INVOICE_GROSS_AMOUNT.value,
            _exact(F.INVOICE_GROSS_AMOUNT),
            (
                rule("lordo gross", weight=0.93),
                rule(
                    "totale total",
                    "documento fattura invoice",
                    none="imponibile netto net",
                    weight=0.88,
                ),
                rule("iva vat", "inclusa compresa included", weight=0.93),
                # "Totale" alone: very likely the total WITH VAT, but only likely.
                rule("totale total", weight=0.72, none="imponibile netto net riga iva"),
            ),
            fit_money,
        ),
        F.LINE_DESCRIPTION.value: FieldSem(
            F.LINE_DESCRIPTION.value,
            _exact(F.LINE_DESCRIPTION),
            (
                rule("descrizione description oggetto causale dettaglio", weight=0.93),
                rule("voce articolo prodotto servizio", none="costo spesa", weight=0.8),
            ),
            fit_text,
        ),
        F.QUANTITY.value: FieldSem(
            F.QUANTITY.value,
            _exact(F.QUANTITY),
            (rule("quantita quantity qty qta", weight=0.93),),
            fit_money,
        ),
        F.UNIT_PRICE.value: FieldSem(
            F.UNIT_PRICE.value,
            _exact(F.UNIT_PRICE),
            (rule("prezzo price", "unitario unit", weight=0.93),),
            fit_money,
        ),
        F.LINE_TOTAL.value: FieldSem(
            F.LINE_TOTAL.value,
            _exact(F.LINE_TOTAL),
            (
                # Says it is NET: sure.
                rule(
                    "imponibile netto net",
                    none=f"documento fattura invoice {_NOT_A_NUMBER_OF_THE_DOCUMENT}",
                    weight=0.93,
                ),
                # An amount that does not say whether VAT is in it: proposed, then ASKED about.
                rule(
                    "importo amount costo spesa valore prezzo totale",
                    none=_NOT_A_NUMBER_OF_THE_DOCUMENT + " unitario unit quantita",
                    weight=0.7,
                ),
            ),
            fit_money,
        ),
        F.VAT_RATE.value: FieldSem(
            F.VAT_RATE.value,
            _exact(F.VAT_RATE),
            (rule("aliquota rate", "iva vat", weight=0.93), rule("aliquota", weight=0.88)),
            fit_percentage,
        ),
        F.COST_CATEGORY.value: FieldSem(
            F.COST_CATEGORY.value,
            _exact(F.COST_CATEGORY),
            (
                rule("categoria category", none="documento fiscale", weight=0.93),
                rule("tipo tipologia", "costo spesa", weight=0.9),
                rule("centro conto voce", "costo spesa", weight=0.85),
            ),
            fit_vocabulary(_is_category_name),
        ),
    },
    order=tuple(field.value for field in InvoiceField),
    title_words=stems(
        "fatture fattura acquisti costi spese fornitori registro contabilita passive scadenzario "
        "invoice invoices purchases expenses"
    ),
    # A supplier is a business: its name, VAT number and IBAN are what an invoice IS. Nothing is
    # locked here (NINFA keeps suppliers); a column that is not mapped is dropped at import anyway.
    locked={},
)

__all__ = ["COSTS", "GROSS_WORDS", "NET_WORDS"]

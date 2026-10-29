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
from app.modules.document_understanding.pii import PiiKind, looks_like_names
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import stems
from app.modules.ingestion.models import DataSourceDomain
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.mapping import InvoiceField
from app.modules.invoices.suggestions import FIELD_ALIASES

F = InvoiceField

# Words that say the amount is NET (before VAT) / GROSS (with VAT).
# ("Amount excl. VAT", "Importo IVA esclusa": the amount says it leaves the VAT out)
NET_WORDS = stems("imponibile netto net excl excluding esclusa escluso senza before")
GROSS_WORDS = stems("lordo gross inclusa compresa incl including with")
_NOT_A_NUMBER_OF_THE_DOCUMENT = "iva imposta vat tax lordo gross inclusa compresa aliquota"
# A payslip is not a purchase: "Netto in busta" is what an employee takes home.
_PAYROLL = stems("busta cedolino stipendio stipendi payroll salary retribuzione")
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


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _fit_document_number(stats: ColumnStats) -> float:
    """A document number: not a row counter (1, 2, 3...) and, unlike a booking code, allowed to
    come back: the lines of one invoice all carry its number. What a number is: short, with
    digits in it, several different ones."""
    base = fit_identifier(stats)
    if stats.n and stats.distinct >= 3 and stats.text_fraction + stats.numeric / stats.n >= 0.95:
        shown = stats.strings or stats.texts
        short = stats.avg_len <= 25 or not stats.texts
        numbered = not shown or sum(1 for text in shown if _has_digit(text)) / len(shown) >= 0.8
        if short and numbered and stats.date_fraction == 0:
            base = max(base, 0.9)
    if (
        stats.n
        and stats.numeric == stats.n
        and stats.integral == stats.n
        and stats.minimum is not None
        and stats.maximum is not None
        and stats.minimum <= 1
        and stats.maximum <= stats.n + 1
    ):
        return 0.1  # the values contradict the name: it is not a document number
    return base


def _fit_amount(stats: ColumnStats) -> float:
    """An amount of a register: a credit note is NEGATIVE (the amount it takes back)."""
    return fit_money(stats, allow_negative=True)


def _fit_supplier(stats: ColumnStats) -> float:
    """A supplier is a business or a professional; a column of people's names is more likely
    the holder of an account or an employee - to be checked, never certain."""
    base = fit_text(stats)
    return 0.6 * base if looks_like_names(stats) else base


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
                rule(
                    "fornitore supplier vendor emittente cedente ditta creditore creditor payee "
                    "venditore seller prestatore issuer",
                    weight=0.93,
                ),
                rule("billed invoiced", weight=0.88),  # "Billed By"
                rule("ragione denominazione", "sociale fornitore societa", weight=0.9),
                rule("intestatario titolare", weight=0.8),
                rule("chi", weight=0.85),  # "Da chi": a hand-made sheet
            ),
            _fit_supplier,
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
                rule(
                    "fattura invoice documento doc fatt inv bill",
                    "numero n num nr no id ref rif riferimento reference",
                    weight=0.93,
                ),
                rule(
                    "numero n num nr ref rif riferimento reference",
                    "fattura invoice documento doc fatt inv bill",
                    weight=0.93,
                ),
                rule("protocollo", weight=0.8),
                # "Numero", "Num.", "N.", "Doc." alone, in a register of invoices
                rule("numero", none="riga linea line prot protocollo", weight=0.8),
                rule("doc documento", none="tipo tipologia data date", weight=0.8),
            ),
            _fit_document_number,
        ),
        F.INVOICE_DATE.value: FieldSem(
            F.INVOICE_DATE.value,
            # ("Fattura del", "Invoice dated": the preposition is the word "date", and a
            # preposition is not a word of a header)
            (*_exact(F.INVOICE_DATE), "fattura del", "documento del", "invoice dated"),
            (
                rule(
                    "data date dt",
                    "fattura invoice documento doc emissione registrazione fatt inv bill issue "
                    "issued",
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
            (
                rule("scadenza due", weight=0.93),
                rule("pagabile payable pay", "entro by", weight=0.9),
            ),
            fit_date,
        ),
        F.DOCUMENT_TYPE.value: FieldSem(
            F.DOCUMENT_TYPE.value,
            _exact(F.DOCUMENT_TYPE),
            (rule("tipo tipologia causale", "documento doc fattura", weight=0.93),),
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
            _fit_amount,
            veto=_PAYROLL,
        ),
        F.INVOICE_TAX_AMOUNT.value: FieldSem(
            F.INVOICE_TAX_AMOUNT.value,
            _exact(F.INVOICE_TAX_AMOUNT),
            (
                rule(
                    "iva vat imposta tax",
                    none="aliquota rate percentuale perc excl excluding esclusa escluso",
                    weight=0.92,
                ),
            ),
            _fit_tax_amount,
            veto=_PAYROLL,
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
                rule(
                    "iva vat tax", "inclusa compresa included incl including with con", weight=0.93
                ),
                # "Totale" alone: very likely the total WITH VAT, but only likely.
                rule("totale total", weight=0.72, none="imponibile netto net riga iva"),
            ),
            _fit_amount,
            veto=_PAYROLL,
        ),
        F.LINE_DESCRIPTION.value: FieldSem(
            F.LINE_DESCRIPTION.value,
            _exact(F.LINE_DESCRIPTION),
            (
                rule(
                    "descrizione description oggetto causale dettaglio dettagli details detail "
                    "prestazione memo narrative",
                    weight=0.93,
                ),
                rule("text testo", "fattura invoice line riga", weight=0.88),
                rule(
                    "voce articolo prodotto servizio item merce goods services service",
                    none="costo spesa",
                    weight=0.8,
                ),
                rule("cosa", weight=0.85),  # a hand-made sheet
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
                # "Amount excl. VAT": says it is net, in words that also name the VAT.
                rule(
                    "excl excluding esclusa escluso before senza ex",
                    "vat iva tax",
                    none="incl including inclusa compresa lordo gross with con",
                    weight=0.93,
                ),
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
            _fit_amount,
            veto=_PAYROLL,
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
                rule(
                    "tipo tipologia classe type class natura nature",
                    "costo spesa cost expense",
                    weight=0.9,
                ),
                rule("conto voce", "costo spesa", weight=0.85),
            ),
            fit_vocabulary(_is_category_name),
            # Where a cost is booked is not what it was spent on.
            veto=stems("centro cdc"),
        ),
    },
    order=tuple(field.value for field in InvoiceField),
    title_words=stems(
        "fatture fattura acquisti costi spese fornitori registro contabilita passive scadenzario "
        "invoice invoices purchases expenses"
    ),
    # A supplier is a business: its name, VAT number and IBAN are what an invoice IS. Nothing is
    # locked here (NINFA keeps suppliers); a column that is not mapped is dropped at import anyway.
    locked={PiiKind.TAX_CODE: "IDENTITY", PiiKind.IBAN: "IDENTITY"},
    # Every amount of a register: which one is the net, the tax, the total is never guessed.
    financial=frozenset(
        {
            F.INVOICE_NET_AMOUNT.value,
            F.INVOICE_TAX_AMOUNT.value,
            F.INVOICE_GROSS_AMOUNT.value,
            F.LINE_TOTAL.value,
            F.UNIT_PRICE.value,
            F.VAT_RATE.value,
        }
    ),
)

__all__ = ["COSTS", "GROSS_WORDS", "NET_WORDS"]

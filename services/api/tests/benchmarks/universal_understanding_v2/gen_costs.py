"""Unseen cost-register documents: what an accountant or a purchase ledger exports.

120 documents (30 EASY, 40 MEDIUM, 30 HARD, 20 ADVERSARIAL). A cost register lists the invoices a
hotel received: a supplier, a document number, a document date, a description and the amounts (net /
VAT / gross), sometimes a VAT rate, a category, a due date, a currency. Headers are drawn from what
Passepartout / TeamSystem / Zucchetti-style ledgers, SAP-like exports and hand-made purchase sheets
really write, in Italian and English, abbreviated, with units and punctuation; the shape of the
document and the way its values are written change from one document to the next.

The money rule NINFA works by is the NET amount (before VAT). A column that SAYS it is the net
("Imponibile", "Tot. Netto €", "Net Amount (EUR)", "Totale IVA esclusa") settles the question,
with or without a VAT and a total column beside it; a bare "Importo" / "Totale" / "Amount" does
not, and a register whose only amount says "IVA inclusa" holds the gross, which is not the net. The
amounts of every document are coherent (net + VAT = gross with a VAT rate of 22 / 10 / 4) except in
the recipe that contradicts itself on purpose.

Every truth is what a careful person would say about the file, written by the recipe next to the
file it draws. Nothing here was decided by looking at what Smart Import answers.
"""

import csv
import io
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col, flat_document, headers, parts, records
from tests.benchmarks.smart_import_v3.draw import (
    Note,
    Section,
    Sheet,
    Styled,
    Subtotal,
    TableRef,
    Total,
    write_table,
    xlsx_bytes,
)
from tests.benchmarks.smart_import_v3.kit import Built, facts
from tests.benchmarks.smart_import_v3.model import Doc, Golden, column
from tests.benchmarks.smart_import_v3.pool import email_of, full_name, person, phone_of, tax_code_of
from tests.benchmarks.universal_understanding_v2.common import (
    H,
    Maker,
    assemble,
    date_cell,
    decimal_of,
    maybe,
    money_cell,
    order_of,
    pick,
    pick_language,
    without_table,
)

# --- the data of a cost register ------------------------------------------------------------------


def words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


MONTHS_IT = words(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre"
)
MONTHS_EN = words(
    "January February March April May June July August September October November December"
)
HOTELS = (
    "Hotel Mirasole",
    "Villa Ortensia",
    "Residence Le Dune",
    "Albergo Casa Rossa",
    "Grand Hotel Marinaro",
    "Hotel Terrazza Blu",
)


@dataclass(frozen=True, slots=True)
class Spec:
    """One kind of cost: what it is called, what an invoice for it says, what it costs.

    `answer` is the NINFA category a person would choose for it; the words are how hotels write it
    (every word of a list means that category without a doubt)."""

    answer: str
    net: tuple[int, int]
    rates: tuple[int, ...]
    it: tuple[str, ...]
    en: tuple[str, ...]
    words_it: tuple[str, ...]
    words_en: tuple[str, ...]


SPECS: dict[str, Spec] = {
    "UTILITIES": Spec(
        "UTILITIES",
        (700, 4200),
        (22, 22, 10),
        (
            "Fornitura energia elettrica {month}",
            "Consumi gas metano {month}",
            "Servizio idrico integrato {month}",
            "Energia elettrica - conguaglio {month}",
            "Teleriscaldamento periodo {month}",
            "Fornitura acqua e fognatura {month}",
        ),
        (
            "Electricity supply {month}",
            "Natural gas usage {month}",
            "Water and sewage {month}",
            "Energy settlement {month}",
            "District heating {month}",
            "Utilities bill {month}",
        ),
        ("Energia elettrica", "Energia", "Luce", "Utenze", "Luce e gas"),
        ("Utilities", "Electricity", "Energy", "Gas & Electric"),
    ),
    "LAUNDRY": Spec(
        "LAUNDRY",
        (400, 1900),
        (22,),
        (
            "Lavaggio e stiratura biancheria {month}",
            "Noleggio biancheria piana {month}",
            "Lavaggio tovagliato e divise {month}",
            "Servizio lavanderia camere {month}",
            "Lavaggio copriletti e piumoni",
        ),
        (
            "Linen washing and pressing {month}",
            "Flat linen rental {month}",
            "Table linen and uniform laundry {month}",
            "Rooms laundry service {month}",
            "Duvet and bedspread cleaning",
        ),
        ("Lavanderia", "Servizio lavanderia", "Biancheria e lavanderia"),
        ("Laundry", "Linen & Laundry", "Laundry Services"),
    ),
    "FOOD": Spec(
        "FOOD",
        (90, 950),
        (10, 10, 4, 22),
        (
            "Fornitura pane e prodotti da forno",
            "Latticini e uova per colazione",
            "Frutta e verdura fresca",
            "Fornitura bevande e acque minerali",
            "Caffè in grani 6 kg",
            "Pasticceria per buffet colazione",
            "Salumi e affettati",
            "Pescato fresco consegna settimanale",
            "Succhi e marmellate monoporzione",
        ),
        (
            "Bread and bakery supply",
            "Dairy and eggs for breakfast",
            "Fresh fruit and vegetables",
            "Beverages and mineral water",
            "Coffee beans 6 kg",
            "Pastries for breakfast buffet",
            "Cold cuts",
            "Fresh fish weekly delivery",
            "Juices and single-serve jams",
        ),
        ("Alimentari", "Colazioni", "Derrate alimentari", "Food", "Bevande e alimenti"),
        ("Food & Beverage", "F&B", "Groceries", "Food Supplies", "Breakfast supplies"),
    ),
    "MAINTENANCE": Spec(
        "MAINTENANCE",
        (120, 2600),
        (22, 22, 10),
        (
            "Intervento caldaia camera {room}",
            "Riparazione condizionatore piano {floor}",
            "Manutenzione ordinaria ascensore {month}",
            "Sostituzione serratura camera {room}",
            "Revisione impianto antincendio",
            "Manutenzione giardino e siepi {month}",
            "Riparazione perdita bagno camera {room}",
            "Tinteggiatura corridoio piano {floor}",
        ),
        (
            "Boiler repair room {room}",
            "Air conditioning repair floor {floor}",
            "Lift routine maintenance {month}",
            "Lock replacement room {room}",
            "Fire safety system inspection",
            "Garden and hedge maintenance {month}",
            "Bathroom leak repair room {room}",
            "Corridor repainting floor {floor}",
        ),
        ("Manutenzione", "Manutenzioni", "Manutenzione ordinaria", "Riparazioni"),
        ("Maintenance", "Repairs", "Repairs & Maintenance"),
    ),
    "CLEANING": Spec(
        "CLEANING",
        (180, 2100),
        (22,),
        (
            "Pulizia camere e parti comuni {month}",
            "Sanificazione ambienti",
            "Fornitura detergenti e sacchi",
            "Pulizia straordinaria piano {floor}",
            "Lavaggio vetrate e facciata",
            "Servizio pulizie fine stagione",
        ),
        (
            "Rooms and common areas cleaning {month}",
            "Premises sanitising",
            "Detergents and bin liners supply",
            "Deep cleaning floor {floor}",
            "Window and facade washing",
            "End of season cleaning service",
        ),
        ("Pulizie", "Pulizia", "Servizio pulizie", "Igiene e pulizia"),
        ("Cleaning", "Cleaning Services", "Cleaning & Hygiene"),
    ),
    "SOFTWARE": Spec(
        "SOFTWARE",
        (45, 700),
        (22,),
        (
            "Canone gestionale alberghiero {month}",
            "Licenza channel manager {month}",
            "Assistenza tecnica software PMS",
            "Rinnovo dominio e hosting sito",
            "Backup cloud mensile {month}",
            "Abbonamento booking engine",
        ),
        (
            "Hotel management software fee {month}",
            "Channel manager licence {month}",
            "PMS technical support",
            "Domain and website hosting renewal",
            "Monthly cloud backup {month}",
            "Booking engine subscription",
        ),
        ("Software", "Licenze software", "Gestionale", "Canoni software"),
        ("Software", "Software Licences", "IT Software"),
    ),
    "MARKETING": Spec(
        "MARKETING",
        (150, 1800),
        (22,),
        (
            "Campagna social {month}",
            "Realizzazione brochure stagionale",
            "Servizio fotografico struttura",
            "Stampa locandine eventi",
            "Gestione campagne web {month}",
            "Inserzione guida turistica",
        ),
        (
            "Social media campaign {month}",
            "Seasonal brochure design",
            "Property photo shoot",
            "Event flyer printing",
            "Web campaign management {month}",
            "Travel guide advertisement",
        ),
        ("Marketing", "Pubblicità", "Promozione", "Comunicazione e marketing"),
        ("Marketing", "Advertising", "Promotion"),
    ),
    "PROFESSIONAL_SERVICES": Spec(
        "PROFESSIONAL_SERVICES",
        (200, 2200),
        (22,),
        (
            "Consulenza fiscale {month}",
            "Elaborazione paghe e cedolini {month}",
            "Assistenza legale contratto fornitura",
            "Piano di autocontrollo HACCP",
            "Revisione contabile semestrale",
            "Consulenza sicurezza sul lavoro",
        ),
        (
            "Tax advisory {month}",
            "Payroll processing {month}",
            "Legal assistance supply contract",
            "HACCP self-control plan",
            "Half-year accounts review",
            "Occupational safety consulting",
        ),
        ("Consulenze", "Consulenza professionale", "Servizi professionali"),
        ("Consulting", "Professional Fees", "Professional Services"),
    ),
    "OTHER": Spec(
        "OTHER",
        (25, 420),
        (22,),
        (
            "Materiale di cancelleria",
            "Ferramenta varia",
            "Spedizione corriere",
            "Stampati e modulistica",
            "Piccole attrezzature reception",
            "Materiale di consumo bagni",
        ),
        (
            "Stationery supplies",
            "Assorted hardware",
            "Courier shipping",
            "Forms and printed matter",
            "Small reception equipment",
            "Bathroom consumables",
        ),
        ("Altro", "Varie", "Spese varie", "Altre spese"),
        ("Other", "Misc", "Miscellaneous", "Sundry"),
    ),
    # kinds of cost whose word no hotel vocabulary decides alone (a person says what they mean)
    "TELECOM": Spec(
        "UTILITIES",
        (60, 420),
        (22,),
        (
            "Canone linee telefoniche {month}",
            "Traffico telefonico e internet {month}",
            "Canone connettività fibra {month}",
        ),
        (
            "Phone lines rental {month}",
            "Voice and data traffic {month}",
            "Fibre connectivity fee {month}",
        ),
        ("Telefonia",),
        ("Telephony",),
    ),
    "TRAINING": Spec(
        "PROFESSIONAL_SERVICES",
        (150, 900),
        (22,),
        (
            "Corso sicurezza sul lavoro",
            "Formazione addetti antincendio",
            "Corso HACCP personale sala",
        ),
        (
            "Occupational safety course",
            "Fire safety staff training",
            "HACCP course for dining staff",
        ),
        ("Formazione",),
        ("Training",),
    ),
    "TRANSPORT": Spec(
        "OTHER",
        (80, 900),
        (22,),
        (
            "Trasporto merci conto terzi",
            "Servizio navetta ospiti {month}",
            "Spedizione pallet biancheria",
        ),
        ("Freight haulage", "Guest shuttle service {month}", "Linen pallet shipment"),
        ("Trasporti",),
        ("Transport",),
    ),
    "GIFTS": Spec(
        "OTHER",
        (60, 500),
        (22,),
        ("Cesti omaggio benvenuto", "Omaggi per clienti fedeli", "Confezioni regalo ospiti"),
        ("Welcome gift baskets", "Gifts for loyal guests", "Guest gift packs"),
        ("Omaggi ospiti",),
        ("Guest gifts",),
    ),
    "UNIFORMS": Spec(
        "OTHER",
        (100, 800),
        (22,),
        ("Fornitura divise sala", "Divise reception e piani", "Grembiuli cucina"),
        ("Dining room uniforms", "Reception and housekeeping uniforms", "Kitchen aprons"),
        ("Divise personale",),
        ("Staff uniforms",),
    ),
    "SUBSCRIPTIONS": Spec(
        "OTHER",
        (30, 350),
        (22,),
        (
            "Abbonamento quotidiani e riviste",
            "Abbonamento TV satellitare camere",
            "Canone musica d'ambiente",
        ),
        (
            "Newspaper and magazine subscription",
            "Room satellite TV subscription",
            "Background music licence",
        ),
        ("Abbonamenti",),
        ("Subscriptions",),
    ),
}
KNOWN = (
    "UTILITIES",
    "LAUNDRY",
    "FOOD",
    "MAINTENANCE",
    "CLEANING",
    "SOFTWARE",
    "MARKETING",
    "PROFESSIONAL_SERVICES",
    "OTHER",
)
UNKNOWN = ("TELECOM", "TRAINING", "TRANSPORT", "GIFTS", "UNIFORMS", "SUBSCRIPTIONS")

_VENDOR_ROWS: tuple[tuple[str, str], ...] = (
    ("Energia Verde Adriatica S.p.A.", "UTILITIES"),
    ("Gas e Luce Valmarecchia S.r.l.", "UTILITIES"),
    ("Aquaviva Servizi Idrici S.p.A.", "UTILITIES"),
    ("Termogas Riviera S.r.l.", "UTILITIES"),
    ("Greenfield Energy Ltd", "UTILITIES"),
    ("Lavanderia Industriale Azzurra S.r.l.", "LAUNDRY"),
    ("Candida Lavasecco di Neri & C.", "LAUNDRY"),
    ("Biancheria Service Tirrena S.r.l.", "LAUNDRY"),
    ("Linea Pulita Noleggio Tessile S.p.A.", "LAUNDRY"),
    ("Nordic Linen Supply GmbH", "LAUNDRY"),
    ("Panificio Forno Antico di Gatti", "FOOD"),
    ("Caseificio Colline Verdi Soc. Agr.", "FOOD"),
    ("Ortofrutta Mercato Nuovo S.r.l.", "FOOD"),
    ("Bevande Alto Adriatico S.r.l.", "FOOD"),
    ("Salumificio Fratelli Orsini S.n.c.", "FOOD"),
    ("Torrefazione Moka d'Oro S.r.l.", "FOOD"),
    ("Pasticceria Dolce Riva S.a.s.", "FOOD"),
    ("Ittica Porto Blu S.r.l.", "FOOD"),
    ("Harbour Coffee Roasters Ltd", "FOOD"),
    ("Idrotermica Bassini S.r.l.", "MAINTENANCE"),
    ("Elettroimpianti Fontana & Figli", "MAINTENANCE"),
    ("Ascensori Ligure Service S.r.l.", "MAINTENANCE"),
    ("Fabbro Edile Zanardi S.n.c.", "MAINTENANCE"),
    ("Giardini d'Autore S.r.l.", "MAINTENANCE"),
    ("Anchor Repairs & Services Ltd", "MAINTENANCE"),
    ("Pulimar Servizi di Pulizia Soc. Coop.", "CLEANING"),
    ("Brillante Igiene Professionale S.r.l.", "CLEANING"),
    ("Detergenti Albaluce S.r.l.", "CLEANING"),
    ("Sanificazione Riviera S.r.l.", "CLEANING"),
    ("Clearwater Facility Services Ltd", "CLEANING"),
    ("Hospitality Cloud Systems S.r.l.", "SOFTWARE"),
    ("Gestionale Alberghi Zeta S.r.l.", "SOFTWARE"),
    ("ChannelBridge Software Ltd", "SOFTWARE"),
    ("Reti e Dati Costa S.r.l.", "SOFTWARE"),
    ("BlueWave Cloud Ltd", "SOFTWARE"),
    ("Agenzia Orizzonte Comunicazione S.r.l.", "MARKETING"),
    ("Studio Grafico Pixel & Carta", "MARKETING"),
    ("Visibilità Web Turistica S.r.l.", "MARKETING"),
    ("Stampa Rapida Digitale S.n.c.", "MARKETING"),
    ("Summit Media Partners LLC", "MARKETING"),
    ("Studio Associato Mancini e Bruni", "PROFESSIONAL_SERVICES"),
    ("Studio Legale Tessari", "PROFESSIONAL_SERVICES"),
    ("Consulenza HACCP Sicura S.r.l.", "PROFESSIONAL_SERVICES"),
    ("Revisori Contabili Adriatica S.r.l.", "PROFESSIONAL_SERVICES"),
    ("Meridian Advisory Partners LLP", "PROFESSIONAL_SERVICES"),
    ("Cartoleria Il Foglio S.n.c.", "OTHER"),
    ("Ferramenta Centrale di Pini", "OTHER"),
    ("Corriere Espresso Adriatico S.r.l.", "OTHER"),
    ("Tipografia Colorgraf S.r.l.", "OTHER"),
    ("Paperline Office Supplies Ltd", "OTHER"),
    ("Fibra Costa Telecom S.r.l.", "TELECOM"),
    ("VoiceLink Telefonia S.p.A.", "TELECOM"),
    ("Accademia Ospitalità Formazione S.r.l.", "TRAINING"),
    ("Sicurezza Lavoro Consulting S.r.l.", "TRAINING"),
    ("Autotrasporti Rapid Bell S.r.l.", "TRANSPORT"),
    ("Navetta Riviera Transfer S.r.l.", "TRANSPORT"),
    ("Cestini e Bontà Regalo S.n.c.", "GIFTS"),
    ("Divise Alta Sartoria Sala S.r.l.", "UNIFORMS"),
    ("Edicola Abbonamenti Italia S.r.l.", "SUBSCRIPTIONS"),
    ("Musica Ambiente Licenze S.r.l.", "SUBSCRIPTIONS"),
)


@dataclass(frozen=True, slots=True)
class Vendor:
    ident: int
    name: str
    category: str

    @property
    def tax_digits(self) -> str:
        """An invented 11-digit company number (distinct for every vendor)."""
        return f"{(self.ident * 7_654_321_093 + 31_415_926_535) % 10**11:011d}"

    @property
    def vat_number(self) -> str:
        return f"IT{self.tax_digits}"


VENDORS = tuple(Vendor(i, name, kind) for i, (name, kind) in enumerate(_VENDOR_ROWS))
VENDORS_BY_KEY: dict[str, tuple[Vendor, ...]] = {
    key: tuple(v for v in VENDORS if v.category == key) for key in SPECS
}


@dataclass(frozen=True, slots=True)
class Bill:
    """One line of a purchase register."""

    seq: int
    vendor: Vendor
    category: str
    number: Any
    day: date  # the date of the document
    booked: date  # the date it was registered
    due: date
    paid: date | None
    description: str
    net: float
    rate: int
    vat: float
    gross: float
    person: int  # who asked for it (personal data of the columns that show it)
    kind: str = "FT"


def month_end(day: date) -> date:
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def describe(rng: random.Random, spec: Spec, lang: str, day: date) -> str:
    template = rng.choice(spec.it if lang == "it" else spec.en)
    months = MONTHS_IT if lang == "it" else MONTHS_EN
    return template.format(
        month=months[day.month - 1], room=rng.randint(101, 420), floor=rng.randint(1, 4)
    )


SERIES_STYLES = ("slash_year", "year_dash", "alpha_dash", "plain", "slash_e", "fa_year", "padded")


def format_number(style: str, n: int) -> Any:
    """A document number the way a supplier's or an office's series writes it."""
    if style == "slash_year":
        return f"FT/2026/{n:04d}"
    if style == "year_dash":
        return f"2026-{n:06d}"
    if style == "alpha_dash":
        return f"A-{n + 8000}"
    if style == "plain":
        return n + 1000
    if style == "slash_e":
        return f"{n}/E"
    if style == "fa_year":
        return f"FA 26/{n:04d}"
    return f"{n:07d}"


class NumberSeries:
    """The document numbers of a register: one series for all, or one per supplier."""

    def __init__(self, rng: random.Random, style: str | None = None) -> None:
        self.rng = rng
        self.style = style or rng.choice((*SERIES_STYLES, "per_vendor"))
        self.counter = rng.randint(1, 600)
        self.per_vendor: dict[int, int] = {}
        self.credits = 0

    def next(self, vendor: Vendor) -> Any:
        if self.style == "per_vendor":
            style = SERIES_STYLES[vendor.ident % len(SERIES_STYLES)]
            n = self.per_vendor.get(vendor.ident, 5 + vendor.ident * 13 % 400)
            n += self.rng.randint(1, 3)
            self.per_vendor[vendor.ident] = n
            return format_number(style, n)
        self.counter += self.rng.randint(1, 4)
        return format_number(self.style, self.counter)

    def credit(self) -> str:
        self.credits += 1
        return f"NC/2026/{self.credits:03d}"


def bills(
    rng: random.Random,
    count: int,
    *,
    lang: str = "it",
    series: NumberSeries | None = None,
    year: int = 2026,
    month: int | None = None,
    categories: Sequence[str] = KNOWN,
    credits: int = 0,
) -> list[Bill]:
    """`count` invoices of one month, in the order of their dates; the last one is always dated
    after the 12th (so a day-first text date can always prove its order)."""
    series = series or NumberSeries(rng)
    first = date(year, month or rng.randint(1, 10), rng.randint(1, 5))
    offsets = sorted(rng.randint(0, 22) for _ in range(count))
    offsets[-1] = 23
    credit_at = set(rng.sample(range(1, count), credits)) if credits else set()
    out: list[Bill] = []
    for index, offset in enumerate(offsets):
        key = rng.choice(list(categories))
        spec = SPECS[key]
        vendor = rng.choice(VENDORS_BY_KEY[key])
        day = first + timedelta(days=offset)
        net = round(rng.uniform(*spec.net), 2)
        if maybe(rng, 0.25):
            net = float(round(net))
        rate = rng.choice(spec.rates)
        description = describe(rng, spec, lang, day)
        number = series.next(vendor)
        kind = "FT"
        if index in credit_at:
            net = -net
            number = series.credit()
            description = ("Nota di credito - " if lang == "it" else "Credit note - ") + description
            kind = "NC"
        vat = round(net * rate / 100, 2)
        paid = day + timedelta(days=rng.randint(20, 55)) if maybe(rng, 0.6) else None
        out.append(
            Bill(
                seq=index + 1,
                vendor=vendor,
                category=key,
                number=number,
                day=day,
                booked=min(day + timedelta(days=rng.randint(0, 5)), month_end(day)),
                due=day + timedelta(days=rng.choice((30, 30, 60, 60, 90))),
                paid=paid,
                description=description,
                net=net,
                rate=rate,
                vat=vat,
                gross=round(net + vat, 2),
                person=rng.randint(0, 300),
                kind=kind,
            )
        )
    return out


def invoice_lines(
    rng: random.Random, count: int, *, lang: str = "it", series: NumberSeries | None = None
) -> list[Bill]:
    """`count` invoices, each on one to four lines that share its number, supplier and dates."""
    out: list[Bill] = []
    for head in bills(rng, count, lang=lang, series=series):
        spec = SPECS[head.category]
        lines = rng.choice((1, 2, 2, 3, 4))
        used = {head.description}
        for part in range(lines):
            net = head.net if lines == 1 else round(rng.uniform(*spec.net) / lines, 2)
            vat = round(net * head.rate / 100, 2)
            description = head.description
            if part:
                for _ in range(8):  # another line of the same invoice says something else
                    description = describe(rng, spec, lang, head.day)
                    if description not in used:
                        break
                used.add(description)
            out.append(
                replace(
                    head,
                    description=description,
                    net=net,
                    vat=vat,
                    gross=round(net + vat, 2),
                )
            )
    return [replace(b, seq=i + 1) for i, b in enumerate(out)]


# --- headers --------------------------------------------------------------------------------------


def vocabulary(*, it: str = "", en: str = "", both: str = "") -> tuple[H, ...]:
    """Headers written as 'first|second|third' for each language (`both`: either language)."""
    return (
        *(H(text, "it") for text in it.split("|") if text),
        *(H(text, "en") for text in en.split("|") if text),
        *(H(text, "any") for text in both.split("|") if text),
    )


SUPPLIER_H = vocabulary(
    it="Fornitore|Ragione sociale|Rag. sociale|Denominazione|Denominazione fornitore|"
    "Cedente/prestatore|Emittente|Società emittente|Anagrafica fornitore|Nome fornitore|"
    "Ditta",
    en="Vendor|Vendor Name|Supplier|Supplier Name|Payee|Billed By|Issuer|Creditor",
)
NUMBER_H = vocabulary(
    it="N. doc.|N. fattura|Num. fatt.|Nr. documento|Numero doc.|Fattura n.|Doc. n.|"
    "N° fattura|Numero fattura|Rif. fattura|N. documento fornitore",
    en="Inv. No.|Invoice #|Invoice Number|Inv Ref|Bill No.|Document No.|Doc. Number|"
    "Invoice Ref.|Supplier Invoice No.|Vendor Invoice #",
)
DATE_H = vocabulary(
    it="Data fattura|Data doc.|Data documento|Data emissione|Data fatt.|Dt. fattura|"
    "Data emissione fattura|Data del documento|Fattura del",
    en="Invoice Date|Inv. Date|Document Date|Bill Date|Date of Invoice|Issue Date|Invoice Dt",
)
REGISTERED_H = vocabulary(
    it="Data reg.|Data registrazione|Registrata il|Data competenza|Data contabile",
    en="Posting Date|Booked On|Entry Date|Date Recorded|Accounting Date",
)
PAID_H = vocabulary(
    it="Data pagamento|Pagata il|Data saldo",
    en="Payment Date|Paid On|Settled On",
)
DUE_H = vocabulary(
    it="Scadenza|Data scad.|Data scadenza|Scad. pagamento|Pagabile entro|Scadenza pagamento",
    en="Due Date|Payment Due|Pay By|Due On|Maturity Date",
)
DESC_H = vocabulary(
    it="Descrizione|Descr.|Oggetto|Descr. articolo|Descrizione articolo|Dettaglio|"
    "Prestazione|Descrizione fornitura|Causale|Servizio / merce|Oggetto della fattura|"
    "Descrizione spesa",
    en="Description|Item Description|Memo|Details|Line Text|Item|Goods / Services|Narrative|"
    "Expense Description|Invoice Text",
)
CATEGORY_H = vocabulary(
    it="Categoria|Cat. costo|Categoria spesa|Voce di costo|Conto|Natura costo|"
    "Tipologia costo|Classe di spesa",
    en="Category|Expense Category|Cost Type|Cost Category|Expense Type|Spend Category|GL Category",
)
NET_H = vocabulary(
    it="Imponibile|Imponibile €|Tot. Netto €|Totale netto|Netto|Importo netto|Imp. netto|"
    "Totale imponibile|Netto fattura|Importo imponibile|Imponibile (€)",
    en="Net Amount (EUR)|Net Amount|Net|Net Total|Amount excl. VAT|Taxable Amount|Net Value|"
    "Net (EUR)|Total excl. VAT|Net Invoice Value",
)
# a net said by the VAT it leaves out
NET_VAT_OUT_H = vocabulary(
    it="Totale IVA esclusa|Importo al netto di IVA|Importo senza IVA|Valore IVA esclusa|"
    "Tot. senza IVA",
    en="Amount before VAT|Total ex VAT|Value before tax|Excl. VAT|Amount Net of VAT",
)
VAT_H = vocabulary(
    it="IVA|Imp. IVA|Importo IVA|Imposta|IVA €|Iva (€)|Imposta IVA",
    en="VAT|VAT Amount|Tax|Tax Amount|VAT (EUR)",
)
GROSS_H = vocabulary(
    it="Totale doc.|Totale documento|Lordo|Totale fattura|Importo lordo|Totale IVA inclusa|"
    "Totale con IVA|Tot. fatt.",
    en="Gross Amount|Gross|Invoice Total|Total incl. VAT|Gross Total|Amount incl. VAT",
)
# a gross said by the VAT it holds
GROSS_VAT_IN_H = vocabulary(
    it="Totale IVA inclusa|Lordo|Importo lordo|Totale con IVA|Importo IVA compresa",
    en="Total incl. VAT|Gross Amount|Gross Total|Amount incl. VAT|Total with Tax",
)
BARE_TOTAL_H = vocabulary(
    it="Totale|Tot.|Totale €",
    en="Total|Total (EUR)",
)
BARE_AMOUNT_H = vocabulary(
    it="Importo|Importo €|Importo (€)|Totale|Tot.",
    en="Amount|Amount (EUR)|Total",
)
RATE_H = vocabulary(
    it="Aliq. %|Aliquota IVA|% IVA|Aliq. IVA %|Aliquota",
    en="VAT %|VAT Rate|Tax Rate (%)|VAT Rate %",
)
CURRENCY_H = vocabulary(
    it="Valuta|Div.|Divisa",
    en="Currency|Ccy|Curr.",
)
VAT_NUMBER_H = vocabulary(
    it="P.IVA|P. IVA fornitore|Partita IVA|Part. IVA|P.IVA forn.",
    en="VAT No.|VAT Number|Supplier VAT ID|Vendor VAT No.",
)
DOC_TYPE_H = vocabulary(
    it="Tipo doc.|Tipo documento|Causale doc.",
    en="Doc Type|Document Type",
)
REQUESTER_H = vocabulary(
    it="Richiesto da|Referente acquisto|Responsabile reparto|Ordinato da|Approvato da",
    en="Requested By|Purchaser|Approver|Ordered By|Department Manager",
)
EMAIL_H = vocabulary(
    it="E-mail referente|Email|Mail contatto",
    en="Contact Email|Approver Email",
)
PHONE_H = vocabulary(
    it="Telefono referente|Cell.|Recapito",
    en="Contact Phone|Mobile",
)
IBAN_H = vocabulary(
    it="IBAN fornitore|Coordinate bancarie",
    en="Bank Account (IBAN)|Payee IBAN",
    both="IBAN",
)
TAX_CODE_H = vocabulary(
    it="Codice fiscale|Cod. fisc. referente",
    en="Tax Code|Fiscal Code",
)

JUNK_IT: tuple[tuple[str, Callable[[Bill], Any]], ...] = (
    ("Cdc", lambda b: f"CC0{b.person % 3 + 1}"),
    ("Centro di costo", lambda b: ("Camere", "Cucina", "Generale")[b.person % 3]),
    ("Stato pagamento", lambda b: ("pagata", "da pagare", "in scadenza")[b.person % 3]),
    ("Pagato", lambda b: "SI" if b.person % 2 else "NO"),
    ("Rif. ordine", lambda b: f"ODA-{4000 + b.person}"),
    ("Cod. interno", lambda b: 700 + b.person % 40),
    ("Prot. interno", lambda b: 20000 + b.day.toordinal() % 997 * 3 + b.person % 3),
    ("Mod. pagamento", lambda b: ("Bonifico", "RiBa", "Carta")[b.person % 3]),
    ("Cod. conto", lambda b: f"310.{b.person % 90 + 10:02d}00"),
    ("Allegati", lambda b: b.person % 2),
    ("Sel.", lambda b: None),
    ("Rev.", lambda b: b.person % 3),
)
JUNK_EN: tuple[tuple[str, Callable[[Bill], Any]], ...] = (
    ("Cost Center", lambda b: f"CC{b.person % 4 + 1:02d}"),
    ("Payment Status", lambda b: ("Paid", "Open", "Overdue")[b.person % 3]),
    ("PO Number", lambda b: f"PO-{6000 + b.person}"),
    ("Approved", lambda b: "Y" if b.person % 4 else "N"),
    ("GL Account", lambda b: 600000 + b.person % 70 * 10),
    ("Payment Terms", lambda b: ("30 days", "60 days", "90 days")[b.person % 3]),
    ("Entity", lambda b: "HQ"),
    ("Attachments", lambda b: b.person % 3),
    ("Posting Key", lambda b: f"31{b.person % 4}"),
    ("Company Code", lambda b: "1000"),
)

SHEETS_IT = (
    "Registro acquisti",
    "Fatture ricevute",
    "Fatture passive",
    "Partitario",
    "Prima nota",
    "Acquisti",
    "Costi",
    "Foglio1",
    "Export",
    "Scadenzario",
)
SHEETS_EN = (
    "Purchase Ledger",
    "Vendor Invoices",
    "AP Invoices",
    "Bills",
    "Sheet1",
    "Export",
    "Invoices",
    "Expenses",
)
XLSX_NAMES = (
    "registro_acquisti.xlsx",
    "fatture_passive_ottobre.xlsx",
    "partitario_fornitori.xlsx",
    "prima_nota_costi.xlsx",
    "acquisti_2026.xlsx",
    "export_contabilita.xlsx",
    "costi di gestione.xlsx",
    "fatture da registrare.xlsx",
    "ap_invoices_export.xlsx",
    "vendor_bills.xlsx",
    "purchase_ledger.xlsx",
    "scadenziario_fornitori.xlsx",
)
CSV_NAMES = (
    "acquisti.csv",
    "fatture_ricevute.csv",
    "prima_nota.csv",
    "ap_invoices.csv",
    "vendor_ledger.csv",
    "export_fornitori.csv",
    "registro_iva_acquisti.csv",
    "bills_export.csv",
)
TITLES_IT = (
    "REGISTRO ACQUISTI",
    "FATTURE PASSIVE",
    "PARTITARIO FORNITORI",
    "ELENCO FATTURE RICEVUTE",
    "Costi di gestione",
    "Fatture da registrare",
    "SCADENZARIO FORNITORI",
)
TITLES_EN = (
    "PURCHASE LEDGER",
    "SUPPLIER INVOICES",
    "ACCOUNTS PAYABLE LISTING",
    "Vendor bills",
    "Operating expenses",
    "Invoices to post",
)


# --- how the values of a document are written -----------------------------------------------------

REAL_MONEY = ("num", "num", "num_eur", "num_fmt")
TEXT_MONEY = (
    "it",
    "it_plain",
    "us",
    "point",
    "eur_prefix",
    "eur_suffix",
    "eur_prefix_point",
    "space_it",
    "eur_code",
)
MONEY_BY_DECIMAL = {",": ("num", "it_plain", "it"), ".": ("num", "point", "us")}
REAL_DATES = ("xl", "xl", "xl_iso", "xl_long")
TEXT_DATES = {
    "it": ("it", "it", "dotted", "short", "iso", "text_it", "text_it_long", "weekday"),
    "en": ("iso", "iso", "text_en", "dash_mon", "slash_iso", "us", "it"),
}


@dataclass(slots=True)
class Look:
    """How the values of one document are written."""

    lang: str = "it"
    dates: str = "xl"
    money: str = "num"
    words: dict[str, str] = field(default_factory=dict)  # category -> the word this hotel uses


def head(rng: random.Random, look: Look, options: Sequence[H]) -> str:
    return pick(rng, options, look.lang)


def category_words(rng: random.Random, lang: str) -> dict[str, str]:
    return {
        key: rng.choice(spec.words_it if lang == "it" else spec.words_en)
        for key, spec in SPECS.items()
    }


def pick_look(
    rng: random.Random,
    *,
    text_dates: bool = False,
    text_money: bool = False,
    lang: str | None = None,
) -> Look:
    language = lang or pick_language(rng)
    dates = rng.choice(TEXT_DATES[language]) if text_dates else rng.choice(REAL_DATES)
    money = rng.choice(TEXT_MONEY) if text_money else rng.choice(REAL_MONEY)
    return Look(language, dates, money, category_words(rng, language))


def csv_options(
    delimiter: str, decimal: str, dates: str, *, bom: bool = True, newline: str = "\r\n"
) -> dict[str, Any]:
    return {
        "delimiter": delimiter,
        "decimal": decimal,
        "dates": dates,
        "encoding": "utf-8-sig" if bom else "utf-8",
        "newline": newline,
    }


def csv_or_xlsx(
    rng: random.Random, look: Look, probability: float
) -> tuple[dict[str, Any] | None, str]:
    """Sometimes a register is a CSV export: its delimiter, and how dates and numbers are written
    in it, follow. Returns the CSV options (None: an .xlsx file) and the name of the file."""
    if not maybe(rng, probability):
        return None, rng.choice(XLSX_NAMES)
    delimiter = rng.choice((";", ";", ",", "\t"))
    decimal = "," if delimiter == ";" else rng.choice((".", ","))
    if look.lang == "it":
        look.dates = rng.choice(("xl", "xl", "it", "iso", "dotted"))
    else:
        look.dates = rng.choice(("xl", "iso", "slash_iso"))
    look.money = rng.choice(MONEY_BY_DECIMAL[decimal])
    options = csv_options(delimiter, decimal, rng.choice(("iso", "it", "dotted")))
    return options, rng.choice(CSV_NAMES)


def rewrite_csv(
    content: bytes, *, delimiter: str, quote_all: bool, trailing: bool, newline: str
) -> bytes:
    """The same CSV with every field quoted and/or a delimiter after the last field."""
    encoding = "utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8"
    rows = list(csv.reader(io.StringIO(content.decode(encoding)), delimiter=delimiter))
    out = io.StringIO()
    writer = csv.writer(
        out,
        delimiter=delimiter,
        quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL,
        lineterminator=newline,
    )
    for row in rows:
        writer.writerow([*row, ""] if trailing and row else row)
    return out.getvalue().encode(encoding)


def text_date_style(look: Look, options: dict[str, Any] | None) -> str | None:
    """The style the dates of a document are written in as TEXT (None: real Excel dates)."""
    if look.dates.startswith("xl"):
        return str(options["dates"]) if options else None
    return look.dates


def date_order_for(look: Look, options: dict[str, Any] | None) -> str | None:
    style = text_date_style(look, options)
    return order_of(style) if style else None


def decimal_mark_for(look: Look, options: dict[str, Any] | None) -> str | None:
    if look.money in REAL_MONEY:
        return str(options["decimal"]) if options else None
    return decimal_of(look.money)


def check_provable(items: Sequence[Bill], look: Look, options: dict[str, Any] | None) -> None:
    """A day-first (or month-first) text date proves its order only if some day is above 12."""
    if order_of(text_date_style(look, options) or "") is None:
        return
    for name, days in (
        ("document", [b.day.day for b in items]),
        ("registration", [b.booked.day for b in items]),
        ("due", [b.due.day for b in items]),
    ):
        if max(days) <= 12:
            raise ValueError(f"the {name} dates of this document prove no order")


def check_headers(cols: Sequence[Col]) -> None:
    seen: set[str] = set()
    for col in cols:
        key = col.header.casefold()
        if key in seen:
            raise ValueError(f"header written twice: {col.header}")
        seen.add(key)


def labels_of(cols: Sequence[Col], items: Sequence[Bill], look: Look) -> dict[str, dict[str, str]]:
    """The category words of a document and what each one means (when it has a category column)."""
    if not any(c.field == "cost_category" for c in cols):
        return {}
    used = sorted({b.category for b in items})
    return {"category_mapping": {look.words[key]: SPECS[key].answer for key in used}}


def sheet_name(rng: random.Random, lang: str) -> str:
    return rng.choice(SHEETS_IT if lang == "it" else SHEETS_EN)


def period_label(items: Sequence[Bill], lang: str) -> str:
    day = items[0].day
    months = MONTHS_IT if lang == "it" else MONTHS_EN
    return f"{months[day.month - 1]} {day.year}"


def preamble(rng: random.Random, look: Look, items: Sequence[Bill], lines: int) -> list[Any]:
    hotel = rng.choice(HOTELS)
    it = look.lang == "it"
    title = rng.choice(TITLES_IT if it else TITLES_EN)
    options: list[Any] = [
        ("title", title),
        ("subtitle", f"{hotel} - {period_label(items, look.lang)}"),
        ("note", "stampato il 3 novembre 2026" if it else "printed on 3 November 2026"),
    ]
    return options[:lines]


# --- columns --------------------------------------------------------------------------------------


def c_date(rng: random.Random, look: Look, options: Sequence[H] = DATE_H) -> Col:
    return Col(head(rng, look, options), lambda b: date_cell(b.day, look.dates), "invoice_date")


def c_number(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, NUMBER_H), lambda b: b.number, "invoice_number")


def c_supplier(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, SUPPLIER_H), lambda b: b.vendor.name, "supplier_name")


def c_desc(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, DESC_H), lambda b: b.description, "line_description")


def c_net(rng: random.Random, look: Look, options: Sequence[H] = NET_H) -> Col:
    return Col(head(rng, look, options), lambda b: money_cell(b.net, look.money), "net_amount")


def c_vat(rng: random.Random, look: Look) -> Col:
    return Col(
        head(rng, look, VAT_H), lambda b: money_cell(b.vat, look.money), "invoice_tax_amount"
    )


def c_gross(rng: random.Random, look: Look, options: Sequence[H] = GROSS_H) -> Col:
    return Col(
        head(rng, look, options),
        lambda b: money_cell(b.gross, look.money),
        "invoice_gross_amount",
    )


def rate_cell(rate: int, style: str) -> Any:
    if style == "pct_text":
        return f"{rate}%"
    if style == "pct_fmt":
        return Styled(rate / 100, fmt="0%")
    return rate


def c_rate(rng: random.Random, look: Look, style: str = "int") -> Col:
    return Col(head(rng, look, RATE_H), lambda b: rate_cell(b.rate, style), "vat_rate")


def c_category(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, CATEGORY_H), lambda b: look.words[b.category], "cost_category")


def c_due(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, DUE_H), lambda b: date_cell(b.due, look.dates), "due_date")


def c_registered(rng: random.Random, look: Look) -> Col:
    """The date the document was registered: not the document date."""
    return Col(head(rng, look, REGISTERED_H), lambda b: date_cell(b.booked, look.dates))


def c_paid(rng: random.Random, look: Look) -> Col:
    return Col(
        head(rng, look, PAID_H),
        lambda b: date_cell(b.paid, look.dates) if b.paid else None,
    )


def c_currency(rng: random.Random, look: Look) -> Col:
    word = rng.choice(("EUR", "EUR", "€", "Euro"))
    return Col(head(rng, look, CURRENCY_H), lambda b: word, "currency")


def c_vat_number(rng: random.Random, look: Look) -> Col:
    return Col(head(rng, look, VAT_NUMBER_H), lambda b: b.vendor.vat_number, "supplier_vat_number")


def identity(rng: random.Random, look: Look, *, shuffle: float = 0.3) -> list[Col]:
    cols = [c_date(rng, look), c_number(rng, look), c_supplier(rng, look), c_desc(rng, look)]
    if maybe(rng, shuffle):
        rng.shuffle(cols)
    return cols


def amounts(rng: random.Random, look: Look, shape: str) -> list[Col]:
    """The amount columns of a register, every net said to be the net."""
    net = c_net(rng, look)
    vat = c_vat(rng, look)
    gross = c_gross(rng, look)
    return {
        "net": [net],
        "net_vat": [net, vat],
        "net_gross": [net, gross],
        "full": [net, vat, gross],
    }[shape]


def junk(rng: random.Random, look: Look, count: int) -> list[Col]:
    pool = JUNK_IT if look.lang == "it" else JUNK_EN
    return [Col(name, cell) for name, cell in rng.sample(pool, count)]


def personal(rng: random.Random, look: Look, count: int) -> list[Col]:
    """Columns about the people behind the purchases: all personal data."""
    pool = [
        Col(
            head(rng, look, REQUESTER_H),
            lambda b: full_name(b.person, last_first=b.person % 2 == 0),
            pii=True,
        ),
        Col(head(rng, look, EMAIL_H), lambda b: email_of(*person(b.person)), pii=True),
        Col(head(rng, look, PHONE_H), lambda b: phone_of(b.person), pii=True),
        Col(head(rng, look, IBAN_H), lambda b: iban_of(b.person), pii=True),
        Col(head(rng, look, TAX_CODE_H), lambda b: tax_code_of(b.person), pii=True),
    ]
    rng.shuffle(pool)
    return pool[:count]


def iban_of(index: int) -> str:
    """An invented IBAN (27 characters, no real bank behind it)."""
    return (
        f"IT{(index * 7) % 90 + 10:02d}Z{(index * 131) % 100000:05d}"
        f"{(index * 977) % 100000:05d}{(index * 7919) % 10**12:012d}"
    )


# --- layout helpers -------------------------------------------------------------------------------


def sum_cells(
    cols: Sequence[Col],
    group: Sequence[Bill],
    look: Look,
    label: str,
    anchor: int,
    *,
    drift: float = 0.0,
) -> list[Any]:
    """A subtotal / total line: the label in one column, the sums under the amount columns."""
    cells: list[Any] = [None] * len(cols)
    cells[anchor] = label
    for index, col in enumerate(cols):
        if col.field == "net_amount":
            cells[index] = money_cell(round(sum(b.net for b in group) + drift, 2), look.money)
        elif col.field == "invoice_tax_amount":
            cells[index] = money_cell(round(sum(b.vat for b in group), 2), look.money)
        elif col.field == "invoice_gross_amount":
            cells[index] = money_cell(round(sum(b.gross for b in group), 2), look.money)
    return cells


def label_anchor(rng: random.Random, cols: Sequence[Col]) -> int:
    """The column a TOTAL label is written in: a text column, as a ledger does."""
    texts = [i for i, c in enumerate(cols) if c.field in {"supplier_name", "line_description"}]
    return rng.choice(texts) if texts else 0


def totals_wrap(
    rng: random.Random,
    cols: Sequence[Col],
    items: Sequence[Bill],
    look: Look,
    *,
    drift: float = 0.0,
    footnote: bool = False,
) -> Callable[[list[list[Any]]], list[Any]]:
    label = rng.choice(
        ("TOTALE", "Totale generale", "Totale fatture")
        if look.lang == "it"
        else ("TOTAL", "Grand total", "Total invoices")
    )
    anchor = label_anchor(rng, cols)
    note = (
        "Stampato dal gestionale - non modificare"
        if look.lang == "it"
        else "Printed from the ledger - do not edit"
    )

    def wrap(body: list[list[Any]]) -> list[Any]:
        total = Total(sum_cells(cols, items, look, label, anchor, drift=drift))
        return [*body, total, Note(note)] if footnote else [*body, total]

    return wrap


def layout_noise(
    rng: random.Random,
    cols: Sequence[Col],
    items: Sequence[Bill],
    look: Look,
    *,
    titles: float = 0.3,
    indent: float = 0.2,
    totals: float = 0.25,
) -> dict[str, Any]:
    """What surrounds the table in real exports: title lines, a left margin, a total line."""
    layout: dict[str, Any] = {}
    if maybe(rng, titles):
        layout["preamble"] = preamble(rng, look, items, rng.randint(1, 3))
    if maybe(rng, indent):
        layout["left"] = rng.choice((1, 2))
    if maybe(rng, totals):
        layout["wrap"] = totals_wrap(rng, cols, items, look, footnote=maybe(rng, 0.3))
    return layout


def document(
    rng: random.Random,
    cols: list[Col],
    items: list[Bill],
    look: Look,
    *,
    name: str,
    outcome: str = "READY",
    csv: dict[str, Any] | None = None,
    **layout: Any,
) -> Built:
    """One flat register as a file, with the truth that goes with how it was written."""
    check_headers(cols)
    if layout.pop("provable", True):
        check_provable(items, look, csv)
    return flat_document(
        "costs",
        name,
        cols,
        items,
        outcome=outcome,
        csv=csv,
        date_order=layout.pop("date_order", date_order_for(look, csv)),
        decimal=layout.pop("decimal", decimal_mark_for(look, csv)),
        labels=layout.pop("labels", labels_of(cols, items, look)),
        sheet_title=layout.pop("sheet_title", sheet_name(rng, look.lang)),
        **layout,
    )


def golden_of(
    cols: Sequence[Col],
    items: Sequence[Bill],
    look: Look,
    where: dict[str, Any],
    *,
    outcome: str = "READY",
    **extra: Any,
) -> Golden:
    """The truth of a register assembled by hand (several sheets, several tables)."""
    meaning = parts(cols, items)
    return Golden(
        "costs",
        outcome,
        **where,
        fields=meaning["fields"],
        ambiguous=meaning["ambiguous"],
        unmapped=meaning["unmapped"],
        pii_columns=meaning["pii_columns"],
        pii_values=meaning["pii_values"],
        labels=extra.pop("labels", labels_of(cols, items, look)),
        date_order=extra.pop("date_order", date_order_for(look, None)),
        decimal=extra.pop("decimal", decimal_mark_for(look, None)),
        **extra,
    )


def group_header(groups: Sequence[str | None]) -> tuple[list[str | None], list[tuple[int, int]]]:
    """The upper header line of a two-level header: a label on the first column of each group,
    and the merges that stretch it over the others."""
    labels: list[str | None] = []
    merges: list[tuple[int, int]] = []
    start = 0
    for index, group in enumerate(groups):
        if group is not None and (index == 0 or group != groups[index - 1]):
            labels.append(group)
            start = index
        else:
            labels.append(None)
        last_of_run = group is not None and (index == len(groups) - 1 or groups[index + 1] != group)
        if last_of_run and index > start:
            merges.append((start + 1, index + 1))
    return labels, merges


# ==================================================================================================
# EASY: a clean register the benchmark has never seen
# ==================================================================================================


def easy_xlsx_register(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(8, 22), lang=look.lang)
    shape = rng.choice(("net", "net", "net_vat", "full"))
    cols = [*identity(rng, look), *amounts(rng, look, shape)]
    return document(rng, cols, items, look, name=rng.choice(XLSX_NAMES))


def easy_csv_semicolon(rng: random.Random) -> Built:
    look = pick_look(rng, lang="it")
    look.dates = rng.choice(("xl", "xl", "it", "iso", "dotted"))
    look.money = rng.choice(("num", "it_plain", "it"))
    items = bills(rng, rng.randint(8, 22), lang="it")
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    options = csv_options(";", ",", rng.choice(("it", "iso", "dotted")))
    return document(rng, cols, items, look, name=rng.choice(CSV_NAMES), csv=options)


def easy_csv_english(rng: random.Random) -> Built:
    look = pick_look(rng, lang="en")
    look.dates = rng.choice(("xl", "iso", "slash_iso"))
    look.money = rng.choice(("num", "point"))
    items = bills(rng, rng.randint(8, 22), lang="en")
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    options = csv_options(",", ".", "iso")
    return document(rng, cols, items, look, name=rng.choice(CSV_NAMES), csv=options)


def easy_xlsx_full_amounts(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(8, 22), lang=look.lang)
    cols = [*identity(rng, look, shuffle=0.15), *amounts(rng, look, "full")]
    if maybe(rng, 0.5):
        cols.append(c_currency(rng, look))
    if maybe(rng, 0.4):
        cols.insert(rng.randint(4, len(cols)), c_rate(rng, look))
    return document(rng, cols, items, look, name=rng.choice(XLSX_NAMES))


def easy_xlsx_titled(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(8, 20), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        preamble=preamble(rng, look, items, rng.randint(1, 3)),
        left=rng.choice((0, 0, 1)),
    )


def easy_xlsx_categories(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 24), lang=look.lang)
    cols = [*identity(rng, look), c_category(rng, look), *amounts(rng, look, "net_vat")]
    return document(rng, cols, items, look, name=rng.choice(XLSX_NAMES))


# ==================================================================================================
# MEDIUM: aliases, reordering, noise
# ==================================================================================================


def medium_reorder_junk(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.2)
    items = bills(rng, rng.randint(10, 26), lang=look.lang)
    shape = rng.choice(("net", "net_vat", "net_gross", "full"))
    cols = [
        *identity(rng, look, shuffle=0),
        *amounts(rng, look, shape),
        *junk(rng, look, rng.randint(1, 3)),
    ]
    if maybe(rng, 0.4):
        cols.append(c_category(rng, look))
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        preamble=preamble(rng, look, items, rng.randint(0, 2)),
        left=rng.choice((0, 1, 2)),
        wrap=(
            totals_wrap(rng, cols, items, look, footnote=maybe(rng, 0.4))
            if maybe(rng, 0.6)
            else None
        ),
    )


def medium_personal_data(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    cols = [
        *identity(rng, look, shuffle=0),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
        *personal(rng, look, rng.randint(2, 4)),
    ]
    rng.shuffle(cols)
    return document(
        rng, cols, items, look, name=name, csv=options, **layout_noise(rng, cols, items, look)
    )


def medium_text_formats(rng: random.Random) -> Built:
    look = pick_look(rng, text_dates=True, text_money=True)
    items = bills(rng, rng.randint(12, 26), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    if maybe(rng, 0.4):
        cols.append(c_due(rng, look))
    return document(
        rng, cols, items, look, name=rng.choice(XLSX_NAMES), **layout_noise(rng, cols, items, look)
    )


def summary_sheet(look: Look, items: Sequence[Bill], title: str) -> Sheet:
    """A per-supplier summary: another table, on a sheet of its own."""
    sheet = Sheet(title)
    it = look.lang == "it"
    sheet.title_line("RIEPILOGO PER FORNITORE" if it else "SUMMARY BY SUPPLIER", 3)
    sheet.blank()
    body: list[Any] = []
    for name in sorted({b.vendor.name for b in items}):
        mine = [b for b in items if b.vendor.name == name]
        body.append([name, len(mine), round(sum(b.net for b in mine), 2)])
    heading = ["Fornitore", "N. fatture", "Totale"] if it else ["Supplier", "Invoices", "Total"]
    write_table(sheet, heading, body)
    return sheet


def medium_extra_sheets(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 20), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    archive = Sheet("Archivio 2025" if look.lang == "it" else "Archive 2025", hidden=True)
    older = bills(rng, 6, lang=look.lang, year=2025)
    write_table(archive, headers(cols), records(cols, older))
    others: list[Sheet] = [archive]
    if maybe(rng, 0.7):
        others.append(summary_sheet(look, items, "Riepilogo" if look.lang == "it" else "Summary"))
    if maybe(rng, 0.4):
        directory = Sheet("Anagrafica" if look.lang == "it" else "Vendors")
        names = sorted({b.vendor.name for b in items})
        heading = (
            ["Ragione sociale", "Partita IVA", "Città"]
            if look.lang == "it"
            else ["Vendor", "VAT No.", "City"]
        )
        write_table(
            directory,
            heading,
            [[n, next(v.vat_number for v in VENDORS if v.name == n), "Rimini"] for n in names],
        )
        others.append(directory)
    first = maybe(rng, 0.3)
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        sheets_before=others if first else [],
        sheets_after=[] if first else others,
    )


def csv_dialect(
    rng: random.Random, delimiter: str, *, quote_all: bool, trailing: bool, bom: bool, newline: str
) -> Built:
    """A register exported as CSV in one dialect: delimiter, quoting, BOM, line ends, a delimiter
    after the last field."""
    look = pick_look(rng)
    decimal = "," if delimiter == ";" else rng.choice((".", ","))
    look.dates = rng.choice(("xl", "xl", "it", "iso", "dotted"))
    look.money = rng.choice(MONEY_BY_DECIMAL[decimal])
    options = csv_options(
        delimiter, decimal, rng.choice(("iso", "it", "dotted")), bom=bom, newline=newline
    )
    items = bills(rng, rng.randint(10, 24), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    if maybe(rng, 0.5):
        cols.extend(junk(rng, look, 1))
    built = document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(CSV_NAMES),
        csv=options,
        preamble=preamble(rng, look, items, rng.randint(0, 1)),
    )
    built.content = rewrite_csv(
        built.content, delimiter=delimiter, quote_all=quote_all, trailing=trailing, newline=newline
    )
    return built


def medium_csv_comma_trailing(rng: random.Random) -> Built:
    return csv_dialect(rng, ",", quote_all=maybe(rng, 0.3), trailing=True, bom=False, newline="\n")


def medium_csv_semicolon_quoted(rng: random.Random) -> Built:
    return csv_dialect(
        rng,
        ";",
        quote_all=True,
        trailing=maybe(rng, 0.3),
        bom=maybe(rng, 0.5),
        newline="\r\n",
    )


def medium_csv_tab(rng: random.Random) -> Built:
    return csv_dialect(
        rng,
        "\t",
        quote_all=maybe(rng, 0.2),
        trailing=False,
        bom=maybe(rng, 0.5),
        newline="\n",
    )


def medium_csv_comma_quoted(rng: random.Random) -> Built:
    return csv_dialect(
        rng,
        ",",
        quote_all=True,
        trailing=maybe(rng, 0.4),
        bom=False,
        newline="\r\n",
    )


def medium_multiline_invoices(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = invoice_lines(rng, rng.randint(6, 10), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    if maybe(rng, 0.4):
        cols.extend(junk(rng, look, 1))
    return document(
        rng, cols, items, look, name=name, csv=options, **layout_noise(rng, cols, items, look)
    )


def medium_credit_notes(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(12, 24), lang=look.lang, credits=rng.randint(2, 5))
    words = rng.choice(
        (("FA", "NC"), ("TD01", "TD04"))
        if look.lang == "it"
        else (("INV", "CN"), ("Invoice", "Credit note"))
    )
    kind = Col(
        head(rng, look, DOC_TYPE_H),
        lambda b: words[1] if b.kind == "NC" else words[0],
        "document_type",
    )
    cols = [
        *identity(rng, look, shuffle=0.2),
        kind,
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        **layout_noise(rng, cols, items, look),
        tolerated=("VALUE_LABELS",),
        note="Credit notes carry negative amounts and a document type.",
    )


def medium_categories_dues(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(12, 26), lang=look.lang)
    extras = [c_category(rng, look), c_due(rng, look), c_vat_number(rng, look)]
    if maybe(rng, 0.6):
        extras.append(c_currency(rng, look))
    if maybe(rng, 0.6):
        extras.append(c_rate(rng, look, rng.choice(("int", "int", "pct_text"))))
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net_vat", "full"))), *extras]
    rng.shuffle(cols)
    return document(
        rng, cols, items, look, name=name, csv=options, **layout_noise(rng, cols, items, look)
    )


# ==================================================================================================
# HARD: relationships between the amounts, two-level headers, header deep in the sheet, subtotals
# ==================================================================================================


def hard_bare_total_beside_net(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(10, 24), lang=look.lang)
    total = Col(
        head(rng, look, BARE_TOTAL_H),
        lambda b: money_cell(b.gross, look.money),
        "invoice_gross_amount",
    )
    money = [c_net(rng, look), total]
    if maybe(rng, 0.7):
        money.insert(1, c_vat(rng, look))
    if maybe(rng, 0.3):
        money.reverse()
    cols = [*identity(rng, look), *money]
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        **layout_noise(rng, cols, items, look),
        note="The net is labelled; the bare total beside it is the gross (net + VAT = total).",
    )


def hard_two_level_header(rng: random.Random) -> Built:
    look = pick_look(rng)
    it = look.lang == "it"
    items = bills(rng, rng.randint(10, 20), lang=look.lang)
    day_head, number_head = rng.choice(
        (("Data", "Numero"), ("Data", "N."), ("Data", "Num."))
        if it
        else (("Date", "Number"), ("Date", "No."))
    )
    doc_group = rng.choice(("Documento", "Fattura") if it else ("Document", "Invoice"))
    money_group = rng.choice(
        ("Importi", "Importi in €", "Valori", "Totali fattura")
        if it
        else ("Amounts", "Amounts (EUR)", "Values", "Invoice Totals")
    )
    low_net, low_vat, low_gross = rng.choice(
        (("Netto", "IVA", "Totale"), ("Imponibile", "Imposta", "Lordo"))
        if it
        else (("Net", "VAT", "Gross"), ("Net Amount", "VAT Amount", "Total"))
    )
    cols = [
        Col(day_head, lambda b: date_cell(b.day, look.dates), "invoice_date"),
        Col(number_head, lambda b: b.number, "invoice_number"),
        c_supplier(rng, look),
        c_desc(rng, look),
        Col(low_net, lambda b: money_cell(b.net, look.money), "net_amount"),
        Col(low_vat, lambda b: money_cell(b.vat, look.money), "invoice_tax_amount"),
        Col(low_gross, lambda b: money_cell(b.gross, look.money), "invoice_gross_amount"),
    ]
    groups: list[str | None] = [doc_group, doc_group, None, None, *([money_group] * 3)]
    if maybe(rng, 0.4):  # no VAT column: the group is "net, total"
        del cols[5], groups[5]
    upper, merges = group_header(groups)
    grouped = {
        col.field: column(group, col.header)
        for col, group in zip(cols, groups, strict=True)
        if group and col.field
    }
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        upper=upper,
        upper_merges=merges,
        extra_fields=grouped,
        note="Two header lines: a group over 'Netto | IVA | Totale'.",
    )


def hard_supplier_subtotals(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.2)
    items = bills(rng, rng.randint(14, 26), lang=look.lang)
    items.sort(key=lambda b: (b.vendor.name, b.day))
    cols = [
        *identity(rng, look, shuffle=0),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    sections = maybe(rng, 0.5)
    anchor = label_anchor(rng, cols)
    word = rng.choice(("Totale", "Subtotale") if look.lang == "it" else ("Total", "Subtotal"))

    def wrap(body: list[list[Any]]) -> list[Any]:
        out: list[Any] = []
        start = 0
        while start < len(items):
            vendor = items[start].vendor
            end = start
            while end < len(items) and items[end].vendor == vendor:
                end += 1
            if sections:
                out.append(Section(vendor.name))
            out.extend(body[start:end])
            label = f"{word} {vendor.name}"
            out.append(Subtotal(sum_cells(cols, items[start:end], look, label, anchor)))
            start = end
        if maybe(rng, 0.6):
            grand = "TOTALE GENERALE" if look.lang == "it" else "GRAND TOTAL"
            out.append(Total(sum_cells(cols, items, look, grand, anchor)))
        return out

    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        wrap=wrap,
        note="A subtotal line after each supplier's invoices (sometimes with a line per supplier).",
    )


def hard_several_date_columns(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    others = [c_registered(rng, look), c_due(rng, look)]
    if maybe(rng, 0.5):
        others.append(c_paid(rng, look))
    cols = [
        *identity(rng, look, shuffle=0),
        *others,
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        **layout_noise(rng, cols, items, look),
        note="The document date is the one called invoice/document date; the rest are other dates.",
    )


def hard_sheet_per_month(rng: random.Random) -> Built:
    look = pick_look(rng)
    it = look.lang == "it"
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    check_headers(cols)
    anchor = label_anchor(rng, cols)
    first_month = rng.randint(1, 8)
    series = NumberSeries(rng)
    months = MONTHS_IT if it else MONTHS_EN
    naming = rng.choice(("full", "short", "iso"))
    sheets: list[Sheet] = []
    refs: list[TableRef] = []
    everything: list[Bill] = []
    for month in range(first_month, first_month + rng.choice((3, 3, 4))):
        items = bills(rng, rng.randint(6, 11), lang=look.lang, series=series, month=month)
        everything.extend(items)
        title = {
            "full": months[month - 1].capitalize(),
            "short": f"{months[month - 1][:3].capitalize()} 26",
            "iso": f"2026-{month:02d}",
        }[naming]
        sheet = Sheet(title)
        body: list[Any] = records(cols, items)
        if maybe(rng, 0.5):
            body.append(Total(sum_cells(cols, items, look, "TOTALE" if it else "TOTAL", anchor)))
        refs.append(write_table(sheet, headers(cols), body))
        sheets.append(sheet)
    check_provable(everything, look, None)
    merged = refs[0].merged(*refs[1:])
    golden = golden_of(
        cols,
        everything,
        look,
        facts(merged, sheets=[s.title for s in sheets]),
        note="One sheet per month with the same columns: one register.",
    )
    return Built(rng.choice(XLSX_NAMES), xlsx_bytes(sheets), golden, sheets)


def hard_deep_header_metadata(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    it = look.lang == "it"
    items = bills(rng, rng.randint(10, 20), lang=look.lang)
    cols = [
        *identity(rng, look),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
        *junk(rng, look, rng.randint(0, 2)),
    ]
    style = "it" if look.dates.startswith("xl") else look.dates
    first_day = date(items[0].day.year, items[0].day.month, 1)
    period = (first_day, month_end(first_day))
    lines: list[Any] = [
        ("title", rng.choice(TITLES_IT if it else TITLES_EN)),
        ("label", "Società" if it else "Company", rng.choice(HOTELS) + " S.r.l."),
        ("label", "Partita IVA" if it else "VAT No.", Vendor(999, "", "").vat_number),
        ("label", "Esercizio" if it else "Fiscal year", "2026"),
        (
            "label",
            "Periodo" if it else "Period",
            f"{date_cell(period[0], style)} - {date_cell(period[1], style)}",
        ),
        ("label", "Filtro" if it else "Filter", "tutti i fornitori" if it else "all vendors"),
        ("label", "Estratto da" if it else "Extracted by", rng.choice(("amm1", "contabilita"))),
    ]
    lines = lines[: rng.randint(4, len(lines))]

    def after(sheet: Sheet) -> None:
        sheet.blank()
        sheet.add(
            ["I dati non includono le fatture in attesa di registrazione."]
            if it
            else ["Figures exclude invoices awaiting posting."],
            style="note",
        )

    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        preamble=lines,
        after=after if maybe(rng, 0.7) else None,
        note="The header sits under a block of company and filter lines.",
    )


def hard_kpi_band_decoy(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.2)
    it = look.lang == "it"
    items = bills(rng, rng.randint(10, 20), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net_vat", "full")))]
    total = round(sum(b.net for b in items), 2)
    band_above = maybe(rng, 0.65)
    lines: list[Any] = []
    if band_above:
        lines = [
            ("title", "CRUSCOTTO COSTI" if it else "COST DASHBOARD"),
            (
                "band",
                "Totale acquisti" if it else "Total purchases",
                total,
                None,
                "N. fatture" if it else "Invoices",
                len(items),
            ),
            (
                "band",
                "Costo medio" if it else "Average",
                round(total / len(items), 2),
                None,
                "Fornitori" if it else "Vendors",
                len({b.vendor.name for b in items}),
            ),
        ]

    def after(sheet: Sheet) -> None:
        sheet.blank(2)
        sheet.add(["Riepilogo per categoria" if it else "Summary by category"], style="label")
        heading = ["Categoria", "N.", "Imponibile"] if it else ["Category", "No.", "Net"]
        sheet.add(heading, style="header")
        for key in sorted({b.category for b in items}):
            mine = [b for b in items if b.category == key]
            sheet.add([look.words[key], len(mine), round(sum(b.net for b in mine), 2)])

    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        preamble=lines,
        after=after if (not band_above or maybe(rng, 0.5)) else None,
        note="A KPI band above and/or a summary by category below: neither is the register.",
    )


def hard_relationship_headers(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    money = [c_net(rng, look, NET_VAT_OUT_H), c_gross(rng, look, GROSS_VAT_IN_H)]
    if maybe(rng, 0.5):
        money.insert(1, c_vat(rng, look))
    cols = [*identity(rng, look), *money]
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        **layout_noise(rng, cols, items, look),
        note="The net says 'VAT excluded', the gross 'VAT included': nothing to ask.",
    )


def hard_totals_contradict(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(12, 22), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, "full")]
    if maybe(rng, 0.5):
        # on every third invoice net + VAT is not the total: a typing slip in the register
        items = [
            replace(b, gross=round(b.gross + rng.choice((2.0, 9.9, 45.0, -18.0)), 2))
            if i % 3 == 1
            else b
            for i, b in enumerate(items)
        ]
        wrap = totals_wrap(rng, cols, items, look)
        note = "On a third of the invoices net + VAT is not the total."
    else:
        wrap = totals_wrap(rng, cols, items, look, drift=rng.choice((100.0, 250.0, -75.0)))
        note = "The TOTAL line does not add up the invoices above it."
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="WARN",
        wrap=wrap,
        note=note,
    )


def hard_bare_amount_ask(rng: random.Random) -> Built:
    look = pick_look(rng)
    options, name = csv_or_xlsx(rng, look, 0.25)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    header = head(rng, look, BARE_AMOUNT_H)
    amount = Col(header, lambda b: money_cell(b.net, look.money), "net_amount", ambiguous=True)
    cols = [*identity(rng, look), amount]
    if maybe(rng, 0.4):
        cols.append(c_category(rng, look))
    return document(
        rng,
        cols,
        items,
        look,
        name=name,
        csv=options,
        outcome="ASK",
        questions=("AMOUNT_BASIS",),
        answers={"amount_basis": "NET"},
        wrap=totals_wrap(rng, cols, items, look) if maybe(rng, 0.3) else None,
        note=f"'{header}' alone does not say whether it is the net or the gross.",
    )


def hard_second_table_ask(rng: random.Random) -> Built:
    look = pick_look(rng)
    it = look.lang == "it"
    cols = [*identity(rng, look, shuffle=0), *amounts(rng, look, rng.choice(("net", "net_vat")))]
    check_headers(cols)
    hotel = rng.choice(HOTELS)
    other = rng.choice([h for h in HOTELS if h != hotel])
    mode = rng.choice(("properties", "years", "previous_month"))
    month = rng.randint(2, 9)
    months = MONTHS_IT if it else MONTHS_EN
    mine = bills(rng, rng.randint(6, 11), lang=look.lang, month=month)
    theirs = bills(
        rng,
        rng.randint(5, 9),
        lang=look.lang,
        month=month - 1 if mode == "previous_month" else month,
        year=2025 if mode == "years" else 2026,
    )
    if mode == "properties":
        titles = (
            (f"Sede - {hotel}", f"Dependance - {other}")
            if it
            else (f"Main building - {hotel}", f"Annex - {other}")
        )
    elif mode == "years":
        titles = (
            ("Fatture 2026", "Fatture 2025 (confronto)")
            if it
            else ("Invoices 2026", "Invoices 2025 (comparison)")
        )
    else:
        now, before = months[month - 1].capitalize(), months[month - 2].capitalize()
        titles = (
            (f"{now} 2026", f"{before} 2026 (mese precedente)")
            if it
            else (f"{now} 2026", f"{before} 2026 (previous month)")
        )
    mine_first = mode == "properties" or maybe(rng, 0.5)
    ordered = [(titles[0], mine), (titles[1], theirs)]
    if not mine_first:
        ordered.reverse()
    sheet = Sheet(sheet_name(rng, look.lang))
    refs: dict[str, TableRef] = {}
    for position, (title, items) in enumerate(ordered):
        if position:
            sheet.blank(2)
        sheet.add([title], style="label")
        refs[title] = write_table(sheet, headers(cols), records(cols, items))
    chosen = refs[titles[0]]
    check_provable([*mine, *theirs], look, None)
    golden = golden_of(
        cols,
        [],
        look,
        facts(chosen),
        outcome="ASK",
        questions=("TABLE",),
        answers={"table_first_row": chosen.first_row},
        note="Two registers with the same columns on one sheet: which one is the person's call.",
    )
    return Built(rng.choice(XLSX_NAMES), xlsx_bytes([sheet]), golden, [sheet])


def hard_category_words_ask(rng: random.Random) -> Built:
    look = pick_look(rng)
    unknown = rng.sample(UNKNOWN, rng.randint(2, 4))
    known = rng.sample(KNOWN[:5], 2)
    items = bills(rng, rng.randint(14, 24), lang=look.lang, categories=[*known, *unknown])
    cols = [*identity(rng, look), c_category(rng, look), *amounts(rng, look, "net")]
    used = sorted({b.category for b in items})
    mapping = {look.words[k]: ("?" if k in UNKNOWN else SPECS[k].answer) for k in used}
    answers = {look.words[k]: SPECS[k].answer for k in used if k in UNKNOWN}
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="ASK",
        questions=("VALUE_LABELS",),
        labels={"category_mapping": mapping},
        answers={"labels": {"category_mapping": answers}},
        note="Words no hotel vocabulary decides alone: the person says which category they mean.",
    )


# ==================================================================================================
# ADVERSARIAL: documents that look like a cost register and are not, or the other way round
# ==================================================================================================

PAYROLL_HEADERS = (
    ("Dipendente", "Reparto", "Mese", "Retribuzione lorda", "Netto in busta", "Contributi"),
    ("Cognome e nome", "Qualifica", "Periodo", "Lordo", "Netto a pagare", "Trattenute"),
    ("Nominativo", "Mansione", "Mese", "Totale lordo", "Netto busta paga", "INPS azienda"),
    ("Dipendente", "Livello", "Competenza", "Lordo mensile", "Netto in busta", "Oneri sociali"),
    ("Collaboratore", "Area", "Mese", "Retribuzione", "Netto erogato", "Contributi c/ditta"),
)
BANK_HEADERS_IT = (
    ("Data operazione", "Descrizione", "Entrate", "Uscite", "Saldo"),
    ("Data valuta", "Causale", "Entrate", "Uscite", "Saldo contabile"),
    ("Data", "Movimento", "Entrate", "Uscite", "Saldo progressivo"),
)
BANK_HEADERS_EN = (
    ("Date", "Description", "Money in", "Money out", "Balance"),
    ("Value date", "Details", "Credit", "Debit", "Running balance"),
)
PEOPLE_H = SUPPLIER_H + vocabulary(
    it="Collaboratore|Professionista|Prestatore", en="Contractor|Freelancer"
)
COMPANY_TAX_H = vocabulary(it="Cod. fisc.|Codice fiscale", en="Tax Code|Tax ID")
COUNTER_H = ("N. doc.", "N.", "Num. doc.", "Nr.", "Doc. n.")
COUNTER_EN_H = ("Doc No.", "No.", "Doc. Number", "Entry No.")


def adv_payroll_as_costs(rng: random.Random) -> Built:
    columns = rng.choice(PAYROLL_HEADERS)
    people = sorted(rng.sample(range(300), rng.randint(9, 16)))
    style = rng.choice(("it", "num", "eur_suffix"))
    body: list[list[Any]] = []
    names: list[str] = []
    for index in people:
        gross = rng.randint(1500, 3200) + rng.choice((0.0, 0.5))
        name = full_name(index, last_first=True)
        names.append(name)
        body.append(
            [
                name,
                rng.choice(("Reception", "Cucina", "Sala", "Piani", "Manutenzione")),
                "ottobre 2026",
                money_cell(gross, style),
                money_cell(round(gross * 0.74, 2), style),
                money_cell(round(gross * 0.31, 2), style),
            ]
        )
    pii_columns: list[tuple[str, ...]] = [(columns[0],)]
    pii_values = list(names)
    heading = list(columns)
    if maybe(rng, 0.5):
        heading.append("IBAN")
        for row, index in zip(body, people, strict=True):
            row.append(iban_of(index))
            pii_values.append(iban_of(index))
        pii_columns.append(("IBAN",))
    sheet = Sheet(rng.choice(("Paghe", "Cedolini", "Stipendi")))
    if maybe(rng, 0.5):
        sheet.title_line("PROSPETTO PAGHE OTTOBRE 2026", 4)
        sheet.blank()
    ref = write_table(sheet, heading, body)
    golden = Golden(
        "other",
        "NOT_AUTOMATIC",
        **facts(ref),
        absent=("supplier_name", "invoice_number", "invoice_date", "net_amount"),
        pii_columns=tuple(pii_columns),
        pii_values=tuple(sorted(pii_values)),
        note="Payroll: names and salaries on the costs card. Not a supplier register.",
    )
    name = rng.choice(("paghe_ottobre.xlsx", "cedolini_2026.xlsx", "costo_personale.xlsx"))
    return Built(name, xlsx_bytes([sheet]), golden, [sheet], card="costs")


def adv_bank_statement(rng: random.Random) -> Built:
    look = pick_look(rng, lang=rng.choice(("it", "it", "en")))
    it = look.lang == "it"
    items = bills(rng, rng.randint(10, 16), lang=look.lang)
    balance = float(rng.randint(15000, 40000))
    body: list[list[Any]] = []
    for b in items:
        if maybe(rng, 0.25):
            income = float(rng.randint(300, 4000))
            balance += income
            what = "Accredito incassi POS" if it else "Card settlement credit"
            body.append(
                [
                    date_cell(b.day, look.dates),
                    what,
                    money_cell(income, look.money),
                    None,
                    money_cell(round(balance, 2), look.money),
                ]
            )
        balance -= b.gross
        what = (
            f"Bonifico a favore di {b.vendor.name} saldo fatt. {b.number}"
            if it
            else f"Transfer to {b.vendor.name} inv. {b.number}"
        )
        body.append(
            [
                date_cell(b.day, look.dates),
                what,
                None,
                money_cell(b.gross, look.money),
                money_cell(round(balance, 2), look.money),
            ]
        )
    heading = rng.choice(BANK_HEADERS_IT if it else BANK_HEADERS_EN)
    sheet = Sheet(rng.choice(("Movimenti", "Conto corrente") if it else ("Transactions", "Bank")))
    title = rng.choice(("ESTRATTO CONTO ", "MOVIMENTI BANCARI ") if it else ("ACCOUNT STATEMENT ",))
    sheet.title_line(title + period_label(items, look.lang), 5)
    sheet.blank()
    ref = write_table(sheet, list(heading), body)
    golden = Golden(
        "other",
        "REJECT",
        **facts(ref),
        absent=("supplier_name", "invoice_number", "net_amount"),
        note="A bank statement: money in and out, no invoice and no supplier column.",
    )
    return Built("estratto_conto.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


def adv_people_as_suppliers(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(
        rng,
        rng.randint(10, 20),
        lang=look.lang,
        categories=("PROFESSIONAL_SERVICES", "MARKETING", "MAINTENANCE"),
    )
    last_first = maybe(rng, 0.5)
    # (a sole trader IS a supplier: the official benchmark reads a holder's name as one, after a
    # confirmation. So the column is neither personal nor settled: it must be asked about)
    who = Col(
        head(rng, look, PEOPLE_H),
        lambda b: full_name(b.person, last_first=last_first),
        "supplier_name",
        ambiguous=True,
    )
    cols = [
        c_date(rng, look),
        c_number(rng, look),
        who,
        c_desc(rng, look),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="NOT_AUTOMATIC",
        note="The supplier column holds the names of people: asked about, never decided.",
    )


def adv_row_counter_number(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    header = rng.choice(COUNTER_H if look.lang == "it" else COUNTER_EN_H)
    counter = Col(header, lambda b: b.seq)
    cols = [
        counter,
        c_date(rng, look),
        c_supplier(rng, look),
        c_desc(rng, look),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="NOT_AUTOMATIC",
        absent=("invoice_number",),
        note=f"'{header}' counts the rows 1..n: it is not the number of an invoice.",
    )


def adv_vat_percent_column(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    style = rng.choice(("int", "pct_text", "pct_fmt"))
    header = rng.choice(("IVA", "% IVA", "Aliq. IVA") if look.lang == "it" else ("VAT", "VAT %"))
    rate = Col(header, lambda b: rate_cell(b.rate, style), "vat_rate")
    cols = [*identity(rng, look), c_net(rng, look), rate]
    if maybe(rng, 0.4):
        cols.append(c_gross(rng, look))
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        absent=("invoice_tax_amount",),
        note=f"'{header}' holds the VAT rate (22 / 10 / 4), not an amount of VAT.",
    )


def adv_ambiguous_date_order(rng: random.Random) -> Built:
    look = pick_look(rng)
    look.dates = rng.choice(("it", "dotted", "short"))
    base = bills(rng, rng.randint(10, 16), lang=look.lang)
    months = sorted(rng.randint(1, 9) for _ in base)
    items = []
    for b, month in zip(base, months, strict=True):
        day = date(2026, month, rng.randint(1, 12))
        text = describe(rng, SPECS[b.category], look.lang, day)
        items.append(
            replace(b, day=day, booked=day, due=day + timedelta(days=30), description=text)
        )
    if all(b.day.day == b.day.month for b in items):
        raise ValueError("a document whose day and month are always the same is not ambiguous")
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat")))]
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="ASK",
        provable=False,
        questions=("DATE_ORDER",),
        answers={"date_order": "DMY"},
        date_order="DMY",
        note="Every day is 12 or less: 03/04 can be the 3rd of April or the 4th of March.",
    )


def adv_gross_only(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    cols = [*identity(rng, look), c_gross(rng, look, GROSS_VAT_IN_H)]
    if maybe(rng, 0.3):
        cols.append(c_rate(rng, look))
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="NOT_AUTOMATIC",
        absent=("net_amount",),
        blockers=("AMOUNT_NOT_NET",),
        note="The only amount says VAT is included: it is the gross, NINFA works with the net.",
    )


def adv_bookings_under_costs_title(rng: random.Random) -> Built:
    it = maybe(rng, 0.75)
    sheet = Sheet(rng.choice(("Fatture", "Costi", "Registro") if it else ("Invoices", "Costs")))
    sheet.title_line(rng.choice(TITLES_IT if it else TITLES_EN), 6)
    sheet.blank()
    channels = ("Booking.com", "Expedia", "Diretto", "Telefono", "Sito web", "Airbnb")
    body: list[list[Any]] = []
    for index in range(rng.randint(10, 16)):
        arrival = date(2026, 10, 14) + timedelta(days=rng.randint(0, 40))
        nights = rng.choice((1, 2, 3, 4, 7))
        body.append(
            [
                f"BK{500000 + index * 37 + rng.randint(0, 30)}",
                date_cell(arrival - timedelta(days=rng.randint(5, 60)), "xl"),
                date_cell(arrival, "xl"),
                date_cell(arrival + timedelta(days=nights), "xl"),
                rng.choice(channels),
                money_cell(rng.choice((89.0, 119.0, 149.0, 189.0)) * nights, "num"),
            ]
        )
    heading = (
        ["Cod. prenotazione", "Data pren.", "Arrivo", "Partenza", "Canale", "Importo camere"]
        if it
        else ["Booking ref", "Booked on", "Arrival", "Departure", "Channel", "Room revenue"]
    )
    ref = write_table(sheet, heading, body)
    golden = Golden(
        "bookings",
        "NOT_AUTOMATIC",
        **facts(ref),
        absent=("supplier_name", "invoice_number", "net_amount"),
        note="The title speaks of invoices and costs; the table is a list of bookings.",
    )
    name = rng.choice(("fatture_ottobre.xlsx", "registro_costi.xlsx", "elenco_fatture.xlsx"))
    return Built(name, xlsx_bytes([sheet]), golden, [sheet], card="costs")


def adv_tax_ids_as_number(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 20), lang=look.lang)
    company_code = Col(head(rng, look, COMPANY_TAX_H), lambda b: b.vendor.tax_digits, junk=False)
    cols = [
        c_date(rng, look),
        c_supplier(rng, look),
        c_desc(rng, look),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
        c_vat_number(rng, look),
        company_code,
    ]
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="NOT_AUTOMATIC",
        absent=("invoice_number",),
        note="The number-like columns are the suppliers' VAT number and tax code, not an invoice.",
    )


def adv_hidden_sheet_only(rng: random.Random) -> Built:
    look = pick_look(rng)
    it = look.lang == "it"
    items = bills(rng, rng.randint(8, 16), lang=look.lang)
    cols = [*identity(rng, look), *amounts(rng, look, rng.choice(("net", "net_vat", "full")))]
    check_headers(cols)
    visible = Sheet("LEGGIMI" if it else "README")
    visible.add(
        ["I dati delle fatture sono nel foglio nascosto 'Registro'."]
        if it
        else ["The invoices are on the hidden sheet 'Ledger'."]
    )
    hidden = Sheet("Registro" if it else "Ledger", hidden=True)
    ref = write_table(hidden, headers(cols), records(cols, items))
    golden = golden_of(
        cols,
        items,
        look,
        facts(ref),
        outcome="NOT_AUTOMATIC",
        note="The invoices are on a hidden sheet: nothing is imported without a person.",
    )
    return Built(
        rng.choice(XLSX_NAMES),
        xlsx_bytes([visible, hidden]),
        without_table(golden),
        [visible, hidden],
    )


def adv_restaurant_sales(rng: random.Random) -> Built:
    it = maybe(rng, 0.7)
    sheet = Sheet("Incassi" if it else "Sales")
    sheet.title_line("INCASSI RISTORANTE" if it else "RESTAURANT TAKINGS", 6)
    sheet.blank()
    body: list[list[Any]] = []
    for offset in range(rng.randint(8, 12)):
        day = date(2026, 10, 12) + timedelta(days=offset)
        for service in ("Pranzo", "Cena") if it else ("Lunch", "Dinner"):
            covers = rng.randint(18, 90)
            takings = round(covers * rng.uniform(21, 46), 2)
            body.append(
                [
                    date_cell(day, "xl"),
                    service,
                    covers,
                    rng.randint(covers // 3, covers),
                    takings,
                    round(takings / covers, 2),
                ]
            )
    heading = (
        ["Data", "Servizio", "Coperti", "Scontrini", "Incasso €", "Scontrino medio"]
        if it
        else ["Date", "Service", "Covers", "Receipts", "Takings", "Average check"]
    )
    ref = write_table(sheet, heading, body)
    golden = Golden(
        "other",
        "REJECT",
        **facts(ref),
        absent=("supplier_name", "invoice_number", "net_amount"),
        note="Daily takings of a restaurant: revenue, not a cost register.",
    )
    return Built("incassi_ristorante.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


def adv_utilities_summary(rng: random.Random) -> Built:
    sheet = Sheet("Utenze")
    sheet.title_line("CONSUMI E SPESE UTENZE 2026", 7)
    sheet.blank()
    body: list[Any] = []
    energy = rng.randint(14000, 26000)
    for month in range(rng.randint(6, 10)):
        kwh = energy + rng.randint(-3000, 3000)
        gas = rng.randint(300, 3200)
        water = rng.randint(250, 900)
        body.append(
            [
                MONTHS_IT[month].capitalize(),
                kwh,
                gas,
                water,
                round(kwh * rng.uniform(0.21, 0.29), 2),
                round(gas * rng.uniform(1.0, 1.4), 2),
                round(water * rng.uniform(2.1, 2.8), 2),
            ]
        )
    if maybe(rng, 0.6):
        body.append(
            Total(
                [
                    "TOTALE",
                    sum(r[1] for r in body),
                    sum(r[2] for r in body),
                    sum(r[3] for r in body),
                    round(sum(r[4] for r in body), 2),
                    round(sum(r[5] for r in body), 2),
                    round(sum(r[6] for r in body), 2),
                ]
            )
        )
    ref = write_table(
        sheet,
        ["Mese", "kWh", "Gas m3", "Acqua m3", "Spesa energia €", "Spesa gas €", "Spesa acqua €"],
        body,
    )
    golden = Golden(
        "other",
        "NOT_AUTOMATIC",
        **facts(ref),
        absent=("supplier_name", "invoice_number"),
        note="Monthly consumption and spend by utility: a summary, no invoice in it.",
    )
    return Built("consumi_utenze.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="costs")


def adv_no_description(rng: random.Random) -> Built:
    look = pick_look(rng)
    items = bills(rng, rng.randint(10, 22), lang=look.lang)
    cols = [
        c_date(rng, look),
        c_number(rng, look),
        c_supplier(rng, look),
        *amounts(rng, look, rng.choice(("net", "net_vat", "full"))),
    ]
    return document(
        rng,
        cols,
        items,
        look,
        name=rng.choice(XLSX_NAMES),
        outcome="REJECT",
        blockers=("MISSING_REQUIRED",),
        absent=("line_description",),
        note="Nothing says what each invoice is for: a required fact is missing.",
    )


RECIPES: dict[str, Sequence[Maker]] = {
    "EASY": (
        easy_xlsx_register,
        easy_csv_semicolon,
        easy_csv_english,
        easy_xlsx_full_amounts,
        easy_xlsx_titled,
        easy_xlsx_categories,
    ),
    "MEDIUM": (
        medium_reorder_junk,
        medium_personal_data,
        medium_text_formats,
        medium_extra_sheets,
        medium_multiline_invoices,
        medium_credit_notes,
        medium_categories_dues,
        medium_csv_semicolon_quoted,
        medium_csv_comma_trailing,
        medium_csv_tab,
        medium_csv_comma_quoted,
    ),
    "HARD": (
        hard_bare_total_beside_net,
        hard_bare_amount_ask,
        hard_second_table_ask,
        hard_two_level_header,
        hard_supplier_subtotals,
        hard_several_date_columns,
        hard_sheet_per_month,
        hard_deep_header_metadata,
        hard_category_words_ask,
        hard_kpi_band_decoy,
        hard_relationship_headers,
        hard_totals_contradict,
    ),
    "ADVERSARIAL": (
        adv_payroll_as_costs,
        adv_bank_statement,
        adv_people_as_suppliers,
        adv_row_counter_number,
        adv_vat_percent_column,
        adv_ambiguous_date_order,
        adv_gross_only,
        adv_bookings_under_costs_title,
        adv_tax_ids_as_number,
        adv_hidden_sheet_only,
        adv_restaurant_sales,
        adv_utilities_summary,
        adv_no_description,
    ),
}


def build() -> list[Doc]:
    return assemble("UC", "costs", RECIPES)


__all__ = ["RECIPES", "build"]

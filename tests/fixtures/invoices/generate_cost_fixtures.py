"""Synthetic invoice fixtures and the independent expected result of the Gate 6 golden scenario
("MASSERIA NINFA DEMO — COST DATA V1").

Standard library only (csv, fractions, hashlib, unicodedata, datetime, json). It shares NO code with
the application: not the name normalisation, not the fuzzy similarity, not the rounding, not the
classification. Exact arithmetic (`fractions.Fraction`) is used everywhere; the application uses
`Decimal`. Every person, company, e-mail, phone, address, tax code and bank account below is
invented (`example`, `+39 000 ...`, fictional IBANs whose check digits are valid but whose accounts
do not exist).

It (re)writes, next to itself:

  xml/*.xml                                  15 FatturaPA fixtures (one per case of the specification)
  structured/*                               the structured CSV fixtures and two unsupported files
  golden/masseria_ninfa_cost_*.xml/.csv      the golden import files, in the order they are imported
  golden/masseria_ninfa_cost_v1.expected.json  the WORLD OF TRUTH: suppliers, aliases, reviews,
                                             invoices, lines, categories and aggregates

The expected result is not "what the application does": it is what the WORLD below says. The world
is designed by hand: which supplier each invoice belongs to, which spelling and identifier it
carries, which sign it is written with, which category each line deserves and why. The rules that
turn that into canonical amounts (signs, half-up rounding) and the fuzzy similarity of the one
intended near-duplicate are re-implemented here from the written specification
(docs/architecture/cost-ingestion-v1.md).

Run it from anywhere:  python generate_cost_fixtures.py
"""

import csv
import hashlib
import io
import json
import unicodedata
from datetime import date
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
XML_DIR = HERE / "xml"
STRUCTURED_DIR = HERE / "structured"
GOLDEN_DIR = HERE / "golden"
EXPECTED = GOLDEN_DIR / "masseria_ninfa_cost_v1.expected.json"

NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"

# Fictional bank accounts with valid check digits (the well-known documentation examples).
IBAN_A = "IT60X0542811101000000123456"
IBAN_B = "GB82WEST12345698765432"
IBAN_C = "DE89370400440532013000"

# PII that a source carries and NINFA must never store (fixtures and golden).
RECIPIENT = "Masseria Cliente Fittizia S.r.l."
RECIPIENT_TAX = "99999999999"
SUPPLIER_EMAIL = "amministrazione@fornitore-fittizio.example"
SUPPLIER_PHONE = "+39 000 5550101"
SUPPLIER_STREET = "Via Inventata 12"


# --- exact arithmetic ----------------------------------------------------------------------------


def half_up_2(value: Fraction) -> Fraction:
    """Round half away from zero to two decimals (the specified HALF_UP)."""
    sign = -1 if value < 0 else 1
    cents = int((abs(value) * 100 + Fraction(1, 2)) // 1)
    return Fraction(sign * cents, 100)


def money(value: Fraction) -> str:
    """Two-decimal text of an exact value (which must already be a whole number of cents)."""
    cents = value * 100
    assert cents.denominator == 1, value
    n = int(cents)
    sign = "-" if n < 0 else ""
    return f"{sign}{abs(n) // 100}.{abs(n) % 100:02d}"


def it_number(value: Fraction) -> str:
    """Italian formatting: thousands dot, decimal comma."""
    text = money(value)
    sign = "-" if text.startswith("-") else ""
    whole, cents = text.lstrip("-").split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{'.'.join(groups)},{cents}"


def plain(value: Fraction) -> str:
    """Shortest decimal text of an exact value with a finite decimal expansion."""
    if value.denominator == 1:
        return str(value.numerator)
    text = f"{float(value):.10f}".rstrip("0").rstrip(".")
    assert Fraction(text) == value, value
    return text


# --- independent name normalisation and similarity -------------------------------------------------


def norm_name(text: str) -> str:
    """Comparison form of a supplier name: no dots, no accents, lower case, words only."""
    text = unicodedata.normalize("NFKC", text).replace(".", "")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    words: list[str] = []
    current = ""
    for char in text.casefold():
        if char.isalnum():
            current += char
        else:
            if current:
                words.append(current)
            current = ""
    if current:
        words.append(current)
    return " ".join(words)


def _longest(a: str, alo: int, ahi: int, b: str, blo: int, bhi: int) -> tuple[int, int, int]:
    best = (alo, blo, 0)
    for i in range(alo, ahi):
        for j in range(blo, bhi):
            k = 0
            while i + k < ahi and j + k < bhi and a[i + k] == b[j + k]:
                k += 1
            if k > best[2]:
                best = (i, j, k)
    return best


def _matching(a: str, alo: int, ahi: int, b: str, blo: int, bhi: int) -> int:
    i, j, k = _longest(a, alo, ahi, b, blo, bhi)
    if k == 0:
        return 0
    return k + _matching(a, alo, i, b, blo, j) + _matching(a, i + k, ahi, b, j + k, bhi)


def similarity(a: str, b: str) -> str:
    """Ratcliff/Obershelp ratio 2*M/T, four decimals half up, as text."""
    ratio = Fraction(2 * _matching(a, 0, len(a), b, 0, len(b)), len(a) + len(b))
    scaled = int((ratio * 10000 + Fraction(1, 2)) // 1)
    return f"{scaled // 10000}.{scaled % 10000:04d}"


# --- an independent FatturaPA writer ---------------------------------------------------------------


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tag(name: str, inner: str, prefix: str = "") -> str:
    return f"<{prefix}{name}>{inner}</{prefix}{name}>"


def opt(name: str, value: str | None, prefix: str = "") -> str:
    return "" if value is None else tag(name, esc(value), prefix)


def fattura(
    cedente: dict,
    bodies: list[dict],
    *,
    version: str = "FPR12",
    prefix: str = "",
    doctype: str = "",
) -> str:
    """`cedente`: name | (first, last), country, vat, tax. `bodies`: see `body_xml`."""
    p = prefix
    ns = f' xmlns{":" + p[:-1] if p else ""}="{NS}"'
    name = cedente.get("name")
    if name is not None:
        anagrafica = tag("Denominazione", esc(name), p)
    else:
        anagrafica = opt("Nome", cedente.get("first"), p) + opt("Cognome", cedente.get("last"), p)
    vat = cedente.get("vat")
    vat_xml = (
        tag("IdFiscaleIVA", opt("IdPaese", cedente.get("country", "IT"), p) + opt("IdCodice", vat, p), p)
        if vat is not None
        else ""
    )
    header = tag(
        "FatturaElettronicaHeader",
        tag(
            "DatiTrasmissione",
            tag("IdTrasmittente", opt("IdPaese", "IT", p) + opt("IdCodice", "00000000001", p), p)
            + opt("ProgressivoInvio", "00001", p)
            + opt("FormatoTrasmissione", version, p)
            + opt("CodiceDestinatario", "ABCDEFG", p)
            + opt("PECDestinatario", "cliente-pec@example.com", p),
            p,
        )
        + tag(
            "CedentePrestatore",
            tag(
                "DatiAnagrafici",
                vat_xml
                + opt("CodiceFiscale", cedente.get("tax"), p)
                + tag("Anagrafica", anagrafica, p)
                + opt("RegimeFiscale", "RF01", p),
                p,
            )
            + tag(
                "Sede",
                opt("Indirizzo", SUPPLIER_STREET, p)
                + opt("CAP", "06121", p)
                + opt("Comune", "Perugia", p)
                + opt("Provincia", "PG", p)
                + opt("Nazione", cedente.get("country", "IT"), p),
                p,
            )
            + tag("Contatti", opt("Telefono", SUPPLIER_PHONE, p) + opt("Email", SUPPLIER_EMAIL, p), p),
            p,
        )
        + tag(
            "CessionarioCommittente",
            tag(
                "DatiAnagrafici",
                opt("CodiceFiscale", RECIPIENT_TAX, p)
                + tag("Anagrafica", opt("Denominazione", RECIPIENT, p), p),
                p,
            )
            + tag("Sede", opt("Indirizzo", "Via del Cliente 1", p) + opt("Nazione", "IT", p), p),
            p,
        ),
        p,
    )
    body_text = "".join(body_xml(body, p) for body in bodies)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + doctype
        + f'<{p}FatturaElettronica{ns} versione="{version}">\n'
        + header
        + "\n"
        + body_text
        + f"</{p}FatturaElettronica>\n"
    )


def body_xml(body: dict, p: str) -> str:
    """`body`: type, date, number, lines [(n, desc, qty, unit, price, total, vat)], gross (bool),
    payments [(due, iban, beneficiary)], rate (summary VAT rate, default 22)."""
    lines = "".join(
        tag(
            "DettaglioLinee",
            opt("NumeroLinea", str(n), p)
            + opt("Descrizione", desc, p)
            + opt("Quantita", None if qty is None else plain(qty), p)
            + opt("UnitaMisura", unit, p)
            + opt("PrezzoUnitario", None if price is None else plain(price), p)
            + opt("PrezzoTotale", plain(total), p)
            + opt("AliquotaIVA", vat, p),
            p,
        )
        for n, desc, qty, unit, price, total, vat in body["lines"]
    )
    rate = Fraction(body.get("rate", "22"))
    net = half_up_2(sum((line[5] for line in body["lines"]), Fraction(0)))
    tax = half_up_2(net * rate / 100)
    summary = tag(
        "DatiRiepilogo",
        opt("AliquotaIVA", money(rate), p)
        + opt("ImponibileImporto", money(net), p)
        + opt("Imposta", money(tax), p),
        p,
    )
    payments = ""
    if body.get("payments"):
        details = "".join(
            tag(
                "DettaglioPagamento",
                opt("Beneficiario", ben, p)
                + opt("ModalitaPagamento", "MP05", p)
                + opt("DataScadenzaPagamento", due, p)
                + opt("ImportoPagamento", "100.00", p)
                + opt("IBAN", iban, p),
                p,
            )
            for due, iban, ben in body["payments"]
        )
        payments = tag("DatiPagamento", opt("CondizioniPagamento", "TP02", p) + details, p)
    general = tag(
        "DatiGeneraliDocumento",
        opt("TipoDocumento", body.get("type", "TD01"), p)
        + opt("Divisa", body.get("currency", "EUR"), p)
        + opt("Data", body.get("date"), p)
        + opt("Numero", body.get("number"), p)
        + opt("ImportoTotaleDocumento", money(net + tax) if body.get("gross") else None, p),
        p,
    )
    return tag(
        "FatturaElettronicaBody",
        tag("DatiGenerali", general, p)
        + tag("DatiBeniServizi", lines + summary, p)
        + payments
        + tag("Allegati", opt("NomeAttachment", "copia.pdf", p) + opt("Attachment", "JVBERi0xLjQKJSVFT0Y=", p), p),
        p,
    )


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.write_bytes(data)


def line(n, desc, total, *, qty=None, unit=None, price=None, vat="22.00"):
    return (n, desc, qty, unit, price, Fraction(total), vat)


# --- the 15 FatturaPA fixtures -------------------------------------------------------------------------

ROSSI = {"name": "Rossi Food S.r.l.", "vat": "01234567890"}
BIANCHI = {"name": "Bianchi Servizi S.n.c.", "vat": "09876543210", "tax": "09876543210"}


def xml_fixtures() -> dict[str, str]:
    standard = {
        "type": "TD01",
        "date": "2026-03-10",
        "number": "FA-0001",
        "gross": True,
        "lines": [
            line(1, "Forniture di cucina", "120.00", qty=Fraction(4), unit="pz", price=Fraction(30)),
            line(2, "Consegna", "20.00"),
        ],
    }
    files: dict[str, str] = {}
    files["01_fpr12_standard.xml"] = fattura(ROSSI, [standard])
    files["02_fpa12_standard.xml"] = fattura(
        ROSSI, [{**standard, "number": "FA-0002"}], version="FPA12"
    )
    files["03_td04_credit_note.xml"] = fattura(
        ROSSI,
        [{**standard, "type": "TD04", "number": "NC-0001", "lines": [line(1, "Storno forniture", "50.00")]}],
    )
    files["04_td08_simplified_credit_note.xml"] = fattura(
        ROSSI,
        [{**standard, "type": "TD08", "number": "NCS-0001", "lines": [line(1, "Storno scontrino", "12.30")]}],
    )
    files["05_multi_body.xml"] = fattura(
        ROSSI,
        [
            {**standard, "number": "MB-0101", "date": "2026-03-01"},
            {**standard, "number": "MB-0102", "date": "2026-03-02", "type": "TD04",
             "lines": [line(1, "Storno parziale", "10.00")]},
            {**standard, "number": "MB-0103", "date": "2026-03-03",
             "lines": [line(1, "Altra fornitura", "70.00"), line(2, "Trasporto", "8.00")]},
        ],
    )
    files["06_supplier_vat_and_tax_code.xml"] = fattura(
        BIANCHI, [{**standard, "number": "BS-0001", "lines": [line(1, "Servizio di manutenzione", "200.00")]}]
    )
    files["07_same_vat_slightly_different_name.xml"] = fattura(
        {"name": "Rossi Food Società S.r.l.", "vat": "01234567890"},
        [{**standard, "number": "FA-0701"}],
    )
    files["08_no_vat_exact_alias.xml"] = fattura(
        {"name": "ROSSI FOOD SOCIETA' S.R.L."}, [{**standard, "number": "FA-0801"}]
    )
    files["09_fuzzy_candidate.xml"] = fattura(
        {"name": "Rossi Foods S.r.l."}, [{**standard, "number": "FA-0901"}]
    )
    files["10_conflicting_identities.xml"] = fattura(
        {"name": "Rossi Food S.r.l.", "vat": "01234567890", "tax": "09876543210"},
        [{**standard, "number": "FA-1001"}],
    )
    files["11_one_due_date.xml"] = fattura(
        ROSSI, [{**standard, "number": "FA-1101", "payments": [("2026-04-10", None, None)]}]
    )
    files["12_multiple_due_dates.xml"] = fattura(
        ROSSI,
        [{**standard, "number": "FA-1201",
          "payments": [("2026-04-10", None, None), ("2026-05-10", None, None)]}],
    )
    files["13_raw_iban.xml"] = fattura(
        ROSSI,
        [{**standard, "number": "FA-1301", "payments": [("2026-04-10", IBAN_A, "Rossi Food S.r.l.")]}],
    )
    files["14_malicious_doctype_entity.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE FatturaElettronica [\n'
        '  <!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        "]>\n"
        f'<FatturaElettronica xmlns="{NS}" versione="FPR12">&xxe;&lol2;</FatturaElettronica>\n'
    )
    missing = {**standard, "number": None, "date": None, "lines": [line(1, "Forniture", "10.00")]}
    files["15_missing_required_data.xml"] = fattura(ROSSI, [missing])
    return files


# --- the structured fixtures ------------------------------------------------------------------------------


def csv_text(rows: list[list[str]], delimiter: str) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, delimiter=delimiter, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


EN_HEADERS = ["Supplier", "VAT", "Invoice No", "Invoice Date", "Description", "Line Total"]
IT_HEADERS = ["Fornitore", "P.IVA", "Numero Fattura", "Data", "Descrizione", "Importo"]
EN_ROWS = [
    ["Rossi Food S.r.l.", "01234567890", "EN-1", "2026-03-10", "Kitchen supplies", "120.00"],
    ["Rossi Food S.r.l.", "01234567890", "EN-1", "2026-03-10", "Delivery", "20.00"],
    ["Bianchi Servizi S.n.c.", "09876543210", "EN-2", "2026-03-11", "Maintenance visit", "200.00"],
]
IT_ROWS = [
    ["Rossi Food S.r.l.", "01234567890", "IT-1", "10/03/2026", "Forniture di cucina", "1.234,56"],
    ["Rossi Food S.r.l.", "01234567890", "IT-1", "10/03/2026", "Consegna caffè", "20,00"],
    ["Bianchi Servizi S.n.c.", "09876543210", "IT-2", "11/03/2026", "Visita di manutenzione", "200,00"],
]


def structured_fixtures() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["it_semicolon.csv"] = csv_text([IT_HEADERS, *IT_ROWS], ";").encode("utf-8")
    files["en_comma.csv"] = csv_text([EN_HEADERS, *EN_ROWS], ",").encode("utf-8")
    files["utf8_bom.csv"] = b"\xef\xbb\xbf" + csv_text([EN_HEADERS, *EN_ROWS], ",").encode("utf-8")
    files["cp1252.csv"] = csv_text([IT_HEADERS, *IT_ROWS], ";").encode("cp1252")
    # 6. the invoice header repeated on every line (net and gross too)
    headers = [*EN_HEADERS, "Gross"]
    files["repeated_invoice_header.csv"] = csv_text(
        [
            headers,
            ["Rossi Food S.r.l.", "01234567890", "RH-1", "2026-03-10", "Line one", "10.00", "36.60"],
            ["Rossi Food S.r.l.", "01234567890", "RH-1", "2026-03-10", "Line two", "20.00", "36.60"],
            ["Rossi Food S.r.l.", "01234567890", "RH-1", "2026-03-10", "Line three", "0.00", "36.60"],
        ],
        ",",
    ).encode("utf-8")
    # 7. a category column whose labels need the mapping
    files["category_mapped.csv"] = csv_text(
        [
            [*EN_HEADERS, "Category"],
            ["Rossi Food S.r.l.", "01234567890", "CM-1", "2026-03-10", "Bed linen rental", "80.00", "Biancheria"],
            ["Rossi Food S.r.l.", "01234567890", "CM-1", "2026-03-10", "Delivery", "10.00", "Trasporto"],
            ["Rossi Food S.r.l.", "01234567890", "CM-1", "2026-03-10", "Odd item", "5.00", "OTHER"],
        ],
        ",",
    ).encode("utf-8")
    # 8. the same invoice stating two different totals
    files["conflicting_repeated_total.csv"] = csv_text(
        [
            headers,
            ["Rossi Food S.r.l.", "01234567890", "CT-1", "2026-03-10", "Line one", "10.00", "12.20"],
            ["Rossi Food S.r.l.", "01234567890", "CT-1", "2026-03-10", "Line two", "20.00", "36.60"],
        ],
        ",",
    ).encode("utf-8")
    # 9. the same line number twice in one invoice
    files["duplicate_line_number.csv"] = csv_text(
        [
            [*EN_HEADERS, "Line"],
            ["Rossi Food S.r.l.", "01234567890", "DL-1", "2026-03-10", "First", "10.00", "1"],
            ["Rossi Food S.r.l.", "01234567890", "DL-1", "2026-03-10", "Second", "20.00", "1"],
        ],
        ",",
    ).encode("utf-8")
    # 10. personal data in columns nobody mapped
    files["pii_unmapped_columns.csv"] = csv_text(
        [
            [*EN_HEADERS, "Contact email", "Contact phone", "Street", "Customer"],
            ["Rossi Food S.r.l.", "01234567890", "PI-1", "2026-03-10", "Kitchen supplies", "120.00",
             SUPPLIER_EMAIL, SUPPLIER_PHONE, SUPPLIER_STREET, RECIPIENT],
        ],
        ",",
    ).encode("utf-8")
    # 11. a mapped column renamed
    files["changed_schema.csv"] = csv_text(
        [
            ["Supplier", "VAT", "Invoice No", "Invoice Date", "Description", "Amount"],
            ["Rossi Food S.r.l.", "01234567890", "CS-1", "2026-03-10", "Kitchen supplies", "120.00"],
        ],
        ",",
    ).encode("utf-8")
    # 12. files NINFA does not read (placeholders, not real documents)
    files["unsupported.pdf"] = b"%PDF-1.4\n% synthetic placeholder: NINFA V1 has no PDF reader\n%%EOF\n"
    files["unsupported.xml.p7m"] = b"0\x82\x01\x00 synthetic placeholder: a signed file is refused in V1\n"
    return files


# --- the golden world ------------------------------------------------------------------------------------
#
# Nine suppliers, five files of XML and two structured ones, January to June 2026, one property.

SUPPLIERS = {
    "S1": {"name": "Lavanderia Salentina S.r.l.", "vat": "03111111111", "ibans": [IBAN_A]},
    "S2": {"name": "Energia Puglia S.p.A.", "vat": "03222222222", "ibans": [IBAN_B]},
    "S3": {"name": "Agrifood Murgia S.r.l.", "vat": "03333333333", "tax": "03333333333", "ibans": []},
    "S4": {"name": "Software Salento S.r.l.", "vat": "03444444444", "ibans": []},
    # a structured file gives a country only through the VAT number: none here, so it stays unknown
    "S5": {"name": "Bianchi Laura", "tax": "BNCLRA85M41H501Z", "ibans": [], "country": None},
    "S6": {"name": "Trasporti Rapidi S.n.c.", "vat": "03555555555", "ibans": [IBAN_C]},
    "S7": {"name": "Agrifood Murgia Sud S.r.l.", "ibans": []},
    "S9": {"name": "Nuovo Fornitore Ospitalità S.r.l.", "vat": "03999999999", "ibans": []},
}
S1_VARIANT = "Lavanderia Salentina di Rossi S.r.l."
S1_IBAN_ONLY = "L. Salentina Lavanderie"
S5_VARIANT = "Laura Bianchi"

# (category, method, confidence) shorthands of a line's truth
RULE = "DETERMINISTIC_RULE"
DEFAULT = "SUPPLIER_DEFAULT"
EXPLICIT = "EXPLICIT_SOURCE"
NONE = "UNCLASSIFIED"
CONF = {RULE: "80.00", DEFAULT: "90.00", EXPLICIT: "100.00", NONE: "0.00"}

INVOICES: list[dict] = []


def invoice(step, supplier, number, day, lines, *, kind="INVOICE", type_code="TD01", fmt,
            method, spelling=None, headline="positive", net_given=True, tax_given=False,
            gross_given=False, due=None, rate="22"):
    """One document of the world. `lines`: (n, description, source total, category, how)."""
    INVOICES.append(
        {
            "step": step, "supplier": supplier, "number": number, "date": day, "kind": kind,
            "type_code": type_code, "fmt": fmt, "method": method, "spelling": spelling,
            "headline": headline, "net_given": net_given, "tax_given": tax_given,
            "gross_given": gross_given, "due": due, "rate": rate, "lines": lines,
        }
    )


def L(n, desc, total, category, how, *, qty=None, unit=None, price=None):
    return {"n": n, "desc": desc, "total": Fraction(total), "category": category, "how": how,
            "qty": None if qty is None else Fraction(qty), "unit": unit,
            "price": None if price is None else Fraction(price)}


XML = "FATTURAPA_XML"
CSV = "CSV"
XLSX = "XLSX"
LAUNDRY_LINES = lambda a, b, c: [  # noqa: E731 - three lines of a laundry invoice
    L(1, "Servizio lavanderia biancheria camere", a, "LAUNDRY", RULE),
    L(2, "Noleggio biancheria ospiti", b, "LAUNDRY", RULE),
    L(3, "Trasporto e ritiro", c, "OTHER", NONE),
]


def build_world() -> None:
    INVOICES.clear()
    # Step 1 - one multi-body XML of Lavanderia Salentina (5 invoices and 1 credit note)
    inv = dict(step=1, supplier="S1", fmt=XML, method="CREATED_NEW", spelling="Lavanderia Salentina S.r.l.")
    invoice(**inv, number="LS/2026/001", day="2026-01-31", due=["2026-03-02"],
            lines=[L(1, "Servizio lavanderia biancheria camere", "300.00", "LAUNDRY", RULE,
                     qty=120, unit="kg", price="2.5"),
                   L(2, "Noleggio biancheria ospiti", "85.00", "LAUNDRY", RULE),
                   L(3, "Trasporto e ritiro", "25.00", "OTHER", NONE)])
    invoice(**inv, number="LS/2026/002", day="2026-02-28", due=["2026-04-01"],
            lines=[L(1, "Servizio lavanderia biancheria camere", "237.50", "LAUNDRY", RULE,
                     qty=95, unit="kg", price="2.5"),
                   L(2, "Noleggio biancheria ospiti", "85.00", "LAUNDRY", RULE),
                   L(3, "Trasporto e ritiro", "25.00", "OTHER", NONE)])
    invoice(**inv, number="LS/2026/003", day="2026-03-31", due=["2026-05-01", "2026-06-01"],
            lines=[L(1, "Servizio lavanderia biancheria camere", "350.00", "LAUNDRY", RULE,
                     qty=140, unit="kg", price="2.5"),
                   L(2, "Noleggio biancheria ospiti", "85.00", "LAUNDRY", RULE),
                   # 3 x 12.335 = 37.005: the canonical amount is 37.01 (half up, once)
                   L(3, "Trasporto e ritiro straordinario", "37.005", "OTHER", NONE,
                     qty=3, unit="pz", price="12.335")])
    invoice(**inv, number="LS/2026/004", day="2026-04-30", due=["2026-06-01"], gross_given=True,
            lines=LAUNDRY_LINES("400.00", "85.00", "25.00"))
    invoice(**inv, number="NC/2026/001", day="2026-04-15", kind="CREDIT_NOTE", type_code="TD04",
            gross_given=True, due=None,
            lines=[L(1, "Storno lavanderia biancheria camere (reclamo)", "62.50", "LAUNDRY", RULE),
                   L(2, "Storno noleggio biancheria ospiti", "20.00", "LAUNDRY", RULE),
                   L(3, "Storno trasporto", "10.00", "OTHER", NONE)])
    invoice(**inv, number="LS/2026/005", day="2026-05-31", due=["2026-07-01"],
            lines=LAUNDRY_LINES("525.00", "85.00", "25.00"))
    # Step 2 - Energia Puglia (4 invoices)
    inv = dict(step=2, supplier="S2", fmt=XML, method="CREATED_NEW", spelling="Energia Puglia S.p.A.")
    for number, day, a, b, c, period in (
        ("EP/2026/0201", "2026-02-28", "1520.40", "812.35", "356.10", "gennaio-febbraio"),
        ("EP/2026/0404", "2026-04-30", "1610.75", "640.20", "361.55", "marzo-aprile"),
        ("EP/2026/0606", "2026-06-30", "1985.10", "233.05", "402.30", "maggio-giugno"),
    ):
        invoice(**inv, number=number, day=day, due=[day],
                lines=[L(1, f"Fornitura energia elettrica {period}", a, "UTILITIES", RULE),
                       L(2, f"Fornitura gas naturale {period}", b, "UTILITIES", RULE),
                       L(3, "Oneri di sistema e imposte", c, "OTHER", NONE)])
    invoice(**inv, number="EP/2026/0203", day="2026-03-15", due=["2026-03-15"],
            lines=[L(1, "Conguaglio energia elettrica", "118.90", "UTILITIES", RULE),
                   L(2, "Conguaglio oneri", "12.40", "OTHER", NONE),
                   L(3, "Diritti di segreteria", "5.00", "OTHER", NONE)])
    # Step 3 - Agrifood Murgia (3 invoices; VAT number and tax code)
    inv = dict(step=3, supplier="S3", fmt=XML, method="CREATED_NEW", spelling="Agrifood Murgia S.r.l.",
               rate="10")
    invoice(**inv, number="AM/2026/011", day="2026-01-20",
            lines=[L(1, "Olio extravergine di oliva 5 lt", "933.60", "OTHER", NONE, qty=24, unit="pz", price="38.9"),
                   L(2, "Farina di grano duro 25 kg", "214.50", "OTHER", NONE, qty=10, unit="pz", price="21.45")])
    invoice(**inv, number="AM/2026/031", day="2026-03-12",
            lines=[L(1, "Pasta artigianale 500 g", "370.00", "OTHER", NONE, qty=200, unit="pz", price="1.85"),
                   L(2, "Passata di pomodoro", "134.40", "OTHER", NONE, qty=120, unit="pz", price="1.12")])
    invoice(**inv, number="AM/2026/052", day="2026-05-22",
            lines=[L(1, "Vino rosso 0,75 l", "705.60", "OTHER", NONE, qty=96, unit="pz", price="7.35"),
                   L(2, "Acqua minerale", "93.00", "OTHER", NONE, qty=300, unit="pz", price="0.31")])
    # Step 4 - the same VAT number, another spelling (resolved by VAT; S1 has a default by now)
    inv = dict(step=4, supplier="S1", fmt=XML, method="VAT_NUMBER", spelling=S1_VARIANT)
    invoice(**inv, number="LS/2026/006", day="2026-06-15",
            lines=[L(1, "Servizio mensile", "480.00", "LAUNDRY", DEFAULT),
                   L(2, "Servizio straordinario", "95.00", "LAUNDRY", DEFAULT)])
    invoice(**inv, number="LS/2026/007", day="2026-06-30",
            lines=[L(1, "Servizio mensile", "505.00", "LAUNDRY", DEFAULT),
                   L(2, "Consegna extra", "40.00", "LAUNDRY", DEFAULT)])
    # Step 5 - no VAT number at all, only the bank account (resolved by the IBAN hash)
    invoice(step=5, supplier="S1", number="LS/2026/008", day="2026-06-20", fmt=XML,
            method="IBAN_SHA256", spelling=S1_IBAN_ONLY, due=["2026-07-20"],
            lines=[L(1, "Ritiro e lavaggio", "210.00", "LAUNDRY", DEFAULT),
                   L(2, "Igienizzazione", "60.00", "LAUNDRY", DEFAULT)])
    # Step 6 - the structured Italian CSV (Software Salento, Bianchi Laura, Trasporti Rapidi)
    inv = dict(step=6, fmt=CSV, method="CREATED_NEW", tax_given=False)
    invoice(**inv, supplier="S4", spelling="Software Salento S.r.l.", number="SS-101", day="2026-01-10",
            lines=[L(1, "Licenza software gestionale annuale", "1200.00", "SOFTWARE", RULE),
                   L(2, "Canone SaaS channel manager", "360.00", "SOFTWARE", EXPLICIT)])
    invoice(**inv, supplier="S4", spelling="Software Salento S.r.l.", number="SS-102", day="2026-04-10",
            lines=[L(1, "Assistenza software", "240.00", "SOFTWARE", RULE)])
    invoice(**inv, supplier="S5", spelling="Bianchi Laura", number="BL-12", day="2026-02-05",
            lines=[L(1, "Consulenza contabile mensile", "400.00", "PROFESSIONAL_SERVICES", EXPLICIT),
                   L(2, "Elaborazione paghe", "150.00", "PROFESSIONAL_SERVICES", EXPLICIT)])
    invoice(**inv, supplier="S5", spelling="Bianchi Laura", number="BL-19", day="2026-05-05",
            lines=[L(1, "Consulenza contabile mensile", "400.00", "PROFESSIONAL_SERVICES", EXPLICIT)])
    invoice(**inv, supplier="S6", spelling="Trasporti Rapidi S.n.c.", number="TR-77", day="2026-03-03",
            lines=[L(1, "Trasporto ospiti aeroporto", "90.00", "TRANSPORT", EXPLICIT),
                   L(2, "Trasporto bagagli", "45.50", "TRANSPORT", EXPLICIT),
                   L(3, "Supplemento notturno", "20.00", "TRANSPORT", EXPLICIT)])
    invoice(**inv, supplier="S6", spelling="Trasporti Rapidi S.n.c.", number="TR-78", day="2026-03-18",
            lines=[L(1, "Transfer stazione", "60.00", "TRANSPORT", EXPLICIT),
                   L(2, "Attesa", "15.00", "TRANSPORT", EXPLICIT)])
    invoice(**inv, supplier="S6", spelling="Trasporti Rapidi S.n.c.", number="TR-NC-1", day="2026-04-02",
            kind="CREDIT_NOTE", type_code="Nota di credito", headline="positive",
            lines=[L(1, "Storno transfer stazione", "60.00", "TRANSPORT", EXPLICIT)])
    invoice(**inv, supplier="S6", spelling="Trasporti Rapidi S.n.c.", number="TR-NC-2", day="2026-05-02",
            kind="CREDIT_NOTE", type_code="Nota di credito", headline="negative",
            lines=[L(1, "Storno attesa", "-15.00", "TRANSPORT", EXPLICIT)])
    # Step 7 - a name close to Agrifood Murgia, no identifier: a NEW supplier and a review
    invoice(step=7, supplier="S7", number="AMS/2026/1", day="2026-06-05", fmt=XML,
            method="CREATED_NEW_WITH_REVIEW", spelling="Agrifood Murgia Sud S.r.l.", rate="10",
            lines=[L(1, "Verdure fresche di stagione", "184.70", "OTHER", NONE),
                   L(2, "Frutta di stagione", "96.30", "OTHER", NONE)])
    # Step 8 - the structured XLSX of a second data source
    inv = dict(step=8, fmt=XLSX, net_given=False)
    invoice(**inv, supplier="S3", spelling="Agrifood Murgia S.r.l.", method="EXACT_NAME",
            number="AM-501", day="2026-06-08",
            lines=[L(1, "Olio extravergine di oliva 5 lt", "421.20", "FOOD", DEFAULT),
                   L(2, "Passata di pomodoro", "67.20", "FOOD", DEFAULT)])
    invoice(**inv, supplier="S5", spelling=S5_VARIANT, method="TAX_CODE", number="BL-24", day="2026-06-12",
            lines=[L(1, "Consulenza contabile mensile", "400.00", "PROFESSIONAL_SERVICES", EXPLICIT)])
    invoice(**inv, supplier="S1", spelling=S1_IBAN_ONLY, method="EXACT_ALIAS", number="LS-XLS-1",
            day="2026-06-28", lines=[L(1, "Lavaggio straordinario", "88.00", "LAUNDRY", DEFAULT)])
    invoice(**inv, supplier="S9", spelling="Nuovo Fornitore Ospitalità S.r.l.", method="CREATED_NEW",
            number="NF-1", day="2026-06-15",
            lines=[L(1, "Materiale vario", "149.90", "OTHER", NONE)])


# --- canonical (expected) values of the world ----------------------------------------------------------------


def source_sum(doc: dict) -> Fraction:
    return sum((line["total"] for line in doc["lines"]), Fraction(0))


def canonical(doc: dict) -> dict:
    """The stored form of a document, from the world's own rules (sign, half up once)."""
    net_src = half_up_2(source_sum(doc))
    tax_src = half_up_2(net_src * Fraction(doc["rate"]) / 100)
    gross_src = net_src + tax_src
    headline = gross_src if doc["gross_given"] else net_src if doc["net_given"] else source_sum(doc)
    sign = 1
    if doc["kind"] == "CREDIT_NOTE" and headline > 0:
        sign = -1  # written positive: a credit note is stored negative
    if doc["fmt"] == XML:  # an XML always states the VAT summary (net and tax)
        net, tax = half_up_2(net_src * sign), half_up_2(tax_src * sign)
    else:
        net = half_up_2(net_src * sign) if doc["net_given"] else None
        tax = None
    gross = half_up_2(gross_src * sign) if doc["gross_given"] else None
    if doc["fmt"] == XML:
        type_code = doc["type_code"]
    elif doc["fmt"] == CSV:  # the raw label of the file's type column
        type_code = doc["type_code"] if doc["type_code"] != "TD01" else "Fattura"
    else:  # the XLSX has no type column
        type_code = None
    lines = [
        {
            "n": line["n"] if doc["fmt"] == XML else line["row"],
            "description": line["desc"],
            "total": money(half_up_2(line["total"] * sign)),
            "category": line["category"],
            "method": line["how"],
            "confidence": CONF[line["how"]],
        }
        for line in doc["lines"]
    ]
    return {
        "supplier": doc["supplier"],
        "number": doc["number"],
        "normalized_number": " ".join(doc["number"].upper().split()),
        "date": doc["date"],
        "kind": doc["kind"],
        "type_code": type_code,
        "source_format": doc["fmt"],
        "resolution_method": doc["method"],
        "due_date": doc["due"][0] if doc["due"] and len(set(doc["due"])) == 1 else None,
        "net": None if net is None else money(net),
        "tax": None if tax is None else money(tax),
        "gross": None if gross is None else money(gross),
        "lines": lines,
    }


def golden_files() -> dict[str, str]:
    """The five XML files, the Italian CSV and the rows of the XLSX, in import order."""
    files: dict[str, str] = {}
    by_step: dict[int, list[dict]] = {}
    for doc in INVOICES:
        by_step.setdefault(doc["step"], []).append(doc)

    def xml_bodies(docs: list[dict], iban: str | None) -> list[dict]:
        bodies = []
        for doc in docs:
            payments = [(due, iban, doc["spelling"]) for due in doc["due"]] if doc["due"] else []
            bodies.append(
                {
                    "type": doc["type_code"], "date": doc["date"], "number": doc["number"],
                    "gross": doc["gross_given"], "rate": doc["rate"], "payments": payments,
                    "lines": [
                        (l["n"], l["desc"], l["qty"], l["unit"], l["price"], l["total"],
                         money(Fraction(doc["rate"])))
                        for l in doc["lines"]
                    ],
                }
            )
        return bodies

    def cedente(key: str, spelling: str, *, with_vat: bool = True) -> dict:
        data = SUPPLIERS[key]
        result: dict = {"name": spelling}
        if with_vat and "vat" in data:
            result["vat"] = data["vat"]
        if with_vat and "tax" in data:
            result["tax"] = data["tax"]
        return result

    names = {
        1: "masseria_ninfa_cost_01_lavanderia_multi_body.xml",
        2: "masseria_ninfa_cost_02_energia.xml",
        3: "masseria_ninfa_cost_03_agrifood.xml",
        4: "masseria_ninfa_cost_04_lavanderia_other_spelling.xml",
        5: "masseria_ninfa_cost_05_lavanderia_iban_only.xml",
        7: "masseria_ninfa_cost_07_agrifood_sud.xml",
    }
    for step, name in names.items():
        docs = by_step[step]
        supplier = docs[0]["supplier"]
        spelling = docs[0]["spelling"]
        iban = SUPPLIERS[supplier]["ibans"][0] if SUPPLIERS[supplier]["ibans"] else None
        no_vat = step == 5
        files[name] = fattura(
            cedente(supplier, spelling, with_vat=not no_vat), xml_bodies(docs, iban)
        )
    # the Italian CSV (step 6)
    rows = [["Fornitore", "P.IVA", "Codice Fiscale", "IBAN", "Numero Fattura", "Data", "Tipo",
             "Descrizione", "Importo", "Categoria", "Imponibile", "Riferimento cliente"]]
    labels = {"SOFTWARE": "Canone", "PROFESSIONAL_SERVICES": "Consulenza", "TRANSPORT": "Trasporto"}
    for doc in by_step[6]:
        data = SUPPLIERS[doc["supplier"]]
        net = it_number(half_up_2(source_sum(doc)))
        y, m, d = doc["date"].split("-")
        for line in doc["lines"]:
            rows.append([
                doc["spelling"], data.get("vat", ""), data.get("tax", ""),
                data["ibans"][0] if data["ibans"] else "", doc["number"], f"{d}/{m}/{y}",
                "Nota di credito" if doc["kind"] == "CREDIT_NOTE" else "Fattura",
                line["desc"], it_number(line["total"]),
                labels.get(line["category"], "") if line["how"] == EXPLICIT else "",
                net, "Rif. cliente riservato",
            ])
    files["masseria_ninfa_cost_06_structured.csv"] = csv_text(rows, ";")
    # the rows of the XLSX (step 8): ISO dates and dot decimals; the test writes typed cells
    rows = [["Supplier", "VAT", "Tax Code", "Invoice No", "Invoice Date", "Description",
             "Line Total", "Category"]]
    for doc in by_step[8]:
        data = SUPPLIERS[doc["supplier"]]
        with_ids = doc["method"] in {"CREATED_NEW", "TAX_CODE"}  # the others carry no identifier
        for line in doc["lines"]:
            rows.append([
                doc["spelling"], data.get("vat", "") if with_ids else "",
                data.get("tax", "") if with_ids and doc["supplier"] == "S5" else "",
                doc["number"], doc["date"], line["desc"], money(line["total"]),
                "Consulenza" if line["how"] == EXPLICIT else "",
            ])
    files["masseria_ninfa_cost_08_xlsx_rows.csv"] = csv_text(rows, ",")
    return files


def number_rows() -> None:
    """A structured file without a line-number column numbers its lines by spreadsheet row: the
    header is row 1, the first data row is 2 (the world writes the rows in this order)."""
    for step in (6, 8):
        row = 2
        for doc in (d for d in INVOICES if d["step"] == step):
            for line in doc["lines"]:
                line["row"] = row
                row += 1


def expected() -> dict:
    build_world()
    number_rows()
    invoices = [canonical(doc) for doc in INVOICES]
    # suppliers
    aliases: dict[str, set[str]] = {key: {norm_name(data["name"])} for key, data in SUPPLIERS.items()}
    for doc in INVOICES:
        if doc["method"] in {"VAT_NUMBER", "IBAN_SHA256", "TAX_CODE"}:
            aliases[doc["supplier"]].add(norm_name(doc["spelling"]))
    suppliers = []
    for key, data in SUPPLIERS.items():
        identifiers = []
        if "vat" in data:
            identifiers.append(["VAT_NUMBER", "IT" + data["vat"]])
        if "tax" in data:
            identifiers.append(["TAX_CODE", data["tax"]])
        for iban in data["ibans"]:
            identifiers.append(["IBAN_SHA256", hashlib.sha256(iban.encode()).hexdigest()])
        suppliers.append(
            {
                "key": key,
                "legal_name": data["name"],
                "normalized_name": norm_name(data["name"]),
                "country": data.get("country", "IT"),
                "identifiers": sorted(identifiers),
                "aliases": sorted(aliases[key]),
                "default_cost_category": {"S1": "LAUNDRY", "S3": "FOOD"}.get(key),
                "is_verified": False,
            }
        )
    # the only near-duplicate the world contains (checked below)
    reviews = [
        {
            "provisional": "S7",
            "candidate": "S3",
            "reason": "FUZZY_NAME_SIMILARITY",
            "similarity": similarity(norm_name(SUPPLIERS["S7"]["name"]), norm_name(SUPPLIERS["S3"]["name"])),
            "status": "PENDING",
        }
    ]
    # design check: no other pair of supplier names (or spellings) is close enough to be proposed
    names = {key: norm_name(data["name"]) for key, data in SUPPLIERS.items()}
    keys = list(names)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            close = float(similarity(names[a], names[b])) >= 0.85
            assert close == ({a, b} == {"S3", "S7"}), (a, b)

    def total(selector) -> dict[str, str]:
        sums: dict[str, Fraction] = {}
        for inv, doc in zip(invoices, INVOICES):
            for line in inv["lines"]:
                key = selector(inv, doc, line)
                sums[key] = sums.get(key, Fraction(0)) + Fraction(line["total"])
        return {key: money(sums[key]) for key in sorted(sums)}

    all_lines = [line for inv in invoices for line in inv["lines"]]
    aggregates = {
        "invoice_count": len(invoices),
        "line_count": len(all_lines),
        "supplier_count": len(suppliers),
        "credit_note_count": sum(1 for inv in invoices if inv["kind"] == "CREDIT_NOTE"),
        "line_total_sum": money(sum((Fraction(l["total"]) for l in all_lines), Fraction(0))),
        "credit_note_line_total_sum": money(
            sum((Fraction(l["total"]) for inv in invoices if inv["kind"] == "CREDIT_NOTE"
                 for l in inv["lines"]), Fraction(0))
        ),
        "by_month": total(lambda inv, doc, line: inv["date"][:7]),
        "by_category": total(lambda inv, doc, line: line["category"]),
        "by_supplier": total(lambda inv, doc, line: inv["supplier"]),
        "by_method": total(lambda inv, doc, line: line["method"]),
        "invoices_by_format": {
            fmt: sum(1 for inv in invoices if inv["source_format"] == fmt) for fmt in (XML, CSV, XLSX)
        },
        "invoices_by_resolution_method": {
            method: sum(1 for inv in invoices if inv["resolution_method"] == method)
            for method in sorted({inv["resolution_method"] for inv in invoices})
        },
        "other_lines": sum(1 for l in all_lines if l["category"] == "OTHER"),
    }
    steps = [
        {"step": 1, "file": "masseria_ninfa_cost_01_lavanderia_multi_body.xml", "source": "A",
         "documents": 6, "rows": 18, "invoices_created": 6, "lines_created": 18,
         "suppliers_created": 1, "suppliers_matched": 0, "identifiers_added": 0, "aliases_added": 0,
         "reviews_created": 0, "warnings": {"MULTIPLE_PAYMENT_DUE_DATES": 1},
         "after": {"set_default": {"supplier": "S1", "category": "LAUNDRY"}}},
        {"step": 2, "file": "masseria_ninfa_cost_02_energia.xml", "source": "A", "documents": 4,
         "rows": 12, "invoices_created": 4, "lines_created": 12, "suppliers_created": 1,
         "suppliers_matched": 0, "identifiers_added": 0, "aliases_added": 0, "reviews_created": 0,
         "warnings": {}},
        {"step": 3, "file": "masseria_ninfa_cost_03_agrifood.xml", "source": "A", "documents": 3,
         "rows": 6, "invoices_created": 3, "lines_created": 6, "suppliers_created": 1,
         "suppliers_matched": 0, "identifiers_added": 0, "aliases_added": 0, "reviews_created": 0,
         "warnings": {}, "after": {"set_default": {"supplier": "S3", "category": "FOOD"}}},
        {"step": 4, "file": "masseria_ninfa_cost_04_lavanderia_other_spelling.xml", "source": "A",
         "documents": 2, "rows": 4, "invoices_created": 2, "lines_created": 4, "suppliers_created": 0,
         "suppliers_matched": 1, "identifiers_added": 0, "aliases_added": 1, "reviews_created": 0,
         "warnings": {}},
        {"step": 5, "file": "masseria_ninfa_cost_05_lavanderia_iban_only.xml", "source": "A",
         "documents": 1, "rows": 2, "invoices_created": 1, "lines_created": 2, "suppliers_created": 0,
         "suppliers_matched": 1, "identifiers_added": 0, "aliases_added": 1, "reviews_created": 0,
         "warnings": {}},
        {"step": 6, "file": "masseria_ninfa_cost_06_structured.csv", "source": "A", "documents": 8,
         "rows": 13, "invoices_created": 8, "lines_created": 13, "suppliers_created": 3,
         "suppliers_matched": 0, "identifiers_added": 0, "aliases_added": 0, "reviews_created": 0,
         "warnings": {}},
        {"step": 7, "file": "masseria_ninfa_cost_07_agrifood_sud.xml", "source": "A", "documents": 1,
         "rows": 2, "invoices_created": 1, "lines_created": 2, "suppliers_created": 1,
         "suppliers_matched": 0, "identifiers_added": 0, "aliases_added": 0, "reviews_created": 1,
         "warnings": {}},
        {"step": 8, "file": "masseria_ninfa_cost_08_xlsx_rows.csv", "source": "B", "documents": 4,
         "rows": 5, "invoices_created": 4, "lines_created": 5, "suppliers_created": 1,
         "suppliers_matched": 3, "identifiers_added": 0, "aliases_added": 1, "reviews_created": 0,
         "warnings": {}},
    ]
    ordered = sorted(invoices, key=lambda item: (item["date"], item["number"], item["supplier"]))
    canonical_json = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "world": "MASSERIA NINFA DEMO — COST DATA V1",
        "note": "Computed independently of the application (see the generator's docstring).",
        "sources": {
            "A": "COSTS data source with the Italian CSV mapping (XML needs none)",
            "B": "COSTS data source with the English XLSX mapping",
        },
        "csv_mapping": {
            "category_mapping": {"Canone": "SOFTWARE", "Consulenza": "PROFESSIONAL_SERVICES",
                                 "Trasporto": "TRANSPORT"},
        },
        "steps": steps,
        "suppliers": suppliers,
        "reviews": reviews,
        "invoices": invoices,
        "aggregates": aggregates,
        "invoices_sha256": hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        "iban_sha256": {
            "A": hashlib.sha256(IBAN_A.encode()).hexdigest(),
            "B": hashlib.sha256(IBAN_B.encode()).hexdigest(),
            "C": hashlib.sha256(IBAN_C.encode()).hexdigest(),
        },
        "raw_ibans_never_stored": [IBAN_A, IBAN_B, IBAN_C],
        "private_values_never_stored": [
            RECIPIENT, RECIPIENT_TAX, SUPPLIER_EMAIL, SUPPLIER_PHONE, SUPPLIER_STREET,
            "Rif. cliente riservato", "cliente-pec@example.com",
        ],
    }


def main() -> None:
    for name, content in xml_fixtures().items():
        write(XML_DIR / name, content)
    for name, data in structured_fixtures().items():
        write(STRUCTURED_DIR / name, data)
    result = expected()
    for name, content in golden_files().items():
        write(GOLDEN_DIR / name, content)
    write(EXPECTED, json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(
        f"invoices={result['aggregates']['invoice_count']} lines={result['aggregates']['line_count']}"
        f" suppliers={result['aggregates']['supplier_count']} sha256={result['invoices_sha256'][:16]}"
    )


if __name__ == "__main__":
    main()

"""Documents NINFA must NOT import automatically, and files it cannot read at all.

NEGATIVE (27): real spreadsheets of a hotel's office that are none of bookings, staff or costs -
inventory, a trial balance, restaurant sales, a marketing report, web analytics, a contact list, a
shopping list, a workbook of rules - uploaded on each of the three cards. Several share a word or a
shape with a real domain on purpose ("Fornitore", "Canale", "Costo", a date, a status): a
word is not evidence. The right answer is never an automatic import (a question, the
matching screen or a refusal are all fine).

UNSUPPORTED (12): files that are not a readable .csv / .xlsx (a PDF, plain text, an old .xls,
a macro workbook, UTF-16 text, an empty file, a broken archive, a workbook renamed .csv...).
The right answer is a clean refusal: no exception, no import.
"""

import random
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.draw import Sheet, sheet_csv, write_table, xlsx_bytes
from tests.benchmarks.smart_import_v3.kit import Built, facts, pii, structure_of
from tests.benchmarks.smart_import_v3.model import Doc, Golden
from tests.benchmarks.smart_import_v3.pool import email_of, guest, guest_name, phone_of
from tests.benchmarks.universal_understanding_v2.common import rng_of

CARDS = ("bookings", "labor", "costs")


def _golden(domain: str = "other", outcome: str = "REJECT", **more: Any) -> Golden:
    return Golden(domain, outcome, **more)


def _table(
    rng: random.Random,
    filename: str,
    header: Sequence[str],
    body: list[list[Any]],
    *,
    title: str | None = None,
    note: str,
    as_csv: bool = False,
    personal: tuple[Sequence[str], Sequence[str]] | None = None,
) -> Built:
    sheet = Sheet(rng.choice(("Foglio1", "Dati", "Export", "Report")))
    if title:
        sheet.title_line(title, len(header))
        sheet.blank()
    ref = write_table(sheet, list(header), body)
    extra: dict[str, Any] = {}
    if personal is not None:
        extra = pii([(h,) for h in personal[0]], personal[1])
    golden = _golden(**facts(ref, csv=as_csv), note=note, **extra)
    if as_csv:
        return Built(filename, sheet_csv(sheet, delimiter=";", decimal=","), golden, [sheet])
    return Built(filename, xlsx_bytes([sheet]), golden, [sheet])


def _days(rng: random.Random, count: int, start: date = date(2026, 10, 1)) -> list[datetime]:
    return [
        datetime.combine(start + timedelta(days=i + rng.randint(0, 1)), datetime.min.time())
        for i in range(count)
    ]


def inventory(rng: random.Random) -> Built:
    articles = (
        "Lenzuola matrimoniali",
        "Asciugamani viso",
        "Detersivo pavimenti",
        "Shampoo 30ml",
        "Caffè in cialde",
    )
    body = [
        [
            f"ART-{1000 + i}",
            rng.choice(articles),
            rng.randint(0, 400),
            rng.choice(("pz", "kg", "lt")),
            round(rng.uniform(0.4, 38), 2),
            rng.choice(("Alfa Forniture", "Bianchi Srl", "Gamma Hotel Supply")),
            rng.randint(10, 80),
        ]
        for i in range(rng.randint(14, 24))
    ]
    return _table(
        rng,
        "inventario_magazzino.xlsx",
        [
            "Codice articolo",
            "Articolo",
            "Giacenza",
            "UM",
            "Prezzo acquisto",
            "Fornitore",
            "Scorta minima",
        ],
        body,
        title="INVENTARIO MAGAZZINO",
        note="A stock list: a supplier and a price, but no invoice and no date.",
    )


def trial_balance(rng: random.Random) -> Built:
    accounts = (
        ("310.010", "Acquisti materie prime"),
        ("310.020", "Energia elettrica"),
        ("410.001", "Ricavi camere"),
        ("410.002", "Ricavi ristorante"),
        ("220.100", "Debiti v/fornitori"),
        ("130.200", "Crediti v/clienti"),
    )
    body = [
        [code, name, round(rng.uniform(0, 90000), 2), round(rng.uniform(0, 90000), 2)]
        for code, name in accounts * rng.randint(2, 4)
    ]
    return _table(
        rng,
        "bilancio_di_verifica.xlsx",
        ["Conto", "Descrizione conto", "Dare", "Avere"],
        body,
        title="BILANCIO DI VERIFICA AL 30/09/2026",
        note="A trial balance: accounts with debit and credit, no document, no supplier.",
    )


def restaurant_sales(rng: random.Random) -> Built:
    body = [
        [
            day,
            rng.randint(25, 140),
            round(rng.uniform(900, 5200), 2),
            round(rng.uniform(22, 48), 2),
            round(rng.uniform(200, 1500), 2),
        ]
        for day in _days(rng, rng.randint(20, 30))
    ]
    return _table(
        rng,
        "incassi_ristorante.xlsx",
        ["Data", "Coperti", "Incasso", "Scontrino medio", "di cui bevande"],
        body,
        note="Daily restaurant takings: a date and amounts, no booking, no staff, no invoice.",
    )


def marketing_report(rng: random.Random) -> Built:
    body = [
        [
            f"CMP-{i + 1:03d}",
            rng.choice(("Google Ads", "Meta", "Newsletter", "Booking.com", "Metasearch")),
            rng.randint(2000, 90000),
            rng.randint(30, 4000),
            round(rng.uniform(0.4, 5.2), 2),
            round(rng.uniform(40, 1800), 2),
            rng.randint(0, 60),
        ]
        for i in range(rng.randint(12, 22))
    ]
    return _table(
        rng,
        "campagne_marketing.csv",
        ["Campagna", "Canale", "Impression", "Click", "CTR %", "Costo", "Conversioni"],
        body,
        note="A marketing report: a 'channel' and a 'cost' of ads, not bookings or invoices.",
        as_csv=True,
    )


def web_analytics(rng: random.Random) -> Built:
    pages = ("/camere", "/offerte", "/contatti", "/ristorante", "/prenota", "/spa", "/blog/estate")
    body = [
        [
            day,
            rng.choice(pages),
            rng.randint(20, 900),
            rng.randint(10, 700),
            round(rng.uniform(20, 80), 1),
            rng.choice(("organic", "cpc", "direct", "referral")),
        ]
        for day in _days(rng, rng.randint(18, 28))
    ]
    return _table(
        rng,
        "analytics_sito.xlsx",
        ["Data", "Pagina", "Sessioni", "Utenti", "Frequenza di rimbalzo %", "Fonte / Mezzo"],
        body,
        note="Web analytics: sessions per page and day. 'Fonte' is a traffic source.",
    )


def contact_list(rng: random.Random) -> Built:
    count = rng.randint(14, 24)
    names = [guest_name(i) for i in range(count)]
    emails = [email_of(*guest(i)) for i in range(count)]
    phones = [phone_of(i) for i in range(count)]
    body = [
        [
            names[i],
            emails[i],
            phones[i],
            rng.choice(("Alfa Srl", "Studio Rossi", "Hotel Aurora")),
            rng.choice(("Roma", "Milano", "Torino")),
        ]
        for i in range(count)
    ]
    return _table(
        rng,
        "rubrica_contatti.xlsx",
        ["Nominativo", "E-mail", "Telefono", "Azienda", "Città"],
        body,
        note="An address book: personal data and nothing NINFA needs.",
        personal=(["Nominativo", "E-mail", "Telefono"], [*names, *emails, *phones]),
    )


def todo_sheet(rng: random.Random) -> Built:
    tasks = (
        "Ordinare lenzuola",
        "Chiamare il tecnico caldaia",
        "Aggiornare il sito",
        "Verificare estintori",
        "Preparare menù natalizio",
    )
    body = [
        [
            rng.choice(tasks),
            rng.choice(("Marta", "Luca", "Giulia", "Paolo")),
            day,
            rng.choice(("Da fare", "In corso", "Fatto")),
            rng.choice(("alta", "media", "bassa")),
        ]
        for day in _days(rng, rng.randint(10, 18), start=date(2026, 10, 26))
    ]
    return _table(
        rng,
        "attivita_da_fare.xlsx",
        ["Attività", "Responsabile", "Scadenza", "Stato", "Priorità"],
        body,
        note="A to-do list: a status and a due date, nothing to import.",
    )


def rules_workbook(rng: random.Random) -> Built:
    first = Sheet("Regolamento")
    first.title_line("REGOLAMENTO INTERNO DELL'ALBERGO", 1)
    for number in range(1, rng.randint(8, 14)):
        first.add(
            [
                f"Art. {number}. "
                + "Il personale è tenuto al rispetto degli orari e delle procedure. "
                * rng.randint(2, 4)
            ]
        )
    second = Sheet("Procedure")
    for number in range(1, rng.randint(6, 10)):
        second.add(
            [
                f"Procedura {number}: "
                + "Verificare, registrare e comunicare al responsabile di turno. " * 3
            ]
        )
    golden = _golden(note="Paragraphs of text on two sheets: no table at all.")
    return Built("regolamento_procedure.xlsx", xlsx_bytes([first, second]), golden, [first, second])


def costs_like_menu(rng: random.Random) -> Built:
    body = [
        [
            rng.choice(("Antipasti", "Primi", "Secondi", "Dolci", "Bevande")),
            f"Piatto {i}",
            round(rng.uniform(4, 38), 2),
            rng.randint(0, 40),
        ]
        for i in range(rng.randint(14, 22))
    ]
    return _table(
        rng,
        "menu_listino.xlsx",
        ["Categoria", "Descrizione", "Prezzo", "Venduti"],
        body,
        title="LISTINO RISTORANTE",
        note="A price list: a category, a description and an amount, but no supplier or invoice.",
    )


NEGATIVE_RECIPES: tuple[Callable[[random.Random], Built], ...] = (
    inventory,
    trial_balance,
    restaurant_sales,
    marketing_report,
    web_analytics,
    contact_list,
    todo_sheet,
    rules_workbook,
    costs_like_menu,
)


def build_negative() -> list[Doc]:
    """3 uploads (one per card) of each of 9 recipes: 27 documents."""
    docs: list[Doc] = []
    number = 0
    for maker in NEGATIVE_RECIPES:
        for card in CARDS:
            number += 1
            case_id = f"UN{number:03d}_negative_{maker.__name__}_{card}"
            built = maker(rng_of(case_id))
            docs.append(
                Doc(
                    id=case_id,
                    card=card,
                    filename=built.filename,
                    content=built.content,
                    golden=built.golden,
                    tags=(
                        "negative",
                        f"recipe:{maker.__name__}",
                        "csv" if built.filename.endswith(".csv") else "xlsx",
                        "unseen",
                    ),
                    structure=structure_of(built),
                    sheet_count=max(1, len(built.sheets)),
                )
            )
    return docs


# --- files that cannot be read --------------------------------------------------------------------


PIPE_BOOKINGS = (
    ("Codice", "Prenotata il", "Arrivo", "Partenza", "Canale", "Ricavo camere"),
    ("BK1001", "2026-09-01", "2026-10-02", "2026-10-04", "Booking.com", "240.00"),
    ("BK1002", "2026-09-03", "2026-10-05", "2026-10-06", "Diretto", "120.00"),
    ("BK1003", "2026-09-07", "2026-10-09", "2026-10-12", "Expedia", "390.00"),
)
PIPE_LABOR = (
    ("Data", "Reparto", "Ore previste", "Ore effettive"),
    ("2026-10-05", "Sala", "8", "8"),
    ("2026-10-05", "Cucina", "7", "7.5"),
    ("2026-10-06", "Reception", "8", "8"),
)
PIPE_COSTS = (
    ("Fornitore", "Fattura n.", "Data", "Descrizione", "Imponibile"),
    ("Alfa Srl", "FT/001", "2026-10-02", "Forniture", "310.00"),
    ("Beta Spa", "FT/118", "2026-10-03", "Pulizie", "540.00"),
    ("Gamma Srl", "FT/207", "2026-10-09", "Manutenzione", "128.00"),
)


def _pipe_file(rows: tuple[tuple[str, ...], ...]) -> bytes:
    return "\r\n".join("|".join(row) for row in rows).encode("utf-8")


def _unsupported() -> list[tuple[str, str, bytes]]:
    csv_text = "Data;Reparto;Ore\r\n01/10/2026;Sala;8\r\n02/10/2026;Bar;7\r\n"
    macro = Sheet("Foglio1")
    macro.title_line("MACRO DI PRENOTAZIONI", 3)
    macro.add(["Codice", "Arrivo", "Partenza"])
    one = Sheet("Foglio1")
    one.title_line("TITOLO SENZA DATI", 3)
    renamed = Sheet("Dati")
    renamed.add(["Reparto", "Ore"])
    renamed.add(["Sala", 8])
    return [
        ("report_pdf", "report.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
        (
            "plain_text",
            "note.txt",
            b"Promemoria per la reception\nNon dimenticare di chiamare il fornitore.\n",
        ),
        ("old_excel", "vecchio.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600),
        ("macro_workbook", "macro.xlsm", xlsx_bytes([macro])),
        ("utf16_csv", "utf16.csv", b"\xff\xfe" + csv_text.encode("utf-16-le")),
        ("empty_csv", "vuoto.csv", b""),
        ("only_a_title", "solo_titolo.xlsx", xlsx_bytes([one])),
        ("broken_archive", "danneggiato.xlsx", b"PK\x03\x04" + bytes(range(256)) * 4),
        ("workbook_renamed_csv", "dati.csv", xlsx_bytes([renamed])),
        (
            "encrypted_workbook",
            "protetto.xlsx",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            + b"\x00" * 200
            + b"EncryptedPackage"
            + b"\x00" * 400,
        ),
        (
            "html_saved_as_xls",
            "tabella.xls",
            b"<html><body><table><tr><td>Data</td></tr></table></body></html>",
        ),
        ("random_binary", "dump.csv", bytes(range(256)) * 8),
        ("pipe_bookings", "prenotazioni.csv", _pipe_file(PIPE_BOOKINGS)),
        ("pipe_staff", "turni.csv", _pipe_file(PIPE_LABOR)),
        ("pipe_costs", "fatture.csv", _pipe_file(PIPE_COSTS)),
    ]


def build_unsupported() -> list[Doc]:
    docs: list[Doc] = []
    for number, (slug, filename, content) in enumerate(_unsupported(), start=1):
        card = CARDS[number % 3]
        docs.append(
            Doc(
                id=f"UU{number:03d}_unsupported_{slug}",
                card=card,
                filename=filename,
                content=content,
                golden=_golden(note=f"{filename}: not a readable .csv / .xlsx table."),
                tags=(
                    "unsupported",
                    f"recipe:{slug}",
                    "xlsx" if filename.endswith("x") else "csv",
                    "unseen",
                ),
                structure=("unsupported",),
            )
        )
    return docs


__all__ = ["NEGATIVE_RECIPES", "build_negative", "build_unsupported"]

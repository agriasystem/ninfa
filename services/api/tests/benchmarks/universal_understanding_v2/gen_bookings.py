"""Unseen bookings documents: PMS and channel-manager exports, front-desk and revenue sheets.

120 documents (30 EASY, 40 MEDIUM, 30 HARD, 20 ADVERSARIAL). Headers are drawn from what hotels'
systems and hand-made sheets really write, in Italian and English, abbreviated, with units and
punctuation; the shape of the document and the way its values are written vary from one document to
the next. Guests are people: their names, e-mail addresses, phones and notes appear in many of these
files and must never be taken for something NINFA needs.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col, flat_document, headers, parts, records
from tests.benchmarks.smart_import_v3.draw import (
    Note,
    Sheet,
    Total,
    csv_bytes,
    write_table,
    xlsx_bytes,
)
from tests.benchmarks.smart_import_v3.kit import Built, facts
from tests.benchmarks.smart_import_v3.model import Doc, Golden, column
from tests.benchmarks.smart_import_v3.pool import email_of, guest, guest_name, phone_of
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
    stamp_cell,
)

# --- the data of a booking ------------------------------------------------------------------------

CHANNELS: dict[str, tuple[str, str]] = {
    "booking": ("Booking.com", "Booking.com"),
    "expedia": ("Expedia", "Expedia"),
    "website": ("Sito web", "Website"),
    "phone": ("Telefono", "Phone"),
    "direct": ("Diretto", "Direct"),
    "airbnb": ("Airbnb", "Airbnb"),
    "agency": ("Agenzia", "Travel agent"),
    "walkin": ("Walk-in", "Walk-in"),
    "email": ("Email", "E-mail"),
}
STATUS: dict[str, tuple[str, str]] = {
    "CONFIRMED": ("Confermata", "Confirmed"),
    "CANCELLED": ("Cancellata", "Cancelled"),
    "NO_SHOW": ("No show", "No-show"),
}
HOTELS = (
    "Hotel Belvedere",
    "Villa Serena",
    "Residence Mare Blu",
    "Albergo Il Poggio",
    "Grand Hotel Lido",
    "Hotel Alba Chiara",
)
SHEETS_IT = ("Prenotazioni", "Export", "Foglio1", "Report", "Arrivi", "Dati", "Elenco", "Ottobre")
SHEETS_EN = ("Reservations", "Export", "Sheet1", "Report", "Arrivals", "Data", "Bookings")
ROOM_TYPES = ("Doppia", "Matrimoniale", "Singola", "Family", "Suite")
PLANS = ("Flex", "Non rimborsabile", "B&B", "Mezza pensione")


@dataclass(frozen=True, slots=True)
class Stay:
    ref: Any
    booked: datetime
    arrival: date
    nights: int
    channel: str
    revenue: float
    status: str
    rooms: int
    guest: int
    pax: int
    room_type: str
    plan: str
    commission: float

    @property
    def departure(self) -> date:
        return self.arrival + timedelta(days=self.nights)

    def channel_label(self, lang: str) -> str:
        return CHANNELS[self.channel][0 if lang == "it" else 1]

    def status_label(self, lang: str) -> str:
        return STATUS[self.status][0 if lang == "it" else 1]


def make_ref(rng: random.Random, style: str, index: int) -> Any:
    if style == "bk":
        return f"BK{100000 + index * 37 + rng.randint(0, 30)}"
    if style == "slash":
        return f"2026/{index + 1:05d}"
    if style == "alnum":
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(rng.choice(letters) for _ in range(6))
    if style == "num10":
        return 4800000000 + index * 7919 + rng.randint(0, 99)
    if style == "res":
        return f"RES-26{index + 1:04d}"
    return f"CNF{9000000 + index * 13:07d}"


REF_STYLES = ("bk", "slash", "alnum", "num10", "res", "conf")


def stays(
    rng: random.Random,
    count: int,
    *,
    ref_style: str | None = None,
    start: date = date(2026, 10, 14),
    spread: int = 55,
    channels: Sequence[str] = tuple(CHANNELS),
    statuses: Sequence[str] = ("CONFIRMED",),
    first_index: int = 0,
) -> list[Stay]:
    style = ref_style or rng.choice(REF_STYLES)
    out: list[Stay] = []
    for index in range(count):
        arrival = start + timedelta(days=rng.randint(0, spread))
        nights = rng.choice((1, 2, 2, 3, 3, 4, 5, 7))
        rooms = rng.choice((1, 1, 1, 2))
        rate = rng.choice((69.0, 85.0, 99.0, 119.0, 139.0, 169.0, 219.0, 289.0))
        channel = rng.choice(list(channels))
        out.append(
            Stay(
                make_ref(rng, style, index + first_index),
                datetime.combine(arrival - timedelta(days=rng.randint(2, 80)), datetime.min.time())
                + timedelta(hours=rng.randint(6, 23), minutes=rng.randint(0, 59)),
                arrival,
                nights,
                channel,
                round(rate * nights * rooms, 2),
                rng.choice(list(statuses)),
                rooms,
                rng.randint(0, 400),
                rng.randint(1, 4),
                rng.choice(ROOM_TYPES),
                rng.choice(PLANS),
                0.0 if channel in {"direct", "phone", "website", "walkin", "email"} else 15.0,
            )
        )
    return out


# --- headers --------------------------------------------------------------------------------------

ID = (
    H("N. Prenotazione", "it"),
    H("Num. pren.", "it"),
    H("Cod. Pren.", "it"),
    H("Rif. prenotazione", "it"),
    H("Pratica n.", "it"),
    H("ID Prenotazione", "it"),
    H("Codice conferma", "it"),
    H("Localizzatore", "it"),
    H("Reservation No.", "en"),
    H("Res ID", "en"),
    H("Booking Ref", "en"),
    H("Confirmation #", "en"),
    H("Conf. No.", "en"),
    H("Booking Locator", "en"),
    H("Reservation Number", "en"),
)
BOOKED = (
    H("Data pren.", "it"),
    H("Prenotato il", "it"),
    H("Data creazione", "it"),
    H("Inserita il", "it"),
    H("Registrata il", "it"),
    H("Prenotata in data", "it"),
    H("Booking Date", "en"),
    H("Created", "en"),
    H("Created On", "en"),
    H("Booked On", "en"),
    H("Date Booked", "en"),
    H("Reservation Date", "en"),
)
STAY_PAIRS: tuple[tuple[H, H], ...] = (
    (H("Arr.", "any"), H("Part.", "any")),
    (H("Data arrivo", "it"), H("Data partenza", "it")),
    (H("Check-in", "any"), H("Check-out", "any")),
    (H("Check In", "any"), H("Check Out", "any")),
    (H("CI", "any"), H("CO", "any")),
    (H("Dal", "it"), H("Al", "it")),
    (H("Data ingresso", "it"), H("Data uscita", "it")),
    (H("Giorno arrivo", "it"), H("Giorno partenza", "it")),
    (H("Arrival", "en"), H("Departure", "en")),
    (H("Arrival Date", "en"), H("Departure Date", "en")),
    (H("Date of Arrival", "en"), H("Date of Departure", "en")),
    (H("Stay From", "en"), H("Stay To", "en")),
    (H("Arr. Date", "en"), H("Dep. Date", "en")),
)
STATUS_H = (
    H("Stato", "it"),
    H("Stato prenotazione", "it"),
    H("Stato pren.", "it"),
    H("Situazione prenotazione", "it"),
    H("Status", "en"),
    H("Reservation Status", "en"),
    H("Booking Status", "en"),
    H("Res. Status", "en"),
)
ROOMS = (
    H("N. camere", "it"),
    H("Camere", "it"),
    H("Nr. camere", "it"),
    H("Q.tà camere", "it"),
    H("Stanze", "it"),
    H("Camere prenotate", "it"),
    H("Rooms", "en"),
    H("No. of Rooms", "en"),
    H("Room Count", "en"),
    H("# Rooms", "en"),
    H("Rms", "en"),
    H("Rooms Booked", "en"),
)
REVENUE = (
    H("Ricavo camera", "it"),
    H("Importo camere", "it"),
    H("Ricavo soggiorno", "it"),
    H("Importo soggiorno", "it"),
    H("Incasso camere", "it"),
    H("Fatturato camere", "it"),
    H("Corrispettivo camere", "it"),
    H("Valore soggiorno", "it"),
    H("Room Revenue", "en"),
    H("Room Rev", "en"),
    H("Room Amount", "en"),
    H("Accommodation Revenue", "en"),
    H("Lodging Revenue", "en"),
    H("Revenue - Rooms", "en"),
    H("Room Charges", "en"),
)
CHANNEL_H = (
    H("Canale", "it"),
    H("Provenienza", "it"),
    H("Fonte", "it"),
    H("Origine", "it"),
    H("Portale", "it"),
    H("Canale di vendita", "it"),
    H("Prenotato tramite", "it"),
    H("Channel", "en"),
    H("Source", "en"),
    H("Booking Source", "en"),
    H("Sales Channel", "en"),
    H("Origin", "en"),
    H("Distribution Channel", "en"),
    H("Booked Via", "en"),
)
GUESTS_H = (
    H("Ospiti", "it"),
    H("N. persone", "it"),
    H("Pax", "any"),
    H("Persone", "it"),
    H("Guests", "en"),
    H("No. of Guests", "en"),
    H("Persons", "en"),
)
NIGHTS_H = (H("Notti", "it"), H("Pernott.", "it"), H("Nights", "en"), H("Nts", "en"))
ROOM_TYPE_H = (
    H("Tipologia camera", "it"),
    H("Tipo camera", "it"),
    H("Categoria camera", "it"),
    H("Room Type", "en"),
    H("Room Category", "en"),
    H("Accommodation Type", "en"),
)
PLAN_H = (
    H("Piano tariffario", "it"),
    H("Trattamento", "it"),
    H("Rate Plan", "en"),
    H("Rate Code", "en"),
    H("Package", "en"),
)
COMMISSION_H = (
    H("Commissione", "it"),
    H("Comm. OTA", "it"),
    H("Provvigione", "it"),
    H("Commission", "en"),
    H("Commission Amount", "en"),
)
GUEST_NAME_H = (
    H("Ospite", "it"),
    H("Nominativo", "it"),
    H("Cliente", "it"),
    H("Intestatario prenotazione", "it"),
    H("Guest Name", "en"),
    H("Lead Guest", "en"),
    H("Name", "en"),
)
EMAIL_H = (H("E-mail", "any"), H("Email ospite", "it"), H("Guest Email", "en"))
PHONE_H = (
    H("Cellulare", "it"),
    H("Recapito telefonico", "it"),
    H("Mobile", "en"),
    H("Phone No.", "en"),
)
NOTES_H = (
    H("Note", "it"),
    H("Richieste speciali", "it"),
    H("Remarks", "en"),
    H("Special Requests", "en"),
)
JUNK_H = (
    "Sel.",
    "#",
    "Operatore",
    "Rev.",
    "Gruppo",
    "Flag",
    "Cod. interno",
    "Stampato",
    "Ag.",
    "Check",
)


# --- columns --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Style:
    """How the values of a document are written."""

    dates: str = "xl"
    booked: str = "xl"  # xl | iso | it (with a time of day) | a date style
    money: str = "num"
    lang: str = "it"


def core(
    rng: random.Random,
    style: Style,
    *,
    status: bool = True,
    rooms: bool = True,
    pair: tuple[H, H] | None = None,
) -> list[Col]:
    lang = style.lang
    first, second = pair or rng.choice([p for p in STAY_PAIRS if p[0].lang in {"any", lang}])
    cols = [
        Col(pick(rng, ID, lang), lambda s: s.ref, "source_record_id"),
        Col(
            pick(rng, BOOKED, lang),
            lambda s: stamp_cell(s.booked, style.booked),
            "booked_at",
        ),
        Col(first.text, lambda s: date_cell(s.arrival, style.dates), "check_in"),
        Col(second.text, lambda s: date_cell(s.departure, style.dates), "check_out"),
        Col(
            pick(rng, CHANNEL_H, lang),
            lambda s: s.channel_label(lang),
            "channel",
        ),
        Col(
            pick(rng, REVENUE, lang),
            lambda s: money_cell(s.revenue, style.money),
            "room_revenue",
        ),
    ]
    if status:
        cols.append(Col(pick(rng, STATUS_H, lang), lambda s: s.status_label(lang), "status"))
    if rooms:
        cols.append(Col(pick(rng, ROOMS, lang), lambda s: s.rooms, "rooms"))
    return cols


def optional(rng: random.Random, style: Style, count: int) -> list[Col]:
    lang = style.lang
    pool: list[Col] = [
        Col(pick(rng, GUESTS_H, lang), lambda s: s.pax, "guests"),
        Col(pick(rng, ROOM_TYPE_H, lang), lambda s: s.room_type, "room_type"),
        Col(pick(rng, PLAN_H, lang), lambda s: s.plan, "rate_plan"),
        Col(
            pick(rng, COMMISSION_H, lang),
            lambda s: money_cell(round(s.revenue * s.commission / 100, 2), style.money),
            "commission_amount",
        ),
    ]
    rng.shuffle(pool)
    return pool[:count]


def junk(rng: random.Random, count: int) -> list[Col]:
    names = rng.sample(JUNK_H, count)
    cells: list[Callable[[Stay], Any]] = [
        lambda s: None,
        lambda s: s.guest % 7,
        lambda s: "front" + str(s.guest % 3 + 1),
        lambda s: "A" if s.guest % 2 else "B",
    ]
    return [Col(name, rng.choice(cells)) for name in names]


def personal(rng: random.Random, style: Style) -> list[Col]:
    lang = style.lang
    return [
        Col(pick(rng, GUEST_NAME_H, lang), lambda s: guest_name(s.guest), pii=True),
        Col(
            pick(rng, EMAIL_H, lang),
            lambda s: email_of(*guest(s.guest)),
            pii=True,
        ),
        Col(pick(rng, PHONE_H, lang), lambda s: phone_of(s.guest), pii=True),
        Col(pick(rng, NOTES_H, lang), lambda s: "Richiede culla in camera", pii=True),
    ]


def status_labels(items: Sequence[Stay], lang: str) -> dict[str, dict[str, str]]:
    return {
        "status_mapping": {
            STATUS[s][0 if lang == "it" else 1]: s for s in {i.status for i in items}
        }
    }


def ensure_proof(items: list[Stay], style: Style) -> None:
    """Text dates written day-first or month-first prove their order only if some day is above 12
    (a document with only low days is a different case, built on purpose)."""
    del items, style


def formats_of(style: Style) -> dict[str, Any]:
    return {"date_order": order_of(style.dates), "decimal": decimal_of(style.money)}


def preamble_of(rng: random.Random, lang: str, lines: int) -> list[Any]:
    hotel = rng.choice(HOTELS)
    title = "ELENCO PRENOTAZIONI" if lang == "it" else "RESERVATIONS LIST"
    options: list[Any] = [
        ("title", title),
        ("subtitle", f"{hotel} - generato il 24/10/2026"),
        (
            "subtitle",
            "Periodo: ottobre - dicembre 2026" if lang == "it" else "Period: Oct - Dec 2026",
        ),
        ("note", "Dati riservati - uso interno" if lang == "it" else "Internal use only"),
    ]
    return options[:lines]


def sheet_name(rng: random.Random, lang: str) -> str:
    return rng.choice(SHEETS_IT if lang == "it" else SHEETS_EN)


def totals_row(
    cols: Sequence[Col], items: Sequence[Stay], style: Style
) -> Callable[[list[list[Any]]], list[Any]]:
    """A TOTAL line under the records: the label first, the sum under the revenue column."""
    revenue = next(i for i, c in enumerate(cols) if c.field == "room_revenue")

    def wrap(body: list[list[Any]]) -> list[Any]:
        cells: list[Any] = [None] * len(cols)
        cells[0] = "TOTALE" if style.lang == "it" else "TOTAL"
        cells[revenue] = money_cell(sum(s.revenue for s in items), style.money)
        return [*body, Total(cells)]

    return wrap


def document(
    rng: random.Random,
    cols: list[Col],
    items: list[Stay],
    style: Style,
    *,
    name: str,
    outcome: str = "READY",
    csv: dict[str, Any] | None = None,
    **layout: Any,
) -> Built:
    formats = formats_of(style)
    return flat_document(
        "bookings",
        name,
        cols,
        items,
        outcome=outcome,
        csv=csv,
        date_order=layout.pop("date_order", formats["date_order"]),
        decimal=layout.pop("decimal", formats["decimal"]),
        labels=layout.pop("labels", status_labels(items, style.lang)),
        sheet_title=layout.pop("sheet_title", sheet_name(rng, style.lang)),
        **layout,
    )


def pick_style(rng: random.Random, *, text_dates: bool = False, text_money: bool = False) -> Style:
    lang = pick_language(rng)
    dates = (
        rng.choice(("it", "dotted", "iso", "text_it", "text_en", "dash_mon"))
        if text_dates
        else "xl"
    )
    money = (
        rng.choice(("it", "us", "point", "eur_prefix", "eur_suffix", "space_it", "eur_code"))
        if text_money
        else rng.choice(("num", "num", "num_eur", "num_fmt"))
    )
    return Style(dates=dates, booked="xl", money=money, lang=lang)


# ==================================================================================================
# EASY: a clean table the benchmark has never seen
# ==================================================================================================


def easy_xlsx_clean(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(8, 20))
    cols = core(rng, style)
    if maybe(rng, 0.3):
        rng.shuffle(cols)
    return document(rng, cols, items, style, name="export_pms.xlsx")


def easy_csv_semicolon(rng: random.Random) -> Built:
    style = pick_style(rng)
    style.money = "num"
    items = stays(rng, rng.randint(8, 20))
    cols = core(rng, style)
    dates = rng.choice(("it", "iso", "dotted"))
    return document(
        rng,
        cols,
        items,
        style,
        name="prenotazioni.csv",
        csv={"delimiter": ";", "decimal": ",", "dates": dates},
        date_order=order_of(dates),
        decimal=",",
    )


def easy_xlsx_titles(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(8, 18))
    cols = core(rng, style)
    return document(
        rng,
        cols,
        items,
        style,
        name="report_arrivi.xlsx",
        preamble=preamble_of(rng, style.lang, rng.randint(1, 3)),
        left=rng.choice((0, 0, 1)),
    )


# ==================================================================================================
# MEDIUM: aliases, reordering, noise
# ==================================================================================================


def medium_reorder_junk(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 22), statuses=("CONFIRMED", "CONFIRMED", "CANCELLED"))
    cols = [
        *core(rng, style),
        *optional(rng, style, rng.randint(1, 3)),
        *junk(rng, rng.randint(1, 3)),
    ]
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        items,
        style,
        name="elenco_prenotazioni.xlsx",
        preamble=preamble_of(rng, style.lang, rng.randint(0, 2)),
        left=rng.choice((0, 1, 2)),
        wrap=totals_row(cols, items, style) if maybe(rng, 0.6) else None,
    )


def medium_personal_data(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 20))
    cols = [*core(rng, style), *personal(rng, style)[: rng.randint(2, 4)]]
    rng.shuffle(cols)
    return document(rng, cols, items, style, name="arrivi_con_ospiti.xlsx")


def medium_text_formats(rng: random.Random) -> Built:
    style = pick_style(rng, text_dates=True, text_money=True)
    items = stays(rng, rng.randint(12, 24))
    cols = core(rng, style)
    return document(rng, cols, items, style, name="export_testo.xlsx")


def medium_hidden_summary_sheets(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 18))
    cols = core(rng, style)
    sheet = Sheet(sheet_name(rng, style.lang))
    ref = write_table(sheet, headers(cols), records(cols, items))
    old = Sheet("Archivio 2025", hidden=True)
    write_table(old, headers(cols), records(cols, stays(rng, 6, start=date(2025, 11, 3))))
    summary = Sheet("Riepilogo")
    summary.add(["Mese", "Prenotazioni", "Ricavo"], style="header")
    for month in ("Ottobre", "Novembre", "Dicembre"):
        summary.add([month, rng.randint(40, 90), round(rng.uniform(9000, 30000), 2)])
    sheets = [sheet, summary, old] if maybe(rng, 0.5) else [summary, sheet, old]
    meaning = parts(cols, items)
    golden = Golden(
        "bookings",
        "READY",
        **facts(ref, sheets=[sheet.title]),
        fields=meaning["fields"],
        labels=status_labels(items, style.lang),
        date_order=None,
        note="The bookings are on one sheet; a summary and a hidden archive are other documents.",
    )
    return Built("prenotazioni_con_riepilogo.xlsx", xlsx_bytes(sheets), golden, sheets)


def medium_csv_dialects(rng: random.Random) -> Built:
    style = pick_style(rng)
    style.money = "num"
    items = stays(rng, rng.randint(10, 20))
    cols = core(rng, style) + (junk(rng, 1) if maybe(rng, 0.5) else [])
    delimiter = rng.choice((",", "\t", ";"))
    decimal = "." if delimiter in {",", "\t"} else ","
    dates = rng.choice(("iso", "iso", "it", "dotted"))
    return document(
        rng,
        cols,
        items,
        style,
        name="export_prenotazioni.csv",
        csv={"delimiter": delimiter, "decimal": decimal, "dates": dates},
        date_order=order_of(dates),
        decimal=decimal,
    )


# ==================================================================================================
# HARD: more than one table, two-level headers, header deep in the sheet, a total that says nothing
# ==================================================================================================


def hard_decoy_summary_below(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 18))
    cols = core(rng, style)

    def after(sheet: Sheet) -> None:
        sheet.blank(2)
        sheet.add(
            ["Riepilogo per canale" if style.lang == "it" else "Summary by channel"], style="label"
        )
        sheet.add(
            ["Canale", "Prenotazioni", "Ricavo"]
            if style.lang == "it"
            else ["Channel", "Bookings", "Revenue"],
            style="header",
        )
        for key in ("booking", "expedia", "direct", "website"):
            sheet.add(
                [
                    CHANNELS[key][0 if style.lang == "it" else 1],
                    rng.randint(5, 40),
                    round(rng.uniform(900, 9000), 2),
                ]
            )

    return document(rng, cols, items, style, name="prenotazioni_riepilogo.xlsx", after=after)


def hard_two_level_header(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 16))
    cols = core(rng, style)
    ordered = [
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "channel",
        "status",
        "rooms",
        "room_revenue",
    ]
    cols.sort(key=lambda c: ordered.index(c.field or ""))
    groups = {
        "source_record_id": "Prenotazione",
        "booked_at": "Prenotazione",
        "check_in": "Soggiorno",
        "check_out": "Soggiorno",
        "channel": "Vendita",
        "status": "Vendita",
        "rooms": "Importi",
        "room_revenue": "Importi",
    }
    upper = [groups[c.field or ""] for c in cols]
    # an upper-level label only on the first column of its group (the others are merged under it)
    labels: list[str | None] = []
    merges: list[tuple[int, int]] = []
    start = 0
    for index, label in enumerate(upper):
        if index == 0 or label != upper[index - 1]:
            labels.append(label)
            start = index
        else:
            labels.append(None)
            if index == len(upper) - 1 or upper[index + 1] != label:
                merges.append((start + 1, index + 1))
    meaning = parts(cols, items)
    sheet = Sheet(sheet_name(rng, style.lang))
    ref = write_table(sheet, headers(cols), records(cols, items), upper=labels, upper_merges=merges)
    fields = {
        name: column(upper[i], cols[i].header)
        for i, name in enumerate(c.field for c in cols if c.field)
    }
    del meaning
    golden = Golden(
        "bookings",
        "READY",
        **facts(ref),
        fields=fields,
        labels=status_labels(items, style.lang),
        note="Two header lines: groups over the columns.",
    )
    return Built("prenotazioni_gruppi.xlsx", xlsx_bytes([sheet]), golden, [sheet])


def hard_mixed_formats(rng: random.Random) -> Built:
    style = Style(dates="iso", booked="iso", money="eur_suffix", lang=pick_language(rng))
    items = stays(rng, rng.randint(12, 20))
    cols = core(rng, style)
    for index, col in enumerate(cols):
        if col.field == "check_in":
            cols[index] = Col(col.header, lambda s: date_cell(s.arrival, "xl"), "check_in")
        if col.field == "check_out":
            cols[index] = Col(col.header, lambda s: date_cell(s.departure, "dotted"), "check_out")
    return document(rng, cols, items, style, name="export_misto.xlsx", date_order=None, decimal=",")


def hard_sheet_per_month(rng: random.Random) -> Built:
    style = pick_style(rng)
    cols = core(rng, style)
    sheets: list[Sheet] = []
    refs = []
    names = (
        ("Ottobre", "Novembre", "Dicembre")
        if style.lang == "it"
        else ("October", "November", "December")
    )
    month_starts = (date(2026, 10, 14), date(2026, 11, 14), date(2026, 12, 14))
    all_items: list[Stay] = []
    for name, start in zip(names, month_starts, strict=True):
        items = stays(
            rng,
            rng.randint(6, 10),
            start=start,
            spread=25,
            ref_style="res",
            first_index=len(all_items),
        )
        all_items.extend(items)
        sheet = Sheet(name)
        refs.append(write_table(sheet, headers(cols), records(cols, items)))
        sheets.append(sheet)
    merged = refs[0].merged(*refs[1:])
    meaning = parts(cols, [])
    golden = Golden(
        "bookings",
        "READY",
        **facts(merged, sheets=[s.title for s in sheets]),
        fields=meaning["fields"],
        labels=status_labels(all_items, style.lang),
        note="One sheet per month, the same columns: one table.",
    )
    return Built("prenotazioni_mensili.xlsx", xlsx_bytes(sheets), golden, sheets)


def hard_deep_header_kpi_box(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 16))
    cols = core(rng, style)
    sheet = Sheet(sheet_name(rng, style.lang))
    sheet.title_line("REPORT ARRIVI E PARTENZE", 6)
    sheet.pairs(
        [("Hotel", rng.choice(HOTELS)), ("Esportato il", "24/10/2026"), ("Operatore", "front2")]
    )
    sheet.blank()
    sheet.add(["Occupazione", "82%", None, "ADR", 144.0], style="band")
    sheet.add(["RevPAR", 118.0, None, "Notti vendute", 1234], style="band")
    sheet.blank()
    ref = write_table(sheet, headers(cols), records(cols, items))
    meaning = parts(cols, items)
    golden = Golden(
        "bookings",
        "READY",
        **facts(ref),
        fields=meaning["fields"],
        labels=status_labels(items, style.lang),
        note="Label/value lines and a small KPI band above the table.",
    )
    return Built("report_arrivi_kpi.xlsx", xlsx_bytes([sheet]), golden, [sheet])


def hard_ambiguous_total(rng: random.Random) -> Built:
    style = pick_style(rng)
    header = rng.choice(("Total", "Totale", "Importo", "Amount", "Price", "Prezzo"))
    items = stays(rng, rng.randint(10, 18))
    cols = core(rng, style)
    cols = [
        Col(header, c.cell, "room_revenue", ambiguous=True) if c.field == "room_revenue" else c
        for c in cols
    ]
    return document(
        rng,
        cols,
        items,
        style,
        name="export_totale.xlsx",
        outcome="ASK",
        questions=("COLUMN_MEANING",),
        answers={"column_fields": [{"header": [header], "field": "room_revenue"}]},
        note=f"'{header}' alone does not say it is the room revenue (and not a total with extras).",
    )


def hard_ci_co_pair(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 16))
    pair = rng.choice([p for p in STAY_PAIRS if p[0].text in {"CI", "Arr.", "Dal"}])
    cols = core(rng, style, pair=pair)
    return document(rng, cols, items, style, name="export_ci_co.xlsx")


# ==================================================================================================
# ADVERSARIAL: decoys, contradictions, columns that look like something they are not
# ==================================================================================================


def adv_kpi_block_first(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 16))
    cols = core(rng, style)
    sheet = Sheet(sheet_name(rng, style.lang))
    sheet.title_line("DASHBOARD RICAVI OTTOBRE", 5)
    sheet.add(["KPI", "Valore", "Obiettivo"], style="header")
    for label, value, goal in (
        ("Occupazione", "82%", "85%"),
        ("ADR", 144.0, 150.0),
        ("RevPAR", 118.0, 125.0),
        ("Notti vendute", 1234, 1300),
        ("Ricavo camere", 177800.0, 180000.0),
    ):
        sheet.add([label, value, goal])
    sheet.blank(2)
    sheet.add(["Dettaglio prenotazioni"], style="label")
    ref = write_table(sheet, headers(cols), records(cols, items))
    meaning = parts(cols, items)
    golden = Golden(
        "bookings",
        "READY",
        **facts(ref),
        fields=meaning["fields"],
        labels=status_labels(items, style.lang),
        note="A KPI table comes first; the bookings are the table below it.",
    )
    return Built("dashboard_prenotazioni.xlsx", xlsx_bytes([sheet]), golden, [sheet])


def adv_reversed_dates(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 16))
    cols = core(rng, style)
    swapped: list[Col] = []
    for col in cols:
        if col.field == "check_in":
            swapped.append(
                Col(
                    col.header,
                    lambda s: date_cell(s.departure, style.dates),
                    "check_in",
                    ambiguous=True,
                )
            )
        elif col.field == "check_out":
            swapped.append(
                Col(
                    col.header,
                    lambda s: date_cell(s.arrival, style.dates),
                    "check_out",
                    ambiguous=True,
                )
            )
        else:
            swapped.append(col)
    return document(
        rng,
        swapped,
        items,
        style,
        name="export_date_invertite.xlsx",
        outcome="NOT_AUTOMATIC",
        questions=("DATES_REVERSED",),
        note="The arrival is after the departure on every row: never swapped silently.",
    )


def adv_country_as_source(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 18))
    countries = ("Italia", "Germania", "Francia", "Regno Unito", "Paesi Bassi", "Svizzera")
    header = rng.choice(("Provenienza", "Origine", "Source", "Origin"))
    cols = [c for c in core(rng, style) if c.field != "channel"]
    cols.insert(
        rng.randint(0, len(cols)),
        Col(header, lambda s: countries[s.guest % len(countries)], None, junk=True),
    )
    return document(
        rng,
        cols,
        items,
        style,
        name="export_nazionalita.xlsx",
        outcome="NOT_AUTOMATIC",
        absent=("channel",),
        note=f"'{header}' is the guests' country, not the sales channel: there is no channel.",
    )


def adv_id_is_a_group(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(12, 20))
    cols = [c for c in core(rng, style) if c.field != "source_record_id"]
    groups = ("Gruppo A", "Gruppo B", "Convegno X")
    cols.insert(
        0,
        Col(
            rng.choice(("Rif.", "Cod. gruppo", "Pratica", "Rif. cliente")),
            lambda s: groups[s.guest % 3],
        ),
    )
    return document(
        rng,
        cols,
        items,
        style,
        name="export_gruppi.xlsx",
        outcome="NOT_AUTOMATIC",
        absent=("source_record_id",),
        note="The only reference repeats (a group): it is not a booking code.",
    )


def adv_kpi_report_as_bookings(rng: random.Random) -> Built:
    sheet = Sheet("Occupazione")
    sheet.title_line("ANDAMENTO GIORNALIERO", 5)
    sheet.blank()
    body = []
    for offset in range(28):
        day = date(2026, 10, 1) + timedelta(days=offset)
        body.append(
            [
                datetime(day.year, day.month, day.day),
                round(rng.uniform(55, 98), 1),
                round(rng.uniform(95, 190), 2),
                round(rng.uniform(70, 160), 2),
                rng.randint(20, 60),
            ]
        )
    ref = write_table(sheet, ["Data", "Occ. %", "ADR", "RevPAR", "Camere vendute"], body)
    golden = Golden(
        "other",
        "REJECT",
        **facts(ref),
        note="A daily KPI table: no booking in it.",
    )
    return Built("andamento_giornaliero.xlsx", xlsx_bytes([sheet]), golden, [sheet])


def adv_decoy_columns(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 18))
    cols = core(rng, style)
    decoys = [
        Col(
            "Ultimo aggiornamento",
            lambda s: date_cell(s.booked.date() + timedelta(days=1), style.dates),
        ),
        Col(
            "Data pagamento acconto",
            lambda s: date_cell(s.arrival - timedelta(days=9), style.dates),
        ),
        Col(
            "Data emissione fattura",
            lambda s: date_cell(s.departure + timedelta(days=3), style.dates),
        ),
    ]
    cols = [*cols, *rng.sample(decoys, 2)]
    rng.shuffle(cols)
    return document(
        rng,
        cols,
        items,
        replace(style, lang="it"),
        name="export_con_date_extra.xlsx",
        note="Other dates (a change, a payment, an invoice) are not the booking date or the stay.",
    )


def adv_net_after_commission(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(10, 18), channels=("booking", "expedia", "airbnb"))
    cols = core(rng, style)
    cols.append(
        Col(
            "Commissione OTA",
            lambda s: money_cell(round(s.revenue * s.commission / 100, 2), style.money),
            "commission_amount",
        )
    )
    cols.append(
        Col(
            "Netto dopo commissioni",
            lambda s: money_cell(round(s.revenue * (1 - s.commission / 100), 2), style.money),
        )
    )
    return document(
        rng,
        cols,
        items,
        replace(style, lang="it"),
        name="export_commissioni.xlsx",
        note="The revenue is the room revenue; the net after commissions is a derived column.",
    )


def adv_ambiguous_date_order(rng: random.Random) -> Built:
    style = Style(dates="it", booked="xl", money="num", lang=pick_language(rng))
    items = stays(rng, rng.randint(10, 14), start=date(2026, 10, 1), spread=10)
    items = [
        Stay(
            s.ref,
            datetime.combine(date(2026, 9, 2 + (i % 8)), datetime.min.time()),
            date(2026, 10, 2 + (i % 9)),
            s.nights if s.nights <= 2 else 2,
            s.channel,
            s.revenue,
            s.status,
            s.rooms,
            s.guest,
            s.pax,
            s.room_type,
            s.plan,
            s.commission,
        )
        for i, s in enumerate(items)
    ]
    cols = core(rng, style)
    cols = [
        Col(c.header, lambda s: date_cell(s.booked.date(), "it"), "booked_at")
        if c.field == "booked_at"
        else c
        for c in cols
    ]
    return document(
        rng,
        cols,
        items,
        style,
        name="export_date_ambigue.xlsx",
        outcome="ASK",
        questions=("DATE_ORDER",),
        answers={"date_order": "DMY"},
        date_order="DMY",
        note="Every day is 12 or less: 03/10 can be the 3rd of October or the 10th of March.",
    )


def adv_staff_under_a_booking_title(rng: random.Random) -> Built:
    sheet = Sheet("Prenotazioni")
    sheet.title_line("PRENOTAZIONI TURNI SALA", 5)
    sheet.blank()
    body = []
    for offset in range(14):
        day = date(2026, 10, 19) + timedelta(days=offset % 7)
        body.append(
            [
                datetime(day.year, day.month, day.day),
                rng.choice(("Sala", "Bar", "Cucina")),
                rng.choice((6, 7, 8)),
                rng.choice((6, 7, 7.5, 8)),
            ]
        )
    ref = write_table(sheet, ["Data", "Reparto", "Ore previste", "Ore effettive"], body)
    golden = Golden(
        "labor",
        "NOT_AUTOMATIC",
        **facts(ref),
        tolerated=("DOMAIN",),
        note="The sheet and the title say bookings; the columns and the values are staff hours.",
    )
    return Built("prenotazioni_turni.xlsx", xlsx_bytes([sheet]), golden, [sheet], card="bookings")


def adv_data_on_a_hidden_sheet(rng: random.Random) -> Built:
    style = pick_style(rng)
    items = stays(rng, rng.randint(8, 14))
    cols = core(rng, style)
    visible = Sheet("LEGGIMI")
    visible.add(["Questo file contiene i dati prenotazioni nel foglio nascosto 'Dati'."])
    hidden = Sheet("Dati", hidden=True)
    write_table(hidden, headers(cols), records(cols, items))
    # (no table facts: the product does not read a hidden sheet, so the right answer is a refusal)
    golden = Golden(
        "bookings",
        "NOT_AUTOMATIC",
        data_rows=0,
        note="The records are on a hidden sheet: nothing is imported without a person.",
    )
    return Built(
        "prenotazioni_nascoste.xlsx", xlsx_bytes([visible, hidden]), golden, [visible, hidden]
    )


RECIPES: dict[str, Sequence[Maker]] = {
    "EASY": (easy_xlsx_clean, easy_csv_semicolon, easy_xlsx_titles),
    "MEDIUM": (
        medium_reorder_junk,
        medium_personal_data,
        medium_text_formats,
        medium_hidden_summary_sheets,
        medium_csv_dialects,
    ),
    "HARD": (
        hard_decoy_summary_below,
        hard_two_level_header,
        hard_mixed_formats,
        hard_sheet_per_month,
        hard_deep_header_kpi_box,
        hard_ambiguous_total,
        hard_ci_co_pair,
    ),
    "ADVERSARIAL": (
        adv_kpi_block_first,
        adv_reversed_dates,
        adv_country_as_source,
        adv_id_is_a_group,
        adv_kpi_report_as_bookings,
        adv_decoy_columns,
        adv_net_after_commission,
        adv_ambiguous_date_order,
        adv_staff_under_a_booking_title,
        adv_data_on_a_hidden_sheet,
    ),
}


def build() -> list[Doc]:
    return assemble("UB", "bookings", RECIPES)


__all__ = ["RECIPES", "build", "csv_bytes", "Note"]
